"""État partagé du boîtier + diffusion WebSocket vers les dashboards."""

import asyncio
import json
import threading
import time

from fastapi import WebSocket

from .config import DEVICE_ID


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lock = threading.Lock()
        self.last_seen = 0.0  # time.monotonic() de la dernière mesure
        self.enabled_since: dict[str, object] = {}  # capteur -> datetime de sa remise en service
        self.state = {
            "device": DEVICE_ID,
            "online": False,
            "simule": False,
            "config": {"dht22": True, "mq2": True, "pir": True, "interval_ms": 2000},
            "buzzer": False,
            "led": "vert",
            "last_measure": None,
        }

    def snapshot_state(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))

    def touch(self):
        self.last_seen = time.monotonic()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, message: dict):
        text = json.dumps(message, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)

    def publish(self, msg_type: str, data: dict):
        """Diffuse un message à tous les dashboards. Appelable depuis n'importe quel thread."""
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.broadcast({"type": msg_type, "data": data}), self.loop)


hub = Hub()
