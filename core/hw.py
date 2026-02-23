import queue
import ST7789
from PIL import Image

try:
    from remote_ui import RemoteUI
    _REMOTE_AVAILABLE = True
except ImportError:
    _REMOTE_AVAILABLE = False


class _DisplayProxy:
    """
    A wrapper around ST7789 that intercepts ShowImage()
    and duplicates each frame into RemoteUI.
    This way any code (main_menu, keyboard, list_view, etc.)
    is automatically streamed to the browser without changes.
    """
    def __init__(self, real_disp):
        self._d = real_disp
        self._remote = None  # set after RemoteUI is created

    def __getattr__(self, name):
        # Proxy all other attributes/methods directly
        return getattr(self._d, name)

    def ShowImage(self, img):
        self._d.ShowImage(img)
        if self._remote is not None:
            # img is already rotated by 270° — rotate back for the browser
            self._remote.push_frame(img.rotate(90))


class HWDisplay:
    def __init__(self, remote=True, remote_port=5000):
        real_disp = ST7789.ST7789()
        real_disp.Init()
        real_disp.clear()
        real_disp.bl_DutyCycle(80)

        # Replace disp with a proxy — intercepts ALL ShowImage() calls in the project
        self.disp = _DisplayProxy(real_disp)

        self.W = real_disp.width
        self.H = real_disp.height

        self._remote_queue = queue.Queue()
        self._remote = None

        if remote and _REMOTE_AVAILABLE:
            self._remote = RemoteUI(self._remote_queue, port=remote_port)
            self.disp._remote = self._remote  # give the proxy access to remote
            self._remote.start()
        elif remote and not _REMOTE_AVAILABLE:
            print("[HWDisplay] Flask не установлен.")
            print("[HWDisplay] Установи: pip install flask --break-system-packages")

    def clear(self):
        self.disp.clear()

    def backlight(self, power):
        self.disp.bl_DutyCycle(power)

    def show(self, pil_img):
        rotated = pil_img.rotate(270)
        self.disp.ShowImage(rotated)  # proxy will call push_frame itself

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