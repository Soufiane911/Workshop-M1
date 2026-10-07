#!/usr/bin/env bash
# Sentinel-X — certificat HTTPS de l'API / du dashboard, signé par l'AC de security/init-mqtt.sh.
#
#   ./security/init-https.sh            # crée le certificat s'il manque
#   ./security/init-https.sh --force    # le régénère (ex. : l'IP du serveur a changé)
#
# Produit (non commité, voir .gitignore) :
#   infra/api-certs/api.crt   certificat de l'API (EC P-256, SAN 10.42.0.1, localhost, api)
#   infra/api-certs/api.key   sa clé privée (0600, lisible par l'utilisateur du conteneur, uid 1000)
#
# Le navigateur fait confiance au dashboard dès que infra/mosquitto/certs/ca.crt est importé
# comme autorité (voir security/README.md). Pas besoin de re-flasher l'ESP8266.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKI="$ROOT/infra/pki"
OUT="$ROOT/infra/api-certs"
SERVER_IP="${SERVER_IP:-10.42.0.1}"
API_UID=1000  # utilisateur "sentinel" du conteneur api (backend/Dockerfile)

[[ -f "$PKI/ca.key" ]] || { echo "AC absente : lancer d'abord ./security/init-mqtt.sh" >&2; exit 1; }

if [[ "${1:-}" != "--force" && -f "$OUT/api.crt" ]]; then
  echo "[https] $OUT/api.crt existe déjà (--force pour le régénérer)"
  exit 0
fi

mkdir -p "$OUT"
rm -f "$OUT/api.key" "$OUT/api.crt"
(umask 077; openssl ecparam -name prime256v1 -genkey -noout -out "$OUT/api.key")
# 398 jours : durée maximale acceptée par les navigateurs pour un certificat serveur
openssl req -new -key "$OUT/api.key" -subj "/O=AetherCorp/OU=Sentinel-X/CN=$SERVER_IP" |
  openssl x509 -req -CA "$PKI/ca.crt" -CAkey "$PKI/ca.key" -CAcreateserial -days 398 -sha256 \
    -extfile <(printf '%s\n' \
      "basicConstraints=critical,CA:FALSE" \
      "keyUsage=critical,digitalSignature" \
      "extendedKeyUsage=serverAuth" \
      "subjectAltName=DNS:localhost,DNS:api,IP:127.0.0.1,IP:$SERVER_IP" \
      "authorityKeyIdentifier=keyid") \
    -out "$OUT/api.crt" 2>/dev/null
chmod 644 "$OUT/api.crt"
chmod 600 "$OUT/api.key"
# La clé doit appartenir à l'utilisateur du conteneur (si l'hôte n'a pas le même uid)
[[ "$(id -u)" == "$API_UID" ]] || docker run --rm -v "$OUT:/out" alpine chown "$API_UID" /out/api.key
openssl verify -CAfile "$PKI/ca.crt" "$OUT/api.crt"

cat <<EOF

Terminé. Étapes suivantes :
  1. cd infra && docker compose up -d
  2. Importer infra/mosquitto/certs/ca.crt dans le navigateur (autorité de certification)
  3. Dashboard : https://$SERVER_IP:8000  (ou https://localhost:8000)
EOF
