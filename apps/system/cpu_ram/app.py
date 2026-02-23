"""
apps/system/cpu_ram/app.py
CPU & RAM монитор с графиком истории.
"""

from PIL import Image, ImageDraw


# ── Общие константы стиля ────────────────────────────────────
TOP_BAR_H   = 24   # высота шапки
BOT_BAR_H   = 20   # высота подсказки снизу
BG_COLOR    = (0, 0, 0)
HEADER_BG   = (20, 20, 20)
SEP_COLOR   = (60, 60, 60)
HINT_COLOR  = (100, 100, 100)
LABEL_COLOR = (200, 200, 200)
WHITE       = (255, 255, 255)


def _bar_color(pct: float):
    """Зелёный → жёлтый → красный в зависимости от нагрузки."""
    if pct < 60:
        return (70, 200, 70)
    elif pct < 85:
        return (220, 180, 50)
    else:
        return (220, 70, 70)


class CpuRamApp:
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

    def _draw_bar(self, draw, x, y, w, h, pct, color):
        """Рисует прямоугольный бар с рамкой."""
        draw.rectangle([x, y, x + w, y + h], outline=SEP_COLOR, width=1)
        fill_w = max(0, int((w - 2) * pct / 100.0))
        if fill_w > 0:
            draw.rectangle([x + 1, y + 1, x + fill_w, y + h - 1], fill=color)

    def _draw_graph(self, draw, x0, y0, x1, y1, vals, color):
        """Рисует линейный график в заданной области."""
        if len(vals) < 2:
            return
        gw = x1 - x0
        gh = y1 - y0
        vmin, vmax = min(vals), max(vals)
        if vmax == vmin:
            vmax = vmin + 1.0

        draw.rectangle([x0, y0, x1, y1], outline=SEP_COLOR, width=1)

        # горизонтальные направляющие на 25 / 50 / 75 %
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

        # подписи min/max справа
        for label, gy in [(f"{int(vmax)}%", y0), (f"{int(vmin)}%", y1)]:
            lw, lh = self._ts(draw, label, self.font_label)
            draw.text((x1 - lw - 2, gy + 1), label,
                      font=self.font_label, fill=(90, 90, 90))

    def draw(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG_COLOR)
        draw = ImageDraw.Draw(img)

        cpu      = self.monitor.cpu_percent
        mem_used = self.monitor.mem_used
        mem_tot  = self.monitor.mem_total
        mem_pct  = (mem_used / mem_tot * 100) if mem_tot > 0 else 0
        hist     = self.monitor.cpu_history

        # ── Шапка ───────────────────────────────────────────
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        title = "CPU / RAM"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP_COLOR, width=1)

        # ── Зона контента ────────────────────────────────────
        MARGIN   = 6
        BAR_H    = 14
        y        = TOP_BAR_H + 8

        # --- CPU ---
        cpu_color = _bar_color(cpu)
        cpu_label = f"CPU  {cpu:4.1f}%"
        lw, lh = self._ts(draw, cpu_label, self.font_label)
        draw.text((MARGIN, y), cpu_label, font=self.font_label, fill=LABEL_COLOR)
        y += lh + 3
        self._draw_bar(draw, MARGIN, y, W - MARGIN * 2, BAR_H, cpu, cpu_color)
        y += BAR_H + 10

        # --- RAM ---
        ram_color = _bar_color(mem_pct)
        ram_label = f"RAM  {mem_used}/{mem_tot} MiB  ({mem_pct:.0f}%)"
        lw, lh = self._ts(draw, ram_label, self.font_label)
        # если строка не влезает — укорачиваем
        if lw > W - MARGIN * 2:
            ram_label = f"RAM  {mem_used}/{mem_tot} MiB"
        draw.text((MARGIN, y), ram_label, font=self.font_label, fill=LABEL_COLOR)
        y += lh + 3
        self._draw_bar(draw, MARGIN, y, W - MARGIN * 2, BAR_H, mem_pct, ram_color)
        y += BAR_H + 8

        # --- График CPU ---
        bot_hint_y = H - BOT_BAR_H
        graph_top  = y
        graph_bot  = bot_hint_y - 4

        if graph_bot - graph_top >= 20:
            self._draw_graph(draw,
                             MARGIN, graph_top,
                             W - MARGIN, graph_bot,
                             hist, (100, 180, 255))

        # ── Подсказка снизу ──────────────────────────────────
        hint = "KEY3: back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
