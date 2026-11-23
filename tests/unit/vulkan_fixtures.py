"""Loading the vulkan-1.3 fixtures in tests/fixtures/vulkan (task 0.2b). Not a test module.

Files group into scenarios: <origin>-<label>-gpu<n>-<driver>-<api>.json, one per Vulkan
device, plus <origin>-<label>-nodes.json. Origin is "real" (recorded with capture.py) or
"synthetic" (hand-written); README.md must agree for every file.
"""

import json
import os
import re

from tests import REPO_ROOT

FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "vulkan")
README = os.path.join(FIXTURE_DIR, "README.md")
FILE_PATTERN = re.compile(r"^(?P<origin>real|synthetic)-(?P<label>.+?)-(?:gpu(?P<index>\d+)-.+|nodes)\.json$")
LAVAPIPE_SCENARIO = "real-vmware-lavapipe"


def fixture_files():
    return sorted(name for name in os.listdir(FIXTURE_DIR) if name.endswith(".json"))


def readme_rows():
    """{file name: origin} from the README's Files table."""
    with open(README, "r", encoding="utf-8") as handle:
        text = handle.read()
    rows = {}
    for line in text.split("## Files", 1)[1].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells[1]
    return rows


def scenarios():
    """{"<origin>-<label>": {"devices": [(index, file)], "nodes": file or None}}."""
    found = {}
    for name in fixture_files():
        match = FILE_PATTERN.match(name)
        if not match:
            continue
        key = match.group("origin") + "-" + match.group("label")
        entry = found.setdefault(key, {"devices": [], "nodes": None})
        if match.group("index") is None:
            entry["nodes"] = name
        else:
            entry["devices"].append((int(match.group("index")), name))
    for entry in found.values():
        entry["devices"].sort()
    return found


def load_json(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scenario(key):
    """([device documents], {node: (major, minor)}) for scenario `key`."""
    entry = scenarios()[key]
    documents = [load_json(name) for _, name in entry["devices"]]
    nodes = {}
    if entry["nodes"] is not None:
        for node, info in load_json(entry["nodes"]).items():
            major, minor = info["dev"].split(":")
            nodes[node] = (int(major), int(minor))
    return documents, nodes


def is_real(key):
    """True only if the scenario is named real and README marks every one of its files real."""
    if not key.startswith("real-"):
        return False
    rows = readme_rows()
    entry = scenarios()[key]
    files = [name for _, name in entry["devices"]] + ([entry["nodes"]] if entry["nodes"] else [])
    return bool(files) and all(rows.get(name) == "real" and "synthetic" not in name for name in files)


def real_hardware_scenarios():
    """Real recordings from GPUs: every real scenario except the VMware lavapipe one."""
    return sorted(key for key in scenarios() if key != LAVAPIPE_SCENARIO and is_real(key))
