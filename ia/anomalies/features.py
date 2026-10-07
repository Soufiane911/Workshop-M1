"""Sentinel-X — Extraction de features sur fenêtre glissante.

Une fenêtre = les N dernières mesures (défaut 30, soit ~1 min à 2 s/mesure).
Chaque mesure est un tuple (t, temp, hum, gaz) ; t en secondes, un capteur
désactivé vaut None (ou NaN).

Capteur absent / trop peu de points valides : la feature vaut NaN. Le pipeline
d'entraînement remplace les NaN par la moyenne d'entraînement (SimpleImputer),
donc une valeur « neutre » qui n'influence pas le score.
"""

import csv
import math
from pathlib import Path

import numpy as np

WINDOW = 30
MIN_POINTS = 5  # en dessous, la pente / la corrélation n'ont pas de sens
INTERVAL = 2.0  # secondes entre deux mesures (reconstitution du temps)

FEATURES = [
    "temp_mean", "temp_slope", "temp_std",
    "hum_slope",
    "gaz_mean", "gaz_slope", "gaz_std",
    "corr_temp_gaz",
]


def _valide(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _pente(t, y):
    """Pente des moindres carrés, en unités par minute."""
    t = t - t.mean()
    den = float((t * t).sum())
    if den == 0:
        return 0.0
    return float((t * (y - y.mean())).sum() / den) * 60.0


def _corr(a, b):
    if a.std() == 0 or b.std() == 0:
        return 0.0
    c = float(np.corrcoef(a, b)[0, 1])
    return 0.0 if math.isnan(c) else c


def calculer(fenetre):
    """fenetre : liste de (t, temp, hum, gaz) -> dict {feature: valeur (ou NaN)}."""
    nan = float("nan")
    f = {k: nan for k in FEATURES}
    t = np.array([m[0] for m in fenetre], dtype=float)

    def serie(i):
        ok = np.array([_valide(m[i]) for m in fenetre])
        if ok.sum() < MIN_POINTS:
            return None, None
        return t[ok], np.array([m[i] for m in fenetre], dtype=object)[ok].astype(float)

    tt, temp = serie(1)
    th, hum = serie(2)
    tg, gaz = serie(3)
    if temp is not None:
        f["temp_mean"], f["temp_std"] = float(temp.mean()), float(temp.std())
        f["temp_slope"] = _pente(tt, temp)
    if hum is not None:
        f["hum_slope"] = _pente(th, hum)
    if gaz is not None:
        f["gaz_mean"], f["gaz_std"] = float(gaz.mean()), float(gaz.std())
        f["gaz_slope"] = _pente(tg, gaz)
    if temp is not None and gaz is not None:
        # corrélation sur les instants où les deux capteurs ont répondu
        ok = np.array([_valide(m[1]) and _valide(m[3]) for m in fenetre])
        if ok.sum() >= MIN_POINTS:
            a = np.array([m[1] for m in fenetre], dtype=object)[ok].astype(float)
            b = np.array([m[3] for m in fenetre], dtype=object)[ok].astype(float)
            f["corr_temp_gaz"] = _corr(a, b)
    return f


def vecteur(f):
    return [f[k] for k in FEATURES]


def lire_csv(chemin, interval=INTERVAL, use_ts=False):
    """Lit un CSV du simulateur -> liste de (t, temp, hum, gaz) + liste des phases.

    Par défaut le temps est reconstitué (i * interval) : les pentes ne dépendent
    pas de la gigue d'horodatage. --use-ts utilise la colonne ts (données réelles
    du boîtier, ou CSV du simulateur, dont le ts est en temps simulé).
    """
    def num(s):
        return float(s) if s not in ("", None, "None") else None

    mesures, phases = [], []
    with Path(chemin).open(newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            t = float(row["ts"]) if use_ts else i * interval
            mesures.append((t, num(row["temp"]), num(row["hum"]), num(row["gaz"])))
            phases.append(row.get("phase", "normal"))
    return mesures, phases


def matrice(mesures, window=WINDOW):
    """Features de chaque fenêtre complète -> (X, index de la dernière mesure)."""
    X, idx = [], []
    for i in range(window - 1, len(mesures)):
        X.append(vecteur(calculer(mesures[i - window + 1:i + 1])))
        idx.append(i)
    return np.array(X, dtype=float), idx
