"""Pont MQTT : écoute le boîtier, enregistre les mesures, relaie les ordres."""

import json
import logging
import time

import paho.mqtt.client as mqtt

from .config import (DEVICE_ID, MQTT_HOST, MQTT_PORT, PIR_ALERT_COOLDOWN_S,
                     T_CAPTEURS, T_ETAT)
from .db import Measure, SessionLocal, utcnow
from .hub import hub
from .services import create_alert, set_online

log = logging.getLogger("sentinel.mqtt")

SECURITY_SENSORS = {"pir": "PIR (présence)", "mq2": "MQ-2 (gaz)"}


def _num(value, kind):
    try:
        return kind(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class MqttBridge:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel-api")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.connected = False
        self._last_presence = False
        self._last_pir_alert = 0.0

    def start(self):
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()

    def publish(self, topic: str, payload: dict, retain: bool = False) -> bool:
        if not self.connected:
            return False
        info = self.client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    # --- callbacks (thread MQTT) ---

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("connexion MQTT refusée : %s", reason_code)
            return
        self.connected = True
        log.info("connecté à Mosquitto %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe([(T_CAPTEURS, 0), (T_ETAT, 1)])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("déconnecté de Mosquitto (%s)", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            if not isinstance(data, dict):
                raise ValueError("objet JSON attendu")
        except (json.JSONDecodeError, ValueError):
            log.warning("message ignoré sur %s : JSON invalide", msg.topic)
            return
        try:
            if msg.topic == T_CAPTEURS:
                self._handle_measure(data)
            elif msg.topic == T_ETAT:
                self._handle_state(data)
        except Exception:
            log.exception("erreur de traitement du message %s", msg.topic)

    def _handle_measure(self, data: dict):
        measure = Measure(
            device=str(data.get("device", DEVICE_ID))[:64],
            temp=_num(data.get("temp"), float),
            hum=_num(data.get("hum"), float),
            gaz=_num(data.get("gaz"), int),
            presence=data.get("presence") if isinstance(data.get("presence"), bool) else None,
        )
        with SessionLocal() as s:
            s.add(measure)
            s.commit()
            payload = measure.to_dict()

        hub.touch()
        with hub.lock:
            hub.state["last_measure"] = payload
        set_online(True)
        hub.publish("measure", payload)

        # Front montant du PIR → alerte (avec délai anti-rafale)
        presence = bool(measure.presence)
        now = time.monotonic()
        if presence and not self._last_presence and now - self._last_pir_alert > PIR_ALERT_COOLDOWN_S:
            self._last_pir_alert = now
            create_alert("capteur", "presence", "warning", "Mouvement détecté par le PIR")
        self._last_presence = presence

    def _handle_state(self, data: dict):
        with hub.lock:
            old_config = dict(hub.state["config"])
            for key in ("buzzer", "led", "simule"):
                if key in data:
                    hub.state[key] = data[key]
            if isinstance(data.get("config"), dict):
                hub.state["config"].update(data["config"])
            new_config = dict(hub.state["config"])
            # mémorise la remise en service : le diagnostic ignore les lectures d'avant
            for key in ("dht22", "mq2", "pir"):
                if old_config.get(key) is False and new_config.get(key) is True:
                    hub.enabled_since[key] = utcnow()

        if data.get("online") is False:
            set_online(False, "connexion perdue")
        hub.publish("state", hub.snapshot_state())

        for key, label in SECURITY_SENSORS.items():
            if old_config.get(key, True) and new_config.get(key) is False:
                create_alert("systeme", "capteur_desactive", "warning", f"Capteur de sécurité désactivé : {label}")


bridge = MqttBridge()
