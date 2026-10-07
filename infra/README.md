# Infrastructure

```bash
./security/init-mqtt.sh  # une seule fois : certificats TLS + comptes MQTT
cd infra
docker compose up -d      # démarre la stack
docker compose ps         # état des conteneurs
docker compose logs -f    # logs
docker compose down       # arrêt
```

| Service | Port | État |
|---|---|---|
| Mosquitto | `127.0.0.1:8883`, `10.42.0.1:8883` | ✅ MQTTS (TLS), comptes + ACL |
| API + dashboard | `127.0.0.1:8000` | ✅ voir `backend/README.md` |
| PostgreSQL | interne (non exposé) | ✅ mot de passe dans `infra/.env` |

- `mosquitto/config/mosquitto.conf` : config du broker (TLS uniquement, pas d'anonyme) ; `acl` : droits par compte
- Avant le premier `docker compose up` : `../security/init-mqtt.sh` (certificats + mots de passe, voir `security/README.md`)
- `simulator/` : simulateur de l'ESP8266 (voir son README)
- Réseau de table prévu : 192.168.10.0/24, point d'accès WiFi sur le PC serveur
