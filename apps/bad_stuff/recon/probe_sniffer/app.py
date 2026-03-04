"""
apps/bad_stuff/recon/probe_sniffer/app.py
Probe Request Sniffer — passively captures probe requests from nearby devices.

Uses airodump-ng CSV output to read station probe requests.
Shows which devices are searching for which networks.

Controls:
  IDLE:    CTR:start  K3:exit
  RUNNING: K1:sort toggle  UP/DOWN scroll  K3:background
"""

import os
import re
import csv
import time
import shutil
import logging
import tempfile
import threading
import subprocess
import datetime
from PIL import Image, ImageDraw
from core.background import bgm

log = logging.getLogger("probe_sniffer")

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
PURPLE = (160, 80,  255)
GRAY   = (100, 100, 120)

RESOURCES = ["wlan1_monitor"]
APP_NAME  = "Probe Sniffer"

PREFERRED_IFACE = "wlan1"
CSV_POLL        = 3    # seconds between CSV re-reads

STATE_IDLE    = "idle"
STATE_RUNNING = "running"

VISIBLE_ROWS = 6

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )
)

OUTPUT_DIR = os.path.join(BASE_DIR, "menu_fs", "02_files", "probe_sniffs")


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


def _fmt_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_airodump_csv(csv_path: str) -> list:
    """
    Parse airodump-ng CSV station section.
    Returns list of dicts: {mac, ssids, packets, last_seen}

    CSV station section starts after blank line following AP section.
    Header: Station MAC, First time seen, Last time seen, Power,
            # packets, BSSID, Probed ESSIDs
    """
    results = []
    if not os.path.exists(csv_path):
        return results

    try:
        with open(csv_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Split into AP block and Station block
        blocks = content.split("\r\n\r\n")
        if len(blocks) < 2:
            blocks = content.split("\n\n")
        if len(blocks) < 2:
            return results

        station_block = blocks[1]
        lines = station_block.strip().splitlines()
        if not lines:
            return results

        # Skip header line
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue

            mac       = parts[0].upper()
            last_seen = parts[2].strip()
            packets   = parts[4].strip()
            # Probed ESSIDs are everything from index 6 onward
            ssids_raw = ",".join(parts[6:]).strip() if len(parts) > 6 else ""

            # Validate MAC
            if not re.match(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac):
                continue

            # Split multiple probed ESSIDs
            ssids = [s.strip() for s in ssids_raw.split(",") if s.strip()]
            if not ssids:
                ssids = ["<broadcast>"]

            try:
                pkt_count = int(packets)
            except ValueError:
                pkt_count = 0

            results.append({
                "mac":       mac,
                "ssids":     ssids,
                "packets":   pkt_count,
                "last_seen": last_seen,
            })

    except Exception as e:
        log.warning("_parse_airodump_csv: %s", e)

    return results


class ProbeSnifferApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_IDLE
        self._dirty = True

        self._iface       = None
        self._adapter_ok  = False
        self._adapter_msg = "Checking..."

        self._proc      = None
        self._tmpdir    = None
        self._csv_path  = ""
        self._running   = False
        self._start_time = 0
        self._stop_evt  = threading.Event()
        self._lock      = threading.Lock()

        # Parsed station rows for display
        self._rows: list = []
        self._sort_by    = "packets"   # "packets" or "time"
        self._scroll     = 0

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

        self._tmpdir    = tempfile.mkdtemp()
        cap_base        = os.path.join(self._tmpdir, "probes")
        self._csv_path  = cap_base + "-01.csv"

        self._rows       = []
        self._scroll     = 0
        self._running    = True
        self._start_time = time.time()
        self._stop_evt.clear()
        self.state  = STATE_RUNNING
        self._dirty = True

        bgm.register(APP_NAME, RESOURCES, self._stop,
                     instance=self, module="bad_stuff.recon.probe_sniffer")

        def _capture():
            try:
                subprocess.run(
                    ["sudo", "nmcli", "device", "set",
                     self._iface, "managed", "no"],
                    capture_output=True, timeout=10
                )
                self._proc = subprocess.Popen(
                    [
                        "sudo", "airodump-ng",
                        "--band", "abg",
                        "--output-format", "csv",
                        "--write", cap_base,
                        "--write-interval", str(CSV_POLL),
                        self._iface,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info("Probe sniffer started on %s", self._iface)
                self._proc.wait()
            except Exception as e:
                log.error("Probe capture: %s", e)
            finally:
                self._proc = None

        def _poller():
            """Periodically re-read CSV and update display rows."""
            while not self._stop_evt.wait(CSV_POLL):
                rows = _parse_airodump_csv(self._csv_path)
                with self._lock:
                    self._rows = self._sort_rows(rows)
                self._dirty = True

        threading.Thread(target=_capture, daemon=True).start()
        threading.Thread(target=_poller,  daemon=True).start()

    def _sort_rows(self, rows: list) -> list:
        if self._sort_by == "packets":
            return sorted(rows, key=lambda r: r["packets"], reverse=True)
        else:
            return sorted(rows, key=lambda r: r["last_seen"], reverse=True)

    def _stop(self):
        self._running = False
        self._stop_evt.set()
        _kill_proc(self._proc)
        self._proc = None

        self._save_results()

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
        self.state  = STATE_IDLE
        self._dirty = True

    def _save_results(self):
        with self._lock:
            rows = list(self._rows)
        if not rows:
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"probes_{ts}.txt")
        try:
            with open(path, "w") as f:
                f.write(f"Probe Sniffer — {ts}\n")
                f.write(f"Duration: {_fmt_duration(int(time.time() - self._start_time))}\n")
                f.write(f"Devices: {len(rows)}\n\n")
                for r in rows:
                    ssids = ", ".join(r["ssids"])
                    f.write(f"{r['mac']}  {r['packets']:>4}pkt  {ssids}\n")
            log.info("Saved probes: %s", path)
        except Exception as e:
            log.warning("Save probes failed: %s", e)

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
                self._sort_by = "time" if self._sort_by == "packets" else "packets"
                with self._lock:
                    self._rows = self._sort_rows(self._rows)
                self._scroll = 0
                self._dirty  = True
            elif event == "UP" and self._scroll > 0:
                self._scroll -= 1
                self._dirty   = True
            elif event == "DOWN":
                with self._lock:
                    max_s = max(0, len(self._rows) - VISIBLE_ROWS)
                if self._scroll < max_s:
                    self._scroll += 1
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
        d.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "PROBE SNIFFER", font=self.font_label, fill=CYAN)

        badge, bcol = ("● LIVE", GREEN) if self.state == STATE_RUNNING else ("IDLE", DIM)
        bw, bh = _ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=bcol)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        else:
            self._draw_running(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        cy  = TOP_H + (H - TOP_H - BOT_H) // 2
        col = GREEN if self._adapter_ok else RED
        aw, ah = _ts(d, self._adapter_msg, self.font_label)
        d.text(((W - aw) // 2, cy - ah - 10),
               self._adapter_msg, font=self.font_label, fill=col)

        desc = "Who is looking for what networks"
        dw, _ = _ts(d, desc, self.font_label)
        d.text(((W - dw) // 2, cy + 6),
               desc, font=self.font_label, fill=DIM)

        self._hint(d, W, H, "CTR:start  K3:exit")

    def _draw_running(self, d, W, H):
        M  = 6
        lh = self.font_label.size + 4

        with self._lock:
            rows   = list(self._rows)
            scroll = self._scroll

        # Stats line
        elapsed  = int(time.time() - self._start_time)
        n_dev    = len(rows)
        sort_lbl = "pkt" if self._sort_by == "packets" else "time"
        stat     = f"{_fmt_duration(elapsed)}  {n_dev} devices  [{sort_lbl}]"
        d.text((M, TOP_H + 3), stat, font=self.font_label, fill=CYAN)

        y = TOP_H + lh + 6
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 4

        if not rows:
            tw, _ = _ts(d, "Listening...", self.font_label)
            d.text(((W - tw) // 2, y + 20),
                   "Listening...", font=self.font_label, fill=DIM)
        else:
            visible = rows[scroll:scroll + VISIBLE_ROWS]
            for row in visible:
                mac_short = row["mac"][-8:]
                pkt       = row["packets"]
                ssid      = row["ssids"][0] if row["ssids"] else ""

                # Packet count badge
                cnt_str = f"{pkt:>4}"
                cw, _   = _ts(d, cnt_str, self.font_label)
                d.text((W - cw - M, y), cnt_str,
                       font=self.font_label, fill=GRAY)

                # MAC + first SSID
                left_w = W - cw - M * 2 - 4
                line   = f"{mac_short} {ssid}"
                line   = _trunc(d, line, self.font_label, left_w)
                col    = GREEN if ssid and ssid != "<broadcast>" else DIM
                d.text((M, y), line, font=self.font_label, fill=col)
                y += lh

            # Scroll indicator
            total = len(rows)
            if total > VISIBLE_ROWS:
                bar_h = H - TOP_H - BOT_H - lh - 16
                bar_y = TOP_H + lh + 10
                th    = max(6, bar_h * VISIBLE_ROWS // total)
                ty    = bar_y + bar_h * scroll // total
                d.rectangle([(W - 3, bar_y), (W - 1, bar_y + bar_h)],
                             fill=(30, 30, 50))
                d.rectangle([(W - 3, ty), (W - 1, ty + th)], fill=CYAN)

        self._hint(d, W, H, "K1:sort  ▲▼:scroll  K3:background")
