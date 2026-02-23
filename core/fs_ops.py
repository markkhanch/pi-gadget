"""
core/fs_ops.py
File operations for menu_fs: creating, deleting, renaming folders and .app files.
Running .app commands via shell.
"""

import os
import json
import shutil
import logging
import subprocess


FOLDER_ICON_NAME = "folder.png"


def sanitize_fs_name(name: str) -> str:
    """Converts user input into a safe file/folder name."""
    name = name.strip().replace(" ", "_")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(ch for ch in name if ch in allowed)


def create_folder_named(current_dir: str, display_name: str):
    """
    Creates a folder from user name + .meta.json inside.
    If name already exists — adds suffix _1, _2, etc.
    """
    display_name = (display_name or "").strip()
    if not display_name:
        logging.info("Empty folder name, skipping create")
        return

    safe_name = sanitize_fs_name(display_name) or "Folder"
    new_path = None

    for i in range(1000):
        candidate = safe_name if i == 0 else f"{safe_name}_{i}"
        path = os.path.join(current_dir, candidate)
        if not os.path.exists(path):
            new_path = path
            break

    if new_path is None:
        logging.warning("Could not create folder, limit reached")
        return

    try:
        os.makedirs(new_path, exist_ok=True)
    except Exception as e:
        logging.warning("Failed to create folder %s: %s", new_path, e)
        return

    meta = {
        "display_name": display_name,
        "icon": FOLDER_ICON_NAME,
        "visible": True,
        "sort_priority": 5000,
    }
    try:
        with open(os.path.join(new_path, ".meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logging.warning("Failed to write folder meta: %s", e)

    logging.info("Created folder: %s (display: %s)", new_path, display_name)


def delete_entry(entry: dict):
    """Deletes folder (recursively) or .app file."""
    path = entry["path"]
    try:
        if entry["type"] == "folder":
            shutil.rmtree(path)
            logging.info("Deleted folder: %s", path)
        elif entry["type"] == "app":
            os.remove(path)
            logging.info("Deleted app: %s", path)
    except Exception as e:
        logging.warning("Failed to delete %s: %s", path, e)


def rename_entry(entry: dict, new_display_name: str):
    """
    Renames folder or .app file.
    Updates display_name in .meta.json / .app.
    Mutates entry dict in place (path and display_name).
    """
    display_name = new_display_name.strip()
    if not display_name:
        logging.info("Empty new name, skipping rename")
        return

    path = entry["path"]
    parent = os.path.dirname(path)

    if entry["type"] == "folder":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            logging.info("Sanitized folder name is empty, skipping rename")
            return

        new_path = os.path.join(parent, safe_name)
        if os.path.exists(new_path):
            for i in range(1, 1000):
                candidate = os.path.join(parent, f"{safe_name}_{i}")
                if not os.path.exists(candidate):
                    new_path = candidate
                    break

        try:
            os.rename(path, new_path)
        except Exception as e:
            logging.warning("Failed to rename folder %s -> %s: %s", path, new_path, e)
            return

        # update .meta.json
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
        logging.info("Renamed folder -> %s (display: %s)", new_path, display_name)

    elif entry["type"] == "app":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            logging.info("Sanitized app name is empty, skipping rename")
            return

        new_path = os.path.join(parent, safe_name + ".app")
        if os.path.exists(new_path):
            for i in range(1, 1000):
                candidate = os.path.join(parent, f"{safe_name}_{i}.app")
                if not os.path.exists(candidate):
                    new_path = candidate
                    break

        try:
            os.rename(path, new_path)
        except Exception as e:
            logging.warning("Failed to rename app %s -> %s: %s", path, new_path, e)
            return

        # update name inside .app
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
        logging.info("Renamed app -> %s (display: %s)", new_path, display_name)


def run_app(entry: dict) -> tuple:
    """
    Runs command from .app file via shell.
    Returns (lines: list[str], scroll: int).
    Does not write to globals — main.py decides what to do with result.
    """
    path = entry["path"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        return ([f"ERROR: cannot read .app: {e}"], 0)

    cmd = meta.get("exec")
    if not cmd:
        return (["ERROR: no 'exec' in .app"], 0)

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

    return (text.splitlines(), 0)