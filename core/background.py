"""
core/background.py
Global registry of background tasks.

Apps register when starting a long-running process
and unregister when done.

Usage in an app:
    from core.background import bgm
    bgm.register("Harvester", ["wlan1_monitor"], self._stop_session)
    bgm.unregister("Harvester")
    return "background"  # instead of "exit" to keep running
"""

import time

RESOURCE_LABELS = {
    "wlan1_monitor": "Alfa monitor mode",
    "wlan1_inject":  "Alfa packet injection",
    "wlan0_ap":      "Wi-Fi access point",
}


class BackgroundManager:
    """Singleton registry of active background tasks."""

    def __init__(self):
        self._tasks: dict = {}

    def register(self, name: str, resources: list, stop_fn):
        self._tasks[name] = {
            "resources":  resources,
            "stop_fn":    stop_fn,
            "started_at": time.time(),
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
