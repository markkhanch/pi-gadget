from PIL import Image, ImageDraw

def _wrap_lines(lines, max_chars):
    """Wrap long lines into several lines with max_chars each."""
    wrapped = []
    for line in lines:
        line = line.rstrip()
        if not line:
            wrapped.append("")
            continue
        while len(line) > max_chars:
            wrapped.append(line[:max_chars])
            line = line[max_chars:]
        wrapped.append(line)
    return wrapped


def draw_console(hw, font_label, console_lines, console_scroll):
    """
    Рисует экран консоли с переносом строк и скроллом.
    
    hw          — HWDisplay (из core.hw)
    font_label  — шрифт для текста
    console_lines — список строк исходного вывода
    console_scroll — индекс первой видимой строки (по wrapped-строкам)
    """
    width, height = hw.W, hw.H
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    top_bar_h = 20

    # Header
    header = "OUTPUT"
    draw.text((4, 2), header, font=font_label, fill=(200, 200, 200))
    draw.line([(0, top_bar_h), (width, top_bar_h)], fill=(80, 80, 80), width=1)

    # Обёртка текста, чтобы строки не вылазили за экран по X
    max_chars = 24   # подбирается под ширину твоего дисплея
    wrapped = _wrap_lines(console_lines, max_chars)

    row_h = 14
    max_rows = (height - top_bar_h) // row_h

    if not wrapped:
        wrapped = ["(no output)"]

    # Нормализуем скролл (если вышел за границы)
    if console_scroll < 0:
        console_scroll = 0
    if console_scroll > max(0, len(wrapped) - max_rows):
        console_scroll = max(0, len(wrapped) - max_rows)

    start = console_scroll
    end = min(start + max_rows, len(wrapped))

    y = top_bar_h
    for line in wrapped[start:end]:
        draw.text((2, y), line, font=font_label, fill=(255, 255, 255))
        y += row_h

    hw.show(image)
