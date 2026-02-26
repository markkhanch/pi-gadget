"""
apps/settings/hostname/app.py
Change device hostname.

Controls:
  Joystick     — keyboard navigation
  KEY1         — cycle keyboard language
  KEY2         — confirm and apply
  KEY3         — cancel, exit
"""

import subprocess
from PIL import Image, ImageDraw
from core.ui_keyboard import OnScreenKeyboard

TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
HINT_COLOR = (100, 100, 100)
GREEN      = (70, 200, 70)
RED        = (220, 70, 70)

SCREEN_KB     = "kb"
SCREEN_STATUS = "status"


def _get_hostname() -> str:
    try:
        with open("/etc/hostname") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def _set_hostname(name: str) -> tuple:
    """Apply new hostname via hostnamectl. Returns (ok, message)."""
    # Validate: only letters, digits, hyphens, no leading/trailing hyphen
    import re
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', name):
        return False, "Invalid hostname"
    try:
        r = subprocess.run(
            ["sudo", "hostnamectl", "set-hostname", name],
            capture_output=True, timeout=10
        )
        if r.returncode == 0:
            return True, f"Hostname set to\n{name}"
        err = r.stderr.decode("utf-8", errors="ignore").strip()
        return False, err[:40] or "Failed"
    except Exception as e:
        return False, str(e)[:40]


class HostnameApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.keyboard   = OnScreenKeyboard(hw.disp, self.font_label)
        self.screen     = SCREEN_KB
        self.status_ok  = True
        self.status_msg = ""
        self._dirty     = True

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def on_enter(self):
        current = _get_hostname()
        self.keyboard.start(
            prompt="Hostname:",
            initial_text=current,
            max_len=32
        )
        self.screen = SCREEN_KB
        self._dirty = True

    def on_event(self, event) -> str:
        if self.screen == SCREEN_STATUS:
            return "exit"

        if event == "KEY3":
            return "exit"

        if event == "KEY1":
            self.keyboard.cycle_language()
            self._dirty = True
            return "stay"

        if event == "KEY2":
            self._apply(self.keyboard.text)
            return "stay"

        action, text = self.keyboard.handle_event(event)
        if action == "redraw":
            self._dirty = True
        elif action == "done":
            self._apply(text or "")

        return "stay"

    def _apply(self, name: str):
        name = name.strip()
        if not name:
            return
        ok, msg         = _set_hostname(name)
        self.status_ok  = ok
        self.status_msg = msg
        self.screen     = SCREEN_STATUS
        self._dirty     = True

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        if self.screen == SCREEN_KB:
            self.keyboard.draw()
            return

        # Status screen
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG)
        draw  = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        title = "Hostname"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        color = GREEN if self.status_ok else RED
        icon  = "OK" if self.status_ok else "ERR"
        iw, ih = self._ts(draw, icon, self.font_big)
        draw.text(((W - iw) // 2, TOP_BAR_H + 16),
                  icon, font=self.font_big, fill=color)

        y = TOP_BAR_H + 16 + ih + 10
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(draw, line, self.font_label)
            draw.text(((W - lw) // 2, y), line,
                      font=self.font_label, fill=WHITE)
            y += lh + 4

        hint = "Any key: back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 4),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
