"""
tests/test_fs_ops.py
Unit tests for core/fs_ops.py — file system utility functions.
"""

import os
import json
import shutil
import tempfile
import unittest

from core.fs_ops import sanitize_fs_name, _unique_path, _fmt_size


class TestSanitizeFsName(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(sanitize_fs_name("hello"), "hello")

    def test_spaces(self):
        self.assertEqual(sanitize_fs_name("my folder"), "my_folder")

    def test_special_chars(self):
        self.assertEqual(sanitize_fs_name("a@b#c$d"), "abcd")

    def test_preserves_valid(self):
        self.assertEqual(sanitize_fs_name("test-file_01.txt"), "test-file_01.txt")

    def test_leading_trailing_spaces(self):
        self.assertEqual(sanitize_fs_name("  hello  "), "hello")

    def test_empty(self):
        self.assertEqual(sanitize_fs_name(""), "")


class TestUniquePath(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_no_conflict(self):
        result = _unique_path(self.tmpdir, "test.txt")
        self.assertEqual(result, os.path.join(self.tmpdir, "test.txt"))

    def test_with_conflict(self):
        # Create the file so there's a conflict
        open(os.path.join(self.tmpdir, "test.txt"), "w").close()
        result = _unique_path(self.tmpdir, "test.txt")
        self.assertEqual(result, os.path.join(self.tmpdir, "test_1.txt"))

    def test_multiple_conflicts(self):
        open(os.path.join(self.tmpdir, "test.txt"), "w").close()
        open(os.path.join(self.tmpdir, "test_1.txt"), "w").close()
        result = _unique_path(self.tmpdir, "test.txt")
        self.assertEqual(result, os.path.join(self.tmpdir, "test_2.txt"))


class TestFmtSize(unittest.TestCase):

    def test_bytes(self):
        self.assertEqual(_fmt_size(500), "500 B")

    def test_kilobytes(self):
        self.assertIn("KB", _fmt_size(2048))

    def test_megabytes(self):
        self.assertIn("MB", _fmt_size(2 * 1024 * 1024))

    def test_zero(self):
        self.assertEqual(_fmt_size(0), "0 B")


if __name__ == "__main__":
    unittest.main()
