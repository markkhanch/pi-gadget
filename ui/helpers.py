"""
ui/helpers.py
Shared drawing utilities used by multiple UI modules.
"""


def text_size(draw, text, font):
    """Return (width, height) of rendered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def trunc(draw, text, font, max_w):
    """Truncate text with '…' to fit within max_w pixels."""
    while text:
        w, _ = text_size(draw, text, font)
        if w <= max_w:
            return text
        text = text[:-2] + "…"
    return ""
