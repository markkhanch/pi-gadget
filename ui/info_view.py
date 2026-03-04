"""
ui/info_view.py
File/folder info screen — shown when Info option is selected.
"""

from PIL import Image, ImageDraw
from ui.helpers import text_size as _text_size, trunc as _trunc

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEP    = (25,  45,  75)
SEP_HI = (50,  90,  140)
WHITE  = (220, 235, 255)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
YELLOW = (255, 200, 50)

TOP_H = 26
BOT_H = 18
ROW_H = 22


def draw_info_view(hw, fonts, info_lines: list, scroll: int, entry_name: str):
    """
    Draw info screen.

    info_lines — list of (label, value) tuples from get_entry_info()
    scroll     — how many lines scrolled down
    """
    font_big, font_small, font_label = fonts
    W, H = hw.W, hw.H

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
    draw.rectangle([(0, 0), (3, TOP_H)], fill=YELLOW)
    title = "INFO"
    tw, th = _text_size(draw, title, font_label)
    draw.text((10, (TOP_H - th) // 2), title,
              font=font_label, fill=YELLOW)
    name_t = _trunc(draw, entry_name, font_label, W - tw - 24)
    nw, nh = _text_size(draw, name_t, font_label)
    draw.text((W - nw - 4, (TOP_H - nh) // 2), name_t,
              font=font_label, fill=DIM)
    draw.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    # Info rows
    M        = 8
    max_rows = (H - TOP_H - BOT_H) // ROW_H
    y        = TOP_H + 4

    visible = info_lines[scroll: scroll + max_rows]
    for label, value in visible:
        lw, lh = _text_size(draw, label + ":", font_label)
        draw.text((M, y), label + ":", font=font_label, fill=DIM)
        val_t = _trunc(draw, str(value), font_label, W - lw - M * 3)
        vw, vh = _text_size(draw, val_t, font_label)
        draw.text((M + lw + 4, y), val_t, font=font_label, fill=WHITE)
        y += ROW_H
        draw.line([(M, y - 1), (W - M, y - 1)], fill=SEP, width=1)

    # Scrollbar
    if len(info_lines) > max_rows:
        sb_h   = H - TOP_H - BOT_H
        thumb  = max(6, sb_h * max_rows // len(info_lines))
        offset = sb_h * scroll // len(info_lines)
        draw.rectangle([(W - 3, TOP_H + offset),
                         (W - 1, TOP_H + offset + thumb)], fill=CYAN)

    # Hint
    draw.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
    hint = "UP/DN:scroll  K3:back"
    hw_, hh = _text_size(draw, hint, font_label)
    draw.text(((W - hw_) // 2, H - hh - 2), hint,
              font=font_label, fill=HINT)

    hw.show(img)
