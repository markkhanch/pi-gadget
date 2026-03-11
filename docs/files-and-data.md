# files and data

All captured data is stored under `menu_fs/02_files/` and is accessible via the **Files** section of the main menu. The file browser lets you view, rename, copy, delete, and get info on any file.

***

## Directory layout

```
menu_fs/02_files/
├── handshakes/      ← WPA2 .pcap and .pcapng capture files
├── wardriving/      ← WiGLE CSV and GPX export files
├── cracked/         ← Passwords cracked by WPA2 Cracker
├── probe_sniffs/    ← Probe Sniffer result text files
├── arp_spoof/       ← tcpdump .pcap captures from ARP Spoofer sessions
├── wordlists/       ← Wordlist files for hashcat (add your own here)
└── payloads/        ← Ducky Script .ds payload files
└── portals/         ← HTML captive portal pages for Evil Twin
```

***

## Per-app output

| App               | Output location | Format                    |
| ----------------- | --------------- | ------------------------- |
| Wardriving        | `wardriving/`   | `*.csv` (WiGLE), `*.gpx`  |
| Handshake Capture | `handshakes/`   | `*.pcap`                  |
| PMKID Grab        | `handshakes/`   | `*.pcapng`                |
| Probe Sniffer     | `probe_sniffs/` | `probes_<timestamp>.txt`  |
| Harvester         | `handshakes/`   | `*.pcap`                  |
| WPA2 Cracker      | `cracked/`      | `cracked_<timestamp>.txt` |
| ARP Spoofer       | `arp_spoof/`    | `arp_<timestamp>.pcap`    |

***

## File browser operations

In any list view, press **K2** to open the options menu:

| Option        | Action                                                  |
| ------------- | ------------------------------------------------------- |
| Create Folder | On-screen keyboard → new subfolder in current directory |
| Delete        | Remove selected file or folder                          |
| Rename        | On-screen keyboard → rename in place                    |
| Copy          | Copy selected item to clipboard                         |
| Paste         | Paste clipboard item into current directory             |
| Info          | Show file name, size, modification date                 |

***

## Copying files off the device

{% hint style="info" %}
Via SSH (easiest)
{% endhint %}

```bash
scp pi@<device-ip>:/home/pi/pi-gadget/menu_fs/02_files/handshakes/*.pcap ./
```

{% stepper %}
{% step %}
### Via USB storage mode

1. **Settings → USB Mode → Storage**
2. Connect the Pi USB data port to a computer
3. The device mounts as a USB flash drive
4. Copy files normally
5. Eject from the computer, then switch back to Keyboard mode if needed
{% endstep %}

{% step %}
### Via WebUI

The current WebUI does not include a file download feature. Use SSH or USB storage mode.
{% endstep %}
{% endstepper %}

***

## Adding wordlists

Place `.txt` wordlist files in `menu_fs/02_files/wordlists/`. They appear in the WPA2 Cracker file picker automatically. Common sources:

* `rockyou.txt` (standard, \~14M passwords)
* Custom target-specific wordlists
* CeWL-generated wordlists from target websites

The Pi Zero 2W has limited processing speed. For large wordlists (>1M entries), crack on a desktop GPU by copying the `.pcapng` file off the device.
