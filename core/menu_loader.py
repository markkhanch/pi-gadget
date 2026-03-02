"""
core/menu_loader.py
Load menu entries from menu_fs filesystem.
Supports two folder view types:
  "list" (default) — scrollable list with file details
  "grid"           — icon grid like the main menu (set in .meta.json)
"""

import os
import json
import logging
from PIL import Image

FOLDER_ICON_NAME  = "folder.png"
APP_DEFAULT_ICON  = "app_default.png"

FILE_ICONS = {
    ".csv":  "file_csv.png",
    ".gpx":  "file_gpx.png",
    ".html": "file_html.png",
    ".ds":   "file_ds.png",
    ".txt":  "file_txt.png",
    ".json": "file_json.png",
    ".log":  "file_log.png",
    ".jsonl":"file_log.png",
    ".py":   "file_py.png",
    ".sh":   "file_sh.png",
}
FILE_ICON_FALLBACK = "file_generic.png"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n // 1024}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _load_icon(icons_dir: str, name: str, fallback: str) -> Image.Image:
    for candidate in [name, fallback, APP_DEFAULT_ICON]:
        path = os.path.join(icons_dir, candidate)
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (48, 48), (255, 255, 255, 255))


def _read_meta(dir_path: str) -> dict:
    """Read .meta.json from a directory, return empty dict on failure."""
    meta_path = os.path.join(dir_path, ".meta.json")
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning("Failed to read meta in %s: %s", dir_path, e)
        return {}


def load_root_menu_entries(menu_fs_dir: str, icons_dir: str) -> list:
    """
    Scan menu_fs root for top-level folders.
    Returns up to 6 entries for the main menu grid.
    Each entry includes a 'view' field ("grid" or "list").
    """
    entries = []
    if not os.path.isdir(menu_fs_dir):
        logging.warning("menu_fs_dir does not exist: %s", menu_fs_dir)
        return entries

    for name in sorted(os.listdir(menu_fs_dir)):
        full = os.path.join(menu_fs_dir, name)
        if not os.path.isdir(full):
            continue

        meta          = _read_meta(full)
        display_name  = meta.get("display_name", name)
        icon_name     = meta.get("icon", APP_DEFAULT_ICON)
        visible       = bool(meta.get("visible", True))
        sort_priority = meta.get("sort_priority", 9999)
        view          = meta.get("view", "list")

        if not visible:
            continue

        entries.append({
            "path":          full,
            "display_name":  display_name,
            "icon_name":     icon_name,
            "icon_image":    _load_icon(icons_dir, icon_name, APP_DEFAULT_ICON),
            "sort_priority": sort_priority,
            "view":          view,
        })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries[:6]


def load_grid_entries(dir_path: str, icons_dir: str) -> list:
    """
    Load subfolders and .app files for GRID_VIEW.
    Returns up to 6 entries, same format as load_root_menu_entries.
    Used when a folder has "view": "grid" in its .meta.json.
    """
    entries = []
    if not os.path.isdir(dir_path):
        return entries

    for name in sorted(os.listdir(dir_path)):
        if name.startswith("."):
            continue

        full = os.path.join(dir_path, name)

        if os.path.isdir(full):
            meta          = _read_meta(full)
            display_name  = meta.get("display_name", name)
            icon_name     = meta.get("icon", FOLDER_ICON_NAME)
            visible       = bool(meta.get("visible", True))
            sort_priority = meta.get("sort_priority", 5000)
            view          = meta.get("view", "list")

            if not visible:
                continue

            entries.append({
                "type":          "folder",
                "path":          full,
                "display_name":  display_name,
                "icon_name":     icon_name,
                "icon_image":    _load_icon(icons_dir, icon_name, FOLDER_ICON_NAME),
                "sort_priority": sort_priority,
                "view":          view,
            })

        elif name.endswith(".app"):
            display_name  = os.path.splitext(name)[0]
            icon_name     = APP_DEFAULT_ICON
            sort_priority = 9000
            try:
                with open(full, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                display_name  = meta.get("name", display_name)
                icon_name     = meta.get("icon", icon_name)
                sort_priority = meta.get("sort_priority", sort_priority)
            except Exception as e:
                logging.warning("Failed to read .app for %s: %s", full, e)

            entries.append({
                "type":          "app",
                "path":          full,
                "display_name":  display_name,
                "icon_name":     icon_name,
                "icon_image":    _load_icon(icons_dir, icon_name, APP_DEFAULT_ICON),
                "sort_priority": sort_priority,
                "view":          "list",
            })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries[:6]


def load_list_entries(dir_path: str, icons_dir: str) -> list:
    """
    Load directory contents for LIST_VIEW.
    Returns folders, .app files, and regular files.
    """
    entries = []
    if not os.path.isdir(dir_path):
        return entries

    for name in sorted(os.listdir(dir_path)):
        if name.startswith("."):
            continue

        full = os.path.join(dir_path, name)

        # ── Folders ──────────────────────────────────────────
        if os.path.isdir(full):
            meta          = _read_meta(full)
            display_name  = meta.get("display_name", name)
            icon_name     = meta.get("icon", FOLDER_ICON_NAME)
            visible       = bool(meta.get("visible", True))
            sort_priority = meta.get("sort_priority", 5000)
            view          = meta.get("view", "list")

            if not visible:
                continue

            try:
                item_count = sum(
                    1 for n in os.listdir(full) if not n.startswith(".")
                )
                size_str = f"{item_count} item{'s' if item_count != 1 else ''}"
            except Exception:
                size_str = ""

            entries.append({
                "type":          "folder",
                "path":          full,
                "display_name":  display_name,
                "icon_image":    _load_icon(icons_dir, icon_name, FOLDER_ICON_NAME),
                "sort_priority": sort_priority,
                "size_str":      size_str,
                "ext":           "",
                "view":          view,
            })

        # ── .app files ────────────────────────────────────────
        elif name.endswith(".app"):
            display_name  = os.path.splitext(name)[0]
            icon_name     = APP_DEFAULT_ICON
            sort_priority = 9000
            try:
                with open(full, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                display_name  = meta.get("name", display_name)
                icon_name     = meta.get("icon", icon_name)
                sort_priority = meta.get("sort_priority", sort_priority)
            except Exception as e:
                logging.warning("Failed to read .app meta for %s: %s", full, e)

            entries.append({
                "type":          "app",
                "path":          full,
                "display_name":  display_name,
                "icon_image":    _load_icon(icons_dir, icon_name, APP_DEFAULT_ICON),
                "sort_priority": sort_priority,
                "size_str":      "",
                "ext":           ".app",
                "view":          "list",
            })

        # ── Regular files ─────────────────────────────────────
        else:
            ext      = os.path.splitext(name)[1].lower()
            icon_nm  = FILE_ICONS.get(ext, FILE_ICON_FALLBACK)
            try:
                size_str = _fmt_size(os.path.getsize(full))
            except Exception:
                size_str = ""

            entries.append({
                "type":          "file",
                "path":          full,
                "display_name":  name,
                "icon_image":    _load_icon(icons_dir, icon_nm, FILE_ICON_FALLBACK),
                "sort_priority": 7000,
                "size_str":      size_str,
                "ext":           ext,
                "view":          "list",
            })

    entries.sort(key=lambda e: (e["sort_priority"], e["display_name"].lower()))
    return entries
