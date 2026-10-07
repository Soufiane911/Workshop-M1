# Contrôle Réactif — panneau de commande des actionneurs

```
Navigateur ──HTTP POST /api/v1/commands──▶ API (FastAPI) ──MQTT sentinel/<id>/cmd──▶ ESP8266 (buzzer, LEDs)
Navigateur ◀────── WebSocket /ws ────────── API ◀──MQTT sentinel/<id>/ack|status───┘
```

| Dossier | Contenu |
|---|---|
| `dashboard/control-panel/index.html` | Panneau web (ON / OFF / Impulsion, état en temps réel) |
| `backend/control-api/` | API : commandes, WebSocket, tests |
| `firmware/actuators/` | Firmware PlatformIO de l'ESP8266 |

## Contrat
- Commande (POST, `Authorization: Bearer <API_TOKEN>`) : `{"device_id":"esp-01","actuator":"buzzer|led_green|led_red","state":"on|off|pulse"}` → `202`
- MQTT `sentinel/<id>/cmd` : `{"actuator":"buzzer","state":"on"}`
- MQTT `sentinel/<id>/ack` : `{"actuator":"buzzer","state":"on|off"}` (confirmation réelle de l'ESP, c'est elle qui met à jour le panneau)
- MQTT `sentinel/<id>/status` (retained) : `online` / `offline` (Last Will)

## Lancer l'API + le panneau
```bash
cd backend/control-api
pip install -r requirements.txt
cp .env.example .env     # renseigner API_TOKEN (long, aléatoire) puis: export $(grep -v '^#' .env | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000     # panneau sur http://<ip>:8000
python -m pytest -q
```

## Firmware
Copier `include/secrets.example.h` en `include/secrets.h` (ignoré par Git), y mettre Wi-Fi, broker, identifiants et le **CA** de Mosquitto, puis `pio run -t upload`.
Câblage : buzzer **D5**, LED verte **D6**, LED rouge **D7** (+ résistance ≈ 220 Ω sur les LEDs).

## Sécurité intégrée
Token obligatoire (API + WebSocket), liste blanche des actionneurs et validation du `device_id`, MQTTS avec vérification du certificat côté ESP,
buzzer coupé automatiquement après 10 s, aucun secret dans le dépôt.
À faire côté INFRA : TLS devant l'API (HTTPS/WSS) et ACL Mosquitto (l'API écrit sur `cmd`, l'ESP sur `ack`/`status`).
