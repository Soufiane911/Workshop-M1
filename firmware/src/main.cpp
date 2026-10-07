// Sentinel-X — firmware du boîtier (ESP8266 NodeMCU Lolin v3)
//
// Au démarrage : autotest des capteurs, connexion au WiFi de table, puis à Mosquitto.
// En boucle (sans delay bloquant) : lecture des capteurs, publication MQTT,
// affichage OLED, réception des commandes et de la configuration.
// Même format JSON que le simulateur (infra/simulator) : l'API ne voit pas la différence.
// Sécurité : MQTTS (TLS 1.2) avec vérification du certificat du broker par l'AC embarquée,
// et authentification par compte (ACL côté Mosquitto : voir infra/mosquitto/config/acl).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>

#include "config.h"
#include "secrets.h"
#if __has_include("ca_cert.h")
#include "ca_cert.h"
#else
#error "firmware/include/ca_cert.h absent : lancer security/init-mqtt.sh sur le PC serveur"
#endif
#if !defined(MQTT_USER) || !defined(MQTT_PASS)
#error "secrets.h : définir MQTT_USER et MQTT_PASS (voir secrets.example.h)"
#endif
#ifndef BUILD_EPOCH
#define BUILD_EPOCH 1800000000  // repli hors PlatformIO (janv. 2027) : doit tomber dans la validité du certificat
#endif

BearSSL::WiFiClientSecure net;
BearSSL::X509List caCert(CA_CERT);
PubSubClient mqtt(net);
Adafruit_SSD1306 oled(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
DHT* dht = nullptr;

// ---------- État ----------
struct Config {
  bool dht22 = true, mq2 = true, pir = true;
  uint32_t interval = MEASURE_INTERVAL_MS;
} cfg;

struct Mesure {
  float temp = NAN, hum = NAN;
  int gaz = -1;
  bool presence = false;
} last;

int dhtPin = PIN_DHT;
bool oledOk = false;
bool buzzer = false;
bool ledRouge = false;
uint32_t tMesure = 0, tDht = 0, tOled = 0, tReconnect = 0, tServeurOk = 0;
uint32_t pirDebut = 0;  // début de l'impulsion PIR en cours (mesure de la temporisation)
bool pirAvant = false;
bool mflnTeste = false;  // négociation de la taille des trames TLS faite une fois

// ---------- Utilitaires ----------

const char* pinName(int gpio) {
  switch (gpio) {
    case D0: return "D0"; case D1: return "D1"; case D2: return "D2"; case D3: return "D3";
    case D4: return "D4"; case D5: return "D5"; case D6: return "D6"; case D7: return "D7";
    case D8: return "D8"; default: return "?";
  }
}

void setOutput(int pin, bool on) {
  if (pin >= 0) digitalWrite(pin, on ? HIGH : LOW);
}

void setBuzzer(bool on) {
  setOutput(PIN_BUZZER, BUZZER_ACTIVE_LOW ? !on : on);
}

void appliquerSorties() {
  setBuzzer(buzzer);
  setOutput(PIN_LED_ROUGE, ledRouge);
  setOutput(PIN_LED_VERTE, !ledRouge);
}

// ---------- Autotest ----------

// Cherche le DHT22 sur les broches libres : la première qui répond est retenue.
int detecterDht() {
  const int candidates[] = {D6, D7, D4, D3, D0};
  for (int pin : candidates) {
    if (pin == PIN_PIR || pin == PIN_BUZZER || pin == PIN_LED_ROUGE || pin == PIN_LED_VERTE) continue;
    DHT test(pin, DHT22);
    test.begin();
    delay(2100);  // le DHT22 a besoin de 2 s avant la première lecture
    if (!isnan(test.readTemperature())) return pin;
  }
  return -1;
}

void autotest() {
  Serial.println(F("\n===== AUTOTEST SENTINEL-X ====="));

  // Bus I2C : liste des appareils présents
  Wire.begin();
  String i2c;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) i2c += "0x" + String(a, HEX) + " ";
  }
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  Serial.printf("OLED   : %s (I2C trouvé : %s)\n", oledOk ? "OK" : "ABSENT", i2c.length() ? i2c.c_str() : "rien");

  // DHT22
  if (dhtPin < 0) dhtPin = detecterDht();
  if (dhtPin >= 0) {
    dht = new DHT(dhtPin, DHT22);
    dht->begin();
  }
  Serial.printf("DHT22  : %s\n", dhtPin >= 0 ? (String("OK sur ") + pinName(dhtPin)).c_str() : "ABSENT (aucune broche ne répond)");

  // MQ-2 : bloqué à 0 ou 1023 = mauvais branchement probable
  int gaz = analogRead(PIN_MQ2);
  Serial.printf("MQ-2   : %d %s\n", gaz, gaz <= 5 ? "(SUSPECT : 0, non alimenté ?)" : gaz >= 1020 ? "(SUSPECT : saturé)" : "(OK, préchauffage 1-2 min)");

  // PIR
  Serial.printf("PIR    : %s (D5) — 1 juste après la mise sous tension est normal (chauffe ~1 min)\n",
                digitalRead(PIN_PIR) ? "1" : "0");
  Serial.printf("Buzzer : %s | LED : %s\n", PIN_BUZZER >= 0 ? pinName(PIN_BUZZER) : "non configuré",
                PIN_LED_ROUGE >= 0 ? pinName(PIN_LED_ROUGE) : "non configurée");
  Serial.println(F("==============================="));
}

void publierDiagnostic() {
  JsonDocument d;
  d["device"] = DEVICE_ID;
  d["fw"] = FW_VERSION;
  d["oled"] = oledOk;
  d["dht22_pin"] = dhtPin >= 0 ? pinName(dhtPin) : nullptr;
  d["mq2_raw"] = analogRead(PIN_MQ2);
  d["ip"] = WiFi.localIP().toString();
  d["rssi"] = WiFi.RSSI();
  char buf[256];
  serializeJson(d, buf);
  mqtt.publish(T_DIAG, buf, true);
}

// ---------- OLED ----------

void afficher() {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);
  oled.println(F("SENTINEL-X"));
  oled.printf("WiFi %s\n", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "...");
  oled.printf("MQTTS %s\n", mqtt.connected() ? "OK (TLS)" : "hors ligne");
  oled.println();
  if (cfg.dht22 && !isnan(last.temp)) oled.printf("T %.1fC  H %.0f%%\n", last.temp, last.hum);
  else oled.println(cfg.dht22 ? F("DHT22 --") : F("DHT22 coupe"));
  if (cfg.mq2) oled.printf("Gaz %d\n", last.gaz); else oled.println(F("MQ-2 coupe"));
  oled.printf("PIR %s\n", !cfg.pir ? "coupe" : last.presence ? "PRESENCE" : "-");
  oled.display();
}

// ---------- MQTT ----------

void publierEtat() {
  JsonDocument d;
  d["device"] = DEVICE_ID;
  d["online"] = true;
  d["simule"] = false;
  d["buzzer"] = buzzer;
  d["led"] = ledRouge ? "rouge" : "vert";
  JsonObject c = d["config"].to<JsonObject>();
  c["dht22"] = cfg.dht22;
  c["mq2"] = cfg.mq2;
  c["pir"] = cfg.pir;
  c["interval_ms"] = cfg.interval;
  char buf[256];
  serializeJson(d, buf);
  mqtt.publish(T_ETAT, buf, true);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) {
    Serial.printf("[MQTT] JSON invalide ignoré sur %s\n", topic);
    return;
  }
  if (!strcmp(topic, T_COMMANDES)) {
    if (d["buzzer"].is<bool>()) buzzer = d["buzzer"];
    if (d["led"].is<const char*>()) ledRouge = !strcmp(d["led"], "rouge");
    appliquerSorties();
    Serial.printf("[CMD] buzzer=%s led=%s\n", buzzer ? "ON" : "OFF", ledRouge ? "rouge" : "vert");
  } else if (!strcmp(topic, T_CONFIG)) {
    if (d["dht22"].is<bool>()) cfg.dht22 = d["dht22"];
    if (d["mq2"].is<bool>()) cfg.mq2 = d["mq2"];
    if (d["pir"].is<bool>()) cfg.pir = d["pir"];
    if (d["interval_ms"].is<uint32_t>() && d["interval_ms"] >= 500) cfg.interval = d["interval_ms"];
    Serial.printf("[CFG] dht22=%d mq2=%d pir=%d intervalle=%lu ms\n", cfg.dht22, cfg.mq2, cfg.pir, cfg.interval);
  }
  publierEtat();
}

// Reconnexion non bloquante : une tentative toutes les RECONNECT_PERIOD_MS
void maintenirConnexion() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  if (millis() - tReconnect < RECONNECT_PERIOD_MS) return;
  tReconnect = millis();

  // Testament : si la carte disparaît, le broker annonce "online": false à sa place
  char will[64];
  snprintf(will, sizeof will, "{\"device\":\"%s\",\"online\":false}", DEVICE_ID);
  // Trames TLS réduites à 1 Ko si le broker l'accepte : ~25 Ko de RAM économisés
  if (!mflnTeste) {
    mflnTeste = true;
    if (net.probeMaxFragmentLength(MQTT_HOST, MQTT_PORT, 1024)) {
      net.setBufferSizes(1024, 1024);
      Serial.println(F("[TLS] fragments de 1 Ko acceptés par le broker"));
    }
  }
  Serial.printf("[MQTT] connexion TLS à %s:%d… ", MQTT_HOST, MQTT_PORT);
  if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS, T_ETAT, 1, true, will)) {
    Serial.println(F("OK"));
    mqtt.subscribe(T_COMMANDES, 1);
    mqtt.subscribe(T_CONFIG, 1);
    publierEtat();
    publierDiagnostic();
  } else {
    // -2 = échec réseau/TLS (certificat refusé ?), 4/5 = identifiants refusés
    char err[80];
    int code = net.getLastSSLError(err, sizeof err);
    Serial.printf("échec (code %d)%s%s\n", mqtt.state(), code ? " TLS : " : "", code ? err : "");
  }
}

// ---------- Mesures ----------

void lireEtPublier() {
  if (cfg.dht22 && dht && millis() - tDht >= DHT_MIN_PERIOD_MS) {
    tDht = millis();
    float t = dht->readTemperature(), h = dht->readHumidity();
    if (!isnan(t) && !isnan(h)) { last.temp = t; last.hum = h; }
    else { last.temp = NAN; last.hum = NAN; }  // lecture ratée : envoyée comme null
  }
  last.gaz = analogRead(PIN_MQ2);

  JsonDocument d;
  d["device"] = DEVICE_ID;
  if (cfg.dht22 && !isnan(last.temp)) { d["temp"] = roundf(last.temp * 10) / 10; d["hum"] = roundf(last.hum * 10) / 10; }
  else { d["temp"] = nullptr; d["hum"] = nullptr; }
  if (cfg.mq2) d["gaz"] = last.gaz; else d["gaz"] = nullptr;
  if (cfg.pir) d["presence"] = last.presence; else d["presence"] = nullptr;
  d["uptime_s"] = millis() / 1000;

  char buf[200];
  serializeJson(d, buf);
  bool envoye = mqtt.connected() && mqtt.publish(T_CAPTEURS, buf);
  if (envoye) tServeurOk = millis();

  Serial.printf("T=%s H=%s gaz=%d pir=%d | wifi %s mqtt %s\n",
                isnan(last.temp) ? "nan" : String(last.temp, 1).c_str(),
                isnan(last.hum) ? "nan" : String(last.hum, 1).c_str(),
                last.gaz, last.presence,
                WiFi.status() == WL_CONNECTED ? "OK" : "--", envoye ? "envoyé" : "--");
}

// Le PIR est lu en continu : on mesure la durée de chaque impulsion (= temporisation réglée)
void surveillerPir() {
  bool p = digitalRead(PIN_PIR);
  if (p && !pirAvant) pirDebut = millis();
  if (!p && pirAvant) Serial.printf("[PIR] impulsion de %.1f s (temporisation réglée)\n", (millis() - pirDebut) / 1000.0);
  pirAvant = p;
  last.presence = p;
}

// Mode secours : sans serveur, le boîtier reste autonome et alerte sur place
void modeSecours() {
  static bool actif = false;
  bool serveurPerdu = millis() - tServeurOk > SECOURS_AFTER_MS;
  if (serveurPerdu != actif) {
    actif = serveurPerdu;
    Serial.println(actif ? F("[SECOURS] serveur injoignable : alertes locales activées") : F("[SECOURS] serveur de retour"));
    if (!actif) appliquerSorties();  // retour aux sorties demandées par le dashboard
  }
  if (!serveurPerdu) return;
  bool alerte = cfg.pir && last.presence;
  setOutput(PIN_LED_ROUGE, alerte || ledRouge);
  setOutput(PIN_LED_VERTE, !(alerte || ledRouge));
  // Bips courts tant qu'une présence est détectée
  setBuzzer(buzzer || (alerte && (millis() / 250) % 2));
}

// ---------- Programme principal ----------

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PIN_PIR, INPUT);
  if (PIN_BUZZER >= 0) {
    setBuzzer(false);  // niveau « silence » fixé avant de passer en sortie : pas de bip au démarrage
    pinMode(PIN_BUZZER, OUTPUT);
  }
  if (PIN_LED_ROUGE >= 0) pinMode(PIN_LED_ROUGE, OUTPUT);
  if (PIN_LED_VERTE >= 0) pinMode(PIN_LED_VERTE, OUTPUT);
  appliquerSorties();

  autotest();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connexion à « %s »…\n", WIFI_SSID);

  // TLS : seul un broker signé par notre AC est accepté. Sans RTC ni Internet sur le réseau
  // de table, l'horloge de validation des certificats est fixée à la date de compilation.
  net.setTrustAnchors(&caCert);
  net.setX509Time(BUILD_EPOCH);
  Serial.printf("[TLS] AC chargée, horloge des certificats : %lu\n", (unsigned long)BUILD_EPOCH);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setBufferSize(512);
  tServeurOk = millis();
}

void loop() {
  static wl_status_t wifiAvant = WL_IDLE_STATUS;
  wl_status_t w = WiFi.status();
  if (w != wifiAvant) {
    if (w == WL_CONNECTED) Serial.printf("[WiFi] connecté, IP %s, signal %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
    else if (wifiAvant == WL_CONNECTED) Serial.println(F("[WiFi] connexion perdue, reconnexion automatique…"));
    wifiAvant = w;
  }

  maintenirConnexion();
  mqtt.loop();
  surveillerPir();

  if (millis() - tMesure >= cfg.interval) {
    tMesure = millis();
    lireEtPublier();
  }
  if (millis() - tOled >= OLED_PERIOD_MS) {
    tOled = millis();
    afficher();
  }
  modeSecours();
}
