"""
core/background.py
Global registry of background tasks.

Stores running app instances so the menu can re-attach
to a running app instead of creating a new one.

Usage in an app:
    from core.background import bgm
    bgm.register("Harvester", ["wlan1_monitor"], self._stop_session,
                 instance=self, module="bad_stuff.recon.harvester")
    bgm.unregister("Harvester")
    return "background"
"""

import time

RESOURCE_LABELS = {
    "wlan1_monitor": "Alfa monitor mode",
    "wlan1_inject":  "Alfa packet injection",
    "wlan0_ap":      "Wi-Fi access point",
}


class BackgroundManager:
    def __init__(self):
        self._tasks: dict = {}

    def register(self, name: str, resources: list, stop_fn,
                 instance=None, module: str = ""):
        self._tasks[name] = {
            "resources":  resources,
            "stop_fn":    stop_fn,
            "started_at": time.time(),
            "instance":   instance,
            "module":     module,
        }

    def unregister(self, name: str):
        self._tasks.pop(name, None)

    def has_active(self) -> bool:
        return bool(self._tasks)

    def active_tasks(self) -> list:
        return list(self._tasks.keys())

    def conflicts_for(self, resources: list) -> list:
        wanted = set(resources)
        return [
            name for name, info in self._tasks.items()
            if wanted & set(info["resources"])
        ]

    def get_instance_by_module(self, module: str):
        for name, info in self._tasks.items():
            if info.get("module") == module:
                return name, info["instance"]
        return None, None

    def get_task_info(self, name: str) -> dict:
        return dict(self._tasks.get(name, {}))

    def stop(self, name: str):
        task = self._tasks.get(name)
        if task and callable(task.get("stop_fn")):
            try:
                task["stop_fn"]()
            except Exception:
                pass
        self.unregister(name)

    def stop_all(self):
        for name in list(self._tasks.keys()):
            self.stop(name)

    def uptime(self, name: str) -> int:
        task = self._tasks.get(name)
        if not task:
            return 0
        return int(time.time() - task["started_at"])


bgm = BackgroundManager()
