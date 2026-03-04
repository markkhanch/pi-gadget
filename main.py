#!/usr/bin/env python3

import os
import time
import json
import logging

from PIL import Image, ImageFont

from core.hw import HWDisplay
from core.fonts import load_fonts
from core.input import read_buttons
from core.console import draw_console
from core.monitor import SystemMonitor
from core import status

from core.menu_loader import (
    load_root_menu_entries,
    load_grid_entries,
    load_list_entries,
)
from core.fs_ops import (
    create_folder_named,
    delete_entry,
    rename_entry,
    copy_entry,
    paste_clipboard,
    get_entry_info,
    run_app,
)

from ui.screensaver import draw_screensaver
from ui.main_menu import draw_main_menu
from ui.list_view import draw_list_view
from ui.info_view import draw_info_view
from ui.options_menu import (
    draw_options_menu,
    build_options,
    OPT_BACK, OPT_CREATE_FOLDER, OPT_DELETE,
    OPT_RENAME, OPT_COPY, OPT_PASTE, OPT_INFO,
)

from apps.loader import load_app
from core.background import bgm
import signal
import atexit
from core.ui_keyboard import OnScreenKeyboard

logging.basicConfig(level=logging.INFO)


def _cleanup():
    """Stop all background processes on exit."""
    if bgm.has_active():
        logging.info("Stopping background tasks: %s", bgm.active_tasks())
        bgm.stop_all()


atexit.register(_cleanup)


def _signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT — cleanup and exit."""
    _cleanup()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT,  _signal_handler)

# ─────────────────────────── Paths ───────────────────────────

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
ICONS_DIR   = os.path.join(ASSETS_DIR, "icons")
MENU_FS_DIR = os.path.join(BASE_DIR, "menu_fs")

WIFI_ON_ICON_PATH  = os.path.join(ICONS_DIR, "wifi_on.png")
WIFI_OFF_ICON_PATH = os.path.join(ICONS_DIR, "wifi_off.png")
BT_ON_ICON_PATH    = os.path.join(ICONS_DIR, "bt_on.png")
BT_OFF_ICON_PATH   = os.path.join(ICONS_DIR, "bt_off.png")
ETH_ICON_PATH      = os.path.join(ICONS_DIR, "ethernet.png")

# ─────────────────────────── States ──────────────────────────

STATE_SCREENSAVER  = "screensaver"
STATE_MAIN_MENU    = "main_menu"
STATE_GRID_VIEW    = "grid_view"    # Sub-grid (e.g. Hacking categories)
STATE_LIST_VIEW    = "list_view"
STATE_OPTIONS_MENU = "options_menu"
STATE_KEYBOARD     = "keyboard"
STATE_CONSOLE      = "console"
STATE_APP          = "app"
STATE_INFO         = "info"
STATE_DIMMED       = "dimmed"   # Backlight off, waiting for wake
STATE_BG_TASKS     = "bg_tasks"  # Background tasks manager screen

KB_MODE_RENAME     = "rename"
KB_MODE_NEW_FOLDER = "new_folder"


def _load_config() -> dict:
    cfg_path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}


_cfg           = _load_config()
IDLE_TIMEOUT   = float(_cfg.get("idle_timeout", 999999999.0))
SCREEN_TIMEOUT = float(_cfg.get("screen_timeout", 999999999.0))


def load_icon(path: str, size: int = 24) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return img.resize((size, size), Image.LANCZOS)


def _apply_keyboard_result(mode, target, text, current_dir):
    if text is None:
        return
    if mode == KB_MODE_RENAME and target:
        rename_entry(target, text)
    elif mode == KB_MODE_NEW_FOLDER and current_dir:
        create_folder_named(current_dir, text)


def _enter_folder(entry: dict, nav_stack: list,
                  current_dir, current_dir_name,
                  list_entries, selected_list_index, list_scroll,
                  icons_dir: str):
    """
    Decide whether to enter GRID_VIEW or LIST_VIEW based on entry view field.
    Returns (new_state, new_dir, new_dir_name, new_entries, new_sel, new_scroll).
    Pushes current list state onto nav_stack.
    """
    view = entry.get("view", "list")
    path = entry["path"]
    name = entry["display_name"]

    # Save current list state before navigating in
    nav_stack.append((
        current_dir, current_dir_name,
        list_entries, selected_list_index, list_scroll,
    ))

    if view == "grid":
        entries = load_grid_entries(path, icons_dir)
        return STATE_GRID_VIEW, path, name, entries, 0, 0
    else:
        entries = load_list_entries(path, icons_dir)
        return STATE_LIST_VIEW, path, name, entries, 0, 0


def _draw_bg_tasks(hw, fonts, bgm, selected_index: int):
    """Draw background tasks management screen."""
    from PIL import Image, ImageDraw
    import time as _time

    font_big, font_small, font_label = fonts
    W, H = hw.W, hw.H
    img  = Image.new("RGB", (W, H), (4, 8, 16))
    d    = ImageDraw.Draw(img)

    TOP_H  = 26
    BOT_H  = 18
    HDR_BG = (8, 14, 28)
    SEP    = (25, 45, 75)
    WHITE  = (220, 235, 255)
    DIM    = (70, 100, 140)
    HINT   = (50, 75, 110)
    GREEN  = (50, 220, 120)
    RED    = (255, 70, 70)
    ORANGE = (255, 140, 30)

    def ts(text, font):
        b = d.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    # Header
    d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
    d.rectangle([(0, 0), (3, TOP_H)], fill=ORANGE)
    title = "Background Tasks"
    tw, th = ts(title, font_label)
    d.text(((W - tw) // 2, (TOP_H - th) // 2),
           title, font=font_label, fill=ORANGE)
    d.line([(0, TOP_H), (W, TOP_H)], fill=SEP, width=1)

    tasks = bgm.active_tasks()

    if not tasks:
        msg = "No background tasks"
        mw, mh = ts(msg, font_label)
        d.text(((W - mw) // 2, TOP_H + 40), msg,
               font=font_label, fill=DIM)
    else:
        y = TOP_H + 8
        lh = font_label.size + 8

        for i, name in enumerate(tasks):
            info    = bgm.get_task_info(name)
            uptime  = bgm.uptime(name)
            h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
            up_str  = f"{h:02d}:{m:02d}:{s:02d}"

            is_sel  = (i == selected_index)
            row_col = GREEN if is_sel else WHITE
            dim_col = (80, 180, 80) if is_sel else DIM

            # Selection indicator
            if is_sel:
                d.rectangle([(0, y - 2), (W, y + lh - 2)],
                             fill=(10, 30, 20))
                d.rectangle([(0, y - 2), (3, y + lh - 2)],
                             fill=GREEN)

            d.text((8, y), f"● {name}", font=font_label, fill=row_col)
            up_w, _ = ts(up_str, font_label)
            d.text((W - up_w - 6, y), up_str,
                   font=font_label, fill=dim_col)
            y += lh

            if is_sel:
                # Show resources used
                res = ", ".join(info.get("resources", []))
                rw, _ = ts(res, font_label)
                d.text((8, y), res, font=font_label, fill=(100, 100, 140))
                y += lh

    # Bottom hints
    d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
    hint = "CTR:enter  K1:stop  K3:back"
    hw2, hh2 = ts(hint, font_label)
    d.text(((W - hw2) // 2, H - hh2 - 2),
           hint, font=font_label, fill=HINT)

    hw.show(img)


def main():
    hw = HWDisplay()

    _orig_show = hw.show
    def _patched_show(img):
        _orig_show(img)
        if hw._remote:
            hw._remote.push_frame(img)
    hw.show = _patched_show

    fonts = load_fonts()
    font_big, font_small, font_label = fonts

    wifi_icons = {
        "on":  load_icon(WIFI_ON_ICON_PATH,  size=24),
        "off": load_icon(WIFI_OFF_ICON_PATH, size=24),
    }
    bt_icons = {
        "on":  load_icon(BT_ON_ICON_PATH,  size=24),
        "off": load_icon(BT_OFF_ICON_PATH, size=24),
    }
    try:
        eth_icon = load_icon(ETH_ICON_PATH, size=24)
    except Exception:
        eth_icon = None

    root_entries = load_root_menu_entries(MENU_FS_DIR, ICONS_DIR)

    state               = STATE_SCREENSAVER
    selected_root_index = 0

    # Shared list/grid state
    current_dir         = None
    current_dir_name    = ""
    list_entries        = []
    selected_list_index = 0
    list_scroll         = 0

    # Grid view state (sub-menu like Hacking)
    grid_entries        = []
    selected_grid_index = 0

    # Navigation history stack
    # Each item: (current_dir, current_dir_name, list_entries, sel_idx, scroll)
    nav_stack = []

    current_app        = None
    current_app_module = None
    last_frame_time    = time.time()

    # Options menu
    current_options       = []
    selected_option_index = 0

    # Clipboard
    clipboard = None

    # Background tasks screen
    selected_bg_index = 0

    # Info screen
    info_lines  = []
    info_scroll = 0

    keyboard        = OnScreenKeyboard(hw.disp, font_label)
    keyboard_mode   = None
    keyboard_target = None

    console_lines  = []
    console_scroll = 0

    monitor = SystemMonitor(max_points=600, interval=1.0)
    prev_button_states = {name: hw.gpio_read(pin) for name, pin in hw.pins.items()}

    last_input_time  = time.time()
    last_clock_draw  = 0.0
    screen_is_dimmed = False
    menu_dirty      = True
    grid_dirty      = True
    list_dirty      = True
    options_dirty   = True
    keyboard_dirty  = True
    console_dirty   = True
    info_dirty      = True

    try:
        while True:
            now = time.time()
            dt  = now - last_frame_time
            last_frame_time = now
            monitor.sample(now)

            event, prev_button_states = read_buttons(hw, prev_button_states)
            events = []
            if event is not None:
                events.append(event)
            while not hw._remote_queue.empty():
                try:
                    events.append(hw._remote_queue.get_nowait())
                except Exception:
                    pass

            for event in events:
                last_input_time = now

                # Wake screen if backlight was off
                if screen_is_dimmed:
                    screen_is_dimmed = False
                    cfg = _load_config()
                    hw.backlight(int(cfg.get("brightness", 80)))
                    state = STATE_SCREENSAVER
                    continue

                # ── Screensaver ───────────────────────────────
                if state == STATE_SCREENSAVER:
                    if event == "KEY1" and bgm.has_active():
                        state = STATE_BG_TASKS
                    else:
                        state = STATE_MAIN_MENU
                        menu_dirty = True

                # ── App ───────────────────────────────────────
                elif state == STATE_APP:
                    if current_app is not None:
                        result = current_app.on_event(event)
                        if result == "exit":
                            # on_exit is optional — not all apps implement it
                            if hasattr(current_app, "on_exit"):
                                current_app.on_exit()
                            current_app = None
                            current_app_module = None
                            state = STATE_LIST_VIEW
                            list_dirty = True
                        elif result == "background":
                            # App keeps running in background — just go back to menu
                            current_app = None
                            current_app_module = None
                            state = STATE_LIST_VIEW
                            list_dirty = True

                # ── Main menu ─────────────────────────────────
                elif state == STATE_MAIN_MENU:
                    if event == "KEY3":
                        state = STATE_SCREENSAVER
                    elif event in ("UP", "DOWN", "LEFT", "RIGHT"):
                        if root_entries:
                            cols = 3
                            rows = 2
                            idx  = selected_root_index
                            r, c = idx // cols, idx % cols
                            if   event == "UP"    and r > 0:        r -= 1
                            elif event == "DOWN"  and r < rows - 1: r += 1
                            elif event == "LEFT"  and c > 0:        c -= 1
                            elif event == "RIGHT" and c < cols - 1: c += 1
                            new_idx = r * cols + c
                            if new_idx < len(root_entries) and new_idx != selected_root_index:
                                selected_root_index = new_idx
                                menu_dirty = True
                    elif event == "CENTER":
                        if 0 <= selected_root_index < len(root_entries):
                            entry = root_entries[selected_root_index]
                            nav_stack = []  # Fresh navigation history

                            if entry.get("view") == "grid":
                                # Enter sub-grid (e.g. Hacking)
                                grid_entries        = load_grid_entries(entry["path"], ICONS_DIR)
                                selected_grid_index = 0
                                current_dir         = entry["path"]
                                current_dir_name    = entry["display_name"]
                                state = STATE_GRID_VIEW
                                grid_dirty = True
                            else:
                                # Enter list view
                                current_dir         = entry["path"]
                                current_dir_name    = entry["display_name"]
                                list_entries        = load_list_entries(current_dir, ICONS_DIR)
                                selected_list_index = 0
                                list_scroll         = 0
                                state = STATE_LIST_VIEW
                                list_dirty = True
                            logging.info("Enter %s: %s", entry.get("view","list"), entry["display_name"])

                # ── Grid view (sub-menu) ───────────────────────
                elif state == STATE_GRID_VIEW:
                    if event == "KEY3":
                        if nav_stack:
                            prev = nav_stack.pop()
                            current_dir, current_dir_name = prev[0], prev[1]
                            list_entries        = prev[2]
                            selected_list_index = prev[3]
                            list_scroll         = prev[4]
                            state = STATE_LIST_VIEW
                            list_dirty = True
                        else:
                            state = STATE_MAIN_MENU
                            menu_dirty = True
                    elif event in ("UP", "DOWN", "LEFT", "RIGHT"):
                        if grid_entries:
                            cols = 3
                            rows = 2
                            idx  = selected_grid_index
                            r, c = idx // cols, idx % cols
                            if   event == "UP"    and r > 0:        r -= 1
                            elif event == "DOWN"  and r < rows - 1: r += 1
                            elif event == "LEFT"  and c > 0:        c -= 1
                            elif event == "RIGHT" and c < cols - 1: c += 1
                            new_idx = r * cols + c
                            if new_idx < len(grid_entries) and new_idx != selected_grid_index:
                                selected_grid_index = new_idx
                                grid_dirty = True
                    elif event == "CENTER":
                        if grid_entries:
                            item = grid_entries[selected_grid_index]
                            if item["type"] == "folder":
                                # Push grid state, enter list
                                nav_stack.append((
                                    current_dir, current_dir_name,
                                    grid_entries, selected_grid_index, 0,
                                ))
                                current_dir         = item["path"]
                                current_dir_name    = item["display_name"]
                                list_entries        = load_list_entries(current_dir, ICONS_DIR)
                                selected_list_index = 0
                                list_scroll         = 0
                                state = STATE_LIST_VIEW
                                list_dirty = True
                                logging.info("Enter subfolder from grid: %s", current_dir_name)
                            elif item["type"] == "app":
                                # Launch app from grid
                                try:
                                    with open(item["path"], "r", encoding="utf-8") as f:
                                        meta = json.load(f)
                                except Exception as e:
                                    logging.warning("Failed to read app meta: %s", e)
                                    continue
                                module_name = meta.get("module")
                                if module_name:
                                    app = load_app(module_name, hw, fonts, monitor)
                                    if app is not None:
                                        current_app = app
                                        current_app_module = module_name
                                        if hasattr(current_app, "on_enter"):
                                            current_app.on_enter()
                                        state = STATE_APP
                                    else:
                                        logging.warning("Failed to init app: %s", module_name)
                                elif meta.get("exec"):
                                    console_lines, console_scroll = run_app(item)
                                    state = STATE_CONSOLE
                                    console_dirty = True

                # ── List view ─────────────────────────────────
                elif state == STATE_LIST_VIEW:
                    if event == "KEY3":
                        if nav_stack:
                            prev = nav_stack.pop()
                            prev_dir  = prev[0]
                            prev_name = prev[1]
                            prev_data = prev[2]
                            prev_sel  = prev[3]
                            prev_scr  = prev[4]

                            # Detect if we're going back to a grid
                            if isinstance(prev_data, list) and prev_data and \
                               prev_data[0].get("type") in ("folder", "app") and \
                               not any(e.get("size_str") is not None and e.get("ext") is not None
                                       for e in prev_data if e.get("type") == "folder"):
                                # Check if parent was a grid view by looking at meta
                                from core.menu_loader import _read_meta
                                parent_meta = _read_meta(prev_dir) if prev_dir else {}
                                if parent_meta.get("view") == "grid":
                                    grid_entries        = prev_data
                                    selected_grid_index = prev_sel
                                    current_dir         = prev_dir
                                    current_dir_name    = prev_name
                                    state = STATE_GRID_VIEW
                                    grid_dirty = True
                                else:
                                    current_dir         = prev_dir
                                    current_dir_name    = prev_name
                                    list_entries        = prev_data
                                    selected_list_index = prev_sel
                                    list_scroll         = prev_scr
                                    state = STATE_LIST_VIEW
                                    list_dirty = True
                            else:
                                current_dir         = prev_dir
                                current_dir_name    = prev_name
                                list_entries        = prev_data
                                selected_list_index = prev_sel
                                list_scroll         = prev_scr
                                state = STATE_LIST_VIEW
                                list_dirty = True
                            logging.info("Back to: %s", current_dir_name)
                        else:
                            state = STATE_MAIN_MENU
                            menu_dirty = True

                    elif event in ("UP", "DOWN"):
                        if list_entries:
                            max_rows = (hw.H - 26 - 18) // 30
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
                                nav_stack.append((
                                    current_dir, current_dir_name,
                                    list_entries, selected_list_index, list_scroll,
                                ))
                                current_dir      = item["path"]
                                current_dir_name = item["display_name"]
                                list_entries     = load_list_entries(current_dir, ICONS_DIR)
                                selected_list_index = 0
                                list_scroll = 0
                                list_dirty  = True
                                logging.info("Enter subfolder: %s", current_dir_name)
                            elif item["type"] == "app":
                                try:
                                    with open(item["path"], "r", encoding="utf-8") as f:
                                        meta = json.load(f)
                                except Exception as e:
                                    logging.warning("Failed to read app meta: %s", e)
                                    continue
                                module_name = meta.get("module")
                                if module_name:
                                    app = load_app(module_name, hw, fonts, monitor)
                                    if app is not None:
                                        current_app = app
                                        current_app_module = module_name
                                        if hasattr(current_app, "on_enter"):
                                            current_app.on_enter()
                                        state = STATE_APP
                                    else:
                                        logging.warning("Failed to init app: %s", module_name)
                                elif meta.get("exec"):
                                    console_lines, console_scroll = run_app(item)
                                    state = STATE_CONSOLE
                                    console_dirty = True
                            elif item["type"] == "file":
                                info_lines  = get_entry_info(item)
                                info_scroll = 0
                                info_dirty  = True
                                state = STATE_INFO

                    elif event == "KEY2":
                        entry_type = None
                        if list_entries:
                            entry_type = list_entries[selected_list_index]["type"]
                        current_options = build_options(
                            entry_type=entry_type,
                            has_clipboard=clipboard is not None,
                        )
                        selected_option_index = 0
                        options_dirty = True
                        state = STATE_OPTIONS_MENU

                # ── Options menu ──────────────────────────────
                elif state == STATE_OPTIONS_MENU:
                    if event == "KEY3":
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    elif event in ("UP", "DOWN"):
                        max_idx = len(current_options) - 1
                        if event == "UP" and selected_option_index > 0:
                            selected_option_index -= 1
                            options_dirty = True
                        elif event == "DOWN" and selected_option_index < max_idx:
                            selected_option_index += 1
                            options_dirty = True
                    elif event == "CENTER":
                        choice = current_options[selected_option_index]

                        if choice == OPT_BACK:
                            state = STATE_LIST_VIEW
                            list_dirty = True

                        elif choice == OPT_CREATE_FOLDER:
                            if current_dir:
                                keyboard_mode   = KB_MODE_NEW_FOLDER
                                keyboard_target = None
                                keyboard.start("New folder", initial_text="", max_len=64)
                                state = STATE_KEYBOARD
                                keyboard_dirty = True

                        elif choice == OPT_DELETE:
                            if list_entries:
                                delete_entry(list_entries[selected_list_index])
                                list_entries = load_list_entries(current_dir, ICONS_DIR)
                                selected_list_index = min(
                                    selected_list_index, max(0, len(list_entries) - 1)
                                )
                                list_scroll = min(list_scroll, selected_list_index)
                            state = STATE_LIST_VIEW
                            list_dirty = True

                        elif choice == OPT_RENAME:
                            if list_entries:
                                keyboard_mode   = KB_MODE_RENAME
                                keyboard_target = list_entries[selected_list_index]
                                keyboard.start(
                                    "Rename",
                                    initial_text=keyboard_target["display_name"],
                                    max_len=64
                                )
                                state = STATE_KEYBOARD
                                keyboard_dirty = True
                            else:
                                state = STATE_LIST_VIEW
                                list_dirty = True

                        elif choice == OPT_COPY:
                            if list_entries:
                                clipboard = copy_entry(list_entries[selected_list_index])
                            state = STATE_LIST_VIEW
                            list_dirty = True

                        elif choice == OPT_PASTE:
                            if clipboard and current_dir:
                                paste_clipboard(clipboard, current_dir)
                                list_entries = load_list_entries(current_dir, ICONS_DIR)
                                list_dirty = True
                            state = STATE_LIST_VIEW

                        elif choice == OPT_INFO:
                            if list_entries:
                                info_lines  = get_entry_info(
                                    list_entries[selected_list_index]
                                )
                                info_scroll = 0
                                info_dirty  = True
                                state = STATE_INFO
                            else:
                                state = STATE_LIST_VIEW
                                list_dirty = True

                # ── Background tasks screen ──────────────────
                elif state == STATE_BG_TASKS:
                    tasks = bgm.active_tasks()
                    if event == "KEY3":
                        state = STATE_SCREENSAVER
                    elif event in ("UP", "DOWN") and tasks:
                        if event == "UP" and selected_bg_index > 0:
                            selected_bg_index -= 1
                        elif event == "DOWN" and selected_bg_index < len(tasks) - 1:
                            selected_bg_index += 1
                    elif event == "CENTER" and tasks:
                        # Re-enter the selected background app
                        name = tasks[selected_bg_index]
                        instance = bgm.get_instance_by_module(
                            bgm.get_task_info(name).get("module", "")
                        )[1]
                        if instance is not None:
                            current_app = instance
                            state = STATE_APP
                    elif event == "KEY1" and tasks:
                        # Stop selected background task
                        name = tasks[selected_bg_index]
                        bgm.stop(name)
                        selected_bg_index = 0
                        if not bgm.has_active():
                            state = STATE_SCREENSAVER

                # ── Info screen ───────────────────────────────
                elif state == STATE_INFO:
                    if event == "KEY3":
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    elif event == "UP" and info_scroll > 0:
                        info_scroll -= 1
                        info_dirty = True
                    elif event == "DOWN" and info_scroll < max(0, len(info_lines) - 1):
                        info_scroll += 1
                        info_dirty = True

                # ── Keyboard ──────────────────────────────────
                elif state == STATE_KEYBOARD:
                    if event == "KEY3":
                        keyboard_mode   = None
                        keyboard_target = None
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    elif event == "KEY1":
                        keyboard.cycle_language()
                        keyboard_dirty = True
                    elif event == "KEY2":
                        _apply_keyboard_result(
                            keyboard_mode, keyboard_target, keyboard.text, current_dir
                        )
                        list_entries = load_list_entries(current_dir, ICONS_DIR) if current_dir else []
                        selected_list_index = min(
                            selected_list_index, max(0, len(list_entries) - 1)
                        )
                        list_scroll     = min(list_scroll, selected_list_index)
                        keyboard_mode   = None
                        keyboard_target = None
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    else:
                        action, text = keyboard.handle_event(event)
                        if action == "redraw":
                            keyboard_dirty = True
                        elif action == "done":
                            _apply_keyboard_result(
                                keyboard_mode, keyboard_target, text, current_dir
                            )
                            list_entries = load_list_entries(current_dir, ICONS_DIR) if current_dir else []
                            selected_list_index = min(
                                selected_list_index, max(0, len(list_entries) - 1)
                            )
                            list_scroll     = min(list_scroll, selected_list_index)
                            keyboard_mode   = None
                            keyboard_target = None
                            state = STATE_LIST_VIEW
                            list_dirty = True

                # ── Console ───────────────────────────────────
                elif state == STATE_CONSOLE:
                    if event == "KEY3":
                        state = STATE_LIST_VIEW
                        list_dirty = True
                    elif event == "UP" and console_scroll > 0:
                        console_scroll -= 1
                        console_dirty = True
                    elif event == "DOWN" and console_scroll < max(0, len(console_lines) - 1):
                        console_scroll += 1
                        console_dirty = True

            # ── Idle timeout → screensaver ────────────────────
            if state not in (STATE_SCREENSAVER, STATE_DIMMED) and                     (now - last_input_time) > IDLE_TIMEOUT:
                state = STATE_SCREENSAVER

            # ── Screen timeout → backlight off ────────────────
            if not screen_is_dimmed and                     (now - last_input_time) > SCREEN_TIMEOUT:
                hw.backlight(0)
                screen_is_dimmed = True
                state = STATE_DIMMED

            # ── Draw ──────────────────────────────────────────
            if state == STATE_DIMMED:
                pass  # Screen is off, nothing to draw

            elif state == STATE_SCREENSAVER:
                if now - last_clock_draw >= 1.0:
                    draw_screensaver(hw, fonts, wifi_icons, bt_icons, status, eth_icon)
                    last_clock_draw = now

            elif state == STATE_MAIN_MENU:
                if menu_dirty:
                    draw_main_menu(hw, fonts, root_entries, selected_root_index)
                    menu_dirty = False

            elif state == STATE_GRID_VIEW:
                if grid_dirty:
                    # Reuse draw_main_menu with grid_entries and a custom title
                    draw_main_menu(hw, fonts, grid_entries, selected_grid_index,
                                   title=current_dir_name)
                    grid_dirty = False

            elif state == STATE_LIST_VIEW:
                if list_dirty:
                    clip_name = clipboard["name"] if clipboard else ""
                    draw_list_view(
                        hw, fonts, list_entries,
                        selected_list_index, list_scroll,
                        current_dir_name, clip_name
                    )
                    list_dirty = False

            elif state == STATE_OPTIONS_MENU:
                if options_dirty:
                    clip_name = clipboard["name"] if clipboard else ""
                    draw_options_menu(
                        hw, fonts, current_options,
                        selected_option_index, clip_name
                    )
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

            elif state == STATE_BG_TASKS:
                _draw_bg_tasks(hw, fonts, bgm, selected_bg_index)

            elif state == STATE_INFO:
                if info_dirty:
                    entry_name = ""
                    if list_entries:
                        entry_name = list_entries[selected_list_index]["display_name"]
                    draw_info_view(hw, fonts, info_lines, info_scroll, entry_name)
                    info_dirty = False

            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        bgm.stop_all()
        hw.clear()
        logging.info("Exit — all background tasks stopped")


if __name__ == "__main__":
    main()
