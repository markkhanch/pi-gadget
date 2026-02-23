"""
core/menu_loader.py
Loading menu entries from the menu_fs filesystem.
"""

import os
import json
import logging
from PIL import Image


FOLDER_ICON_NAME = "folder.png"
APP_DEFAULT_ICON_NAME = "app_default.png"


def _load_icon_image(icons_dir: str, icon_name: str, fallback_name: str, size=None) -> Image.Image:
    """Loads an icon from icons_dir. On error — fallback, then a white square."""
    path = os.path.join(icons_dir, icon_name)
    try:
        img = Image.open(path).convert("RGBA")
        if size:
            img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        pass

    fallback_path = os.path.join(icons_dir, fallback_name)
    try:
        img = Image.open(fallback_path).convert("RGBA")
        if size:
            img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        s = size or 48
        return Image.new("RGBA", (s, s), (255, 255, 255, 255))


def load_root_menu_entries(menu_fs_dir: str, icons_dir: str) -> list:
    """
    Scans the root of menu_fs, reads .meta.json in each folder.
    Returns up to 6 entries like:
    {
      "path": str,
      "display_name": str,
      "icon_name": str,
      "icon_image": PIL.Image,
      "sort_priority": int
    }
    """
    entries = []

    if not os.path.isdir(menu_fs_dir):
        logging.warning("menu_fs_dir does not exist: %s", menu_fs_dir)
        return entries

    for name in sorted(os.listdir(menu_fs_dir)):
        full = os.path.join(menu_fs_dir, name)
        if not os.path.isdir(full):
            continue

        meta_path = os.path.join(full, ".meta.json")
        display_name = name
        icon_name = APP_DEFAULT_ICON_NAME
        visible = True
        sort_priority = 9999

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                display_name = meta.get("display_name", display_name)
                icon_name = meta.get("icon", icon_name)
                visible = bool(meta.get("visible", True))
                sort_priority = meta.get("sort_priority", sort_priority)
            except Exception as e:
                logging.warning("Failed to read meta for %s: %s", full, e)

        if not visible:
            continue

        icon_img = _load_icon_image(icons_dir, icon_name, APP_DEFAULT_ICON_NAME)

        entries.append({
            "path": full,
            "display_name": display_name,
            "icon_name": icon_name,
            "icon_image": icon_img,
            "sort_priority": sort_priority,
        })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries[:6]


def load_list_entries(dir_path: str, icons_dir: str) -> list:
    """
    Loads folder contents for LIST_VIEW.
    Returns a list of entries like:
    {
      "type": "folder" | "app",
      "path": str,
      "display_name": str,
      "icon_image": PIL.Image,
      "sort_priority": int
    }
    """
    entries = []

    if not os.path.isdir(dir_path):
        return entries

    # --- Folders ---
    for name in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue

        meta_path = os.path.join(full, ".meta.json")
        display_name = name
        icon_name = FOLDER_ICON_NAME
        visible = True
        sort_priority = 5000

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                display_name = meta.get("display_name", display_name)
                icon_name = meta.get("icon", icon_name)
                visible = bool(meta.get("visible", True))
                sort_priority = meta.get("sort_priority", sort_priority)
            except Exception as e:
                logging.warning("Failed to read subfolder meta: %s", e)

        if not visible:
            continue

        icon_img = _load_icon_image(icons_dir, icon_name, FOLDER_ICON_NAME)

        entries.append({
            "type": "folder",
            "path": full,
            "display_name": display_name,
            "icon_image": icon_img,
            "sort_priority": sort_priority,
        })

    # --- .app files ---
    for name in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, name)
        if not os.path.isfile(full) or not name.endswith(".app"):
            continue

        display_name = os.path.splitext(name)[0]
        icon_name = APP_DEFAULT_ICON_NAME
        sort_priority = 9000

        try:
            with open(full, "r", encoding="utf-8") as f:
                meta = json.load(f)
            display_name = meta.get("name", display_name)
            icon_name = meta.get("icon", icon_name)
            sort_priority = meta.get("sort_priority", sort_priority)
        except Exception as e:
            logging.warning("Failed to read .app meta for %s: %s", full, e)

        icon_img = _load_icon_image(icons_dir, icon_name, APP_DEFAULT_ICON_NAME)

        entries.append({
            "type": "app",
            "path": full,
            "display_name": display_name,
            "icon_image": icon_img,
            "sort_priority": sort_priority,
        })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries