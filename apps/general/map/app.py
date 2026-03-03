"""
apps/tools/map/app.py
GPS Map — shows current position on OpenStreetMap tiles.

Requires Wi-Fi. Tiles are cached in menu_fs/04_files/map_cache/.

Controls:
  UP / DOWN   — zoom in / out
  CENTER      — re-center on current position
  KEY3        — exit
"""

import os
import math
import time
import threading
import urllib.request

from PIL import Image, ImageDraw

try:
    import gps as gpslib
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────

TILE_SIZE   = 256
ZOOM_MIN    = 13
ZOOM_MAX    = 18
ZOOM_DEF    = 16

OSM_URL     = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT  = "pi-gadget-map/1.0"

CACHE_DIR   = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "menu_fs", "03_apps", "map_cache"
)

GPS_DEVICES = ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyACM1"]

TOP_H = 26
BOT_H = 18

BG     = (20,  20,  30)
HDR_BG = (8,   14,  28)
SEP_HI = (50,  90,  140)
WHITE  = (220, 235, 255)
DIM    = (70,  100, 140)
HINT   = (50,  75,  110)
CYAN   = (0,   210, 255)
GREEN  = (50,  220, 120)
RED    = (255, 70,  70)
YELLOW = (255, 200, 50)

# ── Tile math ─────────────────────────────────────────────────

def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple:
    """Convert lat/lon to tile x, y coordinates."""
    n    = 2 ** zoom
    x    = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y    = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def _tile_to_pixel_offset(lat: float, lon: float, zoom: int,
                          tile_x: int, tile_y: int) -> tuple:
    """Pixel offset of lat/lon within tile (tile_x, tile_y)."""
    n     = 2 ** zoom
    px    = (lon + 180.0) / 360.0 * n * TILE_SIZE - tile_x * TILE_SIZE
    lat_r = math.radians(lat)
    py    = ((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
             / 2.0 * n * TILE_SIZE - tile_y * TILE_SIZE)
    return int(px), int(py)


# ── Tile loading ──────────────────────────────────────────────

def _tile_cache_path(z: int, x: int, y: int) -> str:
    d = os.path.join(CACHE_DIR, str(z), str(x))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{y}.png")


def _load_tile(z: int, x: int, y: int) -> Image.Image | None:
    """Load tile from cache or download from OSM."""
    path = _tile_cache_path(z, x, y)
    if os.path.exists(path):
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            os.remove(path)

    url = OSM_URL.format(z=z, x=x, y=y)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _placeholder_tile(text: str = "") -> Image.Image:
    """Gray placeholder tile shown while loading."""
    img  = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (60, 60, 80, 255))
    draw = ImageDraw.Draw(img)
    if text:
        draw.text((8, 8), text, fill=(120, 120, 140))
    return img


# ── App ───────────────────────────────────────────────────────

class MapApp:
    def __init__(self, hw, fonts, monitor=None):
        self.hw = hw
        self.font_big, self.font_small, self.font_label = fonts

        self._zoom      = ZOOM_DEF
        self._lat       = None
        self._lon       = None
        self._fix       = False
        self._sats      = 0
        self._speed     = 0.0
        self._center_lat = None
        self._center_lon = None

        self._tile_cache  = {}   # (z, x, y) -> PIL Image
        self._loading     = set()
        self._dirty       = True
        self._status_msg  = "Waiting for GPS..."

        self._gps_thread  = None

    def on_enter(self):
        self._dirty = True
        self._ensure_gpsd()
        self._start_gps()

    def on_exit(self):
        pass

    def _ensure_gpsd(self):
        """Start gpsd if not running."""
        import subprocess
        try:
            r = subprocess.run(["pgrep", "gpsd"], capture_output=True, timeout=3)
            if r.returncode == 0:
                return
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
                except Exception:
                    pass
                break

    def _start_gps(self):
        if self._gps_thread and self._gps_thread.is_alive():
            return
        self._gps_thread = threading.Thread(target=self._gps_loop, daemon=True)
        self._gps_thread.start()

    def _gps_loop(self):
        if not GPS_AVAILABLE:
            return
        try:
            session = gpslib.gps(mode=gpslib.WATCH_ENABLE | gpslib.WATCH_NEWSTYLE)
            while True:
                try:
                    report = session.next()
                    if report["class"] == "TPV":
                        lat = report.get("lat")
                        lon = report.get("lon")
                        if lat and lon:
                            self._lat = lat
                            self._lon = lon
                            self._fix = True
                            spd = report.get("speed", 0)
                            self._speed = (spd * 3.6) if spd else 0
                            # Auto-center on first fix
                            if self._center_lat is None:
                                self._center_lat = lat
                                self._center_lon = lon
                            self._dirty = True
                    elif report["class"] == "SKY":
                        sats = report.get("satellites", [])
                        self._sats = sum(
                            1 for s in sats if s.get("used", False)
                        )
                        self._dirty = True
                except StopIteration:
                    break
                except Exception:
                    time.sleep(1)
        except Exception:
            pass

    def _recenter(self):
        """Center map on current GPS position."""
        if self._lat and self._lon:
            self._center_lat = self._lat
            self._center_lon = self._lon
            self._tile_cache.clear()
            self._dirty = True

    def on_event(self, event) -> str:
        if event == "KEY3":
            return "exit"
        elif event == "UP":
            if self._zoom < ZOOM_MAX:
                self._zoom += 1
                self._tile_cache.clear()
                self._dirty = True
        elif event == "DOWN":
            if self._zoom > ZOOM_MIN:
                self._zoom -= 1
                self._tile_cache.clear()
                self._dirty = True
        elif event == "CENTER":
            self._recenter()
        return "stay"

    def update(self, dt):
        pass

    def draw(self):
        if not self._dirty:
            return
        self._dirty = False

        W, H = self.hw.W, self.hw.H
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)

        # ── Header ────────────────────────────────────────────
        d.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
        d.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
        d.text((10, (TOP_H - self.font_label.size) // 2),
               "MAP", font=self.font_label, fill=CYAN)

        # GPS badge
        if self._fix:
            badge     = f"GPS ●  {self._sats}sat"
            badge_col = GREEN
        else:
            badge     = "GPS ○  no fix"
            badge_col = RED

        bw, bh = self._ts(d, badge, self.font_label)
        d.text((W - bw - 6, (TOP_H - bh) // 2),
               badge, font=self.font_label, fill=badge_col)
        d.line([(0, TOP_H), (W, TOP_H)], fill=SEP_HI, width=1)

        # ── Map area ──────────────────────────────────────────
        map_y0 = TOP_H
        map_h  = H - TOP_H - BOT_H

        if self._center_lat is None:
            # No position yet — show message
            msg = "Waiting for GPS fix..."
            mw, mh = self._ts(d, msg, self.font_label)
            d.text(((W - mw) // 2, map_y0 + map_h // 2 - mh),
                   msg, font=self.font_label, fill=YELLOW)
            sub = "Point antenna to sky"
            sw, sh = self._ts(d, sub, self.font_label)
            d.text(((W - sw) // 2, map_y0 + map_h // 2 + 4),
                   sub, font=self.font_label, fill=DIM)
        else:
            self._draw_map(img, d, W, map_y0, map_h)

        # ── Hint bar ──────────────────────────────────────────
        d.line([(0, H - BOT_H), (W, H - BOT_H)], fill=(25, 45, 75), width=1)

        # Speed on left, hint on right
        if self._fix:
            spd_s = f"{self._speed:.1f}km/h"
            d.text((4, H - BOT_H + 1), spd_s,
                   font=self.font_label, fill=DIM)

        hint   = f"z{self._zoom}  UP/DN:zoom  CTR:recenter  K3:exit"
        hw_, hh = self._ts(d, hint, self.font_label)
        d.text(((W - hw_) // 2, H - hh - 1),
               hint, font=self.font_label, fill=HINT)

        self.hw.show(img)

    def _draw_map(self, img, d, W, map_y0, map_h):
        """Render OSM tiles centered on _center_lat/_center_lon."""
        lat  = self._center_lat
        lon  = self._center_lon
        zoom = self._zoom

        # Center tile
        cx, cy = _lat_lon_to_tile(lat, lon, zoom)
        # Pixel offset of center within that tile
        px, py = _tile_to_pixel_offset(lat, lon, zoom, cx, cy)

        # How many tiles needed in each direction
        tiles_x = math.ceil(W / TILE_SIZE) + 2
        tiles_y = math.ceil(map_h / TILE_SIZE) + 2

        # Pixel of map center on screen
        screen_cx = W // 2
        screen_cy = map_y0 + map_h // 2

        # Top-left tile index
        start_tx = cx - tiles_x // 2
        start_ty = cy - tiles_y // 2

        # Pixel origin
        origin_x = screen_cx - px - (cx - start_tx) * TILE_SIZE
        origin_y = screen_cy - py - (cy - start_ty) * TILE_SIZE

        for tx_off in range(tiles_x + 1):
            for ty_off in range(tiles_y + 1):
                tx = start_tx + tx_off
                ty = start_ty + ty_off
                sx = origin_x + tx_off * TILE_SIZE
                sy = origin_y + ty_off * TILE_SIZE

                # Skip tiles completely outside visible area
                if sx + TILE_SIZE < 0 or sx > W:
                    continue
                if sy + TILE_SIZE < map_y0 or sy > map_y0 + map_h:
                    continue

                tile = self._get_tile(zoom, tx, ty)
                try:
                    img.paste(tile.convert("RGB"), (sx, sy))
                except Exception:
                    pass

        # ── Clip map to its area ──────────────────────────────
        # Draw black bars to mask overflow into header/hint
        d.rectangle([(0, 0), (W, map_y0)], fill=HDR_BG)

        # ── Position dot ──────────────────────────────────────
        if self._lat and self._lon:
            # Compute screen position of actual GPS location
            dpx, dpy = _tile_to_pixel_offset(
                self._lat, self._lon, zoom, cx, cy
            )
            dot_x = screen_cx + (dpx - px)
            dot_y = screen_cy + (dpy - py)

            # Only draw if on screen
            if map_y0 <= dot_y <= map_y0 + map_h:
                r = 6
                # White halo
                d.ellipse([(dot_x - r - 2, dot_y - r - 2),
                            (dot_x + r + 2, dot_y + r + 2)],
                           fill=(255, 255, 255))
                # Blue dot
                d.ellipse([(dot_x - r, dot_y - r),
                            (dot_x + r, dot_y + r)],
                           fill=(30, 120, 255))
                # Center pin
                d.ellipse([(dot_x - 2, dot_y - 2),
                            (dot_x + 2, dot_y + 2)],
                           fill=(255, 255, 255))

        # ── Accuracy circle (approximate) ─────────────────────
        # Zoom scale: at zoom 16, 1 tile = ~611m, so 1px ≈ 2.4m
        meters_per_px = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
        acc_px = int(20 / meters_per_px)  # ~20m accuracy circle
        if 3 < acc_px < 80:
            d.ellipse([(screen_cx - acc_px, screen_cy - acc_px),
                        (screen_cx + acc_px, screen_cy + acc_px)],
                       outline=(30, 120, 255, 128), width=1)

    def _get_tile(self, z: int, x: int, y: int) -> Image.Image:
        """Get tile from memory cache or start background download."""
        key = (z, x, y)
        if key in self._tile_cache:
            return self._tile_cache[key]

        if key not in self._loading:
            self._loading.add(key)
            threading.Thread(
                target=self._fetch_tile, args=(z, x, y), daemon=True
            ).start()

        return _placeholder_tile()

    def _fetch_tile(self, z: int, x: int, y: int):
        """Download tile in background thread, then trigger redraw."""
        key   = (z, x, y)
        tile  = _load_tile(z, x, y)
        if tile:
            self._tile_cache[key] = tile
        self._loading.discard(key)
        self._dirty = True

    @staticmethod
    def _ts(draw, text, font) -> tuple:
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0], b[3] - b[1]
