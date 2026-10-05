"""Extraction de features sur fenêtre glissante (cœur du modèle prédictif).

On ne regarde pas une valeur isolée : on décrit la *dynamique* de la fenêtre
(pente, variabilité, corrélation T°/gaz...), ce qui permet de détecter une
dérive lente avant qu'elle n'atteigne un seuil critique.
"""
import numpy as np
import pandas as pd

from .config import CHANNELS, STEP, WINDOW_SIZE


def _slope(v: np.ndarray) -> float:
    x = np.arange(len(v), dtype=float)
    x -= x.mean()
    return float((x * (v - v.mean())).sum() / (x ** 2).sum())


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() < 1e-9 or b.std() < 1e-9:   # capteur figé -> pas de corrélation calculable
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


FEATURE_NAMES = (
    [f"{c}_{s}" for c in CHANNELS for s in ("mean", "std", "slope", "range", "maxdiff")]
    + ["temp_gas_corr", "temp_hum_corr", "pir_ratio"]
)


def window_features(w: pd.DataFrame) -> np.ndarray:
    f = []
    for c in CHANNELS:
        v = w[c].to_numpy(float)
        # variabilité en échelle log : un capteur figé (std ~ 0) devient très atypique
        f += [v.mean(), np.log(v.std() + 1e-3), _slope(v), v.max() - v.min(),
              np.log(np.abs(np.diff(v)).max() + 1e-3)]
    t, h, g = (w[c].to_numpy(float) for c in ("temperature", "humidity", "gas"))
    f += [_corr(t, g), _corr(t, h), float(w["pir"].mean())]
    return np.asarray(f)


def build_dataset(df: pd.DataFrame, window=WINDOW_SIZE, step=STEP):
    """Retourne X (n_fenêtres, n_features), y, end_idx (indice de la dernière mesure).
    y = 1 si >=50% de la fenêtre est anormale, 0 si 100% normale, -1 si ambiguë
    (fenêtre à cheval sur le début/fin d'une anomalie -> exclue des métriques)."""
    X, y, ends = [], [], []
    has_label = "label" in df.columns
    for end in range(window, len(df) + 1, step):
        w = df.iloc[end - window:end]
        X.append(window_features(w))
        ends.append(end - 1)
        if has_label:
            r = w["label"].mean()
            y.append(1 if r >= 0.5 else 0 if r == 0 else -1)
    return np.vstack(X), (np.asarray(y) if has_label else None), np.asarray(ends)
