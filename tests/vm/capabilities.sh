#!/usr/bin/env bash
# Camera Obscura: capability framework VM tests (build-brief tasks 0.2 and 0.2b).
# Run inside a VMware Workstation VM booted from the built image, as root:
#   sudo tests/vm/capabilities.sh <test> [args]
# See tests/vm/README.md for VMware setup. Exit codes: 0 pass, 1 fail, 77 skipped.
#
#   state [--present a,b]  C-1: no failed units; each capability matches expectation
#                          (default: all absent); no capd warnings; DBus tree matches
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
SKIPPED=0

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
    local present_list="" name expected status units warnings objects
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

    warnings=$(journalctl -b -q -p warning SYSLOG_IDENTIFIER=obscura-capd --no-pager || true)
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
    local name status
    for name in $(declared); do
        status=$(has_status "$name")
        if [ "$status" = 0 ] || [ "$status" = 1 ]; then
            pass "has $name -> $status"
        else
            fail "has $name -> $status (declared names must answer 0 or 1)"
        fi
    done
    status=$(has_status not-a-capability)
    if [ "$status" = 2 ]; then
        pass "unknown name -> 2"
    else
        fail "unknown name -> $status, expected 2"
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
    local flags feature shown expected=0 line systemd_says cpu_says ldso status
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
    local summary lavapipe nodes node unit active result units
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
        if journalctl -b -q --no-pager SYSLOG_IDENTIFIER=obscura-cap-vulkan-probe | grep -q "$node"; then
            pass "the journal gives the reason for $node:"
            journalctl -b -q --no-pager -o cat SYSLOG_IDENTIFIER=obscura-cap-vulkan-probe | grep "$node" | tail -n 1 | sed 's/^/      /'
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

# C-13: vulkan-1.3 can't be faked.
test_vulkan_no_fake() {
    local node
    if systemctl start "$VULKAN_TARGET" 2>/dev/null; then
        fail "manual start of $VULKAN_TARGET was allowed"
    else
        pass "manual start of $VULKAN_TARGET refused"
    fi
    for node in $(render_nodes); do
        systemctl restart "$VULKAN_PROBE@$node.service" || true
        if [ "$(has_status vulkan-1.3)" = 1 ]; then
            pass "rerunning the probe for $node leaves vulkan-1.3 absent"
        else
            fail "rerunning the probe for $node made vulkan-1.3 present"
        fi
    done
    # A probe for a node that doesn't exist waits for its device and never runs.
    systemctl start --no-block "$VULKAN_PROBE@renderD999.service" 2>/dev/null || true
    sleep 2
    if [ "$(systemctl show -P ActiveState "$VULKAN_PROBE@renderD999.service")" != active ] \
        && [ "$(systemctl show -P ExecMainStartTimestampMonotonic "$VULKAN_PROBE@renderD999.service")" = 0 ] \
        && [ "$(has_status vulkan-1.3)" = 1 ]; then
        pass "a probe for a nonexistent node doesn't run"
    else
        fail "$VULKAN_PROBE@renderD999.service ran or vulkan-1.3 became present"
    fi
    systemctl stop "$VULKAN_PROBE@renderD999.service" 2>/dev/null || true
}

# C-14: unplugging the last qualifying device stops the capability, without a reboot. The
# VM has no qualifying GPU, so this builds a stand-in from the installed probe and target
# (only the device, the target name and the detection command are swapped) and binds it to
# the passed-through webcam. BindsTo=, Upholds= and StopWhenUnneeded= are the real lines.
test_unplug_mechanism() {
    local run=/run/systemd/system stand_in target_unit device elapsed=0 before after
    if [ ! -t 0 ]; then
        skip "interactive: needs you to connect and disconnect the webcam in VMware"
    fi
    stand_in="$run/obscura-test-upholds@.service"
    target_unit="$run/obscura-test-upheld.target"
    sed -e 's/dev-dri-%i\.device/dev-%i.device/g' \
        -e "s/$VULKAN_TARGET/obscura-test-upheld.target/g" \
        -e 's#^ExecCondition=.*#ExecCondition=/usr/bin/true#' \
        -e 's/^Description=.*/Description=Obscura C-14 stand-in probe for %i/' \
        -e '/^Before=multi-user.target/d' \
        "/usr/lib/systemd/system/$VULKAN_PROBE@.service" >"$stand_in"
    sed -e 's/^Description=.*/Description=Obscura C-14 stand-in capability/' \
        "/usr/lib/systemd/system/$VULKAN_TARGET" >"$target_unit"
    # run_test runs each test in its own subshell, so this cleans up whenever the test ends.
    trap 'systemctl stop "obscura-test-upholds@*.service" obscura-test-upheld.target 2>/dev/null; rm -f "$stand_in" "$target_unit"; systemctl daemon-reload' EXIT
    grep -qx 'BindsTo=dev-%i.device' "$stand_in" || { fail "stand-in lost BindsTo="; return 0; }
    grep -qx 'Upholds=obscura-test-upheld.target' "$stand_in" || { fail "stand-in lost Upholds="; return 0; }
    grep -qx 'StopWhenUnneeded=yes' "$target_unit" || { fail "stand-in target lost StopWhenUnneeded="; return 0; }
    systemctl daemon-reload

    echo "Disconnect the webcam now (VM > Removable Devices > <camera> > Disconnect), then press Enter."
    read -r _
    before=$(systemctl list-units --type=device --all --plain --no-legend 'dev-video*' | awk '{print $1}' | sort)
    echo "Connect the webcam (VM > Removable Devices > <camera> > Connect), then press Enter."
    read -r _
    sleep 1
    after=$(systemctl list-units --type=device --plain --no-legend 'dev-video*' | awk '{print $1}' | sort)
    device=$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | head -n 1)
    if [ -z "$device" ]; then
        fail "no new dev-video*.device appeared"
        return 0
    fi
    device=${device#dev-}
    device=${device%.device}
    systemctl start "obscura-test-upholds@$device.service"
    if [ "$(systemctl show -P ActiveState obscura-test-upheld.target)" = active ]; then
        pass "stand-in probe on $device upholds the stand-in target"
    else
        fail "stand-in target not active with the device present"
        return 0
    fi

    echo "Disconnect the webcam, then press Enter."
    read -r _
    while [ "$(systemctl show -P ActiveState obscura-test-upheld.target)" != inactive ] && [ "$elapsed" -lt 50 ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
    if [ "$(systemctl show -P ActiveState obscura-test-upheld.target)" = inactive ]; then
        pass "unplugging the last device stopped the target in ~$((elapsed * 100)) ms, no reboot"
    else
        fail "the target is still $(systemctl show -P ActiveState obscura-test-upheld.target) 5 s after unplugging"
    fi
    if [ "$(systemctl show -P ActiveState "obscura-test-upholds@$device.service")" = inactive ]; then
        pass "the stand-in probe stopped with its device (BindsTo=)"
    else
        fail "the stand-in probe is still $(systemctl show -P ActiveState "obscura-test-upholds@$device.service")"
    fi
    if [ -z "$(systemctl --failed --no-legend --plain | grep -v '^$' || true)" ]; then
        pass "no failed units"
    else
        fail "failed units after unplugging"
    fi
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
