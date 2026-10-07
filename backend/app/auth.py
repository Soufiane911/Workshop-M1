"""Authentification : session (cookie) pour le dashboard, jeton Bearer pour les modules IA.

- Superviseur : identifiant + mot de passe (haché PBKDF2-SHA256, jamais en clair)
  -> cookie de session aléatoire, HttpOnly, SameSite=Strict, durée limitée.
- Machines (IA anomalies, vision) : `Authorization: Bearer <API_TOKEN>`, accepté
  UNIQUEMENT sur les routes où elles écrivent (moindre privilège).
- Anti-bruteforce : après MAX_FAILS échecs depuis une IP, elle est bloquée LOCK_S secondes.

Les secrets viennent de l'environnement (infra/.env, généré par security/set-dashboard-password.py).
"""

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time

log = logging.getLogger("sentinel.auth")

COOKIE = "sentinel_session"
SESSION_TTL_S = float(os.getenv("SESSION_TTL_S", str(8 * 3600)))
# Secure = cookie envoyé seulement en HTTPS : à activer dès que l'API passe en HTTPS
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
MAX_FAILS = 5
LOCK_S = 300.0

USER = os.getenv("DASHBOARD_USER", "admin")
PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "")
API_TOKEN = os.getenv("API_TOKEN", "")

if not PASSWORD_HASH:
    log.error("DASHBOARD_PASSWORD_HASH absent : toute connexion au dashboard sera refusée")
if len(API_TOKEN) < 32:
    log.error("API_TOKEN absent ou trop court : les modules IA ne pourront pas écrire dans l'API")
    API_TOKEN = ""

# Format : pbkdf2_sha256:<itérations>:<sel hex>:<hash hex> (sans « $ », que docker compose interpréterait)
ITERATIONS = 600_000


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256:{iterations}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, expected = stored.split(":")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


# Calculé une fois : une connexion avec un mauvais identifiant prend le même temps qu'avec le bon
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_credentials(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username.encode(), USER.encode())
    pass_ok = verify_password(password, PASSWORD_HASH if PASSWORD_HASH else _DUMMY_HASH)
    return user_ok and pass_ok and bool(PASSWORD_HASH)


def check_token(header: str | None) -> bool:
    if not API_TOKEN or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].encode(), API_TOKEN.encode())


class Sessions:
    """Sessions en mémoire : déconnexion immédiate possible, tout est perdu au redémarrage de l'API."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[str, float]] = {}

    def create(self, user: str) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self._sessions = {k: v for k, v in self._sessions.items() if v[1] > now}
            self._sessions[sid] = (user, now + SESSION_TTL_S)
        return sid

    def user(self, sid: str | None) -> str | None:
        if not sid:
            return None
        with self._lock:
            entry = self._sessions.get(sid)
            if not entry:
                return None
            if entry[1] < time.time():
                del self._sessions[sid]
                return None
            return entry[0]

    def delete(self, sid: str | None):
        with self._lock:
            self._sessions.pop(sid or "", None)


class Throttle:
    """Compte les échecs de connexion par IP et bloque après MAX_FAILS."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def locked_for(self, ip: str) -> float:
        """Secondes de blocage restantes (0 = autorisé)."""
        with self._lock:
            now = time.time()
            recent = [t for t in self._fails.get(ip, []) if now - t < LOCK_S]
            self._fails[ip] = recent
            if len(recent) >= MAX_FAILS:
                return LOCK_S - (now - recent[-MAX_FAILS])
            return 0.0

    def fail(self, ip: str):
        with self._lock:
            self._fails.setdefault(ip, []).append(time.time())

    def reset(self, ip: str):
        with self._lock:
            self._fails.pop(ip, None)


sessions = Sessions()
throttle = Throttle()
