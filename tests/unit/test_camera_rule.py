"""The camera capability rule (70-obscura-cap-camera.rules) against the v4l fixtures, task
0.2c: only capture nodes of physical devices count (ARCHITECTURE.md §4, §11).

The rule is run through tests/lib/udev_rules.py. Its agreement with real udev is checked in
the VM (tests/lib/rule_crosscheck.py, C-15 to C-17); here the scenarios, a mutation test
that each exclusion line is load-bearing, and lints."""

import importlib.util
import json
import os
import re
import unittest

from tests import REPO_ROOT, UDEV_DIR

RULE = os.path.join(UDEV_DIR, "70-obscura-cap-camera.rules")
UNIT = "obscura-cap-camera.target"
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "v4l")
README = os.path.join(FIXTURE_DIR, "README.md")
CAPABILITIES_SH = os.path.join(REPO_ROOT, "tests", "vm", "capabilities.sh")
FILE_PATTERN = re.compile(r"^(?P<origin>real|synthetic)-.+-(?P<kernel>[a-z-]+\d+)\.json$")
STREAMING_LOOPBACK = "real-loopback-streaming-video0.json"


def load_module(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


udev_rules = load_module("udev_rules_for_camera", "tests", "lib", "udev_rules.py")


def rule_text():
    with open(RULE, "r", encoding="utf-8") as handle:
        return handle.read()


def fixture_files():
    return sorted(name for name in os.listdir(FIXTURE_DIR) if name.endswith(".json"))


def readme_rows():
    """{file name: origin} from the README's Files table."""
    with open(README, "r", encoding="utf-8") as handle:
        text = handle.read()
    rows = {}
    for line in text.split("## Files", 1)[1].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells[1]
    return rows


def is_real(name):
    return name.startswith("real-") and "synthetic" not in name and readme_rows().get(name) == "real"


def record(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def counts(name, text=None, action=None, use_database=False):
    """Does the rule (or `text`) make PID 1 pull in the camera target for this recording?
    use_database evaluates the recorded udev database instead of the fresh v4l_id output."""
    document = record(name)
    if use_database:
        document = dict(document, fresh={})
    event = udev_rules.event_from_record(document, action)
    return udev_rules.wants(udev_rules.evaluate(udev_rules.parse(text or rule_text()), event), UNIT)


# file: (counts?, why). Every fixture must be listed here.
SCENARIOS = {
    "real-c920-video1.json": (True, "C920 capture node"),
    "real-c920-video2.json": (False, "C920 metadata node"),
    "real-vm-idle-video0.json": (False, "OBS loopback idle"),
    STREAMING_LOOPBACK: (False, "OBS loopback streaming"),
    "real-c920-video0.json": (False, "OBS loopback, stale database"),
    "real-vivid-video1.json": (False, "vivid capture node"),
    "real-vivid-video2.json": (False, "vivid output node"),
    "real-vivid-video3.json": (False, "vivid metadata capture node"),
    "real-vivid-video4.json": (False, "vivid metadata output node"),
    "synthetic-loopback-nocaps-video0.json": (False, "v4l2loopback, exclusive_caps=0"),
    "synthetic-loopback-parent-video0.json": (False, "v4l2loopback with a platform parent"),
    "synthetic-ipu6-video0.json": (True, "IPU6 CSI node"),
    "synthetic-ir-only-video0.json": (True, "IR-only sensor (counted for now, §11)"),
}


class StreamingLoopbackNegativeTest(unittest.TestCase):
    """The key negative test: OBS's v4l2loopback reports :capture: while ffmpeg streams into
    it, and the 0.2b rule counted it (VM recon of 2026-11-24). It uses the real recording
    only, never a synthetic stand-in."""

    def test_real_streaming_loopback_never_counts(self):
        if STREAMING_LOOPBACK not in fixture_files():
            self.fail("no " + STREAMING_LOOPBACK + " yet: record it in the VM while ffmpeg streams into the "
                      "loopback (tests/fixtures/v4l/README.md) and commit it with a README row marked real")
        self.assertTrue(is_real(STREAMING_LOOPBACK), "README must mark it real")
        document = record(STREAMING_LOOPBACK)
        # The test means something only if the loopback really claimed capture.
        self.assertIn(":capture:", document["fresh"]["ID_V4L_CAPABILITIES"])
        self.assertTrue(document["devpath"].startswith("/devices/virtual/"))
        for action in ("change", "add"):
            with self.subTest(action=action):
                self.assertFalse(counts(STREAMING_LOOPBACK, action=action))

    def test_the_old_rule_counted_it(self):
        """Guards the test itself: the 0.2b rule (without the exclusions) tags this record,
        as real udev did in the VM."""
        old = "\n".join(line for line in rule_text().splitlines()
                        if not line.startswith(("DEVPATH==", "DRIVERS==")))
        self.assertTrue(counts(STREAMING_LOOPBACK, text=old))


class ScenarioTest(unittest.TestCase):
    def test_every_fixture_has_a_scenario(self):
        self.assertEqual(sorted(SCENARIOS), fixture_files())

    def test_scenarios(self):
        for name, (expected, why) in SCENARIOS.items():
            for action in ("add", "change"):
                with self.subTest(name=name, action=action, why=why):
                    self.assertEqual(counts(name, action=action), expected)

    def test_remove_never_counts(self):
        self.assertFalse(counts("real-c920-video1.json", action="remove"))

    def test_stale_database_does_not_count_either(self):
        """An event sees v4l_id's fresh output; but if no event comes (v4l2loopback 0.15.4
        sent none when streaming stopped), the database value is what stays. Neither counts."""
        document = record("real-c920-video0.json")
        self.assertEqual(document["properties"]["ID_V4L_CAPABILITIES"], ":capture:")
        self.assertEqual(document["fresh"]["ID_V4L_CAPABILITIES"], ":video_output:")
        self.assertFalse(counts("real-c920-video0.json"))
        self.assertFalse(counts("real-c920-video0.json", use_database=True))

    def test_vivid_is_not_virtual(self):
        """vivid sits under /devices/platform: only the DRIVERS line keeps it out."""
        self.assertTrue(record("real-vivid-video1.json")["devpath"].startswith("/devices/platform/"))


class MutationTest(unittest.TestCase):
    """Deleting any one exclusion line makes the scenario it guards count."""

    GUARDS = {
        'ACTION=="remove"': [("real-c920-video1.json", "remove")],
        'SUBSYSTEM!="video4linux"': [],  # checked below with a non-video4linux event
        'ENV{ID_V4L_CAPABILITIES}!=': [("real-c920-video2.json", "add")],
        'DEVPATH=="/devices/virtual/*"': [(STREAMING_LOOPBACK, "change"), ("synthetic-loopback-nocaps-video0.json", "add")],
        'DRIVERS==': [("real-vivid-video1.json", "add"), ("synthetic-loopback-parent-video0.json", "change")],
    }

    def without(self, prefix):
        lines = rule_text().splitlines()
        kept = [line for line in lines if not line.startswith(prefix)]
        self.assertEqual(len(kept), len(lines) - 1, "exactly one line starts with " + prefix)
        return "\n".join(kept) + "\n"

    def test_each_exclusion_is_load_bearing(self):
        for prefix, guarded in self.GUARDS.items():
            mutated = self.without(prefix)
            for name, action in guarded:
                with self.subTest(removed=prefix, scenario=name):
                    self.assertFalse(counts(name, action=action))
                    self.assertTrue(counts(name, text=mutated, action=action))

    def test_subsystem_line(self):
        event = udev_rules.event_from_record(record("real-c920-video1.json"))
        event = dict(event, subsystem="usb")
        rules = udev_rules.parse(rule_text())
        mutated = udev_rules.parse(self.without('SUBSYSTEM!="video4linux"'))
        self.assertFalse(udev_rules.wants(udev_rules.evaluate(rules, event), UNIT))
        self.assertTrue(udev_rules.wants(udev_rules.evaluate(mutated, event), UNIT))


class LintTest(unittest.TestCase):
    def tokens(self):
        return [(rule.number, token) for rule in udev_rules.parse(rule_text()) for token in rule.matches]

    def test_runs_on_change_too(self):
        """Only ACTION=="remove" may appear: restricting to add would miss a node whose
        capabilities change (a streaming loopback, or a real node after a driver rebind)."""
        actions = [(op, value) for _, (key, _, op, value) in self.tokens() if key == "ACTION"]
        self.assertEqual(actions, [("==", "remove")])

    def test_exclusions_come_before_the_tag(self):
        rules = udev_rules.parse(rule_text())
        tag_line = next(r.number for r in rules if any(k == "TAG" for k, _, _, _ in r.actions))
        for key in ("DEVPATH", "DRIVERS"):
            with self.subTest(key=key):
                lines = [r.number for r in rules if any(t[0] == key for t in r.matches + r.parent_matches)]
                self.assertTrue(lines, key + " exclusion missing")
                self.assertTrue(all(number < tag_line for number in lines))

    def test_driver_list_matches_the_vm_ground_truth(self):
        rules = udev_rules.parse(rule_text())
        drivers = [t[3] for r in rules for t in r.parent_matches if t[0] == "DRIVERS"]
        self.assertEqual(len(drivers), 1)
        with open(CAPABILITIES_SH, "r", encoding="utf-8") as handle:
            found = re.search(r'^readonly VIRTUAL_V4L_DRIVERS="([^"]*)"', handle.read(), re.MULTILINE)
        self.assertIsNotNone(found, "VIRTUAL_V4L_DRIVERS missing from capabilities.sh")
        self.assertEqual(sorted(drivers[0].split("|")), sorted(found.group(1).split()))


class FixtureReadmeTest(unittest.TestCase):
    def test_every_file_has_a_matching_row(self):
        rows = readme_rows()
        for name in fixture_files():
            with self.subTest(name=name):
                match = FILE_PATTERN.match(name)
                self.assertIsNotNone(match, "name must be <origin>-<label>-<kernel>.json")
                self.assertEqual(rows.get(name), match.group("origin"))
        self.assertEqual(sorted(rows), fixture_files(), "README lists a file that doesn't exist")

    def test_no_identifying_keys(self):
        for name in fixture_files():
            with self.subTest(name=name):
                with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as handle:
                    text = handle.read()
                self.assertIsNone(re.search(r"serial|uuid", text, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
