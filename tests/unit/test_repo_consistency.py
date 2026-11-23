"""Lint: every declared capability has a well-formed target and udev rule, nothing else
claims to be a capability, and the vocabulary matches PACKS.md §2."""

import glob
import os
import re
import unittest
from unittest import mock

from tests import REPO_ROOT, UDEV_DIR, UNIT_DIR, VOCABULARY_DIR
from obscura_capd import report
from obscura_capd.vocabulary import load_vocabulary


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def packs_vocabulary():
    """{name: kind} from the PACKS.md §2 table."""
    text = read(os.path.join(REPO_ROOT, "docs", "PACKS.md"))
    section = text.split("## 2. Capability vocabulary", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`"):
            for name in re.findall(r"`([^`]+)`", cells[0]):
                rows[name] = cells[1]
    return rows


STATIC_DROP_IN = os.path.join(UNIT_DIR, "sysinit.target.d", "50-obscura-static-capabilities.conf")
CAPD_SERVICE = os.path.join(UNIT_DIR, "obscura-capd.service")
TARGET_PATTERN = re.compile(r"(obscura-cap-[a-z0-9.-]+\.target)")

# x86-64 psABI levels v2 and v3, in systemd's ConditionCPUFeature= spelling (src/basic/virt.c,
# checked at systemd v262). Hard-coded here, independently of the unit file, so neither
# side can drift: FMA is fma3, LZCNT is abm, SSE3 is pni.
X86_64_V3_FEATURES = frozenset({
    "cx16", "lahf_lm", "popcnt", "pni", "sse4_1", "sse4_2", "ssse3",              # v2
    "avx", "avx2", "bmi1", "bmi2", "f16c", "fma3", "abm", "movbe", "xsave", "osxsave",  # v3
})


def directive_values(text, directive):
    """Every value of `directive=` in a unit file, split on whitespace."""
    values = []
    for match in re.finditer(r"^\s*" + directive + r"\s*=\s*(.*)$", text, re.MULTILINE):
        values.extend(match.group(1).split())
    return values


def packs_attachable():
    """{name: True/False} from the Attachable column of the PACKS.md §2 table."""
    text = read(os.path.join(REPO_ROOT, "docs", "PACKS.md"))
    section = text.split("## 2. Capability vocabulary", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith("`"):
            for name in re.findall(r"`([^`]+)`", cells[0]):
                rows[name] = {"yes": True, "no": False}.get(cells[2])
    return rows


class ConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(report, "_send"):
            cls.vocabulary = load_vocabulary(VOCABULARY_DIR)

    def test_every_declaration_has_a_target(self):
        for name, declaration in self.vocabulary.items():
            with self.subTest(name):
                path = os.path.join(UNIT_DIR, declaration.target)
                self.assertTrue(os.path.exists(path), "missing " + declaration.target)
                text = read(path)
                for directive in ("StopWhenUnneeded=yes", "RefuseManualStart=yes", "RefuseManualStop=yes"):
                    self.assertIn(directive, text)
                # Capabilities are started by detection only, never by being enabled.
                self.assertNotIn("[Install]", text)

    def test_every_target_has_a_declaration(self):
        targets = {os.path.basename(path) for path in glob.glob(os.path.join(UNIT_DIR, "obscura-cap-*.target"))}
        self.assertEqual(targets, {declaration.target for declaration in self.vocabulary.values()})

    def test_device_capabilities_have_udev_rules(self):
        for name, declaration in self.vocabulary.items():
            if declaration.kind != "device":
                continue
            with self.subTest(name):
                path = os.path.join(UDEV_DIR, "70-obscura-cap-" + name + ".rules")
                self.assertTrue(os.path.exists(path), "missing " + path)
                text = read(path)
                self.assertIn('ENV{SYSTEMD_WANTS}+="' + declaration.target + '"', text)
                self.assertIn('TAG+="systemd"', text)
                self.assertRegex(text, r'ACTION=="remove", GOTO="obscura_cap_[a-z0-9_]+_end"')

    def test_udev_rules_only_want_declared_targets(self):
        declared = {declaration.target for declaration in self.vocabulary.values()}
        for path in glob.glob(os.path.join(UDEV_DIR, "*.rules")):
            for target in TARGET_PATTERN.findall(read(path)):
                with self.subTest(path=path, target=target):
                    self.assertIn(target, declared)

    def test_no_unit_pulls_in_a_capability(self):
        """Services attach with PartOf=/WantedBy=; Requires=/Wants=/BindsTo= on a capability
        target would start it and fake a "present". Two exceptions, each checked by its own
        test: the static-capability drop-in (Wants=, static targets only) and a device
        capability's probe template (Upholds= its own target only)."""
        pattern = re.compile(r"^\s*(Requires|Requisite|Wants|BindsTo|Upholds)\s*=.*obscura-cap-", re.MULTILINE)
        exceptions = {os.path.normpath(STATIC_DROP_IN)}
        exceptions.update(os.path.normpath(path) for path in glob.glob(os.path.join(UNIT_DIR, "obscura-cap-*-probe@.service")))
        for path in glob.glob(os.path.join(REPO_ROOT, "files", "**", "*.*"), recursive=True):
            if not path.endswith((".service", ".target", ".socket", ".path", ".timer", ".conf", ".mount")):
                continue
            if os.path.normpath(path) in exceptions:
                continue
            with self.subTest(path):
                self.assertIsNone(pattern.search(read(path)))

    def test_static_drop_in_wants_exactly_the_static_targets(self):
        text = read(STATIC_DROP_IN)
        static = {d.target for d in self.vocabulary.values() if d.kind == "static"}
        self.assertEqual(set(directive_values(text, "Wants")), static)
        for directive in ("Requires", "Requisite", "BindsTo", "Upholds"):
            self.assertEqual(directive_values(text, directive), [], directive)

    def test_static_targets_are_ordered_before_sysinit(self):
        for name, declaration in self.vocabulary.items():
            if declaration.kind != "static":
                continue
            with self.subTest(name):
                text = read(os.path.join(UNIT_DIR, declaration.target))
                self.assertIn("sysinit.target", directive_values(text, "Before"))
                self.assertEqual(directive_values(text, "DefaultDependencies"), ["no"])
                self.assertIn("shutdown.target", directive_values(text, "Conflicts"))
                self.assertFalse(os.path.exists(os.path.join(UDEV_DIR, "70-obscura-cap-" + name + ".rules")),
                                 "a static capability has no udev rule")

    def test_capd_is_ordered_after_every_static_target(self):
        after = set(directive_values(read(CAPD_SERVICE), "After"))
        for name, declaration in self.vocabulary.items():
            if declaration.kind == "static":
                with self.subTest(name):
                    self.assertIn(declaration.target, after)

    def test_x86_64_v3_conditions_are_exactly_the_psabi_levels(self):
        text = read(os.path.join(UNIT_DIR, "obscura-cap-x86-64-v3.target"))
        features = directive_values(text, "ConditionCPUFeature")
        self.assertEqual(len(features), len(set(features)), "duplicate condition")
        self.assertEqual(set(features), X86_64_V3_FEATURES)
        # Conditions ANDed with the "|" (OR) prefix would weaken the check.
        self.assertNotIn("|", "".join(features))

    def test_vocabulary_matches_packs_md(self):
        documented = packs_vocabulary()
        self.assertIn("ram-32g", documented)
        for name, declaration in self.vocabulary.items():
            with self.subTest(name):
                self.assertIn(name, documented, name + " is declared but not in PACKS.md §2")
                self.assertEqual(documented[name], declaration.kind)

    def test_attachable_matches_packs_md(self):
        documented = packs_attachable()
        self.assertTrue(all(value is not None for value in documented.values()), documented)
        for name, declaration in self.vocabulary.items():
            with self.subTest(name):
                self.assertEqual(documented[name], declaration.attachable)

    def test_no_pack_capabilities_in_vocabulary(self):
        documented = packs_vocabulary()
        for name in ("windows-apps", "android-apps"):
            self.assertNotIn(name, documented)
            self.assertNotIn(name, self.vocabulary)


if __name__ == "__main__":
    unittest.main()
