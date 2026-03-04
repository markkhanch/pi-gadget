"""
ui/list_view.py
Updated to show file size/type alongside name.
"""

from PIL import Image, ImageDraw
from ui.helpers import text_size as _text_size, trunc as _trunc

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEL_BG = (12,  25,  50)
SEP    = (25,  45,  75)
SEP_HI = (50,  90,  140)
WHITE  = (220, 235, 255)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
GREEN  = (50,  220, 120)
YELLOW = (255, 200, 50)
PURPLE = (160, 80,  255)
RED    = (255, 70,  70)
ORANGE = (255, 140, 30)

# Extension color coding
EXT_COLORS = {
    ".csv":  GREEN,
    ".gpx":  CYAN,
    ".html": ORANGE,
    ".ds":   YELLOW,
    ".txt":  WHITE,
    ".json": PURPLE,
    ".log":  DIM,
    ".jsonl":DIM,
    ".py":   CYAN,
    ".sh":   YELLOW,
}

ROW_H   = 30
ICON_S  = 20
TOP_H   = 26
BOT_H   = 18


def draw_list_view(hw, fonts, entries, selected_index, scroll,
                   dir_name: str, clipboard_name: str = ""):
    """
    Draw file/folder list.

    Each row shows:
      [icon]  [name]                    [size/count]
    Selected row has accent bar on left and highlight background.
    """
    font_big, font_small, font_label = fonts
    W, H = hw.W, hw.H

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── Header ────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
    draw.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
    name_t = _trunc(draw, dir_name, font_label, W - 80)
    tw, th = _text_size(draw, name_t, font_label)
    draw.text((10, (TOP_H - th) // 2), name_t,
              font=font_label, fill=WHITE)

    # Item count badge
    count_s = f"{len(entries)} items" if entries else "empty"
    cw, ch  = _text_size(draw, count_s, font_label)
    draw.text((W - cw - 4, (TOP_H - ch) // 2), count_s,
              font=font_label, fill=DIM)

    draw.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    # ── Entry rows ────────────────────────────────────────────
    max_rows = (H - TOP_H - BOT_H) // ROW_H
    y        = TOP_H

    if not entries:
        msg = "Empty folder"
        mw, mh = _text_size(draw, msg, font_label)
        draw.text(((W - mw) // 2, y + 30), msg,
                  font=font_label, fill=DIM)
    else:
        for idx in range(scroll, min(scroll + max_rows, len(entries))):
            entry  = entries[idx]
            is_sel = idx == selected_index
            y1     = y + ROW_H

            # Row background
            if is_sel:
                draw.rectangle([(0, y), (W, y1 - 1)], fill=SEL_BG)

            # Accent bar on left for selected
            entry_type = entry.get("type", "file")
            if is_sel:
                bar_color = {
                    "folder": CYAN,
                    "app":    YELLOW,
                    "file":   EXT_COLORS.get(entry.get("ext", ""), GREEN),
                }.get(entry_type, WHITE)
                draw.rectangle([(0, y), (3, y1 - 1)], fill=bar_color)

            # Icon
            icon = entry.get("icon_image")
            M    = 6
            if icon:
                try:
                    icon_r = icon.resize((ICON_S, ICON_S), 1)
                    img.paste(icon_r, (M + 2, y + (ROW_H - ICON_S) // 2), icon_r)
                except Exception:
                    pass

            # Name
            name_x  = M + ICON_S + 8
            name_col = WHITE if is_sel else (DIM if entry_type == "app" else WHITE)

            # Right side: size/count
            size_str = entry.get("size_str", "")
            sw, sh   = _text_size(draw, size_str, font_label) if size_str else (0, 0)
            name_max = W - name_x - sw - 8

            name_t = _trunc(draw, entry["display_name"], font_label, name_max)
            nw, nh = _text_size(draw, name_t, font_label)
            draw.text((name_x, y + (ROW_H - nh) // 2), name_t,
                      font=font_label, fill=name_col)

            if size_str:
                size_col = EXT_COLORS.get(entry.get("ext", ""), DIM)
                if entry_type == "folder":
                    size_col = CYAN
                elif entry_type == "app":
                    size_col = YELLOW
                draw.text((W - sw - 4, y + (ROW_H - sh) // 2), size_str,
                          font=font_label, fill=size_col if is_sel else DIM)

            # Separator
            draw.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)
            y += ROW_H

    # ── Scrollbar ─────────────────────────────────────────────
    if len(entries) > max_rows:
        sb_h   = H - TOP_H - BOT_H
        thumb  = max(6, sb_h * max_rows // len(entries))
        offset = sb_h * scroll // len(entries)
        draw.rectangle([(W - 3, TOP_H + offset),
                         (W - 1, TOP_H + offset + thumb)],
                        fill=CYAN)

    # ── Hint bar ──────────────────────────────────────────────
    draw.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)

    if clipboard_name:
        hint = f"📋{clipboard_name[:10]}  K2:menu  K3:back"
    else:
        hint = "CTR:open  K2:menu  K3:back"
    hw_, hh = _text_size(draw, hint, font_label)
    hint_t  = _trunc(draw, hint, font_label, W - 4)
    draw.text(((W - hw_) // 2, H - hh - 2), hint_t,
              font=font_label, fill=HINT)

    hw.show(img)
