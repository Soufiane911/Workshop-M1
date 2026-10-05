"""Entraînement + évaluation de l'Isolation Forest.

    python -m app.train

Principe : apprentissage NON supervisé sur du fonctionnement normal uniquement.
Les anomalies (simulées) ne servent qu'à l'évaluation. Les seuils d'alerte sont
déduits de la distribution des scores d'entraînement (pas de seuil codé en dur
sur la température ou le gaz).
"""
import json

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import DATA_DIR, MODEL_PATH, REPORT_PATH, SAMPLE_PERIOD_S, STEP, WINDOW_SIZE
from .features import FEATURE_NAMES, build_dataset
from .simulate import generate


def fit(X_normal):
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("iforest", IsolationForest(n_estimators=300, contamination="auto", random_state=42)),
    ])
    pipe.fit(X_normal)
    s = pipe.decision_function(X_normal)
    warning = float(np.percentile(s, 0.5))                 # 0,5 % des fenêtres normales les plus atypiques
    critical = float(warning - 0.75 * (np.median(s) - warning))  # nettement plus extrême
    return pipe, warning, critical


def event_detection(df, ends, flagged):
    """Détection par ÉVÉNEMENT : un événement est détecté si au moins une fenêtre
    se terminant pendant l'événement est signalée. Donne aussi le délai de 1re détection."""
    kinds = df["anomaly_type"].to_numpy()
    res = {}
    i = 0
    while i < len(df):
        if kinds[i] != "normal":
            j = i
            while j < len(df) and kinds[j] == kinds[i]:
                j += 1
            hit = [e for e, f in zip(ends, flagged) if f and i <= e < j]
            r = res.setdefault(kinds[i], {"events": 0, "detected": 0, "delays_s": [], "temp_at_detection": [], "temp_event_max": []})
            r["events"] += 1
            if hit:
                r["detected"] += 1
                r["delays_s"].append(int((hit[0] - i) * SAMPLE_PERIOD_S))
                r["temp_at_detection"].append(float(df["temperature"].iloc[hit[0]]))
            r["temp_event_max"].append(float(df["temperature"].iloc[i:j].max()))
            i = j
        else:
            i += 1
    for r in res.values():
        r["mean_delay_s"] = float(np.mean(r["delays_s"])) if r["delays_s"] else None
    return res


def main():
    DATA_DIR.mkdir(exist_ok=True); MODEL_PATH.parent.mkdir(exist_ok=True); REPORT_PATH.parent.mkdir(exist_ok=True)

    train_df = generate(n=20000, seed=1, with_anomalies=False)
    test_df = generate(n=20000, seed=2, with_anomalies=True)
    train_df.to_csv(DATA_DIR / "train_normal.csv", index=False)
    test_df.to_csv(DATA_DIR / "test_with_anomalies.csv", index=False)

    X_tr, _, _ = build_dataset(train_df)
    pipe, warn, crit = fit(X_tr)

    X_te, y_te, ends = build_dataset(test_df)
    scores = pipe.decision_function(X_te)
    pred = (scores < warn).astype(int)
    keep = y_te != -1                      # on ignore les fenêtres ambiguës
    p, r, f1, _ = precision_recall_fscore_support(y_te[keep], pred[keep], average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_te[keep], pred[keep]).ravel()

    # par type d'anomalie (une fenêtre est rattachée au type de sa dernière mesure)
    per_type = {}
    for t in ("drift", "gas_leak", "stuck_sensor", "spike"):
        m = test_df["anomaly_type"].to_numpy()[ends] == t
        per_type[t] = {"windows": int(m.sum()), "detected": float(pred[m].mean()) if m.any() else None}

    report = {
        "window_size": WINDOW_SIZE, "step": STEP, "n_features": len(FEATURE_NAMES),
        "thresholds": {"warning": warn, "critical": crit},
        "precision": float(p), "recall": float(r), "f1": float(f1),
        "false_positive_rate": float(fp / (fp + tn)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "detection_rate_by_type": per_type,
        "event_detection": event_detection(test_df, ends, pred.astype(bool)),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    joblib.dump({"pipeline": pipe, "warning_threshold": warn, "critical_threshold": crit,
                 "feature_names": FEATURE_NAMES}, MODEL_PATH)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
