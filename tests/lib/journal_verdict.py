"""Classify PID 1's start-job entries for one unit (task 0.2b gate tests).

    journalctl -o json _PID=1 UNIT=<unit> ... | python3 -I journal_verdict.py <unit>

Prints one line per finished start job of <unit>, tab-separated:

    reached<TAB><MESSAGE>   identified positively: MESSAGE starts "Reached target <unit>"
    skipped<TAB><MESSAGE>   a condition failed and the unit was not started (wording of
                            systemd 255 or 262, below)
    unknown<TAB><MESSAGE>   a finished start job (MESSAGE_ID UNIT_STARTED, JOB_TYPE=start,
                            JOB_RESULT=done) that is neither; callers treat it as a failure,
                            so a new systemd wording can't pass or fail silently

Why text: systemd finishes a condition-skipped start job as JOB_DONE, and job_done_mid()
(src/core/job.c) gives every JOB_START/JOB_DONE the MESSAGE_ID SD_MESSAGE_UNIT_STARTED
(39f53479...). A skip and a real start carry the same ID, JOB_TYPE and JOB_RESULT on both
255 and 262, and the skip's wording changed between them:
    255  "<unit> - <description> was skipped because of an unmet condition check (<cond>)."
    262  "<unit> - <description> skipped, unmet condition check <cond>"
Recorded entries of both are in tests/fixtures/journal/. These entries are logged at the
default log level, unlike "changed dead -> active", which is debug-only and isn't used.

Test helper (tests/ is exempt from the production try/except rule): a malformed line raises.
"""

import json
import re
import sys

UNIT_STARTED = "39f53479d3a045ac8e11786248231fbf"
SKIP_PATTERN = re.compile(
    r"was skipped because of an unmet condition check"   # 255 (and earlier)
    r"|skipped, unmet condition check"                     # 262
    r"|skipped because no trigger condition checks were met"
    r"|^Condition check resulted in .* being skipped\.")   # older wording, services


def message_text(entry):
    """MESSAGE as text; journalctl -o json gives non-UTF-8 messages as a byte array."""
    message = entry.get("MESSAGE")
    if isinstance(message, str):
        return message
    return bytes(message or []).decode("utf-8", "replace")


def classify(entry, unit):
    """'reached', 'skipped', 'unknown' or None for one journal entry (a dict of fields)."""
    if entry.get("UNIT") != unit or entry.get("_PID", "1") != "1":
        return None
    message = message_text(entry)
    if re.match(r"Reached target " + re.escape(unit) + r"(\s|\.|$)", message):
        return "reached"
    if SKIP_PATTERN.search(message):
        return "skipped"
    if (entry.get("MESSAGE_ID") == UNIT_STARTED and entry.get("JOB_TYPE") == "start"
            and entry.get("JOB_RESULT") == "done"):
        return "unknown"
    return None


def verdicts(lines, unit):
    """[(verdict, message)] for the JSON lines of `journalctl -o json`, in order."""
    found = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        verdict = classify(entry, unit)
        if verdict is not None:
            found.append((verdict, message_text(entry)))
    return found


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: journal_verdict.py <unit> < journalctl -o json output\n")
        return 2
    for verdict, message in verdicts(sys.stdin, argv[1]):
        sys.stdout.write(verdict + "\t" + message.replace("\n", " ") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
