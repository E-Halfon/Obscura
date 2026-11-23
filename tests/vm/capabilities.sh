#!/usr/bin/env bash
# Camera Obscura: capability framework VM tests (build-brief task 0.2).
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
#   mcelog                 C-8: mcelog runs only on Intel with /dev/mcelog; skipped, not failed, elsewhere
#   all                    state, restart, semantics, no-fake, mcelog (non-interactive)

set -Eeuo pipefail
trap 'echo "ERROR: ${FUNCNAME[0]:-main} line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

readonly VOCABULARY_DIR=/usr/share/obscura/capabilities.d
readonly WAIT_SECONDS=2
FAILURES=0

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
# Tests print with skip, then `return 77`; run_test counts that as a skip, not a failure.
skip() { echo "SKIP: $*"; return 77; }

declared() {
    local file
    for file in "$VOCABULARY_DIR"/*.toml; do
        basename "$file" .toml
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
        return 77
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
        return 77
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
        return 77
    fi
    if [ "$(has_status battery)" = 0 ]; then
        skip "a real battery is present (VMware 'Report battery information to guest'?); turn it off for this test"
        return 77
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

test_mcelog() {
    local result active
    if ! systemctl cat mcelog.service >/dev/null 2>&1; then
        skip "mcelog.service not in this image"
        return 77
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
        return 77
    else
        fail "mcelog: Result=$result ActiveState=$active"
    fi
}

SKIPPED=0

# run_test <function> [args]: runs one test, counting a 77 return as a skip.
run_test() {
    local status=0
    "$@" || status=$?
    if [ "$status" = 77 ]; then
        SKIPPED=$((SKIPPED + 1))
    elif [ "$status" != 0 ]; then
        fail "$1 stopped with status $status"
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
        mcelog) run_test test_mcelog ;;
        all)
            run_test test_state "$@"
            run_test test_restart
            run_test test_semantics
            run_test test_no_fake
            run_test test_mcelog
            ;;
        *) echo "unknown test: $test" >&2; exit 1 ;;
    esac
    if [ "$FAILURES" -gt 0 ]; then
        echo "$FAILURES failure(s), $SKIPPED skipped"
        exit 1
    fi
    if [ "$SKIPPED" -gt 0 ] && [ "$test" != all ]; then
        exit 77
    fi
    echo "all checks passed ($SKIPPED skipped)"
}

main "$@"
