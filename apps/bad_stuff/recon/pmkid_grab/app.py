"""
apps/bad_stuff/recon/pmkid_grab/app.py
PMKID Grabber — capture PMKIDs from access points without waiting for clients.

Uses hcxdumptool to send association requests and capture PMKID responses.
Much faster than waiting for a full EAPOL handshake.

Output saved to handshakes/ as .pcapng (use hcxpcapngtool to convert).

Controls:
  IDLE:    CTR:start  K3:exit
  RUNNING: K1:stop+save  K3:background
  DONE:    K3:back
"""

import os
import re
import time
import shutil
import logging
import tempfile
import threading
import subprocess
import datetime
from PIL import Image, ImageDraw
from core.background import bgm

log = logging.getLogger("pmkid_grab")

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
PURPLE = (200, 100, 255)
GRAY   = (100, 100, 120)

RESOURCES       = ["wlan1_monitor"]
APP_NAME        = "PMKID Grab"
PREFERRED_IFACE = "wlan1"

STATE_IDLE    = "idle"
STATE_RUNNING = "running"
STATE_DONE    = "done"

# Poll interval for reading hcxdumptool output
POLL_INTERVAL = 2.0

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )
)

OUTPUT_DIR = os.path.join(BASE_DIR, "menu_fs", "02_files", "handshakes")


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


def _fmt_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _iface_exists(iface):
    return os.path.exists(f"/sys/class/net/{iface}")


def _is_monitor(iface):
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, timeout=5)
        return "type monitor" in r.stdout.decode()
    except Exception:
        return False


def _enable_monitor(iface):
    try:
        subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "iw", iface, "set", "monitor", "control"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                       timeout=5, capture_output=True)
        return _is_monitor(iface)
    except Exception as e:
        log.warning("_enable_monitor: %s", e)
        return False


def _kill_proc(proc):
    if proc is None:
        return
    try:
        subprocess.run(["sudo", "kill", "-TERM", str(proc.pid)],
                       capture_output=True, timeout=3)
        proc.wait(timeout=3)
    except Exception:
        try:
            subprocess.run(["sudo", "kill", "-KILL", str(proc.pid)],
                           capture_output=True, timeout=3)
        except Exception:
            pass


def _count_pmkids(pcapng_path: str) -> int:
    """Count PMKID hashes in a .pcapng file using hcxpcapngtool."""
    if not os.path.exists(pcapng_path):
        return 0
    try:
        tmpdir = tempfile.mkdtemp()
        out    = os.path.join(tmpdir, "out.hc22000")
        r = subprocess.run(
            ["hcxpcapngtool", "-o", out, pcapng_path],
            capture_output=True, timeout=15
        )
        stdout = r.stdout.decode("utf-8", errors="ignore")
        # Count lines in hash file
        count = 0
        if os.path.exists(out):
            with open(out) as f:
                count = sum(1 for line in f
                            if line.startswith("WPA*01*") or line.startswith("WPA*02*"))
        shutil.rmtree(tmpdir, ignore_errors=True)
        return count
    except Exception as e:
        log.warning("_count_pmkids: %s", e)
        return 0


class PmkidGrabApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_IDLE
        self._dirty = True

        self._iface       = None
        self._adapter_ok  = False
        self._adapter_msg = "Checking..."

        self._proc       = None
        self._tmpdir     = None
        self._cap_path   = ""
        self._running    = False
        self._start_time = 0
        self._stop_evt   = threading.Event()
        self._lock       = threading.Lock()

        # Live stats from hcxdumptool output
        self._aps_seen   = 0
        self._pmkids     = 0
        self._eapols     = 0
        self._last_line  = ""

        # Final result
        self._result_pmkids = 0
        self._result_file   = ""

        self._last_redraw = 0

    def on_enter(self):
        self.state  = STATE_IDLE
        self._dirty = True
        threading.Thread(target=self._check_adapter, daemon=True).start()

    def on_exit(self):
        self._stop()

    def _check_adapter(self):
        iface = PREFERRED_IFACE if _iface_exists(PREFERRED_IFACE) else None
        if iface is None:
            self._adapter_ok  = False
            self._adapter_msg = "No adapter on wlan1"
        elif not _is_monitor(iface):
            ok = _enable_monitor(iface)
            self._iface       = iface if ok else None
            self._adapter_ok  = ok
            self._adapter_msg = f"{iface} ready" if ok else "Monitor mode failed"
        else:
            self._iface       = iface
            self._adapter_ok  = True
            self._adapter_msg = f"{iface} ready"
        self._dirty = True

    # ── Session ───────────────────────────────────────────────

    def _start(self):
        if not self._adapter_ok or not self._iface:
            return

        conflicts = bgm.conflicts_for(RESOURCES)
        if conflicts:
            self._adapter_msg = f"Conflict: {conflicts[0]}"
            self._dirty = True
            return

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._tmpdir  = tempfile.mkdtemp()
        ts            = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._cap_path = os.path.join(self._tmpdir, f"pmkid_{ts}.pcapng")

        self._aps_seen   = 0
        self._pmkids     = 0
        self._eapols     = 0
        self._last_line  = ""
        self._running    = True
        self._start_time = time.time()
        self._stop_evt.clear()
        self.state  = STATE_RUNNING
        self._dirty = True

        bgm.register(APP_NAME, RESOURCES, self._stop,
                     instance=self, module="bad_stuff.recon.pmkid_grab")

        def _capture():
            try:
                subprocess.run(
                    ["sudo", "nmcli", "device", "set",
                     self._iface, "managed", "no"],
                    capture_output=True, timeout=10
                )
                cmd = [
                    "sudo", "hcxdumptool",
                    "-i", self._iface,
                    "-w", self._cap_path,
                    "-F",          # scan all channels
                    "--rds=1",     # real time display sorted by status
                ]
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                log.info("hcxdumptool started on %s", self._iface)

                for line in self._proc.stdout:
                    if self._stop_evt.is_set():
                        break
                    line = line.strip()
                    if not line:
                        continue
                    self._parse_status(line)
                    self._dirty = True

                self._proc.wait()
            except Exception as e:
                log.error("hcxdumptool error: %s", e)
            finally:
                self._proc = None

        threading.Thread(target=_capture, daemon=True).start()

    def _parse_status(self, line: str):
        """
        Parse hcxdumptool real-time display output.
        Line format: CHA LAST R 1 3 P S MAC-AP ESSID
        Tracks unique MACs to avoid double-counting updated rows.
        """
        if not line:
            return
        stripped = line.strip()
        if stripped.startswith("CHA") or stripped.startswith("---") or                 stripped.startswith("LAST") or stripped.startswith("SCAN"):
            return

        parts = stripped.split()
        if len(parts) < 6:
            with self._lock:
                self._last_line = stripped[:50]
            return

        # MAC-AP is at index 5
        mac = parts[5].lower()
        if not re.match(r"[0-9a-f]{12}", mac):
            return

        with self._lock:
            if not hasattr(self, "_seen_macs"):
                self._seen_macs = {}

            prev = self._seen_macs.get(mac, {"pmkid": False, "eapol": False})

            has_pmkid = len(parts) > 3 and parts[3] == "+"
            has_eapol = len(parts) > 4 and parts[4] == "+"

            if has_pmkid and not prev["pmkid"]:
                self._pmkids += 1
                prev["pmkid"] = True

            if has_eapol and not prev["eapol"]:
                self._eapols += 1
                prev["eapol"] = True

            self._seen_macs[mac] = prev
            self._aps_seen = len(self._seen_macs)
            self._last_line = stripped[:50]

    def _stop(self):
        self._running = False
        self._stop_evt.set()
        _kill_proc(self._proc)
        self._proc = None

        # Count PMKIDs in captured file
        pmkids = _count_pmkids(self._cap_path)

        # Save to output dir if we got anything
        if os.path.exists(self._cap_path) and os.path.getsize(self._cap_path) > 0:
            ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name = f"pmkid_{ts}.pcapng"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            try:
                shutil.copy2(self._cap_path, out_path)
                self._result_file = out_name
                log.info("Saved: %s", out_path)
            except Exception as e:
                log.error("Save failed: %s", e)

        self._result_pmkids = pmkids

        try:
            subprocess.run(
                ["sudo", "nmcli", "device", "set",
                 self._iface or PREFERRED_IFACE, "managed", "yes"],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

        bgm.unregister(APP_NAME)
        self.state  = STATE_DONE
        self._dirty = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER" and self._adapter_ok:
                self._start()

        elif self.state == STATE_RUNNING:
            if event == "KEY3":
                return "background"
            elif event == "KEY1":
                self._stop()

        elif self.state == STATE_DONE:
            if event == "KEY3":
                self.state  = STATE_IDLE
                self._dirty = True

        return "stay"

    def update(self, dt):
        if self.state == STATE_RUNNING:
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

        # Header
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=PURPLE)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "PMKID GRAB", font=self.font_label, fill=PURPLE)

        badge_map = {
            STATE_IDLE:    ("IDLE",      DIM),
            STATE_RUNNING: ("● RUNNING", GREEN),
            STATE_DONE:    ("DONE",      CYAN),
        }
        badge, bcol = badge_map.get(self.state, ("", DIM))
        bw, bh = _ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=bcol)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        elif self.state == STATE_RUNNING:
            self._draw_running(d, W, H)
        elif self.state == STATE_DONE:
            self._draw_done(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        M  = 8
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        col = GREEN if self._adapter_ok else RED
        aw, ah = _ts(d, self._adapter_msg, self.font_label)
        d.text(((W - aw) // 2, cy - ah - 20),
               self._adapter_msg, font=self.font_label, fill=col)

        lines = [
            ("No client needed", DIM),
            ("Attacks AP directly", DIM),
            ("Saves .pcapng to handshakes/", DIM),
        ]
        y = cy - 4
        for text, tc in lines:
            tw, th = _ts(d, text, self.font_label)
            d.text(((W - tw) // 2, y), text, font=self.font_label, fill=tc)
            y += th + 4

        self._hint(d, W, H, "CTR:start  K3:exit")

    def _draw_running(self, d, W, H):
        M  = 8
        y  = TOP_H + 6
        lh = self.font_label.size + 6

        elapsed = int(time.time() - self._start_time)
        dw, _   = _ts(d, _fmt_duration(elapsed), self.font_label)
        d.text(((W - dw) // 2, y),
               _fmt_duration(elapsed), font=self.font_label, fill=CYAN)
        y += lh + 2

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        with self._lock:
            aps    = self._aps_seen
            pmkids = self._pmkids
            eapols = self._eapols
            last   = self._last_line

        rows = [
            (f"APs seen:  {aps}",    WHITE),
            (f"PMKIDs:    {pmkids}", GREEN if pmkids > 0 else DIM),
            (f"EAPOLs:    {eapols}", GREEN if eapols > 0 else DIM),
        ]
        for text, col in rows:
            d.text((M, y), text, font=self.font_label, fill=col)
            y += lh

        if last:
            y += 4
            d.line([(M, y), (W - M, y)], fill=SEP, width=1)
            y += 4
            st = _trunc(d, last, self.font_label, W - M * 2)
            d.text((M, y), st, font=self.font_label, fill=GRAY)

        self._hint(d, W, H, "K1:stop+save  K3:background")

    def _draw_done(self, d, W, H):
        M  = 8
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        elapsed = int(time.time() - self._start_time)

        if self._result_pmkids > 0:
            result     = f"✓ {self._result_pmkids} PMKIDs captured"
            result_col = GREEN
        else:
            result     = "No PMKIDs found"
            result_col = YELLOW

        rw, rh = _ts(d, result, self.font_label)
        d.text(((W - rw) // 2, cy - rh - 10),
               result, font=self.font_label, fill=result_col)

        dur = _fmt_duration(elapsed)
        dw, dh = _ts(d, dur, self.font_label)
        d.text(((W - dw) // 2, cy + 6),
               dur, font=self.font_label, fill=DIM)

        if self._result_file:
            tip = "Crack with Cracker app"
            tw, _ = _ts(d, tip, self.font_label)
            d.text(((W - tw) // 2, cy + 6 + dh + 8),
                   tip, font=self.font_label, fill=CYAN)

        self._hint(d, W, H, "K3:back")
