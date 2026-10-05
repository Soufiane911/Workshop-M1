"""Service d'inférence branché sur le broker Mosquitto.

    ESP8266 --(MQTTS)--> sentinel/<device_id>/sensors --> [ce service] --> sentinel/<device_id>/ai/maintenance
                                                                       \\-> POST /api/v1/alerts (si alerte)

Payload attendu de l'ESP8266 (à valider avec l'équipe DEV firmware) :
    {"device_id": "esp-01", "ts": 1760000000, "temperature": 22.4, "humidity": 51.2, "gas": 303, "pir": 0}

Aucun secret en dur : tout passe par variables d'environnement (voir .env.example).
"""
import json
import logging
import os
import ssl

import paho.mqtt.client as mqtt
import requests

from .detector import AnomalyDetector

log = logging.getLogger("maintenance")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "8883"))
USER = os.getenv("MQTT_USERNAME") or None
PASSWORD = os.getenv("MQTT_PASSWORD") or None
CA_CERT = os.getenv("MQTT_CA_CERT") or None
API_URL = os.getenv("API_URL") or None
API_TOKEN = os.getenv("API_TOKEN") or None

TOPIC_IN = "sentinel/+/sensors"
detectors = {}  # un détecteur (fenêtre glissante) par boîtier


def post_alert(device_id, ts, res):
    if not API_URL:
        return
    body = {
        "source": "ai-maintenance", "device_id": device_id, "ts": ts,
        "level": res["level"], "score": res["score"], "details": res["top_features"],
    }
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    try:
        requests.post(API_URL, json=body, headers=headers, timeout=3,
                      verify=CA_CERT if CA_CERT else True)
    except requests.RequestException as e:
        log.warning("POST alerte impossible: %s", e)


def on_message(client, _userdata, msg):
    try:
        data = json.loads(msg.payload)
        device = str(data.get("device_id") or msg.topic.split("/")[1])
        det = detectors.setdefault(device, AnomalyDetector())
        res = det.push(data)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        log.warning("Message ignoré (%s): %s", msg.topic, e)
        return
    if res is None:
        return
    out = {"device_id": device, "ts": data.get("ts"), **res}
    client.publish(f"sentinel/{device}/ai/maintenance", json.dumps(out), qos=1)
    if res["alert"]:
        log.warning("ALERTE %s: %s", device, out)
        post_alert(device, data.get("ts"), res)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if USER:
        client.username_pw_set(USER, PASSWORD)
    if CA_CERT:
        client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_connect = lambda c, *_: (c.subscribe(TOPIC_IN, qos=1), log.info("Connecté, abonné à %s", TOPIC_IN))
    client.on_message = on_message
    client.connect(HOST, PORT, keepalive=30)
    client.loop_forever()


if __name__ == "__main__":
    main()
