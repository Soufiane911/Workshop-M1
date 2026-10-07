"""Sentinel-X — API de supervision (REST + WebSocket)."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from . import auth
from .config import DASHBOARD_DIR, OFFLINE_AFTER_S, SNAPSHOT_DIR, T_COMMANDES, T_CONFIG
from .db import Action, Alert, Measure, SessionLocal, init_db, utcnow
from .diagnostics import compute_sensors
from .forecast import compute_forecast
from .hub import hub
from .mqtt_bridge import bridge
from .services import analysis, create_alert, frames, log_action, save_snapshot, set_online, vision_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sentinel.api")

MAX_FRAME_BYTES = 2 * 1024 * 1024


async def watchdog():
    """Passe le boîtier hors ligne s'il n'envoie plus de mesures."""
    while True:
        await asyncio.sleep(2)
        if hub.state["online"] and time.monotonic() - hub.last_seen > OFFLINE_AFTER_S:
            await asyncio.to_thread(set_online, False, f"aucune mesure depuis {OFFLINE_AFTER_S:.0f} s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    hub.loop = asyncio.get_running_loop()
    bridge.start()
    task = asyncio.create_task(watchdog())
    yield
    task.cancel()
    bridge.stop()


# Documentation interactive désactivée : elle décrirait toute l'API à un attaquant
app = FastAPI(title="Sentinel-X API", version="1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


# --- Authentification (voir auth.py) ---

# Accessibles sans connexion : la page de login et ce qu'elle charge
PUBLIC = {"/api/v1/health", "/api/v1/auth/login", "/login.html", "/style.css", "/js/login.js"}
# Seules routes ouvertes au jeton des modules IA (en plus de la session)
MACHINE = {("POST", "/api/v1/alerts"), ("POST", "/api/v1/analysis"),
           ("POST", "/api/v1/vision/frame"), ("POST", "/api/v1/vision/stats")}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC:
        return await call_next(request)
    user = auth.sessions.user(request.cookies.get(auth.COOKIE))
    if user is None and (request.method, path) in MACHINE and auth.check_token(request.headers.get("authorization")):
        user = "module-ia"
    if user is None:
        if path.startswith(("/api/", "/snapshots/")):
            return JSONResponse({"detail": "authentification requise"}, status_code=401)
        return RedirectResponse("/login.html", status_code=303)
    request.state.user = user
    response = await call_next(request)
    # Pages et données du dashboard : jamais gardées en cache (bouton « précédent » après déconnexion)
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob:; connect-src 'self'; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'")
    return response


# --- Schémas ---

class AlertIn(BaseModel):
    """Alerte envoyée par l'IA (vision, anomalies) ou un autre module.
    Les champs supplémentaires (persons, confidence...) sont gardés dans `details`."""

    model_config = ConfigDict(extra="allow")
    source: str = Field(max_length=32, examples=["vision"])
    type: str = Field(max_length=32, examples=["intrusion"])
    level: Literal["info", "warning", "critical"] = "warning"
    message: str = Field(max_length=500)


class CommandIn(BaseModel):
    buzzer: bool | None = None
    led: Literal["vert", "rouge"] | None = None


class ConfigIn(BaseModel):
    dht22: bool | None = None
    mq2: bool | None = None
    pir: bool | None = None
    interval_ms: int | None = Field(None, ge=500, le=60000)


class VisionStatsIn(BaseModel):
    inference_ms: float = Field(ge=0)
    fps: float = Field(ge=0)
    persons: int = Field(ge=0)
    model: str = Field(max_length=64)
    conf: float = Field(ge=0, le=1)


class AnalysisIn(BaseModel):
    """Résultat du service de détection d'anomalies."""

    state: Literal["normal", "derive", "anomalie"]
    score: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=300)
    features: dict = Field(default_factory=dict)
    model: str | None = Field(None, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def actor(request: Request) -> str:
    """Qui a fait l'action : compte connecté + adresse IP (journal des actions)."""
    user = getattr(request.state, "user", None)
    return f"{user} ({client_ip(request)})" if user else client_ip(request)


# --- Routes ---

@app.post("/api/v1/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    wait = auth.throttle.locked_for(ip)
    if wait:
        raise HTTPException(429, f"trop d'essais, réessayer dans {int(wait // 60) + 1} min")
    # PBKDF2 (~0,3 s) hors de la boucle asyncio : le reste de l'API reste fluide
    ok = await asyncio.to_thread(auth.check_credentials, body.username, body.password)
    if not ok:
        auth.throttle.fail(ip)
        log.warning("connexion refusée pour %r depuis %s", body.username[:64], ip)
        await asyncio.to_thread(log_action, ip, "login_echec", {"user": body.username[:64]})
        raise HTTPException(401, "identifiant ou mot de passe incorrect")
    auth.throttle.reset(ip)
    sid = auth.sessions.create(body.username)
    response.set_cookie(auth.COOKIE, sid, max_age=int(auth.SESSION_TTL_S), httponly=True,
                        samesite="strict", secure=auth.COOKIE_SECURE, path="/")
    log.info("connexion de %s depuis %s", body.username, ip)
    await asyncio.to_thread(log_action, f"{body.username} ({ip})", "login", {})
    return {"user": body.username}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response):
    auth.sessions.delete(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    log_action(actor(request), "logout", {})
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(request: Request):
    return {"user": request.state.user}


@app.get("/api/v1/health")
def health():
    try:
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"api": "ok", "mqtt": bridge.connected, "vision": frames.active(), "db": db_ok,
            "analysis": analysis.fresh()}


@app.get("/api/v1/status")
def status():
    with SessionLocal() as s:
        open_alerts = s.scalar(select(func.count()).select_from(Alert).where(Alert.acknowledged.is_(False)))
    return {**hub.snapshot_state(), "open_alerts": open_alerts, "vision": frames.active(), "mqtt": bridge.connected}


@app.get("/api/v1/metrics")
def metrics(minutes: int = Query(10, ge=1, le=1440)):
    since = utcnow() - timedelta(minutes=minutes)
    with SessionLocal() as s:
        # au-delà de la limite, on garde les plus récentes (puis ordre chronologique)
        rows = s.scalars(select(Measure).where(Measure.ts >= since)
                         .order_by(Measure.ts.desc()).limit(5000)).all()
    return [m.to_dict() for m in reversed(rows)]


@app.get("/api/v1/alerts")
def list_alerts(limit: int = Query(50, ge=1, le=500), level: str | None = None,
                source: str | None = None, unacked: bool = False):
    query = select(Alert)
    if level:
        query = query.where(Alert.level == level)
    if source:
        query = query.where(Alert.source == source)
    if unacked:
        query = query.where(Alert.acknowledged.is_(False))
    with SessionLocal() as s:
        rows = s.scalars(query.order_by(Alert.ts.desc()).limit(limit)).all()
    return [a.to_dict() for a in rows]


@app.post("/api/v1/alerts", status_code=201)
def post_alert(alert: AlertIn):
    details = dict(alert.model_extra or {})
    snapshot = save_snapshot() if alert.source == "vision" else None
    return create_alert(alert.source, alert.type, alert.level, alert.message, snapshot, details)


@app.post("/api/v1/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, request: Request):
    with SessionLocal() as s:
        alert = s.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "alerte introuvable")
        if not alert.acknowledged or alert.acked_at is None:
            alert.acknowledged = True
            alert.acked_at, alert.acked_by = utcnow(), actor(request)
        s.commit()
        data = alert.to_dict()
    log_action(actor(request), "ack", {"alert_id": alert_id})
    hub.publish("alert_ack", {"id": alert_id, "acked_at": data["acked_at"], "acked_by": data["acked_by"]})
    return data


@app.get("/api/v1/forecast")
def get_forecast(horizon: int = Query(10, ge=1, le=60)):
    return compute_forecast(horizon)


@app.get("/api/v1/sensors")
def get_sensors():
    return compute_sensors()


@app.get("/api/v1/actions")
def list_actions(limit: int = Query(100, ge=1, le=1000)):
    with SessionLocal() as s:
        rows = s.scalars(select(Action).order_by(Action.ts.desc()).limit(limit)).all()
    return [a.to_dict() for a in rows]


@app.post("/api/v1/analysis", status_code=204)
def post_analysis(body: AnalysisIn):
    hub.publish("analysis", analysis.put(body.model_dump()))


@app.get("/api/v1/analysis")
def get_analysis():
    return analysis.get()


@app.post("/api/v1/commands")
def send_command(cmd: CommandIn, request: Request):
    payload = cmd.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(422, "aucune commande fournie (buzzer ou led)")
    if not bridge.publish(T_COMMANDES, payload):
        raise HTTPException(503, "broker MQTT indisponible")
    log_action(actor(request), "command", payload)
    return {"sent": payload}


@app.post("/api/v1/config")
def send_config(cfg: ConfigIn, request: Request):
    payload = cfg.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(422, "aucun paramètre fourni")
    # retain : le boîtier retrouve sa configuration après un redémarrage
    if not bridge.publish(T_CONFIG, payload, retain=True):
        raise HTTPException(503, "broker MQTT indisponible")
    log_action(actor(request), "config", payload)
    return {"sent": payload}


@app.post("/api/v1/vision/frame", status_code=204)
async def post_frame(request: Request):
    data = await request.body()
    if not data or len(data) > MAX_FRAME_BYTES or not data.startswith(b"\xff\xd8"):
        raise HTTPException(422, "image JPEG attendue (2 Mo max)")
    frames.put(data)


@app.post("/api/v1/vision/stats", status_code=204)
def post_vision_stats(body: VisionStatsIn):
    vision_stats.put(body.model_dump())


@app.get("/api/v1/vision/stats")
def get_vision_stats():
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as s:
        today = s.scalar(select(func.count()).select_from(Alert).where(
            Alert.source == "vision", Alert.type == "intrusion", Alert.ts >= midnight))
    base = vision_stats.data or {"inference_ms": None, "fps": None, "persons": None, "model": None, "conf": None}
    return {**base, "active": frames.active(), "intrusions_today": today,
            "updated": vision_stats.updated.isoformat() if vision_stats.updated else None}


@app.get("/api/v1/vision/status")
def vision_status():
    return {"active": frames.active()}


@app.get("/api/v1/vision/stream")
async def vision_stream():
    async def generate():
        last = -1
        while True:
            seq, jpeg = frames.get()
            if jpeg and seq != last:
                last = seq
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    # Le middleware HTTP ne voit pas les WebSocket : contrôle de la session ici
    if auth.sessions.user(ws.cookies.get(auth.COOKIE)) is None:
        await ws.close(code=1008)
        return
    await hub.connect(ws)
    try:
        await ws.send_json({"type": "state", "data": hub.snapshot_state()})
        while True:
            await ws.receive_text()  # le dashboard n'envoie rien ; garde la connexion ouverte
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


# --- Fichiers statiques (après les routes API) ---

SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")
if DASHBOARD_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
else:
    log.warning("dossier du dashboard introuvable : %s", DASHBOARD_DIR)
