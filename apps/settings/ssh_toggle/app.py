"""
apps/settings/ssh_toggle/app.py
SSH info screen — shows running status, IP, and boot autostart toggle.

SSH process is detected via pgrep (works even when systemd shows 'failed').
CENTER toggles autostart on boot (systemctl enable/disable).

Controls:
  CENTER — toggle boot autostart
  KEY3   — exit
"""

import subprocess
from PIL import Image, ImageDraw

TOP_BAR_H  = 24
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
GRAY       = (150, 150, 150)
HINT_COLOR = (100, 100, 100)
GREEN      = (70, 200, 70)
RED        = (220, 70, 70)
YELLOW     = (220, 180, 50)


def _sh(cmd):
    """Run a simple command list (no shell=True, no redirection tricks)."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=8)
        out = (r.stdout + r.stderr).decode("utf-8", errors="ignore").strip()
        return r.returncode, out
    except Exception as e:
        return 1, str(e)


def _get_status() -> dict:
    # Check if sshd process is running
    code, _ = _sh(["pgrep", "-x", "sshd"])
    process_running = (code == 0)

    # Check if port 22 is listening
    _, ss_out = _sh(["ss", "-tlnp"])
    port_open = ":22" in ss_out

    active = process_running or port_open

    # Get IPs
    ips = {}
    for iface in ("eth0", "wlan0"):
        _, addr = _sh(["ip", "-4", "addr", "show", iface])
        for line in addr.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ips[iface] = line.split()[1].split("/")[0]
                break

    # Check boot autostart
    _, en_out = _sh(["systemctl", "is-enabled", "ssh"])
    enabled_on_boot = en_out.strip() == "enabled"

    return {
        "active":          active,
        "ips":             ips,
        "enabled_on_boot": enabled_on_boot,
    }


def _set_boot(enable: bool) -> tuple:
    action = "enable" if enable else "disable"
    code, out = _sh(["sudo", "systemctl", action, "ssh"])
    if code == 0:
        return True, f"SSH autostart\n{'enabled' if enable else 'disabled'}"
    return False, out[:50] or "Failed"


class SshToggleApp:
    S_MAIN = "main"
    S_STAT = "stat"

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.status     = {}
        self.status_ok  = True
        self.status_msg = ""
        self.screen     = self.S_MAIN
        self._dirty     = True

    def on_enter(self):
        self.screen = self.S_MAIN
        self.status = _get_status()
        self._dirty = True

    def on_event(self, event) -> str:
        if self.screen == self.S_STAT:
            self.screen = self.S_MAIN
            self.status = _get_status()
            self._dirty = True
            return "stay"

        if event == "KEY3":
            return "exit"

        if event == "CENTER":
            on_boot = self.status.get("enabled_on_boot", False)
            # Draw loading screen immediately before blocking call
            self._show_stat(True, "Updating...")
            ok, msg = _set_boot(not on_boot)
            self.status_ok  = ok
            self.status_msg = msg
            self._dirty     = True

        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False
        if self.screen == self.S_MAIN:
            self._draw_main()
        else:
            self._draw_stat()

    def _show_stat(self, ok, msg):
        self.screen     = self.S_STAT
        self.status_ok  = ok
        self.status_msg = msg
        self._draw_stat()

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _draw_main(self):
        W, H    = self.hw.W, self.hw.H
        img     = Image.new("RGB", (W, H), BG)
        d       = ImageDraw.Draw(img)
        active  = self.status.get("active", False)
        ips     = self.status.get("ips", {})
        on_boot = self.status.get("enabled_on_boot", False)

        # Header
        d.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(d, "SSH Server", self.font_label)
        d.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
               "SSH Server", font=self.font_label, fill=WHITE)
        d.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        y = TOP_BAR_H + 14

        # Big running status
        lbl = "RUNNING" if active else "NOT RUNNING"
        col = GREEN if active else RED
        lw, lh = self._ts(d, lbl, self.font_small)
        d.text(((W - lw) // 2, y), lbl, font=self.font_small, fill=col)
        y += lh + 10

        # IPs
        if ips:
            for iface, ip in ips.items():
                line = f"pi@{ip}"
                lw2, lh2 = self._ts(d, line, self.font_label)
                d.text(((W - lw2) // 2, y), line, font=self.font_label, fill=GRAY)
                y += lh2 + 3
            pw, ph = self._ts(d, "port 22", self.font_label)
            d.text(((W - pw) // 2, y), "port 22",
                   font=self.font_label, fill=(80, 80, 80))
            y += ph + 10
        else:
            nw, nh = self._ts(d, "No network", self.font_label)
            d.text(((W - nw) // 2, y), "No network",
                   font=self.font_label, fill=YELLOW)
            y += nh + 10

        d.line([(10, y), (W - 10, y)], fill=SEP, width=1)
        y += 10

        # Boot autostart + toggle button
        boot_lbl = "Boot: ON" if on_boot else "Boot: OFF"
        boot_col = GREEN if on_boot else YELLOW
        bw, bh   = self._ts(d, boot_lbl, self.font_label)
        d.text(((W - bw) // 2, y), boot_lbl,
               font=self.font_label, fill=boot_col)
        y += bh + 6

        btn     = "Disable autostart" if on_boot else "Enable autostart"
        btn_col = RED if on_boot else GREEN
        tw2, th2 = self._ts(d, btn, self.font_label)
        pad = 8
        bx0 = (W - tw2 - pad * 2) // 2
        d.rounded_rectangle(
            [(bx0, y), (bx0 + tw2 + pad * 2, y + th2 + pad)],
            radius=6, fill=(25, 25, 25), outline=btn_col, width=2
        )
        d.text((bx0 + pad, y + pad // 2), btn,
               font=self.font_label, fill=btn_col)

        hint = "CTR:toggle boot  K3:exit"
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)

    def _draw_stat(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        d.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(d, "SSH Server", self.font_label)
        d.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
               "SSH Server", font=self.font_label, fill=WHITE)
        d.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

        color = GREEN if self.status_ok else RED
        icon  = "OK" if self.status_ok else "ERR"
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, TOP_BAR_H + 20),
               icon, font=self.font_big, fill=color)

        y = TOP_BAR_H + 20 + ih + 12
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, y), line, font=self.font_label, fill=WHITE)
            y += lh + 4

        hw2, hh2 = self._ts(d, "Any key: back", self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 4),
               "Any key: back", font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
