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
            for target in re.findall(r"(obscura-cap-[a-z0-9-]+\.target)", read(path)):
                with self.subTest(path=path, target=target):
                    self.assertIn(target, declared)

    def test_no_unit_pulls_in_a_capability(self):
        """Services attach with PartOf=/WantedBy=; Requires=/Wants=/BindsTo= on a capability
        target would start it and fake a "present"."""
        pattern = re.compile(r"^\s*(Requires|Requisite|Wants|BindsTo|Upholds)\s*=.*obscura-cap-", re.MULTILINE)
        for path in glob.glob(os.path.join(REPO_ROOT, "files", "**", "*.*"), recursive=True):
            if not path.endswith((".service", ".target", ".socket", ".path", ".timer", ".conf", ".mount")):
                continue
            with self.subTest(path):
                self.assertIsNone(pattern.search(read(path)))

    def test_vocabulary_matches_packs_md(self):
        documented = packs_vocabulary()
        self.assertIn("ram-32g", documented)
        for name, declaration in self.vocabulary.items():
            with self.subTest(name):
                self.assertIn(name, documented, name + " is declared but not in PACKS.md §2")
                self.assertEqual(documented[name], declaration.kind)

    def test_no_pack_capabilities_in_vocabulary(self):
        documented = packs_vocabulary()
        for name in ("windows-apps", "android-apps"):
            self.assertNotIn(name, documented)
            self.assertNotIn(name, self.vocabulary)


if __name__ == "__main__":
    unittest.main()
