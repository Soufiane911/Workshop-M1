#!/usr/bin/env bash
# Sentinel-X — génère tout ce qu'il faut pour MQTTS (à lancer une fois, puis après chaque changement d'IP).
#
#   ./security/init-mqtt.sh            # crée ce qui manque (certificats, mots de passe)
#   ./security/init-mqtt.sh --force    # régénère l'AC et les certificats (re-flasher l'ESP ensuite !)
#
# Produit (rien n'est commité, voir .gitignore) :
#   infra/pki/ca.key                     clé privée de l'AC — ne quitte jamais le PC serveur
#   infra/mosquitto/certs/ca.crt         certificat de l'AC (public : API, IA, simulateur, ESP)
#   infra/mosquitto/certs/server.{crt,key}  certificat du broker, signé par l'AC
#   infra/mosquitto/config/passwd        comptes MQTT hachés (PBKDF2-SHA512)
#   infra/.env                           mots de passe MQTT_*_PASSWORD (aléatoires)
#   firmware/include/ca_cert.h           AC embarquée dans le firmware
#
# Les clés sont en EC P-256 : poignée de main TLS ~10x plus rapide que RSA sur l'ESP8266.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKI="$ROOT/infra/pki"
CERTS="$ROOT/infra/mosquitto/certs"
CONF="$ROOT/infra/mosquitto/config"
ENV_FILE="$ROOT/infra/.env"
CA_HEADER="$ROOT/firmware/include/ca_cert.h"

SERVER_IP="${SERVER_IP:-10.42.0.1}"       # IP du PC serveur sur le WiFi de table
MOSQUITTO_IMAGE="eclipse-mosquitto:2"
MOSQUITTO_UID=1883                         # utilisateur "mosquitto" dans l'image officielle
USERS=(boitier simulateur api ia)         # comptes MQTT (droits : infra/mosquitto/config/acl)

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

mkdir -p "$PKI" "$CERTS"
chmod 700 "$PKI"

# ---------- Certificats ----------

if $FORCE || [[ ! -f "$PKI/ca.key" ]]; then
  echo "[pki] nouvelle autorité de certification"
  rm -f "$PKI"/ca.* "$CERTS"/*
  openssl ecparam -name prime256v1 -genkey -noout -out "$PKI/ca.key"
  chmod 600 "$PKI/ca.key"
  openssl req -x509 -new -key "$PKI/ca.key" -sha256 -days 3650 \
    -subj "/O=AetherCorp/OU=Sentinel-X/CN=Sentinel-X Root CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$PKI/ca.crt"
fi

if $FORCE || [[ ! -f "$CERTS/server.crt" ]]; then
  echo "[pki] certificat du broker pour $SERVER_IP"
  rm -f "$CERTS/server.key" "$CERTS/server.crt"
  openssl ecparam -name prime256v1 -genkey -noout -out "$CERTS/server.key"
  # "DNS:<ip>" en plus de "IP:<ip>" : BearSSL (ESP8266) ne compare le nom qu'aux entrées DNS
  SAN="DNS:mosquitto,DNS:localhost,DNS:$SERVER_IP,IP:127.0.0.1,IP:$SERVER_IP"
  openssl req -new -key "$CERTS/server.key" -subj "/O=AetherCorp/OU=Sentinel-X/CN=$SERVER_IP" |
    openssl x509 -req -CA "$PKI/ca.crt" -CAkey "$PKI/ca.key" -CAcreateserial -days 825 -sha256 \
      -extfile <(printf '%s\n' \
        "basicConstraints=critical,CA:FALSE" \
        "keyUsage=critical,digitalSignature" \
        "extendedKeyUsage=serverAuth" \
        "subjectAltName=$SAN" \
        "authorityKeyIdentifier=keyid") \
      -out "$CERTS/server.crt" 2>/dev/null
  cp "$PKI/ca.crt" "$CERTS/ca.crt"
  chmod 644 "$CERTS/ca.crt" "$CERTS/server.crt"
  openssl verify -CAfile "$CERTS/ca.crt" "$CERTS/server.crt"
fi

# ---------- AC embarquée dans le firmware ----------

{
  echo "// Généré par security/init-mqtt.sh — NE PAS MODIFIER, NE PAS COMMITER."
  echo "// Certificat public de l'AC : l'ESP8266 refuse tout broker qu'elle n'a pas signé."
  echo "#pragma once"
  echo "#include <Arduino.h>"
  echo
  echo "static const char CA_CERT[] PROGMEM = R\"EOF("
  cat "$CERTS/ca.crt"
  echo ")EOF\";"
} > "$CA_HEADER"
echo "[firmware] $CA_HEADER"

# ---------- Mots de passe ----------

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
for u in "${USERS[@]}"; do
  var="MQTT_${u^^}_PASSWORD"
  if ! grep -q "^$var=" "$ENV_FILE"; then
    echo "$var=$(openssl rand -base64 24 | tr -d '/+=')" >> "$ENV_FILE"
    echo "[env] $var ajouté à infra/.env"
  fi
done

# Fichier passwd (haché) + droits pour l'utilisateur mosquitto du conteneur.
# Fait dans un conteneur : mosquitto_passwd n'est pas forcément installé sur l'hôte.
# Les mots de passe passent par stdin (jamais en argument : visibles dans `ps`).
rm -f "$CONF/passwd"
{
  echo "set -e; umask 077; touch /conf/passwd"
  for u in "${USERS[@]}"; do
    var="MQTT_${u^^}_PASSWORD"
    echo "mosquitto_passwd -b /conf/passwd '$u' '$(grep "^$var=" "$ENV_FILE" | cut -d= -f2-)'"
  done
  echo "chown $MOSQUITTO_UID:$MOSQUITTO_UID /conf/passwd /certs/server.key"
  echo "chmod 600 /conf/passwd /certs/server.key"
} | docker run --rm -i -v "$CONF:/conf" -v "$CERTS:/certs" --entrypoint sh "$MOSQUITTO_IMAGE"
echo "[mosquitto] comptes : ${USERS[*]}"

cat <<EOF

Terminé. Étapes suivantes :
  1. cd infra && docker compose up -d --force-recreate
  2. firmware/include/secrets.h : MQTT_PORT 8883, MQTT_USER "boitier",
     MQTT_PASS = valeur de MQTT_BOITIER_PASSWORD dans infra/.env
  3. Re-flasher l'ESP8266 (l'AC est dans firmware/include/ca_cert.h)
EOF
