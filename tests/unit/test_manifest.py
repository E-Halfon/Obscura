"""Pack manifest v1 parsing and validation (obscura_packs.manifest)."""

import os
import tempfile
import unittest
from unittest import mock

from tests import SIGNATURES_FILE
from obscura_capd import report
from obscura_packs import manifest
from obscura_packs.manifest import (
    ManifestError,
    load_manifest_file,
    load_signatures,
    parse_manifest,
    parse_signatures,
    validate_manifest,
)

SIGNATURES = frozenset({"mz"})
SHA = "a" * 64

VALID = """
[pack]
name      = "pack-example"
api       = 1
version   = "1.2-3"
platform  = "retro"
technique = "emulation"
summary   = "An example pack."

[handles]
magic      = ["mz"]
extensions = [".cue"]

[requires]
capabilities = ["x86-64-v3"]

[recommends]
capabilities = ["dgpu"]

[[user_supplies]]
id     = "bios-us"
label  = "Example BIOS (US)"
kind   = "bios"
file   = "example.dat"
sha256 = ["%s"]

[fallback]
remote = true
""" % SHA


def replace(text, old, new):
    """VALID with one line changed; fails loudly if the line isn't there."""
    if old not in text:
        raise AssertionError("fixture line not found: " + old)
    return text.replace(old, new, 1)


class ReportCapture(unittest.TestCase):
    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)

    def failures(self):
        return [args for args in self.sent if args[0] == 3 and "failure in" in args[2]]


class ParseManifestTest(ReportCapture):
    def test_valid(self):
        pack = parse_manifest(VALID, "pack.toml", SIGNATURES, "pack-example")
        self.assertEqual(pack.name, "pack-example")
        self.assertEqual(pack.files_dir, "example")
        self.assertEqual(pack.status, "experimental")
        self.assertFalse(pack.runtime)
        self.assertEqual(pack.requires, ("x86-64-v3",))
        self.assertEqual(pack.recommends, ("dgpu",))
        self.assertTrue(pack.remote)
        self.assertEqual(len(pack.user_supplies), 1)
        self.assertTrue(pack.user_supplies[0].required)
        self.assertEqual(pack.user_supplies[0].sha256, (SHA,))
        self.assertEqual(self.sent, [])

    def test_minimal_system_pack_handles_nothing(self):
        text = '[pack]\nname = "pack-sys"\napi = 1\nversion = "1"\nplatform = "system"\n' \
               'technique = "remote"\nsummary = "s"\n'
        pack = parse_manifest(text, "pack.toml", SIGNATURES)
        self.assertEqual(pack.magic, ())
        self.assertEqual(pack.user_supplies, ())

    def test_files_dir_shared_by_console(self):
        pack = parse_manifest(replace(VALID, 'summary   = "An example pack."',
                                      'summary   = "An example pack."\nfiles_dir = "ps1"'),
                              "pack.toml", SIGNATURES)
        self.assertEqual(pack.files_dir, "ps1")

    def test_os_image_may_omit_checksum(self):
        text = replace(VALID, 'kind   = "bios"', 'kind   = "os-image"')
        text = replace(text, 'sha256 = ["%s"]' % SHA, "")
        pack = parse_manifest(text, "pack.toml", SIGNATURES)
        self.assertEqual(pack.user_supplies[0].sha256, ())

    def test_rejections(self):
        cases = {
            "bad toml": "[pack\n",
            "no pack table": "[handles]\nmagic = []\n",
            "unknown table": VALID + "\n[extras]\nx = 1\n",
            "unknown key": replace(VALID, "remote = true", "remote = true\nremot = false"),
            "unknown pack key": replace(VALID, 'api       = 1', 'api       = 1\nvendor = "x"'),
            "missing name": replace(VALID, 'name      = "pack-example"', ""),
            "missing summary": replace(VALID, 'summary   = "An example pack."', ""),
            "blank summary": replace(VALID, '"An example pack."', '"   "'),
            "api 2": replace(VALID, "api       = 1", "api       = 2"),
            "api 0": replace(VALID, "api       = 1", "api       = 0"),
            "api bool": replace(VALID, "api       = 1", "api       = true"),
            "api string": replace(VALID, "api       = 1", 'api       = "1"'),
            "name without prefix": replace(VALID, '"pack-example"', '"example"'),
            "uppercase name": replace(VALID, '"pack-example"', '"pack-Example"'),
            "underscore name": replace(VALID, '"pack-example"', '"pack-ex_ample"'),
            "bad version": replace(VALID, '"1.2-3"', '"1.2 beta"'),
            "unknown platform": replace(VALID, '"retro"', '"ios"'),
            "unknown technique": replace(VALID, '"emulation"', '"magic"'),
            "unknown status": replace(VALID, 'summary   = "An example pack."', 'summary   = "s"\nstatus = "great"'),
            "runtime not bool": replace(VALID, 'summary   = "An example pack."', 'summary   = "s"\nruntime = 1'),
            "files_dir path": replace(VALID, 'summary   = "An example pack."', 'summary   = "s"\nfiles_dir = "../etc"'),
            "unregistered magic": replace(VALID, '["mz"]', '["elf"]'),
            "magic not a list": replace(VALID, '["mz"]', '"mz"'),
            "magic not strings": replace(VALID, '["mz"]', '[1]'),
            "duplicate extension": replace(VALID, '[".cue"]', '[".cue", ".cue"]'),
            "extension without dot": replace(VALID, '[".cue"]', '["cue"]'),
            "uppercase extension": replace(VALID, '[".cue"]', '[".CUE"]'),
            "installer is also extension": replace(VALID, 'extensions = [".cue"]', 'extensions = [".cue"]\ninstallers = [".cue"]'),
            "handles nothing": replace(replace(VALID, 'magic      = ["mz"]', ""), 'extensions = [".cue"]', ""),
            "required and recommended": replace(VALID, '["dgpu"]', '["x86-64-v3"]'),
            "bad capability name": replace(VALID, '["x86-64-v3"]', '["X86"]'),
            "remote not bool": replace(VALID, "remote = true", 'remote = "yes"'),
            "user file traversal": replace(VALID, '"example.dat"', '"../example.dat"'),
            "user file subdir": replace(VALID, '"example.dat"', '"sub/example.dat"'),
            "user file backslash": replace(VALID, '"example.dat"', '"sub\\\\example.dat"'),
            "user file hidden": replace(VALID, '"example.dat"', '".example"'),
            "user file empty": replace(VALID, '"example.dat"', '""'),
            "bios without checksum": replace(VALID, 'sha256 = ["%s"]' % SHA, ""),
            "bios empty checksum list": replace(VALID, 'sha256 = ["%s"]' % SHA, "sha256 = []"),
            "uppercase checksum": replace(VALID, SHA, "A" * 64),
            "short checksum": replace(VALID, SHA, "a" * 63),
            "unknown file kind": replace(VALID, '"bios"', '"save"'),
            "unknown user file key": replace(VALID, 'label  = "Example BIOS (US)"', 'label  = "x"\nwhere = "~/x"'),
            "bad user file id": replace(VALID, '"bios-us"', '"Bios"'),
            "user_supplies as table": replace(VALID, "[[user_supplies]]", "[user_supplies]"),
            "duplicate user file id": VALID + '\n[[user_supplies]]\nid = "bios-us"\nlabel = "x"\nkind = "media"\nfile = "y.dat"\n',
            "duplicate user file name": VALID + '\n[[user_supplies]]\nid = "other"\nlabel = "x"\nkind = "media"\nfile = "example.dat"\n',
            "self dependency": VALID + '\n[depends]\nruntime = ["pack-example"]\n',
            "runtime pack with depends": replace(VALID, 'summary   = "An example pack."', 'summary   = "s"\nruntime = true') + '\n[depends]\nruntime = ["pack-wine"]\n',
            "bad action name": VALID + '\n[provides]\nactions = ["Run-It"]\n',
            "device outside /dev": VALID + '\n[touches]\ndevices = ["/etc/passwd"]\n',
            "device traversal": VALID + '\n[touches]\ndevices = ["/dev/../etc/passwd"]\n',
            "bad kernel module": VALID + '\n[touches]\nkernel_modules = ["kvm amd"]\n',
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(ManifestError):
                    parse_manifest(text, "pack.toml", SIGNATURES)
        # Malformed manifests are expected input: none of these is an internal failure.
        self.assertEqual(self.failures(), [])

    def test_directory_must_match_name(self):
        with self.assertRaises(ManifestError):
            parse_manifest(VALID, "pack.toml", SIGNATURES, directory_name="pack-other")

    def test_size_limit(self):
        with self.assertRaises(ManifestError):
            parse_manifest(VALID + "#" * (64 * 1024), "pack.toml", SIGNATURES)

    def test_newer_api_says_so(self):
        with self.assertRaisesRegex(ManifestError, "newer Obscura"):
            parse_manifest(replace(VALID, "api       = 1", "api       = 2"), "pack.toml", SIGNATURES)

    def test_no_signature_registry_means_magic_is_invalid(self):
        with self.assertRaises(ManifestError):
            parse_manifest(VALID, "pack.toml", frozenset())


class FailClosedTest(ReportCapture):
    """An unexpected exception never yields a valid manifest (CLAUDE.md, 0.21 review)."""

    def test_exception_in_a_validator_makes_the_manifest_invalid(self):
        for target in ("_validate_user_supplies", "_validate_handles", "_validate_pack", "_tables"):
            with self.subTest(target):
                self.sent.clear()
                with mock.patch.object(manifest, target, side_effect=IndexError("boom")):
                    pack, reason = validate_manifest(VALID, "pack.toml", SIGNATURES)
                self.assertIsNone(pack)
                self.assertIn("internal error", reason)
                self.assertEqual(len(self.failures()), 1, self.sent)

    def test_exception_while_loading_a_file_makes_it_invalid(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, "pack-example")
            os.mkdir(directory)
            path = os.path.join(directory, "pack.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(VALID)
            with mock.patch.object(manifest, "validate_manifest", side_effect=RuntimeError("boom")):
                pack, reason = load_manifest_file(path, SIGNATURES)
            self.assertIsNone(pack)
            self.assertIn("internal error", reason)
            self.assertEqual(len(self.failures()), 1)

    def test_malformed_manifest_is_invalid_without_a_failure(self):
        pack, reason = validate_manifest("[pack\n", "pack.toml", SIGNATURES)
        self.assertIsNone(pack)
        self.assertIn("TOML", reason)
        self.assertEqual(self.failures(), [])


class LoadManifestFileTest(ReportCapture):
    def write(self, root, directory, text, binary=False):
        path = os.path.join(root, directory)
        os.makedirs(path, exist_ok=True)
        path = os.path.join(path, "pack.toml")
        with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as handle:
            handle.write(text)
        return path

    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as root:
            pack, reason = load_manifest_file(self.write(root, "pack-example", VALID), SIGNATURES)
            self.assertIsNone(reason)
            self.assertEqual(pack.name, "pack-example")

    def test_directory_name_checked(self):
        with tempfile.TemporaryDirectory() as root:
            pack, reason = load_manifest_file(self.write(root, "pack-wrong", VALID), SIGNATURES)
            self.assertIsNone(pack)
            self.assertIn("named after the pack", reason)

    def test_unreadable_and_non_utf8(self):
        with tempfile.TemporaryDirectory() as root:
            pack, reason = load_manifest_file(os.path.join(root, "pack-x", "pack.toml"), SIGNATURES)
            self.assertIsNone(pack)
            self.assertIn("cannot read", reason)
            pack, reason = load_manifest_file(self.write(root, "pack-example", b"\xff\xfe", binary=True), SIGNATURES)
            self.assertIsNone(pack)
        self.assertEqual(self.failures(), [])


class SignaturesTest(ReportCapture):
    def test_shipped_registry(self):
        names = load_signatures(SIGNATURES_FILE)
        self.assertIn("mz", names)
        self.assertEqual(self.sent, [])

    def test_rejections(self):
        cases = {
            "no api": '[signature.mz]\nsummary = "x"\nmagic = "4d5a"\n',
            "uppercase hex": 'api = 1\n[signature.mz]\nsummary = "x"\nmagic = "4D5A"\n',
            "odd hex": 'api = 1\n[signature.mz]\nsummary = "x"\nmagic = "4d5"\n',
            "mask length": 'api = 1\n[signature.mz]\nsummary = "x"\nmagic = "4d5a"\nmask = "ff"\n',
            "negative offset": 'api = 1\n[signature.mz]\nsummary = "x"\nmagic = "4d5a"\noffset = -1\n',
            "unknown key": 'api = 1\n[signature.mz]\nsummary = "x"\nmagic = "4d5a"\nhandler = "/bin/sh"\n',
            "bad name": 'api = 1\n[signature.MZ]\nsummary = "x"\nmagic = "4d5a"\n',
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(ManifestError):
                    parse_signatures(text, "signatures.toml")

    def test_missing_registry_is_empty_and_reported(self):
        names = load_signatures(os.path.join(tempfile.gettempdir(), "no-such-obscura-signatures.toml"))
        self.assertEqual(names, frozenset())
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
