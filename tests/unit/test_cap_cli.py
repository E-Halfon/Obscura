"""obscura-cap (obscura_capd.cli) with the capability service stubbed out.

`has NAME` prints "present" (exit 0) or "absent" (exit 1). An unknown name, an unreachable
service or any other error prints nothing on stdout, says why on stderr, and exits 2.
The DBus integration test runs the same commands against a real capd.
"""

import contextlib
import io
import sys
import types
import unittest
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)
from obscura_capd import cli


class UnknownCapabilityError(Exception):
    """Stands in for obscura_capd.errors.UnknownCapabilityError, which needs dasbus."""


class FakeProxy:
    def __init__(self, present, declared):
        self.present = present
        self.declared = declared

    def Has(self, name):
        if name not in self.declared:
            raise UnknownCapabilityError("unknown capability: " + name)
        return name in self.present


class HasTest(unittest.TestCase):
    def setUp(self):
        errors = types.ModuleType("obscura_capd.errors")
        errors.UnknownCapabilityError = UnknownCapabilityError
        patcher = mock.patch.dict(sys.modules, {"obscura_capd.errors": errors})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_has(self, name, proxy=None, proxy_error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        side_effect = proxy_error if proxy_error is not None else (lambda: proxy)
        with mock.patch.object(cli, "_proxy", side_effect=side_effect), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main(["has", name])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_present(self):
        status, out, _ = self.run_has("battery", FakeProxy({"battery"}, {"battery", "camera"}))
        self.assertEqual((status, out), (0, "present\n"))

    def test_absent(self):
        """camera absent: prints "absent" and exits 1 (the VM pass saw exit 0 only because a
        webcam was connected, so camera really was present)."""
        status, out, _ = self.run_has("camera", FakeProxy({"battery"}, {"battery", "camera"}))
        self.assertEqual((status, out), (1, "absent\n"))

    def test_unknown_name(self):
        status, out, err = self.run_has("windows-apps", FakeProxy(set(), {"camera"}))
        self.assertEqual((status, out), (2, ""))
        self.assertIn("unknown capability", err)

    def test_service_unreachable(self):
        status, out, _ = self.run_has("camera", proxy_error=RuntimeError("no bus"))
        self.assertEqual((status, out), (2, ""))

    def test_other_error_during_has(self):
        proxy = mock.Mock()
        proxy.Has.side_effect = RuntimeError("timeout")
        status, out, err = self.run_has("camera", proxy)
        self.assertEqual((status, out), (2, ""))
        self.assertIn("timeout", err)

    def test_bad_arguments(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main(["has"])
        self.assertEqual((status, stdout.getvalue()), (2, ""))


if __name__ == "__main__":
    unittest.main()
