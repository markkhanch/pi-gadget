# Pi-gadget

Pi-gadget is a personal side project I work on in my free time.  
It is a small Raspberry Pi–based handheld device created to explore system-level programming, hardware interaction, and custom interfaces.

The project is in an early stage and evolves gradually as I experiment and add functionality.

---

## 🧠 About the project

This project is built primarily for personal learning and experimentation.  
It is not intended to be a finished or polished product.

Development is incremental and driven by curiosity rather than fixed goals or deadlines.

---

## 🛠️ Required hardware

The following components are **mandatory** for the project to work:

- **Raspberry Pi Zero 2 W** (with GPIO header)
- **Waveshare 1.3" LCD HAT** (ST7789-based, with buttons)

Without these components, the project will not function as intended.

---

## 🔌 Optional hardware

The following components are **optional** and enable additional features:

- **Ethernet / USB Hub HAT** (RJ45 + USB ports)
- **USB expansion / breakout board**
- **USB GPS dongle** (VK-172 or compatible)

These components are not required for basic operation but are used to extend functionality.

---

## 🚀 Setup

```bash
git clone https://github.com/markkhanch/pi-gadget.git
cd pi-gadget
./install.sh
python3 main.py
