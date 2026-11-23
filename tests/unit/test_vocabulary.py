"""Declaration parsing and loading (obscura_capd.vocabulary)."""

import os
import tempfile
import unittest
from unittest import mock

from tests import VOCABULARY_DIR
from obscura_capd import report, vocabulary
from obscura_capd.vocabulary import DeclarationError, load_vocabulary, parse_declaration

VALID = """
[capability]
name    = "battery"
api     = 1
kind    = "device"
target  = "obscura-cap-battery.target"
summary = "A system battery"
attachable = false
"""


def declaration_text(**overrides):
    fields = {
        "name": '"battery"',
        "api": "1",
        "kind": '"device"',
        "target": '"obscura-cap-battery.target"',
        "summary": '"A system battery"',
        "attachable": "false",
    }
    fields.update(overrides)
    lines = ["[capability]"]
    for key, value in fields.items():
        if value is not None:
            lines.append(key + " = " + value)
    return "\n".join(lines) + "\n"


class ReportCapture(unittest.TestCase):
    """Collects report._send calls instead of writing to the journal or stderr."""

    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)


class ParseDeclarationTest(ReportCapture):
    def test_valid(self):
        declaration = parse_declaration(VALID, "battery.toml")
        self.assertEqual(declaration.name, "battery")
        self.assertEqual(declaration.target, "obscura-cap-battery.target")
        self.assertEqual(declaration.kind, "device")

    def test_rejections(self):
        cases = {
            "bad toml": "[capability\n",
            "no table": 'name = "battery"\n',
            "missing summary": declaration_text(summary=None),
            "underscore in name": declaration_text(name='"bat_tery"', target='"obscura-cap-bat_tery.target"'),
            "uppercase name": declaration_text(name='"Battery"', target='"obscura-cap-Battery.target"'),
            "trailing hyphen": declaration_text(name='"battery-"', target='"obscura-cap-battery-.target"'),
            "wrong target": declaration_text(target='"battery.target"'),
            "api 2": declaration_text(api="2"),
            "api bool": declaration_text(api="true"),
            "api string": declaration_text(api='"1"'),
            # Pack availability is not a capability kind (pack manager owns it, 0.21).
            "kind pack": declaration_text(kind='"pack"'),
            "empty summary": declaration_text(summary='"  "'),
            "missing attachable": declaration_text(attachable=None),
            "attachable string": declaration_text(attachable='"yes"'),
            "attachable int": declaration_text(attachable="1"),
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(DeclarationError):
                    parse_declaration(text, label)

    def test_multi_word_name(self):
        text = declaration_text(name='"x86-64-v3"', target='"obscura-cap-x86-64-v3.target"', kind='"static"')
        self.assertEqual(parse_declaration(text, "x.toml").name, "x86-64-v3")

    def test_dotted_name(self):
        text = declaration_text(name='"vulkan-1.3"', target='"obscura-cap-vulkan-1.3.target"')
        self.assertEqual(parse_declaration(text, "vulkan-1.3.toml").name, "vulkan-1.3")

    def test_bad_separators_rejected(self):
        for name in ("a..b", ".a", "a.", "a-.b", "a.-b", "A.1", "a_1.3", "a 1"):
            with self.subTest(name):
                text = declaration_text(name='"' + name + '"', target='"obscura-cap-' + name + '.target"')
                with self.assertRaises(DeclarationError):
                    parse_declaration(text, name + ".toml")

    def test_same_rule_as_pack_manifests(self):
        from obscura_packs.constants import CAPABILITY_NAME_PATTERN
        self.assertEqual(vocabulary.NAME_PATTERN.pattern, CAPABILITY_NAME_PATTERN.pattern)


class LoadVocabularyTest(ReportCapture):
    def write(self, directory, filename, text):
        with open(os.path.join(directory, filename), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_shipped_declarations(self):
        loaded = load_vocabulary(VOCABULARY_DIR)
        self.assertEqual(sorted(loaded), ["battery", "camera", "virt", "vulkan-1.3", "x86-64-v3"])
        self.assertEqual(loaded["x86-64-v3"].kind, "static")
        self.assertEqual(loaded["vulkan-1.3"].kind, "device")
        self.assertFalse(loaded["x86-64-v3"].attachable)
        self.assertFalse(loaded["vulkan-1.3"].attachable)
        self.assertEqual(self.sent, [], "shipped declarations must load without problems")

    def test_missing_directory_is_empty_and_reported(self):
        self.assertEqual(load_vocabulary(os.path.join(tempfile.gettempdir(), "obscura-no-such-dir")), {})
        self.assertEqual(len(self.sent), 1)

    def test_bad_files_skipped_good_ones_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "battery.toml", VALID)
            self.write(directory, "broken.toml", "[capability\n")
            self.write(directory, "camera.toml", VALID)  # declares battery: name mismatch
            self.write(directory, "README", "not a declaration")
            loaded = load_vocabulary(directory)
        self.assertEqual(sorted(loaded), ["battery"])
        self.assertEqual(len(self.sent), 2)

    def test_target_for(self):
        self.assertEqual(vocabulary.target_for("virt"), "obscura-cap-virt.target")


if __name__ == "__main__":
    unittest.main()
