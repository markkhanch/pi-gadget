# apps recon

All recon apps live under `apps/bad_stuff/recon/` and appear in the **Hacking → Recon** submenu.

## Wardriving

**Module:** `bad_stuff.recon.wardriving`

Scans for Wi-Fi networks while moving and logs them with GPS coordinates.

What it does:

* Puts `wlan1` into monitor mode
* Runs `airodump-ng --band abg` to capture beacon frames
* Polls a connected GPS dongle via `gpsd` for coordinates
* Logs every unique BSSID with its SSID, channel, signal level, encryption, and lat/lon
* Exports logs as **WiGLE CSV** and **GPX** (importable into most mapping tools)

Saved to: `menu_fs/02_files/wardriving/`

Controls:

| State   | Input  | Action                  |
| ------- | ------ | ----------------------- |
| IDLE    | CENTER | Start session           |
| IDLE    | K3     | Exit                    |
| RUNNING | K1     | Toggle stats / map view |
| RUNNING | K3     | Go to background        |

Notes:

* GPS fix required for coordinate logging. Without a fix, networks are still captured but saved without coordinates.
* Adapter stays in monitor mode while in background. Use the Background Tasks screen to stop.

***

## Net Intel

**Module:** `bad_stuff.recon.net_intel`

Scans the local network for active hosts and attempts OS fingerprinting.

What it does:

* Discovers the local subnet via `ip route`
* Runs `nmap -sn` for host discovery
* Runs `nmap -O` for OS detection on discovered hosts
* Displays IP, MAC, hostname, and OS guess per host

Controls:

| State   | Input     | Action           |
| ------- | --------- | ---------------- |
| IDLE    | CENTER    | Start scan       |
| IDLE    | K3        | Exit             |
| RUNNING | UP / DOWN | Scroll host list |
| RUNNING | K3        | Exit             |

***

## Handshake Capture

**Module:** `bad_stuff.recon.handshake`

Captures WPA2 4-way handshakes from selected access points.

What it does:

* Scans for APs via `airodump-ng`
* Lets user select a target AP from the list
* Captures traffic on the target's channel with `airodump-ng -c <ch> --bssid <bssid>`
* Sends deauthentication frames via `aireplay-ng --deauth` to force clients to reconnect and retransmit the handshake
* Monitors the capture file until a EAPOL handshake is confirmed

Saved to: `menu_fs/02_files/handshakes/` as `.pcap`

Controls:

| State   | Input     | Action                     |
| ------- | --------- | -------------------------- |
| SCAN    | UP / DOWN | Select AP                  |
| SCAN    | CENTER    | Lock target, start capture |
| CAPTURE | K1        | Send deauth burst          |
| CAPTURE | K3        | Go to background           |

Notes:

* Networks using **802.11w Protected Management Frames (PMF)** are immune to deauthentication attacks. Institutional/university networks commonly enable this.
* The captured `.pcap` can be opened with Wireshark or cracked with the **WPA2 Cracker** app or `hashcat` directly.

***

## PMKID Grab

**Module:** `bad_stuff.recon.pmkid_grab`

Passively captures PMKID values from WPA2/WPA3 access points without deauthenticating any clients.

What it does:

* Runs `hcxdumptool -i wlan1 -w <file.pcapng> -F --rds=1`
* Tracks unique APs (by BSSID) as they are captured
* Counts captured PMKIDs using `hcxpcapngtool` (looks for `WPA*01*` and `WPA*02*` lines)
* Runs in background mode while scanning continues

Saved to: `menu_fs/02_files/handshakes/` as `.pcapng`

Controls:

| State   | Input     | Action           |
| ------- | --------- | ---------------- |
| IDLE    | CENTER    | Start capture    |
| IDLE    | K3        | Exit             |
| RUNNING | UP / DOWN | Scroll AP list   |
| RUNNING | K3        | Go to background |

Notes:

* Uses `hcxdumptool` **v6.3.5** flags. Other versions have different flag names — verify before modifying.
* The `.pcapng` file can be cracked with `hashcat -m 22000`.
* PMKID capture does not require any client to be connected to the target AP.

***

## Probe Sniffer

**Module:** `bad_stuff.recon.probe_sniffer`

Passively captures Wi-Fi probe requests from nearby devices. Reveals which SSIDs devices have previously connected to.

What it does:

* Puts `wlan1` into monitor mode
* Runs `airodump-ng --band abg --output-format csv`
* Parses the CSV station section every 3 seconds
* Displays device MAC (last 8 chars), probe SSID count, and top SSID
* Saves results to a text file on stop

Saved to: `menu_fs/02_files/probe_sniffs/`

Controls:

| State   | Input     | Action                             |
| ------- | --------- | ---------------------------------- |
| IDLE    | CENTER    | Start                              |
| IDLE    | K3        | Exit                               |
| RUNNING | K1        | Toggle sort (by packets / by time) |
| RUNNING | UP / DOWN | Scroll device list                 |
| RUNNING | K3        | Go to background                   |

***

## Harvester

**Module:** `bad_stuff.recon.harvester`

Passive overnight handshake collector. Runs continuously in the background, capturing any WPA2 handshakes from nearby networks without targeting specific APs.

Controls:

| State   | Input  | Action           |
| ------- | ------ | ---------------- |
| IDLE    | CENTER | Start            |
| IDLE    | K3     | Exit             |
| RUNNING | K3     | Go to background |

***

## WPA2 Cracker

**Module:** `bad_stuff.recon.cracker`

Dictionary attack against captured WPA2 handshakes using `hashcat`.

What it does:

* Browses `menu_fs/02_files/handshakes/` for `.pcap` and `.pcapng` files
* Browses `menu_fs/02_files/wordlists/` for wordlist files
* Runs `hashcat -m 22000` (for `.pcapng`) or `hashcat -m 2500` (for `.pcap`)
* Displays cracked passwords in real time
* Saves results to `menu_fs/02_files/cracked/`

Controls:

| State           | Input     | Action                                      |
| --------------- | --------- | ------------------------------------------- |
| SELECT FILE     | UP / DOWN | Browse captures                             |
| SELECT FILE     | CENTER    | Confirm capture, move to wordlist selection |
| SELECT WORDLIST | UP / DOWN | Browse wordlists                            |
| SELECT WORDLIST | CENTER    | Start cracking                              |
| RUNNING         | K3        | Stop                                        |

Notes:

* Pi Zero 2W has very limited GPU compute. Cracking speed is low — use this for short wordlists or pre-built rule sets. For serious cracking, copy the `.pcapng` to a desktop machine with a GPU.
* Place wordlists in `menu_fs/02_files/wordlists/` before starting.
