"""
apps/bad_stuff/recon/cracker/app.py
WPA2 Hash Cracker — dictionary attack using aircrack-ng.

Workflow:
  1. Select a .cap file from handshakes/
  2. Select a wordlist from wordlists/
  3. Run aircrack-ng in background or foreground
  4. Results saved to cracked/

Controls:
  SELECT_CAP / SELECT_WL:  UP/DOWN navigate  CTR select  K3 back/exit
  CRACKING:                K3 background  K1 stop
  DONE:                    K3 back
"""

import os
import re
import time
import logging
import threading
import subprocess
import datetime
from PIL import Image, ImageDraw
from core.background import bgm

log = logging.getLogger("cracker")

TOP_H = 26
BOT_H = 18

BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
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
GRAY   = (100, 100, 120)

RESOURCES = ["cpu_crack"]
APP_NAME  = "Cracker"

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )
)

HANDSHAKES_DIR = os.path.join(BASE_DIR, "menu_fs", "02_files", "handshakes")
WORDLISTS_DIR  = os.path.join(BASE_DIR, "menu_fs", "02_files", "wordlists")
CRACKED_DIR    = os.path.join(BASE_DIR, "menu_fs", "02_files", "cracked")

STATE_SELECT_CAP  = "select_cap"
STATE_SELECT_WL   = "select_wl"
STATE_CRACKING    = "cracking"
STATE_DONE        = "done"

VISIBLE_ROWS = 7   # How many list rows fit on screen


def _ts(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def _trunc(draw, text, font, max_w):
    while text:
        w, _ = _ts(draw, text, font)
        if w <= max_w:
            return text
        text = text[:-2] + "…"
    return ""


def _list_caps() -> list:
    """List .cap files from handshakes dir, newest first."""
    os.makedirs(HANDSHAKES_DIR, exist_ok=True)
    files = [
        f for f in os.listdir(HANDSHAKES_DIR)
        if f.endswith(".cap")
    ]
    files.sort(reverse=True)
    return files


def _list_wordlists() -> list:
    """List .txt wordlist files, alphabetical."""
    os.makedirs(WORDLISTS_DIR, exist_ok=True)
    files = [
        f for f in os.listdir(WORDLISTS_DIR)
        if f.endswith(".txt")
    ]
    files.sort()
    return files


class CrackerApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_SELECT_CAP
        self._dirty = True

        # File selection
        self._caps      = []
        self._wordlists = []
        self._cap_idx   = 0
        self._wl_idx    = 0
        self._cap_scroll = 0
        self._wl_scroll  = 0

        # Selected files
        self._selected_cap = ""
        self._selected_wl  = ""

        # Cracking
        self._proc         = None
        self._proc_lock    = threading.Lock()
        self._start_time   = 0
        self._tried        = 0     # passwords tried (parsed from output)
        self._speed        = ""    # k/s speed string
        self._result       = ""    # cracked password or "Not found"
        self._result_color = WHITE
        self._status_line  = ""    # last status from aircrack

        self._last_redraw = 0
        self._done_ts     = ""

    def on_enter(self):
        self._caps      = _list_caps()
        self._wordlists = _list_wordlists()
        self._cap_idx   = 0
        self._wl_idx    = 0
        self._cap_scroll = 0
        self._wl_scroll  = 0
        self.state  = STATE_SELECT_CAP
        self._dirty = True

    def on_exit(self):
        self._kill_proc()
        bgm.unregister(APP_NAME)

    # ── Cracking ──────────────────────────────────────────────

    def _start_crack(self):
        cap_path = os.path.join(HANDSHAKES_DIR, self._selected_cap)
        wl_path  = os.path.join(WORDLISTS_DIR,  self._selected_wl)

        if not os.path.exists(cap_path):
            self._result       = "CAP file not found"
            self._result_color = RED
            self.state  = STATE_DONE
            self._dirty = True
            return

        if not os.path.exists(wl_path):
            self._result       = "Wordlist not found"
            self._result_color = RED
            self.state  = STATE_DONE
            self._dirty = True
            return

        os.makedirs(CRACKED_DIR, exist_ok=True)

        self._start_time  = time.time()
        self._tried       = 0
        self._speed       = ""
        self._result      = ""
        self._status_line = "Starting..."
        self.state  = STATE_CRACKING
        self._dirty = True

        bgm.register(APP_NAME, RESOURCES, self._kill_proc,
                     instance=self, module="bad_stuff.recon.cracker")

        def _run():
            try:
                cmd = [
                    "aircrack-ng",
                    "-w", wl_path,
                    cap_path,
                ]
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )

                # Parse live output
                for line in self._proc.stdout:
                    # Strip ANSI escape sequences from aircrack-ng output
                    line = re.sub(r"\[[0-9;]*[A-Za-z]", "", line)
                    line = re.sub(r"\[[0-9]*[A-Z]",     "", line)
                    line = line.strip()
                    if not line:
                        continue

                    # Extract keys tested count
                    m = re.search(r"(\d+)\s+keys tested", line)
                    if m:
                        self._tried = int(m.group(1))

                    # Extract speed
                    m2 = re.search(r"([\d.]+\s*k?/s)", line, re.IGNORECASE)
                    if m2:
                        self._speed = m2.group(1)

                    # Key found
                    if "KEY FOUND" in line.upper():
                        m3 = re.search(r"\[\s*(.+?)\s*\]", line)
                        if m3:
                            pwd = m3.group(1)
                            self._result       = f"✓ {pwd}"
                            self._result_color  = GREEN
                            self._save_result(pwd)

                    # Truncate by chars — no draw object available in thread
                    self._status_line = line[:45] + "…" if len(line) > 45 else line
                    self._dirty = True

                rc = self._proc.wait()

                if not self._result:
                    if rc == 1:
                        # aircrack-ng exits 1 when no handshake found in cap
                        self._result       = "No handshake in CAP file"
                        self._result_color = RED
                    else:
                        self._result       = "Not found in wordlist"
                        self._result_color = YELLOW

            except Exception as e:
                log.error("aircrack-ng error: %s", e)
                self._result       = f"Error: {e}"
                self._result_color = RED
            finally:
                with self._proc_lock:
                    self._proc = None
                bgm.unregister(APP_NAME)
                self._done_ts = datetime.datetime.now().strftime("%H:%M:%S")
                self.state    = STATE_DONE
                self._dirty   = True

        threading.Thread(target=_run, daemon=True).start()

    def _kill_proc(self):
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def _save_result(self, password: str):
        """Save cracked password to cracked/ dir."""
        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        cap_name = os.path.splitext(self._selected_cap)[0]
        out_path = os.path.join(CRACKED_DIR, f"{cap_name}_{ts}.txt")
        try:
            with open(out_path, "w") as f:
                f.write(f"File:     {self._selected_cap}\n")
                f.write(f"Wordlist: {self._selected_wl}\n")
                f.write(f"Password: {password}\n")
                f.write(f"Time:     {ts}\n")
            log.info("Saved cracked result: %s", out_path)
        except Exception as e:
            log.warning("Save result failed: %s", e)

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_SELECT_CAP:
            if event == "KEY3":
                return "exit"
            elif event == "UP" and self._cap_idx > 0:
                self._cap_idx -= 1
                self._cap_scroll = max(0, min(self._cap_scroll,
                                              self._cap_idx))
                self._dirty = True
            elif event == "DOWN" and self._cap_idx < len(self._caps) - 1:
                self._cap_idx += 1
                if self._cap_idx >= self._cap_scroll + VISIBLE_ROWS:
                    self._cap_scroll += 1
                self._dirty = True
            elif event == "CENTER":
                if not self._caps:
                    return "stay"
                self._selected_cap = self._caps[self._cap_idx]
                self._wordlists    = _list_wordlists()
                self._wl_idx       = 0
                self._wl_scroll    = 0
                self.state  = STATE_SELECT_WL
                self._dirty = True

        elif self.state == STATE_SELECT_WL:
            if event == "KEY3":
                self.state  = STATE_SELECT_CAP
                self._dirty = True
            elif event == "UP" and self._wl_idx > 0:
                self._wl_idx -= 1
                self._wl_scroll = max(0, min(self._wl_scroll,
                                             self._wl_idx))
                self._dirty = True
            elif event == "DOWN" and self._wl_idx < len(self._wordlists) - 1:
                self._wl_idx += 1
                if self._wl_idx >= self._wl_scroll + VISIBLE_ROWS:
                    self._wl_scroll += 1
                self._dirty = True
            elif event == "CENTER":
                if not self._wordlists:
                    return "stay"
                self._selected_wl = self._wordlists[self._wl_idx]
                self._start_crack()

        elif self.state == STATE_CRACKING:
            if event == "KEY3":
                # Send to background
                return "background"
            elif event == "KEY1":
                # Stop cracking
                self._kill_proc()
                bgm.unregister(APP_NAME)
                self._result       = "Stopped by user"
                self._result_color = ORANGE
                self._done_ts      = datetime.datetime.now().strftime("%H:%M:%S")
                self.state  = STATE_DONE
                self._dirty = True

        elif self.state == STATE_DONE:
            if event == "KEY3":
                # Back to cap selection for another try
                self._caps   = _list_caps()
                self._cap_idx = 0
                self._cap_scroll = 0
                self.state  = STATE_SELECT_CAP
                self._dirty = True

        return "stay"

    def update(self, dt):
        if self.state == STATE_CRACKING:
            now = time.time()
            if now - self._last_redraw >= 1.0:
                self._last_redraw = now
                self._dirty = True

    # ── Draw ──────────────────────────────────────────────────

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        self._draw_header(d, W)

        if self.state == STATE_SELECT_CAP:
            self._draw_file_list(d, W, H, self._caps,
                                 self._cap_idx, self._cap_scroll,
                                 "Select .cap file",
                                 "No .cap files in handshakes/")
        elif self.state == STATE_SELECT_WL:
            self._draw_file_list(d, W, H, self._wordlists,
                                 self._wl_idx, self._wl_scroll,
                                 f"Wordlist for: {self._selected_cap}",
                                 "No wordlists in wordlists/\nAdd .txt files")
        elif self.state == STATE_CRACKING:
            self._draw_cracking(d, W, H)
        elif self.state == STATE_DONE:
            self._draw_done(d, W, H)

        self.hw.show(img)

    def _draw_header(self, d, W):
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=ORANGE)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "CRACKER", font=self.font_label, fill=ORANGE)

        badge_map = {
            STATE_SELECT_CAP: ("SELECT CAP",  DIM),
            STATE_SELECT_WL:  ("SELECT LIST", DIM),
            STATE_CRACKING:   ("● RUNNING",   GREEN),
            STATE_DONE:       ("DONE",        CYAN),
        }
        badge, col = badge_map.get(self.state, ("", DIM))
        bw, bh = _ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_file_list(self, d, W, H, files, idx, scroll, subtitle, empty_msg):
        M  = 6
        lh = self.font_label.size + 6
        y  = TOP_H + 4

        # Subtitle
        sub = _trunc(d, subtitle, self.font_label, W - M * 2)
        d.text((M, y), sub, font=self.font_label, fill=CYAN)
        y += lh + 2
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 4

        if not files:
            d.text((M, y), empty_msg, font=self.font_label, fill=DIM)
            self._hint(d, W, H, "K3:back")
            return

        visible = files[scroll:scroll + VISIBLE_ROWS]
        for i, fname in enumerate(visible):
            abs_idx = scroll + i
            is_sel  = (abs_idx == idx)
            col     = WHITE if is_sel else GRAY

            if is_sel:
                d.rectangle([(0, y - 1), (W, y + lh - 3)],
                             fill=(15, 25, 40))
                d.rectangle([(0, y - 1), (3, y + lh - 3)],
                             fill=CYAN)

            name = _trunc(d, fname, self.font_label, W - M * 2 - 4)
            d.text((M + 4, y), name, font=self.font_label, fill=col)
            y += lh

        # Scroll indicator
        if len(files) > VISIBLE_ROWS:
            bar_h  = H - TOP_H - BOT_H - 8
            bar_y  = TOP_H + 4
            thumb_h = max(8, bar_h * VISIBLE_ROWS // len(files))
            thumb_y = bar_y + bar_h * scroll // len(files)
            d.rectangle([(W - 3, bar_y), (W - 1, bar_y + bar_h)],
                         fill=(30, 30, 50))
            d.rectangle([(W - 3, thumb_y),
                          (W - 1, thumb_y + thumb_h)], fill=CYAN)

        self._hint(d, W, H, "▲▼ navigate   CTR:select   K3:back")

    def _draw_cracking(self, d, W, H):
        M  = 8
        y  = TOP_H + 6
        lh = self.font_label.size + 5

        # Files being used
        cap = _trunc(d, f"CAP: {self._selected_cap}",
                     self.font_label, W - M * 2)
        d.text((M, y), cap, font=self.font_label, fill=DIM)
        y += lh

        wl = _trunc(d, f"WL:  {self._selected_wl}",
                    self.font_label, W - M * 2)
        d.text((M, y), wl, font=self.font_label, fill=DIM)
        y += lh + 4

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        # Elapsed time
        elapsed = int(time.time() - self._start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        d.text((M, y), f"Time: {h:02d}:{m:02d}:{s:02d}",
               font=self.font_label, fill=CYAN)
        y += lh

        # Keys tried + speed
        if self._tried:
            tried_str = f"{self._tried:,} keys"
            if self._speed:
                tried_str += f"  {self._speed}"
            d.text((M, y), tried_str, font=self.font_label, fill=WHITE)
            y += lh

        # Last status line
        if self._status_line:
            st = _trunc(d, self._status_line, self.font_label, W - M * 2)
            d.text((M, y), st, font=self.font_label, fill=GRAY)
            y += lh

        # Animated dots
        dots = "." * (int(time.time()) % 4)
        d.text((M, y), f"Cracking{dots}", font=self.font_label, fill=ORANGE)

        self._hint(d, W, H, "K1:stop  K3:background")

    def _draw_done(self, d, W, H):
        M  = 8
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        # Result (big)
        rw, rh = _ts(d, self._result, self.font_label)
        d.text(((W - rw) // 2, cy - rh - 10),
               self._result, font=self.font_label, fill=self._result_color)

        # Files used
        cap = _trunc(d, self._selected_cap, self.font_label, W - M * 2)
        wl  = _trunc(d, self._selected_wl,  self.font_label, W - M * 2)
        d.text((M, cy + 8),  cap, font=self.font_label, fill=DIM)
        d.text((M, cy + 8 + self.font_label.size + 4),
               wl, font=self.font_label, fill=DIM)

        # Timestamp
        if self._done_ts:
            tw, _ = _ts(d, self._done_ts, self.font_label)
            d.text((W - tw - M, TOP_H + 6),
                   self._done_ts, font=self.font_label, fill=GRAY)

        # If cracked — note saved
        if self._result.startswith("✓"):
            note = "Saved to cracked/"
            nw, _ = _ts(d, note, self.font_label)
            d.text(((W - nw) // 2, cy + 50),
                   note, font=self.font_label, fill=GREEN)

        self._hint(d, W, H, "K3:try another")
