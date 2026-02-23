"""
apps/settings/display_timeout/app.py
Display timeout (screensaver) setting.
Saves chosen timeout to a config file read by main.py on startup.

Controls:
  UP/DOWN — select timeout option
  CENTER  — apply
  KEY3    — exit
"""

import json
import os
from PIL import Image, ImageDraw

TOP_BAR_H  = 24
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
GRAY       = (150, 150, 150)
HINT_COLOR = (100, 100, 100)
GREEN      = (70, 200, 70)
BLUE       = (80, 160, 255)
SEL_BG     = (40, 40, 40)
ROW_H      = 34

# Config file path — main.py reads this on startup
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.json")
CONFIG_PATH = os.path.abspath(CONFIG_PATH)

# Timeout options: (label, seconds)
OPTIONS = [
    ("30 seconds",  30),
    ("1 minute",    60),
    ("2 minutes",   120),
    ("5 minutes",   300),
    ("10 minutes",  600),
    ("Never",       999999),
]


def _load_timeout() -> int:
    """Read current timeout from config.json. Returns seconds."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f).get("idle_timeout", 60)
    except Exception:
        return 60


def _save_timeout(seconds: int):
    """Write timeout to config.json. Creates file if missing."""
    cfg = {}
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        pass
    cfg["idle_timeout"] = seconds
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


class DisplayTimeoutApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.selected   = 0
        self.current    = 60
        self.saved_msg  = ""
        self._dirty     = True

    def on_enter(self):
        self.current = _load_timeout()
        # Pre-select the current option
        for i, (_, secs) in enumerate(OPTIONS):
            if secs == self.current:
                self.selected = i
                break
        self.saved_msg = ""
        self._dirty    = True

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"
        if event == "UP" and self.selected > 0:
            self.selected -= 1
            self.saved_msg = ""
            self._dirty    = True
        elif event == "DOWN" and self.selected < len(OPTIONS) - 1:
            self.selected += 1
            self.saved_msg = ""
            self._dirty    = True
        elif event == "CENTER":
            _, secs = OPTIONS[self.selected]
            _save_timeout(secs)
            self.current   = secs
            self.saved_msg = "Saved! Takes effect\nafter restart."
            self._dirty    = True
        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False
        self._draw_main()

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _draw_main(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(d, "Display Timeout", self.font_label)
        d.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
               "Display Timeout", font=self.font_label, fill=WHITE)
        d.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        # Options list
        y = TOP_BAR_H + 6
        for i, (label, secs) in enumerate(OPTIONS):
            y0  = y + i * ROW_H
            y1  = y0 + ROW_H - 4
            sel = i == self.selected
            cur = secs == self.current

            d.rounded_rectangle([(6, y0), (W - 6, y1)], radius=6,
                                 fill=SEL_BG if sel else (15, 15, 15),
                                 outline=BLUE if sel else SEP, width=2 if sel else 1)

            lw, lh = self._ts(d, label, self.font_label)
            d.text((16, y0 + (ROW_H - 4 - lh) // 2),
                   label, font=self.font_label,
                   fill=WHITE if sel else GRAY)

            # Checkmark for active option
            if cur:
                cw, ch = self._ts(d, "✓", self.font_label)
                d.text((W - cw - 12, y0 + (ROW_H - 4 - ch) // 2),
                       "✓", font=self.font_label, fill=GREEN)

        # Saved message
        if self.saved_msg:
            sy = TOP_BAR_H + 6 + len(OPTIONS) * ROW_H + 8
            for line in self.saved_msg.split("\n"):
                lw, lh = self._ts(d, line, self.font_label)
                d.text(((W - lw) // 2, sy), line, font=self.font_label, fill=GREEN)
                sy += lh + 2

        hint = "CTR:apply  K3:exit"
        hw, hh = self._ts(d, hint, self.font_label)
        d.text(((W - hw) // 2, H - hh - 2), hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
