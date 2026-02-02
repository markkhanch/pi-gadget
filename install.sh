#!/usr/bin/env bash

set -e

echo "[*] Updating APT..."
sudo apt update

echo "[*] Installing system packages (Python, SPI, fonts)..."
sudo apt install -y \
  python3 python3-pip python3-dev \
  python3-rpi.gpio python3-spidev \
  python3-numpy python3-pil \
  fonts-dejavu

echo "[*] Installing Python packages from requirements.txt..."
pip3 install --break-system-packages -r requirements.txt

echo "[*] Done. You can now run: python3 main.py"
