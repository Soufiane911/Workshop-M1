# Firmware ESP8266

Projet PlatformIO — carte `esp12e`, framework `arduino`.

- Capteurs : DHT22, MQ-2, PIR
- Sorties : OLED I2C (0x3C), buzzer, LED bicolore
- Envoi des mesures en MQTTS vers Mosquitto (topic `sentinel/capteurs`)
- Réception des commandes (topic `sentinel/commandes`)

## Avant de compiler

1. Sur le PC serveur : `./security/init-mqtt.sh` → crée `include/ca_cert.h` (AC du broker) et les mots de passe dans `infra/.env`
2. `cp include/secrets.example.h include/secrets.h` puis renseigner le WiFi et `MQTT_PASS` (= `MQTT_BOITIER_PASSWORD` de `infra/.env`)
3. `pio run -t upload && pio device monitor`

## Sécurité (MQTTS)

- `BearSSL::WiFiClientSecure` + `setTrustAnchors` : le boîtier refuse tout broker dont le certificat n'est pas signé par notre AC (anti-MitM)
- Pas d'horloge ni d'Internet sur la table : la validité du certificat est vérifiée par rapport à la **date de compilation** (`BUILD_EPOCH`)
- Compte `boitier` : ne peut publier que ses mesures/état et lire les ordres (ACL Mosquitto)
- CPU à 160 MHz pour accélérer la poignée de main TLS
- Après `init-mqtt.sh --force` (nouvelle AC) : **recompiler et re-flasher**
