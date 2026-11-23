"""The vulkan-1.3 acceptance rule (build-brief task 0.2b). Pure: no I/O, no subprocesses.

The capability means a hardware-accelerated Vulkan 1.3 device on an integrated or discrete
GPU. One render node qualifies only if some Vulkan device, as described by
`vulkaninfo --json=<n>`, meets all of these:

1. Its JSON has VkPhysicalDeviceDrmPropertiesEXT with hasRender true and the node's
   renderMajor:renderMinor. A device without the struct doesn't count, so a software
   device (lavapipe, which has no DRM node) can never be credited to a node.
2. deviceType is INTEGRATED_GPU or DISCRETE_GPU. CPU, VIRTUAL_GPU and OTHER never count.
3. The device's own apiVersion is at least 1.3. The instance version is not used.
4. It isn't a software rasterizer (llvmpipe/lavapipe, SwiftShader), judged by driverID,
   driverName and deviceName. Missing driver properties mean it doesn't count.

Anything missing or of the wrong type means "doesn't count", never an exception escaping
to the caller as a pass.
"""

import re
from dataclasses import dataclass

from obscura_capd import report

ACCEPTED_TYPES = ("INTEGRATED_GPU", "DISCRETE_GPU")
# VkPhysicalDeviceType values, for vulkaninfo versions that print numbers.
DEVICE_TYPES = {0: "OTHER", 1: "INTEGRATED_GPU", 2: "DISCRETE_GPU", 3: "VIRTUAL_GPU", 4: "CPU"}
# VkDriverId values of software rasterizers (and their names when printed as strings).
SOFTWARE_DRIVER_IDS = {10: "GOOGLE_SWIFTSHADER", 13: "MESA_LLVMPIPE"}
SOFTWARE_NAME = re.compile(r"llvmpipe|lavapipe|swiftshader", re.IGNORECASE)
MINIMUM_API = (1, 3)

DRIVER_STRUCTS = ("VkPhysicalDeviceDriverProperties", "VkPhysicalDeviceDriverPropertiesKHR",
                  "VkPhysicalDeviceVulkan12Properties")


class SchemaError(ValueError):
    """vulkaninfo's JSON doesn't have the expected shape. The probe treats it as absent."""


@dataclass(frozen=True)
class Device:
    """What the rule needs from one vulkaninfo device document."""
    name: str
    device_type: str           # INTEGRATED_GPU, DISCRETE_GPU, VIRTUAL_GPU, CPU, OTHER, or UNKNOWN
    api: tuple                 # (major, minor), or None if unreadable
    driver_id: object          # e.g. "MESA_RADV", or None if the driver properties are missing
    driver_name: object        # str or None
    drm: object                # (renderMajor, renderMinor) if hasRender, "no-render", or None if the struct is missing


def _occurrences(value, wanted, found):
    """Collect every value stored under key `wanted`, at any depth."""
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == wanted:
                    found.append(item)
                _occurrences(item, wanted, found)
        elif isinstance(value, list):
            for item in value:
                _occurrences(item, wanted, found)
        return found
    except Exception as error:
        report.failure("vulkan_rule._occurrences", error)
        raise


def _single_struct(document, name):
    """The one dict stored under `name`, or None if absent. Conflicting copies are a schema
    error: the rule would otherwise depend on which copy it happened to read."""
    try:
        found = _occurrences(document, name, [])
        if not found:
            return None
        first = found[0]
        if not isinstance(first, dict):
            raise SchemaError(name + " is not an object")
        for other in found[1:]:
            if other != first:
                raise SchemaError(name + " appears more than once with different contents")
        return first
    except SchemaError:
        raise
    except Exception as error:
        report.failure("vulkan_rule._single_struct", error)
        raise


def decode_api(value):
    """(major, minor) from a packed Vulkan version integer or a "1.3.289" string, else None."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            if value < 0:
                return None
            return ((value >> 22) & 0x7F, (value >> 12) & 0x3FF)
        if isinstance(value, str):
            match = re.match(r"^\s*(\d+)\.(\d+)(\.\d+)?\s*$", value)
            if match:
                return (int(match.group(1)), int(match.group(2)))
        return None
    except Exception as error:
        report.failure("vulkan_rule.decode_api", error)
        raise


def _enum_name(value, prefix, numbers):
    """'DISCRETE_GPU' from 'VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU' or 2; None if unreadable."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return numbers.get(value, "VALUE_" + str(value))
        if isinstance(value, str):
            text = value.strip()
            if text.startswith(prefix):
                text = text[len(prefix):]
            return text or None
        return None
    except Exception as error:
        report.failure("vulkan_rule._enum_name", error)
        raise


def device_from_document(document):
    """Normalize one `vulkaninfo --json=<n>` document. Raises SchemaError if it has no
    usable VkPhysicalDeviceProperties."""
    try:
        if not isinstance(document, dict):
            raise SchemaError("the document is not an object")
        properties = _single_struct(document, "VkPhysicalDeviceProperties")
        if properties is None:
            raise SchemaError("no VkPhysicalDeviceProperties")

        name = properties.get("deviceName")
        if not isinstance(name, str) or not name.strip():
            raise SchemaError("VkPhysicalDeviceProperties has no deviceName")
        device_type = _enum_name(properties.get("deviceType"), "VK_PHYSICAL_DEVICE_TYPE_", DEVICE_TYPES) or "UNKNOWN"
        api = decode_api(properties.get("apiVersion"))

        driver_id = None
        driver_name = None
        for struct_name in DRIVER_STRUCTS:
            driver = _single_struct(document, struct_name)
            if driver is not None and ("driverID" in driver or "driverName" in driver):
                driver_id = _enum_name(driver.get("driverID"), "VK_DRIVER_ID_", SOFTWARE_DRIVER_IDS)
                driver_name = driver.get("driverName") if isinstance(driver.get("driverName"), str) else None
                break

        drm = None
        drm_struct = _single_struct(document, "VkPhysicalDeviceDrmPropertiesEXT")
        if drm_struct is not None:
            major = drm_struct.get("renderMajor")
            minor = drm_struct.get("renderMinor")
            if drm_struct.get("hasRender") is True and isinstance(major, int) and isinstance(minor, int) \
                    and not isinstance(major, bool) and not isinstance(minor, bool):
                drm = (major, minor)
            else:
                drm = "no-render"

        return Device(name=name.strip(), device_type=device_type, api=api,
                      driver_id=driver_id, driver_name=driver_name, drm=drm)
    except SchemaError:
        raise
    except Exception as error:
        report.failure("vulkan_rule.device_from_document", error)
        raise


def judge(device, node):
    """(counts, reason) for `device` against render node number `node` = (major, minor)."""
    try:
        label = device.name
        if device.drm is None:
            return False, label + ": no VkPhysicalDeviceDrmPropertiesEXT"
        if device.drm == "no-render":
            return False, label + ": VkPhysicalDeviceDrmPropertiesEXT reports no render node"
        if tuple(device.drm) != tuple(node):
            return False, (label + ": render node " + "%d:%d" % tuple(device.drm)
                           + ", not this node " + "%d:%d" % tuple(node))
        if device.device_type not in ACCEPTED_TYPES:
            return False, label + ": device type " + device.device_type + " doesn't count"
        if device.api is None:
            return False, label + ": unreadable apiVersion"
        if tuple(device.api) < MINIMUM_API:
            return False, label + ": device apiVersion %d.%d is below 1.3" % tuple(device.api)
        if device.driver_id is None and device.driver_name is None:
            return False, label + ": no driver properties"
        if device.driver_id in SOFTWARE_DRIVER_IDS.values():
            return False, label + ": software driver " + str(device.driver_id)
        for text in (device.driver_name, device.name):
            if isinstance(text, str) and SOFTWARE_NAME.search(text):
                return False, label + ": software rasterizer (" + text + ")"
        return True, (label + ": " + device.device_type + ", Vulkan %d.%d" % tuple(device.api)
                      + ", driver " + str(device.driver_name or device.driver_id))
    except Exception as error:
        report.failure("vulkan_rule.judge", error)
        raise


def node_qualifies(devices, node):
    """(accepted Device or None, [reason per device]) for render node `node`."""
    try:
        reasons = []
        accepted = None
        for device in devices:
            counts, reason = judge(device, node)
            reasons.append(reason)
            if counts and accepted is None:
                accepted = device
        return accepted, reasons
    except Exception as error:
        report.failure("vulkan_rule.node_qualifies", error)
        raise


def parse_node_number(text):
    """(major, minor) from a sysfs `dev` file ("226:128\\n"). Raises SchemaError."""
    try:
        match = re.match(r"^\s*(\d+):(\d+)\s*$", text)
        if not match:
            raise SchemaError("unreadable device number " + repr(text))
        return (int(match.group(1)), int(match.group(2)))
    except SchemaError:
        raise
    except Exception as error:
        report.failure("vulkan_rule.parse_node_number", error)
        raise
