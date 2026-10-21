"""
core/settings.py
Single source of truth for reading and writing config.json at the repo root.

Previously every consumer (main.py, remote_ui.py, and several Settings apps)
computed the path with a different number of '..' segments and carried its own
load/save pair — a path/format divergence waiting to bite. Everything now goes
through this module.
"""

import json
import os
import threading

# config.json lives at the repository root, one level above this package.
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.json",
)

_lock = threading.Lock()


def load() -> dict:
    """Return config.json as a dict, or {} if it is missing or unreadable."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(data: dict) -> bool:
    """Write the whole config dict atomically-ish. Returns True on success."""
    try:
        with _lock:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def get(key, default=None):
    """Read a single config key."""
    return load().get(key, default)


def set_key(key, value) -> bool:
    """Update a single key, preserving every other value in the file."""
    cfg = load()
    cfg[key] = value
    return save(cfg)
