# Journal fixtures (task 0.2b)

PID 1 journal entries used to test `tests/lib/journal_verdict.py`, which decides whether a
start job of a capability target really reached it or was skipped by the gate's
condition (`tests/unit/test_journal_verdict.py`).

| File | Source | Contents |
|---|---|---|
| `gate-systemd-255.jsonl` | capd-tests run 45440862970 (2026-11-24), systemd 255.4-1ubuntu8.18, `upholds-gate.sh` diagnostics | The journal fields (`-o verbose --output-fields=...`) of five entries, one JSON object per line: the reject probe's "Starting" and its condition skip, the reject target's condition skip, the control target's real "Reached target", and its "Stopped target". Host, boot and cursor fields left out |

Recorded systemd 262 entries come from the `gate-on-image` job's `gate-on-image-journal`
artifact (`journalctl -o json`, PID 1, `MESSAGE_ID=39f53479…`) and are added as
`gate-systemd-262.jsonl`. 262 words the skip differently ("… skipped, unmet condition
check …").

The skip entries and the real start carry the same `MESSAGE_ID` (`39f53479…`,
`SD_MESSAGE_UNIT_STARTED`), `JOB_TYPE=start` and `JOB_RESULT=done`; only the text tells
them apart. That is the reason these fixtures exist.
