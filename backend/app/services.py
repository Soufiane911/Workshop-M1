"""Logique partagée entre les routes HTTP et le pont MQTT."""

import logging
import threading
import time

from .config import ANALYSIS_TTL_S, SNAPSHOT_DIR
from .db import Action, Alert, SessionLocal, utcnow
from .hub import hub

log = logging.getLogger("sentinel.services")


class FrameStore:
    """Dernière image annotée envoyée par le script de vision."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg: bytes | None = None
        self.seq = 0
        self.updated = 0.0

    def put(self, jpeg: bytes):
        with self.lock:
            self.jpeg = jpeg
            self.seq += 1
            self.updated = time.monotonic()

    def get(self) -> tuple[int, bytes | None]:
        with self.lock:
            return self.seq, self.jpeg

    def active(self, max_age: float = 3.0) -> bool:
        return self.jpeg is not None and time.monotonic() - self.updated < max_age


frames = FrameStore()


class VisionStats:
    """Dernières statistiques d'inférence envoyées par le script de vision."""

    def __init__(self):
        self.data: dict | None = None
        self.updated = None

    def put(self, data: dict):
        self.data, self.updated = data, utcnow()


class AnalysisStore:
    """Dernière analyse du service de détection d'anomalies."""

    def __init__(self):
        self.data: dict | None = None
        self.updated = 0.0

    def put(self, data: dict) -> dict:
        self.data = {**data, "ts": utcnow().isoformat()}
        self.updated = time.monotonic()
        return self.data

    def fresh(self) -> bool:
        return self.data is not None and time.monotonic() - self.updated < ANALYSIS_TTL_S

    def get(self) -> dict:
        if self.fresh():
            return self.data
        return {"state": "inactif", "score": None, "explanation": "Aucune analyse récente",
                "features": {}, "model": None, "ts": self.data["ts"] if self.data else None}


vision_stats = VisionStats()
analysis = AnalysisStore()


def save_snapshot() -> str | None:
    """Enregistre l'image vision courante et renvoie son URL publique."""
    if not frames.active():
        return None
    _, jpeg = frames.get()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"intrus_{utcnow():%Y%m%d_%H%M%S_%f}.jpg"
    (SNAPSHOT_DIR / name).write_bytes(jpeg)
    return f"/snapshots/{name}"


def create_alert(source: str, type: str, level: str, message: str,
                 snapshot: str | None = None, details: dict | None = None) -> dict:
    with SessionLocal() as s:
        # Une simple information n'a pas besoin d'être acquittée par l'opérateur
        alert = Alert(source=source, type=type, level=level, message=message,
                      snapshot=snapshot, details=details or {}, acknowledged=level == "info")
        if level == "info":
            alert.acked_at, alert.acked_by = utcnow(), "auto"
        s.add(alert)
        s.commit()
        data = alert.to_dict()
    log.info("alerte %s/%s : %s", source, type, message)
    hub.publish("alert", data)
    return data


def log_action(actor: str, kind: str, payload: dict):
    with SessionLocal() as s:
        s.add(Action(actor=actor, kind=kind, payload=payload))
        s.commit()


def set_online(online: bool, reason: str = ""):
    """Change l'état en ligne du boîtier ; alerte sur une perte de connexion."""
    with hub.lock:
        was_online = hub.state["online"]
        hub.state["online"] = online
    if was_online == online:
        return
    hub.publish("state", hub.snapshot_state())
    if not online:
        create_alert("systeme", "hors_ligne", "critical", f"Boîtier hors ligne ({reason})")
    else:
        create_alert("systeme", "en_ligne", "info", "Boîtier de nouveau en ligne")
