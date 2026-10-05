# Backend — API

- S'abonne à Mosquitto et enregistre les mesures en base
- `POST /api/v1/alerts` : réception des alertes (IA, capteurs)
- WebSocket : envoi temps réel au dashboard
- Relais des commandes du dashboard vers `sentinel/commandes`
