"""Diagnostic des capteurs.

Statistiques et détections sur la dernière heure ; la santé (lectures ratées,
valeur bloquée, hors plage) ne regarde que les dernières minutes, depuis la
dernière remise en service du capteur : un incident passé ne la dégrade pas
pendant une heure.
"""

from datetime import timedelta

from sqlalchemy import select

from .db import Measure, SessionLocal, utcnow
from .hub import hub

WINDOW_MIN = 60
HEALTH_WINDOW_S = 180  # fenêtre de la santé (comportement récent)
NO_READ_S = 30        # sans lecture depuis ce délai : panne
STUCK_N = 30          # nombre de valeurs identiques = capteur figé
PREHEAT_S = 120
MAX_GAP_S = 10        # écart max entre deux mesures d'un flux « continu »
RANGES = {"temp": (-40, 80), "hum": (0, 100), "gaz": (0, 1023)}
INFO = {
    "dht22": {"pin": "D5", "supply": "3,3 V", "fields": ["temp", "hum"]},
    "mq2": {"pin": "A0", "supply": "5 V (convertisseur)", "fields": ["gaz"]},
    "pir": {"pin": "D6", "supply": "3,3 V", "fields": []},
}


def _stats(values):
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {"min": round(min(values), 1), "avg": round(sum(values) / len(values), 1), "max": round(max(values), 1)}


def _continuous_s(times: list[float]) -> float:
    """Durée du flux de mesures ininterrompu qui se termine à la dernière."""
    if not times:
        return 0.0
    start = times[-1]
    for t in reversed(times[:-1]):
        if start - t > MAX_GAP_S:
            break
        start = t
    return times[-1] - start


def _health(enabled, online, last_read, now, recent_null, stuck, oor, failed):
    if not enabled:
        return "hors_service"
    if last_read is None or recent_null or (online and (now - last_read).total_seconds() > NO_READ_S):
        return "panne"
    if stuck or oor or failed > 0:
        return "degrade"
    return "ok"


def compute_sensors() -> dict:
    now = utcnow()
    with SessionLocal() as s:
        rows = s.scalars(select(Measure).where(Measure.ts >= now - timedelta(minutes=WINDOW_MIN))
                         .order_by(Measure.ts)).all()
    state = hub.snapshot_state()
    with hub.lock:
        enabled_since = dict(hub.enabled_since)
    cfg, online = state["config"], state["online"]
    sensors = {}
    for name, info in INFO.items():
        enabled = bool(cfg.get(name, True))
        fields = info["fields"] or ["presence"]
        # une ligne est une lecture réussie si tous les champs du capteur sont renseignés
        ok_rows = [m for m in rows if all(getattr(m, f) is not None for f in fields)]
        last_read = ok_rows[-1].ts if ok_rows else None
        # mesures récentes, postérieures à la dernière remise en service
        since = now - timedelta(seconds=HEALTH_WINDOW_S)
        if enabled_since.get(name) and enabled_since[name] > since:
            since = enabled_since[name]
        recent = [m for m in rows if m.ts >= since]
        failed = sum(1 for m in recent if any(getattr(m, f) is None for f in fields)) if enabled else 0
        recent_null = bool(recent) and all(any(getattr(m, f) is None for f in fields) for m in recent[-5:])
        stuck = oor = False
        stats = {}
        for f in info["fields"]:
            vals = [getattr(m, f) for m in ok_rows]
            stats[f] = _stats(vals)
            rvals = [getattr(m, f) for m in recent if getattr(m, f) is not None]
            stuck = stuck or (len(rvals) >= STUCK_N and len(set(rvals[-STUCK_N:])) == 1)
            lo, hi = RANGES[f]
            oor = oor or any(v < lo or v > hi for v in rvals)
        entry = {"enabled": enabled, "pin": info["pin"], "supply": info["supply"],
                 "interval_ms": cfg.get("interval_ms"),
                 "last_read": last_read.isoformat() if last_read else None,
                 "failed_reads": failed, "stuck": stuck, "out_of_range": oor,
                 "health": _health(enabled, online, last_read, now, recent_null and enabled, stuck, oor, failed)}
        if name == "mq2":
            times = [m.ts.timestamp() for m in ok_rows]
            entry["preheat_done"] = _continuous_s(times) > PREHEAT_S
        if name == "pir":
            pres = [m for m in rows if m.presence is not None]
            ups = [b.ts for a, b in zip(pres, pres[1:]) if not a.presence and b.presence]
            entry["detections_1h"] = len(ups)
            entry["last_detection"] = ups[-1].isoformat() if ups else None
        entry["stats"] = stats
        sensors[name] = entry
    sensors["actuators"] = {"buzzer": state["buzzer"], "led": state["led"], "oled": "non suivi"}
    return {"window_min": WINDOW_MIN, "health_window_s": HEALTH_WINDOW_S, "sensors": sensors}
