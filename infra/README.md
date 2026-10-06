# Infrastructure

```bash
cd infra
docker compose up -d      # démarre la stack
docker compose ps         # état des conteneurs
docker compose logs -f    # logs
docker compose down       # arrêt
```

| Service | Port | État |
|---|---|---|
| Mosquitto | `127.0.0.1:1883` | ✅ dev, sans TLS |
| API + dashboard | `127.0.0.1:8000` | ✅ voir `backend/README.md` |
| PostgreSQL | interne (non exposé) | ✅ mot de passe dans `infra/.env` |

- `mosquitto/config/mosquitto.conf` : config du broker (dev : anonyme, non chiffré — à durcir : TLS 8883, comptes, ACL)
- `simulator/` : simulateur de l'ESP8266 (voir son README)
- Réseau de table prévu : 192.168.10.0/24, point d'accès WiFi sur le PC serveur
