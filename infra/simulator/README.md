# Simulateur ESP8266

Se fait passer pour le boîtier : publie de fausses mesures sur Mosquitto au même format que le vrai firmware, et réagit aux commandes.
Permet au backend, au dashboard et à l'IA de travailler sans la carte. Sert aussi de plan B en démo.

## Installation

```bash
cd infra
docker compose up -d                 # lance Mosquitto (MQTTS localhost:8883)
cd simulator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

Le simulateur se connecte en **MQTTS** avec le compte `boitier` (le même que l'ESP8266) : mot de passe lu dans `infra/.env`, AC dans `infra/mosquitto/certs/ca.crt` (les deux créés par `security/init-mqtt.sh`).

```bash
python simulator.py                                  # fonctionnement normal
python simulator.py --scenario incident              # incident après 30 s
python simulator.py --scenario mix --csv data.csv    # enregistre un dataset
python simulator.py --scenario normal --fast --duration 3600 --csv normal.csv   # 1 h de données en 1 s
```

`--fast` génère un dataset **hors ligne** : temps simulé (`ts` = départ + n × intervalle), rien n'est publié sur MQTT (`--csv` obligatoire).
Les dérives sont exprimées par minute de temps simulé : elles ne dépendent pas de `--interval`, et restent dans les plages physiques des capteurs.

| Scénario | Comportement |
|---|---|
| `normal` | valeurs stables avec bruit, passages rares |
| `surchauffe` | la température monte lentement (+0,3 °C/min, plafond ~60 °C) |
| `fuite_gaz` | le gaz monte (+60 /min) jusqu'à saturation (1023) |
| `incident` | +0,3 °C/min + micro-dérive du gaz (+3 /min, plafond +150) — cas du sujet ; 40 °C atteint vers +60 min |
| `intrusion` | présence continue (PIR) |
| `panne` | le boîtier coupe sa connexion → `online: false` |
| `mix` | après `--start-after` : incident 5 min, normal 3 min, intrusion 1 min, normal 2 min, en boucle |

## Contrat MQTT (identique au vrai firmware)

| Topic | Sens | Exemple |
|---|---|---|
| `sentinel/capteurs` | boîtier → serveur | `{"device":"sentinel-01","temp":22.4,"hum":45.1,"gaz":302,"presence":false,"ts":1791196244}` |
| `sentinel/etat` | boîtier → serveur (retained) | `{"device":"sentinel-01","online":true,"config":{...},"buzzer":false,"led":"vert"}` |
| `sentinel/commandes` | serveur → boîtier | `{"buzzer":true,"led":"rouge"}` |
| `sentinel/config` | serveur → boîtier | `{"dht22":true,"mq2":true,"pir":false,"interval_ms":2000}` |

Un capteur désactivé renvoie `null`. Le gaz est la valeur brute de l'entrée analogique (0-1023).

## Tester à la main

Avec le compte `api` (le seul autorisé à tout lire et à envoyer des ordres) :

```bash
source infra/.env
MQ="-h localhost -p 8883 --cafile /mosquitto/certs/ca.crt -u api -P $MQTT_API_PASSWORD -i outil-$RANDOM"
docker exec sentinel-mosquitto mosquitto_sub $MQ -t 'sentinel/#' -v          # tout écouter
docker exec sentinel-mosquitto mosquitto_pub $MQ -t sentinel/commandes -m '{"buzzer":true}'
docker exec sentinel-mosquitto mosquitto_pub $MQ -t sentinel/config -m '{"pir":false}'
```
