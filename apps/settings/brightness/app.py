"""
apps/settings/brightness/app.py
Screen brightness control.

Controls:
  LEFT / RIGHT  — decrease / increase brightness by 5%
  UP            — increase brightness by 5%
  DOWN          — decrease brightness by 5%
  CENTER        — save to config.json
  KEY3          — exit (keeps current brightness)
"""

import json
import os
from PIL import Image, ImageDraw

TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
HINT_COLOR = (100, 100, 100)
GRAY       = (150, 150, 150)

STEP       = 5    # percent per button press
MIN_BL     = 10   # minimum brightness %
MAX_BL     = 100  # maximum brightness %

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "config.json"
)


def _load_brightness() -> int:
    """Load saved brightness from config.json, default 80."""
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        return int(cfg.get("brightness", 80))
    except Exception:
        return 80


def _save_brightness(value: int):
    """Save brightness to config.json."""
    try:
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
        cfg["brightness"] = value
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def _bar_color(pct: int):
    if pct < 30:
        return (80, 80, 200)
    elif pct < 70:
        return (70, 200, 70)
    else:
        return (220, 180, 50)


class BrightnessApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.value  = 80
        self.saved  = 80
        self._dirty = True

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def on_enter(self):
        self.value  = _load_brightness()
        self.saved  = self.value
        self._dirty = True
        self.hw.backlight(self.value)

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"

        if event in ("RIGHT", "UP"):
            self.value = min(MAX_BL, self.value + STEP)
            self.hw.backlight(self.value)
            self._dirty = True

        elif event in ("LEFT", "DOWN"):
            self.value = max(MIN_BL, self.value - STEP)
            self.hw.backlight(self.value)
            self._dirty = True

        elif event == "CENTER":
            # Save to config
            _save_brightness(self.value)
            self.saved  = self.value
            self._dirty = True

        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG)
        draw  = ImageDraw.Draw(img)

        # Header
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        title = "Brightness"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        # Big percentage number in center
        pct_str = f"{self.value}%"
        pw, ph  = self._ts(draw, pct_str, self.font_big)
        draw.text(((W - pw) // 2, TOP_BAR_H + 20),
                  pct_str, font=self.font_big, fill=WHITE)

        # Bar
        MARGIN = 16
        bar_y  = TOP_BAR_H + 20 + ph + 16
        bar_h  = 18
        bar_w  = W - MARGIN * 2
        color  = _bar_color(self.value)

        draw.rectangle([MARGIN, bar_y, MARGIN + bar_w, bar_y + bar_h],
                       outline=SEP, width=1)
        fill_w = max(0, int((bar_w - 2) * self.value / MAX_BL))
        if fill_w > 0:
            draw.rectangle([MARGIN + 1, bar_y + 1,
                            MARGIN + fill_w, bar_y + bar_h - 1],
                           fill=color)

        # Tick marks at 25/50/75%
        for frac in (0.25, 0.5, 0.75):
            x = MARGIN + int(bar_w * frac)
            draw.line([(x, bar_y + bar_h + 1), (x, bar_y + bar_h + 5)],
                      fill=(80, 80, 80), width=1)

        # MIN / MAX labels under bar
        min_lbl = f"{MIN_BL}%"
        max_lbl = f"{MAX_BL}%"
        mlw, mlh = self._ts(draw, min_lbl, self.font_label)
        draw.text((MARGIN, bar_y + bar_h + 7), min_lbl,
                  font=self.font_label, fill=GRAY)
        mxw, _ = self._ts(draw, max_lbl, self.font_label)
        draw.text((MARGIN + bar_w - mxw, bar_y + bar_h + 7), max_lbl,
                  font=self.font_label, fill=GRAY)

        # Saved indicator
        saved_y = bar_y + bar_h + 7 + mlh + 10
        if self.value == self.saved:
            saved_str = "✓ Saved"
            sc = (70, 200, 70)
        else:
            saved_str = "CENTER to save"
            sc = HINT_COLOR
        sw, sh = self._ts(draw, saved_str, self.font_label)
        draw.text(((W - sw) // 2, saved_y), saved_str,
                  font=self.font_label, fill=sc)

        # Bottom hint
        hint = "◄► adjust   K3:back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
