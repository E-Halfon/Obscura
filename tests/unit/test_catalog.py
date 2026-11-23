"""The installed-pack catalog: factory vs installed roots, removal, and cross-pack rules."""

import os
import tempfile
import unittest
from unittest import mock

from obscura_capd import report
from obscura_packs.catalog import EXTRA, FACTORY, INSTALLED, load_catalog

SIGNATURES = frozenset({"mz"})


def manifest_text(name, version="1.0", runtime=False, depends=()):
    lines = [
        "[pack]",
        'name = "%s"' % name,
        "api = 1",
        'version = "%s"' % version,
        'platform = "windows"',
        'technique = "reimplementation"',
        'summary = "Test pack."',
    ]
    if runtime:
        lines.append("runtime = true")
    lines += ["", "[handles]", 'magic = ["mz"]']
    if depends:
        lines += ["", "[depends]", "runtime = [%s]" % ", ".join('"%s"' % d for d in depends)]
    return "\n".join(lines) + "\n"


def symlinks_work():
    with tempfile.TemporaryDirectory() as root:
        try:
            os.symlink("x", os.path.join(root, "link"))
            return True
        except (OSError, NotImplementedError):
            return False


SYMLINKS = symlinks_work()


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.factory = os.path.join(directory.name, "usr")
        self.installed = os.path.join(directory.name, "var")
        self.extra = os.path.join(directory.name, "extra")
        for path in (self.factory, self.installed, self.extra):
            os.mkdir(path)

    def put(self, root, directory, text):
        path = os.path.join(root, directory)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "pack.toml"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def install(self, name, version, text=None, link=True):
        self.put(os.path.join(self.installed, name), version, text or manifest_text(name, version))
        if link:
            os.symlink(version, os.path.join(self.installed, name, "current"))

    def load(self, **kwargs):
        return load_catalog(SIGNATURES, self.factory, self.installed, **kwargs)

    def problems(self, catalog):
        return [reason for _, reason in catalog.problems]

    def test_factory_packs(self):
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", runtime=True))
        catalog = self.load()
        self.assertEqual(catalog.names(), ["pack-wine"])
        self.assertEqual(catalog.get("pack-wine").origin, FACTORY)
        self.assertEqual(catalog.problems, [])

    def test_missing_roots_are_empty(self):
        catalog = load_catalog(SIGNATURES, os.path.join(self.factory, "none"), os.path.join(self.installed, "none"))
        self.assertEqual(catalog.names(), [])
        self.assertEqual(self.sent, [])

    def test_one_bad_manifest_does_not_block_the_others(self):
        self.put(self.factory, "pack-good", manifest_text("pack-good"))
        self.put(self.factory, "pack-bad", "[pack\n")
        self.put(self.factory, "pack-misnamed", manifest_text("pack-other"))
        self.put(self.factory, "Not_A_Pack", manifest_text("pack-x"))
        catalog = self.load()
        self.assertEqual(catalog.names(), ["pack-good"])
        self.assertEqual(len(catalog.problems), 3)

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_installed_current_wins_over_factory(self):
        self.put(self.factory, "pack-dosbox", manifest_text("pack-dosbox", "1.0"))
        self.install("pack-dosbox", "2.0", manifest_text("pack-dosbox", "2.0"))
        pack = self.load().get("pack-dosbox")
        self.assertEqual(pack.origin, INSTALLED)
        self.assertEqual(pack.manifest.version, "2.0")

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_installed_runtime_pack_falls_back_to_factory(self):
        # Only factory packs may be runtimes until signed repository packs (task 0.23).
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", "1.0", runtime=True))
        self.install("pack-wine", "2.0", manifest_text("pack-wine", "2.0", runtime=True))
        catalog = self.load()
        self.assertEqual(catalog.get("pack-wine").origin, FACTORY)
        self.assertEqual(catalog.get("pack-wine").manifest.version, "1.0")
        self.assertIn("only packs shipped in the image", self.problems(catalog)[0])

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_installed_pack_cannot_become_a_runtime(self):
        self.install("pack-evil", "1.0", manifest_text("pack-evil", "1.0", runtime=True))
        self.put(self.factory, "pack-victim", manifest_text("pack-victim", depends=["pack-evil"]))
        catalog = self.load()
        self.assertIsNone(catalog.get("pack-evil"))
        # The dependent stays, and readiness will say the runtime isn't installed.
        self.assertIsNotNone(catalog.get("pack-victim"))

    def test_extra_root_runtime_pack_is_rejected(self):
        self.put(self.extra, "pack-proton", manifest_text("pack-proton", runtime=True))
        catalog = self.load(extra_roots=[self.extra])
        self.assertIsNone(catalog.get("pack-proton"))
        self.assertIn("only packs shipped in the image", self.problems(catalog)[0])

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_installed_only_pack(self):
        self.install("pack-dosbox", "0.8")
        self.assertEqual(self.load().get("pack-dosbox").origin, INSTALLED)

    def test_removed_marker_hides_factory_pack(self):
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", runtime=True))
        os.makedirs(os.path.join(self.installed, "pack-wine"))
        open(os.path.join(self.installed, "pack-wine", "removed"), "w").close()
        catalog = self.load()
        self.assertEqual(catalog.names(), [])
        self.assertEqual(catalog.problems, [])

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_broken_current_falls_back_to_factory(self):
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", "1.0", runtime=True))
        os.makedirs(os.path.join(self.installed, "pack-wine"))
        os.symlink("9.9", os.path.join(self.installed, "pack-wine", "current"))
        catalog = self.load()
        self.assertEqual(catalog.get("pack-wine").origin, FACTORY)
        self.assertEqual(len(catalog.problems), 1)

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_current_must_point_at_a_sibling_version(self):
        for target in ("/usr/share/obscura/packs/pack-wine", "../pack-other/1.0", ".."):
            with self.subTest(target):
                base = os.path.join(self.installed, "pack-x")
                os.makedirs(base, exist_ok=True)
                link = os.path.join(base, "current")
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(target, link)
                catalog = self.load()
                self.assertIsNone(catalog.get("pack-x"))
                self.assertIn("version directory", self.problems(catalog)[0])

    @unittest.skipUnless(SYMLINKS, "symlinks unavailable")
    def test_installed_manifest_must_match_name_and_version(self):
        self.install("pack-a", "1.0", manifest_text("pack-b", "1.0"))
        self.install("pack-c", "1.0", manifest_text("pack-c", "2.0"))
        catalog = self.load()
        self.assertEqual(catalog.names(), [])
        self.assertEqual(len(catalog.problems), 2)

    def test_current_that_is_not_a_symlink(self):
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", runtime=True))
        os.makedirs(os.path.join(self.installed, "pack-wine", "current"))
        catalog = self.load()
        self.assertEqual(catalog.get("pack-wine").origin, FACTORY)
        self.assertIn("not a symlink", self.problems(catalog)[0])

    def test_extra_roots_add_but_never_replace(self):
        self.put(self.factory, "pack-wine", manifest_text("pack-wine", runtime=True))
        self.put(self.extra, "pack-wine", manifest_text("pack-wine", "6.6"))
        self.put(self.extra, "pack-fixture", manifest_text("pack-fixture"))
        catalog = self.load(extra_roots=[self.extra])
        self.assertEqual(catalog.get("pack-wine").origin, FACTORY)
        self.assertEqual(catalog.get("pack-fixture").origin, EXTRA)
        self.assertIn("duplicate", self.problems(catalog)[0])

    def test_dependency_on_a_runtime_pack(self):
        self.put(self.factory, "pack-proton", manifest_text("pack-proton", runtime=True))
        self.put(self.factory, "pack-steamvr", manifest_text("pack-steamvr", depends=["pack-proton"]))
        self.assertEqual(self.load().names(), ["pack-proton", "pack-steamvr"])

    def test_dependency_on_an_uninstalled_pack_is_kept_for_readiness(self):
        self.put(self.factory, "pack-steamvr", manifest_text("pack-steamvr", depends=["pack-proton"]))
        catalog = self.load()
        self.assertEqual(catalog.names(), ["pack-steamvr"])
        self.assertEqual(catalog.problems, [])

    def test_dependency_on_a_non_runtime_pack_is_rejected(self):
        self.put(self.factory, "pack-dosbox", manifest_text("pack-dosbox"))
        self.put(self.factory, "pack-bad", manifest_text("pack-bad", depends=["pack-dosbox"]))
        catalog = self.load()
        self.assertEqual(catalog.names(), ["pack-dosbox"])
        self.assertIn("not a runtime pack", self.problems(catalog)[0])

    def test_two_level_dependency_is_impossible(self):
        # A runtime pack can't have [depends], so A -> runtime B -> C never validates.
        self.put(self.factory, "pack-b", manifest_text("pack-b", runtime=True, depends=["pack-c"]))
        catalog = self.load()
        self.assertEqual(catalog.names(), [])
        self.assertIn("runtime pack cannot depend", self.problems(catalog)[0])


if __name__ == "__main__":
    unittest.main()
