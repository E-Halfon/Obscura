"""The vulkan-1.3 acceptance rule (obscura_capd.vulkan_rule) against the fixtures."""

import copy
import os
import unittest
from unittest import mock

import tests  # noqa: F401  (puts obscura_capd on sys.path)
from obscura_capd import report
from obscura_capd.vulkan_rule import (SchemaError, decode_api, device_from_document, judge,
                                      kernel_driver_reason, node_qualifies, parse_node_number)
from tests.unit import vulkan_fixtures as fixtures

RENDER_128 = (226, 128)
RENDER_129 = (226, 129)


def devices(key):
    documents, nodes = fixtures.load_scenario(key)
    return [device_from_document(document) for document in documents], nodes


def accepted_name(key, node):
    found, _ = node_qualifies(devices(key)[0], node)
    return found.name if found else None


class LavapipeNegativeTest(unittest.TestCase):
    """The key negative test: lavapipe reports Vulkan 1.3 in the VMware VM, and it must not
    count. It uses the real recording from the VM only (build brief §7, C-12), never a
    synthetic stand-in, and it fails until that recording is committed."""

    def test_real_vmware_lavapipe_never_counts(self):
        if fixtures.LAVAPIPE_SCENARIO not in fixtures.scenarios():
            self.fail("no real-vmware-lavapipe recording yet. Record it in the VM on the 0.2b image: "
                      "python3 capture.py <dir outside the repo> --label vmware-lavapipe (C-12), then "
                      "commit the real-vmware-lavapipe-* files with README rows marked real")
        self.assertTrue(fixtures.is_real(fixtures.LAVAPIPE_SCENARIO), "README must mark every file real")
        found, nodes = devices(fixtures.LAVAPIPE_SCENARIO)
        # The test means something only if lavapipe is there and claims 1.3.
        lavapipe = [d for d in found if "llvmpipe" in d.name.lower() or "llvmpipe" in str(d.driver_name).lower()]
        self.assertTrue(lavapipe, "the recording must contain the llvmpipe device")
        self.assertTrue(any(d.api is not None and d.api >= (1, 3) for d in lavapipe),
                        "lavapipe must report Vulkan >= 1.3 for this negative test to mean anything")
        for node, number in list(nodes.items()) + [("hypothetical renderD128", RENDER_128)]:
            with self.subTest(node):
                accepted, reasons = node_qualifies(found, number)
                self.assertIsNone(accepted, reasons)


class SyntheticBranchTest(unittest.TestCase):
    """Synthetic fixtures exercise the rule's branches. They never satisfy acceptance."""

    def test_radv_counts_for_its_own_node_only(self):
        self.assertEqual(accepted_name("synthetic-radv-lavapipe", RENDER_128), "AMD Radeon RX 7800 XT (RADV NAVI32)")
        self.assertIsNone(accepted_name("synthetic-radv-lavapipe", RENDER_129))

    def test_lavapipe_beside_a_gpu_is_rejected(self):
        found, _ = devices("synthetic-radv-lavapipe")
        lavapipe = [d for d in found if d.device_type == "CPU"][0]
        counts, reason = judge(lavapipe, RENDER_128)
        self.assertFalse(counts)
        self.assertIn("VkPhysicalDeviceDrmPropertiesEXT", reason)

    def test_discrete_and_integrated_each_count_for_their_own_node(self):
        self.assertIn("RADV", accepted_name("synthetic-discrete-integrated", RENDER_128))
        self.assertIn("Intel", accepted_name("synthetic-discrete-integrated", RENDER_129))
        self.assertIsNone(accepted_name("synthetic-discrete-integrated", (226, 130)))

    def test_rejected_scenarios(self):
        for key, expected in (("synthetic-venus-virtual", "MESA_VENUS"),
                              ("synthetic-radv-no-drm-ext", "no VkPhysicalDeviceDrmPropertiesEXT"),
                              ("synthetic-gpu-api-1.2", "below 1.3"),
                              ("synthetic-wrong-type-other", "OTHER")):
            with self.subTest(key):
                found, nodes = devices(key)
                for number in nodes.values():
                    accepted, reasons = node_qualifies(found, number)
                    self.assertIsNone(accepted)
                    self.assertTrue(any(expected in reason for reason in reasons), reasons)


class RealHardwareTest(unittest.TestCase):
    def test_present_on_real_hardware(self):
        """The "vulkan-1.3 present" acceptance test. Real recordings only; open item in the
        build brief until one exists."""
        keys = fixtures.real_hardware_scenarios()
        if not keys:
            self.skipTest("no real hardware recording; open item in build brief §7 (D-2)")
        for key in keys:
            with self.subTest(key):
                found, nodes = devices(key)
                self.assertTrue(nodes, "a hardware recording has render nodes")
                self.assertTrue(any(node_qualifies(found, number)[0] for number in nodes.values()),
                                "at least one render node must qualify")


def base_document(**overrides):
    properties = {
        "VkPhysicalDeviceProperties": {"apiVersion": "1.3.289", "deviceType": "VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU",
                                       "deviceName": "Test GPU"},
        "VkPhysicalDeviceDriverProperties": {"driverID": "VK_DRIVER_ID_MESA_RADV", "driverName": "radv"},
        "VkPhysicalDeviceDrmPropertiesEXT": {"hasRender": True, "renderMajor": 226, "renderMinor": 128},
    }
    for key, value in overrides.items():
        if value is None:
            properties.pop(key, None)
        else:
            properties[key] = value
    return {"capabilities": {"device": {"properties": properties}}}


class InlineRuleTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(report, "_send")
        self.sent = patcher.start()
        self.addCleanup(patcher.stop)

    def counts(self, document, node=RENDER_128):
        return judge(device_from_document(document), node)[0]

    def test_baseline_counts(self):
        self.assertTrue(self.counts(base_document()))

    def test_llvmpipe_disguised_as_a_gpu_is_rejected(self):
        for driver in ({"driverID": "VK_DRIVER_ID_MESA_LLVMPIPE", "driverName": "x"},
                       {"driverID": 13, "driverName": "x"},
                       {"driverID": "VK_DRIVER_ID_MESA_RADV", "driverName": "llvmpipe"},
                       {"driverID": "VK_DRIVER_ID_GOOGLE_SWIFTSHADER", "driverName": "x"}):
            with self.subTest(driver):
                self.assertFalse(self.counts(base_document(VkPhysicalDeviceDriverProperties=driver)))
        name = {"apiVersion": "1.3.0", "deviceType": "VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU",
                "deviceName": "llvmpipe (LLVM 20, 256 bits)"}
        self.assertFalse(self.counts(base_document(VkPhysicalDeviceProperties=name)))

    def test_layered_drivers_are_rejected_whatever_the_type(self):
        """Review item 1: Venus can pass the host's DISCRETE_GPU type through; Dozen too."""
        for driver in ({"driverID": "VK_DRIVER_ID_MESA_VENUS", "driverName": "x"},
                       {"driverID": 22, "driverName": "x"},
                       {"driverID": "VK_DRIVER_ID_MESA_DOZEN", "driverName": "x"},
                       {"driverID": 23, "driverName": "x"},
                       {"driverID": "VK_DRIVER_ID_MESA_RADV", "driverName": "venus"},
                       {"driverID": "VK_DRIVER_ID_MESA_RADV", "driverName": "Dozen"}):
            with self.subTest(driver):
                properties = {"apiVersion": "1.3.0", "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                              "deviceName": "AMD Radeon RX 7800 XT"}
                self.assertFalse(self.counts(base_document(VkPhysicalDeviceProperties=properties,
                                                           VkPhysicalDeviceDriverProperties=driver)))

    def test_venus_codename_in_a_device_name_still_counts(self):
        """Layered drivers are matched by driverID and exact driverName, never by deviceName:
        "Venus" is also an old AMD GPU codename."""
        properties = {"apiVersion": "1.3.0", "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                      "deviceName": "AMD Radeon HD 8870M (RADV VENUS)"}
        self.assertTrue(self.counts(base_document(VkPhysicalDeviceProperties=properties)))

    def test_kernel_driver_reason(self):
        for driver in ("amdgpu", "i915", "xe", "nouveau", "nvidia-drm"):
            with self.subTest(driver):
                self.assertIsNone(kernel_driver_reason(driver))
        for driver in ("virtio_gpu", "vmwgfx", "vkms", "vgem", None, "", "  "):
            with self.subTest(driver):
                self.assertIsNotNone(kernel_driver_reason(driver))

    def test_missing_driver_properties_do_not_count(self):
        self.assertFalse(self.counts(base_document(VkPhysicalDeviceDriverProperties=None)))

    def test_driver_properties_from_vulkan12_struct(self):
        document = base_document(VkPhysicalDeviceDriverProperties=None,
                                 VkPhysicalDeviceVulkan12Properties={"driverID": "VK_DRIVER_ID_MESA_RADV",
                                                                     "driverName": "radv"})
        self.assertTrue(self.counts(document))

    def test_drm_struct_must_report_this_render_node(self):
        self.assertFalse(self.counts(base_document(VkPhysicalDeviceDrmPropertiesEXT=None)))
        self.assertFalse(self.counts(base_document(
            VkPhysicalDeviceDrmPropertiesEXT={"hasRender": False, "renderMajor": 226, "renderMinor": 128})))
        self.assertFalse(self.counts(base_document(
            VkPhysicalDeviceDrmPropertiesEXT={"hasRender": True, "renderMajor": 226, "renderMinor": 129})))
        self.assertFalse(self.counts(base_document(
            VkPhysicalDeviceDrmPropertiesEXT={"hasRender": True, "renderMajor": "226", "renderMinor": 128})))
        self.assertFalse(self.counts(base_document(), node=(227, 128)))

    def test_device_types(self):
        for value, expected in (("VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU", True), (2, True), (1, True),
                                ("VK_PHYSICAL_DEVICE_TYPE_CPU", False), (4, False), (3, False), (0, False),
                                ("VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU", False), (None, False), (True, False)):
            with self.subTest(value):
                properties = {"apiVersion": "1.3.0", "deviceType": value, "deviceName": "Test GPU"}
                self.assertEqual(self.counts(base_document(VkPhysicalDeviceProperties=properties)), expected)

    def test_device_api_version(self):
        for value, expected in (("1.3.0", True), ("1.4.318", True), ("1.2.199", False),
                                ((1 << 22) | (3 << 12), True), ((1 << 22) | (2 << 12) | 999, False),
                                ("2", False), (None, False), (True, False)):
            with self.subTest(value):
                properties = {"apiVersion": value, "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                              "deviceName": "Test GPU"}
                self.assertEqual(self.counts(base_document(VkPhysicalDeviceProperties=properties)), expected)

    def test_decode_api_masks_the_variant(self):
        self.assertEqual(decode_api((7 << 29) | (1 << 22) | (3 << 12) | 5), (1, 3))
        self.assertIsNone(decode_api(-1))

    def test_schema_errors(self):
        for label, document in (("not an object", []), ("no properties", {"capabilities": {}}),
                                ("properties not an object", {"VkPhysicalDeviceProperties": "x"}),
                                ("no device name", base_document(VkPhysicalDeviceProperties={"apiVersion": "1.3.0"}))):
            with self.subTest(label):
                with self.assertRaises(SchemaError):
                    device_from_document(document)

    def test_conflicting_copies_are_a_schema_error(self):
        document = base_document()
        document["elsewhere"] = {"VkPhysicalDeviceDrmPropertiesEXT": {"hasRender": True, "renderMajor": 226,
                                                                     "renderMinor": 129}}
        with self.assertRaises(SchemaError):
            device_from_document(document)
        same = base_document()
        same["elsewhere"] = copy.deepcopy(same["capabilities"]["device"]["properties"])
        self.assertTrue(self.counts(same))

    def test_parse_node_number(self):
        self.assertEqual(parse_node_number("226:128\n"), (226, 128))
        for text in ("", "226", "a:b", "226:128:1"):
            with self.subTest(text):
                with self.assertRaises(SchemaError):
                    parse_node_number(text)


if __name__ == "__main__":
    unittest.main()
