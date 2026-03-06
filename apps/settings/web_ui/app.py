"""
apps/settings/web_ui/app.py
Web UI Toggle — start/stop the remote web interface.

Shows current status, IP address and port for connecting,
and allows toggling the web server on/off at runtime.
Autostart preference is saved to config.json.

Controls:
  CENTER : toggle Web UI on/off
  K3     : exit
"""

import subprocess
import threading
from PIL import Image, ImageDraw

TOP_H = 26
BOT_H = 18

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEP    = (25,  45,  75)
SEP_HI = (50,  90,  140)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
GREEN  = (50,  220, 120)
RED    = (255, 70,  70)
YELLOW = (255, 200, 50)
WHITE  = (220, 235, 255)

WEB_PORT = 5000


def _ts(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def _is_running() -> bool:
    """Check if the web server port is currently open."""
    try:
        _, out = subprocess.Popen(
            ["ss", "-tlnp"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ).communicate(timeout=5)
        return f":{WEB_PORT}".encode() in out
    except Exception:
        return False


def _get_ips() -> dict:
    """Return {iface: ip} for active network interfaces."""
    ips = {}
    for iface in ("wlan0", "eth0", "usb0"):
        try:
            r = subprocess.run(
                ["ip", "-4", "addr", "show", iface],
                capture_output=True, timeout=5
            )
            for line in r.stdout.decode().splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    ips[iface] = line.split()[1].split("/")[0]
                    break
        except Exception:
            pass
    return ips


def _load_config():
    import json, os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.json")
    path = os.path.normpath(path)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    import json, os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.json")
    path = os.path.normpath(path)
    try:
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


class WebUiApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self._running   = False
        self._autostart = True
        self._ips       = {}
        self._busy      = False
        self._dirty     = True

    def on_enter(self):
        self._dirty = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        self._running   = _is_running()
        self._ips       = _get_ips()
        cfg             = _load_config()
        self._autostart = cfg.get("web_server_autostart", True)
        self._busy      = False
        self._dirty     = True

    def _toggle(self):
        if self._busy:
            return
        self._busy  = True
        self._dirty = True

        def _do():
            if not self._running:
                # Start the server at runtime if possible
                remote = getattr(self.hw, "_remote", None)
                if remote is not None:
                    try:
                        remote.start()
                    except Exception:
                        pass
                # Save autostart = True
                cfg = _load_config()
                cfg["web_server_autostart"] = True
                _save_config(cfg)
            else:
                # Cannot gracefully stop Flask mid-run;
                # just disable autostart so it won't start on next boot.
                cfg = _load_config()
                cfg["web_server_autostart"] = False
                _save_config(cfg)

            self._refresh()

        threading.Thread(target=_do, daemon=True).start()

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"
        elif event == "CENTER":
            self._toggle()
        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # --- Header ---
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "Web UI", font=self.font_label, fill=CYAN)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        M  = 10
        lh = self.font_label.size + 8
        y  = TOP_H + 10

        if self._busy:
            msg = "Please wait..."
            mw, mh = _ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, TOP_H + (H - TOP_H - BOT_H) // 2 - mh // 2),
                   msg, font=self.font_label, fill=YELLOW)
        else:
            # --- Status badge ---
            status_txt = "● RUNNING"  if self._running else "○ STOPPED"
            status_col = GREEN        if self._running else RED
            sw, sh = _ts(d, status_txt, self.font_small)
            d.text(((W - sw) // 2, y), status_txt,
                   font=self.font_small, fill=status_col)
            y += sh + 6

            # Autostart indicator
            auto_txt = "autostart: ON" if self._autostart else "autostart: OFF"
            auto_col = DIM
            aw, ah = _ts(d, auto_txt, self.font_label)
            d.text(((W - aw) // 2, y), auto_txt,
                   font=self.font_label, fill=auto_col)
            y += ah + 10

            d.line([(M, y), (W - M, y)], fill=SEP, width=1)
            y += 8

            if self._running and self._ips:
                # Show URL for each interface
                for iface, ip in self._ips.items():
                    url = f"http://{ip}:{WEB_PORT}"
                    lw, _ = _ts(d, iface + ":", self.font_label)
                    d.text((M, y), iface + ":", font=self.font_label, fill=DIM)
                    d.text((M + lw + 4, y), url, font=self.font_label, fill=CYAN)
                    y += lh

            elif self._running and not self._ips:
                # Running but no IP yet
                msg = f"port :{WEB_PORT} open"
                mw, _ = _ts(d, msg, self.font_label)
                d.text(((W - mw) // 2, y), msg,
                       font=self.font_label, fill=YELLOW)

            elif not self._running and not self._autostart:
                # Disabled — show restart note
                for line in ("Server is disabled.", "Enable & reboot"):
                    lw, lhh = _ts(d, line, self.font_label)
                    d.text(((W - lw) // 2, y), line,
                           font=self.font_label, fill=DIM)
                    y += lhh + 4

            else:
                msg = "Server not running"
                mw, _ = _ts(d, msg, self.font_label)
                d.text(((W - mw) // 2, y + 6), msg,
                       font=self.font_label, fill=DIM)

        # --- Hint bar ---
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        if self._running:
            action = "disable"
        else:
            action = "enable"
        hint = f"CTR:{action}  K3:back"
        hw2, hh = _ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh - 2),
               hint, font=self.font_label, fill=HINT)

        self.hw.show(img)
