#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import subprocess
import logging
from datetime import datetime
import shutil  # for deleting non-empty folders

from PIL import ImageFont
from PIL import Image, ImageDraw

from core.hw import HWDisplay
from core.fonts import load_fonts as core_load_fonts
from core.input import read_buttons as core_read_buttons
from core.console import draw_console
from core.monitor import SystemMonitor

from ui.screensaver import draw_screensaver as ui_draw_screensaver
from ui.main_menu import draw_main_menu as ui_draw_main_menu
from ui.list_view import draw_list_view as ui_draw_list_view
from ui.options_menu import draw_options_menu as ui_draw_options_menu

from apps.loader import load_app

from ui_keyboard import OnScreenKeyboard  # on-screen keyboard

logging.basicConfig(level=logging.INFO)

# ---------- Paths ----------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")
MENU_FS_DIR = os.path.join(BASE_DIR, "menu_fs")

# Icons for screensaver (Wi-Fi / BT / GPS)
WIFI_ON_ICON_PATH = os.path.join(ICONS_DIR, "wifi_on.png")
WIFI_OFF_ICON_PATH = os.path.join(ICONS_DIR, "wifi_off.png")
BT_ON_ICON_PATH = os.path.join(ICONS_DIR, "bt_on.png")
BT_OFF_ICON_PATH = os.path.join(ICONS_DIR, "bt_off.png")

GPS_OFF_ICON_PATH = os.path.join(ICONS_DIR, "gps_off.png")
GPS_SEARCH_ICON_PATH = os.path.join(ICONS_DIR, "gps_search.png")
GPS_FIX_ICON_PATH = os.path.join(ICONS_DIR, "gps_fix.png")

FOLDER_ICON_NAME = "folder.png"
APP_DEFAULT_ICON_NAME = "app_default.png"

# ---------- Display init ----------

hw = HWDisplay()
disp = hw.disp  # временная совместимость
SCREEN_WIDTH = hw.W
SCREEN_HEIGHT = hw.H

# ---------- UI states ----------

STATE_SCREENSAVER = "screensaver"
STATE_MAIN_MENU = "main_menu"
STATE_LIST_VIEW = "list_view"
STATE_OPTIONS_MENU = "options_menu"
STATE_KEYBOARD = "keyboard"
STATE_CONSOLE = "console"
STATE_APP = "app"

KB_MODE_RENAME = "rename"
KB_MODE_NEW_FOLDER = "new_folder"

IDLE_TIMEOUT = 999999999.0  # seconds of idle to go back to screensaver

# ---------- Console global state ----------

console_lines = []   # list[str] with command output
console_scroll = 0   # first visible line index

# ---------- Helpers ----------

def _run_command(cmd, timeout=None):
    """
    Run shell command and return stdout as text ('' on error).
    timeout (sec) можно передавать для долгих команд (gpspipe и т.п.).
    """
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=timeout
        )
        return out.decode("utf-8", errors="ignore").strip()
    except subprocess.TimeoutExpired:
        # команда зависла — просто считаем, что данных нет
        return ""
    except Exception:
        return ""


# ---------- GPS helpers ----------

GPS_STATE_OFF = "off"       # нет модуля
GPS_STATE_SEARCH = "search" # модуль есть, но фикса нет
GPS_STATE_FIX = "fix"       # есть координаты (2D/3D фикс)


def is_gps_connected() -> bool:
    """
    GPS считается подключённым, если в lsusb виден девайс u-blox.
    Этого достаточно для простого индикатора на экране.
    """
    out = _run_command(["lsusb"])
    if not out:
        return False

    text = out.lower()
    return "u-blox" in text or "ublox" in text


_GPS_FIX_CACHE = {
    "ts": 0.0,
    "value": False,
}


def gps_has_fix() -> bool:
    """
    Return True if GPS appears to provide valid coordinates.

    Intentionally lenient:
    - any TPV message with non-null lat/lon is treated as a "fix",
      regardless of the reported 'mode' value.
    - protected against hangs and errors:
        * gpspipe timeout
        * result cached for 2 seconds
        * any exception => False
    """

    # If GPS is not physically present → definitely no fix
    if not is_gps_connected():
        _GPS_FIX_CACHE["ts"] = time.time()
        _GPS_FIX_CACHE["value"] = False
        return False

    now = time.time()

    # Use cached result if we checked recently
    if now - _GPS_FIX_CACHE["ts"] < 2.0:
        return _GPS_FIX_CACHE["value"]

    try:
        # Read up to 5 messages, wait at most 0.5 s
        out = _run_command(["gpspipe", "-w", "-n", "5"], timeout=0.5)
        if not out:
            _GPS_FIX_CACHE["ts"] = now
            _GPS_FIX_CACHE["value"] = False
            return False

        has_fix = False

        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            if data.get("class") != "TPV":
                continue

            lat = data.get("lat")
            lon = data.get("lon")

            # Main condition: if gpsd reports coordinates, we treat it as a fix
            if lat is not None and lon is not None:
                has_fix = True
                break

        _GPS_FIX_CACHE["ts"] = now
        _GPS_FIX_CACHE["value"] = has_fix
        return has_fix

    except Exception:
        # Any error here must never kill the UI
        _GPS_FIX_CACHE["ts"] = now
        _GPS_FIX_CACHE["value"] = False
        return False



def get_gps_state() -> str:
    """
    Возвращает одно из:
      - "off"    — нет GPS-модуля
      - "search" — модуль есть, но фикса нет
      - "fix"    — есть GPS-фикс и координаты
    Любые ошибки внутри трактуем как отсутствие фикса / модуля.
    """
    try:
        if not is_gps_connected():
            return GPS_STATE_OFF

        if gps_has_fix():
            return GPS_STATE_FIX

        return GPS_STATE_SEARCH
    except Exception:
        # на всякий случай, чтобы даже тут ничего не уронилo
        return GPS_STATE_OFF


def is_wifi_connected() -> bool:
    """Wi-Fi is connected if iwgetid -r returned SSID."""
    ssid = _run_command(["iwgetid", "-r"])
    return ssid != ""


def is_bluetooth_on() -> bool:
    """Bluetooth is on if adapter hci0 is UP RUNNING."""
    out = _run_command(["hciconfig", "hci0"])
    if not out:
        return False
    return "UP RUNNING" in out or "UP RUNNING" in out.upper()


def load_icon(path: str, size: int = 24) -> Image.Image:
    """Load PNG icon and resize."""
    img = Image.open(path).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    return img


def load_fonts():
    """
    Fonts:
    - font_big   : time on screensaver
    - font_small : date
    - font_label : labels under icons / list items
    """
    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60
        )
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20
        )
        font_label = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15
        )
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_label = ImageFont.load_default()
    return font_big, font_small, font_label


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    """Replacement for draw.textsize using textbbox (for new Pillow)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return w, h


# ---------- Menu FS: root entries ----------

def load_root_menu_entries():
    """
    Scan menu_fs root and read .meta.json in each folder.
    Returns up to 6 entries:
    {
      "path": "/.../menu_fs/01_apps",
      "display_name": "Apps",
      "icon_name": "root_apps.png",
      "icon_image": PIL.Image,
      "sort_priority": int
    }
    """
    entries = []

    if not os.path.isdir(MENU_FS_DIR):
        logging.warning("MENU_FS_DIR does not exist: %s", MENU_FS_DIR)
        return entries

    for name in sorted(os.listdir(MENU_FS_DIR)):
        full = os.path.join(MENU_FS_DIR, name)
        if not os.path.isdir(full):
            continue

        meta_path = os.path.join(full, ".meta.json")
        display_name = name
        icon_name = None
        visible = True
        sort_priority = None

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                display_name = meta.get("display_name", display_name)
                icon_name = meta.get("icon")
                visible = bool(meta.get("visible", True))
                sort_priority = meta.get("sort_priority")
            except Exception as e:
                logging.warning("Failed to read meta for %s: %s", full, e)

        if not visible:
            continue

        icon_file = icon_name or APP_DEFAULT_ICON_NAME
        icon_path = os.path.join(ICONS_DIR, icon_file)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
        except Exception:
            default_path = os.path.join(ICONS_DIR, APP_DEFAULT_ICON_NAME)
            try:
                icon_img = Image.open(default_path).convert("RGBA")
            except Exception:
                icon_img = Image.new("RGBA", (48, 48), (255, 255, 255, 255))

        entries.append({
            "path": full,
            "display_name": display_name,
            "icon_name": icon_file,
            "icon_image": icon_img,
            "sort_priority": sort_priority if sort_priority is not None else 9999,
        })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries[:6]


# ---------- Menu FS: list view entries ----------

def load_list_entries(dir_path: str):
    """
    Load list entries inside directory for LIST_VIEW.
    Returns list of:
    {
      "type": "folder" | "app",
      "path": "/.../menu_fs/02_network/...",
      "display_name": "Wi-Fi",
      "icon_image": PIL.Image,
      "sort_priority": int
    }
    """
    entries = []

    if not os.path.isdir(dir_path):
        return entries

    # Folders
    for name in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, name)
        if name == ".meta.json":
            continue
        if os.path.isdir(full):
            meta_path = os.path.join(full, ".meta.json")
            display_name = name
            icon_name = FOLDER_ICON_NAME
            sort_priority = None
            visible = True

            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    display_name = meta.get("display_name", display_name)
                    icon_name = meta.get("icon", FOLDER_ICON_NAME)
                    visible = bool(meta.get("visible", True))
                    sort_priority = meta.get("sort_priority")
                except Exception as e:
                    logging.warning("Failed to read subfolder meta: %s", e)

            if not visible:
                continue

            icon_path = os.path.join(ICONS_DIR, icon_name)
            try:
                icon_img = Image.open(icon_path).convert("RGBA")
            except Exception:
                fallback_path = os.path.join(ICONS_DIR, FOLDER_ICON_NAME)
                try:
                    icon_img = Image.open(fallback_path).convert("RGBA")
                except Exception:
                    icon_img = Image.new("RGBA", (24, 24, 255, 255))

            entries.append({
                "type": "folder",
                "path": full,
                "display_name": display_name,
                "icon_image": icon_img,
                "sort_priority": sort_priority if sort_priority is not None else 5000,
            })

    # .app files
    for name in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, name)
        if not os.path.isfile(full):
            continue
        if not name.endswith(".app"):
            continue

        display_name = os.path.splitext(name)[0]
        icon_name = APP_DEFAULT_ICON_NAME
        sort_priority = None

        try:
            with open(full, "r", encoding="utf-8") as f:
                meta = json.load(f)
            display_name = meta.get("name", display_name)
            icon_name = meta.get("icon", APP_DEFAULT_ICON_NAME)
            sort_priority = meta.get("sort_priority")
        except Exception as e:
            logging.warning("Failed to read .app meta for %s: %s", full, e)

        icon_path = os.path.join(ICONS_DIR, icon_name)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
        except Exception:
            fallback_path = os.path.join(ICONS_DIR, APP_DEFAULT_ICON_NAME)
            try:
                icon_img = Image.open(fallback_path).convert("RGBA")
            except Exception:
                icon_img = Image.new("RGBA", (24, 24, 255, 255))

        entries.append({
            "type": "app",
            "path": full,
            "display_name": display_name,
            "icon_image": icon_img,
            "sort_priority": sort_priority if sort_priority is not None else 9000,
        })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries


# ---------- Screensaver (clock + Wi-Fi/BT/GPS) ----------

def draw_screensaver(wifi_icons, bt_icons, gps_icons, font_big, font_small):
    """Draw screensaver with time/date and Wi-Fi/BT/GPS status."""
    width, height = SCREEN_WIDTH, SCREEN_HEIGHT

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    bar_height = 30
    draw.line([(0, bar_height), (width, bar_height)], fill=(80, 80, 80), width=1)

    # Wi-Fi / BT
    wifi_connected = is_wifi_connected()
    bt_on = is_bluetooth_on()

    wifi_icon = wifi_icons["on"] if wifi_connected else wifi_icons["off"]
    bt_icon = bt_icons["on"] if bt_on else bt_icons["off"]

    image.paste(wifi_icon, (4, 3), wifi_icon)
    image.paste(bt_icon, (36, 3), bt_icon)

    # GPS: off / search / fix
    try:
        gps_state = get_gps_state()              # "off" / "search" / "fix"
        gps_icon = gps_icons.get(gps_state) or gps_icons["off"]
        image.paste(gps_icon, (68, 3), gps_icon)
    except Exception as e:
        # если вдруг что-то пошло не так — просто не рисуем GPS,
        # но не даём свалиться всей программе
        logging.warning("Failed to draw GPS icon: %s", e)


    now = datetime.now()
    hour_str = now.strftime("%H")
    min_str = now.strftime("%M")
    sec = now.second

    time_str = f"{hour_str}:{min_str}"
    date_str = now.strftime("%m/%d/%Y")

    time_w, time_h = text_size(draw, time_str, font_big)
    date_w, date_h = text_size(draw, date_str, font_small)

    time_x = (width - time_w) // 2
    time_y = bar_height + (height - bar_height) // 2 - time_h

    date_x = (width - date_w) // 2
    date_y = time_y + time_h + 15

    draw.text((time_x, time_y), time_str, font=font_big, fill=(255, 255, 255))

    if sec % 2 == 1:
        left_w, _ = text_size(draw, hour_str, font_big)
        draw.text((time_x + left_w, time_y), ":", font=font_big, fill=(0, 0, 0))

    draw.text((date_x, date_y), date_str, font=font_small, fill=(180, 180, 180))

    im_r = image.rotate(270)
    disp.ShowImage(im_r)


# ---------- Main menu (3×2 grid, title HOME) ----------

def draw_main_menu(entries, selected_index, font_label):
    """Draw main menu 3×2 with title HOME."""
    width, height = SCREEN_WIDTH, SCREEN_HEIGHT
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    top_bar_h = 30
    title = "HOME"
    title_w, title_h = text_size(draw, title, font=font_label)
    title_x = (width - title_w) // 2
    title_y = (top_bar_h - title_h) // 2
    draw.text((title_x, title_y), title, font=font_label, fill=(255, 255, 255))

    draw.line([(0, top_bar_h), (width, top_bar_h)], fill=(80, 80, 80), width=1)

    cols = 3
    rows = 2
    grid_h = height - top_bar_h
    col_w = width // cols
    row_h = grid_h // rows

    icon_size = 48

    for idx, entry in enumerate(entries):
        row = idx // cols
        col = idx % cols
        if row >= rows:
            break

        cell_x0 = col * col_w
        cell_y0 = top_bar_h + row * row_h
        cell_x1 = cell_x0 + col_w
        cell_y1 = cell_y0 + row_h

        cx = (cell_x0 + cell_x1) // 2
        cy = (cell_y0 + cell_y1) // 2

        icon = entry["icon_image"].resize((icon_size, icon_size), Image.LANCZOS)

        label = entry["display_name"]
        label_w, label_h = text_size(draw, label, font=font_label)

        total_h = icon_size + 4 + label_h
        icon_y = cy - total_h // 2
        icon_x = cx - icon_size // 2
        label_x = cx - label_w // 2
        label_y = icon_y + icon_size + 4

        image.paste(icon, (icon_x, icon_y), icon)
        draw.text((label_x, label_y), label, font=font_label, fill=(255, 255, 255))

        if idx == selected_index:
            margin = 4
            draw.rectangle(
                [
                    cell_x0 + margin,
                    cell_y0 + margin,
                    cell_x1 - margin,
                    cell_y1 - margin,
                ],
                outline=(255, 255, 255),
                width=2,
            )

    im_r = image.rotate(270)
    disp.ShowImage(im_r)


# ---------- List view (LIST_VIEW) ----------

def draw_list_view(entries, selected_index, scroll_offset, folder_name, font_label):
    """
    Draw list view of current folder.
    Top bar: folder name + hint for options
    Body: rows with icons + labels
    """
    width, height = SCREEN_WIDTH, SCREEN_HEIGHT
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    top_bar_h = 30
    title = folder_name
    hint = "KEY2: OPT"
    title_w, title_h = text_size(draw, title, font=font_label)
    hint_w, hint_h = text_size(draw, hint, font=font_label)

    title_x = 4
    title_y = (top_bar_h - title_h) // 2
    draw.text((title_x, title_y), title, font=font_label, fill=(255, 255, 255))

    hint_x = width - hint_w - 4
    hint_y = (top_bar_h - hint_h) // 2
    draw.text((hint_x, hint_y), hint, font=font_label, fill=(180, 180, 180))

    draw.line([(0, top_bar_h), (width, top_bar_h)], fill=(80, 80, 80), width=1)

    row_h = 30
    max_rows = (height - top_bar_h) // row_h

    if not entries:
        msg = "Empty"
        msg_w, msg_h = text_size(draw, msg, font=font_label)
        x = (width - msg_w) // 2
        y = top_bar_h + (height - top_bar_h - msg_h) // 2
        draw.text((x, y), msg, font=font_label, fill=(180, 180, 180))
    else:
        icon_size = 20
        start = scroll_offset
        end = min(start + max_rows, len(entries))

        for row, idx in enumerate(range(start, end)):
            entry = entries[idx]
            y0 = top_bar_h + row * row_h
            y1 = y0 + row_h

            if idx == selected_index:
                draw.rectangle(
                    [(0, y0), (width - 1, y1 - 1)],
                    fill=(40, 40, 40),
                    outline=(255, 255, 255),
                    width=1,
                )

            icon = entry["icon_image"].resize((icon_size, icon_size), Image.LANCZOS)
            icon_x = 4
            icon_y = y0 + (row_h - icon_size) // 2
            image.paste(icon, (icon_x, icon_y), icon)

            label = entry["display_name"]
            label_x = icon_x + icon_size + 6
            label_y = y0 + (row_h - font_label.size) // 2
            draw.text((label_x, label_y), label, font=font_label, fill=(255, 255, 255))

    im_r = image.rotate(270)
    disp.ShowImage(im_r)


# ---------- Options menu (OPTIONS_MENU) ----------

OPTIONS_ITEMS = [
    "Create folder",
    "Rename",
    "Delete",
    "Back",
]


def draw_options_menu(selected_index, font_label):
    """Simple modal options menu."""
    width, height = SCREEN_WIDTH, SCREEN_HEIGHT
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    title = "OPTIONS"
    title_w, title_h = text_size(draw, title, font=font_label)
    title_x = (width - title_w) // 2
    title_y = 4
    draw.text((title_x, title_y), title, font=font_label, fill=(255, 255, 255))

    top = title_y + title_h + 4
    row_h = 24

    for idx, txt in enumerate(OPTIONS_ITEMS):
        y0 = top + idx * row_h
        y1 = y0 + row_h

        if idx == selected_index:
            draw.rectangle(
                [(4, y0), (width - 4, y1 - 2)],
                fill=(40, 40, 40),
                outline=(255, 255, 255),
                width=1,
            )

        txt_w, txt_h = text_size(draw, txt, font=font_label)
        x = (width - txt_w) // 2
        y = y0 + (row_h - txt_h) // 2
        draw.text((x, y), txt, font=font_label, fill=(255, 255, 255))

    hint = "UP/DOWN, CENTER=OK, KEY3=BACK"
    hint_w, hint_h = text_size(draw, hint, font=font_label)
    hint_x = (width - hint_w) // 2
    hint_y = height - hint_h - 4
    draw.text((hint_x, hint_y), hint, font=font_label, fill=(180, 180, 180))

    im_r = image.rotate(270)
    disp.ShowImage(im_r)


# ---------- Options actions (filesystem changes) ----------

def create_folder_named(current_dir: str, display_name: str):
    """Create folder with user-defined display name + .meta.json."""
    display_name = (display_name or "").strip()
    if not display_name:
        logging.info("Empty folder name, skipping create")
        return

    safe_name = sanitize_fs_name(display_name)
    if not safe_name:
        safe_name = "Folder"

    base_fs = safe_name
    new_path = None
    for i in range(0, 1000):
        candidate = base_fs if i == 0 else f"{base_fs}_{i}"
        path = os.path.join(current_dir, candidate)
        if not os.path.exists(path):
            new_path = path
            break

    if new_path is None:
        logging.warning("Could not create new folder, limit reached")
        return

    try:
        os.makedirs(new_path, exist_ok=True)
    except Exception as e:
        logging.warning("Failed to create folder %s: %s", new_path, e)
        return

    meta_path = os.path.join(new_path, ".meta.json")
    meta = {
        "display_name": display_name,
        "icon": FOLDER_ICON_NAME,
        "visible": True,
        "sort_priority": 5000,
    }
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logging.warning("Failed to write folder meta: %s", e)

    logging.info("Created folder: %s (display: %s)", new_path, display_name)


def delete_entry(entry):
    """Delete folder (recursive) or app file."""
    path = entry["path"]
    if entry["type"] == "folder":
        try:
            shutil.rmtree(path)
            logging.info("Deleted folder: %s", path)
        except Exception as e:
            logging.warning("Failed to delete folder %s: %s", path, e)
    elif entry["type"] == "app":
        try:
            os.remove(path)
            logging.info("Deleted app: %s", path)
        except Exception as e:
            logging.warning("Failed to delete app %s: %s", path, e)


def sanitize_fs_name(name: str) -> str:
    """Make safe filesystem name from user input."""
    name = name.strip()
    if not name:
        return ""
    # replace spaces with underscores
    name = name.replace(" ", "_")
    # allow only limited set of chars
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    safe = "".join(ch for ch in name if ch in allowed)
    return safe


def rename_entry(entry, new_display_name: str):
    """
    Rename folder or app file on disk and update meta.
    new_display_name is what user typed (can contain spaces).
    """
    path = entry["path"]
    parent = os.path.dirname(path)
    display_name = new_display_name.strip()
    if not display_name:
        logging.info("Empty new name, skipping rename")
        return

    if entry["type"] == "folder":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            logging.info("Sanitized folder name is empty, skipping rename")
            return

        new_path = os.path.join(parent, safe_name)
        # avoid overwrite
        if os.path.exists(new_path):
            for i in range(1, 1000):
                candidate = f"{safe_name}_{i}"
                candidate_path = os.path.join(parent, candidate)
                if not os.path.exists(candidate_path):
                    new_path = candidate_path
                    break

        try:
            os.rename(path, new_path)
        except Exception as e:
            logging.warning("Failed to rename folder %s -> %s: %s", path, new_path, e)
            return

        meta_path = os.path.join(new_path, ".meta.json")
        meta = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        meta["display_name"] = display_name
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logging.warning("Failed to write meta after folder rename: %s", e)

        entry["path"] = new_path
        entry["display_name"] = display_name
        logging.info("Renamed folder to: %s (display: %s)", new_path, display_name)

    elif entry["type"] == "app":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            logging.info("Sanitized app name is empty, skipping rename")
            return

        new_file = safe_name + ".app"
        new_path = os.path.join(parent, new_file)
        if os.path.exists(new_path):
            for i in range(1, 1000):
                candidate = f"{safe_name}_{i}.app"
                candidate_path = os.path.join(parent, candidate)
                if not os.path.exists(candidate_path):
                    new_path = candidate_path
                    break

        try:
            os.rename(path, new_path)
        except Exception as e:
            logging.warning("Failed to rename app %s -> %s: %s", path, new_path, e)
            return

        meta = {}
        try:
            with open(new_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        meta["name"] = display_name
        try:
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logging.warning("Failed to write app meta after rename: %s", e)

        entry["path"] = new_path
        entry["display_name"] = display_name
        logging.info("Renamed app to: %s (display: %s)", new_path, display_name)


# ---------- Run .app (console commands) ----------

def run_app(entry):
    """Run .app file command and fill console_lines with its output."""
    global console_lines, console_scroll

    path = entry["path"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        console_lines = [f"ERROR: cannot read .app: {e}"]
        console_scroll = 0
        return

    cmd = meta.get("exec")
    if not cmd:
        console_lines = ["ERROR: no 'exec' in .app"]
        console_scroll = 0
        return

    logging.info("Running app command: %s", cmd)

    try:
        output = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, shell=True, timeout=20
        )
        text = output.decode("utf-8", errors="ignore")
    except subprocess.CalledProcessError as e:
        text = e.output.decode("utf-8", errors="ignore")
    except Exception as e:
        text = str(e)

    console_lines = text.splitlines()
    console_scroll = 0


# ---------- Input handling (joystick + 3 keys) ----------

def read_buttons(prev_states):
    """
    Read GPIO buttons via disp.digital_read(...).
    Returns (event, new_states).
    event: 'UP','DOWN','LEFT','RIGHT','CENTER','KEY1','KEY2','KEY3' or None
    Event is generated only on 1 -> 0 transition (press).
    """
    pins = {
        "UP": disp.GPIO_KEY_UP_PIN,
        "DOWN": disp.GPIO_KEY_DOWN_PIN,
        "LEFT": disp.GPIO_KEY_LEFT_PIN,
        "RIGHT": disp.GPIO_KEY_RIGHT_PIN,
        "CENTER": disp.GPIO_KEY_PRESS_PIN,
        "KEY1": disp.GPIO_KEY1_PIN,
        "KEY2": disp.GPIO_KEY2_PIN,
        "KEY3": disp.GPIO_KEY3_PIN,
    }

    new_states = {}
    event = None

    for name, pin in pins.items():
        val = disp.digital_read(pin)
        new_states[name] = val
        prev = prev_states.get(name, 1)
        if prev == 1 and val == 0 and event is None:
            event = name

    return event, new_states


# ---------- Main loop ----------

def main():
    global console_lines, console_scroll

    font_big, font_small, font_label = load_fonts()

    wifi_icons = {
        "on": load_icon(WIFI_ON_ICON_PATH, size=24),
        "off": load_icon(WIFI_OFF_ICON_PATH, size=24),
    }
    bt_icons = {
        "on": load_icon(BT_ON_ICON_PATH, size=24),
        "off": load_icon(BT_OFF_ICON_PATH, size=24),
    }

    gps_icons = {
        "off": load_icon(GPS_OFF_ICON_PATH, size=24),
        "search": load_icon(GPS_SEARCH_ICON_PATH, size=24),
        "fix": load_icon(GPS_FIX_ICON_PATH, size=24),
    }

    root_entries = load_root_menu_entries()
    if len(root_entries) == 0:
        logging.warning("No root menu entries found in %s", MENU_FS_DIR)

    # UI state
    state = STATE_SCREENSAVER
    selected_root_index = 0

    # List view state
    current_dir = None
    current_dir_name = ""
    list_entries = []
    selected_list_index = 0
    list_scroll = 0

    current_app = None
    current_app_module = None
    last_frame_time = time.time()

    # Options menu state
    selected_option_index = 0

    # Keyboard state
    keyboard = OnScreenKeyboard(disp, font_label)
    keyboard_mode = None      # "rename" | "new_folder" | None
    keyboard_target = None    # entry dict for rename (or None)

    # Seed initial button states
    prev_button_states = {}
    seed_pins = {
        "UP": disp.GPIO_KEY_UP_PIN,
        "DOWN": disp.GPIO_KEY_DOWN_PIN,
        "LEFT": disp.GPIO_KEY_LEFT_PIN,
        "RIGHT": disp.GPIO_KEY_RIGHT_PIN,
        "CENTER": disp.GPIO_KEY_PRESS_PIN,
        "KEY1": disp.GPIO_KEY1_PIN,
        "KEY2": disp.GPIO_KEY2_PIN,
        "KEY3": disp.GPIO_KEY3_PIN,
    }
    for name, pin in seed_pins.items():
        prev_button_states[name] = disp.digital_read(pin)

    last_input_time = time.time()
    last_clock_draw = 0.0
    menu_dirty = True
    list_dirty = True
    options_dirty = True
    keyboard_dirty = True
    console_dirty = True
    monitor = SystemMonitor(max_points=600, interval=1.0)

    try:
        while True:
            now = time.time()
            dt = now - last_frame_time
            last_frame_time = now
            monitor.sample(now)

            # Input
            event, prev_button_states = read_buttons(prev_button_states)
            if event is not None:
                last_input_time = now
                logging.debug("Input event: %s", event)

                if state == STATE_SCREENSAVER:
                    state = STATE_MAIN_MENU
                    menu_dirty = True

                elif state == STATE_APP:
                    if current_app is not None:
                        result = current_app.on_event(event)
                        if result == "exit":
                            state = STATE_LIST_VIEW
                            list_dirty = True
                            current_app = None
                            current_app_module = None

                elif state == STATE_MAIN_MENU:
                    if event == "KEY3":
                        state = STATE_SCREENSAVER
                    elif event in ("UP", "DOWN", "LEFT", "RIGHT"):
                        if root_entries:
                            rows = 2
                            cols = 3
                            idx = selected_root_index
                            row = idx // cols
                            col = idx % cols

                            if event == "UP" and row > 0:
                                row -= 1
                            elif event == "DOWN" and row < rows - 1:
                                row += 1
                            elif event == "LEFT" and col > 0:
                                col -= 1
                            elif event == "RIGHT" and col < cols - 1:
                                col += 1

                            new_idx = row * cols + col
                            if new_idx < len(root_entries) and new_idx != selected_root_index:
                                selected_root_index = new_idx
                                menu_dirty = True

                    elif event == "CENTER":
                        if 0 <= selected_root_index < len(root_entries):
                            entry = root_entries[selected_root_index]
                            current_dir = entry["path"]
                            current_dir_name = entry["display_name"]
                            list_entries = load_list_entries(current_dir)
                            selected_list_index = 0
                            list_scroll = 0
                            state = STATE_LIST_VIEW
                            list_dirty = True
                            logging.info("Enter LIST_VIEW: %s", current_dir_name)

                elif state == STATE_LIST_VIEW:
                    if event == "KEY3":
                        state = STATE_MAIN_MENU
                        menu_dirty = True

                    elif event in ("UP", "DOWN"):
                        if list_entries:
                            row_h = 30
                            max_rows = (SCREEN_HEIGHT - 30) // row_h
                            if event == "UP" and selected_list_index > 0:
                                selected_list_index -= 1
                                if selected_list_index < list_scroll:
                                    list_scroll = selected_list_index
                                list_dirty = True
                            elif event == "DOWN" and selected_list_index < len(list_entries) - 1:
                                selected_list_index += 1
                                if selected_list_index >= list_scroll + max_rows:
                                    list_scroll = selected_list_index - max_rows + 1
                                list_dirty = True

                    elif event == "CENTER":
                        if list_entries:
                            item = list_entries[selected_list_index]
                            if item["type"] == "folder":
                                current_dir = item["path"]
                                current_dir_name = item["display_name"]
                                list_entries = load_list_entries(current_dir)
                                selected_list_index = 0
                                list_scroll = 0
                                list_dirty = True
                                logging.info("Enter subfolder: %s", current_dir_name)
                            elif item["type"] == "app":
                                try:
                                    with open(item["path"], "r", encoding="utf-8") as f:
                                        meta = json.load(f)
                                except Exception as e:
                                    logging.warning("Failed to read app meta %s: %s", item["path"], e)
                                    continue

                                module_name = meta.get("module")
                                if module_name:
                                    app = load_app(module_name, hw, (font_big, font_small, font_label), monitor)
                                    if app is not None:
                                        current_app = app
                                        current_app_module = module_name
                                        if hasattr(current_app, "on_enter"):
                                            current_app.on_enter()
                                        state = STATE_APP
                                    else:
                                        logging.warning("Failed to init app %s", module_name)
                                else:
                                    exec_cmd = meta.get("exec")
                                    if exec_cmd:
                                        run_app(item)
                                        state = STATE_CONSOLE
                                        console_scroll = 0
                                        console_dirty = True

                    elif event == "KEY2":
                        state = STATE_OPTIONS_MENU
                        selected_option_index = 0
                        options_dirty = True
                        logging.info("Open OPTIONS_MENU")

                elif state == STATE_OPTIONS_MENU:
                    if event == "KEY3":
                        state = STATE_LIST_VIEW
                        list_dirty = True

                    elif event in ("UP", "DOWN"):
                        max_idx = len(OPTIONS_ITEMS) - 1
                        if event == "UP" and selected_option_index > 0:
                            selected_option_index -= 1
                            options_dirty = True
                        elif event == "DOWN" and selected_option_index < max_idx:
                            selected_option_index += 1
                            options_dirty = True

                    elif event == "CENTER":
                        choice = OPTIONS_ITEMS[selected_option_index]
                        logging.info("OPTIONS choice: %s", choice)

                        if choice == "Back":
                            state = STATE_LIST_VIEW
                            list_dirty = True

                        elif choice == "Create folder":
                            if current_dir:
                                keyboard_mode = KB_MODE_NEW_FOLDER
                                keyboard_target = None
                                keyboard.start("New folder", initial_text="", max_len=64)
                                state = STATE_KEYBOARD
                                keyboard_dirty = True

                        elif choice == "Delete":
                            if list_entries:
                                item = list_entries[selected_list_index]
                                delete_entry(item)
                                list_entries = load_list_entries(current_dir)
                                if selected_list_index >= len(list_entries):
                                    selected_list_index = max(0, len(list_entries) - 1)
                                list_scroll = min(list_scroll, selected_list_index)
                                state = STATE_LIST_VIEW
                                list_dirty = True
                            else:
                                state = STATE_LIST_VIEW
                                list_dirty = True

                        elif choice == "Rename":
                            if list_entries:
                                keyboard_mode = KB_MODE_RENAME
                                keyboard_target = list_entries[selected_list_index]
                                initial = keyboard_target["display_name"]
                                keyboard.start("Rename", initial_text=initial, max_len=64)
                                state = STATE_KEYBOARD
                                keyboard_dirty = True
                                logging.info("Open KEYBOARD for rename: %s", initial)
                            else:
                                state = STATE_LIST_VIEW
                                list_dirty = True

                elif state == STATE_KEYBOARD:
                    if event == "KEY3":
                        keyboard_mode = None
                        keyboard_target = None
                        state = STATE_LIST_VIEW
                        list_dirty = True

                    elif event == "KEY1":
                        keyboard.cycle_language()
                        keyboard_dirty = True

                    elif event == "KEY2":
                        text = keyboard.text

                        if keyboard_mode == KB_MODE_RENAME and keyboard_target and text is not None:
                            rename_entry(keyboard_target, text)
                        elif keyboard_mode == KB_MODE_NEW_FOLDER and current_dir and text is not None:
                            create_folder_named(current_dir, text)

                        if current_dir:
                            list_entries = load_list_entries(current_dir)
                            if selected_list_index >= len(list_entries):
                                selected_list_index = max(0, len(list_entries) - 1)
                            list_scroll = min(list_scroll, selected_list_index)

                        keyboard_mode = None
                        keyboard_target = None
                        state = STATE_LIST_VIEW
                        list_dirty = True

                    else:
                        action, text = keyboard.handle_event(event)
                        if action == "redraw":
                            keyboard_dirty = True
                        elif action == "done":
                            if keyboard_mode == KB_MODE_RENAME and keyboard_target and text is not None:
                                rename_entry(keyboard_target, text)
                            elif keyboard_mode == KB_MODE_NEW_FOLDER and current_dir and text is not None:
                                create_folder_named(current_dir, text)

                            if current_dir:
                                list_entries = load_list_entries(current_dir)
                                if selected_list_index >= len(list_entries):
                                    selected_list_index = max(0, len(list_entries) - 1)
                                list_scroll = min(list_scroll, selected_list_index)

                            keyboard_mode = None
                            keyboard_target = None
                            state = STATE_LIST_VIEW
                            list_dirty = True

                elif state == STATE_CONSOLE:
                    if event == "KEY3":
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    elif event == "UP":
                        if console_scroll > 0:
                            console_scroll -= 1
                            console_dirty = True
                    elif event == "DOWN":
                        if console_scroll < max(0, len(console_lines) - 1):
                            console_scroll += 1
                            console_dirty = True

            # Idle timeout → screensaver
            if state != STATE_SCREENSAVER and (now - last_input_time) > IDLE_TIMEOUT:
                state = STATE_SCREENSAVER

            # Draw according to state
            if state == STATE_SCREENSAVER:
                if now - last_clock_draw >= 1.0:
                    draw_screensaver(wifi_icons, bt_icons, gps_icons, font_big, font_small)
                    last_clock_draw = now

            elif state == STATE_MAIN_MENU:
                if menu_dirty:
                    draw_main_menu(root_entries, selected_root_index, font_label)
                    menu_dirty = False

            elif state == STATE_LIST_VIEW:
                if list_dirty:
                    draw_list_view(list_entries, selected_list_index, list_scroll, current_dir_name, font_label)
                    list_dirty = False

            elif state == STATE_OPTIONS_MENU:
                if options_dirty:
                    draw_options_menu(selected_option_index, font_label)
                    options_dirty = False

            elif state == STATE_KEYBOARD:
                if keyboard_dirty:
                    keyboard.draw()
                    keyboard_dirty = False

            elif state == STATE_APP:
                if current_app is not None:
                    current_app.update(dt)
                    current_app.draw()

            elif state == STATE_CONSOLE:
                if console_dirty:
                    draw_console(hw, font_label, console_lines, console_scroll)
                    console_dirty = False

            time.sleep(0.05)

    except KeyboardInterrupt:
        disp.clear()
        logging.info("Exit by KeyboardInterrupt")


if __name__ == "__main__":
    main()
