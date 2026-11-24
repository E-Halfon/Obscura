"""tests/lib/journal_verdict.py against PID 1 entries recorded on systemd 255 (task 0.2b).

A condition-skipped start job and a real one carry the same MESSAGE_ID, JOB_TYPE and
JOB_RESULT; the classifier must tell them apart by text, or the gate tests read every
rejection as "Reached target" (the VM C-12 false failure of 2026-11-24).
"""

import importlib.util
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "tests", "lib", "journal_verdict.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "journal", "gate-systemd-255.jsonl")

spec = importlib.util.spec_from_file_location("journal_verdict", SCRIPT)
journal_verdict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal_verdict)


def recorded():
    with open(FIXTURE, encoding="utf-8") as handle:
        return handle.read().splitlines()


class RecordedEntriesTest(unittest.TestCase):

    def test_target_skip_is_skipped_not_reached(self):
        found = journal_verdict.verdicts(recorded(), "obscura-test-reject.target")
        self.assertEqual([v for v, _ in found], ["skipped"])

    def test_probe_skip_is_skipped(self):
        found = journal_verdict.verdicts(recorded(), "obscura-test-reject-probe@x.service")
        # The "Starting ..." entry has no JOB_RESULT and isn't a finished start job.
        self.assertEqual([v for v, _ in found], ["skipped"])

    def test_real_start_is_reached_and_stop_is_ignored(self):
        found = journal_verdict.verdicts(recorded(), "obscura-test-control.target")
        self.assertEqual(found, [("reached", "Reached target obscura-test-control.target - "
                                  "Obscura test stand-in capability (control).")])

    def test_skip_and_reach_share_the_message_id(self):
        # The reason the text decides: if systemd ever changes this, revisit the classifier.
        entries = [json.loads(line) for line in recorded()]
        ids = {e["UNIT"]: e.get("MESSAGE_ID") for e in entries if e.get("JOB_RESULT") == "done"
               and e.get("JOB_TYPE") == "start"}
        self.assertEqual(ids["obscura-test-reject.target"], journal_verdict.UNIT_STARTED)
        self.assertEqual(ids["obscura-test-control.target"], journal_verdict.UNIT_STARTED)

    def test_other_units_are_ignored(self):
        self.assertEqual(journal_verdict.verdicts(recorded(), "obscura-cap-vulkan-1.3.target"), [])


class ClassifyTest(unittest.TestCase):

    def entry(self, **fields):
        base = {"UNIT": "t.target", "MESSAGE_ID": journal_verdict.UNIT_STARTED,
                "JOB_TYPE": "start", "JOB_RESULT": "done", "MESSAGE": "Reached target t.target."}
        base.update(fields)
        return base

    def test_failed_or_other_jobs_are_not_verdicts(self):
        self.assertIsNone(journal_verdict.classify(self.entry(JOB_RESULT="failed"), "t.target"))
        self.assertIsNone(journal_verdict.classify(self.entry(JOB_TYPE="stop"), "t.target"))
        self.assertIsNone(journal_verdict.classify(self.entry(MESSAGE_ID="other"), "t.target"))

    def test_both_skip_wordings(self):
        for text in ("t.target - T was skipped because of an unmet condition check (X=y).",
                     "t.target - T was skipped because no trigger condition checks were met.",
                     "Condition check resulted in t.target - T being skipped."):
            with self.subTest(text):
                self.assertEqual(journal_verdict.classify(self.entry(MESSAGE=text), "t.target"), "skipped")

    def test_byte_array_message(self):
        message = list("Reached target t.target.".encode())
        self.assertEqual(journal_verdict.classify(self.entry(MESSAGE=message), "t.target"), "reached")

    def test_command_line(self):
        done = subprocess.run([sys.executable, "-I", SCRIPT, "obscura-test-control.target"],
                              input="\n".join(recorded()) + "\n", capture_output=True, text=True,
                              check=True)
        self.assertEqual(done.stdout, "reached\tReached target obscura-test-control.target - "
                                      "Obscura test stand-in capability (control).\n")


if __name__ == "__main__":
    unittest.main()
