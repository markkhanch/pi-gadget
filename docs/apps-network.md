# apps network

All network attack apps live under `apps/bad_stuff/network/` and appear in **Hacking → Network**.

***

## ARP Spoofer

**Module:** `bad_stuff.network.arp_spoofer`

Performs ARP cache poisoning to position the device as a man-in-the-middle between a target host and the gateway.

What it does:

* Scans the local network with `arp-scan` to discover live hosts
* User selects a target from the discovered list
* Sends crafted ARP reply packets via raw sockets in a background thread:
  * Tells the **target**: "the gateway's MAC is my MAC"
  * Tells the **gateway**: "the target's MAC is my MAC"
* Captures traffic with `tcpdump -i eth0 -w <file.pcap>` running in parallel

Saved to: `menu_fs/02_files/arp_spoof/` as `.pcap`

Flow:

{% stepper %}
{% step %}
### SCAN

* Discovers hosts via `arp-scan`
* User selects a target host
{% endstep %}

{% step %}
### ATTACK

* ARP poison loop runs in background (raw sockets)
* `tcpdump` capture runs in parallel, writing `.pcap`
{% endstep %}
{% endstepper %}

Controls:

| State  | Input     | Action                       |
| ------ | --------- | ---------------------------- |
| SCAN   | UP / DOWN | Select target host           |
| SCAN   | CENTER    | Confirm target, start attack |
| ATTACK | K1        | (context action, varies)     |
| ATTACK | K3        | Go to background             |

Notes:

* Requires the Pi to be on the same L2 network as the target (same subnet / same switch).
* IP forwarding must be enabled on the Pi for traffic to actually flow through: `echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward`. Without this, intercepted traffic is dropped and the target loses connectivity.
* Captured `.pcap` files can be opened in Wireshark on a desktop machine.
* Uses raw sockets (`AF_PACKET / SOCK_RAW`) — no external tools needed for the poisoning itself.

***

## DNS Spoofer

**Module:** `bad_stuff.network.dns_spoofer`

Intercepts DNS queries from a poisoned target and responds with attacker-controlled IP addresses, redirecting the target's web traffic to a custom server.

What it does:

* Requires ARP Spoofer to be running first (to intercept traffic)
* Listens for DNS queries from the target using `scapy` or a raw socket listener
* Spoofs DNS responses for configured domains, pointing them to the Pi's IP
* Intended to be used together with Evil Twin's portal server or a locally hosted page

Controls:

| State   | Input  | Action      |
| ------- | ------ | ----------- |
| IDLE    | CENTER | Start       |
| IDLE    | K3     | Exit        |
| RUNNING | K3     | Stop / exit |

***

## Evil Twin

**Module:** `bad_stuff.network.evil_twin`

Creates a rogue access point with a captive portal to harvest credentials.

What it does:

* Scans for real APs using `airodump-ng`
* Clones the target AP's SSID and sets up a rogue AP on `wlan0` using `hostapd`
* Runs `scripts/evil_twin.sh` to configure `hostapd`, `iptables` NAT rules, and `dnsmasq` for DHCP
* Serves a captive portal via a Flask HTTP server (`portal_server.py`)
* Logs submitted credentials to `menu_fs/02_files/portals/`
* Optionally sends deauth frames against the real AP to force clients over (via `wlan1`)

Portal pages: Custom portal HTML files are stored in `menu_fs/02_files/portals/`. The selected HTML is served to any client that connects to the rogue AP and opens a browser. An example portal (`example_portal.html`) is included.

Controls:

| State   | Input     | Action                        |
| ------- | --------- | ----------------------------- |
| SCAN    | UP / DOWN | Select target AP              |
| SCAN    | CENTER    | Launch rogue AP               |
| RUNNING | K1        | Toggle deauth against real AP |
| RUNNING | K3        | Go to background              |

Notes:

* Requires `wlan0` for the rogue AP. If `wlan1` is also present it can be used simultaneously for deauth against the real AP.
* `hostapd` must be installed (included in `install.sh`).
* `iptables` NAT rules are applied by `evil_twin.sh` and cleaned up on stop.
* Clients that already have a PMKID/handshake cached for the real AP may not reconnect to an open clone unless they are deauthed first.
