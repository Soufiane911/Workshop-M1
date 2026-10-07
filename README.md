# Sentinel-X — Workshop M1 2026-27

Boîtier de surveillance autonome (ESP8266) relié à un PC serveur local (option B).

| Dossier | Partie | Contenu |
|---|---|---|
| `firmware/` | 1 — Firmware | Code C++ PlatformIO de l'ESP8266 (capteurs, OLED, buzzer, LED, MQTTS) |
| `backend/` | 2 — API | API REST + WebSocket, `POST /api/v1/alerts`, base de données |
| `dashboard/` | 3 — Dashboard | Interface web de supervision |
| `ia/` | 4 — IA | `vision/` (YOLO webcam) et `anomalies/` (Isolation Forest) |
| `infra/` | 5 — Infra | docker-compose, config Mosquitto, réseau, monitoring |
| `security/` | 5 — Cyber | TLS, hardening, rapport de pentest |
| `docs/` | 6 — Com | Dossier PDF, schémas, présentation, vidéo |

## Lancer le projet

Prérequis : Docker (avec `docker compose`), Python 3.12+, `openssl`.

### 1. Première fois seulement

```bash
./security/init-mqtt.sh                                         # certificats TLS + comptes MQTT -> infra/.env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> infra/.env  # mot de passe de la base
```

> Le compose publie aussi les ports sur `10.42.0.1` (WiFi de table). Si cette adresse n'existe pas sur ton PC,
> `docker compose up` échoue : active le point d'accès WiFi, ou commente les lignes `10.42.0.1:...` dans `infra/docker-compose.yml`.

### 2. Démarrer la stack (Mosquitto, PostgreSQL, API + dashboard, IA anomalies)

```bash
cd infra
docker compose up -d --build
docker compose ps          # vérifier que tout tourne
docker compose logs -f     # suivre les logs
```

Dashboard : <http://localhost:8000>

### 3. Envoyer des données (sans le boîtier)

```bash
cd infra/simulator
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python simulator.py                       # fonctionnement normal
.venv/bin/python simulator.py --scenario incident   # dérive lente -> l'IA anomalies doit alerter
```

Avec le vrai boîtier : voir `firmware/README.md` (compiler et flasher avec PlatformIO).

### 4. Vision (webcam, YOLO)

```bash
cd ia/vision
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python detect.py --api http://localhost:8000/api/v1/alerts
```

Le tout est arrêté par `cd infra && docker compose down`.

Autres scripts (tests isolés, à la racine) : `python detection.py` (YOLO + temps par trame, pilotes caméra Windows)
et `python stream_optimizer.py` (latence du flux webcam), avec les dépendances de `ia/vision/requirements.txt`.
