# shellcheck shell=bash
# Camera Obscura: build a stand-in for a probed capability's units (task 0.2b). Sourced by
# tests/ci/upholds-gate.sh (GitHub runner) and tests/vm/capabilities.sh (C-14, VM).
#
# The stand-in is the real probe template and target, rewritten by sed. Only the names,
# the marker path, the detection command and (optionally) the device change. BindsTo=,
# Upholds=, Before=, RuntimeDirectory=, the marker-writing ExecStart=, StopWhenUnneeded=
# and the ConditionPathExistsGlob= gate stay the real lines, so the stand-in exercises the
# real mechanism.

# stand_in_write <unit-dir> <capability> <label> <exec-condition> <device> <out-dir>
#   unit-dir      where the real units are (repo files/.../system or /usr/lib/systemd/system)
#   capability    e.g. vulkan-1.3
#   label         stand-in name: units obscura-test-<label>-probe@.service and
#                 obscura-test-<label>.target, markers under /run/obscura-cap/test-<label>/
#   exec-condition  replacement ExecCondition= command (/usr/bin/true or /usr/bin/false)
#   device        "drop" to remove BindsTo=/After= on the device (no DRM node), or
#                 "dev" to bind to dev-%i.device instead of dev-dri-%i.device
#   out-dir       usually /run/systemd/system
stand_in_write() {
    local units=$1 capability=$2 label=$3 condition=$4 device=$5 out=$6
    local probe="obscura-cap-$capability-probe@.service" target="obscura-cap-$capability.target"
    local escaped=${capability//./\\.}
    local device_expr
    if [ "$device" = drop ]; then
        device_expr='/^BindsTo=dev-dri-%i\.device$/d; /^After=dev-dri-%i\.device$/d'
    else
        device_expr='s/dev-dri-%i\.device/dev-%i.device/g'
    fi
    sed -e "s/obscura-cap-$escaped\\.target/obscura-test-$label.target/g" \
        -e "s#obscura-cap/$escaped/#obscura-cap/test-$label/#g" \
        -e "s#^ExecCondition=.*#ExecCondition=$condition#" \
        -e "s/^Description=.*/Description=Obscura test stand-in probe ($label) for %i/" \
        -e '/^Before=multi-user\.target$/d' \
        -e "$device_expr" \
        "$units/$probe" >"$out/obscura-test-$label-probe@.service" || return 1
    sed -e "s#obscura-cap/$escaped/#obscura-cap/test-$label/#g" \
        -e "s/^Description=.*/Description=Obscura test stand-in capability ($label)/" \
        "$units/$target" >"$out/obscura-test-$label.target" || return 1
}

# stand_in_check <label> <out-dir>: the stand-in still carries the real gate. Prints what
# is missing and returns 1, so a change to the real units can't silently weaken the test.
stand_in_check() {
    local label=$1 out=$2 problems=0 line
    local probe="$out/obscura-test-$label-probe@.service" target="$out/obscura-test-$label.target"
    for line in "Upholds=obscura-test-$label.target" "Before=obscura-test-$label.target" \
        "RuntimeDirectory=obscura-cap/test-$label/%i" \
        "ExecStart=/usr/bin/touch /run/obscura-cap/test-$label/%i/accepted"; do
        grep -qxF "$line" "$probe" || { echo "stand-in probe lost: $line"; problems=1; }
    done
    for line in "StopWhenUnneeded=yes" "ConditionPathExistsGlob=/run/obscura-cap/test-$label/*/accepted"; do
        grep -qxF "$line" "$target" || { echo "stand-in target lost: $line"; problems=1; }
    done
    # Neither file may still point at the real target or the real markers.
    # Captured first: under pipefail, grep -q could SIGPIPE the writer and read as "clean".
    local leftovers
    leftovers=$(grep -hv '^#' "$probe" "$target" \
        | grep -E 'obscura-cap-[a-z0-9.-]+\.target|/run/obscura-cap/[a-z0-9.-]+/' \
        | grep -v "test-$label" || true)
    if [ -n "$leftovers" ]; then
        echo "stand-in still names a real capability target or marker path"
        problems=1
    fi
    return "$problems"
}

# stand_in_wait_idle <unit> [seconds]: wait until <unit> has no queued job.
stand_in_wait_idle() {
    local unit=$1 limit=$((${2:-10} * 10)) waited=0
    while [ -n "$(systemctl list-jobs --no-legend --plain "$unit" 2>/dev/null)" ]; do
        if [ "$waited" -ge "$limit" ]; then
            return 1
        fi
        sleep 0.1
        waited=$((waited + 1))
    done
}
