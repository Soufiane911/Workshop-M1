import os
from pathlib import Path

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel"
)

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

DEVICE_ID = os.getenv("DEVICE_ID", "sentinel-01")

T_CAPTEURS = "sentinel/capteurs"
T_ETAT = "sentinel/etat"
T_COMMANDES = "sentinel/commandes"
T_CONFIG = "sentinel/config"

# Sans mesure depuis ce délai, le boîtier est considéré hors ligne
OFFLINE_AFTER_S = float(os.getenv("OFFLINE_AFTER_S", "10"))
# Délai minimum entre deux alertes de présence PIR
PIR_ALERT_COOLDOWN_S = float(os.getenv("PIR_ALERT_COOLDOWN_S", "30"))

DASHBOARD_DIR = Path(os.getenv("DASHBOARD_DIR", Path(__file__).resolve().parents[2] / "dashboard"))
SNAPSHOT_DIR = Path(os.getenv("SNAPSHOT_DIR", "/data/snapshots"))

# Seuils de danger INFORMATIFS (prévision uniquement) : ils ne déclenchent jamais d'alerte.
DANGER_THRESHOLDS = {"temp": 40.0, "hum": None, "gaz": 600}
# Sans analyse IA depuis ce délai, le module est considéré inactif
ANALYSIS_TTL_S = float(os.getenv("ANALYSIS_TTL_S", "30"))
