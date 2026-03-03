"""
apps/settings/screen_timeout/app.py
Screen timeout (backlight off) setting.

Controls:
  LEFT / RIGHT — change timeout value
  CENTER       — save to config.json
  KEY3         — exit
"""

import json
import os
from PIL import Image, ImageDraw

TOP_BAR_H = 24
BOT_BAR_H = 20
BG        = (0, 0, 0)
HDR_BG    = (20, 20, 20)
SEP       = (60, 60, 60)
WHITE     = (255, 255, 255)
GRAY      = (150, 150, 150)
HINT      = (100, 100, 100)
GREEN     = (70, 200, 70)
CYAN      = (0, 210, 255)

# Available timeout options: label → seconds (None = disabled)
OPTIONS = [
    ("Off",   None),
    ("30s",   30),
    ("1 min", 60),
    ("2 min", 120),
    ("5 min", 300),
    ("10 min",600),
]

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "config.json"
)


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def _current_index(cfg: dict) -> int:
    """Find OPTIONS index matching saved screen_timeout value."""
    val = cfg.get("screen_timeout", None)
    for i, (_, secs) in enumerate(OPTIONS):
        if secs == val:
            return i
    return 0  # Default to Off


class ScreenTimeoutApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self._idx   = 0
        self._saved = 0
        self._dirty = True

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def on_enter(self):
        cfg = _load_config()
        self._idx   = _current_index(cfg)
        self._saved = self._idx
        self._dirty = True

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"

        if event in ("LEFT", "DOWN"):
            self._idx = (self._idx - 1) % len(OPTIONS)
            self._dirty = True

        elif event in ("RIGHT", "UP"):
            self._idx = (self._idx + 1) % len(OPTIONS)
            self._dirty = True

        elif event == "CENTER":
            cfg = _load_config()
            _, secs = OPTIONS[self._idx]
            if secs is None:
                # Remove key to disable
                cfg.pop("screen_timeout", None)
            else:
                cfg["screen_timeout"] = secs
            _save_config(cfg)
            self._saved = self._idx
            self._dirty = True

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
        d.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HDR_BG)
        title = "Screen Timeout"
        tw, th = self._ts(d, title, self.font_label)
        d.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
               title, font=self.font_label, fill=WHITE)
        d.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        # Current value — big display
        label, _ = OPTIONS[self._idx]
        lw, lh = self._ts(d, label, self.font_big)
        d.text(((W - lw) // 2, TOP_BAR_H + 28),
               label, font=self.font_big, fill=CYAN)

        # Arrow hints
        cy = TOP_BAR_H + 28 + lh // 2
        d.text((10, cy - 8), "◄", font=self.font_label, fill=GRAY)
        d.text((W - 22, cy - 8), "►", font=self.font_label, fill=GRAY)

        # Option dots
        dot_y = TOP_BAR_H + 28 + lh + 16
        dot_spacing = (W - 32) // (len(OPTIONS) - 1)
        for i in range(len(OPTIONS)):
            x = 16 + i * dot_spacing
            col = WHITE if i == self._idx else (60, 60, 60)
            r = 4 if i == self._idx else 2
            d.ellipse([(x - r, dot_y - r), (x + r, dot_y + r)], fill=col)

        # Description
        desc_y = dot_y + 16
        if OPTIONS[self._idx][1] is None:
            desc = "Backlight stays on"
        else:
            desc = f"Screen off after {label}"
        dw, _ = self._ts(d, desc, self.font_label)
        d.text(((W - dw) // 2, desc_y), desc,
               font=self.font_label, fill=GRAY)

        # Saved indicator
        saved_y = desc_y + 22
        if self._idx == self._saved:
            sv, sc = "✓ Saved", GREEN
        else:
            sv, sc = "CENTER to save", HINT
        sw, _ = self._ts(d, sv, self.font_label)
        d.text(((W - sw) // 2, saved_y), sv,
               font=self.font_label, fill=sc)

        # Bottom hint
        hint = "◄► change   K3:back"
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 4),
               hint, font=self.font_label, fill=HINT)

        self.hw.show(img)
