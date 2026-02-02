from PIL import ImageFont

def load_fonts():
    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60
        )
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20
        )
        font_label = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15
        )
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_label = ImageFont.load_default()
    return font_big, font_small, font_label
