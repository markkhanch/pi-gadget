"""
apps/loader.py
App loader — imports module, instantiates *App class.

Before creating a new instance, checks BackgroundManager
for a live instance of the same module. If found, re-attaches
to the running app instead of creating a fresh one.
"""

import importlib
import logging

from core.background import bgm


def load_app(module_name: str, hw, fonts, monitor):
    """
    module_name: 'bad_stuff.recon.harvester' → apps/bad_stuff/recon/harvester/app.py

    If a background task with the same module is already running,
    returns the live instance instead of creating a new one.
    """
    # Re-attach to running background instance if available
    bg_name, bg_instance = bgm.get_instance_by_module(module_name)
    if bg_instance is not None:
        logging.info("Re-attaching to background task: %s", bg_name)
        return bg_instance

    # Normal load path
    try:
        mod = importlib.import_module(f"apps.{module_name}.app")
    except Exception as e:
        logging.warning("Failed to import app module %s: %s", module_name, e)
        return None

    app_cls = None
    for attr in dir(mod):
        if attr.endswith("App"):
            app_cls = getattr(mod, attr)
            break

    if app_cls is None:
        logging.warning("No *App class found in %s", module_name)
        return None

    # Try (hw, fonts, monitor) first, fall back to (hw, fonts)
    try:
        return app_cls(hw, fonts, monitor)
    except TypeError:
        try:
            return app_cls(hw, fonts)
        except Exception as e:
            logging.warning("Failed to instantiate app %s: %s", module_name, e)
            return None
