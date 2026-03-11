# background manager

`core/background.py` provides `bgm` — a global singleton that tracks apps running in the background (e.g. Probe Sniffer, Harvester, PMKID Grab while you navigate menus).

## What problem it solves

Some apps run long-running subprocesses (airodump-ng, hcxdumptool, tcpdump). When the user presses K3 to go back to the menu, the app should continue running. Without a registry, the framework has no way to know what is running, re-attach to it, or stop it cleanly.

`bgm` solves this by:

1. Storing the live app instance alongside metadata
2. Letting the app loader re-attach to a running instance instead of creating a new one
3. Detecting resource conflicts before a second app tries to grab the same interface
4. Providing the Background Tasks screen with uptime and stop controls

## API

### Register a task

Call this when the attack/session starts, **before** returning `"background"` from `on_event()`:

```python
from core.background import bgm

bgm.register(
    name      = "Probe Sniffer",        # Display name in Background Tasks screen
    resources = ["wlan1_monitor"],       # Hardware resources claimed
    stop_fn   = self._stop,             # Callable — called when bgm.stop(name) runs
    instance  = self,                   # The app instance (for re-attach)
    module    = "bad_stuff.recon.probe_sniffer",  # Module path (for loader re-attach)
)
```

### Unregister

Call this inside `_stop()`, after the subprocess is killed and the interface is restored:

```python
bgm.unregister("Probe Sniffer")
```

### Check for conflicts

Before starting any hardware-intensive session, check if another app already owns the interface:

```python
conflicts = bgm.conflicts_for(["wlan1_monitor"])
if conflicts:
    self._msg = f"Conflict: {conflicts[0]}"
    return  # Abort start
```

### Query active tasks

```python
bgm.has_active()          # bool — any tasks running?
bgm.active_tasks()        # list of task name strings
bgm.uptime("Probe Sniffer")  # int seconds since registration
bgm.get_task_info("Probe Sniffer")  # dict with full task metadata
```

### Stop a task

```python
bgm.stop("Probe Sniffer")   # calls stop_fn(), then unregisters
bgm.stop_all()              # stops all tasks — called on SIGTERM/SIGINT
```

## Resource labels

| Label             | Meaning                                |
| ----------------- | -------------------------------------- |
| `"wlan1_monitor"` | `wlan1` in monitor mode                |
| `"wlan1_inject"`  | `wlan1` doing packet injection         |
| `"wlan0_ap"`      | `wlan0` used as a hostapd access point |

Two apps claiming the same resource will conflict. The conflict checker prevents both from running simultaneously.

## Re-attach flow

{% stepper %}
{% step %}
### First launch

User launches Probe Sniffer from menu\
→ apps/loader.py calls bgm.get\_instance\_by\_module("bad\_stuff.recon.probe\_sniffer")\
→ No instance found → normal import + instantiate + on\_enter()
{% endstep %}

{% step %}
### Backgrounding

User presses K3 while running\
→ on\_event returns "background"\
→ main loop: current\_app = None, state = LIST\_VIEW\
→ bgm still holds the instance, threads keep running
{% endstep %}

{% step %}
### Re-attach

User launches Probe Sniffer again\
→ loader calls bgm.get\_instance\_by\_module(...)\
→ Instance found → returns it directly, skips import\
→ on\_enter() is NOT called (app is already running)\
→ User sees the live running state
{% endstep %}
{% endstepper %}

## Cleanup on exit

`main.py` registers `_cleanup()` with both `atexit` and `signal.SIGTERM` / `SIGINT`:

```python
def _cleanup():
    if bgm.has_active():
        bgm.stop_all()
```

This ensures all subprocesses are killed and interfaces restored even if the main process is killed from the terminal or by systemd.
