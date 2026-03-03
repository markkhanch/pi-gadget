#!/usr/bin/env bash
# install.sh — Pi Gadget full setup script
# Run once on a fresh Raspberry Pi OS installation.
#
# What this script does:
#   1. Installs system packages (Python, SPI, fonts, network tools)
#   2. Installs Python packages from requirements.txt
#   3. Enables USB OTG (dwc2 + libcomposite) for HID/storage gadget
#   4. Sets up usb_gadget_setup.sh as a sudoers rule (no password prompt)
#   5. Makes usb_gadget_setup.sh executable
#
# After running this script, REBOOT the Pi for USB OTG to take effect.

set -e

echo "[*] Updating APT..."
sudo apt update

echo "[*] Installing system packages (Python, SPI, fonts)..."
sudo apt install -y \
  hostapd \
  iptables \
  python3 python3-pip python3-dev \
  python3-rpi.gpio python3-spidev \
  python3-numpy python3-pil \
  fonts-dejavu \
  aircrack-ng \
  tcpdump

echo "[*] Installing network tools..."
sudo apt install -y \
  hostapd \
  iptables \
  nmap \
  arp-scan \
  dosfstools

echo "[*] Installing Python packages from requirements.txt..."
pip3 install --break-system-packages -r requirements.txt

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

echo "[*] Making usb_gadget_setup.sh executable..."
chmod +x usb_gadget_setup.sh

echo "[*] Allowing usb_gadget_setup.sh to run without password (sudoers)..."
SUDOERS_LINE="ALL ALL=(ALL) NOPASSWD: /bin/bash $(pwd)/usb_gadget_setup.sh *"
SUDOERS_FILE="/etc/sudoers.d/pi-gadget-usb"
echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"
echo "    Sudoers rule written to $SUDOERS_FILE"

echo ""
echo "[✓] Installation complete."
echo ""
echo "  IMPORTANT: Reboot the Pi for USB OTG to take effect:"
echo "    sudo reboot"
echo ""
echo "  After reboot, connect Pi's USB DATA port (not PWR) to a computer."
echo "  Then use Settings → USB Mode to switch between keyboard / storage."
echo ""
echo "  To run the gadget:"
echo "    python3 main.py"

# Allow gpsd without sudo password
echo "$USER ALL=(ALL) NOPASSWD: /usr/sbin/gpsd" | sudo tee /etc/sudoers.d/pi-gadget-gpsd > /dev/null
