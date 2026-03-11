# troubleshooting

***

## Display

<details>

<summary>Screen stays black after boot</summary>

* SPI is not enabled. Run `sudo raspi-config` → Interface Options → SPI → Enable, then reboot.
* Check the HAT is seated correctly on all 40 GPIO pins.
* Check service logs: `journalctl -u pi-gadget -f`

</details>

<details>

<summary>Screen shows garbled pixels</summary>

* Power issue — Pi Zero 2W at full load can draw more than some USB chargers supply. Use a charger rated ≥ 2A.
* Check SPI speed in `core/ST7789.py` — reduce `spi_freq` if signal integrity is poor.

</details>

***

## Wi-Fi adapter

<details>

<summary>wlan1 not showing up</summary>

```bash
lsusb   # Verify the adapter is detected at the USB level
iw dev  # List wireless interfaces
dmesg | grep -i mt76  # Check kernel driver messages
```

* MT7612U requires the `mt76x2u` kernel module. It loads automatically on Raspberry Pi OS 64-bit.
* Try a powered USB hub if the Pi cannot supply enough current to the adapter.

</details>

<details>

<summary>Monitor mode fails</summary>

```bash
sudo ip link set wlan1 down
sudo iw wlan1 set monitor control
sudo ip link set wlan1 up
iw dev wlan1 info   # Should show "type monitor"
```

If `iw` reports an error, `nmcli` may be managing the interface. Disable it first:

```bash
sudo nmcli device set wlan1 managed no
```

</details>

***

## hcxdumptool

<details>

<summary>"unrecognized option" errors</summary>

Pi-Gadget targets **hcxdumptool v6.3.5**. Older and newer versions use different flag names.

| v6.3.5 flag | Old equivalent      | Description          |
| ----------- | ------------------- | -------------------- |
| `-F`        | `--filterlist_ap`   | Enable AP filter     |
| `--rds=1`   | `--enable_status=1` | Enable status output |

Do not use `--active_beacon` or `--enable_status` — these do not exist in v6.3.5. Check your version:

```bash
hcxdumptool --version
```

</details>

***

## WebUI

<details>

<summary>"Address already in use" on WebUI start</summary>

This was a bug in earlier versions — `RemoteUI` was being restarted on every Settings open. Fixed: the server is now started once and paused/resumed via flags. If you still see it, ensure `core/remote_ui.py` uses the `_stopped` / `_started` flag pattern and does not call `subprocess` for port checking.

</details>

<details>

<summary>Browser shows blank / no stream</summary>

* Confirm WebUI shows RUNNING in the Settings app
* Check device IP: `ip addr show wlan0`
* Ensure browser is on the same network as the device
* Try a different browser — MJPEG support is universal but some browsers add delays

</details>

***

## Deauth attacks not working

<details>

<summary>Most likely cause: 802.11w Protected Management Frames (PMF)</summary>

Networks with PMF enabled silently discard deauthentication frames sent by unauthorized parties. This includes:

* WPA3 networks (PMF is mandatory)
* WPA2 networks with `pmf=required` or `pmf=capable` in router config
* University / enterprise networks (WWU, Resnet, eduroam, etc.)

There is no software workaround. PMF is a cryptographic protection built into the 802.11w standard.

You can check if a network uses PMF:

```bash
sudo airodump-ng wlan1mon
# Look for "WPA2 CCMP MGT" or "WPA3" in the ENC column
```

</details>

***

## USB HID (BadUSB)

<details>

<summary>/dev/hidg0 not found</summary>

USB gadget mode is not configured. Run `bash scripts/usb_gadget_setup.sh keyboard` or use **Settings → USB Mode → Keyboard** on the device. Make sure the USB data port (not PWR) is connected to the target computer.

</details>

<details>

<summary>Keystrokes not registering on target</summary>

* The target OS may not have recognized the new USB device yet — add a `DELAY 1000` at the start of the payload.
* Some keyboards require OS-specific keycodes. Test with `demo_variables.ds` first.
* Windows may show a "device not recognized" or "driver installing" popup — wait for it to finish.

</details>

***

## GPS

<details>

<summary>No GPS fix</summary>

* GPS fix takes 30–120 seconds outdoors on cold start.
* The fix indicator on the screensaver shows `GPS` when locked.
* Confirm the dongle is detected: `ls /dev/ttyUSB* /dev/ttyACM*`
* Check gpsd: `sudo gpsd /dev/ttyUSB0 -F /var/run/gpsd.sock`

</details>

***

## General

<details>

<summary>App crashes on launch</summary>

Check the journal:

```bash
journalctl -u pi-gadget -f
```

Or run manually to see the full traceback:

```bash
sudo systemctl stop pi-gadget
python3 main.py
```

</details>

<details>

<summary>Missing tool (e.g. hcxdumptool, mdk4)</summary>

Re-run the install script:

```bash
bash install.sh
```

Or install manually:

```bash
sudo apt install hcxtools mdk4 tcpdump hashcat
```

</details>
