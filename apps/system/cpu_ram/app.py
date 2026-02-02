from PIL import Image, ImageDraw

class CpuRamApp:
    def __init__(self, hw, fonts, monitor):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.monitor = monitor  # общий монитор

    def _text_size(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        return w, h

    def on_enter(self):
        # ничего не сбрасываем — история хранится в monitor
        pass

    def on_event(self, event):
        if event == "KEY3":
            return "exit"
        return "stay"

    def update(self, dt):
        # обновление делает SystemMonitor, тут ничего не нужно
        pass

    def draw(self):
        W, H = self.hw.W, self.hw.H
        img = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        cpu = self.monitor.cpu_percent
        mem_used = self.monitor.mem_used
        mem_total = self.monitor.mem_total
        hist = self.monitor.cpu_history

        # ---------- заголовок ----------
        title = "CPU / RAM"
        tw, th = self._text_size(draw, title, self.font_label)
        draw.text(((W - tw)//2, 2), title, font=self.font_label, fill=(200,200,200))
        draw.line([(0,18),(W,18)], fill=(80,80,80), width=1)

        # ---------- CPU + бар ----------
        cpu_str = f"CPU: {cpu:4.1f}%"
        cw, ch = self._text_size(draw, cpu_str, self.font_label)
        draw.text((4, 22), cpu_str, font=self.font_label, fill=(255,255,255))

        bar_x = 4
        bar_y = 22 + ch + 4
        bar_w = W - 8
        bar_h = 10

        draw.rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h],
                       outline=(80,80,80), width=1)
        fill_w = int(bar_w * (cpu / 100.0))
        if fill_w > 0:
            draw.rectangle([bar_x+1, bar_y+1,
                            bar_x+fill_w-1, bar_y+bar_h-1],
                           fill=(80,200,80))

        # ---------- RAM + бар ----------
        ram_str = f"RAM: {mem_used} / {mem_total} MiB"
        rw, rh = self._text_size(draw, ram_str, self.font_label)
        draw.text((4, bar_y + bar_h + 6),
                  ram_str, font=self.font_label, fill=(255,255,255))

        rbar_y = bar_y + bar_h + 6 + rh + 4
        draw.rectangle([bar_x, rbar_y, bar_x+bar_w, rbar_y+bar_h],
                       outline=(80,80,80), width=1)
        if mem_total > 0:
            rfill_w = int(bar_w * (mem_used / mem_total))
        else:
            rfill_w = 0
        if rfill_w > 0:
            draw.rectangle([bar_x+1, rbar_y+1,
                            bar_x+rfill_w-1, rbar_y+bar_h-1],
                           fill=(80,80,200))

        # ---------- График CPU с минимальными/максимальными метками ----------
        hint = "KEY3: back"
        hw_hint, hh_hint = self._text_size(draw, hint, self.font_label)
        bottom_hint_y = H - hh_hint - 4

        graph_top = rbar_y + bar_h + 8
        graph_bottom = bottom_hint_y - 8

        if graph_bottom - graph_top >= 10 and len(hist) > 1:
            graph_h = graph_bottom - graph_top
            graph_x0 = 24         # оставим место для цифр слева
            graph_x1 = W - 4
            graph_w = graph_x1 - graph_x0

            # рамка
            draw.rectangle([graph_x0, graph_top, graph_x1, graph_bottom],
                           outline=(60,60,60), width=1)

            vals = hist
            vmin = min(vals)
            vmax = max(vals)
            if vmax == vmin:
                vmax = vmin + 1.0

            # подписи по оси Y (min / max)
            top_label = f"{int(vmax)}%"
            bot_label = f"{int(vmin)}%"
            tlw, tlh = self._text_size(draw, top_label, self.font_label)
            blw, blh = self._text_size(draw, bot_label, self.font_label)
            draw.text((2, graph_top - tlh//2),
                      top_label, font=self.font_label, fill=(150,150,150))
            draw.text((2, graph_bottom - blh//2),
                      bot_label, font=self.font_label, fill=(150,150,150))

            # сама линия
            n = len(vals)
            step_x = graph_w / max(1, n - 1)
            points = []
            for i, v in enumerate(vals):
                x = graph_x0 + i * step_x
                ratio = (v - vmin) / (vmax - vmin)
                y = graph_bottom - ratio * graph_h
                points.append((x, y))

            for i in range(1, len(points)):
                draw.line([points[i-1], points[i]],
                          fill=(120,200,250), width=1)

        # ---------- подсказка ----------
        draw.text(((W - hw_hint)//2, bottom_hint_y),
                  hint, font=self.font_label, fill=(150,150,150))

        self.hw.show(img)
