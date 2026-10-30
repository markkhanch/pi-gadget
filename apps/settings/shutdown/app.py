"""
apps/settings/shutdown/app.py
Shutdown — ask for confirmation, stop background tasks cleanly, then power off.

Referenced by menu_fs/06_settings/Shutdown.app (module "settings.shutdown").
"""

import subprocess

from PIL import Image, ImageDraw

from core.background import bgm

BG    = (0, 0, 0)
WHITE = (255, 255, 255)
RED   = (220, 70, 70)
HINT  = (100, 100, 100)

TITLE  = "Shutdown"
PROMPT = "Power off the device?"
BUSY   = "Shutting down..."
# argv list (no shell); systemctl is granted NOPASSWD by install.sh.
ACTION = ["sudo", "systemctl", "poweroff"]


class ShutdownApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self._busy = False

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def on_enter(self):
        self._busy = False

    def on_event(self, event):
        if self._busy:
            return "stay"
        if event == "CENTER":
            self._busy = True
            self.draw()                 # paint "Shutting down..." before we block
            try:
                bgm.stop_all()
            except Exception:
                pass
            try:
                self.hw.clear()
            except Exception:
                pass
            try:
                subprocess.run(ACTION, timeout=15)
            except Exception:
                pass
            return "stay"
        if event == "KEY3":
            return "exit"
        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        tw, th = self._ts(draw, TITLE, self.font_small)
        draw.text(((W - tw) // 2, 16), TITLE, font=self.font_small, fill=RED)

        if self._busy:
            mw, mh = self._ts(draw, BUSY, self.font_small)
            draw.text(((W - mw) // 2, (H - mh) // 2), BUSY,
                      font=self.font_small, fill=WHITE)
        else:
            pw, ph = self._ts(draw, PROMPT, self.font_label)
            draw.text(((W - pw) // 2, (H - ph) // 2 - 10), PROMPT,
                      font=self.font_label, fill=WHITE)
            hint = "CENTER: confirm   KEY3: cancel"
            hw2, hh2 = self._ts(draw, hint, self.font_label)
            draw.text(((W - hw2) // 2, H - hh2 - 6), hint,
                      font=self.font_label, fill=HINT)

        self.hw.show(img)
