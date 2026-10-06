// Sentinel-X — câblage et paramètres du boîtier
#pragma once
#include <Arduino.h>

#define DEVICE_ID "sentinel-01"
#define FW_VERSION "1.0.0"

// ---------- Câblage ----------
// PIR HC-SR501 : VCC sur VU (5 V), OUT sur D5, GND sur G
#define PIN_PIR D5
// MQ-2 : sortie analogique sur A0 (seule entrée analogique de l'ESP8266)
#define PIN_MQ2 A0
// OLED I2C 0x3C : SDA sur D2, SCL sur D1 (bus I2C par défaut)
#define OLED_ADDR 0x3C
#define OLED_WIDTH 128
#define OLED_HEIGHT 64
// DHT22 : -1 = broche détectée automatiquement au démarrage
#define PIN_DHT -1
// Buzzer et LED bicolore : -1 = non branché (les commandes sont acceptées mais sans effet)
#define PIN_BUZZER -1
#define PIN_LED_ROUGE -1
#define PIN_LED_VERTE -1

// ---------- MQTT ----------
#define T_CAPTEURS "sentinel/capteurs"
#define T_ETAT "sentinel/etat"
#define T_COMMANDES "sentinel/commandes"
#define T_CONFIG "sentinel/config"
#define T_DIAG "sentinel/diagnostic"

// ---------- Temps (ms) ----------
#define MEASURE_INTERVAL_MS 2000   // modifiable à distance via sentinel/config
#define DHT_MIN_PERIOD_MS 2000     // le DHT22 ne supporte pas plus d'une lecture toutes les 2 s
#define OLED_PERIOD_MS 1000
#define RECONNECT_PERIOD_MS 5000
#define SECOURS_AFTER_MS 15000     // mode secours si le serveur ne répond plus depuis ce délai
