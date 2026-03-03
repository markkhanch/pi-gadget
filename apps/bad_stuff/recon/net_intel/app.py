"""
apps/network/scanner/app.py
Network Intelligence — network recon tool.

Screens:
  NET     — own IP, MAC, gateway, DNS, external IP
  HOSTS   — all devices on LAN (arp-scan), one row per host
  DETAIL  — full info about selected host + launch port scan
  PORTS   — port scan results (nmap)

Controls:
  NET / HOSTS:
    LEFT / RIGHT  — switch screens
    KEY1          — previous screen
    KEY2          — next screen
    CENTER        — refresh / open detail
    UP / DOWN     — scroll
    KEY3          — exit

  DETAIL:
    UP / DOWN     — scroll
    CENTER        — start port scan → go to PORTS
    KEY3          — back to HOSTS

  PORTS:
    UP / DOWN     — scroll
    KEY3          — back to DETAIL
"""

import subprocess
import threading
import time
import socket
from PIL import Image, ImageDraw

# ── Layout ────────────────────────────────────────────────────
TOP_H  = 26
BOT_H  = 18
TAB_H  = 20
ROW_H  = 22   # single-line rows — no overflow

# ── Palette ───────────────────────────────────────────────────
BG       = (4,   8,   16)
HDR_BG   = (8,   14,  28)
TAB_BG   = (10,  18,  35)
TAB_ACT  = (15,  30,  60)
SEL_BG   = (12,  25,  50)
SEP      = (25,  45,  75)
SEP_HI   = (50,  90,  140)

WHITE    = (220, 235, 255)
DIM      = (70,  100, 140)
HINT     = (50,  75,  110)

CYAN     = (0,   210, 255)
GREEN    = (50,  220, 120)
YELLOW   = (255, 200, 50)
RED      = (255, 70,  70)
ORANGE   = (255, 140, 30)
BLUE     = (60,  150, 255)

SCREENS       = ["NET", "HOSTS", "DETAIL", "PORTS"]
SCREEN_LABELS = ["Net", "Hosts", "Detail", "Ports"]


# ── Shell helper ──────────────────────────────────────────────

def _sh(cmd, timeout=30):
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


# ── Data collectors ───────────────────────────────────────────

def _collect_overview() -> list:
    """Returns list of (label, value, color) rows."""
    rows = []

    for iface in ("wlan0", "eth0"):
        _, out = _sh(["ip", "-4", "addr", "show", iface])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                rows.append((f"{iface} IP", line.split()[1].split("/")[0], CYAN))
                break

    for iface in ("wlan0", "eth0"):
        _, out = _sh(f"cat /sys/class/net/{iface}/address 2>/dev/null")
        mac = out.strip()
        if mac:
            rows.append((f"{iface} MAC", mac, WHITE))

    _, out = _sh(["ip", "route", "show", "default"])
    parts = out.split()
    if "via" in parts:
        rows.append(("Gateway", parts[parts.index("via") + 1], YELLOW))
    if "dev" in parts:
        rows.append(("Interface", parts[parts.index("dev") + 1], DIM))

    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    rows.append(("DNS", line.split()[1], BLUE))
                    break
    except Exception:
        pass

    _, out = _sh(["curl", "-s", "--max-time", "5", "ifconfig.me"])
    ext = out.strip()
    if ext and len(ext) < 20:
        rows.append(("Ext IP", ext, ORANGE))

    return rows


def _resolve_hostname(ip: str) -> str:
    """Try reverse DNS lookup. Returns hostname or empty string."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _collect_hosts() -> list:
    """ARP scan LAN. Returns list of {ip, mac, vendor, hostname}."""
    _, raw = _sh(["sudo", "arp-scan", "--localnet", "-q"], timeout=20)
    hosts = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0] and ":" in parts[1]:
            ip     = parts[0]
            mac    = parts[1]
            vendor = " ".join(parts[2:])[:24] if len(parts) > 2 else ""
            hosts.append({"ip": ip, "mac": mac, "vendor": vendor, "hostname": ""})

    # Resolve hostnames in parallel
    def resolve(h):
        h["hostname"] = _resolve_hostname(h["ip"])

    threads = [threading.Thread(target=resolve, args=(h,), daemon=True) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    hosts.sort(key=lambda h: [int(x) for x in h["ip"].split(".")])
    return hosts


def _collect_ports(ip: str) -> list:
    """Nmap top-1000 ports with service version detection."""
    _, raw = _sh(["sudo", "nmap", "-T4", "--open", "-sV", "--version-intensity", "3", ip], timeout=180)
    results = []
    for line in raw.splitlines():
        line = line.strip()
        if "/tcp" in line or "/udp" in line:
            parts = line.split()
            if len(parts) >= 3:
                # Format: "80/tcp  open  http  Apache httpd 2.4.x"
                service = parts[2]
                version = " ".join(parts[3:])[:30] if len(parts) > 3 else ""
                results.append({"port": parts[0], "service": service, "version": version})
            elif len(parts) == 2:
                results.append({"port": parts[0], "service": "unknown", "version": ""})
    return results


def _collect_host_detail(ip: str) -> dict:
    """Nmap OS detection + ping latency."""
    info = {"os": "", "latency": ""}

    # Ping latency
    _, out = _sh(["ping", "-c", "1", "-W", "2", ip], timeout=5)
    for line in out.splitlines():
        if "time=" in line:
            try:
                ms = line.split("time=")[1].split()[0]
                info["latency"] = f"{ms} ms"
            except Exception:
                pass
            break

    # OS fingerprint
    _, raw = _sh(["sudo", "nmap", "-O", "--osscan-guess", "-T4", ip], timeout=60)
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("OS:") or line.startswith("Aggressive OS guesses:") or line.startswith("Running:"):
            os_str = line.split(":", 1)[-1].strip()
            # Shorten common OS names
            for old, new in [
                ("Microsoft Windows", "Windows"),
                ("Linux Kernel", "Linux"),
                ("Apple Mac OS X", "macOS"),
                ("Apple iOS", "iOS"),
                ("Android", "Android"),
            ]:
                os_str = os_str.replace(old, new)
            if os_str and not info["os"]:
                info["os"] = os_str[:28]
    return info


# ── App ───────────────────────────────────────────────────────

class ScannerApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen      = "NET"
        self.scroll      = {s: 0 for s in SCREENS}
        self.host_sel    = 0
        self._dirty      = True
        self._scanning   = False
        self._scan_label = ""
        self._scan_dots  = 0
        self._scan_timer = 0.0

        self.net_rows    = []
        self.hosts       = []
        self.detail_host = None
        self.host_detail = {}   # OS, latency for selected host
        self.ports       = []

    # ── Lifecycle ─────────────────────────────────────────────

    def on_enter(self):
        self.screen   = "NET"
        self._dirty   = True
        self._start_scan()

    def _start_scan(self):
        self._scanning   = True
        self._dirty      = True

        if self.screen == "NET":
            self._scan_label = "Gathering info"
            threading.Thread(target=self._do_net, daemon=True).start()
        elif self.screen == "HOSTS":
            self._scan_label = "ARP scanning"
            threading.Thread(target=self._do_hosts, daemon=True).start()
        elif self.screen == "PORTS":
            if not self.detail_host:
                self._scanning = False
                return
            self._scan_label = f"Scanning {self.detail_host['ip']}"
            threading.Thread(target=self._do_ports, daemon=True).start()
        else:
            self._scanning = False

    def _do_net(self):
        self.net_rows  = _collect_overview()
        self._scanning = False
        self._dirty    = True

    def _do_hosts(self):
        self.hosts     = _collect_hosts()
        self.host_sel  = 0
        self.scroll["HOSTS"] = 0
        self._scanning = False
        self._dirty    = True

    def _do_detail(self):
        if self.detail_host:
            self.host_detail = _collect_host_detail(self.detail_host["ip"])
        self._scanning = False
        self._dirty    = True

    def _do_ports(self):
        self.ports     = _collect_ports(self.detail_host["ip"])
        self.scroll["PORTS"] = 0
        self._scanning = False
        self._dirty    = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if event == "KEY3":
            if self.screen == "PORTS":
                self.screen = "DETAIL"
                self._dirty = True
                return "stay"
            if self.screen == "DETAIL":
                self.screen = "HOSTS"
                self._dirty = True
                return "stay"
            return "exit"

        if event in ("KEY1", "LEFT") and not self._scanning:
            if self.screen == "NET":
                pass
            elif self.screen == "HOSTS":
                self.screen = "NET"
                self._dirty = True
                self._start_scan()
            elif self.screen == "DETAIL":
                self.screen = "HOSTS"
                self._dirty = True
            elif self.screen == "PORTS":
                self.screen = "DETAIL"
                self._dirty = True
            return "stay"

        if event in ("KEY2", "RIGHT") and not self._scanning:
            if self.screen == "NET":
                self.screen = "HOSTS"
                self._dirty = True
                self._start_scan()
            elif self.screen == "HOSTS":
                if self.detail_host:
                    self.screen = "DETAIL"
                    self._dirty = True
            elif self.screen == "DETAIL":
                self.screen = "PORTS"
                self._dirty = True
                self._start_scan()
            return "stay"

        if event == "CENTER":
            if self.screen == "HOSTS" and self.hosts and not self._scanning:
                self.detail_host = self.hosts[self.host_sel]
                self.host_detail = {}
                self.screen      = "DETAIL"
                self._dirty      = True
                # Start OS/latency scan in background
                self._scanning   = True
                self._scan_label = "Probing host"
                threading.Thread(target=self._do_detail, daemon=True).start()
            elif self.screen == "DETAIL" and not self._scanning:
                self.screen = "PORTS"
                self.ports  = []
                self._dirty = True
                self._start_scan()
            elif not self._scanning:
                self._start_scan()
            return "stay"

        max_rows = self._max_rows()

        if event == "UP":
            if self.screen == "HOSTS" and self.host_sel > 0:
                self.host_sel -= 1
                self._fix_scroll()
                self._dirty = True
            elif self.scroll[self.screen] > 0:
                self.scroll[self.screen] -= 1
                self._dirty = True

        if event == "DOWN":
            if self.screen == "HOSTS":
                if self.host_sel < len(self.hosts) - 1:
                    self.host_sel += 1
                    self._fix_scroll()
                    self._dirty = True
            else:
                data_len = self._data_len()
                if self.scroll[self.screen] < max(0, data_len - max_rows):
                    self.scroll[self.screen] += 1
                    self._dirty = True

        return "stay"

    def _max_rows(self):
        H = self.hw.H
        return (H - TOP_H - TAB_H - BOT_H) // ROW_H

    def _data_len(self):
        if self.screen == "NET":    return len(self.net_rows)
        if self.screen == "PORTS":  return len(self.ports)
        if self.screen == "DETAIL": return 5  # fixed rows
        return 0

    def _fix_scroll(self):
        max_rows = self._max_rows()
        s = self.scroll["HOSTS"]
        if self.host_sel < s:
            self.scroll["HOSTS"] = self.host_sel
        elif self.host_sel >= s + max_rows:
            self.scroll["HOSTS"] = self.host_sel - max_rows + 1

    # ── Update ────────────────────────────────────────────────

    def update(self, dt):
        if self._scanning:
            self._scan_timer += dt
            if self._scan_timer >= 0.4:
                self._scan_timer = 0.0
                self._scan_dots  = (self._scan_dots + 1) % 4
            self._dirty = True

    # ── Draw ──────────────────────────────────────────────────

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        self._draw_header(draw, W)
        self._draw_tabs(draw, W)

        y0 = TOP_H + TAB_H

        if self._scanning:
            self._draw_scanning(draw, W, H, y0)
        elif self.screen == "NET":
            self._draw_net(draw, W, H, y0)
        elif self.screen == "HOSTS":
            self._draw_hosts(draw, W, H, y0)
        elif self.screen == "DETAIL":
            self._draw_detail(draw, W, H, y0)
        elif self.screen == "PORTS":
            self._draw_ports(draw, W, H, y0)

        self._draw_bottom(draw, W, H)
        self.hw.show(img)

    def _ts(self, draw, text, font):
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]

    def _trunc(self, draw, text, font, max_w):
        """Truncate text to fit max_w pixels."""
        while text:
            w, _ = self._ts(draw, text, font)
            if w <= max_w:
                return text
            text = text[:-2] + "…"
        return ""

    def _draw_header(self, draw, W):
        draw.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        draw.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)

        title = "NET INTEL"
        tw, th = self._ts(draw, title, self.font_label)
        draw.text((10, (TOP_H - th) // 2), title,
                  font=self.font_label, fill=CYAN)

        status = "SCAN" if self._scanning else "READY"
        sc     = YELLOW if self._scanning else GREEN
        dot    = "■" if self._scanning else "●"
        s_str  = f"{dot} {status}"
        sw, sh = self._ts(draw, s_str, self.font_label)
        draw.text((W - sw - 6, (TOP_H - sh) // 2), s_str,
                  font=self.font_label, fill=sc)

        draw.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    def _draw_tabs(self, draw, W):
        draw.rectangle([(0, TOP_H), (W, TOP_H + TAB_H)], fill=TAB_BG)
        # Show only NET and HOSTS tabs (DETAIL and PORTS are sub-screens)
        visible_tabs  = ["NET", "HOSTS"]
        visible_labels = ["Net", "Hosts"]
        tab_w = W // len(visible_tabs)

        for i, (scr, lbl) in enumerate(zip(visible_tabs, visible_labels)):
            x0 = i * tab_w
            x1 = x0 + tab_w
            is_active = (self.screen in (scr,) or
                         (scr == "HOSTS" and self.screen in ("DETAIL", "PORTS")))

            if is_active:
                draw.rectangle([(x0, TOP_H), (x1, TOP_H + TAB_H)], fill=TAB_ACT)
                draw.line([(x0 + 2, TOP_H + TAB_H - 2),
                           (x1 - 2, TOP_H + TAB_H - 2)],
                          fill=CYAN, width=2)

            # Sub-screen indicator
            if scr == "HOSTS" and self.screen in ("DETAIL", "PORTS"):
                sub = " › " + ("Detail" if self.screen == "DETAIL" else "Ports")
                lbl = "Hosts" + sub

            lw, lh = self._ts(draw, lbl, self.font_label)
            color  = CYAN if is_active else DIM
            # Clip label to tab width
            if lw > tab_w - 4:
                lbl = self._trunc(draw, lbl, self.font_label, tab_w - 4)
                lw, lh = self._ts(draw, lbl, self.font_label)
            draw.text((x0 + (tab_w - lw) // 2, TOP_H + (TAB_H - lh) // 2),
                      lbl, font=self.font_label, fill=color)

        draw.line([(0, TOP_H + TAB_H), (W, TOP_H + TAB_H)], fill=SEP, width=1)

    def _draw_scanning(self, draw, W, H, y0):
        dots = "." * self._scan_dots
        msg  = self._scan_label + dots
        mw, mh = self._ts(draw, msg, self.font_label)
        cy = y0 + (H - BOT_H - y0) // 2
        draw.text(((W - mw) // 2, cy - mh // 2), msg,
                  font=self.font_label, fill=CYAN)

    def _draw_bottom(self, draw, W, H):
        draw.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hints = {
            "NET":    "K1/K2:switch  CTR:refresh  K3:exit",
            "HOSTS":  "UP/DN:select  CTR:detail  K3:exit",
            "DETAIL": "CTR:scan ports  K3:back",
            "PORTS":  "UP/DN:scroll  K3:back",
        }
        hint = hints.get(self.screen, "K3:exit")
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        # Truncate if too wide
        hint = self._trunc(draw, hint, self.font_label, W - 4)
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 2),
                  hint, font=self.font_label, fill=HINT)

    # ── NET screen ────────────────────────────────────────────

    def _draw_net(self, draw, W, H, y0):
        MARGIN = 6
        lh     = self.font_label.size + 6
        max_r  = (H - BOT_H - y0) // lh

        if not self.net_rows:
            self._draw_empty(draw, W, H, y0, "No data", "CTR to scan")
            return

        visible = self.net_rows[self.scroll["NET"]: self.scroll["NET"] + max_r]
        y = y0 + 3

        for label, value, vc in visible:
            lbl = label + ":"
            lbw, _ = self._ts(draw, lbl, self.font_label)
            draw.text((MARGIN, y), lbl, font=self.font_label, fill=DIM)

            max_vw = W - MARGIN * 2 - lbw - 4
            val = self._trunc(draw, value, self.font_label, max_vw)
            vw, _ = self._ts(draw, val, self.font_label)
            draw.text((W - vw - MARGIN, y), val, font=self.font_label, fill=vc)

            draw.line([(MARGIN, y + lh - 2), (W - MARGIN, y + lh - 2)],
                      fill=(15, 25, 45), width=1)
            y += lh

        self._draw_scrollbar(draw, W, H, y0,
                             len(self.net_rows), max_r, self.scroll["NET"])

    # ── HOSTS screen ──────────────────────────────────────────

    def _draw_hosts(self, draw, W, H, y0):
        MARGIN   = 5
        max_rows = (H - BOT_H - y0) // ROW_H

        if not self.hosts:
            self._draw_empty(draw, W, H, y0, "No hosts found", "CTR to scan")
            return

        # Host count
        cnt = f"{len(self.hosts)} hosts"
        cw, ch = self._ts(draw, cnt, self.font_label)
        draw.text((W - cw - 5, y0 + 2), cnt,
                  font=self.font_label, fill=DIM)

        visible = self.hosts[self.scroll["HOSTS"]: self.scroll["HOSTS"] + max_rows]
        y = y0

        for i, host in enumerate(visible):
            idx    = self.scroll["HOSTS"] + i
            is_sel = idx == self.host_sel
            y1r    = y + ROW_H

            if is_sel:
                draw.rectangle([(0, y), (W, y1r - 1)], fill=SEL_BG)
                draw.rectangle([(0, y), (2, y1r - 1)], fill=CYAN)

            # Show hostname if available, else IP
            display = host["hostname"] if host["hostname"] else host["ip"]
            col     = CYAN if is_sel else WHITE
            max_w   = W - MARGIN * 2 - 16
            display = self._trunc(draw, display, self.font_label, max_w)
            draw.text((MARGIN + 4, y + (ROW_H - self.font_label.size) // 2),
                      display, font=self.font_label, fill=col)

            # Arrow indicator
            if is_sel:
                arr = ">"
                aw, ah = self._ts(draw, arr, self.font_label)
                draw.text((W - aw - 5,
                           y + (ROW_H - ah) // 2),
                          arr, font=self.font_label, fill=CYAN)

            draw.line([(0, y1r - 1), (W, y1r - 1)], fill=SEP, width=1)
            y += ROW_H

        self._draw_scrollbar(draw, W, H, y0,
                             len(self.hosts), max_rows, self.scroll["HOSTS"])

    # ── DETAIL screen ─────────────────────────────────────────

    def _draw_detail(self, draw, W, H, y0):
        MARGIN = 6
        lh     = self.font_label.size + 7
        h      = self.detail_host

        if not h:
            self._draw_empty(draw, W, H, y0, "No host selected", "Go to Hosts first")
            return

        rows = []
        if h["hostname"]:
            rows.append(("Hostname", h["hostname"], CYAN))
        rows.append(("IP",   h["ip"],  WHITE))
        rows.append(("MAC",  h["mac"], WHITE))
        if h["vendor"]:
            rows.append(("Vendor", h["vendor"], YELLOW))
        if self.host_detail.get("os"):
            rows.append(("OS", self.host_detail["os"], BLUE))
        if self.host_detail.get("latency"):
            rows.append(("Ping", self.host_detail["latency"], GREEN))
        if self.ports:
            rows.append(("Open ports", str(len(self.ports)), GREEN))

        rows.append(("", "CTR: scan ports", DIM))

        y = y0 + 3
        for label, value, vc in rows:
            if label:
                lbl = label + ":"
                lbw, _ = self._ts(draw, lbl, self.font_label)
                draw.text((MARGIN, y), lbl, font=self.font_label, fill=DIM)
                max_vw = W - MARGIN * 2 - lbw - 4
                val = self._trunc(draw, value, self.font_label, max_vw)
                vw, _ = self._ts(draw, val, self.font_label)
                draw.text((W - vw - MARGIN, y), val, font=self.font_label, fill=vc)
            else:
                vw, _ = self._ts(draw, value, self.font_label)
                draw.text(((W - vw) // 2, y), value, font=self.font_label, fill=vc)

            draw.line([(MARGIN, y + lh - 2), (W - MARGIN, y + lh - 2)],
                      fill=(15, 25, 45), width=1)
            y += lh

    # ── PORTS screen ──────────────────────────────────────────

    def _draw_ports(self, draw, W, H, y0):
        MARGIN   = 5
        max_rows = (H - BOT_H - y0) // ROW_H

        # Target banner
        ip_str = self.detail_host["ip"] if self.detail_host else "?"
        banner = f"> {ip_str}"
        bw, bh = self._ts(draw, banner, self.font_label)
        draw.rectangle([(0, y0), (W, y0 + bh + 6)], fill=(8, 20, 40))
        draw.text((MARGIN, y0 + 3), banner, font=self.font_label, fill=YELLOW)
        draw.line([(0, y0 + bh + 6), (W, y0 + bh + 6)], fill=SEP, width=1)
        y0 += bh + 7

        if not self.ports:
            self._draw_empty(draw, W, H, y0, "No open ports", "")
            return

        # Port count
        cnt = f"{len(self.ports)} open"
        cw, _ = self._ts(draw, cnt, self.font_label)
        draw.text((W - cw - 5, y0 - self.font_label.size - 5),
                  cnt, font=self.font_label, fill=GREEN)

        visible = self.ports[self.scroll["PORTS"]: self.scroll["PORTS"] + max_rows]
        y = y0

        for p in visible:
            port    = p["port"]
            service = p["service"]

            pw, _ = self._ts(draw, port, self.font_label)
            draw.text((MARGIN, y + (ROW_H - self.font_label.size) // 2),
                      port, font=self.font_label, fill=CYAN)

            # Show version if available, else service name
            version = p.get("version", "")
            display = version if version else service
            max_sv  = W - MARGIN * 2 - pw - 8
            sv      = self._trunc(draw, display, self.font_label, max_sv)
            svw, _  = self._ts(draw, sv, self.font_label)
            col     = YELLOW if version else GREEN
            draw.text((W - svw - MARGIN,
                       y + (ROW_H - self.font_label.size) // 2),
                      sv, font=self.font_label, fill=col)

            draw.line([(0, y + ROW_H - 1), (W, y + ROW_H - 1)],
                      fill=SEP, width=1)
            y += ROW_H

        self._draw_scrollbar(draw, W, H, y0,
                             len(self.ports), max_rows, self.scroll["PORTS"])

    # ── Helpers ───────────────────────────────────────────────

    def _draw_empty(self, draw, W, H, y0, line1, line2):
        cy = y0 + (H - BOT_H - y0) // 2
        mw, mh = self._ts(draw, line1, self.font_label)
        draw.text(((W - mw) // 2, cy - mh - 2), line1,
                  font=self.font_label, fill=DIM)
        if line2:
            sw, sh = self._ts(draw, line2, self.font_label)
            draw.text(((W - sw) // 2, cy + 2), line2,
                      font=self.font_label, fill=HINT)

    def _draw_scrollbar(self, draw, W, H, y0, total, max_rows, scroll):
        if total <= max_rows:
            return
        area_h = H - BOT_H - y0
        bar_h  = max(10, int(area_h * max_rows / total))
        bar_y  = y0 + int((area_h - bar_h) * scroll / max(1, total - max_rows))
        draw.rectangle([W - 3, bar_y, W - 1, bar_y + bar_h], fill=DIM)
