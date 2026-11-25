"""Cross-check the udev rule evaluator (udev_rules.py) against real udev (task 0.2c).

    sudo python3 -I tests/lib/rule_crosscheck.py [--action change] [--rules FILE]
                                                [--unit UNIT] [--dump] [/dev/videoN ...]

For each node (default: every /dev/video*), two verdicts on "does this event make PID 1
pull in UNIT" (default obscura-cap-camera.target):
- real:  deliver a real event, `udevadm trigger --action=<action> --settle <syspath>`, then
         read what systemd-udevd stored with `udevadm info`: the systemd tag in CURRENT_TAGS
         and UNIT in SYSTEMD_WANTS;
- model: the node recorded right after that event with tests/fixtures/v4l/capture.py, run
         through udev_rules.py on FILE (default the installed 70-obscura-cap-camera.rules).

Why not `udevadm test`: it doesn't run IMPORT{program}. On systemd 262 it logs "Running in
test mode, skipping execution of 'v4l_id /dev/video0'", so ID_V4L_CAPABILITIES is never set
and the camera rule can't match (VM recon of 2026-11-24, where it reported "no" for the
C920 that real udev had tagged). A triggered event runs the full rule set, IMPORTs
included. It is a real event: PID 1 acts on it as on any other, which is what the VM
tests want to observe anyway.

Prints one tab-separated line per node:

    agree<TAB><node><TAB>yes|no<TAB><devpath> caps=<ID_V4L_CAPABILITIES>
    DISAGREE<TAB><node><TAB>real=yes|no model=yes|no<TAB>...
    unknown<TAB><node><TAB><why>      the event couldn't be delivered or read back, or the
                                      node's capabilities changed between event and record

Exit 0 when every node agrees, 1 when any disagrees or is unknown, 2 on bad usage.
`--dump` also prints the `udevadm info` output read back.

Needs root (trigger, and v4l_id has to open the node). Imports go by file path, so `-I`
works.

Test helper (tests/ is exempt from the production try/except rule): failures raise.
"""

import argparse
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
DEFAULT_RULES = "/usr/lib/udev/rules.d/70-obscura-cap-camera.rules"
DEFAULT_UNIT = "obscura-cap-camera.target"
PROPERTY_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
TIMEOUT_SECONDS = 30


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


udev_rules = load("obscura_udev_rules", os.path.join(HERE, "udev_rules.py"))
capture = load("obscura_v4l_capture", os.path.join(TESTS, "fixtures", "v4l", "capture.py"))


def parse_db(stdout):
    """({property: value}, {current tags}) from `udevadm info --query=property` output, or
    (None, None) if it has no DEVPATH. Tags come from CURRENT_TAGS only: TAGS is sticky (a
    tag once set stays in TAGS after the rule stops matching, as the VM showed), and PID 1
    follows CURRENT_TAGS."""
    properties = {}
    for line in stdout.splitlines():
        match = PROPERTY_LINE.match(line.strip())
        if match:
            properties[match.group(1)] = match.group(2).strip()
    if "DEVPATH" not in properties:
        return None, None
    tags = {tag for tag in properties.get("CURRENT_TAGS", "").split(":") if tag}
    return properties, tags


def wanted(properties, tags, unit):
    return "systemd" in tags and unit in properties.get("SYSTEMD_WANTS", "").split()


def real_verdict(devpath, action, unit, dump=False):
    """(True/False, detail) from a real event and the database it left, or (None, why)."""
    trigger = subprocess.run(["udevadm", "trigger", "--action=" + action, "--settle", "/sys" + devpath],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    if trigger.returncode != 0:
        return None, "udevadm trigger exited " + str(trigger.returncode) + ": " + trigger.stderr.strip()[-200:]
    info = subprocess.run(["udevadm", "info", "--query=property", "--path=" + devpath],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    if dump:
        sys.stdout.write("--- udevadm info " + devpath + " after a " + action + " event ---\n")
        sys.stdout.write(info.stdout)
        sys.stdout.write("--- end ---\n")
    if info.returncode != 0:
        return None, "udevadm info exited " + str(info.returncode) + ": " + info.stderr.strip()[-200:]
    properties, tags = parse_db(info.stdout)
    if properties is None:
        return None, "no DEVPATH in udevadm info output (rerun with --dump)"
    return wanted(properties, tags, unit), ("current_tags=" + ",".join(sorted(tags))
                                            + " SYSTEMD_WANTS=" + properties.get("SYSTEMD_WANTS", ""))


def model_verdict(record, action, rules_path, unit):
    result = udev_rules.evaluate_file(rules_path, udev_rules.event_from_record(record, action))
    return udev_rules.wants(result, unit)


def yes(value):
    return "yes" if value else "no"


def main(argv):
    parser = argparse.ArgumentParser(description="udev rule evaluator vs a real udev event (task 0.2c)")
    parser.add_argument("nodes", nargs="*")
    parser.add_argument("--action", default="change", choices=("add", "change"))
    parser.add_argument("--rules", default=DEFAULT_RULES)
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--dump", action="store_true")
    arguments = parser.parse_args(argv)
    nodes = arguments.nodes or capture.video_nodes()
    if not nodes:
        sys.stdout.write("unknown\t-\tno /dev/video* nodes\n")
        return 1
    for override in ("/etc/udev/rules.d", "/run/udev/rules.d"):
        shadow = os.path.join(override, os.path.basename(arguments.rules))
        if os.path.exists(shadow):
            sys.stdout.write("unknown\t-\t" + shadow + " overrides " + arguments.rules + "\n")
            return 1
    status = 0
    for node in nodes:
        kernel = os.path.basename(node)
        devpath = os.path.realpath("/sys/class/video4linux/" + kernel)[len("/sys"):]
        real, detail = real_verdict(devpath, arguments.action, arguments.unit, arguments.dump)
        record = capture.record_node(node, arguments.action)
        db_caps = record["properties"].get("ID_V4L_CAPABILITIES", "")
        fresh_caps = record["fresh"].get("ID_V4L_CAPABILITIES", "")
        context = record["devpath"] + " caps=" + fresh_caps
        if real is None:
            sys.stdout.write("unknown\t" + node + "\t" + detail + "\t" + context + "\n")
            status = 1
            continue
        if db_caps != fresh_caps:
            sys.stdout.write("unknown\t" + node + "\tcapabilities changed after the event (db " + db_caps
                             + ", v4l_id now " + fresh_caps + ")\t" + context + "\n")
            status = 1
            continue
        model = model_verdict(record, arguments.action, arguments.rules, arguments.unit)
        if real == model:
            sys.stdout.write("agree\t" + node + "\t" + yes(real) + "\t" + context + "\n")
        else:
            sys.stdout.write("DISAGREE\t" + node + "\treal=" + yes(real) + " model=" + yes(model) + "\t"
                             + context + " real: " + detail + "\n")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
