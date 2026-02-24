"""
apps/settings/bluetooth/app.py
Bluetooth manager — scan, connect, pair, disconnect, forget, trust.

Key design decisions:
  - Scan runs in a background thread so progress bar actually animates
  - List uses clean rows: status dot + name + short MAC
  - Detail screen shows status tags + action buttons
  - No fake animation — progress bar reflects real elapsed time vs timeout

Screens:  LIST → SCAN → LIST  |  LIST → DETAIL → LIST  |  any → STATUS → LIST
Controls:
  LIST:   UP/DOWN  CENTER=open detail  KEY1=scan  KEY3=exit
  SCAN:   (no input while scanning)  any key=back after done
  DETAIL: UP/DOWN  CENTER=execute     KEY3=back
  STATUS: any key=back
"""

import subprocess
import threading
import time
from PIL import Image, ImageDraw

# ── Dimensions ────────────────────────────────────────────────
# Designed for 128×128 display
TOP_H  = 22
BOT_H  = 18
ROW_H  = 36

# ── Palette ───────────────────────────────────────────────────
BG        = (0,   0,   0  )
HDR_BG    = (15,  15,  20 )
SEL_BG    = (28,  28,  48 )
SEL_LINE  = (80,  80, 180 )
SEP       = (40,  40,  40 )
SEP_HI    = (70,  70,  70 )
WHITE     = (255, 255, 255)
LGRAY     = (180, 180, 180)
GRAY      = (120, 120, 120)
DIM       = (60,  60,  60 )
HINT      = (80,  80,  80 )
GREEN     = (50,  200,  80)
RED       = (220,  60,  60)
BLUE      = (60,  140, 255)
YELLOW    = (220, 180,  40)
CYAN      = (40,  200, 200)

SCAN_SEC  = 8


def _sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="ignore").strip()
    except Exception as e:
        return 1, str(e)


# ── BT data helpers ───────────────────────────────────────────

def _is_powered():
    _, out = _sh(["hciconfig", "hci0"])
    return "UP RUNNING" in out


def _power_on():
    _sh(["sudo", "rfkill", "unblock", "bluetooth"])
    code, out = _sh(["sudo", "hciconfig", "hci0", "up"])
    if code != 0:
        return False, "Power on failed\n" + out[:40]
    time.sleep(1)
    _sh(["sudo", "bluetoothctl", "power", "on"])
    return True, "Bluetooth ON"


def _power_off():
    _sh(["sudo", "bluetoothctl", "power", "off"])
    _sh(["sudo", "hciconfig", "hci0", "down"])
    _sh(["sudo", "rfkill", "block", "bluetooth"])
    return True, "Bluetooth OFF"


def _parse_devices(raw):
    """Parse 'bluetoothctl devices' into [{mac, name, has_name}]."""
    results, seen = [], set()
    for line in raw.splitlines():
        line = line.strip()
        idx  = line.find("Device ")
        if idx == -1:
            continue
        rest  = line[idx + 7:]
        parts = rest.split(" ", 1)
        if not parts:
            continue
        mac = parts[0]
        if len(mac) != 17 or mac.count(":") != 5:
            continue
        name     = parts[1].strip() if len(parts) > 1 else mac
        has_name = not (len(name) == 17 and "-" in name)
        if mac not in seen:
            seen.add(mac)
            results.append({"mac": mac, "name": name, "has_name": has_name})
    return results


def _load_devices():
    _, raw  = _sh(["bluetoothctl", "devices"])
    devices = _parse_devices(raw)
    # Named devices first, then anonymous, both sorted alphabetically
    devices.sort(key=lambda d: (not d["has_name"], d["name"].lower()))
    return devices


def _get_info(mac):
    _, raw = _sh(["bluetoothctl", "info", mac])
    info   = {"mac": mac, "name": mac,
              "paired": False, "connected": False,
              "trusted": False, "bonded": False}
    for line in raw.splitlines():
        s = line.strip()
        if   s.startswith("Name:"):      info["name"]      = s[5:].strip()
        elif s.startswith("Paired:"):    info["paired"]    = "yes" in s
        elif s.startswith("Connected:"): info["connected"] = "yes" in s
        elif s.startswith("Trusted:"):   info["trusted"]   = "yes" in s
        elif s.startswith("Bonded:"):    info["bonded"]    = "yes" in s
    return info


def _pair(mac):
    code, out = _sh(["sudo", "bluetoothctl", "pair", mac], timeout=25)
    ok = code == 0 and "successful" in out.lower()
    return ok, ("Paired!" if ok else out.split("\n")[-1][:45] or "Pairing failed")


def _connect(mac):
    code, out = _sh(["sudo", "bluetoothctl", "connect", mac], timeout=15)
    ok = code == 0 and "successful" in out.lower()
    return ok, ("Connected!" if ok else out.split("\n")[-1][:45] or "Connect failed")


def _disconnect(mac):
    code, out = _sh(["sudo", "bluetoothctl", "disconnect", mac], timeout=10)
    ok = code == 0 and "successful" in out.lower()
    return ok, ("Disconnected" if ok else out.split("\n")[-1][:45] or "Failed")


def _forget(mac):
    code, out = _sh(["sudo", "bluetoothctl", "remove", mac], timeout=10)
    return code == 0, ("Forgotten" if code == 0 else out[:45] or "Failed")


def _set_trust(mac, enable):
    cmd = "trust" if enable else "untrust"
    code, out = _sh(["sudo", "bluetoothctl", cmd, mac], timeout=10)
    lbl = "Trusted" if enable else "Untrusted"
    return code == 0, (lbl if code == 0 else out[:45] or "Failed")


# ── App ───────────────────────────────────────────────────────

class BluetoothApp:
    S_LIST   = "list"
    S_SCAN   = "scan"
    S_DETAIL = "detail"
    S_STATUS = "status"

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_sm, self.font_lb = fonts

        self.screen     = self.S_LIST
        self.powered    = False
        self.devices    = []
        self.sel        = 0
        self.scroll     = 0

        self.target     = None  # current device for detail
        self.info       = {}
        self.det_sel    = 0

        # Scan state — scan runs in a background thread
        self._scan_thread  = None
        self._scan_result  = None   # set by thread when done
        self.scan_start    = 0.0
        self.scan_done     = False

        self.status_ok  = True
        self.status_msg = ""
        self._dirty     = True

    def on_enter(self):
        self.screen  = self.S_LIST
        self.powered = _is_powered()
        self.devices = _load_devices()
        self.sel     = 0
        self.scroll  = 0
        self._dirty  = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.screen == self.S_STATUS:
            self.screen  = self.S_LIST
            self.powered = _is_powered()
            self.devices = _load_devices()
            self.sel     = 0
            self._dirty  = True
            return "stay"

        if self.screen == self.S_SCAN:
            if self.scan_done:
                self.screen = self.S_LIST
                self._dirty = True
            return "stay"

        if self.screen == self.S_DETAIL:
            return self._ev_detail(event)

        return self._ev_list(event)

    def _ev_list(self, event) -> str:
        if event == "KEY3":
            return "exit"

        if event == "KEY1":
            if not self.powered:
                self._show_status(True, "Turning on\nBluetooth...")
                ok, msg = _power_on()
                self.powered    = _is_powered()
                self.status_ok  = ok
                self.status_msg = msg
                self._dirty     = True
            else:
                self._start_scan()
            return "stay"

        if event == "KEY2" and self.powered:
            # Turn off Bluetooth
            self._show_status(True, "Turning off\nBluetooth...")
            ok, msg         = _power_off()
            self.powered    = _is_powered()
            self.status_ok  = ok
            self.status_msg = msg
            self._dirty     = True
            return "stay"

        max_rows = (self.hw.H - TOP_H - BOT_H) // ROW_H
        if event == "UP" and self.sel > 0:
            self.sel -= 1
            if self.sel < self.scroll:
                self.scroll = self.sel
            self._dirty = True
        elif event == "DOWN" and self.sel < len(self.devices) - 1:
            self.sel += 1
            if self.sel >= self.scroll + max_rows:
                self.scroll = self.sel - max_rows + 1
            self._dirty = True
        elif event == "CENTER" and self.devices:
            self.target  = self.devices[self.sel]
            self.info    = _get_info(self.target["mac"])
            self.det_sel = 0
            self.screen  = self.S_DETAIL
            self._dirty  = True

        return "stay"

    def _ev_detail(self, event) -> str:
        if event == "KEY3":
            self.screen = self.S_LIST
            self._dirty = True
            return "stay"

        acts = self._actions()
        if event == "UP" and self.det_sel > 0:
            self.det_sel -= 1
            self._dirty = True
        elif event == "DOWN" and self.det_sel < len(acts) - 1:
            self.det_sel += 1
            self._dirty = True
        elif event == "CENTER" and acts:
            self._exec(acts[self.det_sel][0])

        return "stay"

    def _actions(self):
        info = self.info
        acts = []
        if info.get("connected"):
            acts.append(("disconnect", "Disconnect",     RED))
        else:
            if info.get("paired"):
                acts.append(("connect",  "Connect",          GREEN))
            else:
                acts.append(("pair",     "Pair & Connect",   GREEN))
        if info.get("paired") or info.get("connected"):
            if info.get("trusted"):
                acts.append(("untrust", "Remove trust",  YELLOW))
            else:
                acts.append(("trust",   "Trust device",  CYAN))
            acts.append(("forget",  "Forget device",     RED))
        acts.append(("back", "← Back", DIM))
        return acts

    def _exec(self, action_id):
        if action_id == "back":
            self.screen = self.S_LIST
            self._dirty = True
            return

        mac = self.target["mac"]
        msg = {"connect":    "Connecting...",
               "disconnect": "Disconnecting...",
               "pair":       "Pairing...\n(up to 20s)",
               "forget":     "Forgetting...",
               "trust":      "Trusting...",
               "untrust":    "Removing trust..."}.get(action_id, "Please wait...")

        self._show_status(True, msg)

        if   action_id == "connect":    ok, msg = _connect(mac)
        elif action_id == "disconnect": ok, msg = _disconnect(mac)
        elif action_id == "pair":
            ok, msg = _pair(mac)
            if ok:
                time.sleep(1)
                _connect(mac)
        elif action_id == "forget":     ok, msg = _forget(mac)
        elif action_id == "trust":      ok, msg = _set_trust(mac, True)
        elif action_id == "untrust":    ok, msg = _set_trust(mac, False)
        else:                           ok, msg = False, "Unknown"

        self.status_ok  = ok
        self.status_msg = msg
        self._dirty     = True

    # ── Scan (background thread) ──────────────────────────────

    def _start_scan(self):
        self.scan_done    = False
        self._scan_result = None
        self.scan_start   = time.time()
        self.screen       = self.S_SCAN
        self._dirty       = True

        def worker():
            result = []
            _sh(["sudo", "bluetoothctl", "--timeout", str(SCAN_SEC), "scan", "on"],
                timeout=SCAN_SEC + 5)
            result = _load_devices()
            self._scan_result = result

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    # ── Update ────────────────────────────────────────────────

    def update(self, dt):
        if self.screen == self.S_SCAN:
            self._dirty = True   # animate every frame
            # Check if thread finished
            if self._scan_result is not None:
                self.devices    = self._scan_result
                self._scan_result = None
                self.powered    = _is_powered()
                self.scan_done  = True
                self.sel        = 0
                self.scroll     = 0

    # ── Draw ──────────────────────────────────────────────────

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False
        {self.S_LIST:   self._draw_list,
         self.S_SCAN:   self._draw_scan,
         self.S_DETAIL: self._draw_detail,
         self.S_STATUS: self._draw_status}.get(self.screen, lambda: None)()

    # ── Draw helpers ──────────────────────────────────────────

    def _ts(self, d, text, font):
        b = d.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _header(self, d, W, title, left="", right=""):
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        tw, th = self._ts(d, title, self.font_lb)
        cy = (TOP_H - th) // 2
        d.text(((W - tw) // 2, cy), title, font=self.font_lb, fill=WHITE)
        if left:
            lw, lh = self._ts(d, left, self.font_lb)
            d.text((4, (TOP_H - lh) // 2), left, font=self.font_lb, fill=GRAY)
        if right:
            rw, rh = self._ts(d, right, self.font_lb)
            d.text((W - rw - 4, (TOP_H - rh) // 2), right, font=self.font_lb, fill=GRAY)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    def _show_status(self, ok, msg):
        self.screen     = self.S_STATUS
        self.status_ok  = ok
        self.status_msg = msg
        self._draw_status()

    # ── LIST screen ───────────────────────────────────────────

    def _draw_list(self):
        W, H   = self.hw.W, self.hw.H
        img    = Image.new("RGB", (W, H), BG)
        d      = ImageDraw.Draw(img)
        pwr    = self.powered

        pwr_lbl = "●ON" if pwr else "●OFF"
        pwr_col = BLUE if pwr else RED
        k1_lbl  = "K1:scan" if pwr else "K1:ON"  # K2=OFF when powered

        # Header
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        tw, th = self._ts(d, "Bluetooth", self.font_lb)
        d.text(((W - tw) // 2, (TOP_H - th) // 2),
               "Bluetooth", font=self.font_lb, fill=WHITE)
        pw, ph = self._ts(d, pwr_lbl, self.font_lb)
        d.text((4, (TOP_H - ph) // 2), pwr_lbl, font=self.font_lb, fill=pwr_col)
        k1w, k1h = self._ts(d, k1_lbl, self.font_lb)
        d.text((W - k1w - 4, (TOP_H - k1h) // 2), k1_lbl, font=self.font_lb, fill=GRAY)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        # Bottom bar
        bot = "K2:OFF  CTR:open  K3:exit"
        bw, bh = self._ts(d, bot, self.font_lb)
        d.text(((W - bw) // 2, H - bh - 2), bot, font=self.font_lb, fill=HINT)

        content_h = H - TOP_H - BOT_H
        max_rows  = content_h // ROW_H

        if not self.devices:
            line1 = "No devices" if pwr else "Bluetooth is OFF"
            line2 = "K1 to scan" if pwr else "K1 to turn on"
            l1w, l1h = self._ts(d, line1, self.font_lb)
            l2w, l2h = self._ts(d, line2, self.font_lb)
            mid = TOP_H + content_h // 2
            d.text(((W - l1w) // 2, mid - l1h - 3), line1, font=self.font_lb, fill=GRAY)
            d.text(((W - l2w) // 2, mid + 3),        line2, font=self.font_lb, fill=DIM)
            self.hw.show(img)
            return

        for row in range(max_rows):
            idx = self.scroll + row
            if idx >= len(self.devices):
                break
            dev = self.devices[idx]
            y0  = TOP_H + row * ROW_H
            y1  = y0 + ROW_H
            sel = idx == self.sel

            # Selection background
            if sel:
                d.rectangle([(2, y0 + 1), (W - 3, y1 - 2)],
                             fill=SEL_BG)
                # Left accent bar
                d.rectangle([(0, y0 + 2), (3, y1 - 3)], fill=SEL_LINE)

            # Status dot
            dot_cx = 14
            dot_cy = y0 + ROW_H // 2
            dot_r  = 4

            # Use cached info if this is the target device
            if self.target and dev["mac"] == self.target["mac"] and self.info:
                conn   = self.info.get("connected", False)
                paired = self.info.get("paired", False)
            else:
                conn   = False
                paired = dev["has_name"]  # heuristic

            dot_col = GREEN if conn else (BLUE if paired else DIM)
            d.ellipse([(dot_cx - dot_r, dot_cy - dot_r),
                       (dot_cx + dot_r, dot_cy + dot_r)], fill=dot_col)

            # Name (top line)
            name    = dev["name"]
            name_x  = dot_cx + dot_r + 6
            max_w   = W - name_x - 6
            while name and self._ts(d, name, self.font_lb)[0] > max_w:
                name = name[:-1]
            d.text((name_x, y0 + 5),
                   name, font=self.font_lb,
                   fill=WHITE if dev["has_name"] else GRAY)

            # Short MAC (bottom line, dimmed)
            mac_short = "…" + dev["mac"][-8:]
            d.text((name_x, y0 + 5 + self.font_lb.size + 2),
                   mac_short, font=self.font_lb, fill=DIM)

            d.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)

        # Scroll indicator dots on right edge
        if len(self.devices) > max_rows:
            dot_area_h = content_h
            dot_spacing = dot_area_h / len(self.devices)
            for i, _ in enumerate(self.devices):
                dy = int(TOP_H + i * dot_spacing + dot_spacing / 2)
                col = WHITE if i == self.sel else DIM
                r   = 2 if i == self.sel else 1
                d.ellipse([(W - 5 - r, dy - r), (W - 5 + r, dy + r)], fill=col)

        self.hw.show(img)

    # ── SCAN screen ───────────────────────────────────────────

    def _draw_scan(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        if not self.scan_done:
            # Scanning in progress
            self._header(d, W, "Scanning...")

            elapsed  = time.time() - self.scan_start
            pct      = min(elapsed / SCAN_SEC, 1.0)
            secs_left = max(0, int(SCAN_SEC - elapsed) + 1)

            # Pulse dot animation
            pulse_idx = int(elapsed * 3) % 4
            y = TOP_H + 20
            dots_str = "◉ " * (pulse_idx + 1)
            dw, dh = self._ts(d, dots_str, self.font_lb)
            d.text(((W - dw) // 2, y), dots_str, font=self.font_lb, fill=BLUE)
            y += dh + 14

            # Progress bar — fills as time passes
            bx  = 14
            bw2 = W - 28
            bh2 = 10
            # Track background
            d.rounded_rectangle([(bx, y), (bx + bw2, y + bh2)],
                                 radius=5, fill=(20, 20, 30), outline=SEP_HI, width=1)
            # Fill
            fill_w = max(8, int((bw2 - 2) * pct))
            d.rounded_rectangle([(bx + 1, y + 1), (bx + fill_w, y + bh2 - 1)],
                                 radius=4, fill=BLUE)
            y += bh2 + 10

            # Countdown
            countdown = f"{secs_left}s"
            cw, ch = self._ts(d, countdown, self.font_sm)
            d.text(((W - cw) // 2, y), countdown, font=self.font_sm, fill=LGRAY)
            y += ch + 8

            sub = "searching nearby devices"
            sw, sh = self._ts(d, sub, self.font_lb)
            d.text(((W - sw) // 2, y), sub, font=self.font_lb, fill=DIM)

        else:
            # Scan complete — show summary then wait for keypress
            self._header(d, W, "Scan Complete")

            named   = [dv for dv in self.devices if dv["has_name"]]
            unnamed = [dv for dv in self.devices if not dv["has_name"]]

            y = TOP_H + 14

            # Count summary
            cnt_lbl = f"{len(self.devices)} found"
            cw, ch  = self._ts(d, cnt_lbl, self.font_sm)
            d.text(((W - cw) // 2, y), cnt_lbl, font=self.font_sm, fill=GREEN)
            y += ch + 10

            # Named devices list
            for dev in named[:4]:
                name = dev["name"]
                while name and self._ts(d, name, self.font_lb)[0] > W - 22:
                    name = name[:-1]
                # Small dot + name
                d.ellipse([(8, y + 5), (14, y + 11)], fill=BLUE)
                d.text((18, y), name, font=self.font_lb, fill=WHITE)
                y += self.font_lb.size + 6

            if unnamed:
                anon = f"+ {len(unnamed)} anonymous"
                aw, ah = self._ts(d, anon, self.font_lb)
                d.text(((W - aw) // 2, y), anon, font=self.font_lb, fill=DIM)
                y += ah + 4

            hint = "any key: back"
            hw2, hh2 = self._ts(d, hint, self.font_lb)
            d.text(((W - hw2) // 2, H - hh2 - 2), hint, font=self.font_lb, fill=HINT)

        self.hw.show(img)

    # ── DETAIL screen ─────────────────────────────────────────

    def _draw_detail(self):
        W, H    = self.hw.W, self.hw.H
        img     = Image.new("RGB", (W, H), BG)
        d       = ImageDraw.Draw(img)
        info    = self.info
        acts    = self._actions()

        self._header(d, W, "Device", right="K3:back")
        y = TOP_H + 8

        # Device name
        name = info.get("name", self.target["mac"])
        while name and self._ts(d, name, self.font_sm)[0] > W - 12:
            name = name[:-1]
        nw, nh = self._ts(d, name, self.font_sm)
        d.text(((W - nw) // 2, y), name, font=self.font_sm, fill=WHITE)
        y += nh + 6

        # Status badges — inline row
        badges = []
        if info.get("connected"): badges.append(("Connected", GREEN))
        if info.get("paired"):    badges.append(("Paired",    BLUE))
        if info.get("trusted"):   badges.append(("Trusted",   YELLOW))

        if badges:
            pad = 5
            # Measure total width
            total_w = sum(self._ts(d, t, self.font_lb)[0] + pad * 2 + 6
                          for t, _ in badges) - 6
            bx = (W - total_w) // 2
            for txt, col in badges:
                tw2, th2 = self._ts(d, txt, self.font_lb)
                bx1 = bx + tw2 + pad * 2
                by1 = y + th2 + pad
                d.rounded_rectangle([(bx, y), (bx1, by1)],
                                     radius=3, fill=(0, 0, 0), outline=col, width=1)
                d.text((bx + pad, y + pad // 2), txt, font=self.font_lb, fill=col)
                bx = bx1 + 6
            y += th2 + pad + 8
        else:
            uw, uh = self._ts(d, "Unknown", self.font_lb)
            d.text(((W - uw) // 2, y), "Unknown", font=self.font_lb, fill=DIM)
            y += uh + 8

        # Shortened MAC
        mac_s = self.target["mac"]
        mw, mh = self._ts(d, mac_s, self.font_lb)
        d.text(((W - mw) // 2, y), mac_s, font=self.font_lb, fill=DIM)
        y += mh + 8

        d.line([(10, y), (W - 10, y)], fill=SEP_HI, width=1)
        y += 8

        # Action buttons
        btn_h = 26
        gap   = 4
        for i, (act_id, label, color) in enumerate(acts):
            by0 = y + i * (btn_h + gap)
            by1 = by0 + btn_h
            sel = i == self.det_sel

            if sel:
                d.rectangle([(8, by0), (W - 9, by1)], fill=SEL_BG)
                d.rectangle([(8, by0), (10, by1)], fill=color)   # left accent
            else:
                d.rectangle([(8, by0), (W - 9, by1)], fill=(12, 12, 12))

            lw3, lh3 = self._ts(d, label, self.font_lb)
            lbl_col  = color if sel else (GRAY if act_id != "back" else DIM)
            d.text(((W - lw3) // 2, by0 + (btn_h - lh3) // 2),
                   label, font=self.font_lb, fill=lbl_col)

        self.hw.show(img)

    # ── STATUS screen ─────────────────────────────────────────

    def _draw_status(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Bluetooth")

        col  = GREEN if self.status_ok else RED
        icon = "OK" if self.status_ok else "ERR"
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, TOP_H + 20), icon, font=self.font_big, fill=col)

        y = TOP_H + 20 + ih + 12
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(d, line, self.font_lb)
            d.text(((W - lw) // 2, y), line, font=self.font_lb, fill=WHITE)
            y += lh + 5

        hint = "any key: back"
        hw2, hh2 = self._ts(d, hint, self.font_lb)
        d.text(((W - hw2) // 2, H - hh2 - 4), hint, font=self.font_lb, fill=HINT)
        self.hw.show(img)
