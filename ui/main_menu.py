from PIL import Image, ImageDraw

def draw_main_menu(hw, fonts, categories, selected_index):
    font_big, font_small, font_label = fonts

    image = Image.new("RGB", (hw.W, hw.H), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 3 × 2 сетка
    cols = 3
    rows = 2

    cell_w = hw.W // cols
    cell_h = hw.H // rows

    for i, cat in enumerate(categories):
        row = i // cols
        col = i % cols

        x = col * cell_w
        y = row * cell_h

        # выбранная ячейка
        if i == selected_index:
            draw.rectangle([(x,y),(x+cell_w,y+cell_h)], outline=(100,255,100), width=2)

        # текст по центру
        name = cat["display_name"]
        w, h = draw.textsize(name, font=font_label)
        draw.text((x + (cell_w - w)//2, y + (cell_h - h)//2), name, font=font_label, fill=(255,255,255))

    hw.show(image)
