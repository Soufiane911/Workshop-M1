"""Sentinel-X — Détection d'anomalies en continu (Isolation Forest).

S'abonne à sentinel/capteurs, calcule les features sur une fenêtre glissante,
note chaque mesure et publie l'état à l'API.

Score 0..1 : d = min(decision de l'Isolation Forest, decision de l'enveloppe
elliptique), chacune > 0 = normal, < 0 = anomalie, 0 = frontière apprise
(fixée par `contamination`). Pour l'enveloppe, d = 0,1 × (m² seuil − m²) / m² seuil
avec m² la distance de Mahalanobis au carré. Puis
    score = 1 / (1 + exp(PENTE * d))        avec PENTE = 20
-> d = 0 donne 0,5 ; d = -0,1 donne 0,88 ; d = +0,1 donne 0,12.

États : normal (score < SEUIL_DERIVE), derive (score élevé), anomalie (score
élevé sur N fenêtres consécutives, défaut 3).

Usage :
    python detector.py
    python detector.py --api http://localhost:8000/api/v1 --mqtt-host localhost
"""

import argparse
import json
import math
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import joblib
import numpy as np

import features as ft

T_CAPTEURS = "sentinel/capteurs"
PENTE = 20.0          # raideur de la sigmoïde (voir docstring)
SEUIL_DERIVE = 0.5    # score >= seuil : fenêtre jugée anormale
SEUIL_CRITIQUE = 0.9  # score très élevé -> alerte « critical »
SORTIE = 3            # mesures normales consécutives pour quitter « anomalie »
COOLDOWN = 60.0       # secondes entre deux alertes
MODELE = Path(__file__).parent / "model.joblib"


def score_depuis_decision(d):
    return float(1.0 / (1.0 + math.exp(max(-50, min(50, PENTE * d)))))


def _fr(x, nd=2):
    return f"{x:+.{nd}f}".replace(".", ",")


def _fr_abs(x, nd=2):
    return f"{x:.{nd}f}".replace(".", ",")


def expliquer(f, z, z_min=2.0):
    """Phrase française à partir des features qui s'écartent le plus de l'entraînement.

    f : features courantes, z : z-scores (dict) vs statistiques d'entraînement.
    """
    ok = {k: v for k, v in z.items() if not math.isnan(v)}
    ordre = sorted(ok, key=lambda k: -abs(ok[k]))
    # « instable » est redondant si la pente ou la moyenne du même capteur est déjà citée
    cites = [k for k in ordre if abs(ok[k]) >= z_min][:5] or ordre[:1]
    for capteur in ("temp", "gaz"):
        if f"{capteur}_slope" in cites or f"{capteur}_mean" in cites:
            cites = [k for k in cites if k != f"{capteur}_std"]
    phrases, vus = [], set()
    for k in cites[:3]:
        up = ok[k] > 0
        if k == "temp_slope":
            p = f"température en {'hausse' if up else 'baisse'} ({_fr(f[k])} °C/min)"
        elif k == "gaz_slope":
            p = f"gaz en {'hausse' if up else 'baisse'} ({_fr(f[k], 1)} /min)"
        elif k == "hum_slope":
            p = f"humidité en {'hausse' if up else 'baisse'} ({_fr(f[k], 1)} %/min)"
        elif k == "temp_mean":
            p = f"température moyenne {'élevée' if up else 'basse'} ({_fr_abs(f[k], 1)} °C)"
        elif k == "gaz_mean":
            p = f"niveau de gaz {'élevé' if up else 'bas'} ({_fr_abs(f[k], 0)})"
        elif k == "temp_std":
            p = "température instable" if up else "température anormalement figée"
        elif k == "gaz_std":
            p = "gaz instable" if up else "gaz anormalement figé"
        elif k == "corr_temp_gaz":
            c = f[k]
            p = f"température et gaz {'corrélés' if c > 0 else 'anti-corrélés'} ({_fr_abs(c)})"
        else:
            continue
        if k not in vus:
            vus.add(k)
            phrases.append(p)
    if not phrases:
        return "comportement inhabituel des capteurs"
    # la corrélation se lit mieux en fin de phrase : « ... et gaz en hausse, corrélés (0,92) »
    corr = [p for p in phrases if p.startswith("température et gaz")]
    autres = [p for p in phrases if p not in corr]
    if corr and any(p.startswith(("température en", "gaz en")) for p in autres):
        c = f["corr_temp_gaz"]
        corr = [f"{'corrélés' if c > 0 else 'anti-corrélés'} ({_fr_abs(c)})"]
    txt = " et ".join([", ".join(autres[:-1]), autres[-1]] if len(autres) > 1 else autres) if autres else ""
    if corr:
        txt = f"{txt}, {corr[0]}" if txt else corr[0]
    txt = txt[0].upper() + txt[1:]
    return txt[:300]


class Analyseur:
    """Fenêtre glissante + modèle + machine à états. Utilisé par le service et evaluate.py."""

    def __init__(self, model_path=MODELE, window=None, consecutive=3):
        data = joblib.load(model_path)
        self.pipe, self.meta = data["pipeline"], data["meta"]
        self.envelope = data.get("envelope")  # absent des modèles plus anciens
        self.window = window or self.meta["window"]
        self.consecutive = consecutive
        self.mean = np.array(self.meta["feat_mean"])
        self.std = np.maximum(np.array(self.meta["feat_std"]), 1e-6)
        self.buf = deque(maxlen=self.window)
        self.streak = 0
        self.calme = 0
        self.state = "normal"

    def push(self, t, temp, hum, gaz):
        """Ajoute une mesure. Renvoie None tant que la fenêtre n'est pas pleine, sinon un dict résultat."""
        self.buf.append((t, temp, hum, gaz))
        if len(self.buf) < self.window:
            return None
        f = ft.calculer(list(self.buf))
        x = np.array([ft.vecteur(f)], dtype=float)
        d = float(self.pipe.decision_function(x)[0])
        if self.envelope is not None:
            seuil = self.meta["envelope_mahal2"]
            m2 = float(self.envelope.mahalanobis(self.pipe[:-1].transform(x))[0])
            d = min(d, 0.1 * (seuil - m2) / seuil)
        score = score_depuis_decision(d)

        if score >= SEUIL_DERIVE:
            self.streak += 1
            self.calme = 0
        else:
            self.streak = 0
            self.calme += 1

        if self.streak >= self.consecutive:
            self.state = "anomalie"
        elif self.state == "anomalie" and self.calme < SORTIE:
            pass  # on reste en anomalie jusqu'à SORTIE mesures normales
        elif self.streak >= 1:
            self.state = "derive"
        else:
            self.state = "normal"

        z = {k: float((v - m) / s) if not math.isnan(v) else float("nan")
             for k, v, m, s in zip(ft.FEATURES, x[0], self.mean, self.std)}
        expl = expliquer(f, z) if self.state != "normal" else "Fonctionnement normal"
        return {"state": self.state, "score": score, "decision": d, "features": f, "z": z,
                "explanation": expl}


class Poster:
    """POST JSON dans un thread ; les erreurs sont affichées au plus toutes les 30 s par route."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.derniere_erreur = {}

    def post(self, route, payload):
        threading.Thread(target=self._post, args=(route, payload), daemon=True).start()

    def _post(self, route, payload):
        try:
            req = urllib.request.Request(
                f"{self.base}{route}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3).close()
            self.derniere_erreur.pop(route, None)
        except Exception as e:
            now = time.monotonic()
            if now - self.derniere_erreur.get(route, -1e9) > 30:
                print(f"[API] échec de l'envoi sur {route} : {e}")
                self.derniere_erreur[route] = now


def propre(f):
    """Features sérialisables (NaN -> None, arrondis)."""
    return {k: (None if math.isnan(v) else round(v, 3)) for k, v in f.items()}


def main():
    p = argparse.ArgumentParser(description="Détection d'anomalies Sentinel-X")
    p.add_argument("--api", default="http://localhost:8000/api/v1", help="base de l'API (défaut : http://localhost:8000/api/v1)")
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--model", type=Path, default=MODELE)
    p.add_argument("--window", type=int, default=None, help="taille de fenêtre (défaut : celle du modèle)")
    p.add_argument("--consecutive", type=int, default=3, help="fenêtres anormales consécutives avant « anomalie » (défaut : 3)")
    args = p.parse_args()

    import paho.mqtt.client as mqtt

    an = Analyseur(args.model, args.window, args.consecutive)
    api = Poster(args.api)
    dernier_etat = {"v": "normal", "alerte": -1e9}
    print(f"Modèle chargé ({an.meta['training_rows']} fenêtres, fenêtre {an.window}, "
          f"entraîné le {an.meta['date']}).")

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[MQTT] connexion refusée : {reason_code}")
            return
        print(f"[MQTT] connecté à {args.mqtt_host}:{args.mqtt_port}")
        c.subscribe(T_CAPTEURS, qos=0)

    def on_message(c, userdata, msg):
        try:
            m = json.loads(msg.payload)
            r = an.push(time.time(), m.get("temp"), m.get("hum"), m.get("gaz"))
        except Exception as e:
            print(f"[!] mesure ignorée : {e}")
            return
        if r is None:
            return
        feats = propre(r["features"])
        api.post("/analysis", {
            "state": r["state"], "score": round(r["score"], 3),
            "explanation": r["explanation"], "features": feats, "model": "isolation_forest",
        })
        if r["state"] != dernier_etat["v"]:
            print(f"[état] {dernier_etat['v']} -> {r['state']} (score {r['score']:.2f}) {r['explanation']}")
            entree = r["state"] == "anomalie"
            dernier_etat["v"] = r["state"]
            now = time.monotonic()
            if entree and now - dernier_etat["alerte"] >= COOLDOWN:
                dernier_etat["alerte"] = now
                api.post("/alerts", {
                    "source": "anomalie", "type": "derive_environnement",
                    "level": "critical" if r["score"] >= SEUIL_CRITIQUE else "warning",
                    "message": r["explanation"], "score": round(r["score"], 3), "features": feats,
                })
                print("[alerte] dérive d'environnement signalée")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel-anomalies")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
    print("Détecteur lancé. Ctrl+C pour arrêter.")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
