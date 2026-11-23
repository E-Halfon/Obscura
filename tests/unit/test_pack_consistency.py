"""Lint: every pack shipped in the image validates, uses only PACKS.md §2 capabilities,
matches its PACKS.md catalog row, and contains nothing the repo guard protects (§14.2)."""

import importlib.util
import os
import re
import unittest
from unittest import mock

from tests import FACTORY_PACKS_DIR, REPO_ROOT, SIGNATURES_FILE, VOCABULARY_DIR
from tests.unit.test_repo_consistency import packs_vocabulary, read
from obscura_capd import report
from obscura_packs.catalog import load_catalog
from obscura_capd.vocabulary import load_vocabulary
from obscura_packs.constants import INSUFFICIENT_HARDWARE, READY
from obscura_packs.manifest import load_signatures
from obscura_packs.readiness import evaluate

# PACKS.md section heading -> manifest platform.
SECTION_PLATFORMS = {
    "Windows": "windows",
    "macOS": "macos",
    "Android": "android",
    "Linux (non-native)": "linux-foreign",
    "Sony": "sony",
    "Nintendo": "nintendo",
    "Microsoft Xbox": "xbox",
    "Sega, arcade, and retro computers": "retro",
    "VR": "vr",
    "Infrastructure packs": "system",
    "Other runtimes": None,  # several platforms; the platform isn't checked
}


def catalog_rows():
    """{pack name: (platform or None, is_runtime)} from the PACKS.md platform tables."""
    text = read(os.path.join(REPO_ROOT, "docs", "PACKS.md"))
    rows = {}
    for section in re.split(r"\n## \d+\. ", text)[1:]:
        heading, _, body = section.partition("\n")
        # Only the per-platform catalog tables; §1's summary tables don't mark runtimes.
        if heading.strip() not in SECTION_PLATFORMS:
            continue
        for line in body.splitlines():
            match = re.match(r"^\|\s*`(pack-[a-z0-9-]+)`\s*(\*\(runtime\)\*)?\s*\|", line)
            if match:
                rows.setdefault(match.group(1), (SECTION_PLATFORMS[heading.strip()], bool(match.group(2))))
    return rows


def load_guard():
    path = os.path.join(REPO_ROOT, ".claude", "hooks", "guard_protected_files.py")
    spec = importlib.util.spec_from_file_location("guard_protected_files", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(report, "_send"):
            cls.signatures = load_signatures(SIGNATURES_FILE)
            cls.catalog = load_catalog(cls.signatures, FACTORY_PACKS_DIR, os.path.join(REPO_ROOT, "no-installed-root"))
        cls.rows = catalog_rows()

    def test_pack_wine_ships(self):
        pack = self.catalog.get("pack-wine")
        self.assertIsNotNone(pack)
        self.assertTrue(pack.manifest.runtime)

    def test_every_factory_manifest_validates(self):
        self.assertEqual(self.catalog.problems, [])
        directories = sorted(entry for entry in os.listdir(FACTORY_PACKS_DIR)
                             if os.path.isdir(os.path.join(FACTORY_PACKS_DIR, entry)))
        self.assertEqual(directories, self.catalog.names())

    def test_capabilities_come_from_packs_md(self):
        documented = packs_vocabulary()
        self.assertIn("vulkan-1.3", documented)
        for name in self.catalog.names():
            manifest = self.catalog.get(name).manifest
            for capability in manifest.requires + manifest.recommends:
                with self.subTest(pack=name, capability=capability):
                    self.assertIn(capability, documented, capability + " is not in PACKS.md §2")

    def test_every_pack_has_a_matching_catalog_row(self):
        self.assertIn("pack-wine", self.rows)
        for name in self.catalog.names():
            manifest = self.catalog.get(name).manifest
            with self.subTest(name):
                self.assertIn(name, self.rows, name + " has no row in PACKS.md")
                platform, runtime = self.rows[name]
                if platform is not None:
                    self.assertEqual(manifest.platform, platform)
                self.assertEqual(manifest.runtime, runtime, "runtime flag differs from PACKS.md *(runtime)*")

    def test_nothing_protected_in_pack_directories(self):
        guard = load_guard()
        for directory, _, files in os.walk(FACTORY_PACKS_DIR):
            for file_name in files:
                path = os.path.relpath(os.path.join(directory, file_name), REPO_ROOT)
                with self.subTest(path):
                    self.assertIsNone(guard.protection_reason(path))

    def test_pack_wine_readiness_follows_the_vocabulary(self):
        """Before task 0.2b, capd doesn't declare x86-64-v3 or vulkan-1.3, so pack-wine says
        Obscura can't detect them yet. Once 0.2b declares them, it's Ready when they're present."""
        with mock.patch.object(report, "_send"):
            vocabulary = load_vocabulary(VOCABULARY_DIR)
        manifest = self.catalog.get("pack-wine").manifest
        result = evaluate(manifest, frozenset(vocabulary), vocabulary)
        unknown = [name for name in manifest.requires if name not in vocabulary]
        if unknown:
            self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
            self.assertEqual({reason.subject for reason in result.reasons if reason.code == "capability-unknown"},
                             set(unknown))
        else:
            self.assertEqual(result.state, READY)

    def test_signatures_registry_is_valid(self):
        self.assertIn("mz", self.signatures)


if __name__ == "__main__":
    unittest.main()
