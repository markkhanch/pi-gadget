# controls

## Button map

| Input                   | Event name | Action                                   |
| ----------------------- | ---------- | ---------------------------------------- |
| Joystick UP             | `UP`       | Navigate up in grid / scroll list up     |
| Joystick DOWN           | `DOWN`     | Navigate down in grid / scroll list down |
| Joystick LEFT           | `LEFT`     | Navigate left in grid                    |
| Joystick RIGHT          | `RIGHT`    | Navigate right in grid                   |
| Joystick CENTER (press) | `CENTER`   | Select / confirm / enter                 |
| **K1** (top button)     | `KEY1`     | Context action — varies per app / screen |
| **K2** (middle button)  | `KEY2`     | Options menu (in file browser)           |
| **K3** (bottom button)  | `KEY3`     | Back / Exit                              |

## Screen states

The firmware runs a state machine. The current state determines what is drawn and how inputs are handled.

| State          | Description                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------- |
| `screensaver`  | Clock face with status icons. Any button → main menu. K1 (if background tasks active) → bg tasks screen. |
| `main_menu`    | 3×2 icon grid of top-level sections.                                                                     |
| `grid_view`    | Sub-section icon grid (e.g. Hacking categories).                                                         |
| `list_view`    | Scrollable list of files, folders, and apps.                                                             |
| `app`          | A running app receives all events via `on_event()`.                                                      |
| `options_menu` | Context menu for file operations (rename, delete, copy, paste, info).                                    |
| `keyboard`     | On-screen keyboard for text input.                                                                       |
| `console`      | Output console for shell commands.                                                                       |
| `info`         | File info screen (name, size, date).                                                                     |
| `bg_tasks`     | Background tasks manager.                                                                                |
| `dimmed`       | Screen off (backlight = 0). Only button reads are active — any button wakes the device.                  |

## Navigation flow

{% stepper %}
{% step %}
### Screensaver

* Any button → Main Menu (3×2 grid)
{% endstep %}

{% step %}
### Main Menu

* CENTER → enter section
{% endstep %}

{% step %}
### Entered section

Two possible paths:

* Grid view (e.g. Hacking sub-categories)
  * CENTER → list view of apps
    * CENTER on app → launch app
* List view (Files, System, Settings…)
  * CENTER on app → launch app
  * CENTER on folder → enter folder (nav\_stack push)
  * K3 → back (nav\_stack pop or main menu)
{% endstep %}
{% endstepper %}

Navigation history is stored in `nav_stack`. Each `K3` press pops one level. At depth 0, `K3` returns to main menu.

## Idle timeout & screen dimming

Two timeouts are configured in `config.json`:

| Key              | Default                | Behavior                                          |
| ---------------- | ---------------------- | ------------------------------------------------- |
| `idle_timeout`   | `999999999` (disabled) | After inactivity → screensaver                    |
| `screen_timeout` | `999999999` (disabled) | After inactivity → backlight off (`STATE_DIMMED`) |

When dimmed, the main loop skips all UI drawing and runs only button reads at 10 Hz. The first button press wakes the screen and resets the idle timer.

Both values are configurable via **Settings → Screen Timeout** on the device.

## Background tasks screen

Accessible from the screensaver with **K1** when at least one background task is running.

* **UP / DOWN** — select a task
* **CENTER** — re-enter the selected app (re-attach to running instance)
* **K1** — stop the selected background task
* **K3** — back to screensaver

## On-screen keyboard

Used for renaming files and creating folders.

* **Joystick** — move cursor between keys
* **CENTER** — type the selected character
* **K1** — cycle language / layout
* **K2** — confirm and apply
* **K3** — cancel

## Remote / Web UI controls

When WebUI is enabled, the browser streams the live display and sends button events back to the device. All button names (`UP`, `DOWN`, `CENTER`, `KEY1`, `KEY2`, `KEY3`) are available as clickable buttons in the browser interface.
