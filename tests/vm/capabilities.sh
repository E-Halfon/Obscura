#!/usr/bin/env bash
# Camera Obscura: capability framework VM tests (build-brief tasks 0.2 and 0.2b).
# Run inside a VMware Workstation VM booted from the built image, as root:
#   sudo tests/vm/capabilities.sh <test> [args]
# See tests/vm/README.md for VMware setup. Exit codes: 0 pass, 1 fail, 77 skipped.
#
#   state [--present a,b]  C-1: no failed units; each capability matches expectation
#                          (default: all absent; camera from ground truth); no capd
#                          warnings; DBus tree matches
#   virt                   C-2: virt present (needs nested virtualization; see README)
#   hotplug-camera [N]     C-3: connect/disconnect a USB webcam N times (default 10)
#   hotplug-battery [N]    C-4: load/unload test_power N times (skips if not shipped)
#   restart                C-5: restarting capd rebuilds the same state
#   semantics              C-6: has → 0/1 for declared names, 2 for an unknown one
#   no-fake                C-7: manual start/stop of capability targets is refused
#   bus-policy             C-9: an unprivileged user can read everything and is refused Properties.Set
#   mcelog                 C-8: mcelog runs only on Intel with /dev/mcelog; skipped, not failed, elsewhere
#   x86-64-v3              C-10: x86-64-v3 present exactly when /proc/cpuinfo has the v2+v3 flags (task 0.2b)
#   boot-order             C-11: capd starts only after the static targets' conditions ran
#   vulkan-lavapipe        C-12: vulkan-1.3 absent although lavapipe reports 1.3 (the key negative test)
#   vulkan-no-fake         C-13: vulkan-1.3 can't be started by hand or by a bogus probe
#   unplug                 C-14: unplugging the last device stops an upheld target (interactive, webcam)
#   all                    boot-order, state, restart, semantics, no-fake, bus-policy, mcelog,
#                          x86-64-v3, vulkan-lavapipe, vulkan-no-fake (non-interactive)

set -Eeuo pipefail
trap 'echo "ERROR: ${FUNCNAME[0]:-main} line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

readonly VOCABULARY_DIR=/usr/share/obscura/capabilities.d
readonly WAIT_SECONDS=2
HERE=$(cd "$(dirname "$0")" && pwd)
readonly HERE
# shellcheck source=SCRIPTDIR/../lib/stand-in.sh
. "$HERE/../lib/stand-in.sh"
# shellcheck source=SCRIPTDIR/../lib/vm-checks.sh
. "$HERE/../lib/vm-checks.sh"
# shellcheck source=SCRIPTDIR/../lib/gate-checks.sh
. "$HERE/../lib/gate-checks.sh"
SKIPPED=0

# Journal reads are scoped to this boot by its kernel boot ID, printed in the results.
BOOT_ID=$(tr -d - </proc/sys/kernel/random/boot_id)
readonly BOOT_ID
journal_this_boot() {
    journalctl -q --no-pager _BOOT_ID="$BOOT_ID" "$@"
}

# Each test runs in its own subshell (run_test), so failures are recorded in a file
# rather than a variable, which the subshell couldn't pass back.
RESULTS=$(mktemp)
trap 'rm -f "$RESULTS"' EXIT

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; echo "$*" >>"$RESULTS"; }
# Ends the current test (its subshell) as skipped; run_test counts exit 77 as a skip.
skip() { echo "SKIP: $*"; exit 77; }

declared() {
    local file
    for file in "$VOCABULARY_DIR"/*.toml; do
        basename "$file" .toml
    done
}

# kind_of <name>: static, device or probe, from the declaration.
kind_of() {
    sed -nE 's/^kind[[:space:]]*=[[:space:]]*"([a-z]+)".*/\1/p' "$VOCABULARY_DIR/$1.toml"
}

# capture_nodes: the /dev/video* nodes that are real cameras, one "<node> <sysfs path>"
# per line: ID_V4L_CAPABILITIES has :capture: and the device isn't under
# /sys/devices/virtual (v4l2loopback, vivid). C-1's ground truth for `camera`.
capture_nodes() {
    local node caps path
    for node in /dev/video*; do
        if [ ! -e "$node" ]; then
            continue
        fi
        caps=$(udevadm info --query=property --property=ID_V4L_CAPABILITIES --value --name="$node" 2>/dev/null || true)
        path=$(readlink -f "/sys/class/video4linux/${node#/dev/}" 2>/dev/null || true)
        if [[ "$caps" == *:capture:* ]] && [[ "$path" != /sys/devices/virtual/* ]]; then
            echo "$node $path"
        fi
    done
}

# Exit status of obscura-cap has, without tripping set -e.
has_status() {
    local status=0
    obscura-cap has "$1" >/dev/null 2>&1 || status=$?
    echo "$status"
}

# wait_until <0|1> <name> <seconds>: wait for has == expected. Prints elapsed ms.
wait_until() {
    local expected=$1 name=$2 limit_ms=$(($3 * 1000)) start now
    start=$(date +%s%3N)
    while true; do
        if [ "$(has_status "$name")" = "$expected" ]; then
            now=$(date +%s%3N)
            echo $((now - start))
            return 0
        fi
        now=$(date +%s%3N)
        if [ $((now - start)) -ge "$limit_ms" ]; then
            echo $((now - start))
            return 1
        fi
        sleep 0.1
    done
}

test_state() {
    local present_list="" name expected status units warnings objects cameras
    if [ "${1:-}" = "--present" ]; then
        present_list=",${2:-},"
    fi

    units=$(systemctl --failed --no-legend --plain | grep -v '^$' || true)
    if [ -z "$units" ]; then
        pass "no failed units"
    else
        fail "failed units:"$'\n'"$units"
    fi

    for name in $(declared); do
        expected=1
        if [[ "$present_list" == *",$name,"* ]]; then
            expected=0
        elif [ "$(kind_of "$name")" = static ]; then
            # A static capability is a fixed fact of this CPU, not baseline hardware the
            # tester controls; its own test (C-10, `x86-64-v3`) checks it. Here it only has
            # to be readable and not failed.
            status=$(has_status "$name")
            if [ "$status" = 0 ] || [ "$status" = 1 ]; then
                pass "$name (static) answers $status; checked by its own test"
            else
                fail "$name: obscura-cap has returned $status"
            fi
            if [ "$(systemctl show -P ActiveState "obscura-cap-$name.target")" = "failed" ]; then
                fail "obscura-cap-$name.target is failed (must be active or inactive)"
            fi
            continue
        fi
        if [ "$name" = camera ]; then
            # Ground truth, not the baseline: present iff a real capture node exists.
            cameras=$(capture_nodes)
            if [ -n "$cameras" ]; then
                expected=0
                echo "      camera ground truth: capture nodes outside /sys/devices/virtual:"
                printf '%s\n' "$cameras" | sed 's/^/        /'
            else
                expected=1
                echo "      camera ground truth: no /dev/video* node with :capture: outside /sys/devices/virtual"
            fi
            if [[ "$present_list" == *",camera,"* ]] && [ "$expected" = 1 ]; then
                fail "--present lists camera, but no real capture node exists"
            fi
        fi
        status=$(has_status "$name")
        if [ "$status" = "$expected" ]; then
            pass "$name is $([ "$expected" = 0 ] && echo present || echo absent)"
        else
            fail "$name: obscura-cap has returned $status, expected $expected"
        fi
        if [ "$(systemctl show -P LoadState "obscura-cap-$name.target")" != "loaded" ]; then
            fail "obscura-cap-$name.target is not loaded"
        fi
        if [ "$(systemctl show -P ActiveState "obscura-cap-$name.target")" = "failed" ]; then
            fail "obscura-cap-$name.target is failed (must be active or inactive)"
        fi
    done

    warnings=$(journal_this_boot -p warning SYSLOG_IDENTIFIER=obscura-capd || true)
    if [ -z "$warnings" ]; then
        pass "no capd warnings this boot"
    else
        fail "capd warnings this boot:"$'\n'"$warnings"
    fi

    objects=$(busctl tree --list org.obscura.Capabilities1 | grep -c '/cap/' || true)
    if [ "$objects" = "$(obscura-cap list | grep -c . || true)" ]; then
        pass "DBus exports exactly the present capabilities ($objects)"
    else
        fail "DBus has $objects capability objects; obscura-cap list disagrees"
    fi
}

test_virt() {
    if [ ! -e /dev/kvm ]; then
        skip "no /dev/kvm: enable 'Virtualize Intel VT-x/EPT or AMD-V/RVI' in VMware (blocked while Hyper-V is on in the host; see README)"
    fi
    if [ "$(has_status virt)" = 0 ]; then
        pass "virt present with /dev/kvm"
    else
        fail "/dev/kvm exists but virt is absent"
    fi
}

# hotplug_cycle <name> <connect command> <disconnect command> <cycles>
hotplug_cycle() {
    local name=$1 connect=$2 disconnect=$3 cycles=$4 watch_log watch_pid i elapsed added removed
    watch_log=$(mktemp)
    obscura-cap watch >"$watch_log" 2>&1 &
    watch_pid=$!
    sleep 1
    if [ "$(has_status "$name")" != 1 ]; then
        kill "$watch_pid" 2>/dev/null || true
        fail "$name must be absent before the test starts"
        return
    fi

    for i in $(seq 1 "$cycles"); do
        eval "$connect"
        if elapsed=$(wait_until 0 "$name" "$WAIT_SECONDS"); then
            pass "cycle $i: $name appeared in ${elapsed} ms"
        else
            fail "cycle $i: $name did not appear within ${WAIT_SECONDS}s"
        fi
        eval "$disconnect"
        if elapsed=$(wait_until 1 "$name" "$WAIT_SECONDS"); then
            pass "cycle $i: $name disappeared in ${elapsed} ms"
        else
            fail "cycle $i: $name did not disappear within ${WAIT_SECONDS}s"
        fi
    done

    sleep 1
    kill "$watch_pid" 2>/dev/null || true
    added=$(grep -cx "+$name" "$watch_log" || true)
    removed=$(grep -cx -- "-$name" "$watch_log" || true)
    if [ "$added" = "$cycles" ] && [ "$removed" = "$cycles" ]; then
        pass "exactly one Added and one Removed per cycle ($cycles each)"
    else
        fail "signals: $added Added, $removed Removed for $cycles cycles"
    fi
    rm -f "$watch_log"
    if [ "$(systemctl show -P ActiveState "obscura-cap-$name.target")" = "inactive" ]; then
        pass "target inactive after the last removal (no stuck state)"
    else
        fail "target not inactive after the last removal"
    fi
}

test_hotplug_camera() {
    local cycles=${1:-10}
    if [ ! -t 0 ]; then
        skip "interactive: needs you to connect and disconnect the webcam in VMware"
    fi
    echo "Disconnect the webcam now (VM > Removable Devices > <camera> > Disconnect), then press Enter."
    read -r _
    hotplug_cycle camera \
        'echo "Connect the webcam (VM > Removable Devices > <camera> > Connect), then press Enter."; read -r _' \
        'echo "Disconnect the webcam, then press Enter."; read -r _' \
        "$cycles"
}

test_hotplug_battery() {
    local cycles=${1:-10}
    if ! modinfo test_power >/dev/null 2>&1; then
        skip "test_power module not shipped by this kernel (Fedora sets CONFIG_TEST_POWER off); run C-4 on the laptop"
    fi
    if [ "$(has_status battery)" = 0 ]; then
        skip "a real battery is present (VMware 'Report battery information to guest'?); turn it off for this test"
    fi
    hotplug_cycle battery 'modprobe test_power' 'modprobe -r test_power' "$cycles"
}

test_restart() {
    local before after
    before=$(obscura-cap list)
    systemctl restart obscura-capd.service
    after=$(obscura-cap list)
    if [ "$before" = "$after" ]; then
        pass "state identical after restart: ${after:-(none)}"
    else
        fail "state changed across restart: '$before' -> '$after'"
    fi
    systemctl kill --signal=SIGKILL obscura-capd.service
    sleep 0.5
    after=$(obscura-cap list)
    if [ "$before" = "$after" ]; then
        pass "state identical after SIGKILL and re-activation"
    else
        fail "state changed after SIGKILL: '$before' -> '$after'"
    fi
}

test_semantics() {
    local name status output words
    for name in $(declared); do
        status=0
        output=$(obscura-cap has "$name" 2>/dev/null) || status=$?
        words="$status:$output"
        if [ "$words" = "0:present" ] || [ "$words" = "1:absent" ]; then
            pass "has $name -> $output ($status)"
        else
            fail "has $name -> exit $status, printed '$output' (declared names answer present/0 or absent/1)"
        fi
    done
    status=0
    output=$(obscura-cap has not-a-capability 2>/dev/null) || status=$?
    if [ "$status" = 2 ] && [ -z "$output" ]; then
        pass "unknown name -> 2, nothing on stdout"
    else
        fail "unknown name -> exit $status, printed '$output'; expected 2 and nothing"
    fi
    status=$(has_status windows-apps)
    if [ "$status" = 2 ]; then
        pass "windows-apps is not a capability (pack readiness) -> 2"
    else
        fail "windows-apps -> $status, expected 2"
    fi
}

test_no_fake() {
    local name
    for name in $(declared); do
        if [ "$(has_status "$name")" = 1 ]; then
            if systemctl start "obscura-cap-$name.target" 2>/dev/null; then
                fail "manual start of obscura-cap-$name.target was allowed"
            else
                pass "manual start of $name refused"
            fi
        else
            if systemctl stop "obscura-cap-$name.target" 2>/dev/null; then
                fail "manual stop of obscura-cap-$name.target was allowed"
            else
                pass "manual stop of $name refused"
            fi
        fi
    done
}

test_bus_policy() {
    local user=nobody service=org.obscura.Capabilities1 path=/org/obscura/Capabilities1 output
    local -a call
    call=(runuser -u "$user" -- busctl --system call "$service" "$path")

    if output=$("${call[@]}" org.obscura.Capabilities1 List 2>&1); then
        pass "$user can call List"
    else
        fail "$user refused List: $output"
    fi
    if output=$("${call[@]}" org.obscura.Capabilities1 Has s battery 2>&1); then
        pass "$user can call Has"
    else
        fail "$user refused Has: $output"
    fi
    if output=$("${call[@]}" org.freedesktop.DBus.ObjectManager GetManagedObjects 2>&1); then
        pass "$user can call GetManagedObjects"
    else
        fail "$user refused GetManagedObjects: $output"
    fi
    if output=$("${call[@]}" org.freedesktop.DBus.Properties GetAll s org.obscura.Capabilities1 2>&1); then
        pass "$user can call Properties.GetAll"
    else
        fail "$user refused Properties.GetAll: $output"
    fi
    if output=$("${call[@]}" org.freedesktop.DBus.Properties Set ssv org.obscura.Capabilities1 ApiVersion i 2 2>&1); then
        fail "$user was allowed Properties.Set"
    elif [[ "$output" == *"ccess denied"* || "$output" == *"AccessDenied"* ]]; then
        pass "$user refused Properties.Set by bus policy"
    else
        fail "Properties.Set failed, but not with AccessDenied (policy not applied?): $output"
    fi
}

test_mcelog() {
    local result active
    if ! systemctl cat mcelog.service >/dev/null 2>&1; then
        skip "mcelog.service not in this image"
    fi
    result=$(systemctl show -P Result mcelog.service)
    active=$(systemctl show -P ActiveState mcelog.service)
    if [ "$active" = "failed" ]; then
        fail "mcelog failed (Result=$result)"
        return 0
    fi
    if grep -q "^vendor_id[[:space:]]*: GenuineIntel" /proc/cpuinfo && [ -e /dev/mcelog ]; then
        pass "Intel with /dev/mcelog: mcelog allowed to run (ActiveState=$active)"
    elif [ "$result" = "exec-condition" ]; then
        pass "mcelog skipped by ExecCondition, not failed"
    elif [ "$active" = "inactive" ] && [ "$result" = "success" ]; then
        skip "mcelog was never started this boot (not enabled?)"
    else
        fail "mcelog: Result=$result ActiveState=$active"
    fi
}

# --- Task 0.2b: x86-64-v3 and vulkan-1.3 -------------------------------------------------

readonly X86_TARGET=/usr/lib/systemd/system/obscura-cap-x86-64-v3.target
readonly VULKAN_TARGET=obscura-cap-vulkan-1.3.target
readonly VULKAN_PROBE=obscura-cap-vulkan-1.3-probe
readonly VULKAN_MARKERS=/run/obscura-cap/vulkan-1.3
# vulkan_never_active: this boot, the vulkan-1.3 target never became active and capd never
# announced it (task 0.2b gate). Primary proof: every start job of the target that PID 1
# logged this boot is the "skipped because of an unmet condition" one, never a real
# "Reached target" (tests/lib/gate-checks.sh; a skip carries the same MESSAGE_ID, so the
# text decides). At least one skip must be there, or nothing pulled the target in and the
# check proves nothing. ActiveEnterTimestamp is secondary: PID 1 may have unloaded the
# inactive target earlier this boot ("Collecting.", debug-level, so not visible here), and
# a reloaded target reads 0 whether or not it was ever active. A non-zero value still fails.
vulkan_never_active() {
    local verdicts reached skipped announced
    verdicts=$(gate_verdicts "$VULKAN_TARGET" _BOOT_ID="$BOOT_ID")
    gate_check_unknown "journal for $VULKAN_TARGET" "$verdicts"
    reached=$(gate_count reached "$verdicts")
    skipped=$(gate_count skipped "$verdicts")
    if [ "$reached" = 0 ]; then
        pass "journal (boot $BOOT_ID): no real 'Reached target $VULKAN_TARGET'"
    else
        fail "journal (boot $BOOT_ID): $reached real 'Reached target $VULKAN_TARGET':"
        gate_lines reached "$verdicts"
    fi
    if [ "$skipped" != 0 ]; then
        pass "journal (boot $BOOT_ID): $skipped start(s) of $VULKAN_TARGET, each skipped because of an unmet condition (the gate said no)"
    else
        fail "journal (boot $BOOT_ID): no start of $VULKAN_TARGET was logged, so nothing pulled it in and this check proves nothing (did udev start a probe?)"
    fi
    if [ "$(systemctl show -P ActiveEnterTimestampMonotonic "$VULKAN_TARGET")" = 0 ]; then
        echo "NOTE: secondary: $VULKAN_TARGET's ActiveEnterTimestamp is 0. Not proof on its own: the target may have been unloaded and reloaded this boot, which the default log level doesn't show"
    else
        fail "$VULKAN_TARGET entered active this boot at $(systemctl show -P ActiveEnterTimestamp "$VULKAN_TARGET")"
    fi
    announced=$(journal_this_boot -o short-precise SYSLOG_IDENTIFIER=obscura-capd OBSCURA_CAPABILITY=vulkan-1.3)
    if [[ "$announced" == *"capability present: vulkan-1.3"* ]]; then
        fail "capd announced Added(vulkan-1.3) this boot:"
        printf '%s\n' "$announced" | grep -F "capability present: vulkan-1.3" | sed 's/^/      /'
    else
        pass "capd never announced Added(vulkan-1.3) this boot"
    fi
}

# The /proc/cpuinfo spelling of a systemd ConditionCPUFeature= name; empty if the kernel
# hides the flag (osxsave).
cpuinfo_flag() {
    case "$1" in
        fma3) echo fma ;;
        osxsave) echo "" ;;
        *) echo "$1" ;;
    esac
}

# C-10: x86-64-v3 is present exactly when the CPU has the psABI v2+v3 flags.
test_x86_64_v3() {
    local flags feature shown expected=0 systemd_says cpu_says ldso status
    flags=" $(grep -m1 '^flags' /proc/cpuinfo | cut -d: -f2) "
    for feature in $(sed -nE 's/^[[:space:]]*ConditionCPUFeature[[:space:]]*=[[:space:]]*//p' "$X86_TARGET"); do
        shown=$(cpuinfo_flag "$feature")
        if [ -n "$shown" ] && [[ "$flags" != *" $shown "* ]]; then
            expected=1
        fi
        # Each condition must agree with the kernel's view of that flag (catches a
        # misspelled name, which systemd would quietly evaluate as false).
        systemd_says=0
        systemd-analyze condition "ConditionCPUFeature=$feature" >/dev/null 2>&1 || systemd_says=1
        if [ -n "$shown" ]; then
            cpu_says=1
            if [[ "$flags" == *" $shown "* ]]; then
                cpu_says=0
            fi
            if [ "$systemd_says" = "$cpu_says" ]; then
                pass "ConditionCPUFeature=$feature agrees with /proc/cpuinfo ($shown)"
            else
                fail "ConditionCPUFeature=$feature says $systemd_says, /proc/cpuinfo '$shown' says $cpu_says"
            fi
        elif [ "$systemd_says" != 0 ]; then
            expected=1
        fi
    done

    ldso=1
    if /lib64/ld-linux-x86-64.so.2 --help 2>/dev/null | grep -q 'x86-64-v3 (supported'; then
        ldso=0
    fi
    if [ "$ldso" = "$expected" ]; then
        pass "glibc agrees: x86-64-v3 $([ "$expected" = 0 ] && echo supported || echo not supported)"
    else
        fail "glibc says $ldso, the flags say $expected"
    fi

    status=$(has_status x86-64-v3)
    if [ "$status" = "$expected" ]; then
        pass "x86-64-v3 is $([ "$expected" = 0 ] && echo present || echo absent), as the CPU flags say"
    else
        fail "x86-64-v3: has returned $status, expected $expected"
    fi
    if [ "$(systemctl show -P ActiveState obscura-cap-x86-64-v3.target)" = failed ]; then
        fail "obscura-cap-x86-64-v3.target is failed"
    fi
    if [ "$expected" = 1 ] && [ "$(systemctl show -P ConditionResult obscura-cap-x86-64-v3.target)" != no ]; then
        fail "absent, but not because a condition failed"
    fi
}

# C-11: capd is ordered after the static targets, so it never reads one before its start
# job ran. Run it first after a fresh boot for the strongest check.
test_boot_order() {
    local condition_ts capd_ts
    if systemctl show -P After sysinit.target | tr ' ' '\n' | grep -qx obscura-cap-x86-64-v3.target; then
        pass "sysinit.target is ordered after obscura-cap-x86-64-v3.target"
    else
        fail "sysinit.target is not ordered after obscura-cap-x86-64-v3.target"
    fi
    if systemctl show -P After obscura-capd.service | tr ' ' '\n' | grep -qx obscura-cap-x86-64-v3.target; then
        pass "obscura-capd.service is ordered after obscura-cap-x86-64-v3.target"
    else
        fail "obscura-capd.service is not ordered after obscura-cap-x86-64-v3.target"
    fi
    obscura-cap list >/dev/null    # make sure capd has been activated
    condition_ts=$(systemctl show -P ConditionTimestampMonotonic obscura-cap-x86-64-v3.target)
    capd_ts=$(systemctl show -P ExecMainStartTimestampMonotonic obscura-capd.service)
    if [ "${condition_ts:-0}" -gt 0 ] && [ "${capd_ts:-0}" -gt "$condition_ts" ]; then
        pass "capd started (${capd_ts} µs) after the x86-64-v3 conditions were evaluated (${condition_ts} µs)"
    else
        fail "capd start ${capd_ts:-?} µs is not after the condition check ${condition_ts:-?} µs"
    fi
}

render_nodes() {
    local node
    for node in /sys/class/drm/renderD*; do
        if [ -e "$node" ]; then
            basename "$node"
        fi
    done
}

# C-12: the key negative test. lavapipe reports Vulkan 1.3 here, and it must not count.
test_vulkan_lavapipe() {
    local summary lavapipe nodes node unit active result units reason
    if ! command -v vulkaninfo >/dev/null; then
        fail "vulkaninfo missing: the image must ship vulkan-tools"
        return 0
    fi
    summary=$(vulkaninfo --summary 2>/dev/null || true)
    # Each GPU block lists apiVersion before deviceName; keep the llvmpipe ones.
    lavapipe=$(printf '%s\n' "$summary" | awk '
        /^GPU[0-9]+:/ { api = "" }
        /apiVersion/ { api = $NF }
        /deviceName/ && /llvmpipe/ { print api }')
    if [ -z "$lavapipe" ]; then
        skip "vulkaninfo lists no llvmpipe device, so this negative test would prove nothing"
    fi
    if ! printf '%s\n' "$lavapipe" | grep -Eq '^(1\.([3-9]|[1-9][0-9])|[2-9])'; then
        skip "llvmpipe reports $lavapipe, below 1.3, so this negative test would prove nothing"
    fi
    pass "precondition: llvmpipe reports Vulkan $(printf '%s' "$lavapipe" | head -1)"

    if [ "$(has_status vulkan-1.3)" = 1 ]; then
        pass "vulkan-1.3 is absent although lavapipe reports 1.3"
    else
        fail "vulkan-1.3 is present in the VM"
    fi
    if [ "$(systemctl show -P ActiveState "$VULKAN_TARGET")" = inactive ]; then
        pass "$VULKAN_TARGET is inactive"
    else
        fail "$VULKAN_TARGET is $(systemctl show -P ActiveState "$VULKAN_TARGET")"
    fi
    # Not even for an instant, and because the gate said no (at least one logged skip).
    vulkan_never_active
    units=$(systemctl --failed --no-legend --plain | grep -v '^$' || true)
    if [ -z "$units" ]; then
        pass "no failed units"
    else
        fail "failed units:"$'\n'"$units"
    fi

    nodes=$(render_nodes)
    for node in $nodes; do
        unit="$VULKAN_PROBE@$node.service"
        active=$(systemctl show -P ActiveState "$unit")
        result=$(systemctl show -P Result "$unit")
        if [ "$active" = inactive ] && [ "$result" = exec-condition ]; then
            pass "$unit ran and was skipped (inactive, Result=exec-condition)"
        else
            fail "$unit: ActiveState=$active Result=$result (expected inactive, exec-condition)"
        fi
        if [ -e "$VULKAN_MARKERS/$node" ]; then
            fail "$VULKAN_MARKERS/$node exists although the probe rejected $node"
        fi
        reason=$(journal_this_boot -o cat SYSLOG_IDENTIFIER=obscura-cap-vulkan-probe | grep -F "$node" | tail -n 1 || true)
        if [ -n "$reason" ]; then
            pass "the journal gives the reason for $node:"
            printf '      %s\n' "$reason"
        else
            fail "no probe journal entry for $node"
        fi
    done
    echo "Now record the fixture (outside the repo, as your normal user):"
    echo "  python3 tests/fixtures/vulkan/capture.py ~/vulkan-capture --label vmware-lavapipe"
    if [ -z "$nodes" ]; then
        skip "no DRM render node, so the probe never ran: turn on 'Accelerate 3D graphics' in VMware and rerun"
    fi
}

# C-13: vulkan-1.3 can't be faked, and no probe start ever makes the target active, even
# briefly (the gate: the probe is Before= the target, whose ConditionPathExistsGlob= needs
# an accept marker that only an accepting probe writes).
readonly NO_FAKE_ROUNDS=20
test_vulkan_no_fake() {
    local node round before unit watch_file probe_ts round_cursor verdicts held pins
    if systemctl start "$VULKAN_TARGET" 2>/dev/null; then
        fail "manual start of $VULKAN_TARGET was allowed"
    else
        pass "manual start of $VULKAN_TARGET refused"
    fi

    # Anything capd announces while the probes are restarted ends up here.
    watch_file=$(mktemp)
    obscura-cap watch >"$watch_file" 2>/dev/null &
    NO_FAKE_WATCH=$!
    NO_FAKE_WATCH_FILE=$watch_file
    trap cleanup_no_fake EXIT
    sleep 1

    # Keep the target and probes loaded during the restarts, so their properties are those
    # of the objects that ran (tests/lib/gate-checks.sh). Checked per round.
    pins="$VULKAN_TARGET"
    for node in $(render_nodes); do
        pins="$pins $VULKAN_PROBE@$node.service"
    done
    # shellcheck disable=SC2086  # one word per unit
    if ! gate_pin $pins; then
        fail "couldn't pin $pins, so the property checks below are skipped"
    fi

    for node in $(render_nodes); do
        unit="$VULKAN_PROBE@$node.service"
        held=0
        for round in $(seq 1 "$NO_FAKE_ROUNDS"); do
            before=$(systemctl show -P ConditionTimestampMonotonic "$VULKAN_TARGET")
            # Skipped starts count toward the default start limit (5 in 10 s), and a
            # start-limit-hit probe would stay failed; reset-failed resets the limiter.
            systemctl reset-failed "$unit" 2>/dev/null || true
            round_cursor=$(journalctl -n 1 --show-cursor -q --no-pager | sed -n 's/^-- cursor: //p')
            systemctl restart "$unit" || true
            # restart waits only for the probe's job; the target's job (pulled in by
            # Upholds=, ordered after the probe) may still be queued.
            if ! stand_in_wait_idle "$VULKAN_TARGET" 15; then
                fail "$node round $round: $VULKAN_TARGET still has a job after 15 s"
            fi
            # Primary: the journal of this start.
            verdicts=$(gate_verdicts "$VULKAN_TARGET" --after-cursor "$round_cursor")
            gate_check_unknown "journal for $VULKAN_TARGET" "$verdicts"
            if [ "$(gate_count reached "$verdicts")" != 0 ]; then
                fail "$node round $round: a real 'Reached target $VULKAN_TARGET':"
                gate_lines reached "$verdicts"
            fi
            if [ "$(gate_count skipped "$verdicts")" = 0 ]; then
                fail "$node round $round: no 'skipped because of an unmet condition' entry for $VULKAN_TARGET, so the gate wasn't evaluated and this round proves nothing"
            fi
            if [ -e "$VULKAN_MARKERS/$node" ]; then
                fail "$node round $round: the rejecting probe left $VULKAN_MARKERS/$node"
            fi
            # Secondary: properties, only if they belong to the objects that ran this start.
            if gate_pin_held "$unit" "$VULKAN_TARGET" "$round_cursor" "$before"; then
                held=$((held + 1))
                if [ "$(systemctl show -P ActiveState "$VULKAN_TARGET")" != inactive ] \
                    || [ "$(systemctl show -P ActiveEnterTimestampMonotonic "$VULKAN_TARGET")" != 0 ]; then
                    fail "$node round $round: $VULKAN_TARGET became active"
                fi
                if [ "$(systemctl show -P ConditionResult "$VULKAN_TARGET")" != no ]; then
                    fail "$node round $round: ConditionResult=$(systemctl show -P ConditionResult "$VULKAN_TARGET"), expected no"
                fi
                if [ "$(systemctl show -P Result "$unit")" != exec-condition ]; then
                    fail "$node round $round: $unit Result=$(systemctl show -P Result "$unit"), expected exec-condition"
                fi
            else
                fail "$node round $round: the pin didn't hold (InvocationID or ConditionTimestamp doesn't match this start), so the property checks were skipped"
            fi
        done
        pass "$NO_FAKE_ROUNDS restarts of $unit: each logged a skipped start of the target, no real 'Reached target'; pin held in $held/$NO_FAKE_ROUNDS rounds"
    done

    # A probe for a node that doesn't exist waits for its device and never runs. Its start
    # still queues a start of the target (Upholds=), which must wait behind it (Before=)
    # instead of starting at once: in the old design this left vulkan-1.3 active for an hour.
    unit="$VULKAN_PROBE@renderD999.service"
    round_cursor=$(journalctl -n 1 --show-cursor -q --no-pager | sed -n 's/^-- cursor: //p')
    systemctl start --no-block "$unit" 2>/dev/null || true
    sleep 2
    if [ -n "$(systemctl list-jobs --no-legend --plain "$VULKAN_TARGET")" ]; then
        pass "the target's start job waits behind $unit"
    else
        fail "no queued start job for $VULKAN_TARGET behind $unit (expected one, ordered after the probe)"
    fi
    probe_ts=$(systemctl show -P ExecMainStartTimestampMonotonic "$unit")
    systemctl stop "$unit" 2>/dev/null || true
    stand_in_wait_idle "$VULKAN_TARGET" 15 || fail "$VULKAN_TARGET still has a job 15 s after cancelling $unit"
    verdicts=$(gate_verdicts "$VULKAN_TARGET" --after-cursor "$round_cursor")
    gate_check_unknown "journal for $VULKAN_TARGET" "$verdicts"
    if [ "$(gate_count reached "$verdicts")" != 0 ]; then
        fail "a real 'Reached target $VULKAN_TARGET' after starting $unit:"
        gate_lines reached "$verdicts"
    elif [ "$probe_ts" = 0 ] && [ ! -e "$VULKAN_MARKERS/renderD999" ] \
        && [ "$(systemctl show -P ActiveState "$VULKAN_TARGET")" = inactive ]; then
        if [ "$(gate_count skipped "$verdicts")" != 0 ]; then
            pass "a probe for a nonexistent node never ran; the target's job ran after it and was skipped (unmet condition)"
        else
            pass "a probe for a nonexistent node never ran; the target's job was cancelled with it (no start logged)"
        fi
    else
        fail "$unit ran, left a marker, or $VULKAN_TARGET is $(systemctl show -P ActiveState "$VULKAN_TARGET")"
    fi

    sleep 1
    if ! kill -0 "$NO_FAKE_WATCH" 2>/dev/null; then
        fail "obscura-cap watch exited early, so it couldn't have seen an Added(vulkan-1.3)"
    elif grep -qx '+vulkan-1.3' "$watch_file"; then
        fail "capd announced Added(vulkan-1.3) while the probes were restarted"
    else
        pass "capd never announced Added(vulkan-1.3) during the restarts"
    fi
    vulkan_never_active
}

# EXIT trap of test_vulkan_no_fake's subshell. Never fails: a failing command in an EXIT
# trap would trip the inherited ERR trap and turn a pass into an abort.
cleanup_no_fake() {
    trap - ERR
    set +e
    local job
    kill "${NO_FAKE_WATCH:-}" 2>/dev/null
    rm -f "${NO_FAKE_WATCH_FILE:-}"
    gate_unpin
    systemctl stop "$VULKAN_PROBE@renderD999.service" 2>/dev/null
    # BindsTo= also queued a start of the nonexistent device; cancel it instead of letting
    # it time out after ~90 s.
    for job in $(systemctl list-jobs --no-legend --plain dev-dri-renderD999.device 2>/dev/null | awk '{print $1}'); do
        systemctl cancel "$job" 2>/dev/null
    done
    return 0
}

# C-14: unplugging the last qualifying device stops the capability, without a reboot. The
# VM has no qualifying GPU, so this builds a stand-in from the installed probe and target
# (tests/lib/stand-in.sh: only the names, the marker path, the detection command and the
# device change) and binds it to the passed-through webcam. BindsTo=, Upholds=, Before=,
# the marker, the gate and StopWhenUnneeded= are the real lines.
readonly UNPLUG_LABEL=unplug
readonly UNPLUG_TARGET=obscura-test-$UNPLUG_LABEL.target
readonly UNPLUG_PROBE=obscura-test-$UNPLUG_LABEL-probe
readonly UNPLUG_APPEAR_SECONDS=15

# video_device_units: the plugged dev-video*.device units, sorted. Both sides of the C-14
# comparison use this. It lists with --all (the form that showed dev-video1.device in the
# VM pass of 2026-11-24, where --type=device --state=plugged printed nothing) and keeps
# only active/plugged rows, so dead units left from an earlier connect don't count and
# the same node reappearing is new. Only capture nodes get a unit (TAGS=:systemd: from
# 70-obscura-cap-camera.rules); a webcam's metadata node and OBS's output node don't.
readonly VIDEO_UNITS_CMD="systemctl list-units --all --plain --no-legend 'dev-video*'"
video_device_units() {
    eval "$VIDEO_UNITS_CMD" | awk '$1 ~ /^dev-video[0-9]+\.device$/ && $3 == "active" && $4 == "plugged" {print $1}' | sort
}
test_unplug_mechanism() {
    local run=/run/systemd/system device elapsed=0 before after waited start stable_since now now_units
    if [ ! -t 0 ]; then
        skip "interactive: needs you to connect and disconnect the webcam in VMware"
    fi
    trap cleanup_unplug EXIT
    stand_in_write /usr/lib/systemd/system vulkan-1.3 "$UNPLUG_LABEL" /usr/bin/true dev "$run"
    if ! stand_in_check "$UNPLUG_LABEL" "$run"; then
        fail "the stand-in lost part of the real gate"
        return 0
    fi
    systemctl daemon-reload

    echo "Disconnect the webcam now (VM > Removable Devices > <camera> > Disconnect), then press Enter."
    read -r _
    # udev may still be removing the webcam's nodes: wait until the plugged set has been
    # the same for 2 s (at most UNPLUG_APPEAR_SECONDS), else a node that is still listed
    # and then comes back wouldn't count as new.
    before=$(video_device_units)
    start=$(date +%s%3N)
    stable_since=$start
    while true; do
        sleep 0.5
        now_units=$(video_device_units)
        now=$(date +%s%3N)
        if [ "$now_units" != "$before" ]; then
            before=$now_units
            stable_since=$now
        fi
        if [ $((now - stable_since)) -ge 2000 ] || [ $((now - start)) -ge $((UNPLUG_APPEAR_SECONDS * 1000)) ]; then
            break
        fi
    done
    echo "Connect the webcam (VM > Removable Devices > <camera> > Connect), then press Enter."
    read -r _
    # The C920 takes up to ~5 s after Connect; poll up to UNPLUG_APPEAR_SECONDS.
    start=$(date +%s%3N)
    while true; do
        after=$(video_device_units)
        device=$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | grep . | head -n 1 || true)
        waited=$(($(date +%s%3N) - start))
        if [ -n "$device" ] || [ "$waited" -ge $((UNPLUG_APPEAR_SECONDS * 1000)) ]; then
            break
        fi
        sleep 0.2
    done
    if [ -z "$device" ]; then
        fail "no new dev-video*.device appeared within $UNPLUG_APPEAR_SECONDS s of Connect (was the webcam still connected? see VMware's USB settings)"
        echo "      before Connect: $(printf '%s' "$before" | tr '\n' ' ')"
        echo "      after ${UNPLUG_APPEAR_SECONDS} s:  $(printf '%s' "$after" | tr '\n' ' ')"
        echo "      listing command: $VIDEO_UNITS_CMD | awk '\$1 ~ /^dev-video[0-9]+\\.device\$/ && \$3 == \"active\" && \$4 == \"plugged\"'"
        echo "      its raw output now:"
        eval "$VIDEO_UNITS_CMD" | sed 's/^/        /' || true
        echo "      capture nodes now (camera ground truth):"
        capture_nodes | sed 's/^/        /' || true
        return 0
    fi
    echo "      $device appeared ~$waited ms after Enter"
    device=${device#dev-}
    device=${device%.device}
    systemctl start "$UNPLUG_PROBE@$device.service"
    stand_in_wait_idle "$UNPLUG_TARGET" 10 || true
    if [ "$(systemctl show -P ActiveState "$UNPLUG_TARGET")" = active ] \
        && [ -e "/run/obscura-cap/test-$UNPLUG_LABEL/$device/accepted" ]; then
        pass "the accepting stand-in probe on $device wrote its marker and upholds the stand-in target"
    else
        fail "stand-in target $(systemctl show -P ActiveState "$UNPLUG_TARGET") with the device present"
        return 0
    fi

    echo "Disconnect the webcam, then press Enter."
    read -r _
    while [ "$(systemctl show -P ActiveState "$UNPLUG_TARGET")" != inactive ] && [ "$elapsed" -lt 50 ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
    if [ "$(systemctl show -P ActiveState "$UNPLUG_TARGET")" = inactive ]; then
        pass "unplugging the last device stopped the target in ~$((elapsed * 100)) ms, no reboot"
    else
        fail "the target is still $(systemctl show -P ActiveState "$UNPLUG_TARGET") 5 s after unplugging"
    fi
    if [ "$(systemctl show -P ActiveState "$UNPLUG_PROBE@$device.service")" = inactive ] \
        && [ ! -e "/run/obscura-cap/test-$UNPLUG_LABEL/$device" ]; then
        pass "the stand-in probe stopped with its device (BindsTo=) and its marker is gone"
    else
        fail "the stand-in probe is $(systemctl show -P ActiveState "$UNPLUG_PROBE@$device.service") or its marker remains"
    fi
    if [ -z "$(systemctl --failed --no-legend --plain | grep -v '^$' || true)" ]; then
        pass "no failed units"
    else
        fail "failed units after unplugging"
    fi
}

# EXIT trap of test_unplug_mechanism's subshell. The stand-in target refuses a manual stop
# (RefuseManualStop=, copied from the real one), so this stops the stand-in probes and lets
# StopWhenUnneeded= stop the target, waits for that (removing the unit file of an active
# unit would leave it "not-found, active"), then removes the files. Never fails: a failing
# command here tripped the inherited ERR trap ("run_test line 1: return 0") before.
cleanup_unplug() {
    trap - ERR
    set +e
    local waited=0
    systemctl stop "$UNPLUG_PROBE@*.service" >/dev/null 2>&1
    while [ "$(systemctl show -P ActiveState "$UNPLUG_TARGET" 2>/dev/null)" = active ] && [ "$waited" -lt 50 ]; do
        sleep 0.1
        waited=$((waited + 1))
    done
    rm -f "/run/systemd/system/$UNPLUG_PROBE@.service" "/run/systemd/system/$UNPLUG_TARGET"
    rm -rf "/run/obscura-cap/test-$UNPLUG_LABEL"
    systemctl daemon-reload >/dev/null 2>&1
    return 0
}

# run_test <function> [args]: runs one test in a subshell with set -e in force.
# Calling a function as `f || status=$?` would switch errexit off inside it, so a failing
# command (e.g. systemctl restart) would go unnoticed. Here errexit is turned off only in
# this parent, around a plain subshell, so it stays on inside the test: an unexpected
# failure aborts that test, the ERR trap says where, and it is counted as a failure.
run_test() {
    local status test_name=$1
    # The subshell's non-zero exit is expected here, so neither errexit nor the
    # top-level ERR trap should react to it in this parent.
    set +e
    trap - ERR
    (
        set -Eeuo pipefail
        trap 'echo "ERROR: ${test_name}: ${FUNCNAME[0]:-?} line ${LINENO}: ${BASH_COMMAND}" >&2' ERR
        "$@"
    )
    status=$?
    trap 'echo "ERROR: ${FUNCNAME[0]:-main} line ${LINENO}: ${BASH_COMMAND}" >&2' ERR
    set -e
    if [ "$status" = 77 ]; then
        SKIPPED=$((SKIPPED + 1))
    elif [ "$status" != 0 ]; then
        fail "$1 aborted with status $status (see ERROR above)"
    fi
}

main() {
    if [ "$(id -u)" != 0 ]; then
        echo "run as root (sudo)" >&2
        exit 1
    fi
    local test=${1:-all}
    shift || true
    warn_auto_update
    case "$test" in
        state) run_test test_state "$@" ;;
        virt) run_test test_virt ;;
        hotplug-camera) run_test test_hotplug_camera "$@" ;;
        hotplug-battery) run_test test_hotplug_battery "$@" ;;
        restart) run_test test_restart ;;
        semantics) run_test test_semantics ;;
        no-fake) run_test test_no_fake ;;
        bus-policy) run_test test_bus_policy ;;
        mcelog) run_test test_mcelog ;;
        x86-64-v3) run_test test_x86_64_v3 ;;
        boot-order) run_test test_boot_order ;;
        vulkan-lavapipe) run_test test_vulkan_lavapipe ;;
        vulkan-no-fake) run_test test_vulkan_no_fake ;;
        unplug) run_test test_unplug_mechanism ;;
        all)
            run_test test_boot_order
            run_test test_state "$@"
            run_test test_restart
            run_test test_semantics
            run_test test_no_fake
            run_test test_bus_policy
            run_test test_mcelog
            run_test test_x86_64_v3
            run_test test_vulkan_lavapipe
            run_test test_vulkan_no_fake
            ;;
        *) echo "unknown test: $test" >&2; exit 1 ;;
    esac
    local failures
    failures=$(wc -l <"$RESULTS")
    if [ "$failures" -gt 0 ]; then
        echo "$failures failure(s), $SKIPPED skipped"
        exit 1
    fi
    if [ "$SKIPPED" -gt 0 ] && [ "$test" != all ]; then
        exit 77
    fi
    echo "all checks passed ($SKIPPED skipped)"
}

main "$@"
