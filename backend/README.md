# Backend — API Sentinel-X

FastAPI + PostgreSQL + pont MQTT. Sert aussi le dashboard (`../dashboard`).

## Lancement

```bash
cd infra
cp .env.example .env        # puis mettre un vrai mot de passe (ne jamais commiter .env)
docker compose up -d --build
```

- Dashboard : https://localhost:8000 (connexion obligatoire)
- Documentation interactive de l'API : désactivée (durcissement)

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/v1/health` | état de l'API, MQTT, vision, base (`db`) et IA (`analysis`) |
| GET | `/api/v1/status` | état du boîtier (en ligne, config, buzzer, LED, dernière mesure) |
| GET | `/api/v1/metrics?minutes=10` | historique des mesures |
| GET | `/api/v1/alerts?limit=50&level=&source=&unacked=` | historique des alertes (filtres optionnels) |
| POST | `/api/v1/alerts` | **réception d'une alerte** (IA vision, anomalies…) |
| POST | `/api/v1/alerts/{id}/ack` | acquitter une alerte (`acked_at`, `acked_by` = IP) |
| GET | `/api/v1/forecast?horizon=10` | prévision Holt à 1..60 min (temp, hum, gaz) sur le dernier segment continu (15 min max) : tendance, bande, minutes avant seuil ; `past` (valeur d'il y a 10 min) vaut `null` si le run est plus court |
| GET | `/api/v1/sensors` | diagnostic DHT22 / MQ-2 / PIR : stats et détections sur 60 min, santé (lectures ratées, valeur bloquée, hors plage) sur les 3 dernières minutes depuis la dernière remise en service |
| GET | `/api/v1/actions?limit=100` | journal des commandes, configs et acquittements |
| POST/GET | `/api/v1/analysis` | résultat IA `{state, score, explanation, features, model}` ; GET → `inactif` après 30 s |
| POST/GET | `/api/v1/vision/stats` | stats d'inférence `{inference_ms, fps, persons, model, conf}` + `active`, `intrusions_today` |
| POST | `/api/v1/commands` | `{"buzzer": true, "led": "rouge"}` → `sentinel/commandes` |
| POST | `/api/v1/config` | `{"pir": false, "interval_ms": 2000}` → `sentinel/config` (retained) |
| POST | `/api/v1/vision/frame` | image JPEG annotée envoyée par `detect.py` |
| GET | `/api/v1/vision/stream` | flux vidéo MJPEG pour le dashboard |
| WS | `/ws` | temps réel : `measure`, `state`, `alert`, `alert_ack`, `analysis` |

### Format d'une alerte

```json
{"source": "vision", "type": "intrusion", "level": "critical", "message": "Présence humaine détectée"}
```

`level` : `info`, `warning` ou `critical`. Les champs en plus (`persons`, `confidence`…) sont gardés dans `details`.
Pour une alerte `source: "vision"`, l'API enregistre l'image courante comme capture.

Les seuils de danger de `/forecast` (temp 40 °C, gaz 600) sont **informatifs** : aucune alerte statique n'en découle.
Les colonnes `acked_at` / `acked_by` sont ajoutées automatiquement au démarrage (migration idempotente).

## Alertes générées par l'API

- Boîtier hors ligne (message `online:false` ou aucune mesure depuis 10 s) / de nouveau en ligne
- Mouvement détecté par le PIR (au plus une alerte toutes les 30 s)
- Capteur de sécurité (PIR, MQ-2) désactivé à distance

## Base de données

| Table | Contenu |
|---|---|
| `measures` | mesures reçues, horodatées à la réception |
| `alerts` | alertes et leur acquittement |
| `actions` | journal des commandes, configs et acquittements (qui, quoi, quand) |

## À faire (partie Cyber)

- ~~TLS MQTTS 8883, comptes et ACL Mosquitto~~ ✅ (voir `security/README.md`)
- HTTPS
- Authentification sur les routes de commande et de configuration
