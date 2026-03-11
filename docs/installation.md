# installation

## Prerequisites

* Fresh **Raspberry Pi OS Lite** (64-bit recommended)
* Pi is booted and accessible via SSH or keyboard
* Internet connection on the Pi during install

## Step 1 — Enable SPI

The ST7789 display uses SPI. It must be enabled before the app can start.

```bash
sudo raspi-config
# Navigate to: Interface Options → SPI → Enable
sudo reboot
```

## Step 2 — Clone and install

```bash
git clone https://github.com/markkhanch/pi-gadget.git
cd pi-gadget
bash install.sh
```

`install.sh` does the following automatically:

{% stepper %}
{% step %}
### apt install — system packages

* `python3`, `python3-pip`, `python3-rpi.gpio`, `python3-spidev`, `python3-pil`
* `aircrack-ng`, `tcpdump`, `hcxtools`, `hashcat`, `mdk4`
* `hostapd`, `iptables`, `nmap`, `arp-scan`
* `gpsd`, `gpsd-clients`
* `fonts-dejavu`
{% endstep %}

{% step %}
### pip3 install -r requirements.txt — Python packages

* `flask`, `gpiozero`, `gpsd-py3`, `lgpio`, `numpy`, `Pillow`, `RPi.GPIO`, `spidev`, `ST7789`
{% endstep %}

{% step %}
### USB OTG setup

Adds `dtoverlay=dwc2` to `/boot/firmware/config.txt`, adds `dwc2` and `libcomposite` to `/etc/modules`
{% endstep %}

{% step %}
### sudoers rule

Allows `usb_gadget_setup.sh` to run without a password prompt
{% endstep %}

{% step %}
### systemd service

Creates and enables `pi-gadget.service` for autostart on boot
{% endstep %}
{% endstepper %}

## Step 3 — Reboot

```bash
sudo reboot
```

After reboot, Pi-Gadget starts automatically via the systemd service. The clock face (screensaver) should appear on the display within a few seconds.

## Manual run (development)

To run manually without autostart:

```bash
# Stop the service first to avoid conflicts
sudo systemctl stop pi-gadget
python3 main.py
```

## Autostart management

```bash
# Disable autostart
sudo systemctl disable pi-gadget

# Re-enable autostart
sudo systemctl enable pi-gadget

# Check service status / logs
sudo systemctl status pi-gadget
journalctl -u pi-gadget -f
```

## USB HID mode

After reboot, connect the Pi's **USB DATA port** (the port closer to the center of the board, labeled USB — not PWR) to a computer. Then use **Settings → USB Mode** on the device to switch between keyboard and storage gadget modes.
