"""
apps/system/disk/app.py
Disk usage with progress bar and donut chart.
"""

import shutil
from PIL import Image, ImageDraw
import math


TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG_COLOR   = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP_COLOR  = (60, 60, 60)
HINT_COLOR = (100, 100, 100)
WHITE      = (255, 255, 255)
LABEL_COLOR = (200, 200, 200)


def _disk_color(pct: float):
    if pct < 60:
        return (70, 200, 70)
    elif pct < 85:
        return (220, 180, 50)
    else:
        return (220, 70, 70)


class DiskApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.timer    = 0.0
        self.total_gb = 0.0
        self.used_gb  = 0.0
        self.free_gb  = 0.0
        self.used_pct = 0.0

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _read_disk(self):
        try:
            u = shutil.disk_usage("/")
            self.total_gb = u.total / 1024 ** 3
            self.used_gb  = u.used  / 1024 ** 3
            self.free_gb  = u.free  / 1024 ** 3
            self.used_pct = u.used * 100.0 / u.total if u.total > 0 else 0.0
        except Exception:
            self.total_gb = self.used_gb = self.free_gb = self.used_pct = 0.0

    def on_enter(self):
        self._read_disk()
        self.timer = 0.0

    def on_event(self, event):
        return "exit" if event == "KEY3" else "stay"

    def update(self, dt):
        self.timer += dt
        if self.timer >= 5.0:
            self._read_disk()
            self.timer = 0.0

    def _draw_donut(self, draw, cx, cy, r_out, r_in, pct, color):
        """
        Draw a simple donut chart.
        Filled sector = used, gray = free.
        """
        start_angle = -90          # 12 o'clock position
        used_angle  = 360 * pct / 100.0
        free_angle  = 360 - used_angle

        def arc_bbox(r):
            return [(cx - r, cy - r), (cx + r, cy + r)]

        # background (free) — dark gray
        draw.arc(arc_bbox(r_out), start_angle, start_angle + 360,
                 fill=(50, 50, 50), width=r_out - r_in)

        # used — colored arc
        if used_angle > 0:
            draw.arc(arc_bbox(r_out), start_angle, start_angle + used_angle,
                     fill=color, width=r_out - r_in)

        # percentage label in center
        pct_str = f"{pct:.0f}%"
        pw, ph  = self._ts(draw, pct_str, self.font_label)
        draw.text((cx - pw // 2, cy - ph // 2),
                  pct_str, font=self.font_label, fill=WHITE)

    def draw(self):
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG_COLOR)
        draw  = ImageDraw.Draw(img)
        color = _disk_color(self.used_pct)

        # ── Header ──────────────────────────────────────────
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        title = "Disk Usage"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP_COLOR, width=1)

        # ── Left column: numbers ────────────────────────────
        MARGIN   = 6
        col_split = W // 2 - 4
        y        = TOP_BAR_H + 10

        lines = [
            ("Used",  f"{self.used_gb:.1f} GiB"),
            ("Free",  f"{self.free_gb:.1f} GiB"),
            ("Total", f"{self.total_gb:.1f} GiB"),
        ]
        line_h = self.font_label.size + 6

        for key, val in lines:
            # key — gray, value — white
            kw, kh = self._ts(draw, key + ": ", self.font_label)
            draw.text((MARGIN, y), key + ": ",
                      font=self.font_label, fill=(150, 150, 150))
            draw.text((MARGIN + kw, y), val,
                      font=self.font_label, fill=WHITE)
            y += line_h

        # ── Right column: donut chart ───────────────────────
        bot_hint_y = H - BOT_BAR_H
        right_area_h = bot_hint_y - TOP_BAR_H
        cx = col_split + (W - col_split) // 2
        cy = TOP_BAR_H + right_area_h // 2

        r_out = min((W - col_split) // 2 - 6, right_area_h // 2 - 6)
        r_in  = max(r_out - 16, 8)

        self._draw_donut(draw, cx, cy, r_out, r_in, self.used_pct, color)

        # ── Full-width bar below numbers ────────────────────
        bar_top = y + 6
        bar_h   = 12
        bar_w   = col_split - MARGIN

        draw.rectangle([MARGIN, bar_top, MARGIN + bar_w, bar_top + bar_h],
                       outline=SEP_COLOR, width=1)
        fill_w = max(0, int((bar_w - 2) * self.used_pct / 100.0))
        if fill_w > 0:
            draw.rectangle([MARGIN + 1, bar_top + 1,
                            MARGIN + fill_w, bar_top + bar_h - 1],
                           fill=color)

        # tick marks at 25/50/75% below bar
        for frac in (0.25, 0.5, 0.75):
            x = MARGIN + int(bar_w * frac)
            draw.line([(x, bar_top + bar_h + 1), (x, bar_top + bar_h + 4)],
                      fill=(80, 80, 80), width=1)

        # ── Bottom hint ─────────────────────────────────────
        hint = "KEY3: back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
