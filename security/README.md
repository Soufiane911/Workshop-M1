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
| Rétrogradation vers une suite faible | TLS 1.2 limité à ECDHE-ECDSA + AES-GCM / ChaCha20 (pas de CBC, RSA, SHA-1) | ✅ |
| Faux broker / homme du milieu | l'ESP8266 et les services vérifient le certificat du broker avec notre AC | ✅ |
| Client MQTT pirate | `allow_anonymous false`, un compte par composant | ✅ |
| Compte volé → prise de contrôle | ACL par compte : seul `api` peut envoyer des ordres au boîtier | ✅ |
| Injection de fausses mesures | seul `boitier` peut publier sur `sentinel/capteurs` | ✅ |
| DoS sur le broker | `max_connections 32`, `max_packet_size 8192`, files bornées | ✅ |
| Fuite de secrets dans Git / images Docker | `.gitignore` + `.dockerignore`, secrets en variables d'environnement | ✅ |
| Escalade depuis un conteneur | tous les conteneurs : processus non-root (`sentinel`, `mosquitto`, `postgres`), **aucune capability effective** (`cap_drop: ALL`), `no-new-privileges`, système de fichiers **en lecture seule** (seuls les volumes de données et `/tmp` en tmpfs sont inscriptibles) | ✅ |
| DoS / fuite mémoire d'un conteneur qui fait tomber l'hôte | limites par conteneur : mémoire (128–512 Mo), CPU, 256 processus max | ✅ |
| Fausses mesures du simulateur confondues avec le boîtier | compte `simulateur` distinct (visible dans les logs du broker) | ✅ |
| Saturation du disque par les logs | logs sur stdout, rotation Docker (3 × 10 Mo par conteneur) | ✅ |
| Accès libre au dashboard / à l'API | connexion obligatoire (mot de passe haché PBKDF2-SHA256 600 000 it.), cookie de session aléatoire `HttpOnly` + `SameSite=Strict`, 8 h max ; toutes les routes protégées (REST, WebSocket, flux vidéo, captures) sauf `/health` | ✅ |
| Pilotage du boîtier par l'API (contournement des ACL MQTT) | `/commands` et `/config` réservés à la session superviseur | ✅ |
| Fausse image caméra / fausse analyse IA / fausses alertes | jeton `API_TOKEN` des modules IA, accepté **uniquement** sur leurs 4 routes d'écriture | ✅ |
| Bruteforce du mot de passe | 5 échecs → IP bloquée 5 min, échecs journalisés (page Système) ; temps de réponse identique quel que soit l'identifiant | ✅ (IP réelle : voir `userland-proxy`) |
| Clickjacking, XSS, reconnaissance | CSP `script-src 'self'`, `X-Frame-Options: DENY`, `nosniff`, documentation `/docs` désactivée | ✅ |
| Écoute du mot de passe / du cookie sur le WiFi | HTTPS uniquement (aucun port HTTP), TLS 1.2+ ECDHE + AES-GCM/ChaCha20, certificat signé par notre AC ; cookie `Secure` | ✅ |
| Client MQTT pirate sur le WiFi de table | pare-feu nftables : 1883/8883 réservés à l'ESP8266 (IP **et** MAC, IP fixée par réservation DHCP) + localhost, refus journalisés | ✅ (`init-firewall.sh`) |
| Autres ports ouverts sur l'hôte | UFW (deny par défaut) | ⏳ à faire |
| SSH par mot de passe | clés uniquement | ⏳ à faire |

## Droits MQTT (`infra/mosquitto/config/acl`)

| Compte | Utilisé par | Publie | Lit |
|---|---|---|---|
| `boitier` | ESP8266 | `capteurs`, `etat`, `diagnostic` | `commandes`, `config` |
| `simulateur` | simulateur (plan B) | `capteurs`, `etat`, `diagnostic` | `commandes`, `config` |
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

## Tests d'attaque (7 oct. 2026, après durcissement, depuis le WiFi de table `10.42.0.1`)

| Test | Résultat attendu | Obtenu |
|---|---|---|
| `openssl s_client -tls1_1` | refusé | ✅ |
| TLS 1.2 avec suite CBC (`ECDHE-ECDSA-AES128-SHA`) | refusé | ✅ |
| TLS 1.2 `ECDHE-ECDSA-AES256-GCM-SHA384` (suite négociée par l'ESP8266) | accepté, certificat vérifié | ✅ |
| Connexion anonyme | refusée | ✅ `not authorised` |
| `simulateur` publie sur `sentinel/commandes` | non relayé | ✅ |
| `simulateur` s'abonne à `sentinel/capteurs` | rien reçu | ✅ |
| Boîtier réel après redémarrage du broker durci | reconnecté seul | ✅ `u'boitier'`, TLS 1.2 AES256-GCM |

**Preuve pour le jury** : Wireshark sur l'interface `ap0` (WiFi de table), filtre `tcp.port == 8883` → uniquement des `Application Data` TLS illisibles. Les logs du broker montrent le compte et le chiffrement de chaque client :

```bash
docker logs sentinel-mosquitto | grep -E "connected|negotiated"   # compte (u'...') et suite TLS de chaque client
```

## Authentification du dashboard et de l'API

```bash
python3 security/set-dashboard-password.py      # identifiant + mot de passe (12 car. min.), crée API_TOKEN
cd infra && docker compose up -d                # l'API relit infra/.env
```

| Qui | Comment | Accès |
|---|---|---|
| Superviseur (navigateur) | page `/login.html` → cookie de session | tout le dashboard et l'API |
| IA anomalies (conteneur) | `Authorization: Bearer $API_TOKEN` | `POST /alerts`, `/analysis` |
| Vision (`ia/vision/detect.py`) | idem, jeton lu dans `infra/.env` | `POST /alerts`, `/vision/frame`, `/vision/stats` |
| Tout le monde | — | `GET /api/v1/health`, page de connexion |

Tests (7 oct. 2026, depuis le WiFi de table, sans session) : `GET /` → 303 vers `/login.html` ; `/metrics`, `/commands`, `/config`, `/vision/frame`, `/analysis`, `/alerts`, `/vision/stream` → **401** ; WebSocket → **403** ; `/docs` → redirigé.
Jeton IA sur `/analysis` → 204, sur `/commands` → **401** ; faux jeton → 401. Après déconnexion, l'ancien cookie → 401. 6ᵉ mauvais mot de passe → **429**.

## HTTPS du dashboard et de l'API

```bash
./security/init-https.sh          # certificat infra/api-certs/api.crt signé par notre AC (SAN 10.42.0.1, localhost, api)
cd infra && docker compose up -d
```

Dashboard : **https://10.42.0.1:8000** (WiFi de table) ou **https://localhost:8000**. Le port 8000 ne parle **que** TLS.

**Faire confiance à notre AC dans le navigateur** (une fois par navigateur ; fichier `infra/mosquitto/certs/ca.crt`) :
- Chrome / Chromium / Brave : Paramètres → Confidentialité et sécurité → Sécurité → Gérer les certificats → Autorités → Importer → cocher « Faire confiance pour identifier des sites web ».
- Firefox : Paramètres → Vie privée et sécurité → Certificats → Afficher les certificats → Autorités → Importer → cocher « identifier des sites web ».

Le détecteur d'anomalies vérifie le certificat avec `SSL_CERT_FILE=/certs/ca.crt` (nom `api`), le script vision avec `--ca` (défaut : `infra/mosquitto/certs/ca.crt`).

Tests (7 oct. 2026, depuis `10.42.0.1`) :

| Test | Attendu | Obtenu |
|---|---|---|
| `curl http://10.42.0.1:8000/` (en clair) | pas de réponse HTTP | ✅ |
| `curl --cacert ca.crt https://10.42.0.1:8000/` et `https://localhost:8000/` | certificat valide | ✅ 200 |
| `curl https://10.42.0.1:8000/` sans notre AC | refusé | ✅ erreur 60 (certificat inconnu) |
| `openssl s_client -tls1_1` | refusé | ✅ |
| TLS 1.2 avec suite CBC | refusé | ✅ |
| Négociation par défaut | TLS 1.3 | ✅ `TLS_AES_256_GCM_SHA384` |
| Client TLS 1.2 | suite forte | ✅ `ECDHE-ECDSA-AES256-GCM-SHA384` |
| Détecteur d'anomalies → `https://api:8000` | accepté, certificat vérifié | ✅ 204 |

**Preuve pour le jury** : Wireshark sur `ap0`, filtre `tcp.port == 8000` pendant une connexion au dashboard → uniquement du TLS, le mot de passe n'apparaît pas.

## Isolation des conteneurs

Vérification (7 oct. 2026) :

```bash
for c in api anomalies mosquitto db; do docker exec sentinel-$c grep -E "CapEff|NoNewPrivs" /proc/1/status; done   # CapEff 0, NoNewPrivs 1
docker top sentinel-db -o user,comm                     # utilisateur 70 (postgres), pas root
docker exec sentinel-api touch /app/x                   # Read-only file system
docker stats --no-stream                                # limites mémoire
```

## Pare-feu MQTT

```bash
sudo ./security/init-firewall.sh     # ESP_IP=... ESP_MAC=... pour un autre boîtier ; --remove pour retirer
```

Ports 1883/8883 de l'hôte : seul le boîtier (`10.42.0.239`, MAC `24:a1:60:2a:a9:d4`, arrivant par `ap0`) et l'hôte lui-même (`127.0.0.1`) passent. Le trafic entre conteneurs (API, IA → `mosquitto`) n'est pas concerné.
Les règles sont en nftables (table `inet sentinel_mqtt`, priorité -150) et non en UFW : Docker publie ses ports par DNAT, qu'UFW ne voit pas. Rechargées au démarrage par `sentinel-firewall.service`. L'IP de l'ESP est réservée dans le DHCP du hotspot (`/etc/NetworkManager/dnsmasq-shared.d/sentinel-esp.conf`).

```bash
sudo nft list table inet sentinel_mqtt     # règles + compteurs (acceptés / refusés)
journalctl -k | grep sentinel-mqtt         # tentatives refusées
```

## Reste à faire

- Hardening de l'hôte : UFW, SSH par clé, Docker
- Rapport d'audit du pentest croisé (jeudi)
