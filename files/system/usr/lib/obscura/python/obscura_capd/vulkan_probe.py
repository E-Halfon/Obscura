"""vulkan-1.3 probe for one DRM render node (build-brief task 0.2b).

Run by obscura-cap-vulkan-1.3-probe@<node>.service as its ExecCondition=:

    python3 -P -m obscura_capd.vulkan_probe renderD128

Exit 0: the node has a hardware-accelerated Vulkan 1.3 device (obscura_capd.vulkan_rule),
so the probe unit becomes active and upholds obscura-cap-vulkan-1.3.target.
Exit 1: it doesn't, or the probe couldn't tell. systemd then skips the unit (inactive,
not failed) and the capability stays absent. The reason is always logged.

Fails closed: a missing vulkaninfo, a crash or signal, a non-zero exit, a timeout
(VULKANINFO_TIMEOUT per call, DEADLINE overall), unparseable or schema-wrong JSON, or an
unreadable sysfs node all mean absent. It never exits 255, which systemd would count as
a failure.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from obscura_capd import report
from obscura_capd.vulkan_rule import SchemaError, device_from_document, node_qualifies, parse_node_number

VULKANINFO_TIMEOUT = 10.0   # seconds per vulkaninfo call
DEADLINE = 45.0             # seconds for the whole probe; the unit's TimeoutStartSec is 90
SYSFS_DRM = "/sys/class/drm"
NODE_PATTERN = re.compile(r"^renderD[0-9]+$")
CLEARED_ENVIRONMENT = ("VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES",
                       "VK_INSTANCE_LAYERS", "VK_LAYER_PATH", "VK_ADD_LAYER_PATH",
                       "VK_LOADER_LAYERS_ENABLE", "MESA_VK_DEVICE_SELECT")

ACCEPT = 0
ABSENT = 1


class Absent(Exception):
    """An expected reason the capability can't be confirmed. Logged once, then exit 1."""


def sysfs_root():
    """/sys/class/drm, or OBSCURA_VULKAN_PROBE_SYSFS for tests."""
    try:
        return os.environ.get("OBSCURA_VULKAN_PROBE_SYSFS", SYSFS_DRM)
    except Exception as error:
        report.failure("vulkan_probe.sysfs_root", error)
        raise


def node_number(node):
    """(major, minor) of render node `node`, from sysfs."""
    try:
        if not NODE_PATTERN.match(node):
            raise Absent("not a render node name: " + repr(node))
        path = os.path.join(sysfs_root(), node, "dev")
        try:
            with open(path, "r", encoding="ascii") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            raise Absent("can't read " + path + ": " + str(error)) from error
        try:
            return parse_node_number(text)
        except SchemaError as error:
            raise Absent(path + ": " + str(error)) from error
    except Absent:
        raise
    except Exception as error:
        report.failure("vulkan_probe.node_number", error)
        raise


def environment():
    """The process environment without anything that changes which Vulkan drivers load."""
    try:
        cleaned = dict(os.environ)
        for name in CLEARED_ENVIRONMENT:
            cleaned.pop(name, None)
        cleaned["MESA_SHADER_CACHE_DISABLE"] = "true"
        return cleaned
    except Exception as error:
        report.failure("vulkan_probe.environment", error)
        raise


class Runner:
    """Runs vulkaninfo within the per-call timeout and the overall deadline."""

    def __init__(self, executable, started):
        try:
            self.executable = executable
            self.started = started
            self.env = environment()
        except Exception as error:
            report.failure("Runner.__init__", error)
            raise

    def run(self, arguments, directory):
        """stdout of `vulkaninfo <arguments>`. Raises Absent on any failure."""
        try:
            remaining = DEADLINE - (time.monotonic() - self.started)
            if remaining <= 0:
                raise Absent("probe deadline of " + str(DEADLINE) + " s exceeded")
            timeout = min(VULKANINFO_TIMEOUT, remaining)
            command = [self.executable] + arguments
            try:
                completed = subprocess.run(command, cwd=directory, env=self.env, stdin=subprocess.DEVNULL,
                                           capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise Absent("vulkaninfo " + " ".join(arguments) + " timed out after "
                             + ("%g" % timeout) + " s") from error
            except OSError as error:
                raise Absent("can't run vulkaninfo: " + str(error)) from error
            if completed.returncode < 0:
                raise Absent("vulkaninfo " + " ".join(arguments) + " was killed by signal "
                             + str(-completed.returncode))
            if completed.returncode != 0:
                raise Absent("vulkaninfo " + " ".join(arguments) + " exited " + str(completed.returncode)
                             + ((": " + completed.stderr.strip()[-300:]) if completed.stderr.strip() else ""))
            return completed.stdout
        except Absent:
            raise
        except Exception as error:
            report.failure("Runner.run", error)
            raise


def device_indices(summary):
    """Indices from `vulkaninfo --summary` ("GPU0:", "GPU1:", ...)."""
    try:
        indices = sorted({int(match) for match in re.findall(r"^\s*GPU(\d+):", summary, re.MULTILINE)})
        if not indices:
            raise Absent("vulkaninfo --summary lists no devices")
        return indices
    except Absent:
        raise
    except Exception as error:
        report.failure("vulkan_probe.device_indices", error)
        raise


def read_device(runner, index):
    """The normalized Device for vulkaninfo device `index`."""
    try:
        with tempfile.TemporaryDirectory(prefix="obscura-vulkan-probe-") as directory:
            stdout = runner.run(["--json=" + str(index), "-o", "device.json"], directory)
            path = os.path.join(directory, "device.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()
            else:
                text = stdout
        try:
            document = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise Absent("device " + str(index) + ": vulkaninfo output isn't JSON: " + str(error)) from error
        try:
            return device_from_document(document)
        except SchemaError as error:
            raise Absent("device " + str(index) + ": unexpected vulkaninfo JSON: " + str(error)) from error
    except Absent:
        raise
    except Exception as error:
        report.failure("vulkan_probe.read_device", error)
        raise


def probe(node):
    """ACCEPT or ABSENT for render node `node`, with every reason logged."""
    try:
        started = time.monotonic()
        number = node_number(node)
        executable = shutil.which("vulkaninfo")
        if executable is None:
            raise Absent("vulkaninfo not found (package vulkan-tools)")
        runner = Runner(executable, started)
        devices = []
        with tempfile.TemporaryDirectory(prefix="obscura-vulkan-probe-") as directory:
            summary = runner.run(["--summary"], directory)
        for index in device_indices(summary):
            devices.append(read_device(runner, index))

        accepted, reasons = node_qualifies(devices, number)
        if accepted is not None:
            report.notice("vulkan-1.3: " + node + " qualifies: " + "; ".join(reasons),
                          OBSCURA_NODE=node, OBSCURA_DEVICE=accepted.name)
            return ACCEPT
        report.notice("vulkan-1.3: " + node + " has no hardware-accelerated Vulkan 1.3 device: "
                      + "; ".join(reasons), OBSCURA_NODE=node)
        return ABSENT
    except Absent as reason:
        report.problem("vulkan-1.3", node + ": " + str(reason) + " (treated as absent)", OBSCURA_NODE=node)
        return ABSENT
    except Exception as error:
        report.failure("vulkan_probe.probe", error)
        return ABSENT


def main(argv=None):
    """Entry point. Always returns ACCEPT or ABSENT; never raises."""
    try:
        report.set_identifier("obscura-cap-vulkan-probe")
        arguments = sys.argv[1:] if argv is None else argv
        if len(arguments) != 1:
            report.problem("vulkan-1.3", "usage: vulkan_probe <renderDN> (treated as absent)")
            return ABSENT
        return probe(arguments[0])
    except BaseException as error:  # noqa: B902 - nothing may escape as exit 255 or a traceback
        try:
            report.failure("vulkan_probe.main", error)
        except BaseException:
            pass
        return ABSENT


if __name__ == "__main__":
    sys.exit(main())
