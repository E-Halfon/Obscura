#!/usr/bin/env python3
"""Record video4linux node fixtures for the camera capability rule (build-brief task 0.2c).

Run it as root on the machine to record (v4l_id has to open the nodes):

    sudo python3 capture.py /var/tmp/v4l-capture --label c920
    sudo python3 capture.py /var/tmp/v4l-capture --label loopback-streaming --action change --node /dev/video0

It writes, into <out-dir> (which must not be inside a git checkout), one file per node:
  real-<label>-<kernel>.json   e.g. real-c920-video1.json
  capture-info-<label>.json    tool, date, kernel, udev version, v4l2loopback version

Each node file holds what the camera rule reads, and nothing else:
  action      the udev action the scenario stands for: "add", or "change" for a node whose
              state changed after it appeared (a streaming v4l2loopback)
  devpath, kernel, subsystem
  properties  an allowlist of the node's udev properties (ALLOWED_PROPERTIES)
  fresh       what /usr/lib/udev/v4l_id prints for the node right now; an event sees this,
              because 60-persistent-v4l.rules imports it before our rule runs
  parents     the device and each parent device up to /sys/devices: kernel name, subsystem,
              bound driver, and an allowlist of attributes (ALLOWED_ATTRIBUTES)

Only allowlisted keys are written, so serial numbers (ID_SERIAL*, ATTRS{serial}) never are,
and the result is re-checked before anything is written. Review the files, copy the
real-*.json ones into tests/fixtures/v4l/, and add a README row for each (Origin: real).

Standard library only. Exit codes: 0 written, 1 failed (nothing written), 2 bad usage or
v4l_id missing. tests/lib/rule_crosscheck.py imports record_node() from here.
"""

import argparse
import datetime
import glob
import json
import os
import platform
import re
import subprocess
import sys

V4L_ID = "/usr/lib/udev/v4l_id"
TIMEOUT_SECONDS = 10
ALLOWED_PROPERTIES = (
    "ID_V4L_CAPABILITIES", "ID_V4L_PRODUCT", "ID_V4L_VERSION", "ID_V4L2LOOPBACK_CAPABILITIES",
    "SUBSYSTEM", "DEVPATH", "DEVNAME", "MAJOR", "MINOR",
    "ID_BUS", "ID_VENDOR_ID", "ID_MODEL_ID", "ID_USB_DRIVER", "ID_USB_INTERFACE_NUM",
)
ALLOWED_ATTRIBUTES = ("name", "index", "idVendor", "idProduct", "product", "manufacturer",
                      "bInterfaceClass", "bInterfaceSubClass", "bInterfaceNumber", "modalias")
FRESH_PROPERTIES = ("ID_V4L_CAPABILITIES", "ID_V4L_PRODUCT", "ID_V4L_VERSION")
FORBIDDEN = re.compile(r"serial|uuid", re.IGNORECASE)
SAFE_NAME = re.compile(r"[^a-z0-9.-]+")


class CaptureError(Exception):
    """An expected failure: reported in one line, and nothing is written."""


def fail(where, error):
    """Report an unexpected exception from `where` on stderr (CLAUDE.md: never silent)."""
    try:
        print("capture.py: failure in " + where + ": " + type(error).__name__ + ": " + str(error),
              file=sys.stderr, flush=True)
    except Exception:
        pass  # stderr itself is unusable: there is nowhere left to report


def safe_part(text):
    """A file-name-safe lowercase fragment."""
    try:
        cleaned = SAFE_NAME.sub("-", str(text).lower()).strip("-.")
        return cleaned or "unknown"
    except Exception as error:
        fail("safe_part", error)
        raise


def parse_properties(text, allowed):
    """{key: value} from KEY=VALUE lines, keeping only `allowed` keys."""
    try:
        found = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in allowed:
                found[key.strip()] = value.strip()
        return found
    except Exception as error:
        fail("parse_properties", error)
        raise


def run(command):
    """stdout of `command`; raises CaptureError on timeout or non-zero exit."""
    try:
        try:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                       timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise CaptureError(" ".join(command) + " timed out") from error
        except OSError as error:
            raise CaptureError(" ".join(command) + ": " + str(error)) from error
        if completed.returncode != 0:
            raise CaptureError(" ".join(command) + " exited " + str(completed.returncode) + ": "
                               + completed.stderr.strip()[-300:])
        return completed.stdout
    except CaptureError:
        raise
    except Exception as error:
        fail("run", error)
        raise


def read_text(path):
    """The stripped content of a sysfs file, or None if it can't be read."""
    try:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read().strip()
        except OSError:
            return None
    except Exception as error:
        fail("read_text", error)
        raise


def link_name(path):
    """The basename of a symlink's target, or None if `path` isn't a link."""
    try:
        if os.path.islink(path):
            return os.path.basename(os.path.realpath(path))
        return None
    except Exception as error:
        fail("link_name", error)
        raise


def parent_chain(syspath, sysfs_root="/sys"):
    """The device and every parent device up to /sys/devices, as udev walks them: a
    directory counts as a device only if it has a uevent file."""
    try:
        chain = []
        stop = os.path.join(os.path.realpath(sysfs_root), "devices")
        current = os.path.realpath(syspath)
        while current.startswith(stop + os.sep):
            if os.path.exists(os.path.join(current, "uevent")):
                attrs = {}
                for name in ALLOWED_ATTRIBUTES:
                    value = read_text(os.path.join(current, name))
                    if value is not None:
                        attrs[name] = value
                chain.append({
                    "kernel": os.path.basename(current),
                    "subsystem": link_name(os.path.join(current, "subsystem")),
                    "driver": link_name(os.path.join(current, "driver")),
                    "attrs": attrs,
                })
            current = os.path.dirname(current)
        return chain
    except Exception as error:
        fail("parent_chain", error)
        raise


def record_node(node, action="add", sysfs_root="/sys"):
    """The fixture record for one /dev/video* node (see the module docstring)."""
    try:
        kernel = os.path.basename(node)
        syspath = os.path.realpath(os.path.join(sysfs_root, "class", "video4linux", kernel))
        if not os.path.isdir(syspath):
            raise CaptureError(node + ": no " + syspath)
        devpath = syspath[len(os.path.realpath(sysfs_root)):]
        properties = parse_properties(run(["udevadm", "info", "--query=property", "--path=" + devpath]),
                                      ALLOWED_PROPERTIES)
        if not os.path.exists(V4L_ID):
            raise CaptureError(V4L_ID + " is missing")
        fresh = parse_properties(run([V4L_ID, "/dev/" + kernel]), FRESH_PROPERTIES)
        record = {
            "action": action,
            "devpath": devpath,
            "kernel": kernel,
            "subsystem": link_name(os.path.join(syspath, "subsystem")) or "video4linux",
            "properties": properties,
            "fresh": fresh,
            "parents": parent_chain(syspath, sysfs_root),
        }
        check_clean(record)
        return record
    except CaptureError:
        raise
    except Exception as error:
        fail("record_node", error)
        raise


def check_clean(value, path="$"):
    """Raise CaptureError if any key or attribute name looks identifying (belt and braces:
    only allowlisted keys are recorded in the first place)."""
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if FORBIDDEN.search(str(key)):
                    raise CaptureError("identifying key " + path + "." + str(key))
                check_clean(item, path + "." + str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                check_clean(item, path + "[" + str(index) + "]")
    except CaptureError:
        raise
    except Exception as error:
        fail("check_clean", error)
        raise


def inside_git_checkout(directory):
    """True if `directory` (existing or not) is inside a git work tree."""
    try:
        current = os.path.abspath(directory)
        while True:
            if os.path.exists(os.path.join(current, ".git")):
                return True
            parent = os.path.dirname(current)
            if parent == current:
                return False
            current = parent
    except Exception as error:
        fail("inside_git_checkout", error)
        raise


def video_nodes():
    """Every /dev/video* node, sorted by number."""
    try:
        nodes = glob.glob("/dev/video*")
        return sorted((n for n in nodes if re.fullmatch(r"/dev/video\d+", n)), key=lambda n: int(n[10:]))
    except Exception as error:
        fail("video_nodes", error)
        raise


def write_json(path, value):
    """Write `value` as indented JSON, refusing to overwrite."""
    try:
        with open(path, "x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
    except FileExistsError as error:
        raise CaptureError("refusing to overwrite " + path) from error
    except Exception as error:
        fail("write_json", error)
        raise


def capture(out_dir, label, action, nodes):
    """Record every node first, then write. Returns the written file names."""
    try:
        if "synthetic" in label.lower():
            raise CaptureError("the label must not contain 'synthetic'")
        if inside_git_checkout(out_dir):
            raise CaptureError(out_dir + " is inside a git checkout; choose a directory outside the repo")
        nodes = nodes or video_nodes()
        if not nodes:
            raise CaptureError("no /dev/video* nodes")
        outputs = {}
        for node in nodes:
            record = record_node(node, action)
            outputs["real-" + safe_part(label) + "-" + record["kernel"] + ".json"] = record
        loopback_version = read_text("/sys/module/v4l2loopback/version")
        info = {
            "tool": "tests/fixtures/v4l/capture.py",
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
            "kernel": platform.release(),
            "udev": run(["udevadm", "--version"]).strip(),
            "v4l2loopback": loopback_version,
            "v4l2loopback_exclusive_caps": read_text("/sys/module/v4l2loopback/parameters/exclusive_caps"),
            "label": label,
            "action": action,
        }
        info_name = "capture-info-" + safe_part(label) + ".json"
        os.makedirs(out_dir, exist_ok=True)
        for name, record in outputs.items():
            write_json(os.path.join(out_dir, name), record)
        write_json(os.path.join(out_dir, info_name), info)
        for name, record in outputs.items():
            drivers = [p["driver"] for p in record["parents"] if p["driver"]]
            print(name + ": " + record["devpath"] + " | db " + record["properties"].get("ID_V4L_CAPABILITIES", "-")
                  + " | fresh " + record["fresh"].get("ID_V4L_CAPABILITIES", "-")
                  + " | drivers " + (",".join(drivers) or "none"))
        return sorted(outputs) + [info_name]
    except CaptureError:
        raise
    except Exception as error:
        fail("capture", error)
        raise


def main(argv=None):
    try:
        parser = argparse.ArgumentParser(description="Record video4linux fixtures (task 0.2c).")
        parser.add_argument("out_dir", help="output directory, outside any git checkout")
        parser.add_argument("--label", required=True, help="scenario label, e.g. c920 or loopback-streaming")
        parser.add_argument("--action", choices=("add", "change"), default="add")
        parser.add_argument("--node", action="append", default=[], help="/dev/videoN (repeatable; default all)")
        arguments = parser.parse_args(argv)
        if not os.path.exists(V4L_ID):
            print("capture.py: " + V4L_ID + " not found", file=sys.stderr)
            return 2
        try:
            written = capture(arguments.out_dir, arguments.label, arguments.action, arguments.node)
        except CaptureError as error:
            print("capture.py: " + str(error) + " (nothing written)", file=sys.stderr)
            return 1
        print("wrote to " + os.path.abspath(arguments.out_dir) + ": " + " ".join(written))
        return 0
    except SystemExit:
        raise
    except Exception as error:
        fail("main", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
