"""The vulkan-1.3 probe (obscura_capd.vulkan_probe) fails closed.

vulkaninfo is replaced in-process (any OS), and on POSIX also by a real fake executable on
PATH, so crashes, signals, exit codes and timeouts go through a real subprocess. Every
outcome is exit 0 (accept) or 1 (absent, reason logged); nothing escapes, nothing is 255.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)
from obscura_capd import report, vulkan_probe
from tests.unit import vulkan_fixtures as fixtures


class ProbeHarness(unittest.TestCase):
    def setUp(self):
        sent = mock.patch.object(report, "_send")
        self.sent = sent.start()
        self.addCleanup(sent.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sysfs = directory.name
        self.add_node("renderD128", "226:128\n")
        environment = mock.patch.dict(os.environ, {"OBSCURA_VULKAN_PROBE_SYSFS": self.sysfs})
        environment.start()
        self.addCleanup(environment.stop)

    def add_node(self, node, dev):
        os.makedirs(os.path.join(self.sysfs, node), exist_ok=True)
        with open(os.path.join(self.sysfs, node, "dev"), "w", encoding="ascii") as handle:
            handle.write(dev)

    def messages(self):
        return [call.args[2] for call in self.sent.call_args_list]

    def assert_absent_with(self, text, node="renderD128"):
        self.assertEqual(vulkan_probe.main([node]), vulkan_probe.ABSENT)
        self.assertTrue(any(text in message for message in self.messages()), self.messages())


def fake_run(documents, summary=None, on_json=None):
    """A subprocess.run replacement playing vulkaninfo with `documents` (one per device)."""
    if summary is None:
        summary = "Vulkan Instance Version: 1.4.318\nDevices:\n" + "".join(
            "GPU%d:\n" % index for index in range(len(documents)))

    def run(command, cwd=None, **kwargs):
        arguments = command[1:]
        if arguments == ["--summary"]:
            return subprocess.CompletedProcess(command, 0, summary, "")
        index = int(arguments[0].split("=", 1)[1])
        if on_json is not None:
            return on_json(command, cwd, index)
        with open(os.path.join(cwd, "device.json"), "w", encoding="utf-8") as handle:
            json.dump(documents[index], handle)
        return subprocess.CompletedProcess(command, 0, "", "")
    return run


class InProcessProbeTest(ProbeHarness):
    def run_with(self, documents, **kwargs):
        return mock.patch.multiple(
            vulkan_probe,
            shutil=mock.Mock(which=mock.Mock(return_value="/usr/bin/vulkaninfo")),
            subprocess=mock.Mock(run=fake_run(documents, **kwargs), CompletedProcess=subprocess.CompletedProcess,
                                 TimeoutExpired=subprocess.TimeoutExpired, DEVNULL=subprocess.DEVNULL),
        )

    def test_hardware_gpu_is_accepted(self):
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")
        with self.run_with(documents):
            self.assertEqual(vulkan_probe.main(["renderD128"]), vulkan_probe.ACCEPT)
        self.assertTrue(any("qualifies" in message for message in self.messages()))

    def test_other_node_of_the_same_machine_is_absent(self):
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")
        self.add_node("renderD129", "226:129\n")
        with self.run_with(documents):
            self.assert_absent_with("no hardware-accelerated Vulkan 1.3 device", node="renderD129")

    def test_virtual_gpu_is_absent(self):
        documents, _ = fixtures.load_scenario("synthetic-venus-virtual")
        with self.run_with(documents):
            self.assert_absent_with("VIRTUAL_GPU")

    def test_vulkaninfo_missing(self):
        with mock.patch.object(vulkan_probe.shutil, "which", return_value=None):
            self.assert_absent_with("vulkaninfo not found")

    def test_non_zero_exit(self):
        def failing(command, cwd, index):
            return subprocess.CompletedProcess(command, 3, "", "ERROR_INITIALIZATION_FAILED")
        with self.run_with([{}], on_json=failing):
            self.assert_absent_with("exited 3")

    def test_killed_by_a_signal(self):
        def crashing(command, cwd, index):
            return subprocess.CompletedProcess(command, -11, "", "")
        with self.run_with([{}], on_json=crashing):
            self.assert_absent_with("killed by signal 11")

    def test_timeout(self):
        def hanging(command, cwd, index):
            raise subprocess.TimeoutExpired(command, vulkan_probe.VULKANINFO_TIMEOUT)
        with self.run_with([{}], on_json=hanging):
            self.assert_absent_with("timed out")

    def test_deadline(self):
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")
        with self.run_with(documents), mock.patch.object(vulkan_probe, "DEADLINE", -1.0):
            self.assert_absent_with("deadline")

    def test_truncated_json(self):
        def truncated(command, cwd, index):
            with open(os.path.join(cwd, "device.json"), "w", encoding="utf-8") as handle:
                handle.write('{"capabilities": {"device": ')
            return subprocess.CompletedProcess(command, 0, "", "")
        with self.run_with([{}], on_json=truncated):
            self.assert_absent_with("isn't JSON")

    def test_schema_wrong_json(self):
        with self.run_with([{"capabilities": {"device": {"properties": {}}}}]):
            self.assert_absent_with("unexpected vulkaninfo JSON")

    def test_json_on_stdout_is_accepted(self):
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")

        def to_stdout(command, cwd, index):
            return subprocess.CompletedProcess(command, 0, json.dumps(documents[index]), "")
        with self.run_with(documents, on_json=to_stdout):
            self.assertEqual(vulkan_probe.main(["renderD128"]), vulkan_probe.ACCEPT)

    def test_no_devices_listed(self):
        with self.run_with([], summary="Devices:\n"):
            self.assert_absent_with("lists no devices")

    def test_unreadable_sysfs(self):
        self.assert_absent_with("can't read", node="renderD200")
        self.add_node("renderD130", "garbage\n")
        self.assert_absent_with("unreadable device number", node="renderD130")

    def test_bad_node_name(self):
        self.assert_absent_with("not a render node name", node="card0")
        self.assert_absent_with("not a render node name", node="../renderD128")

    def test_wrong_argument_count(self):
        self.assertEqual(vulkan_probe.main([]), vulkan_probe.ABSENT)
        self.assertEqual(vulkan_probe.main(["renderD128", "extra"]), vulkan_probe.ABSENT)

    def test_unexpected_exception_is_reported_and_absent(self):
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")
        with self.run_with(documents), mock.patch.object(vulkan_probe, "node_qualifies", side_effect=IndexError("boom")):
            self.assert_absent_with("IndexError: boom")

    def test_environment_drops_driver_overrides(self):
        with mock.patch.dict(os.environ, {"VK_ICD_FILENAMES": "/tmp/evil.json", "MESA_VK_DEVICE_SELECT": "1"}):
            cleaned = vulkan_probe.environment()
        self.assertNotIn("VK_ICD_FILENAMES", cleaned)
        self.assertNotIn("MESA_VK_DEVICE_SELECT", cleaned)
        self.assertEqual(cleaned["MESA_SHADER_CACHE_DISABLE"], "true")


@unittest.skipIf(os.name != "posix", "needs a POSIX shell to stand in for vulkaninfo")
class RealSubprocessProbeTest(ProbeHarness):
    """The probe as a separate process, with a fake vulkaninfo on PATH."""

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bin = directory.name
        documents, _ = fixtures.load_scenario("synthetic-radv-lavapipe")
        self.documents = []
        for index, document in enumerate(documents):
            path = os.path.join(self.bin, "gpu%d.json" % index)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            self.documents.append(path)

    def install(self, json_branch):
        """A fake vulkaninfo: --summary lists two GPUs; --json=N runs `json_branch`."""
        script = textwrap.dedent("""\
            #!/bin/sh
            if [ "$1" = "--summary" ]; then
                printf 'Devices:\\nGPU0:\\nGPU1:\\n'
                exit 0
            fi
            index=${1#--json=}
            """) + json_branch + "\n"
        path = os.path.join(self.bin, "vulkaninfo")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def run_probe(self, timeout=None):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = tests.CAPD_PYTHONPATH
        env["OBSCURA_VULKAN_PROBE_SYSFS"] = self.sysfs
        code = ("import sys; from obscura_capd import vulkan_probe as p; "
                + ("p.VULKANINFO_TIMEOUT = %r; " % timeout if timeout else "")
                + "sys.exit(p.main(['renderD128']))")
        return subprocess.run([sys.executable, "-P", "-c", code], env=env, capture_output=True, text=True, timeout=60)

    def test_accepts_via_output_file(self):
        self.install('cp "%s/gpu$index.json" device.json' % self.bin)
        result = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fail_closed_cases(self):
        cases = {
            "exit 3": ("exit 3", None, "exited 3"),
            "segfault": ("kill -SEGV $$", None, "killed by signal 11"),
            "hang": ("sleep 30", 0.5, "timed out"),
            "truncated": ("printf '{\"capabilities\": ' > device.json", None, "isn't JSON"),
            "schema": ("printf '{\"x\": 1}' > device.json", None, "unexpected vulkaninfo JSON"),
        }
        for label, (branch, timeout, expected) in cases.items():
            with self.subTest(label):
                self.install(branch)
                result = self.run_probe(timeout)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("Traceback", result.stderr.split("OBSCURA_TRACEBACK")[0])


if __name__ == "__main__":
    unittest.main()
