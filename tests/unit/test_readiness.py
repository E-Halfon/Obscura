"""Readiness evaluation (obscura_packs.readiness): states, precedence, and fail-closed."""

import unittest
from unittest import mock

from obscura_capd import report
from obscura_capd.vocabulary import Declaration
from obscura_packs import readiness
from obscura_packs.catalog import Catalog, InstalledPack
from obscura_packs.constants import (
    INSUFFICIENT_HARDWARE,
    MISSING_FILES,
    MISSING_HARDWARE,
    NEEDS_NEWER_OBSCURA,
    NEEDS_PACK,
    READY,
    REMOTE,
    UNEVALUABLE,
)
from obscura_packs.manifest import parse_manifest
from obscura_packs.readiness import Readiness, evaluate, evaluate_catalog
from obscura_packs.userfiles import ABSENT, OK, UNREADABLE, WRONG_DUMP, FileStatus

SHA = "b" * 64


def declaration(name, kind, summary, attachable):
    return Declaration(name=name, api=1, kind=kind, target="obscura-cap-" + name + ".target",
                       summary=summary, source=name + ".toml", attachable=attachable)


VOCABULARY = {
    "x86-64-v3": declaration("x86-64-v3", "static", "AVX2, BMI2, FMA", False),
    "camera": declaration("camera", "device", "A camera", True),
    "apple-coprocessor": declaration("apple-coprocessor", "probe", "An Apple coprocessor", True),
    # A device-kind capability that isn't attachable (PACKS.md §2: an iGPU-only laptop
    # has insufficient hardware, it isn't told to connect a GPU).
    "dgpu": declaration("dgpu", "device", "A discrete GPU", False),
}


def pack(name="pack-test", requires=(), recommends=(), depends=(), files=(), remote=False, runtime=False):
    lines = ["[pack]", 'name = "%s"' % name, "api = 1", 'version = "1"', 'platform = "retro"',
             'technique = "emulation"', 'summary = "Test."']
    if runtime:
        lines.append("runtime = true")
    lines += ["[handles]", 'extensions = [".tst"]',
              "[requires]", "capabilities = [%s]" % ", ".join('"%s"' % c for c in requires),
              "[recommends]", "capabilities = [%s]" % ", ".join('"%s"' % c for c in recommends),
              "[fallback]", "remote = %s" % ("true" if remote else "false")]
    if depends:
        lines += ["[depends]", "runtime = [%s]" % ", ".join('"%s"' % d for d in depends)]
    for file_id, required in files:
        lines += ["[[user_supplies]]", 'id = "%s"' % file_id, 'label = "Test BIOS"', 'kind = "bios"',
                  'file = "%s.dat"' % file_id, 'sha256 = ["%s"]' % SHA, "required = %s" % ("true" if required else "false")]
    return parse_manifest("\n".join(lines) + "\n", "pack.toml", frozenset())


def files(**statuses):
    return {file_id: FileStatus(file_id, "/home/u/Obscura/firmware/test/" + file_id + ".dat", status)
            for file_id, status in statuses.items()}


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)

    def failures(self):
        return [args for args in self.sent if args[0] == 3 and "failure in" in args[2]]

    def codes(self, result):
        return [reason.code for reason in result.reasons]

    # -- each state on its own ---------------------------------------------------------

    def test_ready_with_no_requirements(self):
        result = evaluate(pack(), frozenset(), VOCABULARY)
        self.assertEqual(result, Readiness("pack-test", READY))

    def test_ready_when_requirements_present(self):
        self.assertEqual(evaluate(pack(requires=["camera"]), {"camera"}, VOCABULARY).state, READY)

    def test_absent_static_capability_is_insufficient_hardware(self):
        result = evaluate(pack(requires=["x86-64-v3"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(self.codes(result), ["capability-absent"])
        self.assertIn("doesn't have it", result.reasons[0].message)

    def test_absent_device_capability_is_missing_hardware(self):
        result = evaluate(pack(requires=["camera"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, MISSING_HARDWARE)
        self.assertEqual(result.reasons[0].fix, readiness.FIX_CONNECT_DEVICE)

    def test_absent_probe_capability_is_missing_hardware(self):
        self.assertEqual(evaluate(pack(requires=["apple-coprocessor"]), frozenset(), VOCABULARY).state, MISSING_HARDWARE)

    def test_mixed_static_and_device_is_insufficient_hardware(self):
        # Connecting a camera can't fix the missing CPU feature, so don't say "connect".
        for requires in (["x86-64-v3", "camera"], ["camera", "x86-64-v3"], ["camera", "vulkan-1.3"]):
            with self.subTest(requires):
                result = evaluate(pack(requires=requires), frozenset(), VOCABULARY)
                self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
                self.assertEqual(len(result.reasons), 2)

    def test_attachable_decides_not_the_detection_kind(self):
        result = evaluate(pack(requires=["dgpu"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(result.reasons[0].fix, "")

    def test_only_attachable_absences_are_missing_hardware(self):
        result = evaluate(pack(requires=["camera", "apple-coprocessor"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, MISSING_HARDWARE)

    def test_undeclared_capability_is_insufficient_and_says_so(self):
        # pack-wine before task 0.2b: vulkan-1.3 isn't declared yet.
        result = evaluate(pack(requires=["vulkan-1.3"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(self.codes(result), ["capability-unknown"])
        self.assertEqual(result.reasons[0].fix, readiness.FIX_UPDATE_OBSCURA)

    def test_missing_file(self):
        result = evaluate(pack(files=[("bios", True)]), frozenset(), VOCABULARY, file_status=files(bios=ABSENT))
        self.assertEqual(result.state, MISSING_FILES)
        self.assertEqual(self.codes(result), ["file-absent"])
        self.assertIn("/home/u/Obscura/firmware/test", result.reasons[0].message)
        self.assertEqual(result.reasons[0].fix, readiness.FIX_OPEN_FILES_FOLDER)

    def test_wrong_dump_and_unreadable_are_distinct(self):
        result = evaluate(pack(files=[("a", True), ("b", True)]), frozenset(), VOCABULARY,
                          file_status=files(a=WRONG_DUMP, b=UNREADABLE))
        self.assertEqual(result.state, MISSING_FILES)
        self.assertEqual(self.codes(result), ["file-wrong-dump", "file-unreadable"])

    def test_optional_file_missing_is_only_a_note(self):
        result = evaluate(pack(files=[("bios", False)]), frozenset(), VOCABULARY, file_status=files(bios=ABSENT))
        self.assertEqual(result.state, READY)
        self.assertEqual(len(result.notes), 1)

    def test_present_file_is_ready(self):
        self.assertEqual(evaluate(pack(files=[("bios", True)]), frozenset(), VOCABULARY,
                                  file_status=files(bios=OK)).state, READY)

    def test_recommendations_are_notes(self):
        result = evaluate(pack(recommends=["dgpu"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, READY)
        self.assertIn("discrete GPU", result.notes[0])

    def test_newer_manifest_needs_a_newer_obscura(self):
        text = ('[pack]\nname = "pack-future"\napi = 1\napi_minor = 7\nversion = "1"\nplatform = "retro"\n'
                'technique = "emulation"\nsummary = "Future."\nshiny = true\n')
        manifest = parse_manifest(text, "pack.toml", frozenset())
        result = evaluate(manifest, frozenset(), VOCABULARY)
        self.assertEqual(result.state, NEEDS_NEWER_OBSCURA)
        self.assertEqual(result.reasons[0].fix, readiness.FIX_UPDATE_OBSCURA)

    # -- precedence --------------------------------------------------------------------

    def test_hardware_beats_files_but_all_reasons_are_listed(self):
        result = evaluate(pack(requires=["camera"], files=[("bios", True)]), frozenset(), VOCABULARY,
                          file_status=files(bios=ABSENT))
        self.assertEqual(result.state, MISSING_HARDWARE)
        self.assertEqual(self.codes(result), ["capability-absent", "file-absent"])

    def test_remote_when_a_peer_can_run_it(self):
        manifest = pack(requires=["apple-coprocessor"], remote=True)
        self.assertEqual(evaluate(manifest, frozenset(), VOCABULARY, remote_ready=True).state, REMOTE)
        self.assertEqual(evaluate(manifest, frozenset(), VOCABULARY, remote_ready=False).state, MISSING_HARDWARE)

    def test_no_remote_without_fallback(self):
        self.assertEqual(evaluate(pack(requires=["apple-coprocessor"]), frozenset(), VOCABULARY,
                                  remote_ready=True).state, MISSING_HARDWARE)

    def test_not_on_this_device(self):
        manifest = pack(remote=True)
        self.assertEqual(evaluate(manifest, frozenset(), VOCABULARY, not_on_this_device=True,
                                  remote_ready=True).state, REMOTE)
        result = evaluate(manifest, frozenset(), VOCABULARY, not_on_this_device=True)
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(self.codes(result), ["not-on-this-device"])

    def test_runtime_not_installed_needs_a_pack(self):
        result = evaluate(pack(depends=["pack-proton"]), frozenset(), VOCABULARY)
        self.assertEqual(result.state, NEEDS_PACK)
        self.assertEqual(result.reasons[0].fix, readiness.FIX_INSTALL_PACK)

    def test_runtime_not_ready_passes_its_state_on(self):
        proton = evaluate(pack("pack-proton", requires=["x86-64-v3"], runtime=True), frozenset(), VOCABULARY)
        result = evaluate(pack(depends=["pack-proton"]), frozenset(), VOCABULARY, {"pack-proton": proton})
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(self.codes(result), ["runtime-not-ready"])

    def test_remote_only_runtime_is_not_runnable_for_a_local_only_pack(self):
        proton = Readiness("pack-proton", REMOTE)
        result = evaluate(pack(depends=["pack-proton"]), frozenset(), VOCABULARY, {"pack-proton": proton},
                          remote_ready=True)
        self.assertEqual(result.state, INSUFFICIENT_HARDWARE)
        self.assertEqual(self.codes(result), ["runtime-remote-only"])

    def test_remote_only_runtime_needs_a_peer_for_this_pack(self):
        proton = Readiness("pack-proton", REMOTE)
        manifest = pack(depends=["pack-proton"], remote=True)
        self.assertEqual(evaluate(manifest, frozenset(), VOCABULARY, {"pack-proton": proton},
                                  remote_ready=True).state, REMOTE)
        self.assertEqual(evaluate(manifest, frozenset(), VOCABULARY, {"pack-proton": proton},
                                  remote_ready=False).state, INSUFFICIENT_HARDWARE)

    def test_ready_runtime(self):
        proton = evaluate(pack("pack-proton", runtime=True), frozenset(), VOCABULARY)
        self.assertEqual(evaluate(pack(depends=["pack-proton"]), frozenset(), VOCABULARY,
                                  {"pack-proton": proton}).state, READY)

    def test_runtime_beats_files(self):
        result = evaluate(pack(depends=["pack-proton"], files=[("bios", True)]), frozenset(), VOCABULARY,
                          file_status=files(bios=ABSENT))
        self.assertEqual(result.state, NEEDS_PACK)

    def test_capability_service_unavailable(self):
        self.assertEqual(evaluate(pack(requires=["camera"]), None, VOCABULARY).state, UNEVALUABLE)
        # A pack with no hardware requirements doesn't need capd.
        self.assertEqual(evaluate(pack(), None, VOCABULARY).state, READY)

    def test_capability_service_unavailable_with_only_recommendations(self):
        # Recommended capabilities are notes, never a reason the pack can't be checked.
        result = evaluate(pack(recommends=["dgpu"]), None, VOCABULARY)
        self.assertEqual(result.state, READY)
        self.assertEqual(result.notes, ("Couldn't check for recommended hardware.",))

    # -- fail closed -------------------------------------------------------------------

    def test_exception_in_the_evaluator_is_unevaluable_never_ready(self):
        for target in ("_hardware", "_runtimes", "_files", "_recommendations"):
            with self.subTest(target):
                self.sent.clear()
                with mock.patch.object(readiness, target, side_effect=IndexError("boom")):
                    result = evaluate(pack(), frozenset(), VOCABULARY)
                self.assertEqual(result.state, UNEVALUABLE)
                self.assertNotEqual(result.state, READY)
                self.assertEqual(self.codes(result), ["internal-error"])
                self.assertEqual(len(self.failures()), 1, self.sent)

    def test_missing_file_status_is_unevaluable(self):
        result = evaluate(pack(files=[("bios", True)]), frozenset(), VOCABULARY, file_status={})
        self.assertEqual(result.state, UNEVALUABLE)
        self.assertEqual(len(self.failures()), 1)

    def test_bad_input_types_are_unevaluable(self):
        self.assertEqual(evaluate(pack(requires=["camera"]), frozenset({"camera"}), None).state, READY)
        self.assertEqual(evaluate(pack(requires=["x86-64-v3"]), frozenset(), None).state, UNEVALUABLE)
        self.assertEqual(evaluate(None, frozenset(), VOCABULARY).state, UNEVALUABLE)

    # -- whole catalog -----------------------------------------------------------------

    def catalog(self, *manifests):
        catalog = Catalog()
        for manifest in manifests:
            catalog.packs[manifest.name] = InstalledPack(manifest, "factory", "/x/" + manifest.name)
        return catalog

    def test_catalog_evaluates_runtimes_first(self):
        catalog = self.catalog(pack("pack-a-steamvr", depends=["pack-proton"]),
                               pack("pack-proton", requires=["camera"], runtime=True))
        results = evaluate_catalog(catalog, frozenset(), VOCABULARY, "/home/u", check_files=lambda m, h, c: {})
        self.assertEqual(results["pack-proton"].state, MISSING_HARDWARE)
        self.assertEqual(results["pack-a-steamvr"].state, MISSING_HARDWARE)
        self.assertEqual(results["pack-a-steamvr"].reasons[0].code, "runtime-not-ready")

    def test_catalog_one_failing_pack_does_not_block_the_others(self):
        catalog = self.catalog(pack("pack-a"), pack("pack-b"))

        def check_files(manifest, home, cache):
            if manifest.name == "pack-a":
                raise OSError("disk on fire")
            return {}

        results = evaluate_catalog(catalog, frozenset(), VOCABULARY, "/home/u", check_files=check_files)
        self.assertEqual(results["pack-a"].state, UNEVALUABLE)
        self.assertEqual(results["pack-b"].state, READY)


if __name__ == "__main__":
    unittest.main()
