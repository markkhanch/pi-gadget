"""
ui/main_menu.py
Main menu — 3×2 grid with icons and labels.
"""

from PIL import Image, ImageDraw


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_main_menu(hw, fonts, entries, selected_index):
    """
    Draws the main menu.

    hw             — HWDisplay
    fonts          — (font_big, font_small, font_label)
    entries        — list of entries from load_root_menu_entries()
    selected_index — index of the selected cell
    """
    font_big, font_small, font_label = fonts
    width, height = hw.W, hw.H

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # --- Header ---
    top_bar_h = 30
    title = "HOME"
    title_w, title_h = _text_size(draw, title, font_label)
    draw.text(((width - title_w) // 2, (top_bar_h - title_h) // 2),
              title, font=font_label, fill=(255, 255, 255))
    draw.line([(0, top_bar_h), (width, top_bar_h)], fill=(80, 80, 80), width=1)

    # --- 3×2 grid ---
    cols, rows = 3, 2
    grid_h  = height - top_bar_h
    col_w   = width // cols
    row_h   = grid_h // rows
    icon_size = 48

    for idx, entry in enumerate(entries):
        if idx >= cols * rows:
            break

        row = idx // cols
        col = idx % cols

        cell_x0 = col * col_w
        cell_y0 = top_bar_h + row * row_h
        cell_x1 = cell_x0 + col_w
        cell_y1 = cell_y0 + row_h
        cx = (cell_x0 + cell_x1) // 2
        cy = (cell_y0 + cell_y1) // 2

        # icon
        icon = entry["icon_image"].resize((icon_size, icon_size), Image.LANCZOS)
        label = entry["display_name"]
        label_w, label_h = _text_size(draw, label, font_label)

        total_h = icon_size + 4 + label_h
        icon_x  = cx - icon_size // 2
        icon_y  = cy - total_h // 2
        label_x = cx - label_w // 2
        label_y = icon_y + icon_size + 4

        image.paste(icon, (icon_x, icon_y), icon)
        draw.text((label_x, label_y), label, font=font_label, fill=(255, 255, 255))

        # selected cell border
        if idx == selected_index:
            m = 4
            draw.rectangle(
                [cell_x0 + m, cell_y0 + m, cell_x1 - m, cell_y1 - m],
                outline=(255, 255, 255), width=2
            )

    hw.show(image)