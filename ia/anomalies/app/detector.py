"""Détecteur temps réel : on lui pousse les mesures une par une."""
from collections import deque
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from .config import CONSECUTIVE, MODEL_PATH, STEP, WINDOW_SIZE
from .features import FEATURE_NAMES, window_features

REQUIRED = ("temperature", "humidity", "gas", "pir")


class AnomalyDetector:
    def __init__(self, model_path=MODEL_PATH, consecutive=CONSECUTIVE):
        b = joblib.load(model_path)
        self.pipe = b["pipeline"]
        self.warning = b["warning_threshold"]
        self.critical = b["critical_threshold"]
        self.consecutive = consecutive
        self.buf = deque(maxlen=WINDOW_SIZE)
        self.count = 0
        self.streak = 0

    def push(self, sample: dict) -> Optional[dict]:
        """Ajoute une mesure. Retourne un résultat tous les STEP échantillons
        (une fois la fenêtre pleine), sinon None."""
        missing = [k for k in REQUIRED if k not in sample]
        if missing:
            raise ValueError(f"Champs manquants: {missing}")
        self.buf.append({k: float(sample[k]) for k in REQUIRED})
        self.count += 1
        if len(self.buf) < WINDOW_SIZE or self.count % STEP != 0:
            return None

        x = window_features(pd.DataFrame(self.buf)).reshape(1, -1)
        score = float(self.pipe.decision_function(x)[0])   # < 0 = anormal
        level = ("critical" if score < self.critical
                 else "warning" if score < self.warning else "normal")
        self.streak = self.streak + 1 if level != "normal" else 0

        # Explicabilité : features les plus éloignées du comportement normal appris
        scaler = self.pipe.named_steps["scaler"]
        z = (x[0] - scaler.mean_) / scaler.scale_
        top = np.argsort(-np.abs(z))[:3]
        return {
            "score": round(score, 4),
            "level": level,
            "alert": self.streak >= self.consecutive,
            "top_features": [{"name": FEATURE_NAMES[i], "z": round(float(z[i]), 2)} for i in top],
        }
