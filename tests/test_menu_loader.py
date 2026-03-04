"""
tests/test_menu_loader.py
Unit tests for core/menu_loader.py — menu loading utilities.
"""

import os
import json
import shutil
import tempfile
import unittest

from core.menu_loader import _fmt_size, _read_meta


class TestFmtSize(unittest.TestCase):

    def test_bytes(self):
        self.assertEqual(_fmt_size(100), "100B")

    def test_kilobytes(self):
        self.assertEqual(_fmt_size(2048), "2KB")

    def test_megabytes(self):
        result = _fmt_size(1536 * 1024)
        self.assertIn("MB", result)

    def test_zero(self):
        self.assertEqual(_fmt_size(0), "0B")


class TestReadMeta(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_no_meta_file(self):
        result = _read_meta(self.tmpdir)
        self.assertEqual(result, {})

    def test_valid_meta(self):
        meta = {"display_name": "Test", "icon": "test.png", "visible": True}
        with open(os.path.join(self.tmpdir, ".meta.json"), "w") as f:
            json.dump(meta, f)
        result = _read_meta(self.tmpdir)
        self.assertEqual(result["display_name"], "Test")

    def test_invalid_json(self):
        with open(os.path.join(self.tmpdir, ".meta.json"), "w") as f:
            f.write("not valid json {{{")
        result = _read_meta(self.tmpdir)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
