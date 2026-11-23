"""Unit-state interpretation and presence tracking (obscura_capd.state)."""

import unittest
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)
from obscura_capd import report
from obscura_capd.state import PresenceTable, interpret_unit, object_path_for


class InterpretUnitTest(unittest.TestCase):
    def test_only_loaded_active_is_present(self):
        self.assertEqual(interpret_unit("loaded", "active").present, True)
        self.assertIsNone(interpret_unit("loaded", "active").problem)

    def test_normal_absence_has_no_problem(self):
        for active_state in ("inactive", "activating", "deactivating"):
            with self.subTest(active_state):
                reading = interpret_unit("loaded", active_state)
                self.assertFalse(reading.present)
                self.assertIsNone(reading.problem)

    def test_abnormal_states_are_absent_with_a_problem(self):
        for load_state, active_state in (("loaded", "failed"), ("not-found", "inactive"),
                                         ("error", "inactive"), ("bad-setting", "inactive"),
                                         ("loaded", "reloading")):
            with self.subTest((load_state, active_state)):
                reading = interpret_unit(load_state, active_state)
                self.assertFalse(reading.present)
                self.assertIsNotNone(reading.problem)
                self.assertFalse(reading.deliberate)

    def test_masked_is_deliberate(self):
        reading = interpret_unit("masked", "inactive")
        self.assertFalse(reading.present)
        self.assertTrue(reading.deliberate)


class PresenceTableTest(unittest.TestCase):
    def setUp(self):
        self.table = PresenceTable(["battery", "camera", "virt"])

    def test_transitions(self):
        self.assertEqual(self.table.update("camera", True, 100), "added")
        self.assertIsNone(self.table.update("camera", True, 100))
        self.assertTrue(self.table.is_present("camera"))
        self.assertEqual(self.table.since("camera"), 100)
        self.assertEqual(self.table.update("camera", False, 0), "removed")
        self.assertIsNone(self.table.update("camera", False, 0))
        self.assertEqual(self.table.since("camera"), 0)

    def test_lists_are_sorted(self):
        self.table.update("virt", True, 1)
        self.table.update("battery", True, 2)
        self.assertEqual(self.table.present_names(), ["battery", "virt"])
        self.assertEqual(self.table.declared_names(), ["battery", "camera", "virt"])

    def test_undeclared_name_raises(self):
        with mock.patch.object(report, "_send") as sent:
            with self.assertRaises(KeyError):
                self.table.update("windows-apps", True, 1)
        self.assertEqual(sent.call_count, 1, "the unexpected failure is reported once")
        self.assertFalse(self.table.is_declared("windows-apps"))

    def test_problem_logged_once_until_it_changes(self):
        self.assertTrue(self.table.note_problem("camera", "target ActiveState is failed"))
        self.assertFalse(self.table.note_problem("camera", "target ActiveState is failed"))
        self.assertFalse(self.table.note_problem("camera", None))
        self.assertTrue(self.table.note_problem("camera", "target ActiveState is failed"))


class ObjectPathTest(unittest.TestCase):
    def test_hyphens_become_underscores(self):
        self.assertEqual(object_path_for("x86-64-v3"), "/org/obscura/Capabilities1/cap/x86_64_v3")
        self.assertEqual(object_path_for("virt"), "/org/obscura/Capabilities1/cap/virt")


if __name__ == "__main__":
    unittest.main()
