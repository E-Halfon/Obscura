"""obscura-pack readiness against a real obscura-capd on a private bus (task 0.21).

capd mirrors a mock systemd (the CapdHarness from test_capd_dbus). Flipping the camera
target must flip a camera-requiring fixture pack between Missing hardware and Ready.
Real hardware is covered by tests/vm/packs.sh on the built image.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests import CAPD_PYTHONPATH, PACK_FIXTURES_DIR, SIGNATURES_FILE
from tests.integration.test_capd_dbus import SKIP_REASON, TIMEOUT, CapdHarness, dbus, wait_for


@unittest.skipIf(dbus is None, SKIP_REASON)
class PacksCapdTest(CapdHarness):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = directory.name

    def readiness(self, *names):
        env = self.environment()
        env["PYTHONPATH"] = CAPD_PYTHONPATH
        result = subprocess.run(
            [sys.executable, "-P", "-m", "obscura_packs.cli",
             "--factory-root", os.path.join(self.root, "usr"),
             "--installed-root", os.path.join(self.root, "var"),
             "--extra-root", PACK_FIXTURES_DIR,
             "--home", os.path.join(self.root, "home"),
             "--signatures", SIGNATURES_FILE,
             "readiness", "--json", *names],
            env=env, capture_output=True, text=True, timeout=TIMEOUT * 2,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return {name: value["state"] for name, value in json.loads(result.stdout).items()}

    def test_camera_hotplug_flips_readiness(self):
        self.start_capd()
        self.assertEqual(self.readiness("pack-fixture-camera"), {"pack-fixture-camera": "missing-hardware"})

        self.set_target("obscura-cap-camera.target", "active", 1700000000000001)
        wait_for(lambda: bool(self.manager().Has("camera")), "camera present")
        self.assertEqual(self.readiness("pack-fixture-camera"), {"pack-fixture-camera": "ready"})

        self.set_target("obscura-cap-camera.target", "inactive")
        wait_for(lambda: not self.manager().Has("camera"), "camera absent")
        self.assertEqual(self.readiness("pack-fixture-camera"), {"pack-fixture-camera": "missing-hardware"})

    def test_without_capd_hardware_packs_are_unevaluable_never_ready(self):
        # capd is deliberately not started.
        states = self.readiness("pack-fixture-camera", "pack-fixture-none")
        self.assertEqual(states, {"pack-fixture-camera": "unevaluable", "pack-fixture-none": "ready"})


if __name__ == "__main__":
    unittest.main()
