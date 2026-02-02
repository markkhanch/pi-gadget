from PIL import Image, ImageDraw
import datetime

def draw_screensaver(hw, fonts):
    font_big, font_small, font_label = fonts

    image = Image.new("RGB", (hw.W, hw.H), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")

    # время по центру
    w, h = draw.textsize(time_str, font=font_big)
    draw.text(((hw.W - w) // 2, (hw.H - h) // 2), time_str, font=font_big, fill=(255,255,255))

    # дата ниже
    w2, h2 = draw.textsize(date_str, font=font_small)
    draw.text(((hw.W - w2) // 2, (hw.H - h) // 2 + h), date_str, font=font_small, fill=(200,200,200))

    hw.show(image)
