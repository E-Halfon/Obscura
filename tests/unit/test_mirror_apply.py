"""SystemdMirror: publish before committing (_apply) and read-error handling (resync)."""

import sys
import types
import unittest
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)

try:
    import gi.repository  # noqa: F401
except ImportError:
    # mirror.py imports Gio/GLib at module level; _apply doesn't use them.
    repository = types.ModuleType("gi.repository")
    repository.Gio = object()
    repository.GLib = types.SimpleNamespace(Error=type("Error", (Exception,), {}))
    gi_module = types.ModuleType("gi")
    gi_module.repository = repository
    sys.modules.setdefault("gi", gi_module)
    sys.modules.setdefault("gi.repository", repository)

from obscura_capd import report
from gi.repository import GLib

from obscura_capd.mirror import SystemdMirror
from obscura_capd.vocabulary import Declaration
from obscura_capd.state import PresenceTable


class FakeExporter:
    def __init__(self, fail_apply=False, fail_announce=False):
        self.fail_apply = fail_apply
        self.fail_announce = fail_announce
        self.applied = []
        self.announced = []

    def apply(self, name, transition, since):
        if self.fail_apply:
            raise RuntimeError("publish failed")
        self.applied.append((name, transition))

    def announce(self, name, transition, since):
        if self.fail_announce:
            raise RuntimeError("emit failed")
        self.announced.append((name, transition))


class ApplyOrderTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(report, "_send")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.table = PresenceTable(["camera"])

    def mirror(self, exporter):
        return SystemdMirror(None, {}, self.table, exporter)

    def test_success_publishes_commits_announces(self):
        exporter = FakeExporter()
        self.mirror(exporter)._apply("camera", True, 5)
        self.assertTrue(self.table.is_present("camera"))
        self.assertEqual(exporter.applied, [("camera", "added")])
        self.assertEqual(exporter.announced, [("camera", "added")])

    def test_failed_publish_leaves_table_untouched_and_retries(self):
        exporter = FakeExporter(fail_apply=True)
        mirror = self.mirror(exporter)
        mirror._apply("camera", True, 5)
        self.assertFalse(self.table.is_present("camera"))
        self.assertEqual(exporter.announced, [])
        exporter.fail_apply = False
        mirror._apply("camera", True, 5)
        self.assertTrue(self.table.is_present("camera"))
        self.assertEqual(exporter.applied, [("camera", "added")])

    def test_failed_unpublish_keeps_capability_present(self):
        self.table.update("camera", True, 5)
        self.mirror(FakeExporter(fail_apply=True))._apply("camera", False, 0)
        self.assertTrue(self.table.is_present("camera"))

    def test_no_transition_touches_nothing(self):
        exporter = FakeExporter()
        self.mirror(exporter)._apply("camera", False, 0)
        self.assertEqual(exporter.applied, [])
        self.assertEqual(exporter.announced, [])


class ResyncReadErrorTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(report, "_send")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.table = PresenceTable(["camera"])
        self.table.update("camera", True, 5)
        declaration = Declaration("camera", 1, "device", "obscura-cap-camera.target", "A camera", "camera.toml")
        self.exporter = FakeExporter()
        self.mirror = SystemdMirror(None, {"camera": declaration}, self.table, self.exporter)

    def test_transport_error_keeps_previous_state(self):
        with mock.patch.object(self.mirror, "_read_target", side_effect=GLib.Error("timeout")):
            self.mirror.resync("camera")
        self.assertTrue(self.table.is_present("camera"))
        self.assertEqual(self.exporter.applied, [])

    def test_uninterpretable_reply_is_absent(self):
        with mock.patch.object(self.mirror, "_read_target", side_effect=ValueError("bad reply")):
            self.mirror.resync("camera")
        self.assertFalse(self.table.is_present("camera"))
        self.assertEqual(self.exporter.applied, [("camera", "removed")])


if __name__ == "__main__":
    unittest.main()
