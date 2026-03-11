# writing an app

## Minimum structure

Every app lives in its own package directory inside `apps/`. The class name must end in `App`.

```
apps/
└── my_category/
    └── my_app/
        ├── __init__.py   (empty)
        └── app.py
```

### app.py skeleton

```python
"""
apps/my_category/my_app/app.py
One-line description of what this app does.

Controls:
  IDLE:    CTR:start  K3:exit
  RUNNING: K1:action  UP/DOWN:scroll  K3:background
"""

from PIL import Image, ImageDraw
from core.background import bgm

APP_NAME  = "My App"
RESOURCES = []   # e.g. ["wlan1_monitor"], ["wlan1_inject"]

# Color palette (keep consistent with other apps)
BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEP    = (25,  45,  75)
WHITE  = (220, 235, 255)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
GREEN  = (50,  220, 120)
RED    = (255, 70,  70)
CYAN   = (0,   210, 255)
ORANGE = (255, 140, 30)

TOP_H = 26   # Header height in pixels
BOT_H = 18   # Hint bar height in pixels

STATE_IDLE    = "idle"
STATE_RUNNING = "running"


class MyApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.state  = STATE_IDLE
        self._dirty = True

    def on_enter(self):
        """Called once when the app is launched from the menu."""
        self.state  = STATE_IDLE
        self._dirty = True

    def on_exit(self):
        """Called on clean exit (K3 from idle, or result='exit')."""
        self._stop()

    def on_event(self, event: str) -> str:
        """
        Handle a button event. Must return one of:
          "exit"       — app exits, on_exit() is called, menu resumes
          "background" — app keeps running, on_exit() is NOT called
          "stay"       — no state change
        """
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER":
                self._start()
        elif self.state == STATE_RUNNING:
            if event == "KEY3":
                return "background"   # go to bg, app stays alive
        return "stay"

    def update(self, dt: float):
        """Called every frame. dt = seconds since last frame (~0.05 s)."""
        pass

    def draw(self):
        """Render the current frame and push it to the display."""
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # Header bar
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               APP_NAME, font=self.font_label, fill=CYAN)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP, width=1)

        # Body content
        # ...

        # Hint bar
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hint = "CTR:start  K3:exit"
        b = d.textbbox((0, 0), hint, font=self.font_label)
        hw2 = b[2] - b[0]
        d.text(((W - hw2) // 2, H - (b[3] - b[1]) - 2),
               hint, font=self.font_label, fill=HINT)

        self.hw.show(img)

    # ── Private ───────────────────────────────────────────────

    def _start(self):
        """Start the attack / session."""
        # Check for resource conflicts before touching hardware
        conflicts = bgm.conflicts_for(RESOURCES)
        if conflicts:
            return  # Another app is already using this resource

        self.state  = STATE_RUNNING
        self._dirty = True

        # Register with BackgroundManager
        bgm.register(APP_NAME, RESOURCES, self._stop,
                     instance=self, module="my_category.my_app")

    def _stop(self):
        """Stop the session. Called by bgm.stop() or on_exit()."""
        # Kill subprocesses, restore interfaces, etc.
        bgm.unregister(APP_NAME)
        self.state  = STATE_IDLE
        self._dirty = True
```

***

## Registering in the menu

Create a `.app` file in the appropriate `menu_fs/` subfolder:

```json
{
  "display_name": "My App",
  "icon": "recon.png",
  "module": "my_category.my_app",
  "sort_priority": 5
}
```

The `module` field maps to `apps/<module>/app.py`. `sort_priority` (lower = first) controls the order within the folder.

***

## Background mode

When the user presses K3 while an app is running, the app should return `"background"` from `on_event()`. This tells the state machine to go back to the menu without calling `on_exit()`. The app's threads continue running.

The framework stores the live instance in `BackgroundManager`. Next time the user launches the same app from the menu, `apps/loader.py` detects the running instance and re-attaches to it instead of creating a new one.

```python
# On first launch:       loader creates MyApp instance, calls on_enter()
# After return "background": instance stays in bgm._tasks
# On second launch:      loader finds the same instance, returns it directly
#                        on_enter() is NOT called again
```

The Background Tasks screen (screensaver → K1) lets the user stop background tasks manually.

### Required resource labels

Use these standard labels in the `RESOURCES` list so the conflict checker works correctly:

| Label             | Meaning                             |
| ----------------- | ----------------------------------- |
| `"wlan1_monitor"` | Alfa adapter in monitor mode        |
| `"wlan1_inject"`  | Alfa adapter doing packet injection |
| `"wlan0_ap"`      | Built-in Wi-Fi used as access point |

***

## App loader

`apps/loader.py` imports any module dynamically:

```
module = "bad_stuff.recon.probe_sniffer"
        → import apps.bad_stuff.recon.probe_sniffer.app
        → find class whose name ends in "App"
        → instantiate with (hw, fonts, monitor) or (hw, fonts) as fallback
```

***

## Drawing conventions

* Display size: `hw.W × hw.H` = 240×240 pixels
* Color space: RGB tuples `(r, g, b)` — no alpha in final image
* Always create a fresh `Image.new("RGB", (W, H), BG)` each frame
* Call `self.hw.show(img)` once at the end of `draw()`; the framework handles display rotation and RemoteUI streaming automatically
* Use `self._dirty` flag to skip redundant redraws — only set it to `True` when state actually changes
* Standard layout: header bar (26 px top), hint bar (18 px bottom), body content in between
