# apps wireless usb

***

## Deauth Bomber

**Module:** `bad_stuff.wireless.deauth_bomber`

Sends 802.11 deauthentication frames to disconnect clients from a target access point.

**What it does:**

* Scans for APs using `airodump-ng` with CSV output
* User selects a target AP from the discovered list
* Runs `mdk4 <iface> d -B <bssid>` to continuously send deauth frames on the target's channel

**Flow:**

```
SCAN → airodump-ng discovers APs, populates list
SELECT → user picks AP from scrollable list
RUNNING → mdk4 d mode active against target BSSID
```

**Controls:**

| State   | Input     | Action                            |
| ------- | --------- | --------------------------------- |
| SCAN    | —         | Automatic, wait for APs to appear |
| SELECT  | UP / DOWN | Scroll AP list                    |
| SELECT  | CENTER    | Confirm target, start attack      |
| RUNNING | K3        | Stop and exit                     |

**Notes:**

* Uses `mdk4` tool (installed by `install.sh`).
* **802.11w / Protected Management Frames (PMF):** Networks with PMF enabled are immune to deauthentication. This includes most enterprise networks, university networks, and modern home routers with WPA3 or PMF-required mode. The deauth frames are sent but clients ignore them.
* A single Wi-Fi adapter can only be on one channel at a time. The adapter tunes to the target AP's channel — all other channels are ignored.
* Channel hopping is not performed during an attack.

***

## MAC Changer

**Module:** `bad_stuff.wireless.mac_changer`

Spoofs the MAC address of any network interface.

**What it does:**

* Lists available network interfaces
* Lets user select an interface
* Generates a random locally-administered MAC or accepts a custom one
* Applies the change with `ip link set <iface> down` → `ip link set <iface> address <mac>` → `ip link set <iface> up`

**Controls:**

| State        | Input     | Action                                 |
| ------------ | --------- | -------------------------------------- |
| SELECT IFACE | UP / DOWN | Select interface                       |
| SELECT IFACE | CENTER    | Confirm, choose MAC                    |
| ENTER MAC    | keyboard  | Type custom MAC or press K1 for random |
| CONFIRM      | CENTER    | Apply                                  |
| DONE         | K3        | Exit                                   |

**Notes:**

* Changes are not persistent across reboots. The original MAC is restored when the interface resets.
* Some drivers do not support MAC spoofing — the command may fail silently.

***

## USB Payloads (BadUSB)

**Module:** `bad_stuff.usb.payload`

Injects keystrokes into a connected computer using USB HID gadget mode. The Pi emulates a USB keyboard.

**What it does:**

* Reads Ducky Script 3.0 payload files from `menu_fs/02_files/payloads/`
* Parses and executes commands via `ducky.py`, a custom Ducky Script interpreter
* Sends keystrokes through the USB HID interface (`/dev/hidg0`) set up by `usb_gadget_setup.sh`

**Included payloads:**

| File                       | What it does                             |
| -------------------------- | ---------------------------------------- |
| `demo_variables.ds`        | Demonstrates Ducky Script variable usage |
| `login_form.ds`            | Opens a browser and fills a login form   |
| `open_terminal_windows.ds` | Opens a terminal on Windows              |
| `quick_password.ds`        | Types a predefined string                |

**Controls:**

| State   | Input     | Action               |
| ------- | --------- | -------------------- |
| SELECT  | UP / DOWN | Browse payload files |
| SELECT  | CENTER    | Run selected payload |
| RUNNING | K3        | Cancel / exit        |

**Adding payloads:**

Place `.ds` files in `menu_fs/02_files/payloads/`. They appear in the list automatically.

**Ducky Script 3.0 supported commands (partial):**

```
STRING <text>        Type text as keystrokes
DELAY <ms>           Wait in milliseconds
ENTER
GUI r                Windows key + R (Run dialog)
CTRL ALT DELETE
VAR $name = value
IF ($var == value)   Conditional blocks
REPEAT <n>           Repeat previous line n times
```

**Setup requirement:**

USB HID gadget mode must be configured first. Run **Settings → USB Mode → Keyboard** or run `usb_gadget_setup.sh` manually. The Pi's USB data port must be connected to the target computer before running a payload.
