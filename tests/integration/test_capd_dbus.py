"""obscura-capd end to end against a mock systemd on a private system bus.

Covers the design's C-1 (clean absence), C-3/C-4 (appear/disappear, signal per change),
C-5 (restart rebuilds state), and C-6 (query semantics) without real hardware. Real
udev/systemd behavior is covered by tests/vm/capabilities.sh on the built image.

Needs (Linux): dasbus, PyGObject, dbus-python, python-dbusmock, dbus-daemon.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import unittest

from tests import CAPD_PYTHONPATH, VOCABULARY_DIR

try:
    import dbus
    import dbusmock
    import dasbus  # noqa: F401  (needed by the daemon under test)
except ImportError as missing:
    dbus = None
    SKIP_REASON = "integration dependencies missing: " + str(missing)
else:
    SKIP_REASON = ""

BUS_NAME = "org.obscura.Capabilities1"
MANAGER_PATH = "/org/obscura/Capabilities1"
MANAGER_INTERFACE = "org.obscura.Capabilities1"
CAPABILITY_INTERFACE = "org.obscura.Capabilities1.Capability"
SYSTEMD_MANAGER = "org.freedesktop.systemd1.Manager"
SYSTEMD_UNIT = "org.freedesktop.systemd1.Unit"
TIMEOUT = 5.0

# Mirrors systemd's unit path escaping closely enough for these names.
LOAD_UNIT = (
    "ret = dbus.ObjectPath('/org/freedesktop/systemd1/unit/' + "
    "args[0].replace('-', '_2d').replace('.', '_2e'))"
)


def unit_path(target):
    return "/org/freedesktop/systemd1/unit/" + target.replace("-", "_2d").replace(".", "_2e")


def wait_for(predicate, message):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.05)
    raise AssertionError("timed out: " + message)


@unittest.skipIf(dbus is None, SKIP_REASON)
class CapdHarness(dbusmock.DBusTestCase if dbus is not None else unittest.TestCase):
    """Private system bus, mock systemd, and capd. Holds no tests, so other integration
    suites (e.g. test_packs_capd) can reuse it."""

    @classmethod
    def setUpClass(cls):
        cls.start_system_bus()
        cls.system_bus = cls.get_dbus(system_bus=True)

    def setUp(self):
        self.systemd_process = self.spawn_server(
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1", SYSTEMD_MANAGER,
            system_bus=True, stdout=subprocess.DEVNULL,
        )
        self.addCleanup(self.stop_process, self.systemd_process)
        systemd = self.system_bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
        self.systemd_mock = dbus.Interface(systemd, dbusmock.MOCK_IFACE)
        self.systemd_mock.AddMethod("", "Subscribe", "", "", "")
        self.systemd_mock.AddMethod("", "LoadUnit", "s", "o", LOAD_UNIT)

        # Starting point: battery present, everything else absent.
        self.add_target("obscura-cap-battery.target", "active", 1700000000000000)
        self.add_target("obscura-cap-camera.target", "inactive", 0)
        self.add_target("obscura-cap-virt.target", "inactive", 0)
        self.add_target("obscura-cap-x86-64-v3.target", "inactive", 0)
        self.capd = None
        self.watch_lines = None

    # -- helpers ---------------------------------------------------------------------

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def add_target(self, target, active_state, since):
        self.systemd_mock.AddObject(unit_path(target), SYSTEMD_UNIT, {
            "Id": target,
            "LoadState": "loaded",
            "ActiveState": active_state,
            "ActiveEnterTimestamp": dbus.UInt64(since),
        }, [])

    def set_target(self, target, active_state, since=0, announce=True):
        unit = self.system_bus.get_object("org.freedesktop.systemd1", unit_path(target))
        properties = dbus.Interface(unit, dbus.PROPERTIES_IFACE)
        properties.Set(SYSTEMD_UNIT, "ActiveState", active_state)
        properties.Set(SYSTEMD_UNIT, "ActiveEnterTimestamp", dbus.UInt64(since))
        if announce:
            self.systemd_mock.EmitSignal(SYSTEMD_MANAGER, "JobRemoved", "uoss", [
                dbus.UInt32(1), dbus.ObjectPath("/org/freedesktop/systemd1/job/1"), target, "done",
            ])

    def environment(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = CAPD_PYTHONPATH
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["OBSCURA_CAPD_VOCABULARY_DIR"] = VOCABULARY_DIR
        return env

    def start_capd(self):
        self.capd = subprocess.Popen(
            [sys.executable, "-P", "-m", "obscura_capd.daemon"],
            env=self.environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.addCleanup(self.stop_process, self.capd)
        try:
            wait_for(lambda: self.system_bus.name_has_owner(BUS_NAME), "capd owns " + BUS_NAME)
        except AssertionError as error:
            # Show why capd didn't come up (it may have crashed or be stuck).
            self.stop_process(self.capd)
            output = self.capd.stdout.read() if self.capd.stdout else ""
            raise AssertionError(str(error) + "; capd exit status " + str(self.capd.returncode)
                                 + "; capd output:\n" + (output or "(none)")) from None

    def start_watch(self):
        """obscura-cap watch in the background; its lines go to a queue."""
        process = subprocess.Popen(
            [sys.executable, "-P", "-m", "obscura_capd.cli", "watch"],
            env=self.environment(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self.addCleanup(self.stop_process, process)
        lines = queue.Queue()

        def pump():
            for line in process.stdout:
                lines.put(line.strip())

        threading.Thread(target=pump, daemon=True).start()
        self.watch_lines = lines

    def next_watch_line(self):
        return self.watch_lines.get(timeout=TIMEOUT)

    def manager(self):
        return dbus.Interface(self.system_bus.get_object(BUS_NAME, MANAGER_PATH), MANAGER_INTERFACE)

    def managed_paths(self):
        manager = dbus.Interface(self.system_bus.get_object(BUS_NAME, MANAGER_PATH),
                                 "org.freedesktop.DBus.ObjectManager")
        return sorted(str(path) for path in manager.GetManagedObjects())

    def cli_has(self, name):
        return subprocess.run(
            [sys.executable, "-P", "-m", "obscura_capd.cli", "has", name],
            env=self.environment(), capture_output=True, text=True, timeout=TIMEOUT,
        ).returncode



@unittest.skipIf(dbus is None, SKIP_REASON)
class CapdDBusTest(CapdHarness):
    def test_initial_state_and_queries(self):
        self.start_capd()
        manager = self.manager()
        self.assertEqual(list(manager.List()), ["battery"])
        self.assertEqual(list(manager.Vocabulary()), ["battery", "camera", "virt", "x86-64-v3"])
        self.assertTrue(manager.Has("battery"))
        self.assertFalse(manager.Has("camera"))
        self.assertEqual(self.managed_paths(), ["/org/obscura/Capabilities1/cap/battery"])

        battery = self.system_bus.get_object(BUS_NAME, "/org/obscura/Capabilities1/cap/battery")
        properties = dbus.Interface(battery, dbus.PROPERTIES_IFACE).GetAll(CAPABILITY_INTERFACE)
        self.assertEqual(properties["Kind"], "device")
        self.assertEqual(int(properties["Since"]), 1700000000000000)

    def test_unknown_name_is_an_error_absent_is_not(self):
        self.start_capd()
        with self.assertRaises(dbus.exceptions.DBusException) as caught:
            self.manager().Has("windows-apps")
        self.assertEqual(caught.exception.get_dbus_name(),
                         "org.obscura.Capabilities1.Error.UnknownCapability")
        self.assertEqual(self.cli_has("battery"), 0)
        self.assertEqual(self.cli_has("camera"), 1)
        self.assertEqual(self.cli_has("nonsense"), 2)

    def test_hotplug_signals_once_per_change(self):
        self.start_capd()
        self.start_watch()
        self.assertEqual(self.next_watch_line(), "+battery")
        for _ in range(10):
            self.set_target("obscura-cap-camera.target", "active", 1700000000000001)
            self.assertEqual(self.next_watch_line(), "+camera")
            self.assertIn("/org/obscura/Capabilities1/cap/camera", self.managed_paths())
            self.set_target("obscura-cap-camera.target", "inactive")
            self.assertEqual(self.next_watch_line(), "-camera")
            self.assertNotIn("/org/obscura/Capabilities1/cap/camera", self.managed_paths())
        # A JobRemoved with no state change produces no signal.
        self.set_target("obscura-cap-camera.target", "inactive")
        with self.assertRaises(queue.Empty):
            self.watch_lines.get(timeout=1.0)

    def test_jobs_on_other_units_are_ignored(self):
        self.start_capd()
        self.set_target("obscura-cap-virt.target", "active", 5, announce=False)
        self.systemd_mock.EmitSignal(SYSTEMD_MANAGER, "JobRemoved", "uoss", [
            dbus.UInt32(2), dbus.ObjectPath("/org/freedesktop/systemd1/job/2"), "sshd.service", "done",
        ])
        time.sleep(0.5)
        self.assertFalse(self.manager().Has("virt"))

    def test_daemon_reload_resyncs_everything(self):
        self.start_capd()
        self.set_target("obscura-cap-virt.target", "active", 5, announce=False)
        self.systemd_mock.EmitSignal(SYSTEMD_MANAGER, "Reloading", "b", [False])
        wait_for(lambda: self.manager().Has("virt"), "virt present after reload")

    def test_restart_rebuilds_state(self):
        self.start_capd()
        self.assertTrue(self.manager().Has("battery"))
        self.stop_process(self.capd)
        wait_for(lambda: not self.system_bus.name_has_owner(BUS_NAME), "capd gone")
        self.set_target("obscura-cap-battery.target", "inactive", announce=False)
        self.start_capd()
        self.assertEqual(list(self.manager().List()), [])
        self.assertEqual(self.managed_paths(), [])

    def test_unreadable_target_is_absent_and_daemon_survives(self):
        self.systemd_mock.RemoveObject(unit_path("obscura-cap-camera.target"))
        self.start_capd()
        self.assertFalse(self.manager().Has("camera"))
        self.assertTrue(self.manager().Has("battery"))
        self.assertIsNone(self.capd.poll(), "capd must keep running")

    def test_transport_error_keeps_previous_state(self):
        """A read failure on a present capability keeps it present (no Removed/Added flap)."""
        self.start_capd()
        self.start_watch()
        self.assertEqual(self.next_watch_line(), "+battery")
        self.systemd_mock.RemoveObject(unit_path("obscura-cap-battery.target"))
        self.systemd_mock.EmitSignal(SYSTEMD_MANAGER, "JobRemoved", "uoss", [
            dbus.UInt32(3), dbus.ObjectPath("/org/freedesktop/systemd1/job/3"),
            "obscura-cap-battery.target", "done",
        ])
        with self.assertRaises(queue.Empty):
            self.watch_lines.get(timeout=1.0)
        self.assertTrue(self.manager().Has("battery"))
        self.assertIsNone(self.capd.poll(), "capd must keep running")

    def test_hyphenated_name_gets_an_escaped_path(self):
        self.set_target("obscura-cap-x86-64-v3.target", "active", 9, announce=False)
        self.start_capd()
        self.assertTrue(self.manager().Has("x86-64-v3"))
        path = "/org/obscura/Capabilities1/cap/x86_2d64_2dv3"
        self.assertIn(path, self.managed_paths())
        properties = dbus.Interface(self.system_bus.get_object(BUS_NAME, path),
                                    dbus.PROPERTIES_IFACE).GetAll(CAPABILITY_INTERFACE)
        self.assertEqual(properties["Name"], "x86-64-v3")
        self.assertEqual(properties["Kind"], "static")

    def test_failed_target_is_absent(self):
        self.set_target("obscura-cap-camera.target", "failed", announce=False)
        self.start_capd()
        self.assertFalse(self.manager().Has("camera"))


if __name__ == "__main__":
    unittest.main()
