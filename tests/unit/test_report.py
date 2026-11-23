"""report._send: stderr always; a structured journal entry only under systemd."""

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)
from obscura_capd import report
from obscura_capd.constants import MESSAGE_ID_FAILURE


def environment_without_invocation_id():
    env = dict(os.environ)
    env.pop("INVOCATION_ID", None)
    return env


class SendTest(unittest.TestCase):
    def setUp(self):
        self.journal = mock.Mock()
        patcher = mock.patch.object(report, "_journal", self.journal)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, environment):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), redirect_stderr(stderr):
            report.problem("capability camera", "target ActiveState is failed", OBSCURA_CAPABILITY="camera")
        return stderr.getvalue()

    def test_outside_systemd_stderr_only(self):
        output = self.send(environment_without_invocation_id())
        self.assertIn("target ActiveState is failed", output)
        self.assertIn("OBSCURA_CAPABILITY=camera", output)
        self.journal.send.assert_not_called()

    def test_under_systemd_stderr_and_structured_entry(self):
        output = self.send(dict(environment_without_invocation_id(), INVOCATION_ID="0123456789abcdef"))
        self.assertIn("target ActiveState is failed", output)
        self.journal.send.assert_called_once()
        self.assertEqual(self.journal.send.call_args.kwargs["MESSAGE_ID"], MESSAGE_ID_FAILURE)
        self.assertEqual(self.journal.send.call_args.kwargs["OBSCURA_CAPABILITY"], "camera")

    def test_journal_failure_still_writes_stderr(self):
        self.journal.send.side_effect = OSError("no journal socket")
        output = self.send(dict(environment_without_invocation_id(), INVOCATION_ID="0123456789abcdef"))
        self.assertIn("target ActiveState is failed", output)
        self.assertIn("could not send structured journal entry", output)

    def test_failure_includes_traceback_on_stderr(self):
        stderr = io.StringIO()
        try:
            raise ValueError("boom")
        except ValueError as error:
            with mock.patch.dict(os.environ, environment_without_invocation_id(), clear=True), redirect_stderr(stderr):
                report.failure("test", error)
        self.assertIn("ValueError: boom", stderr.getvalue())
        self.assertIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
