#!/usr/bin/env bash
# Camera Obscura: pack format VM tests (build-brief task 0.21, P-1..P-7).
# Run inside a VM booted from the built image, as your normal user (readiness is per user;
# nothing here needs root). Copy the whole tests/ directory into the VM first: the script
# uses tests/fixtures/. See tests/vm/README.md. Exit codes: 0 pass, 1 fail, 77 skipped.
#
#   factory        P-1: every factory manifest validates; pack-wine listed from the factory root
#   wine           P-2: pack-wine is Insufficient hardware on the VM (reasons depend on task 0.2b)
#   no-reqs        P-3: a fixture with no requirements is Ready
#   camera         P-4: camera fixture: Missing hardware, then Ready with a webcam (interactive)
#   files          P-5: user file absent / wrong dump / right dump
#   removed        P-6: a removed marker hides pack-wine; deleting it restores it
#   malformed      P-7: a malformed fixture is skipped with one problem, no traceback, no failed units
#   all            everything except camera (non-interactive)

set -Eeuo pipefail
trap 'echo "ERROR: ${FUNCNAME[0]:-main} line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

readonly HERE=$(cd "$(dirname "$0")" && pwd)
readonly FIXTURES=${OBSCURA_FIXTURES:-$HERE/../fixtures}
readonly FACTORY_ROOT=/usr/share/obscura/packs
readonly VOCABULARY_DIR=/usr/share/obscura/capabilities.d
readonly WAIT_SECONDS=10
SKIPPED=0

RESULTS=$(mktemp)
SCRATCH=$(mktemp -d)
trap 'rm -rf "$RESULTS" "$SCRATCH"' EXIT

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; echo "$*" >>"$RESULTS"; }
skip() { echo "SKIP: $*"; exit 77; }

# pack <args>: obscura-pack with a scratch home and installed root, so tests never touch
# the user's real files or /var/lib/obscura/packs.
pack() {
    obscura-pack --home "$SCRATCH/home" --installed-root "$SCRATCH/var" "$@"
}

# field <json> <pack> <python expression on r>: read one value from readiness --json.
field() {
    python3 -c 'import json, sys; r = json.loads(sys.argv[1])[sys.argv[2]]; print(eval(sys.argv[3]))' "$1" "$2" "$3"
}

state_of() {
    local name=$1
    shift
    local json
    json=$(pack "$@" readiness --json "$name" 2>/dev/null || true)
    field "$json" "$name" 'r["state"]'
}

codes_of() {
    local name=$1
    shift
    local json
    json=$(pack "$@" readiness --json "$name" 2>/dev/null || true)
    field "$json" "$name" '",".join(x["code"] for x in r["reasons"])'
}

expect_state() {
    local label=$1 expected=$2 actual=$3
    if [ "$actual" = "$expected" ]; then
        pass "$label: $actual"
    else
        fail "$label: expected $expected, got $actual"
    fi
}

test_factory() {
    local directory output
    for directory in "$FACTORY_ROOT"/*/; do
        if output=$(obscura-pack validate "$directory" 2>&1); then
            pass "$output"
        else
            fail "$output"
        fi
    done
    output=$(pack list)
    if printf '%s\n' "$output" | awk -F'\t' -v path="$FACTORY_ROOT/pack-wine" \
            '$1 == "pack-wine" && $3 == "factory" && $4 == path { found = 1 } END { exit !found }'; then
        pass "pack-wine listed from the factory root"
    else
        fail "pack-wine not listed from $FACTORY_ROOT:"$'\n'"$output"
    fi
}

test_wine() {
    local state codes
    state=$(state_of pack-wine)
    codes=$(codes_of pack-wine)
    expect_state "pack-wine" insufficient-hardware "$state"
    if [ ! -e "$VOCABULARY_DIR/x86-64-v3.toml" ]; then
        # Before task 0.2b: neither capability is declared.
        if [ "$codes" = "capability-unknown,capability-unknown" ]; then
            pass "pack-wine reasons (before 0.2b): $codes"
        else
            fail "pack-wine reasons (before 0.2b): expected capability-unknown twice, got $codes"
        fi
    else
        # After 0.2b: the VM has no hardware-accelerated Vulkan (lavapipe/virtual GPU excluded).
        if printf '%s' "$codes" | grep -q "capability-absent" && ! printf '%s' "$codes" | grep -q "capability-unknown"; then
            pass "pack-wine reasons (after 0.2b): $codes"
        else
            fail "pack-wine reasons (after 0.2b): expected vulkan-1.3 capability-absent, got $codes"
        fi
    fi
}

test_no_reqs() {
    expect_state "pack-fixture-none" ready "$(state_of pack-fixture-none --extra-root "$FIXTURES/packs")"
}

# wait_for_state <name> <state>: poll readiness until it matches or WAIT_SECONDS pass.
wait_for_state() {
    local name=$1 expected=$2 deadline=$((SECONDS + WAIT_SECONDS)) state
    while true; do
        state=$(state_of "$name" --extra-root "$FIXTURES/packs")
        if [ "$state" = "$expected" ] || [ "$SECONDS" -ge "$deadline" ]; then
            echo "$state"
            return 0
        fi
        sleep 0.5
    done
}

test_camera() {
    if [ ! -t 0 ]; then
        skip "P-4 is interactive (connect and disconnect a webcam); run it from a terminal"
    fi
    if obscura-cap has camera >/dev/null 2>&1; then
        skip "a camera is already present; disconnect it first (VM → Removable Devices)"
    fi
    expect_state "camera fixture, no webcam" missing-hardware "$(wait_for_state pack-fixture-camera missing-hardware)"
    read -r -p "Connect the webcam (VM → Removable Devices → webcam → Connect), then press Enter. "
    expect_state "camera fixture, webcam connected" ready "$(wait_for_state pack-fixture-camera ready)"
    read -r -p "Disconnect the webcam, then press Enter. "
    expect_state "camera fixture, webcam removed" missing-hardware "$(wait_for_state pack-fixture-camera missing-hardware)"
}

test_files() {
    local directory="$SCRATCH/home/Obscura/firmware/obscura-test" args=(--extra-root "$FIXTURES/packs")
    expect_state "files fixture, file absent" missing-files "$(state_of pack-fixture-files "${args[@]}")"
    expect_state "files fixture, absent reason" file-absent "$(codes_of pack-fixture-files "${args[@]}")"
    mkdir -p "$directory"
    printf 'not the right dump\n' >"$directory/test-dump.dat"
    expect_state "files fixture, wrong dump reason" file-wrong-dump "$(codes_of pack-fixture-files "${args[@]}")"
    printf 'obscura test file\n' >"$directory/test-dump.dat"
    expect_state "files fixture, right dump" ready "$(state_of pack-fixture-files "${args[@]}")"
}

test_removed() {
    mkdir -p "$SCRATCH/var/pack-wine"
    touch "$SCRATCH/var/pack-wine/removed"
    if pack list | grep -q "^pack-wine"; then
        fail "pack-wine still listed with a removed marker"
    else
        pass "removed marker hides pack-wine"
    fi
    rm "$SCRATCH/var/pack-wine/removed"
    if pack list | grep -q "^pack-wine"; then
        pass "pack-wine back after the marker is deleted"
    else
        fail "pack-wine not listed after deleting the marker"
    fi
}

test_malformed() {
    local errors count units
    errors=$(pack --extra-root "$FIXTURES/packs-malformed" list 2>&1 >/dev/null || true)
    count=$(printf '%s\n' "$errors" | grep -c "pack-fixture-broken" || true)
    if [ "$count" = 1 ]; then
        pass "malformed fixture reported once"
    else
        fail "malformed fixture reported $count times:"$'\n'"$errors"
    fi
    if printf '%s' "$errors" | grep -q "Traceback"; then
        fail "traceback printed for a malformed manifest"
    else
        pass "no traceback"
    fi
    units=$(systemctl --failed --no-legend --plain | grep -v '^$' || true)
    if [ -z "$units" ]; then
        pass "no failed units"
    else
        fail "failed units:"$'\n'"$units"
    fi
}

# run_test <function> [args]: one test in a subshell with errexit on (see capabilities.sh).
run_test() {
    local status test_name=$1
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
    if [ ! -d "$FIXTURES/packs" ]; then
        echo "fixtures not found at $FIXTURES (copy tests/ into the VM, or set OBSCURA_FIXTURES)" >&2
        exit 1
    fi
    local test=${1:-all}
    case "$test" in
        factory) run_test test_factory ;;
        wine) run_test test_wine ;;
        no-reqs) run_test test_no_reqs ;;
        camera) run_test test_camera ;;
        files) run_test test_files ;;
        removed) run_test test_removed ;;
        malformed) run_test test_malformed ;;
        all)
            run_test test_factory
            run_test test_wine
            run_test test_no_reqs
            run_test test_files
            run_test test_removed
            run_test test_malformed
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
