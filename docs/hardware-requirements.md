# hardware requirements

## Required components

Both components are mandatory. Without them the firmware will not run.

### Raspberry Pi Zero 2W

* ARM Cortex-A53 quad-core @ 1 GHz, 512 MB RAM
* Must have a **GPIO header** (either soldered or with header pins)
* The USB data port (not the PWR port) is used for USB HID / gadget mode

### Waveshare 1.3" LCD HAT

* ST7789 driver, 240×240 IPS display
* 5-way joystick (UP / DOWN / LEFT / RIGHT / CENTER press)
* 3 physical buttons (K1, K2, K3)
* Connects directly to the 40-pin GPIO header
* SPI interface — SPI must be enabled before first run (see [Installation](/broken/pages/41644f811cd0f6ed0582c6e4c2b0c45733bc143f))

***

## Optional components

| Component                              | What it enables                                                        |
| -------------------------------------- | ---------------------------------------------------------------------- |
| **Alfa AWUS036ACM** (MT7612U)          | Monitor mode on `wlan1`, 5 GHz wardriving, packet injection, Evil Twin |
| **USB GPS dongle** (VK-172 / u-blox 7) | Live GPS coordinates in Wardriving, GPS Map app                        |
| **Ethernet / USB Hub HAT**             | Wired network connectivity, additional USB ports                       |

### Wi-Fi adapter compatibility

The external adapter must expose itself as `wlan1` on the Pi.

| Chipset | Monitor mode | Injection | Notes                         |
| ------- | ------------ | --------- | ----------------------------- |
| MT7612U | ✅            | ✅         | Alfa AWUS036ACM — recommended |
| MT7601U | ✅            | ✅         | Common cheap adapters         |
| RT5572  | ✅            | ✅         | Dual-band                     |
| AR9271  | ✅            | ✅         | Atheros, well-supported       |

Without an external adapter, all wireless tools fall back to the built-in `wlan0` (2.4 GHz only, no monitor mode).

### GPS dongle notes

* `gpsd` is installed by `install.sh` and starts automatically
* The dongle is read from `/dev/ttyUSB0` or `/dev/ttyACM0` (auto-detected by gpsd)
* Cold fix takes 30–120 seconds outdoors. A GPS fix indicator appears on the screensaver.
