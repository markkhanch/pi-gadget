import importlib
import logging

def load_app(module_name: str, hw, fonts, monitor):
    """
    module_name: 'system.cpu_ram' → apps/system/cpu_ram/app.py
    monitor: SystemMonitor из core.monitor
    """
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

    # сначала пробуем (hw, fonts, monitor), если класс старый — падаем на (hw, fonts)
    try:
        return app_cls(hw, fonts, monitor)
    except TypeError:
        try:
            return app_cls(hw, fonts)
        except Exception as e:
            logging.warning("Failed to instantiate app %s: %s", module_name, e)
            return None
