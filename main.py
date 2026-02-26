#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

from core.menu_loader import load_root_menu_entries, load_list_entries
from core.fs_ops import (
    create_folder_named,
    delete_entry,
    rename_entry,
    run_app,
)

from ui.screensaver import draw_screensaver
from ui.main_menu import draw_main_menu
from ui.list_view import draw_list_view
from ui.options_menu import draw_options_menu, OPTIONS_ITEMS

from apps.loader import load_app
from core.ui_keyboard import OnScreenKeyboard

logging.basicConfig(level=logging.INFO)

# ── Paths ───────────────────────────────────────────────────

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
ICONS_DIR   = os.path.join(ASSETS_DIR, "icons")
MENU_FS_DIR = os.path.join(BASE_DIR, "menu_fs")

WIFI_ON_ICON_PATH  = os.path.join(ICONS_DIR, "wifi_on.png")
WIFI_OFF_ICON_PATH = os.path.join(ICONS_DIR, "wifi_off.png")
BT_ON_ICON_PATH    = os.path.join(ICONS_DIR, "bt_on.png")
BT_OFF_ICON_PATH   = os.path.join(ICONS_DIR, "bt_off.png")
ETH_ICON_PATH      = os.path.join(ICONS_DIR, "ethernet.png")

# ── UI States ───────────────────────────────────────────────

STATE_SCREENSAVER  = "screensaver"
STATE_MAIN_MENU    = "main_menu"
STATE_LIST_VIEW    = "list_view"
STATE_OPTIONS_MENU = "options_menu"
STATE_KEYBOARD     = "keyboard"
STATE_CONSOLE      = "console"
STATE_APP          = "app"

KB_MODE_RENAME     = "rename"
KB_MODE_NEW_FOLDER = "new_folder"

def _load_config() -> dict:
    """Load config.json from project root."""
    cfg_path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}

_cfg         = _load_config()
IDLE_TIMEOUT = float(_cfg.get("idle_timeout", 999999999.0))

# ── Utilities ────────────────────────────────────────────────

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


# ── Main Loop ───────────────────────────────────────────────

def main():
    hw = HWDisplay()
    hw.backlight(int(_cfg.get("brightness", 80)))
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

    # Ethernet icon — None if file not found (function won't crash)
    try:
        eth_icon = load_icon(ETH_ICON_PATH, size=24)
    except Exception:
        eth_icon = None

    root_entries = load_root_menu_entries(MENU_FS_DIR, ICONS_DIR)
    if not root_entries:
        logging.warning("No root menu entries found in %s", MENU_FS_DIR)

    state               = STATE_SCREENSAVER
    selected_root_index = 0

    current_dir         = None
    current_dir_name    = ""
    list_entries        = []
    selected_list_index = 0
    list_scroll         = 0

    current_app        = None
    current_app_module = None
    last_frame_time    = time.time()

    selected_option_index = 0

    keyboard        = OnScreenKeyboard(hw.disp, font_label)
    keyboard_mode   = None
    keyboard_target = None

    console_lines  = []
    console_scroll = 0

    monitor = SystemMonitor(max_points=600, interval=1.0)

    prev_button_states = {name: hw.gpio_read(pin) for name, pin in hw.pins.items()}

    last_input_time = time.time()
    last_clock_draw = 0.0
    menu_dirty      = True
    list_dirty      = True
    options_dirty   = True
    keyboard_dirty  = True
    console_dirty   = True

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

            # Drain remote UI button queue (handled by hw.pop_remote_event via input.py)


            for event in events:
                last_input_time = now
                logging.debug("Input event: %s", event)

                if state == STATE_SCREENSAVER:
                    state = STATE_MAIN_MENU
                    menu_dirty = True

                elif state == STATE_APP:
                    if current_app is not None:
                        result = current_app.on_event(event)
                        if result == "exit":
                            current_app = None
                            current_app_module = None
                            state = STATE_LIST_VIEW
                            list_dirty = True

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
                            current_dir      = entry["path"]
                            current_dir_name = entry["display_name"]
                            list_entries     = load_list_entries(current_dir, ICONS_DIR)
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
                            row_h    = 30
                            max_rows = (hw.H - 30) // row_h
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
                                keyboard_mode   = KB_MODE_NEW_FOLDER
                                keyboard_target = None
                                keyboard.start("New folder", initial_text="", max_len=64)
                                state = STATE_KEYBOARD
                                keyboard_dirty = True
                        elif choice == "Delete":
                            if list_entries:
                                delete_entry(list_entries[selected_list_index])
                                list_entries = load_list_entries(current_dir, ICONS_DIR)
                                selected_list_index = min(selected_list_index, max(0, len(list_entries) - 1))
                                list_scroll = min(list_scroll, selected_list_index)
                            state = STATE_LIST_VIEW
                            list_dirty = True
                        elif choice == "Rename":
                            if list_entries:
                                keyboard_mode   = KB_MODE_RENAME
                                keyboard_target = list_entries[selected_list_index]
                                keyboard.start("Rename", initial_text=keyboard_target["display_name"], max_len=64)
                                state = STATE_KEYBOARD
                                keyboard_dirty = True
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
                        _apply_keyboard_result(keyboard_mode, keyboard_target, keyboard.text, current_dir)
                        list_entries = load_list_entries(current_dir, ICONS_DIR) if current_dir else []
                        selected_list_index = min(selected_list_index, max(0, len(list_entries) - 1))
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
                            _apply_keyboard_result(keyboard_mode, keyboard_target, text, current_dir)
                            list_entries = load_list_entries(current_dir, ICONS_DIR) if current_dir else []
                            selected_list_index = min(selected_list_index, max(0, len(list_entries) - 1))
                            list_scroll = min(list_scroll, selected_list_index)
                            keyboard_mode = None
                            keyboard_target = None
                            state = STATE_LIST_VIEW
                            list_dirty = True

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

            # Idle timeout
            if state != STATE_SCREENSAVER and (now - last_input_time) > IDLE_TIMEOUT:
                state = STATE_SCREENSAVER

            # Render
            if state == STATE_SCREENSAVER:
                if now - last_clock_draw >= 1.0:
                    draw_screensaver(hw, fonts, wifi_icons, bt_icons, status, eth_icon)
                    last_clock_draw = now
            elif state == STATE_MAIN_MENU:
                if menu_dirty:
                    draw_main_menu(hw, fonts, root_entries, selected_root_index)
                    menu_dirty = False
            elif state == STATE_LIST_VIEW:
                if list_dirty:
                    draw_list_view(hw, fonts, list_entries, selected_list_index, list_scroll, current_dir_name)
                    list_dirty = False
            elif state == STATE_OPTIONS_MENU:
                if options_dirty:
                    draw_options_menu(hw, fonts, selected_option_index)
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
        hw.clear()
        logging.info("Exit by KeyboardInterrupt")


if __name__ == "__main__":
    main()
