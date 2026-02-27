"""
apps/tools/payload/app.py
USB HID Payload Injector — runs Ducky Script 3.0 payloads.

Payload files: apps/tools/payload/payloads/*.ds (or *.payload)

Controls:
  LIST screen:
    UP / DOWN   — scroll list
    CENTER      — open payload preview
    KEY1        — refresh list
    KEY3        — exit

  PREVIEW screen:
    UP / DOWN   — scroll content
    CENTER      — execute (3s countdown)
    KEY3        — back to list

  RUN screen:
    KEY3        — back (only after execution finishes)
"""

import os
import time
import threading
from PIL import Image, ImageDraw

from apps.tools.payload import ducky

TOP_H = 26
BOT_H = 18
ROW_H = 22

BG      = (4,   8,   16)
HDR_BG  = (8,   14,  28)
SEL_BG  = (12,  25,  50)
SEP     = (25,  45,  75)
SEP_HI  = (50,  90,  140)
WHITE   = (220, 235, 255)
DIM     = (70,  100, 140)
HINT    = (50,  75,  110)
CYAN    = (0,   210, 255)
GREEN   = (50,  220, 120)
YELLOW  = (255, 200, 50)
RED     = (255, 70,  70)
ORANGE  = (255, 140, 30)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAYLOADS_DIR = os.path.join(BASE_DIR, "menu_fs", "04_files", "payloads")
HID_DEVICE   = "/dev/hidg0"

SCREEN_LIST    = "list"
SCREEN_PREVIEW = "preview"
SCREEN_RUN     = "run"


def _list_payloads() -> list:
    os.makedirs(PAYLOADS_DIR, exist_ok=True)
    files = [f for f in os.listdir(PAYLOADS_DIR)
             if f.endswith(".ds") or f.endswith(".payload")]
    return sorted(files)


def _read_lines(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [l.rstrip() for l in f.readlines()]
    except Exception:
        return ["(error reading file)"]


def _line_color(line: str):
    """Syntax highlight color for a payload line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("REM") or \
       stripped.startswith("//") or stripped.startswith("#"):
        return (60, 80, 110)   # comment — blue-gray
    cmd = stripped.split()[0].upper()
    if cmd in ("STRING", "TYPE", "STRINGLN"):
        return (50, 220, 120)  # green — text output
    if cmd == "DELAY":
        return (255, 200, 50)  # yellow — timing
    if cmd in ("VAR", "IF", "ELSE", "END_IF", "WHILE",
               "END_WHILE", "FUNCTION", "END_FUNCTION"):
        return (160, 80, 255)  # purple — control flow
    if cmd in ("ENTER", "TAB", "SPACE", "BACKSPACE",
               "ESC", "DELETE", "UP", "DOWN", "LEFT", "RIGHT"):
        return (0, 210, 255)   # cyan — keys
    if any(stripped.upper().startswith(m) for m in
           ("GUI", "WIN", "CTRL", "ALT", "SHIFT")):
        return (255, 140, 30)  # orange — modifiers
    if stripped.startswith("$"):
        return (220, 180, 255) # light purple — variable
    return (220, 235, 255)     # white — default


class PayloadApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen       = SCREEN_LIST
        self.payloads     = []
        self.sel          = 0
        self.list_scroll  = 0
        self.prev_scroll  = 0
        self.prev_lines   = []
        self.selected     = None

        self._status_ok   = True
        self._status_msg  = ""
        self._running     = False
        self._countdown   = 0
        self._step_msg    = ""
        self._dirty       = True

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
        self.screen      = SCREEN_LIST
        self.payloads    = _list_payloads()
        self.sel         = 0
        self.list_scroll = 0
        self._dirty      = True

    def on_event(self, event) -> str:
        if self.screen == SCREEN_LIST:
            return self._ev_list(event)
        elif self.screen == SCREEN_PREVIEW:
            return self._ev_preview(event)
        elif self.screen == SCREEN_RUN:
            return self._ev_run(event)
        return "stay"

    def _ev_list(self, event) -> str:
        if event == "KEY3":
            return "exit"
        if event == "KEY1":
            self.payloads    = _list_payloads()
            self.list_scroll = 0
            self.sel         = 0
            self._dirty      = True
        elif event == "UP" and self.sel > 0:
            self.sel -= 1
            self._fix_list_scroll()
            self._dirty = True
        elif event == "DOWN" and self.sel < len(self.payloads) - 1:
            self.sel += 1
            self._fix_list_scroll()
            self._dirty = True
        elif event == "CENTER" and self.payloads:
            self.selected   = self.payloads[self.sel]
            path            = os.path.join(PAYLOADS_DIR, self.selected)
            self.prev_lines = _read_lines(path)
            self.prev_scroll = 0
            self.screen     = SCREEN_PREVIEW
            self._dirty     = True
        return "stay"

    def _ev_preview(self, event) -> str:
        if event == "KEY3":
            self.screen = SCREEN_LIST
            self._dirty = True
            return "stay"
        max_r = self._max_rows()
        if event == "UP" and self.prev_scroll > 0:
            self.prev_scroll -= 1
            self._dirty = True
        elif event == "DOWN":
            if self.prev_scroll < max(0, len(self.prev_lines) - max_r):
                self.prev_scroll += 1
                self._dirty = True
        elif event == "CENTER" and not self._running:
            self._countdown = 3
            self._running   = True
            self.screen     = SCREEN_RUN
            self._dirty     = True
            threading.Thread(target=self._run, daemon=True).start()
        return "stay"

    def _ev_run(self, event) -> str:
        if event == "KEY3" and not self._running:
            self.screen = SCREEN_LIST
            self._dirty = True
        return "stay"

    def _run(self):
        for i in range(3, 0, -1):
            self._countdown = i
            self._dirty     = True
            time.sleep(1)
        self._countdown = 0
        self._step_msg  = "Starting..."
        self._dirty     = True

        path    = os.path.join(PAYLOADS_DIR, self.selected)
        ok, msg = ducky.execute(path, status_cb=self._on_step)

        self._status_ok  = ok
        self._status_msg = msg
        self._running    = False
        self._step_msg   = ""
        self._dirty      = True

    def _on_step(self, msg: str):
        self._step_msg = msg
        self._dirty    = True

    def update(self, dt):
        pass

    # ── Helpers ───────────────────────────────────────────────

    def _max_rows(self):
        return (self.hw.H - TOP_H - BOT_H) // ROW_H

    def _fix_list_scroll(self):
        max_r = self._max_rows()
        if self.sel < self.list_scroll:
            self.list_scroll = self.sel
        elif self.sel >= self.list_scroll + max_r:
            self.list_scroll = self.sel - max_r + 1

    # ── Draw ──────────────────────────────────────────────────

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        self._draw_header(d, W)

        y0 = TOP_H
        if self.screen == SCREEN_LIST:
            self._draw_list(d, W, H, y0)
        elif self.screen == SCREEN_PREVIEW:
            self._draw_preview(d, W, H, y0)
        elif self.screen == SCREEN_RUN:
            self._draw_run(d, W, H, y0)

        self._draw_bottom(d, W, H)
        self.hw.show(img)

    def _draw_header(self, d, W):
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=ORANGE)
        tw, th = self._ts(d, "PAYLOADS", self.font_label)
        d.text((10, (TOP_H - th) // 2), "PAYLOADS",
               font=self.font_label, fill=ORANGE)

        hid_ok = os.path.exists(HID_DEVICE)
        s_str  = "● HID OK" if hid_ok else "● NO HID"
        sc     = GREEN if hid_ok else RED
        sw, sh = self._ts(d, s_str, self.font_label)
        d.text((W - sw - 6, (TOP_H - sh) // 2), s_str,
               font=self.font_label, fill=sc)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    def _draw_bottom(self, d, W, H):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hints = {
            SCREEN_LIST:    "UP/DN:select  CTR:open  K3:exit",
            SCREEN_PREVIEW: "UP/DN:scroll  CTR:run  K3:back",
            SCREEN_RUN:     "" if self._running else "K3:back",
        }
        hint = hints.get(self.screen, "")
        if hint:
            hint = self._trunc(d, hint, self.font_label, W - 4)
            hw2, hh2 = self._ts(d, hint, self.font_label)
            d.text(((W - hw2) // 2, H - hh2 - 2),
                   hint, font=self.font_label, fill=HINT)

    def _draw_list(self, d, W, H, y0):
        MARGIN   = 5
        max_rows = self._max_rows()

        if not self.payloads:
            msg = "No payload files found"
            mw, mh = self._ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, y0 + 24), msg,
                   font=self.font_label, fill=DIM)
            sub = f"Add .ds files to payloads/"
            sw, _ = self._ts(d, sub, self.font_label)
            d.text(((W - sw) // 2, y0 + 24 + mh + 6), sub,
                   font=self.font_label, fill=HINT)
            return

        # Counter
        cnt = f"{len(self.payloads)} files"
        cw, _ = self._ts(d, cnt, self.font_label)
        d.text((W - cw - 5, y0 + 3), cnt,
               font=self.font_label, fill=DIM)

        y = y0 + 4
        visible = self.payloads[self.list_scroll: self.list_scroll + max_rows]

        for i, name in enumerate(visible):
            idx    = self.list_scroll + i
            is_sel = idx == self.sel
            y1     = y + ROW_H

            if is_sel:
                d.rectangle([(0, y), (W, y1 - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (2, y1 - 1)], fill=ORANGE)

            # Strip extension
            display = re.sub(r'\.(ds|payload)$', '', name)
            col     = ORANGE if is_sel else WHITE
            display = self._trunc(d, display, self.font_label, W - MARGIN * 2 - 14)
            d.text((MARGIN + 4, y + (ROW_H - self.font_label.size) // 2),
                   display, font=self.font_label, fill=col)

            if is_sel:
                aw, ah = self._ts(d, ">", self.font_label)
                d.text((W - aw - 5, y + (ROW_H - ah) // 2),
                       ">", font=self.font_label, fill=ORANGE)

            d.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)
            y += ROW_H

        if len(self.payloads) > max_rows:
            ah = H - BOT_H - y0
            bh = max(10, int(ah * max_rows / len(self.payloads)))
            by = y0 + int((ah - bh) * self.list_scroll /
                          max(1, len(self.payloads) - max_rows))
            d.rectangle([W - 3, by, W - 1, by + bh], fill=DIM)

    def _draw_preview(self, d, W, H, y0):
        MARGIN = 5
        lh     = self.font_label.size + 4
        max_r  = (H - BOT_H - y0 - lh - 6) // lh

        # Filename banner
        name = re.sub(r'\.(ds|payload)$', '', self.selected or "")
        d.rectangle([(0, y0), (W, y0 + lh + 4)], fill=(8, 20, 40))
        d.text((MARGIN, y0 + 2), name, font=self.font_label, fill=ORANGE)
        cnt = f"{len(self.prev_lines)}L"
        cw, _ = self._ts(d, cnt, self.font_label)
        d.text((W - cw - 5, y0 + 2), cnt, font=self.font_label, fill=DIM)
        d.line([(0, y0 + lh + 4), (W, y0 + lh + 4)], fill=SEP, width=1)

        content_y = y0 + lh + 6
        visible   = self.prev_lines[self.prev_scroll: self.prev_scroll + max_r]
        y = content_y

        for line in visible:
            col     = _line_color(line)
            display = self._trunc(d, line, self.font_label, W - MARGIN * 2)
            d.text((MARGIN, y), display, font=self.font_label, fill=col)
            y += lh

        if len(self.prev_lines) > max_r:
            ah = H - BOT_H - content_y
            bh = max(10, int(ah * max_r / len(self.prev_lines)))
            by = content_y + int((ah - bh) * self.prev_scroll /
                                 max(1, len(self.prev_lines) - max_r))
            d.rectangle([W - 3, by, W - 1, by + bh], fill=DIM)

    def _draw_run(self, d, W, H, y0):
        MARGIN = 6
        cy     = y0 + (H - BOT_H - y0) // 2

        if self._countdown > 0:
            msg = "Aim cursor, running in..."
            mw, mh = self._ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, cy - 44), msg,
                   font=self.font_label, fill=HINT)
            num     = str(self._countdown)
            nw, nh  = self._ts(d, num, self.font_big)
            d.text(((W - nw) // 2, cy - nh // 2), num,
                   font=self.font_big, fill=YELLOW)
            name = re.sub(r'\.(ds|payload)$', '', self.selected or "")
            naw, _ = self._ts(d, name, self.font_label)
            d.text(((W - naw) // 2, cy + nh // 2 + 8), name,
                   font=self.font_label, fill=ORANGE)

        elif self._running:
            msg = "Executing..."
            mw, mh = self._ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, cy - mh - 6), msg,
                   font=self.font_label, fill=CYAN)
            if self._step_msg:
                step = self._trunc(d, self._step_msg, self.font_label, W - MARGIN * 2)
                sw, sh = self._ts(d, step, self.font_label)
                d.text(((W - sw) // 2, cy + 6), step,
                       font=self.font_label, fill=DIM)
        else:
            icon  = "OK" if self._status_ok else "ERR"
            color = GREEN if self._status_ok else RED
            iw, ih = self._ts(d, icon, self.font_big)
            d.text(((W - iw) // 2, cy - ih - 6), icon,
                   font=self.font_big, fill=color)
            for j, line in enumerate(self._status_msg.split("\n")):
                lw, lh = self._ts(d, line, self.font_label)
                d.text(((W - lw) // 2, cy + 4 + j * (lh + 3)), line,
                       font=self.font_label, fill=WHITE)


import re
