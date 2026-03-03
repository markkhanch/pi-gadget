"""
apps/settings/mac_changer/app.py
MAC Address Changer — randomize or set custom MAC for wlan0/eth0.

Screens:
  MAIN   — shows current MACs, select interface + action
  INPUT  — enter custom MAC via on-screen selector
  STATUS — result of operation

Controls:
  MAIN screen:
    UP / DOWN  — select option
    CENTER     — execute selected action
    KEY3       — exit

  STATUS screen:
    Any key    — back to main
"""

import os
import re
import random
import subprocess
import threading
from PIL import Image, ImageDraw

TOP_H  = 26
BOT_H  = 18
ROW_H  = 34

BG      = (4,   8,   16)
HDR_BG  = (8,   14,  28)
SEL_BG  = (12,  25,  50)
SEP     = (25,  45,  75)
SEP_HI  = (50,  90,  140)
WHITE   = (220, 235, 255)
DIM     = (70,  100, 140)
HINT    = (50,  75,  110)
CYAN    = (0,   210, 255)
GREEN   = (50,  220, 120)
YELLOW  = (255, 200, 50)
RED     = (255, 70,  70)
ORANGE  = (255, 140, 30)
PURPLE  = (160, 80,  255)

STATE_MAIN   = "main"
STATE_BUSY   = "busy"
STATE_RESULT = "result"

INTERFACES = ["wlan0", "eth0"]


def _get_mac(iface: str) -> str:
    """Read current MAC address for interface."""
    try:
        path = f"/sys/class/net/{iface}/address"
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return "unavailable"


def _get_original_mac(iface: str) -> str:
    """Try to get permanent/original MAC via ethtool or ip."""
    try:
        r = subprocess.run(
            ["ethtool", "-P", iface],
            capture_output=True, timeout=3
        )
        out = r.stdout.decode("utf-8", errors="ignore")
        m = re.search(r'([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})', out, re.I)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return ""


def _random_mac() -> str:
    """Generate a random locally administered unicast MAC."""
    # First byte: locally administered (bit 1 set) + unicast (bit 0 clear)
    first = random.randint(0, 63) * 4 + 2  # ensures bits: xxxxxx10
    rest  = [random.randint(0, 255) for _ in range(5)]
    return ":".join(f"{b:02x}" for b in [first] + rest)


def _set_mac(iface: str, mac: str) -> tuple:
    """Set MAC address. Returns (ok, message)."""
    # Validate MAC format
    if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac.lower()):
        return False, f"Invalid MAC format:\n{mac}"
    try:
        cmds = [
            ["sudo", "ip", "link", "set", iface, "down"],
            ["sudo", "ip", "link", "set", iface, "address", mac],
            ["sudo", "ip", "link", "set", iface, "up"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            if r.returncode != 0:
                err = r.stderr.decode("utf-8", errors="ignore").strip()
                return False, err[:60] or "Command failed"
        return True, f"MAC set:\n{mac}"
    except Exception as e:
        return False, str(e)[:60]


# ── Menu options ──────────────────────────────────────────────

def _build_options(iface: str) -> list:
    """Build list of action options for selected interface."""
    return [
        {"label": "Randomize MAC",    "action": "random",   "color": CYAN},
        {"label": "Restore original", "action": "restore",  "color": GREEN},
        {"label": "Switch interface",  "action": "switch",   "color": YELLOW},
    ]


class MacChangerApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.iface_idx = 0
        self.sel       = 0
        self.state     = STATE_MAIN

        self.current_macs = {}
        self.options      = []

        self.ok  = True
        self.msg = ""
        self._dirty = True

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _trunc(self, draw, text, font, max_w):
        while text:
            w, _ = self._ts(draw, text, font)
            if w <= max_w:
                return text
            text = text[:-2] + "…"
        return ""

    def on_enter(self):
        self._refresh()
        self.state  = STATE_MAIN
        self._dirty = True

    def _refresh(self):
        for iface in INTERFACES:
            self.current_macs[iface] = _get_mac(iface)
        self.options = _build_options(INTERFACES[self.iface_idx])

    def on_event(self, event) -> str:
        if self.state == STATE_BUSY:
            return "stay"

        if self.state == STATE_RESULT:
            self._refresh()
            self.state  = STATE_MAIN
            self._dirty = True
            return "stay"

        # MAIN screen
        if event == "KEY3":
            return "exit"

        if event == "UP" and self.sel > 0:
            self.sel   -= 1
            self._dirty = True

        elif event == "DOWN" and self.sel < len(self.options) - 1:
            self.sel   += 1
            self._dirty = True

        elif event == "CENTER":
            action = self.options[self.sel]["action"]
            if action == "switch":
                self.iface_idx = (self.iface_idx + 1) % len(INTERFACES)
                self.options   = _build_options(INTERFACES[self.iface_idx])
                self.sel       = 0
                self._dirty    = True
            elif action == "random":
                mac = _random_mac()
                self._apply(INTERFACES[self.iface_idx], mac)
            elif action == "restore":
                iface = INTERFACES[self.iface_idx]
                orig  = _get_original_mac(iface)
                if orig:
                    self._apply(iface, orig)
                else:
                    self.ok     = False
                    self.msg    = "Original MAC not found.\nDevice may not support\npermanent MAC query."
                    self.state  = STATE_RESULT
                    self._dirty = True

        return "stay"

    def _apply(self, iface: str, mac: str):
        self.state  = STATE_BUSY
        self._dirty = True
        threading.Thread(
            target=self._do_apply,
            args=(iface, mac),
            daemon=True
        ).start()

    def _do_apply(self, iface: str, mac: str):
        ok, msg     = _set_mac(iface, mac)
        self.ok     = ok
        self.msg    = msg
        self.state  = STATE_RESULT
        self._dirty = True

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=PURPLE)
        tw, th = self._ts(d, "MAC CHANGER", self.font_label)
        d.text((10, (TOP_H - th) // 2), "MAC CHANGER",
               font=self.font_label, fill=PURPLE)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_BUSY:
            self._draw_busy(d, W, H)
        elif self.state == STATE_RESULT:
            self._draw_result(d, W, H)
        else:
            self._draw_main(d, W, H)

        self.hw.show(img)

    def _draw_main(self, d, W, H):
        MARGIN  = 6
        iface   = INTERFACES[self.iface_idx]
        mac     = self.current_macs.get(iface, "—")

        # Interface info block
        y = TOP_H + 6
        iw, ih = self._ts(d, iface.upper(), self.font_label)
        d.text((MARGIN, y), iface.upper(), font=self.font_label, fill=CYAN)

        # MAC address — split in two lines if needed
        mac_label = mac
        mw, mh = self._ts(d, mac_label, self.font_label)
        if mw > W - MARGIN * 2:
            # Split at middle colon
            parts = mac.split(":")
            mac_label = ":".join(parts[:3]) + "\n" + ":".join(parts[3:])

        y += ih + 2
        for line in mac_label.split("\n"):
            lw, lh = self._ts(d, line, self.font_label)
            d.text((MARGIN, y), line, font=self.font_label, fill=YELLOW)
            y += lh + 1

        d.line([(MARGIN, y + 4), (W - MARGIN, y + 4)], fill=SEP, width=1)
        y += 10

        # Options
        for i, opt in enumerate(self.options):
            is_sel = i == self.sel
            y1 = y + ROW_H

            if is_sel:
                d.rectangle([(0, y), (W, y1 - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (3, y1 - 1)], fill=opt["color"])

            col = WHITE if is_sel else DIM
            lw, lh = self._ts(d, opt["label"], self.font_label)
            d.text((MARGIN + 6, y + (ROW_H - lh) // 2),
                   opt["label"], font=self.font_label, fill=col)

            if is_sel:
                aw, ah = self._ts(d, ">", self.font_label)
                d.text((W - aw - MARGIN, y + (ROW_H - ah) // 2),
                       ">", font=self.font_label, fill=opt["color"])

            d.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)
            y += ROW_H

        # Bottom hint
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hint = "UP/DN:select  CTR:apply  K3:exit"
        hint = self._trunc(d, hint, self.font_label, W - 4)
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT)

    def _draw_busy(self, d, W, H):
        msg = "Applying..."
        mw, mh = self._ts(d, msg, self.font_label)
        cy = TOP_H + (H - TOP_H) // 2
        d.text(((W - mw) // 2, cy - mh // 2),
               msg, font=self.font_label, fill=CYAN)

    def _draw_result(self, d, W, H):
        cy    = TOP_H + (H - TOP_H - BOT_H) // 2
        icon  = "OK" if self.ok else "ERR"
        color = GREEN if self.ok else RED
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, cy - ih - 6),
               icon, font=self.font_big, fill=color)
        for j, line in enumerate(self.msg.split("\n")):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, cy + 4 + j * (lh + 3)),
                   line, font=self.font_label, fill=WHITE)
        hint = "Any key: back"
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 4),
               hint, font=self.font_label, fill=HINT)
