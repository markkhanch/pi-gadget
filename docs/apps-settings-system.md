# apps settings system

## Settings

Settings apps live under `apps/settings/` and appear in the **Settings** menu.

### Wi-Fi Manager

**Module:** `settings.wifi_manager`

Connect to Wi-Fi networks from the device.

* Lists available SSIDs scanned by `nmcli`
* On select: prompts for password via on-screen keyboard
* Connects using `nmcli device wifi connect <ssid> password <pass>`
* Shows connection status (IP address once connected)

### SSH Toggle

**Module:** `settings.ssh`

Enable or disable the SSH daemon without a computer.

* Shows current SSH status (running / stopped)
* When **enabled**: displays connection info — hostname, IP address, port (22), user
* Toggle with CENTER: runs `systemctl start/stop ssh` and `systemctl enable/disable ssh`

This lets you flip SSH on before unplugging from power and carrying the device into the field.

### WebUI

**Module:** `settings.web_ui`

Start or stop the browser-based remote interface.

* Shows current status (RUNNING / STOPPED) and the URL (`http://<ip>:5000`)
* Start: activates the Flask streaming server in `core/remote_ui.py`
* Stop: pauses the MJPEG frame stream without killing the process

The WebUI streams the live display over MJPEG and relays button clicks as events to the main loop. See [Remote UI](/broken/pages/dce632dad2433f29bdd6ea9b462f6142169ffc87) for full details.

### Bluetooth

**Module:** `settings.bluetooth`

Toggle Bluetooth on/off.

* Runs `rfkill unblock bluetooth` / `rfkill block bluetooth`
* Status icon updates on the screensaver immediately

### Brightness

**Module:** `settings.brightness`

Adjust display backlight brightness.

* UP / DOWN to increase / decrease in steps
* Saved to `config.json` → `brightness`
* Applied immediately

### Screen Timeout

**Module:** `settings.screen_timeout`

Configure idle and screen-off timeouts.

* **Idle timeout:** how long before the screensaver activates
* **Screen timeout:** how long before the backlight turns off completely
* Saved to `config.json` → `idle_timeout` and `screen_timeout`

### USB Mode

**Module:** `settings.usb_mode`

Switch between USB keyboard (HID) and USB storage gadget modes.

* Runs `usb_gadget_setup.sh keyboard` or `usb_gadget_setup.sh storage`
* Requires USB data port connected to a computer
* The gadget script teardowns the previous gadget before setting up the new one

### Date / Time

**Module:** `settings.datetime`

Set the system date and time manually (for use in the field without internet NTP).

* On-screen keyboard for date/time entry
* Applies with `sudo date -s "<datetime>"`
* Clock format (12h / 24h) togglable, saved to `settings/datetime/clockfmt.txt`

### Hostname

**Module:** `settings.hostname`

Change the device hostname.

* On-screen keyboard for input
* Writes to `/etc/hostname` and `/etc/hosts`
* Saved to `config.json` → `hostname`

## System

System apps live under `apps/system/` and appear in the **System** menu.

### CPU / RAM Monitor

**Module:** `system.cpu_ram`

Real-time CPU and RAM usage with a scrolling history graph.

* Samples CPU % and RAM % every second via `SystemMonitor` (`core/monitor.py`)
* Displays a live line graph (up to 600 data points, 10-minute window)
* Shows current values as numbers alongside the graph

### Device Info

**Module:** `system.device_info`

Static hardware and software information.

* Hostname, OS version, kernel version
* CPU model, core count, clock speed
* RAM total
* Pi serial number

### Disk Usage

**Module:** `system.disk`

Shows disk space for the root filesystem.

* Total, used, free, usage percentage
* Displayed as a bar chart and numbers
* Reads from `df -h /`

### Temperature

**Module:** `system.temp`

Displays the SoC temperature.

* Reads from `/sys/class/thermal/thermal_zone0/temp`
* Color-coded: green → yellow → red as temperature rises
* Updates every second
