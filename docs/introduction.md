# introduction

Pi-Gadget is a handheld cybersecurity toolkit built on a Raspberry Pi Zero 2W. It runs a custom Python framework with a menu-driven GUI on a 240×240 display, physical button controls, and a modular app system. Everything from Wi-Fi attacks to USB HID payload injection runs directly on the device — no laptop required.

The project is built for personal learning and hands-on experimentation. It is not a finished product and evolves incrementally.

## What it does

| Category            | Tools                                                                       |
| ------------------- | --------------------------------------------------------------------------- |
| **Recon**           | Wardriving, Probe Sniffer, Net Intel, PMKID Grab, WPA2 Handshake, Harvester |
| **Network attacks** | ARP Spoofer, DNS Spoofer, Evil Twin + captive portal                        |
| **Wireless**        | Deauth Bomber, MAC Changer                                                  |
| **USB / HID**       | Ducky Script 3.0 BadUSB payload injector                                    |
| **System**          | CPU/RAM monitor, disk usage, temperature, GPS Map                           |
| **Remote access**   | Browser-based live screen streaming + button control (WebUI)                |

## Hardware at a glance

* **Raspberry Pi Zero 2W** — ARM Cortex-A53 quad-core, 512 MB RAM
* **Waveshare 1.3" LCD HAT** — ST7789, 240×240, 5-way joystick + 3 buttons
* **Alfa AWUS036ACM** (optional) — MT7612U, monitor mode + packet injection on `wlan1`
* **USB GPS dongle** (optional) — VK-172 or u-blox 7, enables wardriving with coordinates

{% hint style="warning" %}
⚠️ For **authorized testing and educational use only.**\
Do not use any tools against networks or devices you do not own or have explicit written permission to test.
{% endhint %}
