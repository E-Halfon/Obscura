#!/usr/bin/env python3
"""Record `vulkaninfo --json` fixtures for the vulkan-1.3 capability (build-brief task 0.2b).

Run it on real hardware, for example from a Fedora live USB:

    sudo dnf install -y vulkan-tools      # if vulkaninfo is missing
    python3 capture.py ~/vulkan-capture --label desktop-radv

It writes, into <out-dir> (which must not be inside a git checkout):
  real-<label>-gpu<n>-<driver>-<api>.json   one per Vulkan device, scrubbed
  nodes.json                                 render node -> major:minor, PCI address, driver
  capture-info.json                          versions, kernel, date, the keys that were scrubbed

Scrubbing: every key whose name contains "UUID" or "LUID" (any case, any depth) is removed,
plus deviceNodeMask, before anything is written. The result is then re-scanned, and nothing
is written if any such key survived. Review the files, then copy them into
tests/fixtures/vulkan/ and add a row for each to README.md (marked real).

Standard library only, so it runs on a live USB without the Obscura tree. Exit codes:
0 written, 1 failed (nothing written), 2 vulkaninfo missing or bad usage.
"""

import argparse
import datetime
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

TIMEOUT_SECONDS = 10      # per vulkaninfo call; the same budget as the capability probe
IDENTIFIER_PATTERN = re.compile(r"uuid|luid", re.IGNORECASE)
EXTRA_SCRUBBED_KEYS = frozenset({"deviceNodeMask"})
CLEARED_ENVIRONMENT = ("VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES",
                       "VK_INSTANCE_LAYERS", "VK_LAYER_PATH", "VK_ADD_LAYER_PATH",
                       "VK_LOADER_LAYERS_ENABLE", "MESA_VK_DEVICE_SELECT")
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


def is_scrubbed_key(key):
    """True for a key that identifies one physical device or driver build."""
    try:
        return isinstance(key, str) and (IDENTIFIER_PATTERN.search(key) is not None
                                         or key in EXTRA_SCRUBBED_KEYS)
    except Exception as error:
        fail("is_scrubbed_key", error)
        raise


def scrub(value, removed):
    """Return a copy of `value` without scrubbed keys, at any depth. Adds each removed key
    name to the set `removed`."""
    try:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if is_scrubbed_key(key):
                    removed.add(key)
                    continue
                result[key] = scrub(item, removed)
            return result
        if isinstance(value, list):
            return [scrub(item, removed) for item in value]
        return value
    except Exception as error:
        fail("scrub", error)
        raise


def remaining_identifiers(value, path="$"):
    """Paths of every scrubbed-type key still present, at any depth."""
    try:
        found = []
        if isinstance(value, dict):
            for key, item in value.items():
                if is_scrubbed_key(key):
                    found.append(path + "." + str(key))
                found.extend(remaining_identifiers(item, path + "." + str(key)))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found.extend(remaining_identifiers(item, path + "[" + str(index) + "]"))
        return found
    except Exception as error:
        fail("remaining_identifiers", error)
        raise


def scrub_document(document):
    """Scrub, then re-scan. Returns (clean document, sorted removed key names). Raises
    CaptureError if anything identifying survived, so the caller writes nothing."""
    try:
        removed = set()
        clean = scrub(document, removed)
        left = remaining_identifiers(clean)
        if left:
            raise CaptureError("identifiers survived the scrub: " + ", ".join(left))
        return clean, sorted(removed)
    except CaptureError:
        raise
    except Exception as error:
        fail("scrub_document", error)
        raise


def find_key(value, wanted):
    """The first value stored under key `wanted`, searching depth-first; None if absent."""
    try:
        if isinstance(value, dict):
            if wanted in value:
                return value[wanted]
            for item in value.values():
                found = find_key(item, wanted)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = find_key(item, wanted)
                if found is not None:
                    return found
        return None
    except Exception as error:
        fail("find_key", error)
        raise


def api_text(value):
    """'1.3' from a packed Vulkan version integer or a '1.3.280' string; 'unknown' otherwise."""
    try:
        if isinstance(value, bool):
            return "unknown"
        if isinstance(value, int):
            return str((value >> 22) & 0x7F) + "." + str((value >> 12) & 0x3FF)
        if isinstance(value, str):
            match = re.match(r"^\s*(\d+)\.(\d+)", value)
            if match:
                return match.group(1) + "." + match.group(2)
        return "unknown"
    except Exception as error:
        fail("api_text", error)
        raise


def safe_part(text):
    """A file-name-safe lowercase fragment."""
    try:
        cleaned = SAFE_NAME.sub("-", str(text).lower()).strip("-.")
        return cleaned or "unknown"
    except Exception as error:
        fail("safe_part", error)
        raise


def summarize(document):
    """(device name, device type, api, driver name) for messages and the file name."""
    try:
        properties = find_key(document, "VkPhysicalDeviceProperties") or {}
        driver = (find_key(document, "VkPhysicalDeviceDriverProperties")
                  or find_key(document, "VkPhysicalDeviceVulkan12Properties") or {})
        if not isinstance(properties, dict):
            properties = {}
        if not isinstance(driver, dict):
            driver = {}
        return (str(properties.get("deviceName", "unknown")),
                str(properties.get("deviceType", "unknown")),
                api_text(properties.get("apiVersion")),
                str(driver.get("driverName", "unknown")))
    except Exception as error:
        fail("summarize", error)
        raise


def output_name(label, index, document):
    """real-<label>-gpu<n>-<driver>-<api>.json. Never contains 'synthetic'."""
    try:
        _, _, api, driver = summarize(document)
        name = ("real-" + safe_part(label) + "-gpu" + str(int(index)) + "-" + safe_part(driver)
                + "-" + safe_part(api) + ".json")
        if "synthetic" in name:
            raise CaptureError("output name would contain 'synthetic': " + name)
        return name
    except CaptureError:
        raise
    except Exception as error:
        fail("output_name", error)
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


def clean_environment():
    """The environment for vulkaninfo, without anything that changes which drivers load."""
    try:
        environment = dict(os.environ)
        for name in CLEARED_ENVIRONMENT:
            environment.pop(name, None)
        return environment
    except Exception as error:
        fail("clean_environment", error)
        raise


def run_vulkaninfo(arguments, directory, environment):
    """Run vulkaninfo; return stdout. Raises CaptureError on timeout, signal, or non-zero exit."""
    try:
        try:
            completed = subprocess.run(["vulkaninfo"] + arguments, cwd=directory, env=environment,
                                       stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                       timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise CaptureError("vulkaninfo " + " ".join(arguments) + " timed out after "
                               + str(TIMEOUT_SECONDS) + " s") from error
        if completed.returncode != 0:
            raise CaptureError("vulkaninfo " + " ".join(arguments) + " exited "
                               + str(completed.returncode) + ": " + completed.stderr.strip()[-500:])
        return completed.stdout
    except CaptureError:
        raise
    except Exception as error:
        fail("run_vulkaninfo", error)
        raise


def device_indices(summary_text):
    """Device indices from `vulkaninfo --summary` ("GPU0:", "GPU1:", ...)."""
    try:
        indices = sorted({int(match) for match in re.findall(r"^\s*GPU(\d+):", summary_text, re.MULTILINE)})
        if not indices:
            raise CaptureError("vulkaninfo --summary lists no devices")
        return indices
    except CaptureError:
        raise
    except Exception as error:
        fail("device_indices", error)
        raise


def instance_version(summary_text):
    """The 'Vulkan Instance Version' line from the summary, or 'unknown'."""
    try:
        match = re.search(r"Vulkan Instance Version:\s*([0-9.]+)", summary_text)
        return match.group(1) if match else "unknown"
    except Exception as error:
        fail("instance_version", error)
        raise


def capture_device(index, environment):
    """The parsed JSON for device `index`. vulkaninfo writes it to a file (-o) or, in some
    versions, to stdout; both are accepted."""
    try:
        with tempfile.TemporaryDirectory(prefix="obscura-vk-") as directory:
            stdout = run_vulkaninfo(["--json=" + str(index), "-o", "device.json"], directory, environment)
            candidates = [os.path.join(directory, "device.json")]
            candidates += sorted(path for path in glob.glob(os.path.join(directory, "*.json"))
                                 if path not in candidates)
            for path in candidates:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as handle:
                        text = handle.read()
                    break
            else:
                text = stdout
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise CaptureError("device " + str(index) + ": vulkaninfo output isn't JSON: " + str(error)) from error
        if not isinstance(document, dict):
            raise CaptureError("device " + str(index) + ": vulkaninfo JSON isn't an object")
        return document
    except CaptureError:
        raise
    except Exception as error:
        fail("capture_device", error)
        raise


def render_nodes(sysfs_root="/sys/class/drm"):
    """{renderDN: {dev, pci, driver}} for every DRM render node."""
    try:
        nodes = {}
        for path in sorted(glob.glob(os.path.join(sysfs_root, "renderD*"))):
            name = os.path.basename(path)
            entry = {"dev": None, "pci": None, "driver": None}
            try:
                with open(os.path.join(path, "dev"), "r", encoding="ascii") as handle:
                    entry["dev"] = handle.read().strip()
            except OSError as error:
                print("capture.py: " + name + ": no dev file: " + str(error), file=sys.stderr)
            device = os.path.realpath(os.path.join(path, "device"))
            if re.match(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$", os.path.basename(device)):
                entry["pci"] = os.path.basename(device)
            driver = os.path.join(path, "device", "driver")
            if os.path.exists(driver):
                entry["driver"] = os.path.basename(os.path.realpath(driver))
            nodes[name] = entry
        return nodes
    except Exception as error:
        fail("render_nodes", error)
        raise


def write_json(path, value):
    """Write `value` as indented JSON, refusing to overwrite."""
    try:
        with open(path, "x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=False)
            handle.write("\n")
    except FileExistsError as error:
        raise CaptureError("refusing to overwrite " + path) from error
    except Exception as error:
        fail("write_json", error)
        raise


def capture(out_dir, label):
    """Capture every device, scrub everything, then write. Returns the written file names."""
    try:
        if "synthetic" in label.lower():
            raise CaptureError("the label must not contain 'synthetic'")
        if inside_git_checkout(out_dir):
            raise CaptureError(out_dir + " is inside a git checkout; choose a directory outside "
                               "the repo, review the files, then copy them in")
        environment = clean_environment()
        with tempfile.TemporaryDirectory(prefix="obscura-vk-") as directory:
            summary = run_vulkaninfo(["--summary"], directory, environment)

        # Capture and scrub everything first; nothing touches out_dir until all succeed.
        outputs = {}
        removed_keys = set()
        summaries = []
        for index in device_indices(summary):
            clean, removed = scrub_document(capture_device(index, environment))
            removed_keys.update(removed)
            name = output_name(label, index, clean)
            if name in outputs:
                raise CaptureError("two devices map to the same file name " + name)
            outputs[name] = clean
            summaries.append((index,) + summarize(clean))

        info = {
            "tool": "tests/fixtures/vulkan/capture.py",
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
            "kernel": platform.release(),
            "vulkan_instance_version": instance_version(summary),
            "drivers": sorted({driver for _, _, _, _, driver in summaries}),
            "scrubbed_keys": sorted(removed_keys),
        }
        nodes = render_nodes()
        clean_info, _ = scrub_document(info)
        clean_nodes, _ = scrub_document(nodes)

        os.makedirs(out_dir, exist_ok=True)
        for name, document in outputs.items():
            write_json(os.path.join(out_dir, name), document)
        write_json(os.path.join(out_dir, "nodes.json"), clean_nodes)
        write_json(os.path.join(out_dir, "capture-info.json"), clean_info)

        for index, device, kind, api, driver in summaries:
            print("GPU" + str(index) + ": " + device + " | " + kind + " | Vulkan " + api + " | " + driver)
        print("render nodes: " + (", ".join(name + "=" + str(entry["dev"]) + " " + str(entry["driver"])
                                            for name, entry in clean_nodes.items()) or "none"))
        print("scrubbed keys: " + (", ".join(sorted(removed_keys)) or "none"))
        return sorted(outputs) + ["nodes.json", "capture-info.json"]
    except CaptureError:
        raise
    except Exception as error:
        fail("capture", error)
        raise


def main(argv=None):
    try:
        parser = argparse.ArgumentParser(description="Record scrubbed vulkaninfo fixtures (task 0.2b).")
        parser.add_argument("out_dir", help="output directory, outside any git checkout")
        parser.add_argument("--label", default="capture",
                            help="machine label for the file names, e.g. desktop-radv")
        arguments = parser.parse_args(argv)

        if shutil.which("vulkaninfo") is None:
            print("capture.py: vulkaninfo not found. Install it with: sudo dnf install -y vulkan-tools",
                  file=sys.stderr)
            return 2
        try:
            written = capture(arguments.out_dir, arguments.label)
        except CaptureError as error:
            print("capture.py: " + str(error) + " (nothing written)", file=sys.stderr)
            return 1
        print("wrote to " + os.path.abspath(arguments.out_dir) + ":")
        for name in written:
            print("  " + name)
        print("Review them, copy them to tests/fixtures/vulkan/, and add a README row for each (real).")
        return 0
    except SystemExit:
        raise
    except Exception as error:
        fail("main", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
