"""The udev rule evaluator (tests/lib/udev_rules.py), the udev database parser of
tests/lib/rule_crosscheck.py, and the v4l fixture recorder (tests/fixtures/v4l/capture.py).
Task 0.2c."""

import glob
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from tests import REPO_ROOT, UDEV_DIR


def load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


udev_rules = load("udev_rules_under_test", "tests", "lib", "udev_rules.py")
crosscheck = load("rule_crosscheck_under_test", "tests", "lib", "rule_crosscheck.py")
capture = load("v4l_capture_under_test", "tests", "fixtures", "v4l", "capture.py")


def event(env=None, parents=None, action="add", devpath="/devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/video4linux/video0",
          kernel="video0", subsystem="video4linux"):
    return {"action": action, "devpath": devpath, "kernel": kernel, "subsystem": subsystem,
            "env": dict(env or {}), "parents": parents if parents is not None else [
                {"kernel": "video0", "subsystem": "video4linux", "driver": None, "attrs": {"name": "Cam"}},
                {"kernel": "1-1:1.0", "subsystem": "usb", "driver": "uvcvideo", "attrs": {"bInterfaceClass": "0e"}},
                {"kernel": "1-1", "subsystem": "usb", "driver": "usb", "attrs": {"idVendor": "046d "}},
            ]}


def run(text, ev):
    return udev_rules.evaluate(udev_rules.parse(text), ev)


TAGGED = 'TAG+="systemd", ENV{SYSTEMD_WANTS}+="x.target"\n'


class MatchTest(unittest.TestCase):
    def test_glob_and_alternatives(self):
        for pattern, value, expected in (("*:capture:*", ":capture:", True), ("*:capture:*", ":video_output:", False),
                                         ("vivid|v4l2loopback", "v4l2loopback", True), ("vivid|v4l2loopback", "uvcvideo", False),
                                         ("video[0-9]", "video7", True), ("?*", "", False), ("", "", True)):
            with self.subTest(pattern=pattern, value=value):
                self.assertEqual(udev_rules.glob_matches(pattern, value), expected)

    def test_missing_property_matches_as_empty(self):
        rules = 'ENV{ID_V4L_CAPABILITIES}!="*:capture:*", GOTO="end"\n' + TAGGED + 'LABEL="end"\n'
        self.assertNotIn("systemd", run(rules, event())["tags"])
        self.assertIn("systemd", run(rules, event({"ID_V4L_CAPABILITIES": ":capture:"}))["tags"])

    def test_goto_skips_to_label(self):
        rules = 'ACTION=="remove", GOTO="end"\n' + TAGGED + 'LABEL="end"\nTAG+="after"\n'
        self.assertEqual(run(rules, event(action="remove"))["tags"], {"after"})
        self.assertEqual(run(rules, event(action="change"))["tags"], {"systemd", "after"})

    def test_env_append_and_wants(self):
        rules = 'ENV{SYSTEMD_WANTS}+="a.target"\n' + TAGGED
        result = run(rules, event())
        self.assertEqual(result["env"]["SYSTEMD_WANTS"], "a.target x.target")
        self.assertTrue(udev_rules.wants(result, "x.target"))
        self.assertFalse(udev_rules.wants(run('ENV{SYSTEMD_WANTS}+="x.target"\n', event()), "x.target"),
                         "without the systemd tag PID 1 ignores SYSTEMD_WANTS")

    def test_devpath(self):
        rules = 'DEVPATH=="/devices/virtual/*", GOTO="end"\n' + TAGGED + 'LABEL="end"\n'
        self.assertFalse(udev_rules.wants(run(rules, event(devpath="/devices/virtual/video4linux/video0")), "x.target"))
        self.assertTrue(udev_rules.wants(run(rules, event()), "x.target"))

    def test_continuation_and_comments(self):
        rules = '# comment\n\nSUBSYSTEM=="video4linux", \\\n  TAG+="systemd"\n'
        self.assertEqual(run(rules, event())["tags"], {"systemd"})


class ParentKeyTest(unittest.TestCase):
    """udev(7): parent keys on one line must all match the same device in the chain."""

    def test_device_itself_is_the_first_candidate(self):
        self.assertTrue(run('KERNELS=="video0", TAG+="t"\n', event())["tags"])

    def test_any_ancestor_can_match_one_key(self):
        self.assertTrue(run('DRIVERS=="uvcvideo", TAG+="t"\n', event())["tags"])
        self.assertFalse(run('DRIVERS=="vivid", TAG+="t"\n', event())["tags"])

    def test_keys_satisfied_by_different_ancestors_do_not_match(self):
        # uvcvideo is on 1-1:1.0, idVendor on 1-1: no single device has both.
        self.assertFalse(run('DRIVERS=="uvcvideo", ATTRS{idVendor}=="046d", TAG+="t"\n', event())["tags"])
        self.assertTrue(run('DRIVERS=="usb", ATTRS{idVendor}=="046d", TAG+="t"\n', event())["tags"])
        self.assertTrue(run('DRIVERS=="uvcvideo", SUBSYSTEMS=="usb", ATTRS{bInterfaceClass}=="0e", TAG+="t"\n',
                            event())["tags"])
        self.assertFalse(run('KERNELS=="video0", SUBSYSTEMS=="usb", TAG+="t"\n', event())["tags"])

    def test_attrs_trailing_whitespace_is_ignored(self):
        self.assertTrue(run('ATTRS{idVendor}=="046d", TAG+="t"\n', event())["tags"])

    def test_missing_attribute_never_matches_even_negated(self):
        self.assertFalse(run('ATTRS{nothing}!="x", TAG+="t"\n', event(parents=[
            {"kernel": "video0", "subsystem": "video4linux", "driver": None, "attrs": {}}]))["tags"])

    def test_negated_parent_key_needs_one_device_that_differs(self):
        # Every device in a chain without drivers has driver "", which isn't "vivid".
        self.assertTrue(run('DRIVERS!="vivid", TAG+="t"\n', event())["tags"])
        only_vivid = [{"kernel": "vivid.0", "subsystem": "platform", "driver": "vivid", "attrs": {}}]
        self.assertFalse(run('DRIVERS!="vivid", TAG+="t"\n', event(parents=only_vivid))["tags"])

    def test_attr_reads_the_device_itself(self):
        self.assertTrue(run('ATTR{name}=="Cam", TAG+="t"\n', event())["tags"])
        self.assertFalse(run('ATTR{idVendor}=="046d", TAG+="t"\n', event())["tags"], "ATTR doesn't search parents")
        self.assertFalse(run('ATTR{idVendor}!="x", TAG+="t"\n', event())["tags"], "missing: never matches")

    def test_no_parents_means_no_match(self):
        self.assertFalse(run('DRIVERS=="?*", TAG+="t"\n', event(parents=[]))["tags"])


class UnsupportedSyntaxTest(unittest.TestCase):
    def test_unknown_syntax_raises(self):
        for line in ('SYMLINK+="x"', 'TAG:="t"', 'ENV{A}-="b"', 'RUN+="/bin/true"',
                     'IMPORT{program}="v4l_id $devnode"', 'TAG="t"', 'GOTO+="x"', 'ENV=="x"',
                     'SUBSYSTEM=="a" TAG+="t"', 'GOTO="nowhere"', 'LABEL="a", TAG+="t"'):
            with self.subTest(line):
                with self.assertRaises(udev_rules.UnsupportedRule):
                    udev_rules.parse(line + "\n")

    def test_capability_rules_use_only_supported_syntax(self):
        paths = glob.glob(os.path.join(UDEV_DIR, "70-obscura-cap-*.rules"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(os.path.basename(path)):
                with open(path, "r", encoding="utf-8") as handle:
                    self.assertTrue(udev_rules.parse(handle.read()))


class RecordToEventTest(unittest.TestCase):
    def test_fresh_v4l_id_output_overrides_the_database(self):
        record = {"action": "change", "devpath": "/devices/virtual/video4linux/video0", "kernel": "video0",
                  "subsystem": "video4linux", "properties": {"ID_V4L_CAPABILITIES": ":video_output:"},
                  "fresh": {"ID_V4L_CAPABILITIES": ":capture:"}, "parents": []}
        ev = udev_rules.event_from_record(record)
        self.assertEqual(ev["env"]["ID_V4L_CAPABILITIES"], ":capture:")
        self.assertEqual(ev["action"], "change")
        self.assertEqual(udev_rules.event_from_record(record, "add")["action"], "add")


# udevadm info --query=property for the OBS loopback after a forced change event while
# ffmpeg streamed, 0.2b rule (VM recon of 2026-11-24, systemd 262), trimmed.
INFO_STREAMING_0_2B = """DEVPATH=/devices/virtual/video4linux/video0
DEVNAME=/dev/video0
SUBSYSTEM=video4linux
ID_V4L_CAPABILITIES=:capture:
SYSTEMD_WANTS=obscura-cap-camera.target
TAGS=:systemd:seat:uaccess:
CURRENT_TAGS=:systemd:uaccess:seat:
"""

# The same node after the next event with the rule no longer matching: TAGS keeps systemd.
INFO_STALE_TAGS = """DEVPATH=/devices/virtual/video4linux/video0
ID_V4L_CAPABILITIES=:video_output:
TAGS=:systemd:seat:uaccess:
CURRENT_TAGS=:uaccess:seat:
"""


class DatabaseParserTest(unittest.TestCase):
    """rule_crosscheck.py reads real udev's verdict from the database after an event."""

    def test_tagged_and_wanted(self):
        properties, tags = crosscheck.parse_db(INFO_STREAMING_0_2B)
        self.assertEqual(tags, {"systemd", "uaccess", "seat"})
        self.assertTrue(crosscheck.wanted(properties, tags, "obscura-cap-camera.target"))

    def test_sticky_tags_do_not_count(self):
        properties, tags = crosscheck.parse_db(INFO_STALE_TAGS)
        self.assertNotIn("systemd", tags)
        self.assertFalse(crosscheck.wanted(properties, tags, "obscura-cap-camera.target"))

    def test_wants_without_the_tag_does_not_count(self):
        text = "DEVPATH=/x\nSYSTEMD_WANTS=obscura-cap-camera.target\nCURRENT_TAGS=:seat:\n"
        properties, tags = crosscheck.parse_db(text)
        self.assertFalse(crosscheck.wanted(properties, tags, "obscura-cap-camera.target"))

    def test_no_devpath_is_unknown(self):
        self.assertEqual(crosscheck.parse_db("Unknown device\n"), (None, None))


class CaptureTest(unittest.TestCase):
    """capture.py against a fake sysfs tree; udevadm and v4l_id are mocked."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="obscura-sysfs-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))

    def make_device(self, relative, subsystem=None, driver=None, attrs=None):
        path = os.path.join(self.root, relative)
        os.makedirs(path, exist_ok=True)
        open(os.path.join(path, "uevent"), "w").close()
        for name, value in (attrs or {}).items():
            with open(os.path.join(path, name), "w") as handle:
                handle.write(value + "\n")
        for link, target in (("subsystem", subsystem and "class/" + subsystem), ("driver", driver and "drivers/" + driver)):
            if target:
                os.makedirs(os.path.join(self.root, target), exist_ok=True)
                os.symlink(os.path.join(self.root, target), os.path.join(path, link))
        return path

    def fake_run(self, command):
        if command[0] == "udevadm":
            return ("DEVPATH=/x\nID_V4L_CAPABILITIES=:capture:\nID_SERIAL=046d_HD_Pro_Webcam_C920_ABC123\n"
                    "ID_SERIAL_SHORT=ABC123\nID_VENDOR_ID=046d\nCURRENT_TAGS=:systemd:\n")
        return "ID_V4L_VERSION=2\nID_V4L_PRODUCT=HD Pro Webcam C920\nID_V4L_CAPABILITIES=:capture:\n"

    def record(self):
        try:
            os.symlink(self.root, os.path.join(self.root, "probe-link"))
        except (OSError, NotImplementedError):
            self.skipTest("needs symlinks (on Windows: Developer Mode)")
        self.make_device("devices/pci0000:00/0000:00:14.0/usb1/1-1", "usb", "usb",
                         {"idVendor": "046d", "serial": "ABC123", "product": "HD Pro Webcam C920"})
        self.make_device("devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0", "usb", "uvcvideo",
                         {"bInterfaceClass": "0e"})
        os.makedirs(os.path.join(self.root, "devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/video4linux"))
        node = self.make_device("devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/video4linux/video1",
                                "video4linux", None, {"name": "HD Pro Webcam C920"})
        os.makedirs(os.path.join(self.root, "class", "video4linux"), exist_ok=True)
        os.symlink(node, os.path.join(self.root, "class", "video4linux", "video1"))
        with mock.patch.object(capture, "run", side_effect=self.fake_run), \
                mock.patch.object(capture.os.path, "exists", side_effect=lambda p: True if p == capture.V4L_ID
                                  else os.path.lexists(p)):
            return capture.record_node("/dev/video1", sysfs_root=self.root)

    def test_record_keeps_only_allowlisted_keys(self):
        record = self.record()
        text = json.dumps(record)
        self.assertNotIn("ABC123", text)
        self.assertNotIn("SERIAL", text.upper())
        self.assertEqual(record["properties"]["ID_VENDOR_ID"], "046d")
        self.assertNotIn("CURRENT_TAGS", record["properties"])

    def test_parent_chain_follows_udev(self):
        record = self.record()
        self.assertEqual(record["devpath"], "/devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/video4linux/video1")
        # The video4linux directory has no uevent file, so it isn't a device.
        self.assertEqual([p["kernel"] for p in record["parents"]], ["video1", "1-1:1.0", "1-1"])
        self.assertEqual([p["driver"] for p in record["parents"]], [None, "uvcvideo", "usb"])
        self.assertEqual(record["parents"][0]["subsystem"], "video4linux")
        self.assertEqual(record["fresh"]["ID_V4L_CAPABILITIES"], ":capture:")

    def test_identifying_keys_are_refused(self):
        with self.assertRaises(capture.CaptureError):
            capture.check_clean({"parents": [{"attrs": {"serial": "x"}}]})

    def test_refuses_to_write_in_a_checkout(self):
        with self.assertRaises(capture.CaptureError):
            capture.capture(os.path.join(REPO_ROOT, "tests", "out"), "x", "add", ["/dev/video0"])
        with self.assertRaises(capture.CaptureError):
            capture.capture(tempfile.gettempdir(), "synthetic-x", "add", ["/dev/video0"])


if __name__ == "__main__":
    unittest.main()
