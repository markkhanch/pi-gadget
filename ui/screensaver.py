"""
ui/screensaver.py
Screensaver: clock, date, Wi-Fi/Ethernet and Bluetooth icons.
"""

import os
import shutil
import subprocess
from PIL import Image, ImageDraw
from datetime import datetime
from core.background import bgm


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


WARN_CPU_PATH  = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "warn_cpu.png")
WARN_DISK_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "warn_disk.png")
WARN_TEMP_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "warn_temp.png")

# Thresholds for warnings
WARN_TEMP_C    = 70.0   # Celsius
WARN_DISK_PCT  = 10     # % free remaining
WARN_CPU_PCT   = 85     # % CPU usage sustained

# Cache warning icons (loaded once)
_warn_icons: dict = {}


def _load_warn_icon(path: str, size: int = 22) -> object:
    """Load and cache a warning icon."""
    if path not in _warn_icons:
        try:
            img = Image.open(os.path.abspath(path)).convert("RGBA")
            _warn_icons[path] = img.resize((size, size), Image.LANCZOS)
        except Exception:
            _warn_icons[path] = None
    return _warn_icons[path]


def _get_cpu_temp() -> float:
    """Read CPU temperature from thermal zone."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return 0.0


_cpu_cache: dict = {"pct": 0.0, "ts": 0.0}
_CPU_SAMPLE_INTERVAL = 10.0


def _get_cpu_pct() -> float:
    """Get CPU usage % from /proc/stat — cached every 10s."""
    import time
    now = time.time()
    if now - _cpu_cache["ts"] < _CPU_SAMPLE_INTERVAL:
        return _cpu_cache["pct"]
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = list(map(int, line.split()[1:]))
        idle  = parts[3]
        total = sum(parts)
        prev  = _cpu_cache.get("_prev", (total, idle))
        dt    = total - prev[0]
        di    = idle  - prev[1]
        pct   = (1.0 - di / dt) * 100.0 if dt > 0 else 0.0
        _cpu_cache["_prev"] = (total, idle)
        _cpu_cache["pct"]   = pct
        _cpu_cache["ts"]    = now
        return pct
    except Exception:
        return 0.0


def _get_disk_free_pct() -> float:
    """Get free disk space % for root partition."""
    try:
        total, used, free = shutil.disk_usage("/")
        return (free / total) * 100
    except Exception:
        return 100.0


def _get_active_warnings() -> list:
    """
    Return list of (icon_path, label) for active warnings.
    Checks temp, disk, CPU.
    """
    warnings = []
    temp = _get_cpu_temp()
    if temp >= WARN_TEMP_C:
        warnings.append((WARN_TEMP_PATH, f"{temp:.0f}°C"))

    disk_free = _get_disk_free_pct()
    if disk_free <= WARN_DISK_PCT:
        warnings.append((WARN_DISK_PATH, f"{disk_free:.0f}%"))

    cpu = _get_cpu_pct()
    if cpu >= WARN_CPU_PCT:
        warnings.append((WARN_CPU_PATH, f"{cpu:.0f}%"))

    return warnings


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

    # Background process indicator dot (left side)
    if bgm.has_active():
        dot_x, dot_y, dot_r = 68, 12, 5
        draw.ellipse([(dot_x - dot_r, dot_y - dot_r),
                      (dot_x + dot_r, dot_y + dot_r)], fill=(255, 140, 0))
        draw.ellipse([(dot_x - 2, dot_y - 2),
                      (dot_x + 2, dot_y + 2)], fill=(255, 210, 100))

    # Warning icons (right side of status bar)
    warnings = _get_active_warnings()
    wx = width - 4
    for (icon_path, _label) in reversed(warnings):
        icon = _load_warn_icon(icon_path, size=22)
        if icon:
            wx -= 22
            image.paste(icon, (wx, 3), icon)
            wx -= 2

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
