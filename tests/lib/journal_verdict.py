"""Classify PID 1's start-job entries for one unit (task 0.2b gate tests).

    journalctl -o json _PID=1 UNIT=<unit> ... | python3 -I journal_verdict.py <unit>

Prints one line per start job that finished, tab-separated:

    reached<TAB><MESSAGE>   the unit really started ("Reached target ...")
    skipped<TAB><MESSAGE>   a condition failed, the unit was not started

Why not MESSAGE_ID alone: systemd finishes a condition-skipped start job as JOB_DONE, and
job_done_mid() (src/core/job.c) gives every JOB_START/JOB_DONE the MESSAGE_ID
SD_MESSAGE_UNIT_STARTED (39f53479...). A skip and a real start carry the same ID,
JOB_TYPE=start and JOB_RESULT=done; only the text differs ("... was skipped because of an
unmet condition check (...)", or "Condition check resulted in ... being skipped." for some
units). These entries are logged at the default log level, unlike "changed dead -> active",
which is debug-only and so isn't used here.

Test helper (tests/ is exempt from the production try/except rule): a malformed line raises.
"""

import json
import sys

UNIT_STARTED = "39f53479d3a045ac8e11786248231fbf"
SKIP_TEXTS = ("was skipped because", "being skipped")


def classify(entry, unit):
    """'reached', 'skipped' or None for one journal entry (a dict of journal fields)."""
    if entry.get("UNIT") != unit:
        return None
    if entry.get("MESSAGE_ID") != UNIT_STARTED:
        return None
    if entry.get("JOB_TYPE") != "start" or entry.get("JOB_RESULT") != "done":
        return None
    message = entry.get("MESSAGE")
    if not isinstance(message, str):
        # journalctl -o json gives non-UTF-8 or binary messages as a byte array.
        message = bytes(message or []).decode("utf-8", "replace")
    if any(text in message for text in SKIP_TEXTS):
        return "skipped"
    return "reached"


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
            found.append((verdict, entry.get("MESSAGE")))
    return found


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: journal_verdict.py <unit> < journalctl -o json output\n")
        return 2
    for verdict, message in verdicts(sys.stdin, argv[1]):
        sys.stdout.write(verdict + "\t" + str(message).replace("\n", " ") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
