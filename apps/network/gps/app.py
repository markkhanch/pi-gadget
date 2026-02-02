from PIL import Image, ImageDraw
import subprocess
import json
import time


class GpsApp:
    """
    Lightweight GPS application for the Network section.

    Shows:
      - status: NO MODULE / SEARCHING / 2D FIX / 3D FIX
      - latitude / longitude in human-readable format
      - altitude, speed, accuracy, satellites used/seen

    Design:
      - minimal use of gpspipe (short calls, small timeout)
      - tuned to real gpspipe JSON you provided
      - any TPV with valid lat/lon is treated as a fix
    """

    def __init__(self, hw, fonts, monitor):
        # hardware / screen
        self.hw = hw
        self.disp = hw.disp
        self.W = hw.W
        self.H = hw.H

        # fonts
        self.font_big, self.font_small, self.font_label = fonts
        self.monitor = monitor  # not used yet

        # internal state
        self.status = "SEARCH"   # "NO_GPS" | "SEARCH" | "FIX_2D" | "FIX_3D"
        self.lat = None
        self.lon = None
        self.alt_m = None
        self.speed_kmh = None
        self.acc_m = None
        self.sats_used = None
        self.sats_seen = None
        self.fix_dim = None      # 2 or 3

        # timing
        self.sample_interval = 5.0  # seconds
        self.last_sample_ts = 0.0

    # ---------- helpers ----------

    def _run_cmd(self, cmd, timeout=None):
        """Run external command safely. Returns text or ''. """
        try:
            out = subprocess.check_output(
                cmd,
                stderr=subprocess.DEVNULL,
                timeout=timeout
            )
            return out.decode("utf-8", errors="ignore")
        except Exception as e:
            print("[GPS APP] _run_cmd error:", e)
            return ""
    def _query_gps(self):
        """
        Single poll of gpsd via gpspipe.

        Strategy:
        - run: gpspipe -w -n 5 (timeout 4.0s)
        - берем ПЕРВУЮ TPV-строку с lat/lon
        - берем ПОСЛЕДНЮЮ SKY-строку для спутников
        Любая ошибка → статус SEARCH.
        """

        # reset values for this sample
        self.lat = None
        self.lon = None
        self.alt_m = None
        self.speed_kmh = None
        self.acc_m = None
        self.sats_used = None
        self.sats_seen = None
        self.fix_dim = None

        # 1) читаем небольшой кусок из gpspipe
        out = self._run_cmd(["gpspipe", "-w", "-n", "5"], timeout=4.0)
        if not out:
            self.status = "SEARCH"
            return

        lines = out.splitlines()

        first_tpv_line = None
        last_sky_line = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if '"class":"TPV"' in line and first_tpv_line is None:
                first_tpv_line = line
            elif '"class":"SKY"' in line:
                last_sky_line = line

        # 2) TPV
        if first_tpv_line is not None:
            try:
                tpv = json.loads(first_tpv_line)
            except Exception:
                tpv = None

            if tpv is not None:
                lat_raw = tpv.get("lat")
                lon_raw = tpv.get("lon")

                if lat_raw is not None and lon_raw is not None:
                    try:
                        self.lat = float(lat_raw)
                        self.lon = float(lon_raw)
                    except Exception:
                        self.lat = None
                        self.lon = None

                alt_raw = tpv.get("alt")
                try:
                    if alt_raw is not None:
                        self.alt_m = float(alt_raw)
                except Exception:
                    self.alt_m = None

                speed_raw = tpv.get("speed")
                try:
                    if speed_raw is not None:
                        self.speed_kmh = float(speed_raw) * 3.6
                except Exception:
                    self.speed_kmh = None

                acc_raw = tpv.get("eph") or tpv.get("epx") or tpv.get("epy")
                try:
                    if acc_raw is not None:
                        self.acc_m = float(acc_raw)
                except Exception:
                    self.acc_m = None

                mode = None
                mode_raw = tpv.get("mode")
                try:
                    if mode_raw is not None:
                        mode = int(mode_raw)
                except Exception:
                    mode = None

                if self.lat is not None and self.lon is not None:
                    if mode == 3:
                        self.fix_dim = 3
                        self.status = "FIX_3D"
                    else:
                        self.fix_dim = 2
                        self.status = "FIX_2D"
                else:
                    self.status = "SEARCH"
        else:
            self.status = "SEARCH"

        # 3) SKY
        if last_sky_line is not None:
            try:
                sky = json.loads(last_sky_line)
            except Exception:
                sky = None

            if sky is not None:
                sats = sky.get("satellites") or []
                used = 0
                seen = 0
                for sat in sats:
                    try:
                        seen += 1
                        if sat.get("used"):
                            used += 1
                    except Exception:
                        continue
                self.sats_used = used
                self.sats_seen = seen

    # ---------- lifecycle ----------

    def on_enter(self):
        """Called when entering the app."""
        self.status = "SEARCH"
        self.lat = None
        self.lon = None
        self.alt_m = None
        self.speed_kmh = None
        self.acc_m = None
        self.sats_used = None
        self.sats_seen = None
        self.fix_dim = None
        self.last_sample_ts = 0.0

        # first data immediately
        self._query_gps()

    def on_event(self, event):
        """
        Handle button events.
        KEY3 = Back.
        """
        if event == "KEY3":
            return "exit"
        return "stay"

    def update(self, dt):
        """
        Periodically poll gpspipe and update internal data.
        """
        now = time.time()
        if (now - self.last_sample_ts) < self.sample_interval:
            return

        self.last_sample_ts = now
        self._query_gps()

    # ---------- drawing ----------

    def _text_size(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _format_latlon(self, value, is_lat=True):
        """
        Format lat/lon as 37.12345° N / 122.12345° W.
        """
        if value is None:
            return "--"

        v = float(value)
        if is_lat:
            hemi = "N" if v >= 0 else "S"
        else:
            hemi = "E" if v >= 0 else "W"
        v_abs = abs(v)
        return f"{v_abs:.5f}° {hemi}"

    def _format_alt(self):
        if self.alt_m is None:
            return "Alt: -- m"
        return f"Alt: {self.alt_m:.1f} m"

    def _format_speed(self):
        if self.speed_kmh is None:
            return "Spd: -- km/h"
        return f"Spd: {self.speed_kmh:.1f} km/h"

    def _format_acc(self):
        if self.acc_m is None:
            return "Acc: -- m"
        return f"Acc: ±{self.acc_m:.1f} m"

    def _format_sats(self):
        if self.sats_used is None or self.sats_seen is None:
            return "Sat: --/--"
        return f"Sat: {self.sats_used}/{self.sats_seen}"

    def _status_text_and_color(self):
        """
        Returns (text, color) for the status line.
        """
        if self.status == "NO_GPS":
            return "NO MODULE", (200, 80, 80)
        if self.status == "SEARCH":
            return "SEARCHING...", (220, 200, 80)
        if self.status == "FIX_3D":
            return "3D FIX", (80, 220, 120)
        if self.status == "FIX_2D":
            return "2D FIX", (80, 180, 220)
        # fallback: unknown status → show as SEARCH
        return "SEARCHING...", (220, 200, 80)
    def draw(self):
        """Draw GPS screen."""
        img = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # status line at top
        status_text, status_color = self._status_text_and_color()
        st_w, st_h = self._text_size(draw, status_text, self.font_label)
        draw.text(((self.W - st_w) // 2, 4),
                  status_text, font=self.font_label, fill=status_color)

        # horizontal separator
        draw.line([(0, 24), (self.W, 24)], fill=(80, 80, 80), width=1)

        center_y = self.H // 2

        if self.status in ("NO_GPS", "SEARCH"):
            msg = (
                "Connect GPS module"
                if self.status == "NO_GPS"
                else "Searching satellites..."
            )
            color = (200, 200, 200) if self.status == "NO_GPS" else (220, 200, 80)
            mw, mh = self._text_size(draw, msg, self.font_label)
            draw.text(((self.W - mw) // 2, center_y - mh // 2),
                      msg, font=self.font_label, fill=color)

            if self.sats_seen is not None:
                sat_msg = f"{self.sats_seen} satellites visible"
                sw, sh = self._text_size(draw, sat_msg, self.font_label)
                draw.text(((self.W - sw) // 2, center_y + mh),
                          sat_msg, font=self.font_label, fill=(150, 150, 150))

        else:
            # FIX_2D or FIX_3D
            lat_str = self._format_latlon(self.lat, is_lat=True)
            lon_str = self._format_latlon(self.lon, is_lat=False)

            lat_w, lat_h = self._text_size(draw, lat_str, self.font_small)
            lon_w, lon_h = self._text_size(draw, lon_str, self.font_small)

            y_lat = center_y - lat_h - 4
            y_lon = center_y + 4

            draw.text(((self.W - lat_w) // 2, y_lat),
                      lat_str, font=self.font_small, fill=(200, 255, 200))
            draw.text(((self.W - lon_w) // 2, y_lon),
                      lon_str, font=self.font_small, fill=(200, 255, 255))

            # bottom info block: Alt / Spd / Acc / Sat
            alt_str = self._format_alt()
            spd_str = self._format_speed()
            acc_str = self._format_acc()
            sat_str = self._format_sats()

            info_lines = [alt_str, spd_str, acc_str, sat_str]

            # each line height
            line_h = self.font_label.size + 2

            # start a bit below center, so we don't touch the hint at the bottom
            # center_y ~ 120; center_y + 30 ~ 150; 4*line_h ~ 48 → до ~200px
            y_start = center_y + 30

            for i, txt in enumerate(info_lines):
                tw, th = self._text_size(draw, txt, self.font_label)
                draw.text(((self.W - tw) // 2, y_start + i * line_h),
                          txt, font=self.font_label, fill=(180, 180, 180))

        # bottom hint (always at the very bottom zone)
        hint = "KEY3: Back"
        hw, hh = self._text_size(draw, hint, self.font_label)
        draw.text(((self.W - hw) // 2, self.H - hh - 2),
                  hint, font=self.font_label, fill=(150, 150, 150))

        # rotate and show
        im_r = img.rotate(270)
        self.disp.ShowImage(im_r)
