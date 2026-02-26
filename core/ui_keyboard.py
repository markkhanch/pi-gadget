# ui_keyboard.py
# On-screen keyboard for 240x240 ST7789 gadget

from PIL import Image, ImageDraw

SCREEN_WIDTH = 240
SCREEN_HEIGHT = 240


class OnScreenKeyboard:
    """
    Phone-style on-screen keyboard.

    Controls:
      - Joystick UP/DOWN/LEFT/RIGHT: move between keys
      - Joystick CENTER: press selected key
      - KEY1 / KEY2 / KEY3 are handled in main.py:
          * KEY1: cycle language (EN <-> RU) in letters mode
          * KEY2: confirm (OK) using current self.text
          * KEY3: cancel (exit without saving)

    API for main.py:
      - start(prompt, initial_text="", max_len=16)
      - handle_event(event) -> (action, text_or_none)
          action: "redraw" | "done" | None
      - draw()
      - cycle_language()
      - .text contains current value
    """

    def __init__(self, disp, font_label):
        self.disp = disp
        self.font = font_label

        # Text / prompt
        self.prompt = "Text"
        self.text = ""
        self.max_len = 64

        # Keyboard state
        self.mode = "letters_en"  # "letters_en" | "letters_ru" | "num_sym"
        self.shift = False
        self.cursor_row = 0
        self.cursor_col = 0

        # Base layouts (lowercase for letters, shift will upper them)
        self.letters_en_rows = [
            list("qwertyuiop"),
            list("asdfghjkl"),
            list("zxcvbnm"),
        ]

        # Simple Russian layout (QWERTY-like)
        self.letters_ru_rows = [
            list("йцукенгшщз"),
            list("фывапролд"),
            list("ячсмитьбю"),
        ]

        self.num_rows = [
            list("1234567890"),
            ["-", "_", "@", ".", ",", "?"],
            ["!", "?", ":", ";", "(", ")"],
        ]

    # ---------- Public API ----------

    def start(self, prompt: str, initial_text: str = "", max_len: int = 64):
        """Prepare keyboard for new input session."""
        self.prompt = prompt
        self.text = initial_text or ""
        self.max_len = max_len

        # Reset navigation & view
        self.mode = "letters_en"
        self.shift = False
        self.cursor_row = 0
        self.cursor_col = 0

    def cycle_language(self):
        """
        Switch language between EN and RU in letters mode.
        If currently in num_sym, jump back to EN.
        """
        if self.mode == "num_sym":
            self.mode = "letters_en"
        elif self.mode == "letters_en":
            self.mode = "letters_ru"
        elif self.mode == "letters_ru":
            self.mode = "letters_en"

    def handle_event(self, event):
        """
        Handle joystick events.
        event: "UP" | "DOWN" | "LEFT" | "RIGHT" | "CENTER" | ...
        Returns:
          ("redraw", None) -> need redraw
          ("done", text)   -> user pressed on-screen "return"
          (None, None)     -> nothing important
        """
        rows = self._get_layout_rows()

        # Navigation
        if event in ("UP", "DOWN", "LEFT", "RIGHT"):
            max_row = len(rows) - 1

            if event == "UP" and self.cursor_row > 0:
                self.cursor_row -= 1
            elif event == "DOWN" and self.cursor_row < max_row:
                self.cursor_row += 1
            elif event == "LEFT" and self.cursor_col > 0:
                self.cursor_col -= 1
            elif event == "RIGHT":
                if self.cursor_col < len(rows[self.cursor_row]) - 1:
                    self.cursor_col += 1

            # Clamp column if moving to shorter row
            if self.cursor_col >= len(rows[self.cursor_row]):
                self.cursor_col = len(rows[self.cursor_row]) - 1

            return "redraw", None

        # Key press
        if event == "CENTER":
            label = self._get_current_key_label()
            if label is None:
                return None, None

            # Special keys from system row
            if label == "space":
                if len(self.text) < self.max_len:
                    self.text += " "
                return "redraw", None

            if label == "⌫":
                if self.text:
                    self.text = self.text[:-1]
                return "redraw", None

            if label == "return":
                # On-screen return key acts like "done"
                return "done", self.text

            if label in ("123", "ABC"):
                # Switch between num_sym and letters
                if self.mode == "num_sym":
                    self.mode = "letters_en"
                else:
                    self.mode = "num_sym"
                # After mode change, keep cursor in system row on same key index
                self.cursor_row = min(self.cursor_row, len(self._get_layout_rows()) - 1)
                self.cursor_col = min(self.cursor_col, len(self._get_layout_rows()[self.cursor_row]) - 1)
                return "redraw", None

            if label == "Shift":
                self.shift = not self.shift
                return "redraw", None

            # Regular character
            if len(label) == 1 and len(self.text) < self.max_len:
                self.text += label
                return "redraw", None

        return None, None

    def draw(self):
        """Draw keyboard and current text on display."""
        width = SCREEN_WIDTH
        height = SCREEN_HEIGHT

        image = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Top input field
        top_margin = 4
        input_h = 40
        box_x0 = 4
        box_y0 = top_margin
        box_x1 = width - 4
        box_y1 = box_y0 + input_h

        draw.rounded_rectangle(
            [(box_x0, box_y0), (box_x1, box_y1)],
            radius=10,
            fill=(25, 25, 25),
            outline=(80, 80, 80),
            width=1,
        )

        # Draw current text (tail if too long)
        display_text = self.text
        max_chars_display = 18
        if len(display_text) > max_chars_display:
            display_text = display_text[-max_chars_display:]

        text_w, text_h = self._text_size(draw, display_text)
        text_x = box_x0 + 8
        text_y = box_y0 + (input_h - text_h) // 2
        draw.text((text_x, text_y), display_text, font=self.font, fill=(220, 220, 220))

        # Layout indicator in top-right corner
        indicator = self._get_layout_indicator()
        ind_w, ind_h = self._text_size(draw, indicator)
        ind_x = box_x1 - ind_w - 6
        ind_y = box_y0 + (input_h - ind_h) // 2
        draw.text((ind_x, ind_y), indicator, font=self.font, fill=(150, 150, 150))

        # Keyboard area
        kb_margin_x = 4
        kb_margin_bottom = 4
        kb_top = box_y1 + 6
        kb_bottom = height - kb_margin_bottom
        kb_height = kb_bottom - kb_top

        rows = self._get_layout_rows()
        rows_count = len(rows)
        row_h = kb_height // rows_count

        for r, row_keys in enumerate(rows):
            # Weights: letters = 1 each, system row = custom weights
            weights = []
            if r < rows_count - 1:
                weights = [1.0] * len(row_keys)
            else:
                # System row: [mode, Shift, space, ⌫, return]
                # Important: order must match row_keys
                for label in row_keys:
                    if label in ("123", "ABC", "Shift", "⌫", "return"):
                        weights.append(1.2)
                    elif label == "space":
                        weights.append(4.0)
                    else:
                        weights.append(1.0)

            total_w = sum(weights)
            available_w = width - kb_margin_x * 2
            x = kb_margin_x
            y0 = kb_top + r * row_h
            y1 = y0 + row_h - 4  # a bit of vertical margin

            for c, label in enumerate(row_keys):
                w = int(available_w * (weights[c] / total_w))
                key_x0 = x + 2
                key_x1 = x + w - 4

                # Rounded button
                selected = (r == self.cursor_row and c == self.cursor_col)
                if selected:
                    fill_color = (80, 80, 80)
                    outline_color = (255, 255, 255)
                else:
                    fill_color = (35, 35, 35)
                    outline_color = (80, 80, 80)

                draw.rounded_rectangle(
                    [(key_x0, y0), (key_x1, y1)],
                    radius=10,
                    fill=fill_color,
                    outline=outline_color,
                    width=1,
                )

                # Label
                label_text = label
                label_w, label_h = self._text_size(draw, label_text)
                label_x = key_x0 + (key_x1 - key_x0 - label_w) // 2
                label_y = y0 + (y1 - y0 - label_h) // 2
                draw.text((label_x, label_y), label_text, font=self.font, fill=(255, 255, 255))

                x += w

        # Rotate 270° for Waveshare ST7789
        im_r = image.rotate(270)
        self.disp.ShowImage(im_r)

    # ---------- Internal helpers ----------

    def _text_size(self, draw: ImageDraw.ImageDraw, text: str):
        if not text:
            return 0, 0
        bbox = draw.textbbox((0, 0), text, font=self.font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _get_layout_indicator(self) -> str:
        """Return short indicator like EN, EN↑, RU, RU↑, 123."""
        if self.mode == "num_sym":
            return "123"
        if self.mode == "letters_en":
            return "EN↑" if self.shift else "EN"
        if self.mode == "letters_ru":
            return "RU↑" if self.shift else "RU"
        return "?"

    def _get_layout_rows(self):
        """
        Return list of rows, each row is list of labels (strings).
        Last row is the system row: [mode_switch, Shift, space, ⌫, return]
        """
        if self.mode == "letters_en":
            base_rows = self.letters_en_rows
        elif self.mode == "letters_ru":
            base_rows = self.letters_ru_rows
        else:  # num_sym
            base_rows = self.num_rows

        rows = []

        # 3 main rows
        for base_row in base_rows:
            row = []
            for ch in base_row:
                if self.mode.startswith("letters"):
                    row.append(ch.upper() if self.shift else ch.lower())
                else:
                    # num_sym: no shift effect
                    row.append(ch)
            rows.append(row)

        # System row
        if self.mode == "num_sym":
            mode_label = "ABC"
        else:
            mode_label = "123"

        system_row = [mode_label, "Shift", "space", "⌫", "return"]
        rows.append(system_row)

        return rows

    def _get_current_key_label(self):
        rows = self._get_layout_rows()
        if self.cursor_row < 0 or self.cursor_row >= len(rows):
            return None
        row = rows[self.cursor_row]
        if self.cursor_col < 0 or self.cursor_col >= len(row):
            return None
        return row[self.cursor_col]
