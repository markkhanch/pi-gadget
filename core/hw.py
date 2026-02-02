import ST7789
from PIL import Image

class HWDisplay:
    def __init__(self):
        self.disp = ST7789.ST7789()
        self.disp.Init()
        self.disp.clear()
        self.disp.bl_DutyCycle(80)

        self.W = self.disp.width
        self.H = self.disp.height

    def clear(self):
        self.disp.clear()

    def backlight(self, power):
        self.disp.bl_DutyCycle(power)

    def show(self, pil_img):
        rotated = pil_img.rotate(270)
        self.disp.ShowImage(rotated)

    def gpio_read(self, pin):
        return self.disp.digital_read(pin)

    @property
    def pins(self):
        return {
            "UP": self.disp.GPIO_KEY_UP_PIN,
            "DOWN": self.disp.GPIO_KEY_DOWN_PIN,
            "LEFT": self.disp.GPIO_KEY_LEFT_PIN,
            "RIGHT": self.disp.GPIO_KEY_RIGHT_PIN,
            "CENTER": self.disp.GPIO_KEY_PRESS_PIN,
            "KEY1": self.disp.GPIO_KEY1_PIN,
            "KEY2": self.disp.GPIO_KEY2_PIN,
            "KEY3": self.disp.GPIO_KEY3_PIN,
        }
