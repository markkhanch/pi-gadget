# architecture

## Directory layout

```
pi-gadget/
├── main.py                  # Main event loop and state machine
├── install.sh               # Full setup script (apt + pip + systemd + sudoers)
├── requirements.txt         # Python dependencies
├── config.json              # Persistent runtime settings
│
├── apps/                    # All runnable apps
│   ├── loader.py            # Dynamic app loader (import + instantiate)
│   ├── bad_stuff/           # Hacking tools
│   │   ├── recon/           # wardriving, probe_sniffer, handshake, harvester,
│   │   │                    # pmkid_grab, net_intel, cracker
│   │   ├── network/         # arp_spoofer, dns_spoofer, evil_twin
│   │   ├── wireless/        # deauth_bomber, mac_changer
│   │   ├── usb/             # payload (BadUSB / Ducky Script injector)
│   │   ├── exploit/         # (placeholder)
│   │   └── crypto/          # (placeholder)
│   ├── general/             # map (GPS OpenStreetMap viewer)
│   ├── system/              # cpu_ram, device_info, disk, temp
│   └── settings/            # wifi_manager, bluetooth, brightness, ssh,
│                            # screen_timeout, web_ui, usb_mode, datetime, hostname
│
├── core/                    # Hardware abstraction and framework utilities
│   ├── hw.py                # HWDisplay singleton — display, backlight, GPIO pins
│   ├── ST7789.py            # Low-level ST7789 SPI driver
│   ├── input.py             # Button edge-detection (read_buttons)
│   ├── fonts.py             # Font loader (returns font_big, font_small, font_label)
│   ├── menu_loader.py       # Reads menu_fs/, builds entry dicts for grid/list views
│   ├── fs_ops.py            # File browser operations (copy, rename, delete, info)
│   ├── background.py        # BackgroundManager (bgm) — tracks running bg tasks
│   ├── remote_ui.py         # Flask server — live screen streaming + button events
│   ├── monitor.py           # SystemMonitor — sampled CPU/RAM/temp time series
│   ├── status.py            # wlan0/wlan1/BT/GPS status helpers
│   ├── config.py            # config.json read/write helpers
│   ├── console.py           # Console output renderer
│   └── ui_keyboard.py       # On-screen keyboard widget
│
├── ui/                      # Rendering functions (stateless, receive data, draw)
│   ├── screensaver.py       # Clock face + status icon bar
│   ├── main_menu.py         # 3×2 icon grid renderer
│   ├── list_view.py         # Scrollable list renderer
│   ├── options_menu.py      # File operations context menu
│   ├── info_view.py         # File info screen
│   └── helpers.py           # Shared _text_size(), _trunc()
│
├── assets/
│   └── icons/               # 48×48 PNG icons (used in menu grids)
│
├── menu_fs/                 # Virtual filesystem that drives the menu structure
│   ├── 01_hacking/          # Opens as icon grid (view=grid in .meta.json)
│   ├── 02_files/            # File browser root
│   ├── 03_apps/             # General apps
│   ├── 04_system/           # System tools
│   ├── 05_games/             # Games
│   └── 06_settings/         # Settings
│
├── scripts/
│   ├── evil_twin.sh         # hostapd + iptables setup for Evil Twin
│   └── usb_gadget_setup.sh  # USB HID / storage gadget configurator
│
└── tests/                   # Unit tests (pytest)
    ├── test_background.py
    ├── test_fs_ops.py
    ├── test_menu_loader.py
    └── test_ui_helpers.py
```

***

## Layers

### core/ — hardware abstraction

`HWDisplay` is the central singleton. All apps receive it as `hw`. It exposes:

```python
hw.show(pil_img)          # Rotate 270°, push to display, forward frame to RemoteUI
hw.backlight(power: int)  # Set backlight duty cycle (0–100)
hw.gpio_read(pin)         # Read a GPIO pin state
hw.pins                   # Dict: {"UP": pin, "DOWN": pin, ..., "KEY3": pin}
hw.W, hw.H                # Display dimensions (240, 240)
hw._remote                # RemoteUI instance or None
hw._remote_queue          # Queue of button events from browser
```

Every `hw.show()` call is intercepted by `_DisplayProxy` inside `hw.py`, which automatically forwards the frame to RemoteUI if it is running.

### apps/ — modular app system

Each app lives in its own package directory with an `app.py` containing a class whose name ends in `App`. Apps receive `hw`, `fonts`, and `monitor` at construction.

Required interface:

```python
class MyApp:
    def __init__(self, hw, fonts, monitor=None): ...
    def on_enter(self): ...     # Called when app is launched
    def on_exit(self): ...      # Called on normal exit (not background)
    def on_event(self, event) -> str: ...  # Returns "exit", "background", or "stay"
    def update(self, dt): ...   # Called every frame (dt = elapsed seconds)
    def draw(self): ...         # Render and call hw.show(img)
```

### menu\_fs/ — filesystem-driven menu

The menu structure is defined entirely by the filesystem. `menu_loader.py` reads it and builds Python dicts that the UI renders.

Each directory can have a `.meta.json` that controls how it appears:

```json
{
  "display_name": "Hacking",
  "icon": "bad_stuff.png",
  "view": "grid"
}
```

Apps are defined by `.app` files (JSON):

```json
{
  "display_name": "Probe Sniffer",
  "icon": "recon.png",
  "module": "bad_stuff.recon.probe_sniffer",
  "sort_priority": 3
}
```

`sort_priority` controls the order within a folder (lower = first).

***

## State machine

`main.py` runs a single `while True` loop. The current `state` string determines which event handlers and draw functions are active. State transitions happen by assigning a new string to `state`.

```
STATE_SCREENSAVER  ←──── idle timeout
STATE_MAIN_MENU
STATE_GRID_VIEW
STATE_LIST_VIEW    ──── CENTER on .app → STATE_APP
STATE_APP          ──── on_event returns "exit"       → STATE_LIST_VIEW
                   ──── on_event returns "background" → STATE_LIST_VIEW (app stays alive)
STATE_OPTIONS_MENU
STATE_KEYBOARD
STATE_CONSOLE
STATE_INFO
STATE_BG_TASKS
STATE_DIMMED       ──── any button → STATE_SCREENSAVER
```

***

## config.json

Runtime settings are persisted in `config.json` at the project root. Keys used by the framework:

| Key              | Type        | Description                                |
| ---------------- | ----------- | ------------------------------------------ |
| `brightness`     | int (0–100) | Display backlight duty cycle               |
| `idle_timeout`   | float       | Seconds of inactivity before screensaver   |
| `screen_timeout` | float       | Seconds of inactivity before backlight off |
| `hostname`       | string      | Device hostname                            |
| `usb_mode`       | string      | `"keyboard"` or `"storage"`                |

Apps read and write `config.json` using `core/config.py` helpers.
