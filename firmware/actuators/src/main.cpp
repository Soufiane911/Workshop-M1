// SENTINEL-X : exécution des commandes d'actionneurs (buzzer, LEDs) reçues en MQTTS.
// Câblage NodeMCU : buzzer D5, LED verte D6, LED rouge D7 (actifs à l'état haut, résistance ~220 Ω sur les LEDs).
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "secrets.h"

struct Actuator { const char* name; uint8_t pin; bool on; bool timed; uint32_t deadline; uint32_t maxMs; };
Actuator acts[] = {
  {"buzzer",    D5, false, false, 0, 10000},   // sécurité : le buzzer se coupe seul après 10 s
  {"led_green", D6, false, false, 0, 0},
  {"led_red",   D7, false, false, 0, 0},
};
const uint32_t PULSE_MS = 500;

BearSSL::WiFiClientSecure net;
BearSSL::X509List caList(CA_CERT);
PubSubClient mqtt(net);
String tCmd = String("sentinel/") + DEVICE_ID + "/cmd";
String tAck = String("sentinel/") + DEVICE_ID + "/ack";
String tStatus = String("sentinel/") + DEVICE_ID + "/status";
uint32_t lastTry = 0;

void publishAck(const Actuator& a) {
  JsonDocument d; d["actuator"] = a.name; d["state"] = a.on ? "on" : "off";
  char buf[96]; size_t n = serializeJson(d, buf);
  mqtt.publish(tAck.c_str(), (const uint8_t*)buf, n, false);
}

void setActuator(Actuator& a, bool on, uint32_t durMs) {
  a.on = on; digitalWrite(a.pin, on ? HIGH : LOW);
  a.timed = on && durMs > 0; a.deadline = millis() + durMs;
  publishAck(a);
}

void onCommand(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;                 // JSON invalide : ignoré
  const char* name = d["actuator"] | ""; const char* st = d["state"] | "";
  for (auto& a : acts) {
    if (strcmp(a.name, name)) continue;                         // liste blanche stricte
    if (!strcmp(st, "on"))         setActuator(a, true, a.maxMs);
    else if (!strcmp(st, "off"))   setActuator(a, false, 0);
    else if (!strcmp(st, "pulse")) setActuator(a, true, PULSE_MS);
  }
}

void connectMqtt() {
  if (millis() - lastTry < 5000) return;                        // reconnexion non bloquante
  lastTry = millis();
  if (!mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS, tStatus.c_str(), 1, true, "offline")) return;
  mqtt.publish(tStatus.c_str(), "online", true);                // LWT : "offline" si coupure brutale
  mqtt.subscribe(tCmd.c_str(), 1);
  for (auto& a : acts) publishAck(a);                           // resynchronise le panneau
}

void setup() {
  Serial.begin(115200);
  for (auto& a : acts) { pinMode(a.pin, OUTPUT); digitalWrite(a.pin, LOW); }
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  configTime(0, 0, "pool.ntp.org");                             // l'heure est nécessaire à la validation TLS
  while (time(nullptr) < 1700000000) delay(300);
  net.setTrustAnchors(&caList);                                 // vérification du certificat du broker
  mqtt.setServer(MQTT_HOST, MQTT_PORT); mqtt.setCallback(onCommand);
}

void loop() {
  if (!mqtt.connected()) connectMqtt(); else mqtt.loop();
  for (auto& a : acts)                                          // extinction automatique (impulsion / timeout)
    if (a.on && a.timed && (int32_t)(millis() - a.deadline) >= 0) setActuator(a, false, 0);
}
