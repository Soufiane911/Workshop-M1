"""Démo hors-ligne : rejoue un CSV dans le détecteur (utile pour la soutenance).

    python -m app.replay            # rejoue data/test_with_anomalies.csv
"""
import sys

import pandas as pd

from .config import DATA_DIR
from .detector import AnomalyDetector


def main(path=DATA_DIR / "test_with_anomalies.csv", limit=6000):
    df = pd.read_csv(path).head(limit)
    det = AnomalyDetector()
    for i, row in df.iterrows():
        res = det.push(row.to_dict())
        if res and res["alert"]:
            print(f"t={int(row['ts']):>6}s  {res['level']:<8} score={res['score']:+.3f}  "
                  f"vérité={row.get('anomaly_type', '?'):<13} causes={[f['name'] for f in res['top_features']]}")


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else main()
