"""
tests/test_ui_helpers.py
Unit tests for ui/helpers.py — shared drawing utilities.
"""

import unittest
from unittest.mock import MagicMock
from ui.helpers import text_size, trunc


class _FakeFont:
    """Stub font where each character has width=8, height=12."""

    def getbbox(self, text, *args, **kwargs):
        return (0, 0, len(text) * 8, 12)


class _FakeDraw:
    """Stub ImageDraw that uses _FakeFont for textbbox."""

    def textbbox(self, xy, text, font=None, **kw):
        return font.getbbox(text)


class TestTextSize(unittest.TestCase):

    def setUp(self):
        self.draw = _FakeDraw()
        self.font = _FakeFont()

    def test_basic(self):
        w, h = text_size(self.draw, "Hello", self.font)
        self.assertEqual(w, 40)  # 5 chars × 8
        self.assertEqual(h, 12)

    def test_empty(self):
        w, h = text_size(self.draw, "", self.font)
        self.assertEqual(w, 0)
        # Height may still reflect font metrics even for empty string
        self.assertGreaterEqual(h, 0)

    def test_single_char(self):
        w, h = text_size(self.draw, "X", self.font)
        self.assertEqual(w, 8)
        self.assertEqual(h, 12)


class TestTrunc(unittest.TestCase):

    def setUp(self):
        self.draw = _FakeDraw()
        self.font = _FakeFont()

    def test_no_truncation_needed(self):
        result = trunc(self.draw, "Hi", self.font, 100)
        self.assertEqual(result, "Hi")

    def test_truncation(self):
        result = trunc(self.draw, "Hello World", self.font, 50)
        self.assertIn("…", result)
        w, _ = text_size(self.draw, result, self.font)
        self.assertLessEqual(w, 50)

    def test_exact_fit(self):
        # "ABC" = 3×8 = 24 pixels
        result = trunc(self.draw, "ABC", self.font, 24)
        self.assertEqual(result, "ABC")

    def test_empty_string(self):
        result = trunc(self.draw, "", self.font, 50)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
