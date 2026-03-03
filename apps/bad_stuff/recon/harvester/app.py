"""
apps/bad_stuff/recon/harvester/app.py
Passive Handshake Harvester — silent monitor mode capture.

No deauth, no noise. Listens passively on all channels and saves
handshakes whenever devices naturally connect to nearby networks.

Saves to: menu_fs/02_files/handshakes/harvest_YYYYMMDD_HHMMSS.cap
Log file: menu_fs/02_files/handshakes/harvest_log.jsonl

Controls:
  IDLE:    CTR:start  K3:exit
  RUNNING: K3:stop+save
  STATS:   K3:back
"""

import os
import re
import json
import time
import shutil
import logging
import tempfile
import threading
import subprocess
import datetime
from PIL import Image, ImageDraw

log = logging.getLogger("harvester")

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

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )
)

OUTPUT_DIR      = os.path.join(BASE_DIR, "menu_fs", "02_files", "handshakes")
LOG_FILE        = os.path.join(OUTPUT_DIR, "harvest_log.jsonl")
PREFERRED_IFACE = "wlan1"

# Check interval — how often to scan .cap for new handshakes
CHECK_INTERVAL  = 60   # seconds

STATE_IDLE    = "idle"
STATE_RUNNING = "running"
STATE_STATS   = "stats"


# ── Helpers ───────────────────────────────────────────────────

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


def _fmt_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _iface_exists(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}")


def _is_monitor(iface: str) -> bool:
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, timeout=5)
        return "type monitor" in r.stdout.decode()
    except Exception:
        return False


def _detect_monitor_iface() -> str | None:
    """Find monitor-capable interface, prefer wlan1."""
    if _iface_exists(PREFERRED_IFACE):
        return PREFERRED_IFACE
    try:
        r = subprocess.run(["iw", "dev"], capture_output=True, timeout=5)
        for line in r.stdout.decode().splitlines():
            m = re.search(r"Interface (wlan\d+)", line)
            if m and m.group(1) != "wlan0":
                return m.group(1)
    except Exception as e:
        log.warning("_detect_monitor_iface: %s", e)
    return None


def _enable_monitor(iface: str) -> bool:
    try:
        subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "iw", iface, "set", "monitor", "control"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                       timeout=5, capture_output=True)
        return _is_monitor(iface)
    except Exception as e:
        log.warning("_enable_monitor(%s): %s", iface, e)
        return False


def _kill_proc(proc, name: str = "process"):
    """Graceful SIGTERM → wait → SIGKILL."""
    if proc is None:
        return
    try:
        subprocess.run(["sudo", "kill", "-TERM", str(proc.pid)],
                       capture_output=True, timeout=3)
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(["sudo", "kill", "-KILL", str(proc.pid)],
                       capture_output=True, timeout=3)
        proc.wait(timeout=3)
    except Exception as e:
        log.warning("kill %s (pid=%s): %s", name, getattr(proc, "pid", "?"), e)


def _extract_handshakes(cap_file: str) -> list:
    """
    Use hcxpcapngtool to find EAPOL pairs and PMKIDs.
    Parses the hash file directly to get per-BSSID entries.
    Hash format: WPA*02*MIC*AP_MAC*CLIENT_MAC*ESSID_HEX*NONCE*EAPOL*FLAGS
    Returns list of dicts: {bssid, ssid, hash, type}
    """
    results = []
    if not os.path.exists(cap_file):
        return results

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        hash_file = os.path.join(tmpdir, "out.hc22000")

        r = subprocess.run(
            ["hcxpcapngtool", "-o", hash_file, cap_file],
            capture_output=True, timeout=15
        )
        if r.returncode not in (0, 1):
            log.warning("hcxpcapngtool exit %d", r.returncode)

        if not os.path.exists(hash_file):
            return results

        # Parse each hash line: WPA*TYPE*MIC*AP_MAC*CLIENT_MAC*ESSID_HEX*...
        with open(hash_file, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("WPA*"):
                    continue
                parts = line.split("*")
                if len(parts) < 6:
                    continue

                wpa_type = parts[1]   # "02" = EAPOL, "01" = PMKID
                ap_mac   = parts[3].upper()
                # Format AP MAC as AA:BB:CC:DD:EE:FF
                if len(ap_mac) == 12:
                    bssid = ":".join(ap_mac[i:i+2] for i in range(0, 12, 2))
                else:
                    bssid = ap_mac

                # Decode ESSID from hex
                essid_hex = parts[5]
                try:
                    ssid = bytes.fromhex(essid_hex).decode("utf-8", errors="replace")
                except Exception:
                    ssid = essid_hex or "<hidden>"

                entry_type = "EAPOL" if wpa_type == "02" else "PMKID"
                results.append({
                    "bssid": bssid,
                    "ssid":  ssid or "<hidden>",
                    "hash":  line,
                    "type":  entry_type,
                })
                log.debug("Found %s: %s (%s)", entry_type, ssid, bssid)

        log.info("hcxpcapngtool: %d hashes parsed", len(results))

    except Exception as e:
        log.warning("_extract_handshakes: %s", e)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def _load_log() -> list:
    """Load harvest log from JSONL file."""
    entries = []
    if not os.path.exists(LOG_FILE):
        return entries
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        log.warning("_load_log: %s", e)
    return entries


def _append_log(entry: dict):
    """Append one entry to harvest log."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning("_append_log: %s", e)


# ── App ───────────────────────────────────────────────────────

class HarvesterApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_IDLE
        self._dirty = True

        # Adapter
        self._iface      = None
        self._adapter_ok = False
        self._adapter_msg = "Checking..."

        # Session
        self._running      = False
        self._start_time   = 0
        self._cap_proc     = None
        self._cap_file     = ""
        self._cap_tmpdir   = None
        self._checker_stop = threading.Event()

        # Thread lock for shared state
        self._lock = threading.Lock()

        # Stats (live)
        self._networks_seen  = 0   # unique BSSIDs from airodump CSV
        self._handshakes_new = []  # new catches this session [{bssid, ssid}]
        self._last_check_ts  = ""  # time of last handshake check
        self._last_catch     = ""  # last caught SSID

        # History from log
        self._log_entries = []

        self._last_redraw = 0

    def on_enter(self):
        self.state  = STATE_IDLE
        self._dirty = True
        threading.Thread(target=self._check_adapter, daemon=True).start()
        self._log_entries = _load_log()

    def on_exit(self):
        if self._running:
            self._stop_session()

    def _check_adapter(self):
        iface = _detect_monitor_iface()
        if iface is None:
            self._adapter_ok  = False
            self._adapter_msg = "No adapter on wlan1+"
        elif not _is_monitor(iface):
            ok = _enable_monitor(iface)
            self._iface       = iface if ok else None
            self._adapter_ok  = ok
            self._adapter_msg = f"{iface} ready" if ok else f"{iface}: monitor failed"
        else:
            self._iface       = iface
            self._adapter_ok  = True
            self._adapter_msg = f"{iface} ready"
        self._dirty = True

    # ── Session ───────────────────────────────────────────────

    def _start_session(self):
        if not self._adapter_ok or not self._iface:
            return

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # airodump writes to temp dir; on stop we copy to OUTPUT_DIR
        self._cap_tmpdir = tempfile.mkdtemp()
        cap_base = os.path.join(self._cap_tmpdir, f"harvest_{ts}")

        self._start_time      = time.time()
        self._networks_seen   = 0
        self._handshakes_new  = []
        self._last_catch      = ""
        self._last_check_ts   = ""
        self._running         = True
        self._checker_stop.clear()
        self.state  = STATE_RUNNING
        self._dirty = True

        def _capture():
            """Run airodump-ng passively — no targeting, all channels."""
            try:
                # Tell NetworkManager to stop managing wlan1 (non-destructive)
                # This prevents NM from hopping channels without killing Wi-Fi
                subprocess.run(
                    ["sudo", "nmcli", "device", "set", self._iface, "managed", "no"],
                    capture_output=True, timeout=10
                )
                log.info("NM released %s", self._iface)
                self._cap_proc = subprocess.Popen(
                    [
                        "sudo", "airodump-ng",
                        "--band", "abg",        # 2.4GHz + 5GHz
                        "--output-format", "pcap,csv",
                        "--write", cap_base,
                        "--write-interval", "10",
                        self._iface,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info("Harvester started on %s", self._iface)
                self._cap_proc.wait()
            except Exception as e:
                log.error("Capture error: %s", e)
            finally:
                self._cap_proc = None

        def _checker():
            """
            Periodically check captured data for new handshakes
            and update network count from CSV.
            Deduplicates by hash string — correctly handles multiple
            BSSIDs and repeated checks.
            """
            # Deduplicate by full hash string (unique per client+AP pair)
            known_hashes: set[str] = set()

            while not self._checker_stop.wait(CHECK_INTERVAL):
                cap_file = cap_base + "-01.cap"
                csv_file = cap_base + "-01.csv"

                # Update unique BSSID count from CSV
                if os.path.exists(csv_file):
                    try:
                        with open(csv_file, encoding="utf-8",
                                  errors="ignore") as f:
                            content = f.read()
                        ap_block = content.split("\n\n")[0]
                        unique_bssids = set()
                        for line in ap_block.strip().splitlines()[1:]:
                            parts = [p.strip() for p in line.split(",")]
                            if parts and re.match(
                                r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}",
                                parts[0]
                            ):
                                unique_bssids.add(parts[0].upper())
                        with self._lock:
                            self._networks_seen = len(unique_bssids)
                    except Exception as e:
                        log.warning("CSV read: %s", e)

                # Check for new handshakes
                if os.path.exists(cap_file):
                    found = _extract_handshakes(cap_file)
                    for entry in found:
                        h = entry.get("hash", "")
                        if h and h not in known_hashes:
                            known_hashes.add(h)
                            with self._lock:
                                self._handshakes_new.append(entry)
                                self._last_catch = entry["ssid"]
                            log.info("New %s: %s (%s)",
                                     entry.get("type", "HS"),
                                     entry["ssid"], entry["bssid"])

                with self._lock:
                    self._last_check_ts = datetime.datetime.now().strftime(
                        "%H:%M:%S"
                    )
                self._dirty = True

        threading.Thread(target=_capture, daemon=True).start()
        threading.Thread(target=_checker, daemon=True).start()

        # Store cap_base for stop
        self._cap_base = cap_base

    def _stop_session(self):
        self._running = False
        self._checker_stop.set()

        # Stop airodump
        if self._cap_proc:
            _kill_proc(self._cap_proc, "airodump-ng harvester")
            self._cap_proc = None

        # Save .cap file to output dir
        cap_file = self._cap_base + "-01.cap" if hasattr(self, "_cap_base") else ""
        if cap_file and os.path.exists(cap_file):
            ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name  = f"harvest_{ts}.cap"
            out_path  = os.path.join(OUTPUT_DIR, out_name)
            try:
                shutil.copy2(cap_file, out_path)
                log.info("Saved harvest: %s", out_path)
            except Exception as e:
                log.error("Save failed: %s", e)

        # Log session summary
        if self._handshakes_new:
            entry = {
                "ts":         datetime.datetime.now().isoformat(),
                "duration_s": int(time.time() - self._start_time),
                "networks":   self._networks_seen,
                "handshakes": self._handshakes_new,
            }
            _append_log(entry)
            self._log_entries = _load_log()

        # Return wlan1 back to NetworkManager management
        try:
            iface = self._iface or PREFERRED_IFACE
            subprocess.run(
                ["sudo", "nmcli", "device", "set", iface, "managed", "yes"],
                capture_output=True, timeout=10
            )
            log.info("NM reclaimed %s", iface)
        except Exception as e:
            log.warning("Failed to restore NM management: %s", e)

        # Cleanup temp
        if self._cap_tmpdir:
            shutil.rmtree(self._cap_tmpdir, ignore_errors=True)
            self._cap_tmpdir = None

        self.state  = STATE_IDLE
        self._dirty = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER" and self._adapter_ok:
                self._start_session()
            elif event == "KEY1" and self._log_entries:
                self.state  = STATE_STATS
                self._dirty = True

        elif self.state == STATE_RUNNING:
            if event == "KEY3":
                self._stop_session()

        elif self.state == STATE_STATS:
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
               "HARVESTER", font=self.font_label, fill=PURPLE)

        # Status badge
        if self.state == STATE_RUNNING:
            badge, badge_col = "● LIVE", GREEN
        elif self.state == STATE_STATS:
            badge, badge_col = "STATS", CYAN
        else:
            badge, badge_col = "IDLE", DIM

        bw, bh = _ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=badge_col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        elif self.state == STATE_RUNNING:
            self._draw_running(d, W, H)
        elif self.state == STATE_STATS:
            self._draw_stats(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        M  = 8
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        # Adapter status
        col = GREEN if self._adapter_ok else RED
        aw, ah = _ts(d, self._adapter_msg, self.font_label)
        d.text(((W - aw) // 2, cy - ah - 22),
               self._adapter_msg, font=self.font_label, fill=col)

        if self._adapter_ok:
            lines = [
                ("Passive mode — no deauth", DIM),
                ("Leave running overnight", DIM),
            ]
            y = cy - 4
            for text, tc in lines:
                tw, th = _ts(d, text, self.font_label)
                d.text(((W - tw) // 2, y), text,
                       font=self.font_label, fill=tc)
                y += th + 6

        # Previous session summary
        if self._log_entries:
            total_hs = sum(
                len(e.get("handshakes", [])) for e in self._log_entries
            )
            summary = f"Lifetime: {total_hs} handshakes"
            sw, sh = _ts(d, summary, self.font_label)
            d.text(((W - sw) // 2, H - BOT_H - sh - 24),
                   summary, font=self.font_label, fill=CYAN)

        hint = "CTR:start  K1:history  K3:exit" if self._log_entries \
               else "CTR:start  K3:exit"
        self._hint(d, W, H, hint)

    def _draw_running(self, d, W, H):
        M   = 8
        y   = TOP_H + 6
        lh  = self.font_label.size + 5

        # Duration
        elapsed = int(time.time() - self._start_time)
        dur_str = _fmt_duration(elapsed)
        dw, _   = _ts(d, dur_str, self.font_label)
        d.text(((W - dw) // 2, y), dur_str,
               font=self.font_label, fill=CYAN)
        y += lh + 2

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        # Networks seen
        d.text((M, y), f"Networks: {self._networks_seen}",
               font=self.font_label, fill=DIM)
        y += lh

        # Handshakes caught
        hs_count = len(self._handshakes_new)
        hs_col   = GREEN if hs_count > 0 else DIM
        d.text((M, y), f"Handshakes: {hs_count}",
               font=self.font_label, fill=hs_col)
        y += lh

        # Last caught
        if self._last_catch:
            last = _trunc(d, f"Last: {self._last_catch}",
                          self.font_label, W - M * 2)
            d.text((M, y), last, font=self.font_label, fill=GREEN)
            y += lh

        # Last check time
        if self._last_check_ts:
            check_str = f"Checked: {self._last_check_ts}"
            d.text((M, y), check_str, font=self.font_label, fill=DIM)
            y += lh

        # Recent catches list (last 2)
        if self._handshakes_new:
            y += 2
            d.line([(M, y), (W - M, y)], fill=SEP, width=1)
            y += 4
            for entry in self._handshakes_new[-2:]:
                row = _trunc(d, f"✓ {entry['ssid']}", self.font_label,
                             W - M * 2)
                d.text((M, y), row, font=self.font_label, fill=GREEN)
                y += lh

        self._hint(d, W, H, "K3:stop+save")

    def _draw_stats(self, d, W, H):
        M  = 8
        y  = TOP_H + 6
        lh = self.font_label.size + 5

        if not self._log_entries:
            tw, _ = _ts(d, "No history yet", self.font_label)
            d.text(((W - tw) // 2, TOP_H + 40),
                   "No history yet", font=self.font_label, fill=DIM)
            self._hint(d, W, H, "K3:back")
            return

        # Summary
        total_sessions  = len(self._log_entries)
        total_hs        = sum(
            len(e.get("handshakes", [])) for e in self._log_entries
        )
        total_networks  = sum(
            e.get("networks", 0) for e in self._log_entries
        )

        d.text((M, y), f"Sessions: {total_sessions}",
               font=self.font_label, fill=DIM)
        y += lh
        d.text((M, y), f"Total handshakes: {total_hs}",
               font=self.font_label, fill=WHITE)
        y += lh
        d.text((M, y), f"Networks seen: {total_networks}",
               font=self.font_label, fill=DIM)
        y += lh + 4

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        # List last caught SSIDs (most recent session)
        last = self._log_entries[-1]
        for hs in last.get("handshakes", [])[:4]:
            row = _trunc(d, f"✓ {hs['ssid']}", self.font_label, W - M * 2)
            d.text((M, y), row, font=self.font_label, fill=GREEN)
            y += lh
            if y > H - BOT_H - lh:
                break

        self._hint(d, W, H, "K3:back")
