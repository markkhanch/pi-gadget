"""
tests/test_background.py
Unit tests for core/background.py — BackgroundManager.
"""

import unittest
from core.background import BackgroundManager


class TestBackgroundManager(unittest.TestCase):

    def setUp(self):
        self.bgm = BackgroundManager()

    def test_empty(self):
        self.assertFalse(self.bgm.has_active())
        self.assertEqual(self.bgm.active_tasks(), [])

    def test_register_unregister(self):
        self.bgm.register("test_task", ["wlan1_monitor"], lambda: None)
        self.assertTrue(self.bgm.has_active())
        self.assertIn("test_task", self.bgm.active_tasks())

        self.bgm.unregister("test_task")
        self.assertFalse(self.bgm.has_active())

    def test_conflicts(self):
        self.bgm.register("task1", ["wlan1_monitor"], lambda: None)

        conflicts = self.bgm.conflicts_for(["wlan1_monitor"])
        self.assertEqual(conflicts, ["task1"])

        no_conflicts = self.bgm.conflicts_for(["wlan0_ap"])
        self.assertEqual(no_conflicts, [])

    def test_stop_calls_stop_fn(self):
        stopped = []
        self.bgm.register("task1", [], lambda: stopped.append(True))

        self.bgm.stop("task1")
        self.assertEqual(stopped, [True])
        self.assertFalse(self.bgm.has_active())

    def test_stop_all(self):
        stopped = []
        self.bgm.register("t1", [], lambda: stopped.append("t1"))
        self.bgm.register("t2", [], lambda: stopped.append("t2"))

        self.bgm.stop_all()
        self.assertFalse(self.bgm.has_active())
        self.assertEqual(sorted(stopped), ["t1", "t2"])

    def test_uptime(self):
        self.bgm.register("task1", [], lambda: None)
        uptime = self.bgm.uptime("task1")
        self.assertGreaterEqual(uptime, 0)

    def test_uptime_nonexistent(self):
        self.assertEqual(self.bgm.uptime("nonexistent"), 0)

    def test_get_instance_by_module(self):
        obj = object()
        self.bgm.register("task1", [], lambda: None,
                          instance=obj, module="test.module")
        name, instance = self.bgm.get_instance_by_module("test.module")
        self.assertEqual(name, "task1")
        self.assertIs(instance, obj)

    def test_get_instance_by_module_not_found(self):
        name, instance = self.bgm.get_instance_by_module("not.found")
        self.assertIsNone(name)
        self.assertIsNone(instance)


if __name__ == "__main__":
    unittest.main()
