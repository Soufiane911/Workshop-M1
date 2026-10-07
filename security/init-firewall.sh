#!/usr/bin/env bash
# Pare-feu MQTT : ports 1883/8883 du PC serveur ouverts uniquement au boîtier ESP8266.
#
#   sudo ./security/init-firewall.sh            # installe (ESP_IP / ESP_MAC / AP_IF modifiables)
#   sudo ./security/init-firewall.sh --remove   # désinstalle
#
# Pourquoi nftables et pas UFW : Docker publie ses ports par DNAT dans ses propres chaînes,
# que les règles UFW (INPUT) ne voient jamais. On filtre donc en prerouting, priorité -150,
# avant la NAT de Docker (-100) : la règle s'applique quel que soit le chemin (DNAT ou docker-proxy).
# Table nftables séparée : ni `ufw reload` ni un redémarrage de Docker ne l'effacent.
#
# Laissé passer :
#   - le boîtier : IP ESP_IP *et* MAC ESP_MAC, arrivant par le WiFi de table (AP_IF)
#   - l'hôte lui-même (lo) : outils et simulateur sur 127.0.0.1:8883
#   - le trafic entre conteneurs (api, anomalies -> mosquitto) : il vise l'IP du conteneur, pas l'hôte
set -euo pipefail

ESP_IP="${ESP_IP:-10.42.0.239}"
ESP_MAC="${ESP_MAC:-24:a1:60:2a:a9:d4}"
AP_IF="${AP_IF:-ap0}"

RULES=/etc/sentinel/mqtt-firewall.nft
UNIT=/etc/systemd/system/sentinel-firewall.service
DHCP=/etc/NetworkManager/dnsmasq-shared.d/sentinel-esp.conf

[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo" >&2; exit 1; }

if [[ "${1:-}" == "--remove" ]]; then
  systemctl disable --now sentinel-firewall.service 2>/dev/null || true
  nft delete table inet sentinel_mqtt 2>/dev/null || true
  rm -f "$RULES" "$UNIT" "$DHCP"
  systemctl daemon-reload
  echo "Pare-feu MQTT retiré."
  exit 0
fi

# 1. IP fixe pour l'ESP : réservation DHCP dans le dnsmasq du hotspot NetworkManager
#    (sinon le bail peut changer et le boîtier se retrouve bloqué)
mkdir -p "$(dirname "$DHCP")"
echo "dhcp-host=$ESP_MAC,$ESP_IP" > "$DHCP"

# 2. Règles
mkdir -p "$(dirname "$RULES")"
cat > "$RULES" <<EOF
# Généré par security/init-firewall.sh
table inet sentinel_mqtt
delete table inet sentinel_mqtt
table inet sentinel_mqtt {
  chain prerouting {
    type filter hook prerouting priority -150; policy accept;
    # Seuls les paquets destinés à une adresse de l'hôte (10.42.0.1, 127.0.0.1...) sont concernés
    meta l4proto { tcp, udp } th dport { 1883, 8883 } fib daddr type local jump mqtt
  }
  chain mqtt {
    iifname "lo" accept
    iifname "$AP_IF" ip saddr $ESP_IP ether saddr $ESP_MAC counter accept
    # Refus journalisés (journalctl -k | grep sentinel-mqtt) : preuves pour le rapport d'audit
    limit rate 10/minute log prefix "[sentinel-mqtt] refus: " level warn
    counter drop
  }
}
EOF
# 3. Rechargement au démarrage
cat > "$UNIT" <<EOF
[Unit]
Description=Sentinel-X : pare-feu MQTT (ports 1883/8883 réservés à l'ESP8266)
Before=network-pre.target docker.service
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/nft -f $RULES
ExecStop=/usr/bin/nft delete table inet sentinel_mqtt

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable sentinel-firewall.service >/dev/null
systemctl restart sentinel-firewall.service   # charge les règles

cat <<EOF
Pare-feu MQTT actif : 1883/8883 réservés à $ESP_IP ($ESP_MAC) sur $AP_IF, + localhost.
  Règles   : nft list table inet sentinel_mqtt
  Refus    : journalctl -k | grep sentinel-mqtt
  IP fixe ESP : appliquée au prochain démarrage du hotspot (nmcli con up Sentinel-X-Table)
EOF
