"""The fixture capture script's scrubbing and safety checks (tests/fixtures/vulkan/capture.py)."""

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from tests import REPO_ROOT

CAPTURE_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "vulkan", "capture.py")


def load_capture():
    spec = importlib.util.spec_from_file_location("obscura_vulkan_capture", CAPTURE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load_capture()

# Shaped like vulkaninfo's profile JSON, with identifiers nested at several depths and in lists.
DOCUMENT = {
    "$schema": "https://schema.khronos.org/vulkan/profiles-0.8-latest.json",
    "capabilities": {
        "device": {
            "extensions": {"VK_EXT_physical_device_drm": 1},
            "properties": {
                "VkPhysicalDeviceProperties": {
                    "apiVersion": (1 << 22) | (3 << 12) | 289,
                    "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                    "deviceName": "AMD Radeon RX 7800 XT (RADV NAVI32)",
                    "pipelineCacheUUID": [1, 2, 3, 4],
                },
                "VkPhysicalDeviceIDProperties": {
                    "deviceUUID": [9, 9], "driverUUID": [8, 8],
                    "deviceLUID": [0], "deviceLUIDValid": False, "deviceNodeMask": 0,
                },
                "VkPhysicalDeviceShaderModuleIdentifierPropertiesEXT": {
                    "shaderModuleIdentifierAlgorithmUUID": [7, 7],
                },
                "VkPhysicalDeviceDriverProperties": {
                    "driverID": "VK_DRIVER_ID_MESA_RADV", "driverName": "radv",
                },
                "VkPhysicalDeviceDrmPropertiesEXT": {
                    "hasPrimary": True, "hasRender": True,
                    "primaryMajor": 226, "primaryMinor": 0, "renderMajor": 226, "renderMinor": 128,
                },
                "VkPhysicalDevicePCIBusInfoPropertiesEXT": {
                    "pciDomain": 0, "pciBus": 3, "pciDevice": 0, "pciFunction": 0,
                },
            },
            "queueFamiliesProperties": [{"vendorUUIDish": {"queueCount": 2}, "queueCount": 1},
                                        {"nested": [{"cacheUuid": [5]}], "queueCount": 1}],
        },
    },
}

IDENTIFIER_KEYS = ("pipelineCacheUUID", "deviceUUID", "driverUUID", "deviceLUID", "deviceLUIDValid",
                   "deviceNodeMask", "shaderModuleIdentifierAlgorithmUUID", "vendorUUIDish", "cacheUuid")


def all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_keys(item)


class ScrubTest(unittest.TestCase):
    def test_every_uuid_and_luid_key_goes_at_any_depth(self):
        clean, removed = capture.scrub_document(copy.deepcopy(DOCUMENT))
        keys = set(all_keys(clean))
        for key in IDENTIFIER_KEYS:
            with self.subTest(key):
                self.assertNotIn(key, keys)
                self.assertIn(key, removed)

    def test_pipeline_cache_uuid_does_not_abort_the_capture(self):
        """pipelineCacheUUID isn't on any fixed list; a list-based scrub plus the re-scan
        would abort every capture."""
        document = {"VkPhysicalDeviceProperties": {"deviceName": "x", "pipelineCacheUUID": [0] * 16}}
        clean, removed = capture.scrub_document(document)
        self.assertEqual(clean, {"VkPhysicalDeviceProperties": {"deviceName": "x"}})
        self.assertEqual(removed, ["pipelineCacheUUID"])

    def test_matching_data_is_kept(self):
        clean, _ = capture.scrub_document(copy.deepcopy(DOCUMENT))
        properties = clean["capabilities"]["device"]["properties"]
        self.assertEqual(properties["VkPhysicalDeviceDrmPropertiesEXT"]["renderMinor"], 128)
        self.assertEqual(properties["VkPhysicalDevicePCIBusInfoPropertiesEXT"]["pciBus"], 3)
        self.assertEqual(properties["VkPhysicalDeviceDriverProperties"]["driverName"], "radv")
        self.assertEqual(clean["capabilities"]["device"]["queueFamiliesProperties"],
                         [{"queueCount": 1}, {"nested": [{}], "queueCount": 1}])

    def test_input_is_not_modified(self):
        original = copy.deepcopy(DOCUMENT)
        capture.scrub_document(original)
        self.assertEqual(original, DOCUMENT)

    def test_rescan_catches_a_surviving_key(self):
        with mock.patch.object(capture, "scrub", side_effect=lambda value, removed: value):
            with self.assertRaises(capture.CaptureError) as caught:
                capture.scrub_document({"a": [{"b": {"driverUUID": [1]}}]})
        self.assertIn("$.a[0].b.driverUUID", str(caught.exception))


class NamingTest(unittest.TestCase):
    def test_output_name(self):
        clean, _ = capture.scrub_document(copy.deepcopy(DOCUMENT))
        self.assertEqual(capture.output_name("Desktop RADV", 0, clean), "real-desktop-radv-gpu0-radv-1.3.json")

    def test_names_never_say_synthetic(self):
        clean, _ = capture.scrub_document(copy.deepcopy(DOCUMENT))
        with self.assertRaises(capture.CaptureError):
            capture.output_name("synthetic", 0, clean)
        with self.assertRaises(capture.CaptureError):
            capture.capture(tempfile.gettempdir(), "my-synthetic-box")

    def test_api_text(self):
        self.assertEqual(capture.api_text((1 << 22) | (3 << 12)), "1.3")
        self.assertEqual(capture.api_text("1.2.199"), "1.2")
        self.assertEqual(capture.api_text(None), "unknown")
        self.assertEqual(capture.api_text(True), "unknown")

    def test_device_indices(self):
        summary = "Devices:\n========\nGPU0:\n\tapiVersion = 1.3.289\nGPU1:\n\tapiVersion = 1.3.289\n"
        self.assertEqual(capture.device_indices(summary), [0, 1])
        with self.assertRaises(capture.CaptureError):
            capture.device_indices("Devices:\n")


class GitGuardTest(unittest.TestCase):
    def test_inside_the_repo_is_refused(self):
        self.assertTrue(capture.inside_git_checkout(os.path.join(REPO_ROOT, "tests", "fixtures", "vulkan")))
        with self.assertRaises(capture.CaptureError):
            capture.capture(os.path.join(REPO_ROOT, "tests", "fixtures", "vulkan", "out"), "x")

    def test_outside_a_checkout_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            if capture.inside_git_checkout(directory):
                self.skipTest("the temporary directory is itself inside a git checkout")
            self.assertFalse(capture.inside_git_checkout(os.path.join(directory, "new")))


class CaptureFlowTest(unittest.TestCase):
    """capture() end to end, with vulkaninfo replaced: everything identifying is gone from
    every written file, and the capture succeeds."""

    def test_written_files_have_no_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            if capture.inside_git_checkout(directory):
                self.skipTest("the temporary directory is itself inside a git checkout")
            out_dir = os.path.join(directory, "out")
            summary = "Vulkan Instance Version: 1.3.289\nDevices:\nGPU0:\nGPU1:\n"
            lavapipe = {"VkPhysicalDeviceProperties": {
                "apiVersion": "1.3.289", "deviceType": "VK_PHYSICAL_DEVICE_TYPE_CPU",
                "deviceName": "llvmpipe (LLVM 19.1.0, 256 bits)", "pipelineCacheUUID": [3]},
                "VkPhysicalDeviceDriverProperties": {"driverID": "VK_DRIVER_ID_MESA_LLVMPIPE",
                                                     "driverName": "llvmpipe"}}
            documents = {0: copy.deepcopy(DOCUMENT), 1: lavapipe}
            with mock.patch.object(capture, "run_vulkaninfo", return_value=summary), \
                    mock.patch.object(capture, "capture_device", side_effect=lambda index, env: documents[index]), \
                    mock.patch.object(capture, "render_nodes", return_value={
                        "renderD128": {"dev": "226:128", "pci": "0000:03:00.0", "driver": "amdgpu"}}):
                written = capture.capture(out_dir, "test-box")
            self.assertEqual(written, ["real-test-box-gpu0-radv-1.3.json", "real-test-box-gpu1-llvmpipe-1.3.json",
                                       "nodes.json", "capture-info.json"])
            for name in written:
                with self.subTest(name):
                    with open(os.path.join(out_dir, name), "r", encoding="utf-8") as handle:
                        keys = set(all_keys(json.load(handle)))
                    self.assertFalse([key for key in keys if capture.is_scrubbed_key(key)])
            with open(os.path.join(out_dir, "capture-info.json"), "r", encoding="utf-8") as handle:
                info = json.load(handle)
            self.assertIn("pipelineCacheUUID", info["scrubbed_keys"])
            self.assertNotIn("hostname", info)


if __name__ == "__main__":
    unittest.main()
