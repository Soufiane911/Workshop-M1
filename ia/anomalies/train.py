"""Sentinel-X — Entraînement de l'Isolation Forest sur des données NORMALES.

Deux modèles appris sur les mêmes fenêtres normales, avec la même contamination :
  - Isolation Forest : combinaisons de features inhabituelles ;
  - enveloppe elliptique (distance de Mahalanobis robuste) : l'Isolation Forest
    « sature » hors du domaine d'entraînement (une température de 35 °C n'y est pas
    plus anormale que la plus haute vue en entraînement) ; l'enveloppe, elle, croît
    avec l'écart et maintient l'anomalie tant que la dérive dure.

Usage :
    python train.py --csv normal.csv
    python train.py --csv normal1.csv normal2.csv --contamination 0.01 --window 30

Génération d'un jeu normal (simulateur) :
    python ../../infra/simulator/simulator.py --fast --duration 7200 --csv normal.csv
Pour des données réelles du boîtier : --use-ts (le champ ts est alors utilisé).
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.covariance import EllipticEnvelope
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import features as ft

MODELE = Path(__file__).parent / "model.joblib"


def entrainer(csvs, window=ft.WINDOW, contamination=0.01, interval=ft.INTERVAL,
              use_ts=False, seed=42):
    blocs = []
    for c in csvs:
        mesures, _ = ft.lire_csv(c, interval, use_ts)
        X, _ = ft.matrice(mesures, window)
        blocs.append(X)
    X = np.vstack(blocs)

    pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="mean")),   # capteur absent -> valeur neutre
        ("scaler", StandardScaler()),
        ("forest", IsolationForest(n_estimators=200, contamination=contamination,
                                   random_state=seed)),
    ])
    pipe.fit(X)
    # Enveloppe sur les features normalisées (même imputation / mise à l'échelle)
    envelope = EllipticEnvelope(contamination=contamination, random_state=seed)
    envelope.fit(pipe[:-1].transform(X))

    scores = pipe.decision_function(X)
    meta = {
        "feature_names": ft.FEATURES,
        "window": window,
        "interval": interval,
        "training_rows": int(len(X)),
        "contamination": contamination,
        "date": datetime.now().isoformat(timespec="seconds"),
        "csv": [str(c) for c in csvs],
        # stats d'entraînement : servent aux z-scores de l'explication
        "feat_mean": np.nanmean(X, axis=0).tolist(),
        "feat_std": np.nanstd(X, axis=0).tolist(),
        "decision_min": float(scores.min()),
        "decision_p01": float(np.percentile(scores, 1)),
        "decision_median": float(np.median(scores)),
        "envelope_mahal2": float(-envelope.offset_),  # frontière apprise (distance² de Mahalanobis)
    }
    return pipe, envelope, meta


def main():
    p = argparse.ArgumentParser(description="Entraînement Isolation Forest Sentinel-X")
    p.add_argument("--csv", nargs="+", required=True, type=Path, help="CSV de données normales")
    p.add_argument("--out", type=Path, default=MODELE, help="fichier modèle (défaut : model.joblib)")
    p.add_argument("--window", type=int, default=ft.WINDOW, help="taille de fenêtre (défaut : 30)")
    p.add_argument("--contamination", type=float, default=0.01, help="part d'anomalies tolérée (défaut : 0.01)")
    p.add_argument("--interval", type=float, default=ft.INTERVAL, help="secondes entre mesures (défaut : 2)")
    p.add_argument("--use-ts", action="store_true", help="utiliser la colonne ts (données réelles)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    pipe, envelope, meta = entrainer(args.csv, args.window, args.contamination, args.interval, args.use_ts, args.seed)
    joblib.dump({"pipeline": pipe, "envelope": envelope, "meta": meta}, args.out)
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"Modèle entraîné sur {meta['training_rows']} fenêtres de {args.window} mesures -> {args.out}")
    print(f"decision_function : min {meta['decision_min']:.3f} | p1 {meta['decision_p01']:.3f} "
          f"| médiane {meta['decision_median']:.3f}")


if __name__ == "__main__":
    main()
