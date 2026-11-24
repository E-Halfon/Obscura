#!/usr/bin/env bash
# Camera Obscura: the probed-capability gate on a real systemd (task 0.2b). Run as root on
# the GitHub runner by capd-tests:  sudo tests/ci/upholds-gate.sh
#
# Upholds= pulls its target in like Wants= whenever the probe starts. Before the gate, that
# made vulkan-1.3 active in the VM although the probe rejected lavapipe. The gate: only an
# accepting probe writes /run/obscura-cap/<name>/<dev>/accepted, the probe is Before= the
# target, and the target has ConditionPathExistsGlob= on the markers.
#
# Stand-ins are built from the repo's real vulkan-1.3 units (tests/lib/stand-in.sh), with
# BindsTo= on the device dropped because the runner has no DRM node:
#   reject   ExecCondition=/usr/bin/false: 20 starts never make the target active, and every
#            start really evaluated the gate (ConditionTimestamp advanced, result no)
#   control  the same without the ConditionPathExistsGlob= line: the target DOES become
#            active (the old bug), which proves this check can see it on this systemd
#   accept   ExecCondition=/usr/bin/true: the marker is written, the target becomes active,
#            and stopping the probe stops it (StopWhenUnneeded) and removes the marker
#   spam     accepting, but with the marker removed and the target stopped by hand:
#            Upholds= retries must not busy-loop the journal
set -Eeuo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
units="$repo/files/system/usr/lib/systemd/system"
out=/run/systemd/system
started_unit=39f53479d3a045ac8e11786248231fbf   # SD_MESSAGE_UNIT_STARTED ("Reached target")
# shellcheck source=SCRIPTDIR/../lib/stand-in.sh
. "$repo/tests/lib/stand-in.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }

cleanup() {
    trap - ERR
    set +e
    local label
    for label in reject control accept spam; do
        systemctl stop "obscura-test-$label-probe@x.service" >/dev/null 2>&1
    done
    for label in reject control accept spam; do
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
    printf '%s
' "$text" | sed -n 's/^-- cursor: //p'
}

# reached_target <cursor> <unit>: 0 if PID 1 logged starting <unit> after <cursor>, by
# MESSAGE_ID (primary) or by its "Reached target" text, which carries the unit name or,
# with StatusUnitFormat=description, only the Description. Output is captured before it
# is searched: under pipefail, grep -q could SIGPIPE the writer and read as "no match".
reached_target() {
    local cursor=$1 unit=$2 description structured text
    description=$(show "$unit" Description)
    structured=$(journalctl -q --no-pager --after-cursor "$cursor" MESSAGE_ID="$started_unit" UNIT="$unit")
    if [ -n "$structured" ]; then
        return 0
    fi
    text=$(journalctl -q --no-pager --after-cursor "$cursor" -o cat _PID=1)
    case "$text" in
        *"Reached target $unit"* | *"Reached target $description"*) return 0 ;;
    esac
    return 1
}

if [ "$(id -u)" != 0 ]; then
    echo "run as root (sudo)" >&2
    exit 1
fi
systemctl --version | head -n 1
# The probe template uses SupplementaryGroups=render; a missing group would be a loud 216/GROUP.
getent group render >/dev/null || groupadd --system render
cursor=$(journal_cursor)
if [ -z "$cursor" ]; then
    echo "no journal cursor: the journal checks would prove nothing" >&2
    exit 1
fi

for spec in "reject /usr/bin/false" "control /usr/bin/false" "accept /usr/bin/true" "spam /usr/bin/true"; do
    read -r label condition <<<"$spec"
    stand_in_write "$units" vulkan-1.3 "$label" "$condition" drop "$out"
    if ! stand_in_check "$label" "$out"; then
        fail "stand-in $label lost part of the real gate"
    fi
done
sed -i '/^ConditionPathExistsGlob=/d' "$out/obscura-test-control.target"
sed -i '/^RefuseManualStop=/d' "$out/obscura-test-spam.target"
systemctl daemon-reload

# --- reject: 20 starts, never active, gate evaluated every time
target=obscura-test-reject.target
probe=obscura-test-reject-probe@x.service
for round in $(seq 1 20); do
    before=$(show "$target" ConditionTimestampMonotonic)
    # Skipped starts count toward the default start limit (5 in 10 s); reset-failed also
    # resets the rate limiter, so round 6 doesn't end in start-limit-hit.
    systemctl reset-failed "$probe" 2>/dev/null || true
    systemctl restart "$probe" || true
    stand_in_wait_idle "$target" 10 || fail "round $round: $target still has a job after 10 s"
    after=$(show "$target" ConditionTimestampMonotonic)
    if [ "$after" = "$before" ] || [ "$after" = 0 ]; then
        fail "round $round: $target's condition wasn't evaluated (Upholds= didn't pull it in?), so this round proves nothing"
    fi
    if [ "$(show "$target" ConditionResult)" != no ]; then
        fail "round $round: ConditionResult=$(show "$target" ConditionResult), expected no"
    fi
    if [ "$(show "$target" ActiveEnterTimestampMonotonic)" != 0 ] || [ "$(show "$target" ActiveState)" != inactive ]; then
        fail "round $round: $target became active ($(show "$target" ActiveState))"
    fi
    if [ "$(show "$probe" Result)" != exec-condition ]; then
        fail "round $round: $probe Result=$(show "$probe" Result), expected exec-condition"
    fi
    if [ -e /run/obscura-cap/test-reject/x ]; then
        fail "round $round: the rejecting probe left its marker directory"
    fi
done
if reached_target "$cursor" "$target"; then
    fail "the journal has 'Reached target' for $target"
else
    pass "20 rejecting probe starts: $target never active, gate evaluated each time, no 'Reached target'"
fi

# --- control: without the condition the old bug shows (else this check proves nothing)
target=obscura-test-control.target
systemctl start obscura-test-control-probe@x.service || true
stand_in_wait_idle "$target" 10 || true
if [ "$(show "$target" ActiveEnterTimestampMonotonic)" != 0 ] && reached_target "$cursor" "$target"; then
    pass "control: without ConditionPathExistsGlob= a rejecting probe makes the target active (the old bug is visible here)"
else
    fail "control: the ungated target never became active, so this systemd can't show the old bug and the reject run proves nothing"
fi

# --- accept: marker, active; stop the probe: inactive, marker gone
target=obscura-test-accept.target
probe=obscura-test-accept-probe@x.service
systemctl start "$probe"
stand_in_wait_idle "$target" 10 || true
if [ "$(show "$target" ActiveState)" = active ] && [ -e /run/obscura-cap/test-accept/x/accepted ]; then
    pass "accept: marker /run/obscura-cap/test-accept/x/accepted written and $target active"
else
    fail "accept: $target is $(show "$target" ActiveState), marker $(ls -l /run/obscura-cap/test-accept/x 2>&1 || true)"
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
if [ "$(show "$target" ActiveState)" = active ]; then
    fail "spam: $target came back active without a marker"
fi

if [ "$failures" -gt 0 ]; then
    echo "$failures failure(s)" >&2
    exit 1
fi
echo "upholds gate: all checks passed"
