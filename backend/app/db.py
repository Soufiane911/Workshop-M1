import logging
import time
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DATABASE_URL

log = logging.getLogger("sentinel.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Measure(Base):
    """Une mesure reçue du boîtier (horodatée à la réception par le serveur)."""

    __tablename__ = "measures"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    device: Mapped[str] = mapped_column(String(64))
    temp: Mapped[float | None]
    hum: Mapped[float | None]
    gaz: Mapped[int | None]
    presence: Mapped[bool | None]

    def to_dict(self):
        return {
            "ts": self.ts.isoformat(),
            "device": self.device,
            "temp": self.temp,
            "hum": self.hum,
            "gaz": self.gaz,
            "presence": self.presence,
        }


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(32))   # vision, anomalie, capteur, systeme
    type: Mapped[str] = mapped_column(String(32))     # intrusion, presence, hors_ligne...
    level: Mapped[str] = mapped_column(String(16))    # info, warning, critical
    message: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    acknowledged: Mapped[bool] = mapped_column(default=False)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_by: Mapped[str | None] = mapped_column(String(64))

    def to_dict(self):
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "source": self.source,
            "type": self.type,
            "level": self.level,
            "message": self.message,
            "snapshot": self.snapshot,
            "details": self.details or {},
            "acknowledged": self.acknowledged,
            "acked_at": self.acked_at.isoformat() if self.acked_at else None,
            "acked_by": self.acked_by,
        }


class Action(Base):
    """Journal des commandes et changements de configuration (traçabilité)."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))     # command, config
    payload: Mapped[dict] = mapped_column(JSON)

    def to_dict(self):
        return {"id": self.id, "ts": self.ts.isoformat(), "actor": self.actor,
                "kind": self.kind, "payload": self.payload}


def init_db(retries: int = 30):
    """Crée les tables, en attendant que PostgreSQL soit prêt."""
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(engine)
            # Migration idempotente : tables créées avant l'ajout de l'acquittement détaillé
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acked_at TIMESTAMPTZ"))
                conn.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acked_by VARCHAR(64)"))
            log.info("base de données prête")
            return
        except OperationalError:
            log.warning("base indisponible (essai %d/%d)", attempt, retries)
            time.sleep(1)
    raise RuntimeError("impossible de joindre la base de données")
