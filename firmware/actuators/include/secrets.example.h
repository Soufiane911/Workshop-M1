// Copier en secrets.h (ignoré par Git) et renseigner. NE JAMAIS committer secrets.h.
#pragma once
#define WIFI_SSID   "wifi-table"
#define WIFI_PASS   "..."
#define MQTT_HOST   "192.168.10.10"
#define MQTT_PORT   8883
#define MQTT_USER   "esp-01"
#define MQTT_PASS   "..."
#define DEVICE_ID   "esp-01"
// Certificat de l'autorité (CA) qui a signé le certificat de Mosquitto
static const char CA_CERT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
)EOF";
