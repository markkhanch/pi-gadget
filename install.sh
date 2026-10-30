#!/usr/bin/env bash
# install.sh — Pi Gadget full setup script
# Run once on a fresh Raspberry Pi OS installation.
#
# What this script does:
#   1. Installs system packages (Python, SPI, fonts, network/wireless tools)
#   2. Installs Python packages from requirements.txt
#   3. Enables USB OTG (dwc2 + libcomposite) for HID/storage gadget
#   4. Writes a sudoers drop-in granting NOPASSWD for the exact commands the
#      apps call (resolved on THIS machine), plus the two helper scripts
#   5. Makes the helper scripts executable
#   6. Installs a systemd autostart service
#
# After running this script, REBOOT the Pi for USB OTG to take effect.
#
# May be run either as the normal user (it calls sudo itself) or via
# `sudo ./install.sh` — in both cases the sudoers/service are bound to the
# real login user, not root.

set -euo pipefail

# Resolve the directory this script lives in, regardless of the cwd it is
# invoked from. Everything below is anchored to this path.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# The user the service and sudoers rules belong to. When invoked with sudo,
# $SUDO_USER is the real user; otherwise fall back to $USER.
RUN_USER="${SUDO_USER:-$USER}"

echo "[*] Project dir: $PROJECT_DIR"
echo "[*] Target user: $RUN_USER"

echo "[*] Updating APT..."
sudo apt update

echo "[*] Installing system packages (Python, SPI, fonts, network/wireless tools)..."
sudo apt install -y \
  python3 python3-pip python3-dev \
  python3-rpi.gpio python3-spidev \
  python3-numpy python3-pil \
  fonts-dejavu \
  hostapd \
  iptables \
  dnsmasq \
  iw \
  wireless-tools \
  rfkill \
  nmap \
  arp-scan \
  dosfstools \
  lsof \
  aircrack-ng \
  tcpdump \
  hcxtools \
  hcxdumptool \
  hashcat \
  mdk4 \
  gpsd gpsd-clients

echo "[*] Installing Python packages from requirements.txt..."
pip3 install --break-system-packages -r "$PROJECT_DIR/requirements.txt"

echo "[*] Enabling USB OTG (dwc2)..."
CONFIG="/boot/firmware/config.txt"
[ -f "$CONFIG" ] || CONFIG="/boot/config.txt"

if ! grep -q "dtoverlay=dwc2" "$CONFIG"; then
    echo "dtoverlay=dwc2" | sudo tee -a "$CONFIG"
    echo "    Added dtoverlay=dwc2 to $CONFIG"
else
    echo "    dtoverlay=dwc2 already present"
fi

if ! grep -q "^dwc2" /etc/modules; then
    echo "dwc2" | sudo tee -a /etc/modules
    echo "    Added dwc2 to /etc/modules"
fi

if ! grep -q "^libcomposite" /etc/modules; then
    echo "libcomposite" | sudo tee -a /etc/modules
    echo "    Added libcomposite to /etc/modules"
fi

echo "[*] Making helper scripts executable..."
chmod +x "$PROJECT_DIR"/scripts/*.sh

echo "[*] Writing sudoers rules (NOPASSWD for the exact commands the apps use)..."
# The apps shell out to a known set of privileged binaries. We grant NOPASSWD
# for exactly those — resolved on THIS machine so the paths are correct for the
# installed distro — never "NOPASSWD: ALL". Binaries that are not installed are
# simply skipped. `bash` and `python3` are NOT granted blanket (that would be a
# root shell); they are restricted to the specific helper scripts.
SUDOERS_FILE="/etc/sudoers.d/pi-gadget"
TMP_SUDOERS="$(mktemp)"
{
  echo "# Managed by pi-gadget install.sh — regenerated on each run. Do not edit by hand."
  # Resolve each privileged binary to an ABSOLUTE path on this machine. sudoers
  # rejects anything that is not fully-qualified, and `command -v` can return a
  # shell builtin name with no path (e.g. "kill"), so fall back to well-known
  # locations in that case. Binaries that resolve to neither are skipped.
  for bin in ip iw iwlist nmcli rfkill iptables hostapd dnsmasq \
             bluetoothctl hciconfig nmap arp-scan tcpdump sysctl kill \
             airmon-ng airodump-ng aireplay-ng mdk4 hcxdumptool hashcat \
             gpsd systemctl timedatectl hostnamectl; do
    p="$(command -v "$bin" 2>/dev/null || true)"
    case "$p" in
      /*) echo "$RUN_USER ALL=(root) NOPASSWD: $p" ;;
      *)  for cand in "/usr/bin/$bin" "/bin/$bin" "/usr/sbin/$bin" "/sbin/$bin"; do
            if [ -x "$cand" ]; then
              echo "$RUN_USER ALL=(root) NOPASSWD: $cand"
              break
            fi
          done ;;
    esac
  done
  BASH_BIN="$(command -v bash)"
  PY3_BIN="$(command -v python3)"
  echo "$RUN_USER ALL=(root) NOPASSWD: $BASH_BIN $PROJECT_DIR/scripts/usb_gadget_setup.sh *"
  echo "$RUN_USER ALL=(root) NOPASSWD: $BASH_BIN $PROJECT_DIR/scripts/evil_twin.sh *"
  echo "$RUN_USER ALL=(root) NOPASSWD: $PY3_BIN $PROJECT_DIR/apps/bad_stuff/network/evil_twin/portal_server.py *"
} > "$TMP_SUDOERS"

# Always validate before installing — a malformed sudoers file can lock you out.
if sudo visudo -c -f "$TMP_SUDOERS" > /dev/null; then
    sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$SUDOERS_FILE"
    echo "    Sudoers rules written to $SUDOERS_FILE"
else
    echo "    ERROR: generated sudoers file failed validation — NOT installed."
    echo "    Review it here: $TMP_SUDOERS"
    exit 1
fi
rm -f "$TMP_SUDOERS"

# Remove sudoers files from older installs (rules are now consolidated above).
sudo rm -f /etc/sudoers.d/pi-gadget-usb /etc/sudoers.d/pi-gadget-gpsd

echo ""
echo "[*] Creating systemd autostart service..."
SERVICE_FILE="/etc/systemd/system/pi-gadget.service"
sudo tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=Pi Gadget
After=multi-user.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
sudo systemctl daemon-reload
sudo systemctl enable pi-gadget.service
echo "    Autostart enabled (pi-gadget.service)"

echo ""
echo "[✓] Installation complete."
echo ""
echo "  IMPORTANT: Reboot the Pi for USB OTG and autostart to take effect:"
echo "    sudo reboot"
echo ""
echo "  After reboot, connect Pi's USB DATA port (not PWR) to a computer."
echo "  Then use Settings → USB Mode to switch between keyboard / storage."
echo ""
echo "  To run manually (development):"
echo "    sudo systemctl stop pi-gadget && python3 main.py"
echo ""
echo "  To disable autostart:"
echo "    sudo systemctl disable pi-gadget"
