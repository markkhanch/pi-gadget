"""
apps/settings/datetime/app.py
Date & Time settings — timezone picker, NTP toggle, manual time set.

Screens:
  MAIN     — clock + NTP status + 3 menu actions
  TIMEZONE — scrollable timezone list
  SETTIME  — field-by-field time editor (HH MM DD Mo YYYY)
  STATUS   — result feedback (OK / ERR)

Controls:
  MAIN:     UP/DOWN=menu  CENTER=select  KEY3=exit
  TIMEZONE: UP/DOWN=scroll  CENTER=apply  KEY3=back
  SETTIME:  LEFT/RIGHT=field  UP/DOWN=value  CENTER=save  KEY3=cancel
  STATUS:   any key=back
"""

import subprocess
import os
from datetime import datetime
from PIL import Image, ImageDraw

# Store clock format preference next to this file
_FMT_FILE = os.path.join(os.path.dirname(__file__), "clockfmt.txt")

def _load_fmt() -> str:
    """Return '12' or '24'."""
    try:
        return open(_FMT_FILE).read().strip()
    except Exception:
        return "24"

def _save_fmt(fmt: str):
    try:
        open(_FMT_FILE, "w").write(fmt)
    except Exception:
        pass

# ── Style ─────────────────────────────────────────────────────
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
BLUE       = (80, 160, 255)
ROW_H      = 32
SEL_BG     = (40, 40, 40)

# Valid IANA timezone names (verified with timedatectl list-timezones)
TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "America/Honolulu",
    "America/Toronto",
    "America/Vancouver",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Moscow",
    "Europe/Kiev",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Bangkok",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Singapore",
    "Australia/Sydney",
    "Pacific/Auckland",
]

MENU_ITEMS = [
    ("ntp_toggle",  "Toggle NTP sync"),
    ("set_tz",      "Change timezone"),
    ("set_time",    "Set time manually"),
    ("fmt_toggle",  "Toggle 12h / 24h"),
]

FIELD_NAMES  = ["HH", "MM", "DD", "Mo", "YYYY"]
FIELD_LIMITS = [(0, 23), (0, 59), (1, 31), (1, 12), (2020, 2099)]


# ── Shell ─────────────────────────────────────────────────────

def _sh(cmd, timeout=10):
    """Run shell command string. Returns (returncode, stdout+stderr stripped)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", errors="ignore")
        err = r.stderr.decode("utf-8", errors="ignore")
        return r.returncode, (out + err).strip()
    except Exception as e:
        return 1, str(e)


# ── timedatectl helpers ───────────────────────────────────────

def _get_td() -> dict:
    """
    Read timedatectl output and return parsed dict.
    Example output we parse:
      Local time: Sun 2026-02-22 17:33:48 -03
      Time zone: America/Argentina/Buenos_Aires (-03, -0300)
      System clock synchronized: no
      NTP service: inactive
    """
    _, raw = _sh("timedatectl")
    td = {"timezone": "Unknown", "ntp": False, "synced": False}

    for line in raw.splitlines():
        line = line.strip()

        if line.startswith("Time zone:"):
            # "Time zone: America/New_York (EST, -0500)"
            # Take only the first token after the colon
            rest = line[len("Time zone:"):].strip()
            td["timezone"] = rest.split()[0]

        elif line.startswith("NTP service:"):
            # "NTP service: inactive" or "NTP service: active"
            val = line[len("NTP service:"):].strip().lower()
            # exact match — "inactive" must NOT match "active"
            td["ntp"] = (val == "active")

        elif line.startswith("Network time on:"):
            val = line[len("Network time on:"):].strip().lower()
            td["ntp"] = (val == "yes")

        elif line.startswith("System clock synchronized:"):
            val = line[len("System clock synchronized:"):].strip().lower()
            td["synced"] = (val == "yes")

        elif line.startswith("NTP synchronized:"):
            val = line[len("NTP synchronized:"):].strip().lower()
            td["synced"] = (val == "yes")

    return td


def _set_timezone(tz: str) -> tuple:
    code, out = _sh(f"sudo timedatectl set-timezone {tz}")
    if code == 0:
        # Update TZ in the current process so datetime.now() reflects new zone immediately
        import os, time as _time
        os.environ["TZ"] = tz
        _time.tzset()
        return True, f"Timezone:\n{tz}"
    return False, out[:60] or "Failed"


def _set_ntp(enable: bool) -> tuple:
    val = "true" if enable else "false"
    code, out = _sh(f"sudo timedatectl set-ntp {val}")
    if code == 0:
        return True, f"NTP {'enabled' if enable else 'disabled'}"
    return False, out[:60] or "Failed"


def _set_time(dt: datetime) -> tuple:
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    code, out = _sh(f'sudo timedatectl set-time "{ts}"')
    if code == 0:
        return True, f"Time set:\n{ts}"
    return False, out[:60] or "Failed"


# ── App ───────────────────────────────────────────────────────

class DatetimeApp:
    S_MAIN = "main"
    S_TZ   = "tz"
    S_TIME = "time"
    S_STAT = "stat"

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen     = self.S_MAIN
        self.menu_sel   = 0
        self.tz_sel     = 0
        self.tz_scroll  = 0
        self.td         = {"timezone": "Unknown", "ntp": False, "synced": False}
        self.status_ok  = True
        self.status_msg = ""

        # Time editor fields: [hour, min, day, month, year]
        self.fields    = [0, 0, 1, 1, 2026]
        self.field_sel = 0

        self.clock_fmt = _load_fmt()   # "12" or "24"
        self._dirty = True
        self._tick  = 0.0

    def on_enter(self):
        self.screen   = self.S_MAIN
        self.menu_sel = 0
        self._reload()
        self._dirty = True

    def _reload(self):
        self.td = _get_td()
        tz = self.td["timezone"]
        if tz in TIMEZONES:
            self.tz_sel    = TIMEZONES.index(tz)
            self.tz_scroll = max(0, self.tz_sel - 2)
        else:
            self.tz_sel = self.tz_scroll = 0

    # ── Lifecycle ─────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.screen == self.S_MAIN:   return self._ev_main(event)
        if self.screen == self.S_TZ:     return self._ev_tz(event)
        if self.screen == self.S_TIME:   return self._ev_time(event)
        if self.screen == self.S_STAT:
            self.screen = self.S_MAIN
            self._reload()
            self._dirty = True
            return "stay"
        return "stay"

    def update(self, dt):
        if self.screen == self.S_MAIN:
            self._tick += dt
            if self._tick >= 1.0:
                self._tick  = 0.0
                self._dirty = True

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False
        {
            self.S_MAIN: self._draw_main,
            self.S_TZ:   self._draw_tz,
            self.S_TIME: self._draw_time,
            self.S_STAT: self._draw_stat,
        }.get(self.screen, lambda: None)()

    # ── Event handlers ────────────────────────────────────────

    def _ev_main(self, event) -> str:
        if event == "KEY3":
            return "exit"
        if event == "UP" and self.menu_sel > 0:
            self.menu_sel -= 1
            self._dirty = True
        elif event == "DOWN" and self.menu_sel < len(MENU_ITEMS) - 1:
            self.menu_sel += 1
            self._dirty = True
        elif event == "CENTER":
            action = MENU_ITEMS[self.menu_sel][0]
            if action == "ntp_toggle":
                self._act(lambda: _set_ntp(not self.td["ntp"]), "Updating NTP...")
            elif action == "fmt_toggle":
                self.clock_fmt = "12" if self.clock_fmt == "24" else "24"
                _save_fmt(self.clock_fmt)
                self._dirty = True
            elif action == "set_tz":
                self.screen = self.S_TZ
                self._dirty = True
            elif action == "set_time":
                if self.td["ntp"]:
                    self._show_stat(False, "Disable NTP first")
                else:
                    now = datetime.now()
                    self.fields    = [now.hour, now.minute, now.day, now.month, now.year]
                    self.field_sel = 0
                    self.screen    = self.S_TIME
                    self._dirty    = True
        return "stay"

    def _ev_tz(self, event) -> str:
        if event == "KEY3":
            self.screen = self.S_MAIN
            self._dirty = True
            return "stay"
        max_rows = (self.hw.H - TOP_BAR_H - 20) // ROW_H
        if event == "UP" and self.tz_sel > 0:
            self.tz_sel -= 1
            if self.tz_sel < self.tz_scroll:
                self.tz_scroll = self.tz_sel
            self._dirty = True
        elif event == "DOWN" and self.tz_sel < len(TIMEZONES) - 1:
            self.tz_sel += 1
            if self.tz_sel >= self.tz_scroll + max_rows:
                self.tz_scroll = self.tz_sel - max_rows + 1
            self._dirty = True
        elif event == "CENTER":
            self._act(lambda: _set_timezone(TIMEZONES[self.tz_sel]),
                      f"Setting timezone...")
        return "stay"

    def _ev_time(self, event) -> str:
        if event == "KEY3":
            self.screen = self.S_MAIN
            self._dirty = True
            return "stay"
        if event == "LEFT" and self.field_sel > 0:
            self.field_sel -= 1
            self._dirty = True
        elif event == "RIGHT" and self.field_sel < len(self.fields) - 1:
            self.field_sel += 1
            self._dirty = True
        elif event in ("UP", "DOWN"):
            lo, hi = FIELD_LIMITS[self.field_sel]
            v = self.fields[self.field_sel]
            v = v + (1 if event == "UP" else -1)
            # Wrap around
            if v > hi: v = lo
            if v < lo: v = hi
            self.fields[self.field_sel] = v
            self._dirty = True
        elif event == "CENTER":
            h, m, d, mo, y = self.fields
            try:
                dt = datetime(y, mo, d, h, m, 0)
            except ValueError as e:
                self._show_stat(False, f"Invalid date:\n{e}")
                return "stay"
            self._act(lambda: _set_time(dt), "Setting time...")
        return "stay"

    # ── Helpers ───────────────────────────────────────────────

    def _act(self, fn, loading_msg: str):
        """Show loading state, run blocking fn, show result."""
        self._show_stat(True, loading_msg)
        ok, msg = fn()
        self.status_ok  = ok
        self.status_msg = msg
        self._dirty     = True

    def _show_stat(self, ok: bool, msg: str):
        self.screen     = self.S_STAT
        self.status_ok  = ok
        self.status_msg = msg
        self._dirty     = True
        self._draw_stat()   # draw immediately before blocking call

    # ── Draw ──────────────────────────────────────────────────

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _header(self, draw, W, title, hint=""):
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        if hint:
            hw, hh = self._ts(draw, hint, self.font_label)
            draw.text((W - hw - 4, (TOP_BAR_H - hh) // 2),
                      hint, font=self.font_label, fill=GRAY)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

    def _draw_main(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Date & Time", "K3:exit")

        now = datetime.now()
        y   = TOP_BAR_H + 6

        # Clock — format depends on user preference
        if self.clock_fmt == "12":
            ts = now.strftime("%I:%M:%S %p")
        else:
            ts = now.strftime("%H:%M:%S")
        tw, th = self._ts(d, ts, self.font_small)
        d.text(((W - tw) // 2, y), ts, font=self.font_small, fill=WHITE)
        y += th + 2

        # Date
        ds = now.strftime("%a %d %b %Y")
        dw, dh = self._ts(d, ds, self.font_label)
        d.text(((W - dw) // 2, y), ds, font=self.font_label, fill=GRAY)
        y += dh + 4

        # Timezone
        tz = self.td["timezone"]
        tz_short = tz.split("/")[-1].replace("_", " ")
        tw2, th2 = self._ts(d, tz_short, self.font_label)
        d.text(((W - tw2) // 2, y), tz_short, font=self.font_label, fill=GRAY)
        y += th2 + 2

        # NTP badge
        ntp_on  = self.td["ntp"]
        ntp_lbl = "NTP ON" if ntp_on else "NTP OFF"
        ntp_col = GREEN if ntp_on else YELLOW
        nw, nh  = self._ts(d, ntp_lbl, self.font_label)
        pad = 4
        bx  = (W - nw - pad * 2) // 2
        d.rounded_rectangle([(bx, y), (bx + nw + pad * 2, y + nh + pad)],
                             radius=4, fill=(0, 0, 0), outline=ntp_col, width=1)
        d.text((bx + pad, y + pad // 2), ntp_lbl, font=self.font_label, fill=ntp_col)
        y += nh + pad + 8

        d.line([(10, y), (W - 10, y)], fill=SEP, width=1)
        y += 6

        # Menu
        for i, (_, label) in enumerate(MENU_ITEMS):
            y0  = y + i * ROW_H
            y1  = y0 + ROW_H - 4
            sel = i == self.menu_sel
            d.rounded_rectangle([(10, y0), (W - 10, y1)], radius=6,
                                 fill=SEL_BG if sel else (15, 15, 15),
                                 outline=WHITE if sel else SEP, width=1)
            lw, lh = self._ts(d, label, self.font_label)
            d.text(((W - lw) // 2, y0 + (ROW_H - 4 - lh) // 2),
                   label, font=self.font_label, fill=WHITE if sel else GRAY)

        self.hw.show(img)

    def _draw_tz(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Timezone", "K3:back")

        hint = "CTR: apply"
        hw, hh = self._ts(d, hint, self.font_label)
        d.text(((W - hw) // 2, H - hh - 2), hint, font=self.font_label, fill=HINT_COLOR)

        current = self.td["timezone"]
        max_rows = (H - TOP_BAR_H - 20) // ROW_H

        for row, idx in enumerate(range(self.tz_scroll,
                                        min(self.tz_scroll + max_rows, len(TIMEZONES)))):
            tz  = TIMEZONES[idx]
            y0  = TOP_BAR_H + row * ROW_H
            y1  = y0 + ROW_H
            sel = idx == self.tz_sel
            cur = tz == current

            if sel:
                d.rectangle([(0, y0), (W - 1, y1 - 1)],
                             fill=SEL_BG, outline=WHITE, width=1)

            short  = tz.split("/")[-1].replace("_", " ")
            region = tz.split("/")[0] if "/" in tz else ""
            color  = GREEN if cur else (WHITE if sel else GRAY)

            d.text((6, y0 + 4), short, font=self.font_label, fill=color)
            if cur:
                d.text((6, y0 + 4 + self.font_label.size + 2),
                       "current", font=self.font_label, fill=GREEN)
            if region:
                rw, _ = self._ts(d, region, self.font_label)
                d.text((W - rw - 4, y0 + 4), region,
                       font=self.font_label, fill=(70, 70, 70))

            d.line([(0, y1 - 1), (W, y1 - 1)], fill=(30, 30, 30), width=1)

        self.hw.show(img)

    def _draw_time(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Set Time", "K3:cancel")

        # Bottom hints
        hints = ["L/R: field    U/D: value", "CTR: save"]
        for i, hint in enumerate(reversed(hints)):
            hw, hh = self._ts(d, hint, self.font_label)
            d.text(((W - hw) // 2, H - (i + 1) * (hh + 3)),
                   hint, font=self.font_label, fill=HINT_COLOR)

        # 5 field boxes: HH MM DD Mo YYYY
        n      = len(self.fields)
        margin = 4
        gap    = 3
        cell_w = (W - margin * 2 - gap * (n - 1)) // n
        cell_h = 60
        y0     = TOP_BAR_H + 20

        for i, (name, val) in enumerate(zip(FIELD_NAMES, self.fields)):
            x0  = margin + i * (cell_w + gap)
            x1  = x0 + cell_w
            y1  = y0 + cell_h
            sel = i == self.field_sel

            bg_col  = (50, 50, 80) if sel else (20, 20, 20)
            out_col = BLUE if sel else SEP
            d.rounded_rectangle([(x0, y0), (x1, y1)], radius=5,
                                 fill=bg_col, outline=out_col, width=2 if sel else 1)

            # Value — bigger font, centered
            val_s = f"{val:04d}" if i == 4 else f"{val:02d}"
            vw, vh = self._ts(d, val_s, self.font_label)
            cx = x0 + (cell_w - vw) // 2
            d.text((cx, y0 + 10), val_s, font=self.font_label,
                   fill=WHITE if sel else GRAY)

            # Field name at bottom of box
            lw, lh = self._ts(d, name, self.font_label)
            d.text((x0 + (cell_w - lw) // 2, y1 - lh - 4),
                   name, font=self.font_label,
                   fill=BLUE if sel else (70, 70, 70))

            # Arrow above/below selected
            if sel:
                aw, ah = self._ts(d, "^", self.font_label)
                cx2 = x0 + (cell_w - aw) // 2
                d.text((cx2, y0 - ah - 1), "^", font=self.font_label, fill=BLUE)
                d.text((cx2, y1 + 1),       "v", font=self.font_label, fill=BLUE)

        self.hw.show(img)

    def _draw_stat(self):
        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        self._header(d, W, "Date & Time")

        color = GREEN if self.status_ok else RED
        icon  = "OK" if self.status_ok else "ERR"
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, TOP_BAR_H + 18), icon, font=self.font_big, fill=color)

        y = TOP_BAR_H + 18 + ih + 10
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, y), line, font=self.font_label, fill=WHITE)
            y += lh + 4

        hint = "Any key: back"
        hw, hh = self._ts(d, hint, self.font_label)
        d.text(((W - hw) // 2, H - hh - 4), hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
