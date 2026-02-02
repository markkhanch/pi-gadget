from PIL import Image, ImageDraw

def draw_options_menu(hw, fonts, options, selected_index, target_name):
    font_big, font_small, font_label = fonts

    image = Image.new("RGB", (hw.W, hw.H), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # имя объекта
    draw.text((4,2), target_name, font=font_label, fill=(200,200,200))
    draw.line([(0,18),(hw.W,18)], fill=(80,80,80), width=1)

    start_y = 20
    line_h = 20

    for i, opt in enumerate(options):
        y = start_y + i*line_h

        if i == selected_index:
            draw.rectangle([(0,y),(hw.W,y+line_h)], fill=(50,50,50))
            color = (255,255,255)
        else:
            color = (200,200,200)

        draw.text((4, y+2), opt, font=font_label, fill=color)

    hw.show(image)
