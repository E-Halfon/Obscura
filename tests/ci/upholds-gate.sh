#!/usr/bin/env bash
# Camera Obscura: the probed-capability gate on a real systemd (task 0.2b). Run as root:
#   sudo tests/ci/upholds-gate.sh [--units <dir>] [--debug]
# --units   where the real probe template and target are (default: the repo's
#           files/system/usr/lib/systemd/system; the image job passes /usr/lib/systemd/system)
# --debug   also print PID 1's debug-level job log for reject round 1 and the control run.
#           Diagnostics only: no verdict depends on a debug-level message.
#
# Upholds= pulls its target in like Wants= whenever the probe starts. Before the gate, that
# made vulkan-1.3 active in the VM although the probe rejected lavapipe. The gate: only an
# accepting probe writes /run/obscura-cap/<name>/<dev>/accepted, the probe is Before= the
# target, and the target has ConditionPathExistsGlob= on the markers.
#
# Stand-ins are built from the real vulkan-1.3 units (tests/lib/stand-in.sh), with BindsTo=
# on the device dropped because there is no DRM node:
#   reject   ExecCondition=/usr/bin/false: each of 20 starts ends with the target's start
#            job logged as skipped (unmet condition) and never a real "Reached target"
#   control  the same without the ConditionPathExistsGlob= line: the journal DOES show a
#            real "Reached target" (the old bug), which proves this check can see it here
#   accept   ExecCondition=/usr/bin/true: "Reached target", the marker is written, and
#            stopping the probe stops the target (StopWhenUnneeded) and removes the marker
#   spam     accepting, but with the marker removed and the target stopped by hand:
#            Upholds= retries must not busy-loop the journal
#
# The journal verdict is the primary proof (tests/lib/gate-checks.sh). Properties
# (ActiveEnterTimestamp, ConditionResult, Result) are checked only for rounds where the
# pin held: without a reference PID 1 unloads the inactive stand-ins at once, and a fresh
# object reads as never active (CI diagnostic run on systemd 255, 2026-11-24).
set -Eeuo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
units="$repo/files/system/usr/lib/systemd/system"
debug=0
while [ $# -gt 0 ]; do
    case "$1" in
        --units)
            units=$2
            shift 2
            ;;
        --debug)
            debug=1
            shift
            ;;
        *)
            echo "usage: upholds-gate.sh [--units <dir>] [--debug]" >&2
            exit 2
            ;;
    esac
done
out=/run/systemd/system
# shellcheck source=SCRIPTDIR/../lib/stand-in.sh
. "$repo/tests/lib/stand-in.sh"
# shellcheck source=SCRIPTDIR/../lib/gate-checks.sh
. "$repo/tests/lib/gate-checks.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }

labels="reject control accept spam"
old_log_level=""
cleanup() {
    trap - ERR
    set +e
    local label
    gate_unpin
    if [ -n "$old_log_level" ]; then
        systemctl log-level "$old_log_level"
    fi
    for label in $labels; do
        systemctl stop "obscura-test-$label-probe@x.service" >/dev/null 2>&1
    done
    for label in $labels; do
        stand_in_wait_idle "obscura-test-$label.target" 10
        rm -f "$out/obscura-test-$label-probe@.service" "$out/obscura-test-$label.target"
        rm -rf "/run/obscura-cap/test-$label"
    done
    systemctl daemon-reload
}
trap cleanup EXIT

show() { systemctl show -P "$2" "$1"; }

# journal_cursor: the cursor of the newest entry; later queries use --after-cursor.
journal_cursor() {
    local text
    text=$(journalctl -n 1 --show-cursor --quiet --no-pager)
    printf '%s\n' "$text" | sed -n 's/^-- cursor: //p'
}

# --- Diagnostics: state and journal of the stand-in units, so a failure says why. They
# never change a pass or a fail.
dumped=" "
dump_units() {
    local unit
    for unit in "$@"; do
        echo "::group::diagnostics: $unit"
        systemctl show -p LoadState,ActiveState,SubState,Result,ConditionResult,ConditionTimestampMonotonic,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic,InvocationID,Upholds,UpheldBy,Before,After "$unit" || true
        systemctl status --no-pager --full "$unit" || true
        echo "--- journal (UNIT= or _SYSTEMD_UNIT=) since the start of this script"
        journalctl -q --no-pager -o verbose \
            --output-fields=MESSAGE,MESSAGE_ID,UNIT,JOB_TYPE,JOB_RESULT,INVOCATION_ID \
            --after-cursor "$cursor" UNIT="$unit" + _SYSTEMD_UNIT="$unit" || true
        echo "::endgroup::"
    done
}
# dump_once <key> <unit>...: dump_units the first time <key> is seen.
dump_once() {
    local key=$1
    shift
    case "$dumped" in
        *" $key "*) return 0 ;;
    esac
    dumped="$dumped$key "
    dump_units "$@"
}
# debug_begin / debug_end <cursor> <pattern>: with --debug, PID 1's job lines for a start.
debug_begin() {
    if [ "$debug" = 1 ]; then
        if [ -z "$old_log_level" ]; then
            old_log_level=$(systemctl log-level)
        fi
        systemctl log-level debug
    fi
}
debug_end() {
    local since=$1 pattern=$2 lines
    if [ "$debug" != 1 ]; then
        return 0
    fi
    systemctl log-level "$old_log_level"
    lines=$(journalctl -q --no-pager -o short-monotonic --after-cursor "$since" _PID=1 || true)
    echo "::group::diagnostics: PID 1 debug log for $pattern"
    printf '%s\n' "$lines" | grep -E "$pattern" | head -n 300 || true
    echo "::endgroup::"
}

if [ "$(id -u)" != 0 ]; then
    echo "run as root (sudo)" >&2
    exit 1
fi
systemctl --version | head -n 1
echo "units from $units"
# The probe template uses SupplementaryGroups=render; a missing group would be a loud 216/GROUP.
getent group render >/dev/null || groupadd --system render
cursor=$(journal_cursor)
if [ -z "$cursor" ]; then
    echo "no journal cursor: the journal checks would prove nothing" >&2
    exit 1
fi

for label in $labels; do
    case "$label" in
        reject | control) condition=/usr/bin/false ;;
        *) condition=/usr/bin/true ;;
    esac
    stand_in_write "$units" vulkan-1.3 "$label" "$condition" drop "$out"
    if ! stand_in_check "$label" "$out"; then
        fail "stand-in $label lost part of the real gate"
    fi
done
sed -i '/^ConditionPathExistsGlob=/d' "$out/obscura-test-control.target"
sed -i '/^RefuseManualStop=/d' "$out/obscura-test-spam.target"
systemctl daemon-reload

pinned=""
for label in $labels; do
    pinned="$pinned obscura-test-$label-probe@x.service obscura-test-$label.target"
done
# shellcheck disable=SC2086  # one word per unit
if gate_pin $pinned; then
    echo "pinned (Manager.RefUnit):$pinned"
else
    fail "couldn't pin the stand-in units, so no property check below is valid"
fi

# --- reject: 20 starts; each one's target job is logged as skipped, never reached
target=obscura-test-reject.target
probe=obscura-test-reject-probe@x.service
held=0
for round in $(seq 1 20); do
    before=$(show "$target" ConditionTimestampMonotonic)
    # Skipped starts count toward the default start limit (5 in 10 s); reset-failed also
    # resets the rate limiter, so round 6 doesn't end in start-limit-hit.
    systemctl reset-failed "$probe" 2>/dev/null || true
    round_cursor=$(journal_cursor)
    if [ "$round" = 1 ]; then
        debug_begin
    fi
    systemctl restart "$probe" || true
    stand_in_wait_idle "$target" 10 || fail "round $round: $target still has a job after 10 s"
    if [ "$round" = 1 ]; then
        debug_end "$round_cursor" 'obscura-test-reject'
    fi

    # Primary: the journal of this start.
    verdicts=$(gate_verdicts "$target" --after-cursor "$round_cursor")
    gate_check_unknown "journal for $target" "$verdicts"
    if [ "$(gate_count reached "$verdicts")" != 0 ]; then
        fail "round $round: the journal has a real 'Reached target' for $target:"
        gate_lines reached "$verdicts" >&2
        dump_once reached "$probe" "$target"
    fi
    if [ "$(gate_count skipped "$verdicts")" = 0 ]; then
        fail "round $round: no 'skipped because of an unmet condition' entry for $target, so the gate wasn't evaluated and this round proves nothing"
        dump_once not-evaluated "$probe" "$target"
    fi
    if [ -e /run/obscura-cap/test-reject/x ]; then
        fail "round $round: the rejecting probe left its marker directory"
    fi

    # Secondary: properties, only if they belong to the objects that ran this start.
    if gate_pin_held "$probe" "$target" "$round_cursor" "$before"; then
        held=$((held + 1))
        if [ "$(show "$target" ConditionResult)" != no ]; then
            fail "round $round: ConditionResult=$(show "$target" ConditionResult), expected no"
        fi
        if [ "$(show "$target" ActiveEnterTimestampMonotonic)" != 0 ] || [ "$(show "$target" ActiveState)" != inactive ]; then
            fail "round $round: $target became active ($(show "$target" ActiveState))"
        fi
        if [ "$(show "$probe" Result)" != exec-condition ]; then
            fail "round $round: $probe Result=$(show "$probe" Result), expected exec-condition"
        fi
    else
        fail "round $round: the pin didn't hold (InvocationID or ConditionTimestamp doesn't match this start), so the property checks were skipped"
        dump_once pin "$probe" "$target"
    fi
done
pass "20 rejecting probe starts: each logged '$target was skipped because of an unmet condition', no real 'Reached target'; pin held in $held/20 rounds"

# --- control: without the condition the old bug shows (else this check proves nothing)
target=obscura-test-control.target
probe=obscura-test-control-probe@x.service
control_cursor=$(journal_cursor)
debug_begin
systemctl start "$probe" || true
stand_in_wait_idle "$target" 10 || true
debug_end "$control_cursor" 'obscura-test-control'
verdicts=$(gate_verdicts "$target" --after-cursor "$control_cursor")
gate_check_unknown "journal for $target" "$verdicts"
if [ "$(gate_count reached "$verdicts")" != 0 ]; then
    pass "control: without ConditionPathExistsGlob= a rejecting probe makes the target active (the old bug is visible here):"
    gate_lines reached "$verdicts"
else
    fail "control: no real 'Reached target' for the ungated $target, so this check can't see the old bug and the reject run proves nothing"
    dump_units "$probe" "$target"
fi
if [ "$(show "$target" ActiveEnterTimestampMonotonic)" = 0 ]; then
    fail "control: $target's ActiveEnterTimestamp is 0 although it was reached: the pin didn't hold"
fi

# --- accept: reached, marker, active; stop the probe: inactive, marker gone
target=obscura-test-accept.target
probe=obscura-test-accept-probe@x.service
accept_cursor=$(journal_cursor)
systemctl start "$probe"
stand_in_wait_idle "$target" 10 || true
verdicts=$(gate_verdicts "$target" --after-cursor "$accept_cursor")
gate_check_unknown "journal for $target" "$verdicts"
if [ "$(gate_count reached "$verdicts")" != 0 ] && [ "$(show "$target" ActiveState)" = active ] \
    && [ -e /run/obscura-cap/test-accept/x/accepted ]; then
    pass "accept: 'Reached target', marker /run/obscura-cap/test-accept/x/accepted written and $target active"
else
    fail "accept: $target is $(show "$target" ActiveState), verdicts [$verdicts], marker $(ls -l /run/obscura-cap/test-accept/x 2>&1 || true)"
    dump_units "$probe" "$target"
fi
systemctl stop "$probe"
waited=0
while [ "$(show "$target" ActiveState)" != inactive ] && [ "$waited" -lt 50 ]; do
    sleep 0.1
    waited=$((waited + 1))
done
if [ "$(show "$target" ActiveState)" = inactive ] && [ ! -e /run/obscura-cap/test-accept/x ]; then
    pass "accept: stopping the last accepting probe stopped $target in ~$((waited * 100)) ms and removed its marker"
else
    fail "accept: after stopping the probe, $target is $(show "$target" ActiveState)"
fi

# --- spam: an active probe whose marker is gone must not busy-loop Upholds= restarts
target=obscura-test-spam.target
probe=obscura-test-spam-probe@x.service
systemctl start "$probe"
stand_in_wait_idle "$target" 10 || true
spam_cursor=$(journal_cursor)
rm -f /run/obscura-cap/test-spam/x/accepted
systemctl stop "$target" || true
sleep 10
spam_text=$(journalctl -q --no-pager --after-cursor "$spam_cursor" UNIT="$target")
lines=$(printf '%s' "$spam_text" | grep -c . || true)
echo "spam: $lines journal lines for $target in 10 s with an upholding probe and no marker"
if [ "$lines" -gt 1000 ]; then
    fail "spam: Upholds= retries busy-loop ($lines lines in 10 s)"
else
    pass "spam: retries are bounded ($lines lines in 10 s)"
fi
verdicts=$(gate_verdicts "$target" --after-cursor "$spam_cursor")
gate_check_unknown "journal for $target" "$verdicts"
if [ "$(gate_count reached "$verdicts")" != 0 ] || [ "$(show "$target" ActiveState)" = active ]; then
    fail "spam: $target came back active without a marker"
    gate_lines reached "$verdicts" >&2
fi

if [ "$failures" -gt 0 ]; then
    echo "$failures failure(s)" >&2
    exit 1
fi
echo "upholds gate: all checks passed"
