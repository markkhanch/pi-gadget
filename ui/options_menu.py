"""
ui/options_menu.py
Context options menu (create folder, rename, delete, back).
"""

from PIL import Image, ImageDraw


OPTIONS_ITEMS = [
    "Create folder",
    "Rename",
    "Delete",
    "Back",
]


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_options_menu(hw, fonts, selected_index):
    """
    Draws the options menu.

    hw             — HWDisplay
    fonts          — (font_big, font_small, font_label)
    selected_index — selected item
    """
    font_big, font_small, font_label = fonts
    width, height = hw.W, hw.H

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # --- Header ---
    title = "OPTIONS"
    title_w, title_h = _text_size(draw, title, font_label)
    draw.text(((width - title_w) // 2, 4), title, font=font_label, fill=(255, 255, 255))

    # --- Menu items ---
    top   = 4 + title_h + 4
    row_h = 24

    for idx, txt in enumerate(OPTIONS_ITEMS):
        y0 = top + idx * row_h
        y1 = y0 + row_h

        if idx == selected_index:
            draw.rectangle(
                [(4, y0), (width - 4, y1 - 2)],
                fill=(40, 40, 40), outline=(255, 255, 255), width=1
            )

        txt_w, txt_h = _text_size(draw, txt, font_label)
        draw.text(((width - txt_w) // 2, y0 + (row_h - txt_h) // 2),
                  txt, font=font_label, fill=(255, 255, 255))

    # --- Bottom hint ---
    hint = "UP/DOWN, CENTER=OK, KEY3=BACK"
    hint_w, hint_h = _text_size(draw, hint, font_label)
    draw.text(((width - hint_w) // 2, height - hint_h - 4),
              hint, font=font_label, fill=(180, 180, 180))

    hw.show(image)