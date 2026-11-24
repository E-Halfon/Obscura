"""vulkan-1.3 probe for one DRM render node (build-brief task 0.2b).

Run by obscura-cap-vulkan-1.3-probe@<node>.service as its ExecCondition=:

    python3 -P -m obscura_capd.vulkan_probe renderD128

Exit 0: the node has a hardware-accelerated Vulkan 1.3 device (obscura_capd.vulkan_rule),
so the probe unit becomes active and upholds obscura-cap-vulkan-1.3.target.
Exit 1: it doesn't, or the probe couldn't tell. systemd then skips the unit (inactive,
not failed) and the capability stays absent. The reason is always logged.

Fails closed: a missing vulkaninfo, a failing `vulkaninfo --summary`, an unreadable
sysfs node or kernel driver, or a virtual GPU's kernel driver (vulkan_rule) means absent.
Each Vulkan device is judged on its own: a crash or signal, a non-zero exit, a timeout
(VULKANINFO_TIMEOUT per call) or unparseable or schema-wrong JSON for one device means
that device doesn't count, and the others are still judged. Past the overall DEADLINE no
further devices are read. Every reason is logged. It never exits 255, which systemd would
count as a failure.

It writes nothing: the unit's ExecStart= writes the accept marker after an exit 0.
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
from obscura_capd.vulkan_rule import (SchemaError, device_from_document, kernel_driver_reason, node_qualifies,
                                      parse_node_number)

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


class DeadlineExceeded(Absent):
    """The overall DEADLINE passed: no further devices are read."""


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


def kernel_driver(node):
    """The kernel driver bound to render node `node`'s device (DRIVER= in its sysfs uevent),
    or None if it can't be read."""
    try:
        path = os.path.join(sysfs_root(), node, "device", "uevent")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return None
        for line in lines:
            if line.startswith("DRIVER="):
                return line[len("DRIVER="):].strip() or None
        return None
    except Exception as error:
        report.failure("vulkan_probe.kernel_driver", error)
        raise


def environment():
    """The process environment without anything that changes which Vulkan drivers load."""
    try:
        cleaned = dict(os.environ)
        for name in CLEARED_ENVIRONMENT:
            cleaned.pop(name, None)
        cleaned["MESA_SHADER_CACHE_DISABLE"] = "true"
        cleaned["VK_LOADER_LAYERS_DISABLE"] = "~implicit~"
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
                raise DeadlineExceeded("probe deadline of " + str(DEADLINE) + " s exceeded")
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
    """The normalized Device for vulkaninfo device `index`. Raises Absent if this device
    can't be read; DeadlineExceeded if the overall deadline passed."""
    try:
        try:
            with tempfile.TemporaryDirectory(prefix="obscura-vulkan-probe-") as directory:
                stdout = runner.run(["--json=" + str(index), "-o", "device.json"], directory)
                path = os.path.join(directory, "device.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as handle:
                        text = handle.read()
                else:
                    text = stdout
        except (OSError, UnicodeDecodeError) as error:
            raise Absent("device " + str(index) + ": can't read vulkaninfo's output: " + str(error)) from error
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
        driver = kernel_driver(node)
        driver_reason = kernel_driver_reason(driver)
        runner = Runner(executable, started)
        devices = []
        unreadable = []
        with tempfile.TemporaryDirectory(prefix="obscura-vulkan-probe-") as directory:
            summary = runner.run(["--summary"], directory)
        indices = device_indices(summary)
        for position, index in enumerate(indices):
            try:
                devices.append(read_device(runner, index))
            except DeadlineExceeded as reason:
                skipped = ", ".join(str(i) for i in indices[position:])
                unreadable.append(str(reason) + "; devices not read: " + skipped)
                break
            except Absent as reason:
                unreadable.append(str(reason))
        for reason in unreadable:
            report.problem("vulkan-1.3", node + ": " + reason + " (that device doesn't count)", OBSCURA_NODE=node)

        accepted, reasons = node_qualifies(devices, number)
        reasons = reasons + [reason + " (doesn't count)" for reason in unreadable]
        if driver_reason is not None:
            # Judged after the Vulkan devices, so the log still says what each one was.
            report.notice("vulkan-1.3: " + node + " doesn't count: " + driver_reason + "; devices: "
                          + "; ".join(reasons), OBSCURA_NODE=node)
            return ABSENT
        if accepted is not None:
            report.notice("vulkan-1.3: " + node + " qualifies (kernel driver " + str(driver) + "): "
                          + "; ".join(reasons), OBSCURA_NODE=node, OBSCURA_DEVICE=accepted.name)
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
