import numpy as np
import pytest

from app.config import MODEL_PATH
from app.detector import AnomalyDetector
from app.features import FEATURE_NAMES, build_dataset
from app.simulate import generate

pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason="lancer `python -m app.train` d'abord")


def test_features_shape():
    X, y, ends = build_dataset(generate(n=300, seed=3))
    assert X.shape[1] == len(FEATURE_NAMES) and np.isfinite(X).all()


def test_normal_stream_has_very_few_false_alerts():
    """Sur du fonctionnement normal, moins de 1 % des fenêtres doivent déclencher une alerte."""
    total = alerts = 0
    for seed in (11, 12, 13, 14):
        det = AnomalyDetector()
        for s in generate(n=5000, seed=seed, with_anomalies=False).to_dict("records"):
            r = det.push(s)
            if r:
                total += 1
                alerts += r["alert"]
    assert alerts / total < 0.01


def test_gas_leak_triggers_alert():
    det = AnomalyDetector()
    df = generate(n=2000, seed=5, with_anomalies=False)
    df.loc[1000:, "gas"] += 150  # fuite brutale
    alerts = [r for r in (det.push(s) for s in df.to_dict("records")) if r and r["alert"]]
    assert alerts


def test_missing_field_rejected():
    with pytest.raises(ValueError):
        AnomalyDetector().push({"temperature": 20})
