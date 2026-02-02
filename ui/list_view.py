from PIL import Image, ImageDraw

def draw_list_view(hw, fonts, entries, selected_index, path_stack):
    font_big, font_small, font_label = fonts

    image = Image.new("RGB", (hw.W, hw.H), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # заголовок — текущая папка
    header = path_stack[-1]["display_name"] if path_stack else "Root"
    w,h = draw.textsize(header, font=font_label)
    draw.text((4, 2), header, font=font_label, fill=(200,200,200))

    draw.line([(0,18),(hw.W,18)], fill=(80,80,80), width=1)

    # варианты
    start_y = 20
    line_h = 18
    visible_lines = (hw.H - start_y) // line_h

    for i, item in enumerate(entries[:visible_lines]):
        y = start_y + i * line_h

        if i == selected_index:
            draw.rectangle([(0,y),(hw.W,y+line_h)], fill=(50,50,50))
            color = (255,255,255)
        else:
            color = (200,200,200)

        draw.text((4, y+2), item["display_name"], font=font_label, fill=color)

    hw.show(image)
