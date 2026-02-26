"""
apps/system/temp/app.py
CPU temperature monitor with color indicator and history graph.
"""

from PIL import Image, ImageDraw, ImageFont


TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG_COLOR   = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP_COLOR  = (60, 60, 60)
HINT_COLOR = (100, 100, 100)
WHITE      = (255, 255, 255)

FONT_PATH  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _temp_color(temp: float):
    if temp < 50:
        return (70, 200, 70)
    elif temp < 70:
        return (220, 180, 50)
    else:
        return (220, 70, 70)


def _temp_label(temp: float) -> str:
    if temp < 50:
        return "Cool"
    elif temp < 70:
        return "Warm"
    else:
        return "Hot!"


def _fit_font(text: str, max_w: int, max_h: int, fallback) -> ImageFont.FreeTypeFont:
    """
    Find the largest font size that fits text within max_w x max_h.
    Tries sizes from 48 down to 12.
    """
    for size in range(48, 11, -1):
        try:
            f = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return fallback
        # use font.getbbox directly — faster
        bbox = f.getbbox(text)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            return f
    return fallback


class TempApp:
    def __init__(self, hw, fonts, monitor):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.monitor = monitor

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def on_enter(self):
        pass

    def on_event(self, event):
        return "exit" if event == "KEY3" else "stay"

    def update(self, dt):
        pass

    def _draw_graph(self, draw, x0, y0, x1, y1, vals, color):
        if len(vals) < 2:
            return
        gw = x1 - x0
        gh = y1 - y0
        vmin, vmax = min(vals), max(vals)
        if vmax == vmin:
            vmax = vmin + 1.0

        draw.rectangle([x0, y0, x1, y1], outline=SEP_COLOR, width=1)

        for frac in (0.25, 0.5, 0.75):
            gy = int(y1 - gh * frac)
            draw.line([(x0 + 1, gy), (x1 - 1, gy)], fill=(35, 35, 35), width=1)

        step = gw / max(1, len(vals) - 1)
        pts  = []
        for i, v in enumerate(vals):
            px = x0 + i * step
            py = y1 - (v - vmin) / (vmax - vmin) * gh
            pts.append((px, py))

        for i in range(1, len(pts)):
            draw.line([pts[i - 1], pts[i]], fill=color, width=1)

        for lbl, gy in [(f"{int(vmax)}°", y0), (f"{int(vmin)}°", y1)]:
            lw, lh = self._ts(draw, lbl, self.font_label)
            draw.text((x1 - lw - 2, gy + 1), lbl,
                      font=self.font_label, fill=(90, 90, 90))

    def draw(self):
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG_COLOR)
        draw  = ImageDraw.Draw(img)

        temp  = self.monitor.temp_c
        hist  = self.monitor.temp_history
        color = _temp_color(temp)
        label = _temp_label(temp)

        # ── Header ──────────────────────────────────────────
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)

        title = "Temperature"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)

        # badge on the right
        bp  = 4
        bw, bh = self._ts(draw, label, self.font_label)
        bx  = W - bw - bp * 2 - 4
        by  = (TOP_BAR_H - bh) // 2 - bp // 2
        draw.rounded_rectangle(
            [(bx - bp, by), (bx + bw + bp, by + bh + bp)],
            radius=4, fill=color
        )
        draw.text((bx, by + bp // 2), label,
                  font=self.font_label, fill=(0, 0, 0))

        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP_COLOR, width=1)

        # ── Temperature number block ──────────────────────────
        MARGIN   = 8
        NUM_PAD  = 8                          # inner padding
        # area available for the number block
        num_area_w = W - MARGIN * 2
        num_area_h = 70                       # 70px reserved for number

        temp_str  = f"{temp:.1f}°C"

        # pick font size — text must fit inside block minus padding
        font_temp = _fit_font(
            temp_str,
            num_area_w - NUM_PAD * 2,
            num_area_h - NUM_PAD * 2,
            self.font_small
        )

        tw2, th2 = self._ts(draw, temp_str, font_temp)

        # draw block within num_area, center text inside
        block_x0 = MARGIN
        block_y0 = TOP_BAR_H + 8
        block_x1 = W - MARGIN
        block_y1 = block_y0 + num_area_h

        bg = tuple(max(0, c - 160) for c in color)
        draw.rounded_rectangle(
            [(block_x0, block_y0), (block_x1, block_y1)],
            radius=8, fill=bg, outline=color, width=2
        )

        # text exactly centered in block
        tx = block_x0 + (num_area_w - tw2) // 2
        ty = block_y0 + (num_area_h - th2) // 2
        draw.text((tx, ty), temp_str, font=font_temp, fill=WHITE)

        # ── Graph ────────────────────────────────────────────
        graph_top  = block_y1 + 8
        bot_hint_y = H - BOT_BAR_H
        graph_bot  = bot_hint_y - 4

        if graph_bot - graph_top >= 20:
            self._draw_graph(draw,
                             MARGIN, graph_top,
                             W - MARGIN, graph_bot,
                             hist, color)

        # ── Hint ─────────────────────────────────────────────
        hint = "KEY3: back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
