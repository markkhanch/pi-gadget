"""
apps/settings/bluetooth/app.py
Bluetooth manager — power toggle + device scanner.

Scan uses: sudo bluetoothctl --timeout 8 scan on
Then reads: bluetoothctl devices

Screens:
  MAIN — power status, paired devices, buttons
  SCAN — progress bar while scanning, then results
  STAT — OK/ERR feedback

Controls:
  MAIN: UP/DOWN=button  CENTER=execute  KEY3=exit
  SCAN: any key=back (after scan finishes)
  STAT: any key=back
"""

import subprocess
import time
from PIL import Image, ImageDraw

TOP_BAR_H  = 24
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
GRAY       = (150, 150, 150)
HINT_COLOR = (100, 100, 100)
GREEN      = (70, 200, 70)
RED        = (220, 70, 70)
BLUE       = (80, 160, 255)
ROW_H      = 28

SCAN_DURATION = 8   # seconds for bluetoothctl --timeout


def _sh(cmd, timeout=15):
    """Run command list, return (returncode, output)."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="ignore").strip()
    except Exception as e:
        return 1, str(e)


def _get_status() -> dict:
    """Read BT power state, MAC address, and known devices."""
    _, hci = _sh(["hciconfig", "hci0"])
    powered = "UP RUNNING" in hci

    address = ""
    for line in hci.splitlines():
        if "BD Address:" in line:
            address = line.strip().split()[2]

    # Known/paired devices from bluetoothctl
    _, devs = _sh(["bluetoothctl", "devices"])
    known = _parse_devices(devs)

    return {"powered": powered, "address": address, "known": known}


def _parse_devices(raw: str) -> list:
    """
    Parse bluetoothctl devices output.
    Each line: "Device AA:BB:CC:DD:EE:FF Name Or MAC"
    Returns list of {mac, name} — only devices with real names.
    """
    results = []
    seen    = set()
    for line in raw.splitlines():
        line = line.strip()
        # Handle both "Device MAC Name" and "[NEW] Device MAC Name"
        if "Device" not in line:
            continue
        idx = line.find("Device ")
        if idx == -1:
            continue
        rest  = line[idx + 7:]       # "MAC Name"
        parts = rest.split(" ", 1)
        if len(parts) < 1:
            continue
        mac  = parts[0]
        name = parts[1].strip() if len(parts) > 1 else ""

        # Skip devices with no real name (name == MAC with dashes)
        mac_as_name = mac.replace(":", "-")
        if not name or name == mac_as_name:
            name = mac   # show MAC if no name

        if mac not in seen:
            seen.add(mac)
            results.append({"mac": mac, "name": name})

    return results


def _turn_on() -> tuple:
    _sh(["sudo", "rfkill", "unblock", "bluetooth"])
    code, out = _sh(["sudo", "hciconfig", "hci0", "up"])
    if code != 0:
        return False, out[:50] or "hciconfig up failed"
    time.sleep(1)
    _sh(["sudo", "bluetoothctl", "power", "on"])
    return True, "Bluetooth ON"


def _turn_off() -> tuple:
    _sh(["sudo", "bluetoothctl", "power", "off"])
    _sh(["sudo", "hciconfig", "hci0", "down"])
    _sh(["sudo", "rfkill", "block", "bluetooth"])
    return True, "Bluetooth OFF"


def _do_scan() -> list:
    """
    Scan using bluetoothctl --timeout, then read devices list.
    Returns list of {mac, name}.
    """
    _sh(["sudo", "bluetoothctl", "--timeout", str(SCAN_DURATION), "scan", "on"],
        timeout=SCAN_DURATION + 5)
    _, devs = _sh(["bluetoothctl", "devices"])
    return _parse_devices(devs)


# ── App ───────────────────────────────────────────────────────

class BluetoothApp:
    S_MAIN = "main"
    S_SCAN = "scan"
    S_STAT = "stat"

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen     = self.S_MAIN
        self.status     = {}
        self.btn_sel    = 0
        self.found      = []          # devices from last scan
        self.scanning   = False       # True while scan is in progress
        self.scan_proc  = None        # subprocess for scan
        self.scan_start = 0.0
        self.scan_done  = False       # scan finished, showing results
        self.status_ok  = True
        self.status_msg = ""
        self._dirty     = True

    def on_enter(self):
        self.screen    = self.S_MAIN
        self.btn_sel   = 0
        self.found     = []
        self.scanning  = False
        self.scan_done = False
        self.status    = _get_status()
        self._dirty    = True

    def on_event(self, event) -> str:
        if self.screen == self.S_STAT:
            self.screen = self.S_MAIN
            self.status = _get_status()
            self._dirty = True
            return "stay"

        if self.screen == self.S_SCAN:
            if self.scan_done:
                # Scan finished — any key goes back
                self.screen = self.S_MAIN
                self._dirty = True
            # While scanning — ignore keys (scan is blocking in update)
            return "stay"

        # MAIN screen
        if event == "KEY3":
            return "exit"

        buttons = self._buttons()
        if event == "UP" and self.btn_sel > 0:
            self.btn_sel -= 1
            self._dirty = True
        elif event == "DOWN" and self.btn_sel < len(buttons) - 1:
            self.btn_sel += 1
            self._dirty = True
        elif event == "CENTER" and buttons:
            action = buttons[self.btn_sel][0]
            powered = self.status.get("powered", False)

            if action == "toggle":
                self._show_stat(True, "Please wait...")
                ok, msg = _turn_off() if powered else _turn_on()
                self.status_ok  = ok
                self.status_msg = msg
                self._dirty     = True

            elif action == "scan":
                # Switch to scan screen — actual scan runs in update()
                self.found     = []
                self.scanning  = True
                self.scan_done = False
                self.scan_start = time.time()
                self.screen    = self.S_SCAN
                self._dirty    = True

        return "stay"

    def update(self, dt):
        # Scan runs as a blocking call triggered once from update
        if self.screen == self.S_SCAN and self.scanning:
            self._dirty = True   # keep animating progress bar

            elapsed = time.time() - self.scan_start
            if elapsed >= 0.5 and not self.scan_done:
                # Draw progress screen first, then block on scan
                # (scan_start trick: we draw one frame first)
                if elapsed >= 1.0:
                    self.found    = _do_scan()
                    self.scanning  = False
                    self.scan_done = True
                    self.status   = _get_status()
                    self._dirty   = True

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False
        if self.screen == self.S_MAIN:
            self._draw_main()
        elif self.screen == self.S_SCAN:
            self._draw_scan()
        else:
            self._draw_stat()

    def _buttons(self):
        powered = self.status.get("powered", False)
        if powered:
            return [
                ("toggle", "Turn OFF",        RED),
                ("scan",   "Scan for devices", BLUE),
            ]
        else:
            return [
                ("toggle", "Turn ON", GREEN),
            ]

    def _show_stat(self, ok, msg):
        self.screen     = self.S_STAT
        self.status_ok  = ok
        self.status_msg = msg
        self._draw_stat()

    def _ts(self, d, text, font):
        b = d.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _header(self, d, W, title):
        d.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(d, title, self.font_label)
        d.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
               title, font=self.font_label, fill=WHITE)
        d.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

    def _draw_main(self):
        W, H    = self.hw.W, self.hw.H
        img     = Image.new("RGB", (W, H), BG)
        d       = ImageDraw.Draw(img)
        powered = self.status.get("powered", False)
        known   = self.status.get("known", [])
        address = self.status.get("address", "")

        self._header(d, W, "Bluetooth")
        y = TOP_BAR_H + 10

        # Power badge
        lbl = "ON" if powered else "OFF"
        col = BLUE if powered else RED
        lw, lh = self._ts(d, lbl, self.font_small)
        d.text(((W - lw) // 2, y), lbl, font=self.font_small, fill=col)
        y += lh + 4

        # MAC
        if address:
            aw, ah = self._ts(d, address, self.font_label)
            d.text(((W - aw) // 2, y), address,
                   font=self.font_label, fill=(70, 70, 70))
            y += ah + 6

        d.line([(10, y), (W - 10, y)], fill=SEP, width=1)
        y += 6

        # Device list — prefer found (from scan), else known
        devices     = self.found if self.found else known
        section_lbl = "Found:" if self.found else "Known devices:"

        if devices:
            lw2, lh2 = self._ts(d, section_lbl, self.font_label)
            d.text((8, y), section_lbl, font=self.font_label, fill=GRAY)
            y += lh2 + 2
            for dev in devices[:4]:
                name = dev["name"]
                # Truncate to fit
                while name and self._ts(d, name, self.font_label)[0] > W - 16:
                    name = name[:-1]
                nw, nh = self._ts(d, name, self.font_label)
                d.text((8, y), name, font=self.font_label, fill=WHITE)
                y += nh + 2
        else:
            mw, mh = self._ts(d, "No known devices", self.font_label)
            d.text(((W - mw) // 2, y), "No known devices",
                   font=self.font_label, fill=GRAY)
            y += mh + 4

        # Buttons at bottom
        buttons   = self._buttons()
        btn_h     = 26
        btn_start = H - len(buttons) * (btn_h + 4) - 20

        for i, (_, label, color) in enumerate(buttons):
            by0 = btn_start + i * (btn_h + 4)
            by1 = by0 + btn_h
            sel = i == self.btn_sel
            d.rounded_rectangle([(8, by0), (W - 8, by1)], radius=6,
                                 fill=(40, 40, 40) if sel else (15, 15, 15),
                                 outline=color if sel else SEP,
                                 width=2 if sel else 1)
            lw3, lh3 = self._ts(d, label, self.font_label)
            d.text(((W - lw3) // 2, by0 + (btn_h - lh3) // 2),
                   label, font=self.font_label, fill=color if sel else GRAY)

        hint = "UP/DN:btn  CTR:ok  K3:exit"
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)

    def _draw_scan(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "BT Scan")

        y = TOP_BAR_H + 16

        if self.scanning:
            # Scanning in progress — show animated bar
            elapsed = min(time.time() - self.scan_start, SCAN_DURATION + 1)
            pct     = min(elapsed / SCAN_DURATION, 1.0)
            dots    = "." * (int(elapsed * 2) % 4)
            msg     = f"Scanning{dots}"
            mw, mh  = self._ts(d, msg, self.font_small)
            d.text(((W - mw) // 2, y), msg, font=self.font_small, fill=BLUE)
            y += mh + 12

            # Progress bar
            bx, bw_bar, bh_bar = 20, W - 40, 10
            d.rounded_rectangle([(bx, y), (bx + bw_bar, y + bh_bar)],
                                 radius=4, outline=SEP, width=1)
            fill = max(2, int(bw_bar * pct))
            d.rounded_rectangle([(bx + 1, y + 1), (bx + fill, y + bh_bar - 1)],
                                 radius=3, fill=BLUE)
            y += bh_bar + 10

            sub = f"{SCAN_DURATION}s scan in progress"
            sw, sh = self._ts(d, sub, self.font_label)
            d.text(((W - sw) // 2, y), sub, font=self.font_label, fill=GRAY)

            hint = "Please wait..."

        else:
            # Scan done — show results
            named   = [dev for dev in self.found if dev["name"] != dev["mac"]]
            unnamed = [dev for dev in self.found if dev["name"] == dev["mac"]]

            cnt = f"{len(self.found)} devices found"
            cw, ch = self._ts(d, cnt, self.font_label)
            d.text(((W - cw) // 2, y), cnt, font=self.font_label, fill=GREEN)
            y += ch + 8

            # Show named devices first
            for dev in (named + unnamed)[:6]:
                name = dev["name"]
                while name and self._ts(d, name, self.font_label)[0] > W - 16:
                    name = name[:-1]
                col = WHITE if dev["name"] != dev["mac"] else (80, 80, 80)
                nw, nh = self._ts(d, name, self.font_label)
                d.text((8, y), name, font=self.font_label, fill=col)
                y += nh + 3

            hint = "Any key: back"

        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)

    def _draw_stat(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Bluetooth")

        color = GREEN if self.status_ok else RED
        icon  = "OK" if self.status_ok else "ERR"
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, TOP_BAR_H + 20),
               icon, font=self.font_big, fill=color)

        y = TOP_BAR_H + 20 + ih + 12
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, y), line, font=self.font_label, fill=WHITE)
            y += lh + 4

        hw2, hh2 = self._ts(d, "Any key: back", self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 4),
               "Any key: back", font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
