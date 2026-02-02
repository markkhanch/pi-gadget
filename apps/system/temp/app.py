from PIL import Image, ImageDraw

class TempApp:
    def __init__(self, hw, fonts, monitor):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.monitor = monitor

    def _text_size(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        return w, h

    def on_enter(self):
        # историю не трогаем
        pass

    def on_event(self, event):
        if event == "KEY3":
            return "exit"
        return "stay"

    def update(self, dt):
        # всё делает SystemMonitor
        pass

    def draw(self):
        W, H = self.hw.W, self.hw.H
        img = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        temp = self.monitor.temp_c
        hist = self.monitor.temp_history

        # статус по температуре
        if temp < 50:
            status = "Cool"
            fill_color = (80, 200, 80)
        elif temp < 70:
            status = "Warm"
            fill_color = (220, 180, 60)
        else:
            status = "Hot!"
            fill_color = (220, 80, 80)

        # ---------- заголовок ----------
        title = "Temperature"
        tw, th = self._text_size(draw, title, self.font_label)
        draw.text(((W - tw)//2, 2), title, font=self.font_label, fill=(200,200,200))
        draw.line([(0,18),(W,18)], fill=(80,80,80), width=1)

        # ---------- крупное значение ----------
        temp_str = f"{temp:4.1f}°C"
        t_w, t_h = self._text_size(draw, temp_str, self.font_big)
        temp_y = 22
        draw.text(((W - t_w)//2, temp_y),
                  temp_str, font=self.font_big, fill=(255,255,255))

        # ---------- статус ----------
        s_w, s_h = self._text_size(draw, status, self.font_label)
        status_y = temp_y + t_h + 4
        draw.text(((W - s_w)//2, status_y),
                  status, font=self.font_label, fill=(180,180,180))

        # ---------- подсказка снизу ----------
        hint = "KEY3: back"
        hw_hint, hh_hint = self._text_size(draw, hint, self.font_label)
        bottom_hint_y = H - hh_hint - 4
        draw.text(((W - hw_hint)//2, bottom_hint_y),
                  hint, font=self.font_label, fill=(150,150,150))

        # ---------- область под градусник и график ----------
        top_area = status_y + s_h + 8
        bottom_area = bottom_hint_y - 8
        if bottom_area <= top_area:
            self.hw.show(img)
            return

        # левый блок (градусник)
        gauge_x0 = 4
        gauge_x1 = W//2 - 4
        gauge_w = gauge_x1 - gauge_x0

        bar_w = min(20, gauge_w - 8)
        bar_x = gauge_x0 + (gauge_w - bar_w)//2
        bar_y = top_area
        bar_h = bottom_area - top_area

        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                       outline=(80,80,80), width=1)

        ratio = max(0.0, min(1.0, temp / 90.0))
        fill_h = int(bar_h * ratio)
        if fill_h > 0:
            draw.rectangle(
                [bar_x + 2,
                 bar_y + bar_h - fill_h + 2,
                 bar_x + bar_w - 2,
                 bar_y + bar_h - 2],
                fill=fill_color
            )

        # правый блок (график температуры)
        if len(hist) > 1:
            graph_x0 = W//2 + 4
            graph_x1 = W - 4
            graph_y0 = top_area
            graph_y1 = bottom_area

            graph_w = graph_x1 - graph_x0
            graph_h = graph_y1 - graph_y0

            draw.rectangle([graph_x0, graph_y0, graph_x1, graph_y1],
                           outline=(60,60,60), width=1)

            vals = hist
            vmin = min(vals)
            vmax = max(vals)
            if vmax == vmin:
                vmax = vmin + 1.0

            # подписи min/max в градусах
            top_label = f"{int(vmax)}°"
            bot_label = f"{int(vmin)}°"
            tlw, tlh = self._text_size(draw, top_label, self.font_label)
            blw, blh = self._text_size(draw, bot_label, self.font_label)
            draw.text((graph_x0 - tlw - 2, graph_y0 - tlh//2),
                      top_label, font=self.font_label, fill=(150,150,150))
            draw.text((graph_x0 - blw - 2, graph_y1 - blh//2),
                      bot_label, font=self.font_label, fill=(150,150,150))

            n = len(vals)
            step_x = graph_w / max(1, n - 1)
            points = []
            for i, v in enumerate(vals):
                x = graph_x0 + i * step_x
                r = (v - vmin) / (vmax - vmin)
                y = graph_y1 - r * graph_h
                points.append((x, y))
            for i in range(1, len(points)):
                draw.line([points[i-1], points[i]],
                          fill=(120,200,250), width=1)

        self.hw.show(img)
