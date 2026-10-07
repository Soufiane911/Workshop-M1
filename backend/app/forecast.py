"""Prévision à court terme (lissage exponentiel double de Holt) — purement informative."""

import math
from datetime import timedelta

from sqlalchemy import select

from .config import DANGER_THRESHOLDS
from .db import Measure, SessionLocal, utcnow

WINDOW_MIN = 15
STEP_S = 10                      # pas de rééchantillonnage
ALPHA, BETA = 0.4, 0.15          # niveau, tendance
MIN_POINTS = 5
UNITS = {"temp": "°C", "hum": "%", "gaz": "brut"}
# Variation (sur 5 min) en dessous de laquelle la série est jugée stable
STABLE_FLOOR = {"temp": 0.3, "hum": 1.0, "gaz": 15.0}
LIMITS = {"temp": (-40.0, 80.0), "hum": (0.0, 100.0), "gaz": (0.0, 1023.0)}
STALE_S = 120                    # dernière mesure trop ancienne : pas de prévision
MAX_GAP_S = 60                   # trou plus long : la série redémarre (boîtier coupé, capteur désactivé)
ROUND = {"temp": 2, "hum": 2, "gaz": 1}


def _resample(samples: list[tuple[float, float]]) -> list[float]:
    """Moyenne par tranche de STEP_S s, trous comblés par interpolation linéaire."""
    t0 = samples[0][0]
    buckets: dict[int, list[float]] = {}
    for t, v in samples:
        buckets.setdefault(int((t - t0) // STEP_S), []).append(v)
    keys = sorted(buckets)
    avg = {k: sum(buckets[k]) / len(buckets[k]) for k in keys}
    out = []
    for i in range(keys[0], keys[-1] + 1):
        if i in avg:
            out.append(avg[i])
            continue
        lo = max(k for k in keys if k < i)
        hi = min(k for k in keys if k > i)
        out.append(avg[lo] + (avg[hi] - avg[lo]) * (i - lo) / (hi - lo))
    return out


def holt(y: list[float]) -> tuple[float, float, float]:
    """Renvoie (niveau, tendance par pas, écart-type des résidus à 1 pas)."""
    level, trend = y[0], (y[min(len(y) - 1, 3)] - y[0]) / min(len(y) - 1, 3)
    resid = []
    for v in y[1:]:
        pred = level + trend
        resid.append(v - pred)
        new_level = ALPHA * v + (1 - ALPHA) * pred
        trend = BETA * (new_level - level) + (1 - BETA) * trend
        level = new_level
    sigma = math.sqrt(sum(r * r for r in resid) / len(resid)) if resid else 0.0
    return level, trend, sigma


def _empty(key: str) -> dict:
    return {"unit": UNITS[key], "past": None, "now": None, "forecast": None, "low": None, "high": None,
            "slope_per_min": None, "trend": "inconnue", "danger_threshold": DANGER_THRESHOLDS[key],
            "minutes_to_threshold": None, "points": []}


def forecast_series(key: str, rows: list[tuple], now, horizon: int) -> dict:
    out = _empty(key)
    samples = [(ts.timestamp(), float(v)) for ts, v in rows if v is not None]
    if len(samples) < MIN_POINTS:
        return out
    r = ROUND[key]
    now_ts = now.timestamp()
    if now_ts - samples[-1][0] > STALE_S:
        return out
    lo_lim, hi_lim = LIMITS[key]
    # valeur d'il y a ~10 min (tolérance 2 min)
    ts_past, v_past = min(samples, key=lambda s: abs(s[0] - (now_ts - 600)))
    if abs(ts_past - (now_ts - 600)) <= 120:
        out["past"] = round(v_past, r)
    out["now"] = round(samples[-1][1], r)

    # Le modèle ne voit que le dernier segment continu : interpoler sur une coupure
    # mélangerait deux sessions et fausserait tendance et incertitude
    start = len(samples) - 1
    while start > 0 and samples[start][0] - samples[start - 1][0] <= MAX_GAP_S:
        start -= 1
    segment = samples[start:]
    y = _resample(segment)
    if len(segment) < MIN_POINTS or len(y) < 3:  # moins de ~30 s de données : pas de tendance
        return out

    level, trend, sigma = holt(y)
    per_min = 60 / STEP_S
    slope = trend * per_min
    thr = DANGER_THRESHOLDS[key]

    def at(m):  # prévision à m minutes, bornée aux valeurs physiquement possibles
        return min(hi_lim, max(lo_lim, level + slope * m))

    out["forecast"] = round(at(horizon), r)
    band = 1.96 * sigma * math.sqrt(horizon)
    out["low"] = round(max(lo_lim, at(horizon) - band), r)
    out["high"] = round(min(hi_lim, at(horizon) + band), r)
    out["slope_per_min"] = round(slope, 3)
    out["trend"] = ("stable" if abs(slope * 5) < max(STABLE_FLOOR[key], 2 * sigma)
                    else "hausse" if slope > 0 else "baisse")
    if thr is not None:
        if level >= thr:
            out["minutes_to_threshold"] = 0.0
        elif out["trend"] == "hausse":
            out["minutes_to_threshold"] = round((thr - level) / slope, 1)
    out["points"] = [{"ts": (now + timedelta(minutes=m)).isoformat(), "value": round(at(m), r)}
                     for m in range(1, horizon + 1)]
    return out


def compute_forecast(horizon: int) -> dict:
    now = utcnow()
    with SessionLocal() as s:
        rows = s.execute(select(Measure.ts, Measure.temp, Measure.hum, Measure.gaz)
                         .where(Measure.ts >= now - timedelta(minutes=WINDOW_MIN))
                         .order_by(Measure.ts)).all()
    series = {k: forecast_series(k, [(r[0], r[i + 1]) for r in rows], now, horizon)
              for i, k in enumerate(("temp", "hum", "gaz"))}
    return {"generated_at": now.isoformat(), "horizon_min": horizon, "method": "holt", "series": series}
