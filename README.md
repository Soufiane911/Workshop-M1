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

> Aucun secret (mot de passe, clé, certificat) ne doit être commité. Utiliser un fichier `.env` (ignoré par Git).
