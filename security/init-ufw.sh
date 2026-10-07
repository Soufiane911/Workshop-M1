#!/usr/bin/env bash
# Pare-feu de l'hôte (UFW) : tout ce qui entre est refusé, sauf le strict nécessaire au WiFi de table.
#
#   sudo DRY_RUN=1 ./security/init-ufw.sh   # affiche les règles iptables sans rien appliquer
#   sudo ./security/init-ufw.sh             # applique
#   sudo SSH=1 ./security/init-ufw.sh       # + SSH (22) depuis le WiFi de table, limité contre le bruteforce
#
# Ce qu'UFW ne gère PAS : les ports publiés par Docker (8000 dashboard, 8883 MQTTS).
# Docker les ouvre par DNAT dans ses propres chaînes, avant UFW. Ils sont limités ailleurs :
#   - docker-compose.yml : publiés seulement sur 127.0.0.1 et 10.42.0.1 (jamais sur l'interface Internet)
#   - security/init-firewall.sh : 8883 réservé à l'ESP8266 (nftables)
set -euo pipefail

AP_IF="${AP_IF:-ap0}"        # WiFi de table (hotspot NetworkManager)
SSH="${SSH:-0}"

[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo" >&2; exit 1; }

ufw_() {
  if [[ "${DRY_RUN:-0}" == 1 ]]; then ufw --dry-run "$@"; else ufw "$@"; fi
}

# Politique par défaut : entrées refusées (sans réponse, le scan voit « filtered »),
# sorties autorisées, routage refusé (le PC ne sert pas de routeur entre le WiFi de table et Internet)
ufw_ default deny incoming
ufw_ default allow outgoing
ufw_ default deny routed

# DHCP du hotspot : sans ça l'ESP8266 n'obtient pas d'adresse
ufw_ allow in on "$AP_IF" to any port 67 proto udp comment "DHCP WiFi de table"

# SSH (optionnel) : seulement depuis le WiFi de table, et « limit » = 6 tentatives / 30 s max par IP
if [[ "$SSH" == 1 ]]; then
  ufw_ limit in on "$AP_IF" to any port 22 proto tcp comment "SSH WiFi de table"
fi

# Pas de DNS (53) : le boîtier et le dashboard sont joints par IP (10.42.0.1), inutile d'exposer dnsmasq

# Journal des paquets refusés (preuves pour le rapport d'audit : journalctl -k | grep "UFW BLOCK")
ufw_ logging low

ufw_ --force enable
[[ "${DRY_RUN:-0}" == 1 ]] || ufw status verbose
