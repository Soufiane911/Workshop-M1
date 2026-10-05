"""Paramètres communs du module Maintenance Prédictive."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "isolation_forest.joblib"
REPORT_PATH = ROOT / "reports" / "metrics.json"
DATA_DIR = ROOT / "data"

SAMPLE_PERIOD_S = 2      # l'ESP8266 envoie 1 mesure toutes les 2 s
WINDOW_SIZE = 30         # fenêtre glissante = 30 mesures = 1 minute
STEP = 5                 # on évalue une fenêtre toutes les 5 mesures
CONSECUTIVE = 3          # nb de fenêtres anormales d'affilée avant alerte (anti faux-positifs)

CHANNELS = ["temperature", "humidity", "gas"]   # DHT22 (temp, hum) + MQ-2 (gas)
