"""
ui/screensaver.py
Screensaver: clock, date, Wi-Fi/Ethernet and Bluetooth icons.
"""

import os
from PIL import Image, ImageDraw
from datetime import datetime
from core.background import bgm


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _get_clock_fmt() -> str:
    """Read 12/24h preference saved by the Date & Time settings app."""
    fmt_file = os.path.join(
        os.path.dirname(__file__), "..",
        "apps", "settings", "datetime", "clockfmt.txt"
    )
    try:
        return open(os.path.abspath(fmt_file)).read().strip()
    except Exception:
        return "24"


def draw_screensaver(hw, fonts, wifi_icons, bt_icons, status, eth_icon=None):
    """
    Draws the screensaver.

    hw         — HWDisplay
    fonts      — (font_big, font_small, font_label)
    wifi_icons — {"on": Image, "off": Image}
    bt_icons   — {"on": Image, "off": Image}
    status     — core.status module
    eth_icon   — Ethernet icon Image (or None if no file)
    """
    font_big, font_small, font_label = fonts
    width, height = hw.W, hw.H

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw  = ImageDraw.Draw(image)

    # --- Status bar ---
    bar_h = 30
    draw.line([(0, bar_h), (width, bar_h)], fill=(80, 80, 80), width=1)

    # First slot — Ethernet replaces Wi-Fi
    if eth_icon is not None and status.is_ethernet_connected():
        slot1_icon = eth_icon
    elif status.is_wifi_connected():
        slot1_icon = wifi_icons["on"]
    else:
        slot1_icon = wifi_icons["off"]

    bt_icon = bt_icons["on"] if status.is_bluetooth_on() else bt_icons["off"]

    image.paste(slot1_icon, (4, 3), slot1_icon)
    image.paste(bt_icon,   (36, 3), bt_icon)

    # Background process indicator dot
    if bgm.has_active():
        dot_x, dot_y, dot_r = 68, 12, 5
        draw.ellipse([(dot_x - dot_r, dot_y - dot_r),
                      (dot_x + dot_r, dot_y + dot_r)], fill=(255, 140, 0))
        # Pulsing inner highlight
        draw.ellipse([(dot_x - 2, dot_y - 2),
                      (dot_x + 2, dot_y + 2)], fill=(255, 210, 100))

    # --- Time and date ---
    now     = datetime.now()
    fmt     = _get_clock_fmt()
    sec     = now.second

    if fmt == "12":
        hour_val = now.hour % 12 or 12
        hour_str = f"{hour_val:02d}"
        min_str  = now.strftime("%M")
        ampm     = now.strftime("%p")
        time_str = f"{hour_str}:{min_str}"
    else:
        hour_str = now.strftime("%H")
        min_str  = now.strftime("%M")
        ampm     = ""
        time_str = f"{hour_str}:{min_str}"

    date_str = now.strftime("%m/%d/%Y")

    time_w, time_h = _text_size(draw, time_str, font_big)
    date_w, date_h = _text_size(draw, date_str, font_small)

    time_x = (width - time_w) // 2
    time_y = bar_h + (height - bar_h) // 2 - time_h
    date_x = (width - date_w) // 2
    date_y = time_y + time_h + 15

    # Blinking colon
    draw.text((time_x, time_y), time_str, font=font_big, fill=(255, 255, 255))
    if sec % 2 == 1:
        left_w, _ = _text_size(draw, hour_str, font_big)
        draw.text((time_x + left_w, time_y), ":", font=font_big, fill=(0, 0, 0))

    # AM/PM label for 12h mode
    if ampm:
        aw, ah = _text_size(draw, ampm, font_label)
        draw.text(((width - aw) // 2, time_y - ah - 2),
                  ampm, font=font_label, fill=(150, 150, 150))

    draw.text((date_x, date_y), date_str, font=font_small, fill=(180, 180, 180))

    hw.show(image)
