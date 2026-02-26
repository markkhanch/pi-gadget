"""
apps/settings/usb_mode/app.py
USB Gadget Mode switcher.
When in storage mode — shows lock screen with Eject button.

Controls:
  SELECT screen:
    UP / DOWN  — select mode
    CENTER     — apply
    KEY3       — exit

  STORAGE LOCK screen:
    CENTER / KEY3 — eject (sync files back, disable gadget)
"""

import os
import subprocess
import threading
from PIL import Image, ImageDraw

TOP_H = 26
BOT_H = 18
ROW_H = 38

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

SETUP_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "scripts", "usb_gadget_setup.sh"
)

MODES = [
    {"id": "keyboard", "label": "HID Keyboard",    "desc": "Emulate USB keyboard", "color": CYAN},
    {"id": "storage",  "label": "USB Flash Drive", "desc": "Share files via USB",   "color": YELLOW},
    {"id": "off",      "label": "Disabled",         "desc": "Turn off USB gadget",  "color": DIM},
]

STATE_SELECT  = "select"
STATE_LOADING = "loading"
STATE_RESULT  = "result"
STATE_STORAGE = "storage"   # lock screen while in storage mode
STATE_EJECTING = "ejecting"


class UsbModeApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw    = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.sel     = 0
        self.current = "off"
        self.state   = STATE_SELECT
        self.ok      = True
        self.msg     = ""
        self._dirty  = True

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

    def on_enter(self):
        self.current = self._detect_mode()
        for i, m in enumerate(MODES):
            if m["id"] == self.current:
                self.sel = i
                break
        # If already in storage mode — show lock screen
        if self.current == "storage":
            self.state = STATE_STORAGE
        else:
            self.state = STATE_SELECT
        self._dirty = True

    def _detect_mode(self) -> str:
        gadget = "/sys/kernel/config/usb_gadget/pigadget"
        try:
            if not os.path.exists(gadget):
                return "off"
            if os.path.exists(f"{gadget}/functions/hid.usb0"):
                return "keyboard"
            if os.path.exists(f"{gadget}/functions/mass_storage.0"):
                return "storage"
        except Exception:
            pass
        return "off"

    def _run_script(self, mode_id: str, on_done=None):
        """Run usb_gadget_setup.sh in background thread."""
        script = os.path.realpath(SETUP_SCRIPT)
        try:
            r = subprocess.run(
                ["sudo", "bash", script, mode_id],
                capture_output=True, timeout=30
            )
            out = (r.stdout + r.stderr).decode("utf-8", errors="ignore").strip()
            ok  = r.returncode == 0
            msg = out[-60:] if not ok and out else mode_id
        except Exception as e:
            ok  = False
            msg = str(e)[:60]
        if on_done:
            on_done(ok, msg)

    def on_event(self, event) -> str:
        # Storage lock screen — only eject allowed
        if self.state == STATE_STORAGE:
            if event in ("CENTER", "KEY3"):
                self.state  = STATE_EJECTING
                self._dirty = True
                threading.Thread(
                    target=self._run_script,
                    args=("eject", self._on_eject_done),
                    daemon=True
                ).start()
            return "stay"

        if self.state == STATE_EJECTING:
            return "stay"

        if self.state == STATE_LOADING:
            return "stay"

        if self.state == STATE_RESULT:
            # If we just enabled storage — go to lock screen
            if self.ok and self.current == "storage":
                self.state  = STATE_STORAGE
            else:
                self.state  = STATE_SELECT
            self._dirty = True
            return "stay"

        # SELECT screen
        if event == "KEY3":
            return "exit"
        if event == "UP" and self.sel > 0:
            self.sel   -= 1
            self._dirty = True
        elif event == "DOWN" and self.sel < len(MODES) - 1:
            self.sel   += 1
            self._dirty = True
        elif event == "CENTER":
            mode_id     = MODES[self.sel]["id"]
            self.state  = STATE_LOADING
            self._dirty = True
            threading.Thread(
                target=self._run_script,
                args=(mode_id, self._on_apply_done),
                daemon=True
            ).start()
        return "stay"

    def _on_apply_done(self, ok: bool, msg: str):
        self.ok     = ok
        self.msg    = msg
        if ok:
            self.current = MODES[self.sel]["id"]
        self.state  = STATE_RESULT
        self._dirty = True

    def _on_eject_done(self, ok: bool, msg: str):
        self.current = "off"
        self.ok      = ok
        self.msg     = "Files synced!" if ok else msg
        self.state   = STATE_RESULT
        self._dirty  = True

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=ORANGE)
        tw, th = self._ts(d, "USB MODE", self.font_label)
        d.text((10, (TOP_H - th) // 2), "USB MODE",
               font=self.font_label, fill=ORANGE)
        cur = f"now: {self.current}"
        cw, ch = self._ts(d, cur, self.font_label)
        d.text((W - cw - 6, (TOP_H - ch) // 2), cur,
               font=self.font_label, fill=DIM)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_LOADING:
            self._draw_message(d, W, H, "Applying...", CYAN)

        elif self.state == STATE_EJECTING:
            self._draw_message(d, W, H, "Ejecting...\nSyncing files...", YELLOW)

        elif self.state == STATE_RESULT:
            cy = TOP_H + (H - TOP_H - BOT_H) // 2
            icon  = "OK" if self.ok else "ERR"
            color = GREEN if self.ok else RED
            iw, ih = self._ts(d, icon, self.font_big)
            d.text(((W - iw) // 2, cy - ih - 4), icon,
                   font=self.font_big, fill=color)
            for j, line in enumerate(self.msg.split("\n")):
                lw, lh = self._ts(d, line, self.font_label)
                d.text(((W - lw) // 2, cy + 4 + j * (lh + 3)),
                       line, font=self.font_label, fill=WHITE)
            hint = "Any key: continue"
            hw2, hh2 = self._ts(d, hint, self.font_label)
            d.text(((W - hw2) // 2, H - hh2 - 4),
                   hint, font=self.font_label, fill=HINT)

        elif self.state == STATE_STORAGE:
            self._draw_storage_lock(d, W, H)

        else:
            self._draw_select(d, W, H)

        self.hw.show(img)

    def _draw_message(self, d, W, H, msg, color):
        cy = TOP_H + (H - TOP_H - BOT_H) // 2
        for j, line in enumerate(msg.split("\n")):
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, cy - lh + j * (lh + 4)),
                   line, font=d._image.info.get("font", self.font_label),
                   fill=color)
        # Re-draw properly
        cy = TOP_H + (H - TOP_H) // 2
        lines = msg.split("\n")
        total_h = len(lines) * (self.font_label.size + 4)
        y = cy - total_h // 2
        for line in lines:
            lw, lh = self._ts(d, line, self.font_label)
            d.text(((W - lw) // 2, y), line, font=self.font_label, fill=color)
            y += lh + 4

    def _draw_storage_lock(self, d, W, H):
        """Lock screen shown while in USB storage mode."""
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        # Big USB icon
        icon = "[USB]"
        iw, ih = self._ts(d, icon, self.font_big)
        d.text(((W - iw) // 2, cy - ih - 24), icon,
               font=self.font_big, fill=YELLOW)

        # Status
        msg = "Connected"
        mw, mh = self._ts(d, msg, self.font_label)
        d.text(((W - mw) // 2, cy - 8), msg,
               font=self.font_label, fill=GREEN)

        sub = "Files accessible from PC"
        sw, sh = self._ts(d, sub, self.font_label)
        d.text(((W - sw) // 2, cy + mh + 2), sub,
               font=self.font_label, fill=DIM)

        # Eject button
        btn = "[ EJECT ]"
        bw, bh = self._ts(d, btn, self.font_label)
        by = H - BOT_H - bh - 8
        d.rectangle([(W//2 - bw//2 - 8, by - 4),
                     (W//2 + bw//2 + 8, by + bh + 4)],
                    fill=(20, 40, 10), outline=GREEN, width=1)
        d.text(((W - bw) // 2, by), btn,
               font=self.font_label, fill=GREEN)

        hint = "CTR or K3: eject"
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT)

    def _draw_select(self, d, W, H):
        MARGIN = 8
        y = TOP_H + 4
        for i, mode in enumerate(MODES):
            is_sel    = i == self.sel
            is_active = mode["id"] == self.current
            if is_sel:
                d.rectangle([(0, y), (W, y + ROW_H - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (3, y + ROW_H - 1)], fill=mode["color"])
            lc = WHITE if is_sel else DIM
            lw, lh = self._ts(d, mode["label"], self.font_label)
            d.text((MARGIN + 4, y + 4), mode["label"],
                   font=self.font_label, fill=lc)
            d.text((MARGIN + 4, y + 4 + lh + 2), mode["desc"],
                   font=self.font_label, fill=HINT)
            if is_active:
                ck = "✓"
                ckw, ckh = self._ts(d, ck, self.font_label)
                d.text((W - ckw - MARGIN, y + (ROW_H - ckh) // 2),
                       ck, font=self.font_label, fill=GREEN)
            d.line([(0, y + ROW_H - 1), (W, y + ROW_H - 1)], fill=SEP, width=1)
            y += ROW_H

        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hint = "UP/DN:select  CTR:apply  K3:exit"
        hint = self._trunc(d, hint, self.font_label, W - 4)
        hw2, hh2 = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh2 - 2),
               hint, font=self.font_label, fill=HINT)
