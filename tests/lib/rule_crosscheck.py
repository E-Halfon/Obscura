"""Cross-check the udev rule evaluator (udev_rules.py) against real udev (task 0.2c).

    sudo python3 -I tests/lib/rule_crosscheck.py [--action change] [--rules FILE]
                                                [--unit UNIT] [/dev/videoN ...]

For each node (default: every /dev/video*), two verdicts on "does this event make PID 1
pull in UNIT" (default obscura-cap-camera.target):
- real:  `udevadm test --action=<action> <devpath>` on the running system, read from the
         properties and tags it prints (the systemd tag, and UNIT in SYSTEMD_WANTS);
- model: the node recorded now with tests/fixtures/v4l/capture.py, run through
         udev_rules.py on FILE (default the installed 70-obscura-cap-camera.rules).

Prints one tab-separated line per node:

    agree<TAB><node><TAB>yes|no<TAB><devpath> caps=<fresh ID_V4L_CAPABILITIES>
    DISAGREE<TAB><node><TAB>real=yes|no model=yes|no<TAB>...
    unknown<TAB><node><TAB><why>      udevadm test printed no property block we could read

Exit 0 when every node agrees, 1 when any disagrees or is unknown, 2 on bad usage.
`--dump` also prints udevadm test's stdout, for checking the parser against a new systemd.

udevadm test runs the rules without applying them (no database write, no RUN), but it does
run IMPORT programs such as v4l_id, so it needs root. Imports go by file path, so `-I` works.

Test helper (tests/ is exempt from the production try/except rule): failures raise.
"""

import argparse
import glob
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
DEFAULT_RULES = "/usr/lib/udev/rules.d/70-obscura-cap-camera.rules"
DEFAULT_UNIT = "obscura-cap-camera.target"
PROPERTY_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


udev_rules = load("obscura_udev_rules", os.path.join(HERE, "udev_rules.py"))
capture = load("obscura_v4l_capture", os.path.join(TESTS, "fixtures", "v4l", "capture.py"))


def parse_udevadm_test(stdout):
    """({property: value}, {tags}) from `udevadm test` stdout, or (None, None) if there is
    no property block. Handles both layouts: bare KEY=VALUE lines (255) and indented ones
    under a "Properties:" header with tags under "Tags:" (newer). For tags, CURRENT_TAGS
    wins over TAGS (TAGS is sticky across events), and a "Tags:" section over both."""
    properties = {}
    section = None
    section_tags = None
    for line in stdout.splitlines():
        # A header is an unindented "Word:" line; KEY=:a:b: lines also end in a colon.
        if "=" not in line and line.strip().endswith(":") and not line.startswith((" ", "\t")):
            section = line.strip().rstrip(":").lower()
            if section == "tags":
                section_tags = set()
            continue
        if section == "tags" and line.startswith(" ") and line.strip():
            section_tags.add(line.strip().lstrip(":").rstrip(":"))
            continue
        match = PROPERTY_LINE.match(line)
        if match:
            properties[match.group(1)] = match.group(2).strip()
    if "DEVPATH" not in properties:
        return None, None
    if section_tags is not None:
        tags = section_tags
    else:
        raw = properties.get("CURRENT_TAGS", properties.get("TAGS", ""))
        tags = {tag for tag in raw.split(":") if tag}
    return properties, tags


def real_verdict(devpath, action, unit, dump=False):
    """(True/False, detail) from udevadm test, or (None, why)."""
    completed = subprocess.run(["udevadm", "test", "--action=" + action, devpath],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    if dump:
        sys.stdout.write("--- udevadm test --action=" + action + " " + devpath + " (stdout) ---\n")
        sys.stdout.write(completed.stdout)
        sys.stdout.write("--- end ---\n")
    if completed.returncode != 0:
        return None, "udevadm test exited " + str(completed.returncode) + ": " + completed.stderr.strip()[-200:]
    properties, tags = parse_udevadm_test(completed.stdout)
    if properties is None:
        return None, "no property block in udevadm test output (rerun with --dump)"
    wanted = "systemd" in tags and unit in properties.get("SYSTEMD_WANTS", "").split()
    return wanted, "tags=" + ",".join(sorted(tags)) + " SYSTEMD_WANTS=" + properties.get("SYSTEMD_WANTS", "")


def model_verdict(node, action, rules_path, unit):
    record = capture.record_node(node, action)
    result = udev_rules.evaluate_file(rules_path, udev_rules.event_from_record(record, action))
    return udev_rules.wants(result, unit), record


def yes(value):
    return "yes" if value else "no"


def main(argv):
    parser = argparse.ArgumentParser(description="udev rule evaluator vs real udevadm test (task 0.2c)")
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
        model, record = model_verdict(node, arguments.action, arguments.rules, arguments.unit)
        real, detail = real_verdict(record["devpath"], arguments.action, arguments.unit, arguments.dump)
        context = record["devpath"] + " caps=" + record["fresh"].get("ID_V4L_CAPABILITIES", "")
        if real is None:
            sys.stdout.write("unknown\t" + node + "\t" + detail + "\t" + context + "\n")
            status = 1
        elif real == model:
            sys.stdout.write("agree\t" + node + "\t" + yes(real) + "\t" + context + "\n")
        else:
            sys.stdout.write("DISAGREE\t" + node + "\treal=" + yes(real) + " model=" + yes(model) + "\t"
                             + context + " real: " + detail + "\n")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
