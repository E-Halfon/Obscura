"""Lint for tests/fixtures/vulkan: README rows, real/synthetic naming, and no identifiers."""

import re
import unittest

from tests.unit import vulkan_fixtures as fixtures

IDENTIFIER_KEY = re.compile(r"uuid|luid", re.IGNORECASE)


def keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


class FixtureLintTest(unittest.TestCase):
    def test_every_fixture_has_a_readme_row_with_its_origin(self):
        rows = fixtures.readme_rows()
        for name in fixtures.fixture_files():
            with self.subTest(name):
                match = fixtures.FILE_PATTERN.match(name)
                self.assertIsNotNone(match, "name must be <real|synthetic>-<label>-(gpu<n>-...|nodes).json")
                self.assertIn(name, rows, "add a README row")
                self.assertEqual(rows[name], match.group("origin"), "prefix and README origin disagree")

    def test_every_readme_row_names_a_file(self):
        files = set(fixtures.fixture_files())
        for name, origin in fixtures.readme_rows().items():
            with self.subTest(name):
                self.assertIn(name, files)
                self.assertIn(origin, ("real", "synthetic"))

    def test_synthetic_files_are_never_real(self):
        for key in fixtures.scenarios():
            if "synthetic" in key:
                with self.subTest(key):
                    self.assertFalse(fixtures.is_real(key))
        self.assertNotIn("synthetic", " ".join(fixtures.real_hardware_scenarios()))

    def test_no_identifiers_in_any_fixture(self):
        for name in fixtures.fixture_files():
            with self.subTest(name):
                found = [key for key in keys(fixtures.load_json(name)) if IDENTIFIER_KEY.search(str(key))
                         or key == "deviceNodeMask"]
                self.assertEqual(found, [], "scrub with capture.py before committing")

    def test_scenarios_are_complete(self):
        for key, entry in fixtures.scenarios().items():
            with self.subTest(key):
                self.assertTrue(entry["devices"], "a scenario needs at least one device")
                self.assertIsNotNone(entry["nodes"], "a scenario needs its -nodes.json")
                indices = [index for index, _ in entry["devices"]]
                self.assertEqual(indices, list(range(len(indices))), "device indices must be 0..n-1")


if __name__ == "__main__":
    unittest.main()
