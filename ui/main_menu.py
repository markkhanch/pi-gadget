"""
ui/main_menu.py
Main menu — 3×2 icon grid.
Reused for sub-grid views (e.g. Hacking) via optional title parameter.
"""

from PIL import Image, ImageDraw


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_main_menu(hw, fonts, entries, selected_index, title: str = "HOME"):
    """
    Draw the main icon grid.

    hw             — HWDisplay
    fonts          — (font_big, font_small, font_label)
    entries        — list of entry dicts from load_root_menu_entries() or load_grid_entries()
    selected_index — index of selected cell
    title          — header title (default "HOME", pass section name for sub-grids)
    """
    font_big, font_small, font_label = fonts
    width, height = hw.W, hw.H

    image = Image.new("RGB", (width, height), (4, 8, 16))
    draw  = ImageDraw.Draw(image)

    # ── Header ────────────────────────────────────────────────
    top_bar_h = 30
    draw.rectangle([(0, 0), (width, top_bar_h)], fill=(8, 14, 28))
    draw.rectangle([(0, 0), (3, top_bar_h)], fill=(0, 210, 255))

    tw, th = _text_size(draw, title, font_label)
    draw.text(((width - tw) // 2, (top_bar_h - th) // 2),
              title, font=font_label, fill=(220, 235, 255))

    draw.line([(0, top_bar_h), (width, top_bar_h)],
              fill=(50, 90, 140), width=1)

    # ── Icon grid 3×2 ─────────────────────────────────────────
    cols, rows = 3, 2
    grid_h    = height - top_bar_h
    col_w     = width // cols
    row_h     = grid_h // rows
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

        icon  = entry["icon_image"].resize((icon_size, icon_size), Image.LANCZOS)
        label = entry["display_name"]
        lw, lh = _text_size(draw, label, font_label)

        total_h = icon_size + 4 + lh
        icon_x  = cx - icon_size // 2
        icon_y  = cy - total_h // 2
        label_x = cx - lw // 2
        label_y = icon_y + icon_size + 4

        image.paste(icon, (icon_x, icon_y), icon)
        draw.text((label_x, label_y), label,
                  font=font_label, fill=(220, 235, 255))

        # Selection border
        if idx == selected_index:
            m = 4
            draw.rectangle(
                [cell_x0 + m, cell_y0 + m, cell_x1 - m, cell_y1 - m],
                outline=(0, 210, 255), width=2
            )

        # Cell separator lines
        if col < cols - 1:
            draw.line([(cell_x1, cell_y0 + 8), (cell_x1, cell_y1 - 8)],
                      fill=(25, 45, 75), width=1)
        if row < rows - 1:
            draw.line([(cell_x0 + 8, cell_y1), (cell_x1 - 8, cell_y1)],
                      fill=(25, 45, 75), width=1)

    hw.show(image)
