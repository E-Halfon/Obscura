# shellcheck shell=bash
# Camera Obscura: checks for the probed-capability gate (task 0.2b), shared by
# tests/ci/upholds-gate.sh (GitHub runner, image container) and tests/vm/capabilities.sh
# (C-12, C-13, VM).
#
# Primary proof that a target never became active: PID 1's journal entry for each start
# job of the target is the "skipped because of an unmet condition" one, and there is no
# real "Reached target" (journal_verdict.py: MESSAGE_ID UNIT_STARTED, JOB_TYPE=start,
# JOB_RESULT=done, and not a skip text). Both are logged at the default log level.
#
# Secondary: properties (ActiveEnterTimestamp == 0, ConditionResult, Result). Only valid
# while the unit stayed loaded: PID 1 garbage-collects an unreferenced inactive unit, and
# the next `systemctl show` reads a fresh object whose timestamps are 0 (CI diagnostic run
# of 2026-11-24). gate_pin keeps units loaded; gate_pin_held checks that it did.

GATE_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GATE_PIN_PID=""
GATE_PIN_FILE=""

# gate_verdicts <unit> <journalctl filter args...>: "reached|skipped<TAB>message" lines
# for <unit>'s finished start jobs among PID 1's entries matching the filter. Flushes the
# journal first, so the entries of a job that just finished are readable.
gate_verdicts() {
    local unit=$1 json
    shift
    journalctl --sync 2>/dev/null || true
    json=$(journalctl -q --no-pager -o json "$@" _PID=1 UNIT="$unit" || true)
    printf '%s\n' "$json" | python3 -I "$GATE_LIB/journal_verdict.py" "$unit"
}

# gate_count <verdict> <verdicts>: how many lines of <verdicts> are <verdict>.
gate_count() {
    printf '%s\n' "$2" | grep -c "^$1"$'\t' || true
}

# gate_lines <verdict> <verdicts>: those lines' messages, indented, for a failure report.
gate_lines() {
    printf '%s\n' "$2" | grep "^$1"$'\t' | cut -f2- | sed 's/^/      /' || true
}

# gate_pin <unit>...: keep the units loaded (Manager.RefUnit from a background process)
# until gate_unpin. Returns 1 if the pin couldn't be set up within 10 s.
gate_pin() {
    local waited=0
    GATE_PIN_FILE=$(mktemp)
    rm -f "$GATE_PIN_FILE"
    python3 -I "$GATE_LIB/pin_units.py" "$GATE_PIN_FILE" "$@" &
    GATE_PIN_PID=$!
    while [ ! -s "$GATE_PIN_FILE" ]; do
        if [ "$waited" -ge 100 ] || ! kill -0 "$GATE_PIN_PID" 2>/dev/null; then
            return 1
        fi
        sleep 0.1
        waited=$((waited + 1))
    done
}

# gate_unpin: drop the references. Never fails (it runs from EXIT traps).
gate_unpin() {
    if [ -n "$GATE_PIN_PID" ]; then
        kill "$GATE_PIN_PID" 2>/dev/null || true
        wait "$GATE_PIN_PID" 2>/dev/null || true
    fi
    rm -f "${GATE_PIN_FILE:-}"
    GATE_PIN_PID=""
    return 0
}

# gate_pin_held <probe> <target> <cursor> <condition-timestamp-before>: the properties
# about to be read are those of the objects that ran this start: the probe's InvocationID
# is the one PID 1 logged for it after <cursor>, and the target's ConditionTimestamp
# advanced (a freshly loaded target reads 0).
gate_pin_held() {
    local probe=$1 target=$2 since=$3 before=$4 id logged after
    id=$(systemctl show -P InvocationID "$probe")
    logged=$(journalctl -q --no-pager -o verbose --output-fields=INVOCATION_ID \
        --after-cursor "$since" _PID=1 UNIT="$probe" | sed -n 's/^ *INVOCATION_ID=//p' | grep . | tail -n 1 || true)
    after=$(systemctl show -P ConditionTimestampMonotonic "$target")
    [ -n "$id" ] && [ "$id" = "$logged" ] && [ "$after" != 0 ] && [ "$after" != "$before" ]
}
