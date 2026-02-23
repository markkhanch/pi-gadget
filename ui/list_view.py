"""
ui/list_view.py
List of apps and folders inside the selected category.
"""

from PIL import Image, ImageDraw


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_list_view(hw, fonts, entries, selected_index, scroll_offset, folder_name):
    """
    Draws the folder contents list.

    hw             — HWDisplay
    fonts          — (font_big, font_small, font_label)
    entries        — list of entries from load_list_entries()
    selected_index — selected item
    scroll_offset  — first visible row
    folder_name    — current folder name (for the header)
    """
    font_big, font_small, font_label = fonts
    width, height = hw.W, hw.H

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # --- Header ---
    top_bar_h = 30
    hint = "KEY2: OPT"

    title_w, title_h = _text_size(draw, folder_name, font_label)
    hint_w,  hint_h  = _text_size(draw, hint, font_label)

    draw.text((4, (top_bar_h - title_h) // 2),
              folder_name, font=font_label, fill=(255, 255, 255))
    draw.text((width - hint_w - 4, (top_bar_h - hint_h) // 2),
              hint, font=font_label, fill=(180, 180, 180))
    draw.line([(0, top_bar_h), (width, top_bar_h)], fill=(80, 80, 80), width=1)

    # --- List ---
    row_h    = 30
    max_rows = (height - top_bar_h) // row_h
    icon_size = 20

    if not entries:
        msg = "Empty"
        msg_w, msg_h = _text_size(draw, msg, font_label)
        draw.text(((width - msg_w) // 2, top_bar_h + (height - top_bar_h - msg_h) // 2),
                  msg, font=font_label, fill=(180, 180, 180))
    else:
        start = scroll_offset
        end   = min(start + max_rows, len(entries))

        for row, idx in enumerate(range(start, end)):
            entry = entries[idx]
            y0 = top_bar_h + row * row_h
            y1 = y0 + row_h

            # highlight selected
            if idx == selected_index:
                draw.rectangle(
                    [(0, y0), (width - 1, y1 - 1)],
                    fill=(40, 40, 40), outline=(255, 255, 255), width=1
                )

            # icon
            icon = entry["icon_image"].resize((icon_size, icon_size), Image.LANCZOS)
            icon_x = 4
            icon_y = y0 + (row_h - icon_size) // 2
            image.paste(icon, (icon_x, icon_y), icon)

            # label
            label_x = icon_x + icon_size + 6
            label_y = y0 + (row_h - font_label.size) // 2
            draw.text((label_x, label_y),
                      entry["display_name"], font=font_label, fill=(255, 255, 255))

    hw.show(image)