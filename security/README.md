# Cybersécurité

## Mise en place (PC serveur)

```bash
./security/init-mqtt.sh                 # certificats + comptes MQTT (crée ce qui manque)
cd infra && docker compose up -d --force-recreate
```

`SERVER_IP=192.168.10.1 ./security/init-mqtt.sh --force` si l'IP du serveur change (puis re-flasher l'ESP8266).

| Fichier généré | Rôle | Commité ? |
|---|---|---|
| `infra/pki/ca.key` | clé privée de l'autorité de certification (AC) | ❌ ne quitte jamais le PC serveur |
| `infra/mosquitto/certs/ca.crt` | certificat public de l'AC | ❌ (régénéré par machine) |
| `infra/mosquitto/certs/server.{crt,key}` | certificat du broker (EC P-256, SAN `10.42.0.1`, `mosquitto`, `localhost`) | ❌ |
| `infra/mosquitto/config/passwd` | comptes MQTT hachés (PBKDF2-SHA512), propriétaire `mosquitto`, `0600` | ❌ |
| `infra/.env` | mots de passe `MQTT_*_PASSWORD` aléatoires, `0600` | ❌ |
| `firmware/include/ca_cert.h` | AC embarquée dans l'ESP8266 | ❌ |

## Matrice de sécurité

| Menace | Contre-mesure | État |
|---|---|---|
| Écoute du WiFi de table (Wireshark) | MQTTS : TLS 1.2 minimum (TLS 1.3 entre conteneurs), aucun port MQTT en clair | ✅ |
| Faux broker / homme du milieu | l'ESP8266 et les services vérifient le certificat du broker avec notre AC | ✅ |
| Client MQTT pirate | `allow_anonymous false`, un compte par composant | ✅ |
| Compte volé → prise de contrôle | ACL par compte : seul `api` peut envoyer des ordres au boîtier | ✅ |
| Injection de fausses mesures | seul `boitier` peut publier sur `sentinel/capteurs` | ✅ |
| DoS sur le broker | `max_connections 32`, `max_packet_size 8192`, files bornées | ✅ |
| Fuite de secrets dans Git / images Docker | `.gitignore` + `.dockerignore`, secrets en variables d'environnement | ✅ |
| Escalade depuis un conteneur | conteneurs non-root (`api`, `anomalies`, Mosquitto passe en `mosquitto`) | ✅ |
| Accès libre à l'API / au dashboard | HTTPS + authentification | ⏳ à faire |
| Ports ouverts sur l'hôte | UFW (deny par défaut) | ⏳ à faire |
| SSH par mot de passe | clés uniquement | ⏳ à faire |

## Droits MQTT (`infra/mosquitto/config/acl`)

| Compte | Utilisé par | Publie | Lit |
|---|---|---|---|
| `boitier` | ESP8266, simulateur | `capteurs`, `etat`, `diagnostic` | `commandes`, `config` |
| `api` | backend | `commandes`, `config` | `sentinel/#` |
| `ia` | détecteur d'anomalies | — | `capteurs` |

## Tests d'attaque (6 oct. 2026, depuis le PC serveur)

| Test | Résultat attendu | Obtenu |
|---|---|---|
| Connexion MQTT en clair (1883) | refusée | ✅ `Connection refused` (port fermé) |
| TLS sans compte | refusée | ✅ `Not authorized` |
| TLS mauvais mot de passe | refusée | ✅ `Not authorized` |
| Broker non signé par notre AC | refusé par le client | ✅ `CERTIFICATE_VERIFY_FAILED` |
| `boitier` s'abonne à `sentinel/capteurs` | rien reçu | ✅ |
| `ia` publie `{"led":"rouge"}` sur `sentinel/commandes` | non relayé au boîtier | ✅ |
| `api` publie sur `sentinel/commandes` | relayé | ✅ |
| Suite TLS de l'ESP8266 (`ECDHE-ECDSA-AES128-GCM-SHA256`, TLS 1.2) | acceptée, cert valide pour `10.42.0.1` | ✅ |

**Preuve pour le jury** : Wireshark sur l'interface `ap0` (WiFi de table), filtre `tcp.port == 8883` → uniquement des `Application Data` TLS illisibles. Les logs du broker montrent le compte et le chiffrement de chaque client :

```bash
docker logs sentinel-mosquitto | grep -E "connected|negotiated"
```

## Reste à faire

- HTTPS + authentification de l'API (`/commands`, `/config`, `/alerts`) et du dashboard
- Hardening de l'hôte : UFW, SSH par clé, Docker
- Rapport d'audit du pentest croisé (jeudi)
