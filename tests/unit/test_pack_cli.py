"""obscura-pack (obscura_packs.cli) against temporary roots, with capd stubbed out."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from tests import SIGNATURES_FILE
from tests.unit.test_readiness import VOCABULARY
from obscura_capd import report
from obscura_packs import capabilities, cli

CONTENT = b"obscura cli test file\n"

DEMO = """[pack]
name = "pack-demo"
api = 1
version = "1"
platform = "retro"
technique = "emulation"
summary = "Demo."
[handles]
extensions = [".dmo"]
[requires]
capabilities = ["camera"]
[[user_supplies]]
id = "bios"
label = "Demo BIOS"
kind = "bios"
file = "demo.dat"
sha256 = ["%s"]
""" % hashlib.sha256(CONTENT).hexdigest()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)
        # cli.main() reports as obscura-pack; put capd's identity back for later tests.
        self.addCleanup(report.set_identifier, "obscura-capd")
        self.present = {"camera"}
        for name, value in (("present_capabilities", lambda: frozenset(self.present)),
                            ("capability_vocabulary", lambda: VOCABULARY)):
            patcher = mock.patch.object(capabilities, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        self.factory = os.path.join(self.root, "usr")
        os.makedirs(os.path.join(self.factory, "pack-demo"))
        with open(os.path.join(self.factory, "pack-demo", "pack.toml"), "w", encoding="utf-8") as handle:
            handle.write(DEMO)
        self.home = os.path.join(self.root, "home")

    def run_cli(self, *argv):
        output = io.StringIO()
        base = ["--factory-root", self.factory, "--installed-root", os.path.join(self.root, "var"),
                "--home", self.home, "--signatures", SIGNATURES_FILE]
        with contextlib.redirect_stdout(output):
            status = cli.main(base + list(argv))
        return status, output.getvalue()

    def place_bios(self, content=CONTENT):
        directory = os.path.join(self.home, "Obscura", "firmware", "demo")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "demo.dat"), "wb") as handle:
            handle.write(content)

    def test_validate(self):
        status, output = self.run_cli("validate", os.path.join(self.factory, "pack-demo"))
        self.assertEqual(status, 0)
        self.assertIn("OK pack-demo", output)
        bad = os.path.join(self.root, "pack-bad")
        os.mkdir(bad)
        with open(os.path.join(bad, "pack.toml"), "w", encoding="utf-8") as handle:
            handle.write("[pack\n")
        status, output = self.run_cli("validate", bad)
        self.assertEqual(status, 1)
        self.assertIn("INVALID", output)

    def test_list_json(self):
        status, output = self.run_cli("list", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["packs"][0]["origin"], "factory")

    def test_readiness_follows_files_and_hardware(self):
        status, output = self.run_cli("readiness", "pack-demo", "--json")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output)["pack-demo"]["state"], "missing-files")

        self.place_bios(b"not the right dump\n")
        status, output = self.run_cli("readiness", "pack-demo", "--json")
        self.assertEqual(json.loads(output)["pack-demo"]["reasons"][0]["code"], "file-wrong-dump")

        self.place_bios()
        status, output = self.run_cli("readiness", "pack-demo", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["pack-demo"]["state"], "ready")

        self.present = set()
        status, output = self.run_cli("readiness", "pack-demo", "--json")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output)["pack-demo"]["state"], "missing-hardware")

    def test_unknown_pack_is_a_usage_error(self):
        status, _ = self.run_cli("readiness", "pack-nope")
        self.assertEqual(status, 2)

    def test_bad_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["frobnicate"]), 2)


if __name__ == "__main__":
    unittest.main()
