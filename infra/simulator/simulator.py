"""Sentinel-X — Simulateur de l'ESP8266.

Publie de fausses mesures capteurs sur Mosquitto, au même format que le
vrai firmware, et réagit aux commandes comme le ferait le boîtier.

Topics :
    sentinel/capteurs   ← mesures publiées (JSON)
    sentinel/etat       ← état du boîtier (retained, + testament "offline")
    sentinel/commandes  → ordres reçus (buzzer, LED)
    sentinel/config     → activation des capteurs, fréquence

Usage :
    python simulator.py                            # scénario normal
    python simulator.py --scenario surchauffe      # incident après 30 s
    python simulator.py --scenario mix --csv data.csv
    python simulator.py --fast --duration 7200 --csv normal.csv   # dataset hors ligne

Les dérives sont exprimées par minute de temps simulé (indépendantes de
--interval) et bornées aux plages physiques des capteurs.
"""

import argparse
import csv
import json
import math
import random
import signal
import time
from pathlib import Path

import paho.mqtt.client as mqtt

DEVICE = "sentinel-01"
T_CAPTEURS = "sentinel/capteurs"
T_ETAT = "sentinel/etat"
T_COMMANDES = "sentinel/commandes"
T_CONFIG = "sentinel/config"

# Vitesses de dérive (par minute de temps simulé) et bornes physiques
TEMP_RATE = 0.3        # °C/min : surchauffe lente (local technique mal ventilé)
TEMP_DRIFT_MAX = 38.0  # la température plafonne vers 60 °C (DHT22 : -40..80 °C)
GAZ_LEAK_RATE = 60.0   # unités ADC/min : fuite franche
GAZ_MICRO_RATE = 3.0   # unités ADC/min : micro-dérive corrélée de l'incident
GAZ_MICRO_MAX = 150.0
RETOUR_S = 120.0       # constante de temps du retour à la normale

# mix : (phase, durée en s), en boucle après --start-after
CYCLE_MIX = [("incident", 300), ("normal", 180), ("intrusion", 60), ("normal", 120)]

SCENARIOS = {
    "normal": "valeurs stables avec bruit, passages rares",
    "surchauffe": "la température monte lentement (+0,3 °C/min, plafond ~60 °C)",
    "fuite_gaz": "le gaz monte (+60 /min) jusqu'à saturation (1023)",
    "incident": "+0,3 °C/min + micro-dérive du gaz +3 /min (cas du sujet)",
    "intrusion": "présence continue détectée par le PIR",
    "panne": "le boîtier cesse d'émettre (perte de connexion)",
    "mix": "enchaîne incident 5 min → normal 3 min → intrusion 1 min → normal 2 min",
}


def parse_args():
    p = argparse.ArgumentParser(description="Simulateur ESP8266 Sentinel-X")
    p.add_argument("--host", default="localhost", help="adresse du broker (défaut : localhost)")
    p.add_argument("--port", type=int, default=1883, help="port du broker (défaut : 1883)")
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--start-after", type=float, default=30, help="secondes de normal avant l'incident (défaut : 30)")
    p.add_argument("--interval", type=float, default=2.0, help="secondes entre deux mesures (défaut : 2)")
    p.add_argument("--duration", type=float, default=0, help="arrêt après N secondes (0 = infini)")
    p.add_argument("--csv", type=Path, help="enregistre aussi les mesures dans ce fichier CSV")
    p.add_argument("--fast", action="store_true",
                   help="génération de dataset : temps simulé, sans attente ni MQTT (exige --csv)")
    p.add_argument("--seed", type=int, help="graine aléatoire pour reproduire un run")
    return p.parse_args()


class Boitier:
    """État simulé du boîtier : capteurs, actionneurs, configuration."""

    def __init__(self, interval):
        self.config = {"dht22": True, "mq2": True, "pir": True, "interval_ms": int(interval * 1000)}
        self.buzzer = False
        self.led = "vert"
        self.temp_drift = 0.0
        self.gaz_drift = 0.0

    def phase(self, scenario, elapsed, start_after):
        """Renvoie le comportement actif à cet instant."""
        if scenario == "normal" or elapsed < start_after:
            return "normal"
        if scenario != "mix":
            return scenario
        t = (elapsed - start_after) % sum(d for _, d in CYCLE_MIX)
        for name, duree in CYCLE_MIX:
            if t < duree:
                return name
            t -= duree
        return "normal"

    def mesure(self, phase, t, dt, ts):
        """t : secondes de temps simulé depuis le départ, dt : secondes depuis la mesure précédente."""
        # Base normale : légère oscillation (cycle jour/nuit compressé, ~8 et ~11 min) + bruit
        temp = 22.0 + 0.6 * math.sin(t / 80) + random.gauss(0, 0.15)
        hum = 45.0 + 2.0 * math.sin(t / 110) + random.gauss(0, 0.6)
        gaz = 300 + random.gauss(0, 6)
        presence = random.random() < 0.02  # passage rare

        minutes = dt / 60
        retour = math.exp(-dt / RETOUR_S)  # décroissance exponentielle vers la normale
        if phase in ("surchauffe", "incident"):
            self.temp_drift = min(TEMP_DRIFT_MAX, self.temp_drift + TEMP_RATE * minutes)
        else:
            self.temp_drift *= retour
        if phase == "fuite_gaz":
            self.gaz_drift = min(1023.0 - 300, self.gaz_drift + GAZ_LEAK_RATE * minutes)
        elif phase == "incident":
            self.gaz_drift = min(GAZ_MICRO_MAX, self.gaz_drift + GAZ_MICRO_RATE * minutes)
        else:
            self.gaz_drift *= retour
        if phase == "intrusion":
            presence = random.random() < 0.9

        temp += self.temp_drift
        hum -= self.temp_drift * 0.4  # l'air chaud s'assèche
        gaz = max(0, min(1023, gaz + self.gaz_drift))  # entrée analogique 10 bits

        return {
            "device": DEVICE,
            "temp": round(temp, 1) if self.config["dht22"] else None,
            "hum": round(max(0, min(100, hum)), 1) if self.config["dht22"] else None,
            "gaz": int(gaz) if self.config["mq2"] else None,
            "presence": presence if self.config["pir"] else None,
            "ts": int(ts),
        }


def connecter(args, boitier):
    """Client MQTT du boîtier simulé : publie l'état, applique commandes et configuration."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{DEVICE}-sim")
    # Testament : si le simulateur meurt, le broker annonce "offline"
    client.will_set(T_ETAT, json.dumps({"device": DEVICE, "online": False}), qos=1, retain=True)

    def publier_etat():
        etat = {"device": DEVICE, "online": True, "simule": True,
                "config": boitier.config, "buzzer": boitier.buzzer, "led": boitier.led}
        client.publish(T_ETAT, json.dumps(etat), qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[MQTT] connexion refusée : {reason_code}")
            return
        print(f"[MQTT] connecté à {args.host}:{args.port}")
        c.subscribe([(T_COMMANDES, 1), (T_CONFIG, 1)])
        publier_etat()

    def on_message(c, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except json.JSONDecodeError:
            print(f"[!] message ignoré (JSON invalide) sur {msg.topic}")
            return
        if msg.topic == T_COMMANDES:
            if "buzzer" in data:
                boitier.buzzer = bool(data["buzzer"])
                print(f"🔔 BUZZER {'ON' if boitier.buzzer else 'OFF'}")
            if data.get("led") in ("vert", "rouge"):
                boitier.led = data["led"]
                print(f"💡 LED {boitier.led.upper()}")
        elif msg.topic == T_CONFIG:
            for key in ("dht22", "mq2", "pir"):
                if key in data:
                    boitier.config[key] = bool(data[key])
            if isinstance(data.get("interval_ms"), int) and data["interval_ms"] >= 500:
                boitier.config["interval_ms"] = data["interval_ms"]
            print(f"⚙️  config : {boitier.config}")
        publier_etat()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()
    return client


def main():
    args = parse_args()
    if args.fast and not args.csv:
        raise SystemExit("--fast génère un dataset hors ligne : préciser --csv fichier.csv")
    if args.seed is not None:
        random.seed(args.seed)

    boitier = Boitier(args.interval)
    # --fast : dataset hors ligne, rien n'est publié (sinon l'API enregistrerait des
    # heures de mesures en quelques secondes, toutes horodatées « maintenant »)
    client = None if args.fast else connecter(args, boitier)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    writer = None
    csv_file = None
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        csv_file = args.csv.open("w", newline="")
        writer = csv.DictWriter(csv_file, fieldnames=["ts", "temp", "hum", "gaz", "presence", "phase"])
        writer.writeheader()

    print(f"Scénario « {args.scenario} » : {SCENARIOS[args.scenario]}. Ctrl+C pour arrêter.")
    start = time.time()
    step = 0
    prev = 0.0
    last_phase = None
    try:
        while running:
            # --fast : temps simulé (start + step * interval) ; sinon temps réel
            elapsed = step * args.interval if args.fast else time.time() - start
            if args.duration and elapsed >= args.duration:
                break
            phase = boitier.phase(args.scenario, elapsed, args.start_after)
            if phase != last_phase:
                print(f"--- phase : {phase} ---")
                last_phase = phase

            if phase == "panne":
                # Coupure brutale : le testament "offline" sera publié par le broker
                print("✖ panne simulée : arrêt des émissions")
                if client:
                    client._sock_close()
                break

            dt = elapsed - prev if step else args.interval
            prev = elapsed
            data = boitier.mesure(phase, elapsed, dt, start + elapsed)
            if writer:
                # ts au dixième de seconde : reste croissant même avec --interval < 1
                writer.writerow({**{k: data[k] for k in ("temp", "hum", "gaz", "presence")},
                                 "ts": round(start + elapsed, 1), "phase": phase})
            if client:
                client.publish(T_CAPTEURS, json.dumps(data), qos=0)
                print(f"→ temp={data['temp']} hum={data['hum']} gaz={data['gaz']} presence={data['presence']}")

            step += 1
            if not args.fast:
                time.sleep(boitier.config["interval_ms"] / 1000)
    finally:
        if csv_file:
            csv_file.close()
            print(f"{step} mesures écrites dans {args.csv}")
        if client:
            if last_phase != "panne":
                client.publish(T_ETAT, json.dumps({"device": DEVICE, "online": False}),
                               qos=1, retain=True).wait_for_publish(2)
                client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
