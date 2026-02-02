import shutil
from PIL import Image, ImageDraw

class DiskApp:
    def __init__(self, hw, fonts, monitor=None):
        # monitor не используем, но принимаем для совместимости
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.last_update = 0.0
        self.total_gb = 0.0
        self.used_gb = 0.0
        self.free_gb = 0.0
        self.used_pct = 0.0

    def _text_size(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        return w, h

    def _read_disk(self):
        """Читаем использование корневого раздела /."""
        try:
            usage = shutil.disk_usage("/")
            total = usage.total
            used = usage.used
            free = usage.free

            self.total_gb = total / (1024**3)
            self.used_gb = used / (1024**3)
            self.free_gb = free / (1024**3)
            if total > 0:
                self.used_pct = used * 100.0 / total
            else:
                self.used_pct = 0.0
        except Exception:
            self.total_gb = 0.0
            self.used_gb = 0.0
            self.free_gb = 0.0
            self.used_pct = 0.0

    def on_enter(self):
        self._read_disk()

    def on_event(self, event):
        if event == "KEY3":
            return "exit"
        return "stay"

    def update(self, dt):
        # Можно обновлять, например, раз в 5 секунд
        self.last_update += dt
        if self.last_update >= 5.0:
            self._read_disk()
            self.last_update = 0.0

    def draw(self):
        W, H = self.hw.W, self.hw.H
        img = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ---------- Заголовок ----------
        title = "Disk usage"
        tw, th = self._text_size(draw, title, self.font_label)
        draw.text(((W - tw)//2, 2),
                  title, font=self.font_label, fill=(200,200,200))
        draw.line([(0,18),(W,18)], fill=(80,80,80), width=1)

        # ---------- Основные цифры ----------
        # Строка: "Used: 12.3 / 28.6 GiB"
        used_str = f"Used: {self.used_gb:4.1f} / {self.total_gb:4.1f} GiB"
        uw, uh = self._text_size(draw, used_str, self.font_label)
        y0 = 22
        draw.text(((W - uw)//2, y0),
                  used_str, font=self.font_label, fill=(255,255,255))

        # Строка: "Free: 16.3 GiB (57%)"
        free_str = f"Free: {self.free_gb:4.1f} GiB ({100.0 - self.used_pct:3.0f}%)"
        fw, fh = self._text_size(draw, free_str, self.font_label)
        y1 = y0 + uh + 2
        draw.text(((W - fw)//2, y1),
                  free_str, font=self.font_label, fill=(200,200,200))

        # ---------- Большой бар ----------
        bar_x = 10
        bar_y = y1 + fh + 10
        bar_w = W - 2*bar_x
        bar_h = 20

        # рамка
        draw.rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h],
                       outline=(80,80,80), width=1)

        # used (красный/жёлтый/зелёный в зависимости от заполнения)
        pct = self.used_pct
        if pct < 60:
            fill_color = (80, 200, 80)     # зелёный
        elif pct < 85:
            fill_color = (220, 180, 60)   # жёлтый
        else:
            fill_color = (220, 80, 80)    # красный

        fill_w = int(bar_w * (pct / 100.0))
        if fill_w > 0:
            draw.rectangle([bar_x+1, bar_y+1,
                            bar_x+fill_w-1, bar_y+bar_h-1],
                           fill=fill_color)

        # подпись процента поверх бара
        pct_str = f"{pct:4.1f}%"
        pw, ph = self._text_size(draw, pct_str, self.font_label)
        draw.text((bar_x + (bar_w - pw)//2, bar_y + (bar_h - ph)//2),
                  pct_str, font=self.font_label, fill=(0,0,0))

        # ---------- Мелкие деления по бару (25, 50, 75%) ----------
        for frac in (0.25, 0.5, 0.75):
            x = bar_x + int(bar_w * frac)
            draw.line([(x, bar_y), (x, bar_y + bar_h)],
                      fill=(60,60,60), width=1)

        # ---------- Подсказка ----------
        hint = "KEY3: back"
        hw_hint, hh_hint = self._text_size(draw, hint, self.font_label)
        bottom_hint_y = H - hh_hint - 4
        draw.text(((W - hw_hint)//2, bottom_hint_y),
                  hint, font=self.font_label, fill=(150,150,150))

        self.hw.show(img)
