"""
apps/system/device_info/app.py
Device information — IP, MAC, gateway, hostname, OS, uptime, Pi model.
"""

import subprocess
from PIL import Image, ImageDraw


TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG_COLOR   = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP_COLOR  = (60, 60, 60)
HINT_COLOR = (100, 100, 100)
WHITE      = (255, 255, 255)
LABEL_COL  = (130, 130, 130)
VALUE_COL  = (220, 220, 220)
GREEN      = (70, 200, 70)
YELLOW     = (220, 180, 50)
RED        = (220, 70, 70)


def _sh(cmd, timeout=5):
    """Run a command given as an argv list (no shell — no injection surface)."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _read_file(path: str) -> str:
    """Read a small sysfs/proc file, stripped. Empty string on any error."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read().replace("\x00", "").strip()
    except Exception:
        return ""


def _os_pretty_name() -> str:
    for line in _read_file("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _cpuinfo_model() -> str:
    for line in _read_file("/proc/cpuinfo").splitlines():
        if line.startswith("Model") and ":" in line:
            return line.split(":", 1)[1].strip()
    return ""


def _get_info() -> list:
    """
    Collect device info rows.
    Returns list of (label, value) tuples.
    """
    rows = []

    # Hostname
    hostname = _sh(["hostname"]) or "unknown"
    rows.append(("Host", hostname))

    # Wi-Fi IP and MAC
    wlan_ip = ""
    out = _sh(["ip", "-4", "addr", "show", "wlan0"])
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            wlan_ip = line.split()[1].split("/")[0]
            break
    rows.append(("Wi-Fi IP", wlan_ip or "—"))

    wlan_mac = _read_file("/sys/class/net/wlan0/address") or "—"
    rows.append(("Wi-Fi MAC", wlan_mac))

    # Ethernet IP and MAC
    eth_ip = ""
    out = _sh(["ip", "-4", "addr", "show", "eth0"])
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            eth_ip = line.split()[1].split("/")[0]
            break
    rows.append(("ETH IP", eth_ip or "—"))

    eth_mac = _read_file("/sys/class/net/eth0/address") or "—"
    rows.append(("ETH MAC", eth_mac))

    # Default gateway
    gw = ""
    out = _sh(["ip", "route", "show", "default"])
    parts = out.split()
    if "via" in parts and parts.index("via") + 1 < len(parts):
        gw = parts[parts.index("via") + 1]
    rows.append(("Gateway", gw or "—"))

    # Uptime
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        uptime = f"{h}h {m}m"
    except Exception:
        uptime = "—"
    rows.append(("Uptime", uptime))

    # OS version
    os_name = _os_pretty_name() or "—"
    # Shorten long names
    os_name = os_name.replace("GNU/Linux", "").replace("  ", " ").strip()
    if len(os_name) > 18:
        os_name = os_name[:17] + "…"
    rows.append(("OS", os_name))

    # Pi model
    model = _read_file("/proc/device-tree/model")
    if not model:
        model = _cpuinfo_model()
    if len(model) > 20:
        model = model[:19] + "…"
    rows.append(("Model", model or "—"))

    return rows


class DeviceInfoApp:
    REFRESH_INTERVAL = 10.0  # seconds between auto-refresh

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.rows   = []
        self.scroll = 0
        self.timer  = 0.0
        self._dirty = True

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def on_enter(self):
        self.rows   = _get_info()
        self.scroll = 0
        self.timer  = 0.0
        self._dirty = True

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"

        if event == "KEY1":
            # Manual refresh
            self.rows   = _get_info()
            self.scroll = 0
            self.timer  = 0.0
            self._dirty = True
            return "stay"

        row_h    = self.font_label.size + 8
        max_rows = (self.hw.H - TOP_BAR_H - BOT_BAR_H) // row_h

        if event == "UP" and self.scroll > 0:
            self.scroll -= 1
            self._dirty  = True
        elif event == "DOWN" and self.scroll < max(0, len(self.rows) - max_rows):
            self.scroll += 1
            self._dirty  = True

        return "stay"

    def update(self, dt):
        self.timer += dt
        if self.timer >= self.REFRESH_INTERVAL:
            self.rows   = _get_info()
            self.timer  = 0.0
            self._dirty = True

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG_COLOR)
        draw  = ImageDraw.Draw(img)

        # Header
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        title = "Device Info"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        # Refresh hint top-right
        hint_top = "K1:refresh"
        htw, hth = self._ts(draw, hint_top, self.font_label)
        draw.text((W - htw - 4, (TOP_BAR_H - hth) // 2),
                  hint_top, font=self.font_label, fill=HINT_COLOR)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP_COLOR, width=1)

        # Rows
        row_h    = self.font_label.size + 8
        max_rows = (H - TOP_BAR_H - BOT_BAR_H) // row_h
        MARGIN   = 6
        y        = TOP_BAR_H + 4

        visible = self.rows[self.scroll: self.scroll + max_rows]
        for label, value in visible:
            # Label left, value right — truncate if needed
            lbl_str = label + ":"
            lw, lh  = self._ts(draw, lbl_str, self.font_label)
            draw.text((MARGIN, y), lbl_str, font=self.font_label, fill=LABEL_COL)

            # Value — right-aligned, truncate if too wide
            max_val_w = W - MARGIN * 2 - lw - 6
            val_str   = value
            vw, vh    = self._ts(draw, val_str, self.font_label)
            while vw > max_val_w and len(val_str) > 1:
                val_str = val_str[:-2] + "…"
                vw, _   = self._ts(draw, val_str, self.font_label)

            draw.text((W - vw - MARGIN, y), val_str,
                      font=self.font_label, fill=VALUE_COL)

            # Separator line
            draw.line([(MARGIN, y + row_h - 2), (W - MARGIN, y + row_h - 2)],
                      fill=(30, 30, 30), width=1)
            y += row_h

        # Scroll indicator
        total = len(self.rows)
        if total > max_rows:
            bar_h   = max(16, int((H - TOP_BAR_H - BOT_BAR_H) * max_rows / total))
            bar_y   = TOP_BAR_H + int((H - TOP_BAR_H - BOT_BAR_H - bar_h) * self.scroll / max(1, total - max_rows))
            draw.rectangle([W - 3, bar_y, W - 1, bar_y + bar_h], fill=(80, 80, 80))

        # Bottom hint
        hint = "UP/DOWN:scroll  K3:back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
