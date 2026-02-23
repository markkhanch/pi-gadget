"""
apps/settings/wifi_manager/app.py
Wi-Fi Manager — full-featured network manager using NetworkManager (nmcli).

Screens:
  LIST    — scanned networks + current connection status
  DETAIL  — details for selected network (connect / disconnect / forget)
  PASS    — password input via on-screen keyboard
  STATUS  — operation result (OK / ERR)

Controls:
  LIST screen:
    UP / DOWN   — scroll list
    CENTER      — open network detail screen
    KEY1        — manual rescan
    KEY3        — exit

  DETAIL screen:
    UP / DOWN   — navigate actions
    CENTER      — execute selected action
    KEY3        — back to list

  PASS screen:
    Joystick    — keyboard navigation
    KEY1        — cycle keyboard language
    KEY2        — confirm and connect
    KEY3        — cancel, back to detail

  STATUS screen:
    Any key     — back to list (triggers rescan)
"""

import subprocess
import time
from PIL import Image, ImageDraw
from ui_keyboard import OnScreenKeyboard

# ── Style ─────────────────────────────────────────────────────
TOP_BAR_H  = 24
BOT_BAR_H  = 20
BG         = (0, 0, 0)
HEADER_BG  = (20, 20, 20)
SEP        = (60, 60, 60)
WHITE      = (255, 255, 255)
GRAY       = (150, 150, 150)
HINT_COLOR = (100, 100, 100)
GREEN      = (70, 200, 70)
RED        = (220, 70, 70)
YELLOW     = (220, 180, 50)
BLUE       = (80, 160, 255)
ROW_H      = 38
ROW_SEL_BG = (40, 40, 40)

# Auto-rescan interval in seconds
AUTO_RESCAN_INTERVAL = 30.0


# ── Shell helpers ─────────────────────────────────────────────

def _run(cmd, timeout=10):
    """Run command list, return stdout or '' on error."""
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout)
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _run_shell(cmd, timeout=20):
    """Run shell string, return (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", errors="ignore")
        err = r.stderr.decode("utf-8", errors="ignore")
        return r.returncode, out + err
    except Exception as e:
        return 1, str(e)


def _get_current_ssid() -> str:
    return _run(["iwgetid", "-r"]).strip()


def _get_ip() -> str:
    """Get wlan0 IP address."""
    out = _run(["ip", "-4", "addr", "show", "wlan0"])
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split("/")[0]
    return ""


def _scan_networks() -> list:
    """
    Scan with iwlist, return list of dicts:
    {ssid, signal, open}
    Sorted by signal descending, deduplicated by SSID.
    """
    raw = _run(["sudo", "iwlist", "wlan0", "scan"], timeout=12)
    networks = []
    current = {}

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Cell "):
            if current.get("ssid") is not None:
                networks.append(current)
            current = {"ssid": None, "signal": -100, "open": True}
        elif "ESSID:" in line:
            try:
                ssid = line.split('ESSID:"')[1].rstrip('"')
                current["ssid"] = ssid if ssid else "<hidden>"
            except Exception:
                current["ssid"] = "<hidden>"
        elif "Signal level=" in line:
            try:
                current["signal"] = int(line.split("Signal level=")[1].split(" ")[0])
            except Exception:
                pass
        elif "Encryption key:" in line:
            current["open"] = "off" in line.lower()

    if current.get("ssid") is not None:
        networks.append(current)

    # Deduplicate — keep strongest per SSID
    seen = {}
    for n in networks:
        ssid = n["ssid"]
        if ssid not in seen or n["signal"] > seen[ssid]["signal"]:
            seen[ssid] = n

    result = list(seen.values())
    result.sort(key=lambda n: n["signal"], reverse=True)
    return result


def _get_saved_ssids() -> set:
    """Return set of SSIDs that have saved credentials in NetworkManager."""
    code, out = _run_shell("nmcli -t -f NAME connection show")
    if code != 0:
        return set()
    return set(line.strip() for line in out.splitlines() if line.strip())


def _signal_bars(dbm: int) -> str:
    if dbm >= -50: return "IIII"
    if dbm >= -65: return "III."
    if dbm >= -75: return "II.."
    if dbm >= -85: return "I..."
    return "...."


# ── Network actions ───────────────────────────────────────────

def _connect_network(ssid: str, password: str) -> tuple:
    """
    Connect using nmcli. NM persists credentials automatically.
    Returns (success, message).
    """
    # Remove stale saved connection to avoid conflicts
    _run_shell(f'nmcli connection delete "{ssid}" 2>/dev/null || true')

    if password:
        cmd = f'sudo nmcli device wifi connect "{ssid}" password "{password}" ifname wlan0'
    else:
        cmd = f'sudo nmcli device wifi connect "{ssid}" ifname wlan0'

    code, out = _run_shell(cmd, timeout=30)

    if code == 0 and "successfully activated" in out.lower():
        return True, f"Connected to {ssid}"

    # Double-check via iwgetid
    time.sleep(2)
    if _get_current_ssid() == ssid:
        return True, f"Connected to {ssid}"

    # Return last line of nmcli output as error
    err = out.strip().split("\n")[-1][:38] if out.strip() else "Unknown error"
    return False, err


def _disconnect_network() -> tuple:
    """Disconnect wlan0 from current network."""
    code, out = _run_shell("sudo nmcli device disconnect wlan0", timeout=10)
    if code == 0:
        return True, "Disconnected"
    err = out.strip().split("\n")[-1][:38] if out.strip() else "Failed"
    return False, err


def _forget_network(ssid: str) -> tuple:
    """Delete saved connection profile for this SSID."""
    code, out = _run_shell(f'nmcli connection delete "{ssid}"', timeout=10)
    if code == 0:
        return True, f"Forgot {ssid}"
    # Try with sudo
    code, out = _run_shell(f'sudo nmcli connection delete "{ssid}"', timeout=10)
    if code == 0:
        return True, f"Forgot {ssid}"
    return False, "Forget failed"


# ── App ───────────────────────────────────────────────────────

class WifiManagerApp:
    SCREEN_LIST   = "list"
    SCREEN_DETAIL = "detail"
    SCREEN_PASS   = "pass"
    SCREEN_STATUS = "status"

    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts
        self.keyboard = OnScreenKeyboard(hw.disp, self.font_label)

        self.screen       = self.SCREEN_LIST
        self.networks     = []
        self.selected     = 0       # selected row in LIST
        self.scroll       = 0
        self.current_ssid = ""
        self.current_ip   = ""
        self.saved_ssids  = set()

        self.target_net   = None    # network dict for DETAIL / PASS
        self.detail_items = []      # action labels for DETAIL screen
        self.detail_sel   = 0       # selected action in DETAIL

        self.status_msg   = ""
        self.status_ok    = True

        self.scanning     = False
        self.scan_started = False
        self.auto_timer   = 0.0     # countdown to next auto-rescan

        self._dirty = True

    # ── Lifecycle ─────────────────────────────────────────────

    def on_enter(self):
        self.screen       = self.SCREEN_LIST
        self.networks     = []
        self.selected     = 0
        self.scroll       = 0
        self._trigger_scan()

    def _trigger_scan(self):
        self.scanning     = True
        self.scan_started = False
        self.auto_timer   = AUTO_RESCAN_INTERVAL
        self._dirty       = True

    # ── Main loop hooks ───────────────────────────────────────

    def on_event(self, event) -> str:
        if self.screen == self.SCREEN_LIST:
            return self._event_list(event)
        elif self.screen == self.SCREEN_DETAIL:
            return self._event_detail(event)
        elif self.screen == self.SCREEN_PASS:
            return self._event_pass(event)
        elif self.screen == self.SCREEN_STATUS:
            # Any key → back to list and rescan
            self.screen = self.SCREEN_LIST
            self._trigger_scan()
            return "stay"
        return "stay"

    def update(self, dt):
        # Run blocking scan once per scan session
        if self.scanning and not self.scan_started:
            self.scan_started = True
            self.networks     = _scan_networks()
            self.current_ssid = _get_current_ssid()
            self.current_ip   = _get_ip()
            self.saved_ssids  = _get_saved_ssids()
            self.selected     = 0
            self.scroll       = 0
            self.scanning     = False
            self._dirty       = True
            return

        # Auto-rescan countdown (only on LIST screen, not while scanning)
        if self.screen == self.SCREEN_LIST and not self.scanning:
            self.auto_timer -= dt
            if self.auto_timer <= 0:
                self._trigger_scan()

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        if self.screen == self.SCREEN_LIST:
            self._draw_list()
        elif self.screen == self.SCREEN_DETAIL:
            self._draw_detail()
        elif self.screen == self.SCREEN_PASS:
            self.keyboard.draw()
        elif self.screen == self.SCREEN_STATUS:
            self._draw_status()

    # ── Event handlers ────────────────────────────────────────

    def _event_list(self, event) -> str:
        if event == "KEY3":
            return "exit"

        if event == "KEY1":
            # Manual rescan
            self.networks = []
            self._trigger_scan()
            return "stay"

        max_rows = (self.hw.H - TOP_BAR_H - BOT_BAR_H) // ROW_H

        if event == "UP" and self.selected > 0:
            self.selected -= 1
            if self.selected < self.scroll:
                self.scroll = self.selected
            self._dirty = True

        elif event == "DOWN" and self.selected < len(self.networks) - 1:
            self.selected += 1
            if self.selected >= self.scroll + max_rows:
                self.scroll = self.selected - max_rows + 1
            self._dirty = True

        elif event == "CENTER" and self.networks:
            # Open detail screen for selected network
            self.target_net = self.networks[self.selected]
            self._build_detail_items()
            self.detail_sel = 0
            self.screen     = self.SCREEN_DETAIL
            self._dirty     = True

        return "stay"

    def _build_detail_items(self):
        """Build action list for DETAIL screen based on network state."""
        net = self.target_net
        items = []
        is_connected = (net["ssid"] == self.current_ssid)
        is_saved     = (net["ssid"] in self.saved_ssids)

        if is_connected:
            items.append(("disconnect", "Disconnect", RED))
        else:
            items.append(("connect", "Connect", GREEN))

        if is_saved:
            items.append(("forget", "Forget network", YELLOW))

        items.append(("back", "Back", GRAY))
        self.detail_items = items

    def _event_detail(self, event) -> str:
        if event == "KEY3":
            self.screen = self.SCREEN_LIST
            self._dirty = True
            return "stay"

        if event == "UP" and self.detail_sel > 0:
            self.detail_sel -= 1
            self._dirty = True

        elif event == "DOWN" and self.detail_sel < len(self.detail_items) - 1:
            self.detail_sel += 1
            self._dirty = True

        elif event == "CENTER":
            action, label, color = self.detail_items[self.detail_sel]

            if action == "back":
                self.screen = self.SCREEN_LIST
                self._dirty = True

            elif action == "connect":
                if self.target_net["open"]:
                    self._do_connect("")
                else:
                    self.screen = self.SCREEN_PASS
                    self.keyboard.start(
                        f"Password: {self.target_net['ssid'][:12]}",
                        initial_text="",
                        max_len=64
                    )
                    self._dirty = True

            elif action == "disconnect":
                self._do_action(_disconnect_network, "Disconnecting...")

            elif action == "forget":
                self._do_action(
                    lambda: _forget_network(self.target_net["ssid"]),
                    f"Forgetting\n{self.target_net['ssid']}..."
                )

        return "stay"

    def _event_pass(self, event) -> str:
        if event == "KEY3":
            self.screen = self.SCREEN_DETAIL
            self._dirty = True
            return "stay"

        if event == "KEY1":
            self.keyboard.cycle_language()
            self._dirty = True
            return "stay"

        if event == "KEY2":
            self._do_connect(self.keyboard.text)
            return "stay"

        action, text = self.keyboard.handle_event(event)
        if action == "redraw":
            self._dirty = True
        elif action == "done":
            self._do_connect(text or "")

        return "stay"

    # ── Actions ───────────────────────────────────────────────

    def _do_connect(self, password: str):
        if self.target_net is None:
            return
        self._show_status(f"Connecting to\n{self.target_net['ssid']}...", True)
        ok, msg = _connect_network(self.target_net["ssid"], password)
        self.status_ok  = ok
        self.status_msg = msg
        self._dirty     = True

    def _do_action(self, fn, loading_msg: str):
        """Run any blocking action with loading screen."""
        self._show_status(loading_msg, True)
        ok, msg = fn()
        self.status_ok  = ok
        self.status_msg = msg
        self._dirty     = True

    def _show_status(self, msg: str, ok: bool):
        """Immediately draw status screen (before blocking call)."""
        self.screen     = self.SCREEN_STATUS
        self.status_msg = msg
        self.status_ok  = ok
        self._dirty     = True
        self._draw_status()

    # ── Draw ──────────────────────────────────────────────────

    def _ts(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _draw_header(self, draw, W, title, hint=""):
        draw.rectangle([(0, 0), (W, TOP_BAR_H)], fill=HEADER_BG)
        tw, th = self._ts(draw, title, self.font_label)
        draw.text(((W - tw) // 2, (TOP_BAR_H - th) // 2),
                  title, font=self.font_label, fill=WHITE)
        if hint:
            hw2, hh2 = self._ts(draw, hint, self.font_label)
            draw.text((W - hw2 - 4, (TOP_BAR_H - hh2) // 2),
                      hint, font=self.font_label, fill=GRAY)
        draw.line([(0, TOP_BAR_H), (W, TOP_BAR_H)], fill=SEP, width=1)

    def _draw_list(self):
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG)
        draw  = ImageDraw.Draw(img)

        # Header — show SSID and auto-rescan countdown
        if self.scanning:
            self._draw_header(draw, W, "Wi-Fi  Scanning...", "K1:scan")
        else:
            ssid_short = (self.current_ssid[:9] + "…") if len(self.current_ssid) > 9 else (self.current_ssid or "none")
            countdown  = max(0, int(self.auto_timer))
            self._draw_header(draw, W, f"Wi-Fi [{ssid_short}]", f"K1:{countdown}s")

        # Bottom hint
        bot = "CTR:details  K3:exit"
        bw, bh = self._ts(draw, bot, self.font_label)
        draw.text(((W - bw) // 2, H - bh - 2),
                  bot, font=self.font_label, fill=HINT_COLOR)

        content_h = H - TOP_BAR_H - BOT_BAR_H

        if self.scanning or not self.networks:
            msg = "Scanning..." if self.scanning else "No networks found"
            mw, mh = self._ts(draw, msg, self.font_label)
            draw.text(((W - mw) // 2, TOP_BAR_H + (content_h - mh) // 2),
                      msg, font=self.font_label, fill=GRAY)
            self.hw.show(img)
            return

        # Show current IP under header if connected
        if self.current_ssid and self.current_ip:
            ip_str = f"IP: {self.current_ip}"
            iw, ih = self._ts(draw, ip_str, self.font_label)
            # Draw tiny IP line inside first visible area — but only if there's room
            # We'll just show it in status bar area (skip, already tight)

        # Network rows
        max_rows = content_h // ROW_H
        for row, idx in enumerate(range(self.scroll, min(self.scroll + max_rows, len(self.networks)))):
            net  = self.networks[idx]
            y0   = TOP_BAR_H + row * ROW_H
            y1   = y0 + ROW_H
            is_connected = net["ssid"] == self.current_ssid
            is_saved     = net["ssid"] in self.saved_ssids

            if idx == self.selected:
                draw.rectangle([(0, y0), (W - 1, y1 - 1)],
                               fill=ROW_SEL_BG, outline=WHITE, width=1)

            # SSID color: green=connected, blue=saved, white=unknown
            if is_connected:
                ssid_color = GREEN
            elif is_saved:
                ssid_color = BLUE
            else:
                ssid_color = WHITE

            ssid = (net["ssid"] or "<hidden>")[:15]
            draw.text((6, y0 + 4), ssid, font=self.font_label, fill=ssid_color)

            # Bottom line: ENC tag + saved indicator
            tags = []
            if not net["open"]:
                tags.append(("ENC", YELLOW))
            if is_saved:
                tags.append(("SAVED", BLUE))
            if is_connected:
                tags.append((self.current_ip or "connected", GREEN))

            x_tag = 6
            for tag_text, tag_color in tags:
                draw.text((x_tag, y0 + 4 + self.font_label.size + 3),
                          tag_text, font=self.font_label, fill=tag_color)
                tw2, _ = self._ts(draw, tag_text, self.font_label)
                x_tag += tw2 + 6

            # Signal bars + dBm on right
            bars = _signal_bars(net["signal"])
            bw2, _ = self._ts(draw, bars, self.font_label)
            draw.text((W - bw2 - 4, y0 + 4),
                      bars, font=self.font_label, fill=GREEN)

            dbm = f"{net['signal']}dBm"
            dw, _ = self._ts(draw, dbm, self.font_label)
            draw.text((W - dw - 4, y0 + 4 + self.font_label.size + 3),
                      dbm, font=self.font_label, fill=GRAY)

            draw.line([(0, y1 - 1), (W, y1 - 1)], fill=SEP, width=1)

        self.hw.show(img)

    def _draw_detail(self):
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG)
        draw  = ImageDraw.Draw(img)

        net = self.target_net
        self._draw_header(draw, W, "Network Details", "K3:back")

        y = TOP_BAR_H + 8
        line_h = self.font_label.size + 5

        # SSID large
        ssid = net["ssid"] or "<hidden>"
        sw, sh = self._ts(draw, ssid, self.font_small)
        draw.text(((W - sw) // 2, y), ssid, font=self.font_small, fill=WHITE)
        y += sh + 4

        # Info line: signal + open/enc
        enc_str  = "Open" if net["open"] else "Encrypted"
        info_str = f"{net['signal']}dBm  {enc_str}  {_signal_bars(net['signal'])}"
        iw, ih   = self._ts(draw, info_str, self.font_label)
        draw.text(((W - iw) // 2, y), info_str, font=self.font_label, fill=GRAY)
        y += ih + 4

        # IP if connected
        if net["ssid"] == self.current_ssid and self.current_ip:
            ip_str = f"IP: {self.current_ip}"
            ipw, iph = self._ts(draw, ip_str, self.font_label)
            draw.text(((W - ipw) // 2, y), ip_str, font=self.font_label, fill=GREEN)
            y += iph + 4

        # Divider
        draw.line([(10, y + 2), (W - 10, y + 2)], fill=SEP, width=1)
        y += 10

        # Action buttons
        btn_h = 28
        for idx, (action, label, color) in enumerate(self.detail_items):
            by0 = y + idx * (btn_h + 4)
            by1 = by0 + btn_h
            is_sel = idx == self.detail_sel

            bg_color = (50, 50, 50) if is_sel else (20, 20, 20)
            outline  = WHITE if is_sel else SEP

            draw.rounded_rectangle([(10, by0), (W - 10, by1)],
                                   radius=6, fill=bg_color, outline=outline, width=1)
            lw, lh = self._ts(draw, label, self.font_label)
            draw.text(((W - lw) // 2, by0 + (btn_h - lh) // 2),
                      label, font=self.font_label, fill=color)

        self.hw.show(img)

    def _draw_status(self):
        W, H  = self.hw.W, self.hw.H
        img   = Image.new("RGB", (W, H), BG)
        draw  = ImageDraw.Draw(img)

        self._draw_header(draw, W, "Wi-Fi")

        color = GREEN if self.status_ok else RED
        icon  = "OK" if self.status_ok else "ERR"

        iw, ih = self._ts(draw, icon, self.font_big)
        draw.text(((W - iw) // 2, TOP_BAR_H + 16),
                  icon, font=self.font_big, fill=color)

        y = TOP_BAR_H + 16 + ih + 10
        for line in self.status_msg.split("\n"):
            lw, lh = self._ts(draw, line, self.font_label)
            draw.text(((W - lw) // 2, y), line, font=self.font_label, fill=WHITE)
            y += lh + 4

        hint = "Any key: back"
        hw2, hh2 = self._ts(draw, hint, self.font_label)
        draw.text(((W - hw2) // 2, H - hh2 - 4),
                  hint, font=self.font_label, fill=HINT_COLOR)

        self.hw.show(img)
