# Journal fixtures (task 0.2b)

PID 1 journal entries used to test `tests/lib/journal_verdict.py`, which decides whether a
start job of a capability target really reached it or was skipped by the gate's
condition (`tests/unit/test_journal_verdict.py`).

| File | Source | Contents |
|---|---|---|
| `gate-systemd-262.jsonl` | bluebuild run 45447100505, job `gate-on-image` (2026-11-24): image `e38d61f-45`, systemd 262.1-1.fc45, artifact `gate-on-image-journal` (`journalctl -o json _PID=1 MESSAGE_ID=39f53479…`) | Three entries: the reject target's condition skip (first start, empty INVOCATION_ID), the control target's real "Reached target", and the spam target's skip after it had run (INVOCATION_ID set). PID 1's job fields, MESSAGE, MESSAGE_ID, CODE_* and UNIT kept; host, boot, machine, cursor and timestamp fields left out |
| `gate-systemd-255.jsonl` | capd-tests run 45440862970 (2026-11-24), systemd 255.4-1ubuntu8.18, `upholds-gate.sh` diagnostics | The journal fields (`-o verbose --output-fields=...`) of five entries, one JSON object per line: the reject probe's "Starting" and its condition skip, the reject target's condition skip, the control target's real "Reached target", and its "Stopped target". Host, boot and cursor fields left out |

262 words the skip differently ("… skipped, unmet condition check …"). On 262 the skip
and the real start differ only in MESSAGE (and CODE_LINE, a source line that changes
between builds); INVOCATION_ID is empty on a first skip but set once the unit has run, so
it can't tell them apart either.

The skip entries and the real start carry the same `MESSAGE_ID` (`39f53479…`,
`SD_MESSAGE_UNIT_STARTED`), `JOB_TYPE=start` and `JOB_RESULT=done`; only the text tells
them apart. That is the reason these fixtures exist.
