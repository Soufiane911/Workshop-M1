#!/usr/bin/env python3
"""Sentinel-X — définit le compte du dashboard et le jeton des modules IA (dans infra/.env).

    python3 security/set-dashboard-password.py            # demande identifiant + mot de passe
    python3 security/set-dashboard-password.py --token    # régénère aussi API_TOKEN
    python3 security/set-dashboard-password.py --check    # vérifie un mot de passe sans rien modifier

Écrit dans infra/.env (droits 0600, jamais commité) :
  DASHBOARD_USER           identifiant du superviseur
  DASHBOARD_PASSWORD_HASH  PBKDF2-SHA256, 600 000 itérations, sel aléatoire : le mot de passe n'est stocké nulle part
  API_TOKEN                jeton des modules IA (anomalies, vision), créé s'il manque

Puis : cd infra && docker compose up -d   (l'API relit infra/.env)
"""

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / "infra" / ".env"
ITERATIONS = 600_000  # même format que backend/app/auth.py
MIN_LEN = 12


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256:{ITERATIONS}:{salt.hex()}:{digest.hex()}"


def check():
    """Compare un mot de passe tapé au hash de infra/.env (diagnostic, ne modifie rien)."""
    env = dict(l.split("=", 1) for l in ENV_FILE.read_text().splitlines() if "=" in l)
    stored = env.get("DASHBOARD_PASSWORD_HASH")
    if not stored:
        raise SystemExit("Aucun mot de passe enregistré dans infra/.env.")
    _, iterations, salt, expected = stored.split(":")
    password = getpass.getpass(f"Mot de passe de « {env.get('DASHBOARD_USER', 'admin')} » à vérifier : ")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    if hmac.compare_digest(digest.hex(), expected):
        print("✅ Correct : c'est bien ce mot de passe. Vérifier l'identifiant exact dans le navigateur.")
    else:
        print(f"❌ Différent du mot de passe enregistré ({len(password)} caractères tapés).")
        if password != password.strip():
            print("   Il contient des espaces au début ou à la fin.")


def write_env(values: dict):
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    lines = [l for l in lines if l.split("=", 1)[0] not in values]
    lines += [f"{k}={v}" for k, v in values.items()]
    ENV_FILE.touch(mode=0o600, exist_ok=True)
    os.chmod(ENV_FILE, 0o600)
    ENV_FILE.write_text("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--user", help="identifiant (sinon demandé, défaut : admin)")
    p.add_argument("--token", action="store_true", help="régénère API_TOKEN (relancer ensuite les modules IA)")
    p.add_argument("--password-stdin", action="store_true", help="lit le mot de passe sur l'entrée standard (scripts)")
    p.add_argument("--check", action="store_true", help="vérifie un mot de passe sans rien modifier")
    args = p.parse_args()
    if args.check:
        check()
        return

    user = args.user or input("Identifiant [admin] : ").strip() or "admin"
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass(f"Mot de passe ({MIN_LEN} caractères min.) : ")
        if password != getpass.getpass("Confirmer : "):
            raise SystemExit("Les deux mots de passe sont différents.")
    if len(password) < MIN_LEN:
        raise SystemExit(f"Mot de passe trop court ({MIN_LEN} caractères minimum).")

    values = {"DASHBOARD_USER": user, "DASHBOARD_PASSWORD_HASH": hash_password(password)}
    existing = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if args.token or "\nAPI_TOKEN=" not in "\n" + existing:
        values["API_TOKEN"] = secrets.token_urlsafe(32)
        print("[env] nouveau API_TOKEN (modules IA)")
    write_env(values)
    print(f"[env] compte « {user} » enregistré dans {ENV_FILE} (mot de passe haché)")
    print("Appliquer : cd infra && docker compose up -d")


if __name__ == "__main__":
    main()
