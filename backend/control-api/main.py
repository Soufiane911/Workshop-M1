"""API de Contrôle Réactif : panneau web -> MQTT -> ESP8266, et retour d'état en WebSocket.

    uvicorn main:app --host 0.0.0.0 --port 8000
Topics : sentinel/<id>/cmd (API -> ESP) | sentinel/<id>/ack, sentinel/<id>/status (ESP -> API)
"""
import asyncio
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("control")
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["API_TOKEN"]  # obligatoire : pas de valeur par défaut
states: dict[str, dict] = {}     # device_id -> {"online": bool, "buzzer": "on"|"off", ...}
clients: set[WebSocket] = set()
loop: asyncio.AbstractEventLoop | None = None

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


class Command(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    actuator: Literal["buzzer", "led_green", "led_red"]   # liste blanche
    state: Literal["on", "off", "pulse"]


def check_token(authorization: str = Header(default="")):
    if not hmac.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="Token invalide")


async def broadcast(msg: dict):
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            clients.discard(ws)


def on_connect(c, *_):
    c.subscribe([("sentinel/+/ack", 1), ("sentinel/+/status", 1)])
    log.info("MQTT connecté")


def on_message(_c, _u, m):
    try:
        device = m.topic.split("/")[1]
        st = states.setdefault(device, {})
        if m.topic.endswith("/status"):
            st["online"] = m.payload.decode() == "online"
            msg = {"type": "status", "device_id": device, "online": st["online"]}
        else:
            d = json.loads(m.payload)
            if d["actuator"] not in ("buzzer", "led_green", "led_red") or d["state"] not in ("on", "off"):
                return
            st[d["actuator"]] = d["state"]
            msg = {"type": "ack", "device_id": device, "actuator": d["actuator"], "state": d["state"]}
    except (KeyError, ValueError, IndexError):
        return
    if loop:
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)


@asynccontextmanager
async def lifespan(_app):
    global loop
    loop = asyncio.get_running_loop()
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
    if os.getenv("MQTT_CA_CERT"):
        client.tls_set(ca_certs=os.environ["MQTT_CA_CERT"])
    client.on_connect, client.on_message = on_connect, on_message
    client.connect_async(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "8883")))
    client.loop_start()   # reconnexion automatique
    yield
    client.loop_stop()


app = FastAPI(title="SENTINEL-X Contrôle Réactif", lifespan=lifespan)


@app.post("/api/v1/commands", status_code=202, dependencies=[Depends(check_token)])
def send_command(cmd: Command):
    info = client.publish(f"sentinel/{cmd.device_id}/cmd",
                          json.dumps({"actuator": cmd.actuator, "state": cmd.state}), qos=1)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise HTTPException(status_code=503, detail="Broker MQTT injoignable")
    return {"status": "sent"}


@app.get("/api/v1/devices/{device_id}/state", dependencies=[Depends(check_token)])
def device_state(device_id: str):
    return states.get(device_id, {})


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    if not hmac.compare_digest(token, TOKEN):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    clients.add(websocket)
    try:
        await websocket.send_json({"type": "snapshot", "states": states})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


PANEL = Path(os.getenv("PANEL_DIR", Path(__file__).resolve().parents[2] / "dashboard" / "control-panel"))
if PANEL.is_dir():
    app.mount("/", StaticFiles(directory=PANEL, html=True), name="panel")
