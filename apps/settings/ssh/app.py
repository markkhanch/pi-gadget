"""
apps/settings/ssh/app.py
SSH Toggle — enable/disable SSH service on the Pi.

Shows current status, IP address for connecting, and allows
toggling SSH on/off via systemctl.

Controls:
  CENTER : toggle SSH on/off
  K3     : exit
"""

import os
import subprocess
import threading
from PIL import Image, ImageDraw

TOP_H = 26
BOT_H = 18

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEP    = (25,  45,  75)
SEP_HI = (50,  90,  140)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
GREEN  = (50,  220, 120)
RED    = (255, 70,  70)
YELLOW = (255, 200, 50)
WHITE  = (220, 235, 255)


def _ts(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def _get_ssh_status() -> bool:
    """Return True if SSH service is active."""
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "ssh"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _get_local_ip() -> str:
    """Get primary local IP address."""
    try:
        r = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True, timeout=5
        )
        ips = r.stdout.strip().split()
        return ips[0] if ips else "unknown"
    except Exception:
        return "unknown"


def _get_hostname() -> str:
    try:
        r = subprocess.run(
            ["hostname"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return "pi"


def _set_ssh(enable: bool):
    """Enable or disable SSH service."""
    action = "start" if enable else "stop"
    subprocess.run(["sudo", "systemctl", action, "ssh"],
                   capture_output=True, timeout=10)
    # Also enable/disable persistence across reboots
    persist = "enable" if enable else "disable"
    subprocess.run(["sudo", "systemctl", persist, "ssh"],
                   capture_output=True, timeout=10)


class SshApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self._ssh_on  = False
        self._ip      = ""
        self._host    = ""
        self._busy    = False
        self._dirty   = True

    def on_enter(self):
        self._dirty = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        self._ssh_on = _get_ssh_status()
        self._ip     = _get_local_ip()
        self._host   = _get_hostname()
        self._busy   = False
        self._dirty  = True

    def _toggle(self):
        if self._busy:
            return
        self._busy  = True
        self._dirty = True

        def _do():
            _set_ssh(not self._ssh_on)
            self._refresh()

        threading.Thread(target=_do, daemon=True).start()

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"
        elif event == "CENTER":
            self._toggle()
        return "stay"

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
        d.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "SSH", font=self.font_label, fill=CYAN)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        M  = 10
        lh = self.font_label.size + 8
        y  = TOP_H + 10

        if self._busy:
            msg = "Please wait..."
            mw, mh = _ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, TOP_H + (H - TOP_H - BOT_H) // 2 - mh // 2),
                   msg, font=self.font_label, fill=YELLOW)
        else:
            # Status badge
            status_txt = "● ENABLED" if self._ssh_on else "○ DISABLED"
            status_col = GREEN       if self._ssh_on else RED
            sw, sh = _ts(d, status_txt, self.font_small)
            d.text(((W - sw) // 2, y), status_txt,
                   font=self.font_small, fill=status_col)
            y += sh + 12

            d.line([(M, y), (W - M, y)], fill=SEP, width=1)
            y += 8

            if self._ssh_on and self._ip:
                # Connection info
                rows = [
                    ("Host:", self._host,            WHITE),
                    ("IP:",   self._ip,              CYAN),
                    ("Port:", "22",                  DIM),
                    ("User:", os.environ.get("USER", "pi"), DIM),
                ]
                for label, value, col in rows:
                    lw, _ = _ts(d, label, self.font_label)
                    d.text((M, y), label, font=self.font_label, fill=DIM)
                    d.text((M + lw + 6, y), value, font=self.font_label, fill=col)
                    y += lh

                y += 4
                d.line([(M, y), (W - M, y)], fill=SEP, width=1)
                y += 8

                # Connection command hint
                cmd = f"ssh {os.environ.get('USER', 'pi')}@{self._ip}"
                cw, _ = _ts(d, cmd, self.font_label)
                if cw > W - M * 2:
                    cmd = f"ssh ...@{self._ip}"
                d.text((M, y), cmd, font=self.font_label, fill=YELLOW)

            elif not self._ssh_on:
                msg = "SSH is disabled"
                mw, _ = _ts(d, msg, self.font_label)
                d.text(((W - mw) // 2, y + 10),
                       msg, font=self.font_label, fill=DIM)

        # Hint bar
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        action = "disable" if self._ssh_on else "enable"
        hint   = f"CTR:{action}  K3:back"
        hw2, hh = _ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh - 2),
               hint, font=self.font_label, fill=HINT)

        self.hw.show(img)
