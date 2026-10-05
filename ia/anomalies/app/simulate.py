"""Simulateur de séries temporelles ESP8266 (DHT22 + MQ-2 + PIR).

Sert à entraîner / tester le modèle tant que le vrai boîtier n'est pas câblé.
Remplacer ensuite par les vraies mesures collectées (même colonnes).
"""
import numpy as np
import pandas as pd

from .config import SAMPLE_PERIOD_S


def _ar1(rng, n, phi, sigma):
    x = np.zeros(n)
    eps = rng.normal(0, sigma, n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def generate(n=20000, seed=0, with_anomalies=True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    slow = np.sin(2 * np.pi * t / 1800)  # lente variation ambiante

    temp = 22 + 1.5 * slow + _ar1(rng, n, 0.9, 0.08)
    hum = 50 - 1.5 * slow + _ar1(rng, n, 0.9, 0.2)
    gas = 300 + 6 * slow + _ar1(rng, n, 0.7, 3.0)
    pir = (rng.random(n) < 0.02).astype(int)
    kind = np.array(["normal"] * n, dtype=object)

    if with_anomalies:
        cur = 300
        order = ["drift", "gas_leak", "stuck_sensor", "spike"]
        k = 0
        while cur < n - 250:
            a = order[k % 4]
            k += 1
            if a == "drift":      # hausse lente de T° + micro-déviation du gaz
                L = int(rng.integers(120, 200)); r = np.linspace(0, 1, L)
                temp[cur:cur + L] += 6 * r
                gas[cur:cur + L] += 22 * r
                hum[cur:cur + L] -= 8 * r
            elif a == "gas_leak":
                L = int(rng.integers(60, 100))
                gas[cur:cur + L] += 160 * (1 - np.exp(-np.arange(L) / 20))
            elif a == "stuck_sensor":  # capteur figé (panne)
                L = int(rng.integers(60, 100))
                temp[cur:cur + L] = temp[cur]
                gas[cur:cur + L] = gas[cur]
            else:                  # pic brutal de température
                L = int(rng.integers(15, 25))
                temp[cur:cur + L] += 9
            kind[cur:cur + L] = a
            cur += L + int(rng.integers(300, 700))

    df = pd.DataFrame({
        "ts": np.arange(n) * SAMPLE_PERIOD_S,
        "temperature": temp.round(2),
        "humidity": hum.round(2),
        "gas": gas.round(1),
        "pir": pir,
        "anomaly_type": kind,
    })
    df["label"] = (df["anomaly_type"] != "normal").astype(int)
    return df
