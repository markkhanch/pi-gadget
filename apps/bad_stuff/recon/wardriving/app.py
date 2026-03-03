"""
apps/tools/wardriving/app.py
Wardriving — scan Wi-Fi networks and log with GPS coordinates.

Saves to:
  menu_fs/02_files/wardriving/wardriving_YYYYMMDD_HHMMSS.csv  (WiGLE format)
  menu_fs/02_files/wardriving/wardriving_YYYYMMDD_HHMMSS.gpx  (GPS track)

Adapter priority:
  1. Alfa AWUS036ACM (wlan1) — monitor mode, airodump-ng, 2.4GHz + 5GHz
  2. wlan0 fallback — iwlist, 2.4GHz only

Controls:
  IDLE:    CTR:start  K1:last log  K3:exit
  RUNNING: CTR:scan now  K3:stop+save
  STATS:   K3:back
"""

import os
import csv
import time
import threading
import subprocess
import datetime
import re
import shutil
import tempfile
from PIL import Image, ImageDraw

try:
    import gps as gpslib
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False

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

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "menu_fs", "02_files", "wardriving"
)

GPS_DEVICES    = ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyACM1"]
ALFA_IFACE     = "wlan1"
FALLBACK_IFACE = "wlan0"
SCAN_INTERVAL  = 5

STATE_IDLE    = "idle"
STATE_RUNNING = "running"
STATE_STATS   = "stats"


# ── Helpers ───────────────────────────────────────────────────

def _ts_size(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def _trunc(draw, text, font, max_w):
    while text:
        w, _ = _ts_size(draw, text, font)
        if w <= max_w:
            return text
        text = text[:-2] + "…"
    return ""


def _iface_exists(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}")


def _ch_to_band(channel_str: str) -> str:
    """Return '5' for 5GHz channels (>14), else '2.4'."""
    try:
        return "5" if int(channel_str) > 14 else "2.4"
    except Exception:
        return "2.4"


def _ensure_gpsd():
    try:
        r = subprocess.run(["pgrep", "gpsd"], capture_output=True, timeout=3)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    for dev in GPS_DEVICES:
        if os.path.exists(dev):
            try:
                subprocess.Popen(
                    ["sudo", "gpsd", dev, "-F", "/var/run/gpsd.sock", "-n"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                time.sleep(1.5)
                return True
            except Exception:
                pass
    return False


def _enable_monitor_mode(iface: str) -> bool:
    """Put interface into monitor mode, return True on success."""
    try:
        subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "iw", iface, "set", "monitor", "control"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                       timeout=5, capture_output=True)
        r = subprocess.run(["iw", "dev", iface, "info"],
                            capture_output=True, timeout=5)
        return "type monitor" in r.stdout.decode()
    except Exception:
        return False


def _restore_managed_mode(iface: str):
    try:
        subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "iw", iface, "set", "type", "managed"],
                       timeout=5, capture_output=True)
        subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                       timeout=5, capture_output=True)
    except Exception:
        pass


# ── Scan backends ─────────────────────────────────────────────

def _scan_airodump(iface: str, duration: int = 4) -> list:
    """
    Scan using airodump-ng — captures 2.4GHz + 5GHz.
    Returns list of network dicts.
    """
    tmpdir  = tempfile.mkdtemp()
    outbase = os.path.join(tmpdir, "scan")

    try:
        proc = subprocess.Popen(
            [
                "sudo", "airodump-ng",
                "--band", "abg",
                "--output-format", "csv",
                "--write", outbase,
                "--write-interval", "1",
                iface,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(duration)
        subprocess.run(["sudo", "kill", str(proc.pid)],
                       capture_output=True)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return []

    networks = []
    csv_path = outbase + "-01.csv"

    if os.path.exists(csv_path):
        try:
            with open(csv_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Airodump CSV: AP section is before first blank line
            ap_section = content.split("\n\n")[0]
            lines = ap_section.strip().splitlines()

            for line in lines[1:]:  # skip header row
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 14:
                    continue
                bssid = parts[0].strip()
                if not re.match(
                    r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", bssid
                ):
                    continue
                try:
                    signal = int(parts[8].strip())
                except Exception:
                    signal = -100
                channel = parts[3].strip().lstrip("-")
                privacy = parts[5].strip()
                ssid    = parts[13].strip() if len(parts) > 13 else ""

                if "WPA3" in privacy:
                    enc = "WPA3"
                elif "WPA2" in privacy:
                    enc = "WPA2"
                elif "WPA" in privacy:
                    enc = "WPA"
                else:
                    enc = "OPEN"

                networks.append({
                    "bssid":      bssid.upper(),
                    "ssid":       ssid,
                    "channel":    channel,
                    "signal":     signal,
                    "encryption": enc,
                })
        except Exception:
            pass

    shutil.rmtree(tmpdir, ignore_errors=True)
    return networks


def _scan_iwlist(iface: str = FALLBACK_IFACE) -> list:
    """Fallback scan using iwlist (2.4GHz only)."""
    try:
        r = subprocess.run(
            ["sudo", "iwlist", iface, "scan"],
            capture_output=True, timeout=15
        )
        output = r.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return []

    networks = []
    current  = {}

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Cell "):
            if current:
                networks.append(current)
            m = re.search(r"Address: ([0-9A-F:]{17})", line)
            current = {
                "bssid": m.group(1) if m else "",
                "ssid": "", "channel": "",
                "signal": -100, "encryption": "OPEN",
            }
        elif "ESSID:" in line:
            m = re.search(r'ESSID:"(.*)"', line)
            current["ssid"] = m.group(1) if m else ""
        elif "Channel:" in line:
            m = re.search(r"Channel:(\d+)", line)
            current["channel"] = m.group(1) if m else ""
        elif "Signal level=" in line:
            m = re.search(r"Signal level=(-?\d+)", line)
            if m:
                current["signal"] = int(m.group(1))
        elif "Encryption key:on" in line:
            current["encryption"] = "WPA"
        elif "IE: WPA Version" in line or "WPA2" in line:
            current["encryption"] = "WPA2"
        elif "IE: IEEE 802.11i/WPA2" in line:
            current["encryption"] = "WPA2"
        elif "WPA3" in line:
            current["encryption"] = "WPA3"

    if current:
        networks.append(current)

    return [n for n in networks if n.get("bssid")]


# ── App ───────────────────────────────────────────────────────

class WardrivingApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.state    = STATE_IDLE
        self._dirty   = True
        self._running = False

        # Adapter
        self._use_alfa    = False
        self._monitor_ok  = False
        self._scan_method = "iwlist"

        # GPS
        self._lat    = None
        self._lon    = None
        self._speed  = 0.0
        self._fix    = False
        self._sats   = 0
        self._gpsd_ok = False

        # Session
        self._networks     = {}  # bssid → best-signal entry
        self._scan_count   = 0
        self._session_file = ""
        self._gpx_file     = ""
        self._gpx_points   = []
        self._last_found   = 0
        self._stats        = None

    def on_enter(self):
        self.state  = STATE_IDLE
        self._dirty = True
        threading.Thread(target=self._init, daemon=True).start()

    def on_exit(self):
        self._running = False
        if self._use_alfa and self._monitor_ok:
            _restore_managed_mode(ALFA_IFACE)

    def _init(self):
        """Detect Alfa, enable monitor mode, start GPS."""
        if _iface_exists(ALFA_IFACE):
            self._use_alfa   = True
            self._monitor_ok = _enable_monitor_mode(ALFA_IFACE)
            if self._monitor_ok:
                r = subprocess.run(["which", "airodump-ng"],
                                   capture_output=True)
                self._scan_method = (
                    "airodump" if r.returncode == 0 else "iwlist"
                )
            else:
                self._use_alfa = False
        self._dirty   = True
        self._gpsd_ok = _ensure_gpsd()
        self._dirty   = True
        if self._gpsd_ok:
            threading.Thread(target=self._gps_loop, daemon=True).start()

    def _gps_loop(self):
        if not GPS_AVAILABLE:
            return
        try:
            session = gpslib.gps(
                mode=gpslib.WATCH_ENABLE | gpslib.WATCH_NEWSTYLE
            )
            while True:
                try:
                    report = session.next()
                    if report["class"] == "TPV":
                        lat = report.get("lat")
                        lon = report.get("lon")
                        if lat and lon:
                            self._lat   = lat
                            self._lon   = lon
                            self._fix   = True
                            spd = report.get("speed", 0)
                            self._speed = (spd * 3.6) if spd else 0
                            self._dirty = True
                    elif report["class"] == "SKY":
                        sats = report.get("satellites", [])
                        self._sats  = sum(
                            1 for s in sats if s.get("used", False)
                        )
                        self._dirty = True
                except StopIteration:
                    break
                except Exception:
                    time.sleep(1)
        except Exception:
            pass

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.state == STATE_IDLE:
            if event == "KEY3":
                return "exit"
            elif event == "CENTER":
                self._start_session()
            elif event == "KEY1":
                self._load_last_stats()
                self.state  = STATE_STATS
                self._dirty = True

        elif self.state == STATE_RUNNING:
            if event == "KEY3":
                self._stop_session()
            elif event == "CENTER":
                threading.Thread(
                    target=self._do_scan, daemon=True
                ).start()

        elif self.state == STATE_STATS:
            if event == "KEY3":
                self.state  = STATE_IDLE
                self._dirty = True

        return "stay"

    # ── Session ───────────────────────────────────────────────

    def _start_session(self):
        os.makedirs(os.path.realpath(OUTPUT_DIR), exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(os.path.realpath(OUTPUT_DIR), f"wardriving_{ts}")
        self._session_file = base + ".csv"
        self._gpx_file     = base + ".gpx"

        with open(self._session_file, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "WigleWifi-1.4", "appRelease=pi-gadget",
                "model=RaspberryPi", "release=1.0", "device=Pi",
                "display=", "board=", "brand=RPi",
                "star=Sol", "body=3", "subBody=0"
            ])
            w.writerow([
                "MAC", "SSID", "AuthMode", "FirstSeen", "Channel",
                "Frequency", "RSSI", "CurrentLatitude", "CurrentLongitude",
                "AltitudeMeters", "AccuracyMeters", "Type"
            ])

        self._networks   = {}
        self._scan_count = 0
        self._last_found = 0
        self._gpx_points = []
        self._running    = True
        self.state       = STATE_RUNNING
        self._dirty      = True

        threading.Thread(target=self._scan_loop, daemon=True).start()

    def _stop_session(self):
        self._running = False
        self._write_gpx()
        self.state  = STATE_IDLE
        self._dirty = True

    def _scan_loop(self):
        while self._running:
            self._do_scan()
            for _ in range(SCAN_INTERVAL * 10):
                if not self._running:
                    break
                time.sleep(0.1)

    def _do_scan(self):
        if self._scan_method == "airodump":
            networks = _scan_airodump(ALFA_IFACE, duration=4)
            if not networks:
                networks = _scan_iwlist(FALLBACK_IFACE)
        else:
            networks = _scan_iwlist(FALLBACK_IFACE)

        self._scan_count += 1
        self._last_found  = len(networks)

        ts  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lat = self._lat or 0.0
        lon = self._lon or 0.0

        if self._fix:
            self._gpx_points.append((lat, lon, ts))

        try:
            with open(self._session_file, "a", newline="",
                      encoding="utf-8") as f:
                w = csv.writer(f)
                for net in networks:
                    bssid = net["bssid"]

                    # Keep best signal per BSSID
                    if (bssid not in self._networks or
                            net["signal"] > self._networks[bssid]["signal"]):
                        self._networks[bssid] = {
                            **net, "lat": lat, "lon": lon
                        }

                    # Frequency from channel
                    try:
                        ch = int(net["channel"])
                        freq = 5000 + ch * 5 if ch > 14 else 2407 + ch * 5
                    except Exception:
                        freq = 0

                    w.writerow([
                        bssid, net["ssid"],
                        f"[{net['encryption']}]",
                        ts, net["channel"], freq,
                        net["signal"],
                        f"{lat:.8f}", f"{lon:.8f}",
                        0, 10, "WIFI"
                    ])
        except Exception:
            pass

        self._dirty = True

    def _write_gpx(self):
        if not self._gpx_points:
            return
        try:
            with open(self._gpx_file, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<gpx version="1.1" creator="pi-gadget">\n')
                f.write('  <trk><name>Wardriving</name><trkseg>\n')
                for lat, lon, ts in self._gpx_points:
                    f.write(
                        f'    <trkpt lat="{lat:.8f}" lon="{lon:.8f}">'
                        f'<time>{ts.replace(" ", "T")}Z</time></trkpt>\n'
                    )
                f.write('  </trkseg></trk>\n</gpx>\n')
        except Exception:
            pass

    def _load_last_stats(self):
        d = os.path.realpath(OUTPUT_DIR)
        if not os.path.isdir(d):
            self._stats = None
            return
        files = sorted([f for f in os.listdir(d) if f.endswith(".csv")])
        if not files:
            self._stats = None
            return
        path = os.path.join(d, files[-1])
        unique = set()
        enc   = {"OPEN": 0, "WPA": 0, "WPA2": 0, "WPA3": 0}
        bands = {"2.4GHz": 0, "5GHz": 0}
        try:
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader); next(reader)
                for row in reader:
                    if len(row) < 5:
                        continue
                    unique.add(row[0])
                    auth = row[2].strip("[]")
                    if auth in enc:
                        enc[auth] += 1
                    try:
                        ch = int(row[4])
                        if ch > 14:
                            bands["5GHz"] += 1
                        else:
                            bands["2.4GHz"] += 1
                    except Exception:
                        pass
        except Exception:
            pass
        self._stats = {
            "file":  files[-1],
            "total": len(unique),
            "enc":   enc,
            "bands": bands,
        }

    def update(self, dt):
        pass

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
               "WARDRIVING", font=self.font_label, fill=CYAN)

        # GPS badge
        if not self._gpsd_ok:
            gps_str, gps_col = "GPS ✗", RED
        elif self._fix:
            gps_str, gps_col = f"● {self._sats}sat", GREEN
        else:
            gps_str, gps_col = "○ no fix", YELLOW

        gw, gh = _ts_size(d, gps_str, self.font_label)
        d.text((W - gw - 6, (TOP_H - gh) // 2),
               gps_str, font=self.font_label, fill=gps_col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        if self.state == STATE_IDLE:
            self._draw_idle(d, W, H)
        elif self.state == STATE_RUNNING:
            self._draw_running(d, W, H)
        elif self.state == STATE_STATS:
            self._draw_stats(d, W, H)

        self.hw.show(img)

    def _hint_bar(self, d, W, H, text):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        tw, th = _ts_size(d, text, self.font_label)
        d.text(((W - tw) // 2, H - th - 2),
               text, font=self.font_label, fill=HINT)

    def _draw_idle(self, d, W, H):
        M  = 8
        y  = TOP_H + 10
        lh = self.font_label.size + 6

        # Adapter status line
        if self._use_alfa and self._monitor_ok:
            adapter_str = f"Alfa wlan1 [{self._scan_method}] 2.4+5GHz"
            adapter_col = GREEN
        elif _iface_exists(ALFA_IFACE):
            adapter_str = "Alfa found, monitor failed"
            adapter_col = YELLOW
        else:
            adapter_str = "wlan0 only (2.4GHz)"
            adapter_col = ORANGE

        aw, _ = _ts_size(d, adapter_str, self.font_label)
        d.text(((W - aw) // 2, y), adapter_str,
               font=self.font_label, fill=adapter_col)
        y += lh + 4
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 8

        # GPS info
        if self._fix and self._lat:
            lines = [
                (f"{self._lat:.5f}°  {self._lon:.5f}°", CYAN),
                (f"{self._speed:.1f} km/h", DIM),
            ]
        else:
            lines = [
                ("Waiting for GPS...", YELLOW),
                ("Point antenna to sky", DIM),
            ]
        for text, color in lines:
            tw, th = _ts_size(d, text, self.font_label)
            d.text(((W - tw) // 2, y), text,
                   font=self.font_label, fill=color)
            y += th + 6

        self._hint_bar(d, W, H, "CTR:start  K1:last log  K3:exit")

    def _draw_running(self, d, W, H):
        M  = 8
        y  = TOP_H + 6
        lh = self.font_label.size + 5

        if self._fix and self._lat:
            coord = _trunc(d, f"{self._lat:.5f}, {self._lon:.5f}",
                           self.font_label, W - M * 2)
            d.text((M, y), coord, font=self.font_label, fill=CYAN)
        else:
            d.text((M, y), "No GPS fix", font=self.font_label, fill=RED)
        y += lh

        d.text((M, y), f"{self._speed:.1f} km/h",
               font=self.font_label, fill=DIM)
        y += lh + 4
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        d.text((M, y), f"Networks: {len(self._networks)}",
               font=self.font_label,
               fill=GREEN if self._networks else DIM)
        y += lh

        d.text((M, y), f"Scans: {self._scan_count}  Last: {self._last_found}",
               font=self.font_label, fill=DIM)
        y += lh

        # Band breakdown
        b24 = sum(1 for n in self._networks.values()
                  if _ch_to_band(n.get("channel", "0")) == "2.4")
        b5  = sum(1 for n in self._networks.values()
                  if _ch_to_band(n.get("channel", "0")) == "5")
        d.text((M, y), f"2.4G:{b24}  5G:{b5}",
               font=self.font_label, fill=PURPLE)
        y += lh

        # Encryption breakdown
        enc_counts = {}
        for net in self._networks.values():
            e = net.get("encryption", "?")
            enc_counts[e] = enc_counts.get(e, 0) + 1
        if enc_counts:
            enc_str = "  ".join(
                f"{k}:{v}" for k, v in sorted(enc_counts.items())
            )
            d.text((M, y),
                   _trunc(d, enc_str, self.font_label, W - M * 2),
                   font=self.font_label, fill=YELLOW)

        self._hint_bar(d, W, H, "CTR:scan now  K3:stop+save")

    def _draw_stats(self, d, W, H):
        M  = 8
        y  = TOP_H + 8
        lh = self.font_label.size + 6

        if not self._stats:
            tw, _ = _ts_size(d, "No logs found", self.font_label)
            d.text(((W - tw) // 2, y + 30),
                   "No logs found", font=self.font_label, fill=DIM)
            self._hint_bar(d, W, H, "K3:back")
            return

        s     = self._stats
        fname = s["file"].replace("wardriving_", "").replace(".csv", "")
        d.text((M, y),
               _trunc(d, fname, self.font_label, W - M * 2),
               font=self.font_label, fill=DIM)
        y += lh + 2

        d.text((M, y), f"Total: {s['total']} networks",
               font=self.font_label, fill=WHITE)
        y += lh

        bands = s.get("bands", {})
        d.text((M, y),
               f"2.4GHz: {bands.get('2.4GHz', 0)}  "
               f"5GHz: {bands.get('5GHz', 0)}",
               font=self.font_label, fill=PURPLE)
        y += lh + 4
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 6

        for enc, count in sorted(s["enc"].items()):
            if count == 0:
                continue
            color = {
                "OPEN": RED, "WPA": ORANGE,
                "WPA2": YELLOW, "WPA3": GREEN
            }.get(enc, WHITE)
            vw, _ = _ts_size(d, str(count), self.font_label)
            d.text((M, y), f"{enc}:",
                   font=self.font_label, fill=DIM)
            d.text((W - vw - M, y), str(count),
                   font=self.font_label, fill=color)
            y += lh

        self._hint_bar(d, W, H, "K3:back")
