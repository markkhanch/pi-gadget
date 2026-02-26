import queue
from core import ST7789
from PIL import Image

try:
    from remote_ui import RemoteUI
    _REMOTE_AVAILABLE = True
except ImportError:
    _REMOTE_AVAILABLE = False

# Singleton guard — ensures RemoteUI starts only once even if HWDisplay is imported multiple times
_remote_instance = None


class _DisplayProxy:
    """
    Wrapper around ST7789 that intercepts every ShowImage() call
    and forwards the frame to RemoteUI for browser streaming.
    """
    def __init__(self, real_disp):
        self._d = real_disp
        self._remote = None

    def __getattr__(self, name):
        return getattr(self._d, name)

    def ShowImage(self, img):
        self._d.ShowImage(img)
        if self._remote is not None:
            # img is already rotated 270° for the physical display — rotate back for browser
            self._remote.push_frame(img.rotate(90))


class HWDisplay:
    def __init__(self, remote=True, remote_port=5000):
        global _remote_instance

        real_disp = ST7789.ST7789()
        real_disp.Init()
        real_disp.clear()
        real_disp.bl_DutyCycle(80)

        # Replace disp with proxy — intercepts ALL ShowImage() calls project-wide
        self.disp = _DisplayProxy(real_disp)

        self.W = real_disp.width
        self.H = real_disp.height

        self._remote_queue = queue.Queue()
        self._remote = None

        if remote and _REMOTE_AVAILABLE:
            if _remote_instance is None:
                # Start RemoteUI only once
                _remote_instance = RemoteUI(self._remote_queue, port=remote_port)
                _remote_instance.start()
            else:
                # Reuse existing instance's queue
                self._remote_queue = _remote_instance.button_queue

            self._remote = _remote_instance
            self.disp._remote = _remote_instance

        elif remote and not _REMOTE_AVAILABLE:
            print("[HWDisplay] Flask not installed.")
            print("[HWDisplay] Run: pip install flask --break-system-packages")

    def clear(self):
        self.disp.clear()

    def backlight(self, power):
        self.disp.bl_DutyCycle(power)

    def show(self, pil_img):
        rotated = pil_img.rotate(270)
        self.disp.ShowImage(rotated)  # proxy handles push_frame automatically

    def gpio_read(self, pin):
        return self.disp.digital_read(pin)

    def pop_remote_event(self):
        try:
            return self._remote_queue.get_nowait()
        except queue.Empty:
            return None

    @property
    def pins(self):
        return {
            "UP":     self.disp.GPIO_KEY_UP_PIN,
            "DOWN":   self.disp.GPIO_KEY_DOWN_PIN,
            "LEFT":   self.disp.GPIO_KEY_LEFT_PIN,
            "RIGHT":  self.disp.GPIO_KEY_RIGHT_PIN,
            "CENTER": self.disp.GPIO_KEY_PRESS_PIN,
            "KEY1":   self.disp.GPIO_KEY1_PIN,
            "KEY2":   self.disp.GPIO_KEY2_PIN,
            "KEY3":   self.disp.GPIO_KEY3_PIN,
        }
