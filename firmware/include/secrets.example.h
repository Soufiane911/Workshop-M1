// Copier ce fichier en secrets.h et renseigner les vraies valeurs.
// secrets.h est ignoré par Git : aucun mot de passe ne doit être commité.
#pragma once

#define WIFI_SSID "Sentinel-X-Table"
#define WIFI_PASS "mot-de-passe-du-wifi"

#define MQTT_HOST "10.42.0.1"   // adresse du PC serveur sur le WiFi de table (doit figurer dans son certificat)
#define MQTT_PORT 8883          // MQTTS uniquement
#define MQTT_USER "boitier"
#define MQTT_PASS "valeur-de-MQTT_BOITIER_PASSWORD-dans-infra/.env"
