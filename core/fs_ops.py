"""
core/fs_ops.py
File system operations for menu_fs: create, delete, rename, copy, paste.
"""

import os
import json
import shutil
import logging
import subprocess
import datetime

FOLDER_ICON_NAME = "folder.png"


def sanitize_fs_name(name: str) -> str:
    """Convert user input to a safe filename."""
    name    = name.strip().replace(" ", "_")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
    return "".join(ch for ch in name if ch in allowed)


def _unique_path(parent: str, name: str) -> str:
    """Return a path that does not exist yet, appending _1, _2 as needed."""
    base, ext = os.path.splitext(name)
    candidate = os.path.join(parent, name)
    if not os.path.exists(candidate):
        return candidate
    for i in range(1, 1000):
        candidate = os.path.join(parent, f"{base}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise FileExistsError(f"Cannot find unique name for {name} in {parent}")


# ── Create ────────────────────────────────────────────────────

def create_folder_named(current_dir: str, display_name: str):
    """Create a folder with .meta.json inside."""
    display_name = (display_name or "").strip()
    if not display_name:
        return
    safe_name = sanitize_fs_name(display_name) or "Folder"
    try:
        new_path = _unique_path(current_dir, safe_name)
    except FileExistsError:
        logging.warning("Could not create folder, limit reached")
        return
    try:
        os.makedirs(new_path, exist_ok=True)
    except Exception as e:
        logging.warning("Failed to create folder %s: %s", new_path, e)
        return
    meta = {"display_name": display_name, "icon": FOLDER_ICON_NAME,
            "visible": True, "sort_priority": 5000}
    try:
        with open(os.path.join(new_path, ".meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logging.warning("Failed to write folder meta: %s", e)
    logging.info("Created folder: %s (display: %s)", new_path, display_name)


# ── Delete ────────────────────────────────────────────────────

def delete_entry(entry: dict):
    """Delete folder (recursively), .app file, or regular file."""
    path = entry["path"]
    try:
        if entry["type"] == "folder":
            shutil.rmtree(path)
            logging.info("Deleted folder: %s", path)
        else:
            os.remove(path)
            logging.info("Deleted file: %s", path)
    except Exception as e:
        logging.warning("Failed to delete %s: %s", path, e)


# ── Rename ────────────────────────────────────────────────────

def rename_entry(entry: dict, new_display_name: str):
    """
    Rename folder or file.
    Updates display_name in .meta.json / .app.
    Mutates entry dict in-place (path, display_name).
    """
    display_name = new_display_name.strip()
    if not display_name:
        return

    path   = entry["path"]
    parent = os.path.dirname(path)

    if entry["type"] == "folder":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            return
        try:
            new_path = _unique_path(parent, safe_name)
        except FileExistsError:
            return
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
                pass
        meta["display_name"] = display_name
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logging.warning("Failed to write meta after folder rename: %s", e)
        entry["path"]         = new_path
        entry["display_name"] = display_name

    elif entry["type"] == "app":
        safe_name = sanitize_fs_name(display_name)
        if not safe_name:
            return
        try:
            new_path = _unique_path(parent, safe_name + ".app")
        except FileExistsError:
            return
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
            pass
        meta["name"] = display_name
        try:
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logging.warning("Failed to write app meta after rename: %s", e)
        entry["path"]         = new_path
        entry["display_name"] = display_name

    elif entry["type"] == "file":
        # Keep original extension
        ext      = os.path.splitext(entry["path"])[1]
        new_name = sanitize_fs_name(display_name)
        if not new_name:
            return
        # Ensure extension is preserved
        if ext and not new_name.endswith(ext):
            new_name += ext
        try:
            new_path = _unique_path(parent, new_name)
        except FileExistsError:
            return
        try:
            os.rename(path, new_path)
        except Exception as e:
            logging.warning("Failed to rename file %s -> %s: %s", path, new_path, e)
            return
        entry["path"]         = new_path
        entry["display_name"] = os.path.basename(new_path)

    logging.info("Renamed -> %s", entry["path"])


# ── Copy / Paste ──────────────────────────────────────────────

def copy_entry(entry: dict) -> dict:
    """
    Return clipboard dict describing what to copy.
    Does NOT copy yet — paste_clipboard() performs the actual copy.
    """
    return {
        "source_path": entry["path"],
        "type":        entry["type"],
        "name":        os.path.basename(entry["path"]),
    }


def paste_clipboard(clipboard: dict, dest_dir: str) -> bool:
    """
    Copy clipboard item into dest_dir.
    Returns True on success.
    """
    if not clipboard:
        return False

    src  = clipboard["source_path"]
    name = clipboard["name"]

    if not os.path.exists(src):
        logging.warning("Paste: source does not exist: %s", src)
        return False

    try:
        dest = _unique_path(dest_dir, name)
    except FileExistsError:
        logging.warning("Paste: cannot find unique dest for %s", name)
        return False

    try:
        if os.path.isdir(src):
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        logging.info("Pasted %s -> %s", src, dest)
        return True
    except Exception as e:
        logging.warning("Paste failed: %s", e)
        return False


# ── File info ─────────────────────────────────────────────────

def get_entry_info(entry: dict) -> list:
    """
    Return list of (label, value) strings describing an entry.
    Shown in INFO screen.
    """
    path = entry["path"]
    info = [("Name", entry["display_name"])]

    if entry["type"] == "folder":
        try:
            items = [n for n in os.listdir(path) if not n.startswith(".")]
            info.append(("Items", str(len(items))))
            # Total size
            total = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(path)
                for f in files
            )
            info.append(("Size", _fmt_size(total)))
        except Exception:
            pass

    elif entry["type"] == "file":
        try:
            size = os.path.getsize(path)
            info.append(("Size", _fmt_size(size)))
        except Exception:
            pass
        ext = os.path.splitext(path)[1].lower()
        info.append(("Type", ext.lstrip(".").upper() if ext else "File"))

    elif entry["type"] == "app":
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            module = meta.get("module", "")
            if module:
                info.append(("Module", module))
        except Exception:
            pass

    try:
        mtime = os.path.getmtime(path)
        info.append(("Modified", datetime.datetime.fromtimestamp(mtime)
                     .strftime("%Y-%m-%d %H:%M")))
    except Exception:
        pass

    info.append(("Path", path))
    return info


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# ── Run app ───────────────────────────────────────────────────

def run_app(entry: dict) -> tuple:
    """Run exec command from .app file. Returns (lines, scroll)."""
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
