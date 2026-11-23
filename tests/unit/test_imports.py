"""Every obscura_capd module must import. Catches load-time errors (syntax, a name
shadowing an annotation type, a bad import) in the unit tests rather than only as a
daemon that silently fails to start in the integration tests.

Modules that need dasbus or PyGObject are skipped where those aren't installed (e.g. on
Windows); in CI they are installed, so every module is imported there.
"""

import importlib
import os
import pkgutil
import sys
import unittest

from tests import CAPD_PYTHONPATH

# Optional dependencies that only exist on Linux. A module failing to import because
# one of these is missing is skipped; any other import failure is a test failure.
OPTIONAL_DEPENDENCIES = ("dasbus", "gi")


def dependency_available(name):
    try:
        module = sys.modules.get(name)
        if module is not None:
            # tests.unit.test_mirror_apply may install a stub gi; a stub doesn't count.
            return getattr(module, "__file__", None) is not None
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class ImportEveryModuleTest(unittest.TestCase):
    def test_every_module_imports(self):
        package_dir = os.path.join(CAPD_PYTHONPATH, "obscura_capd")
        names = sorted(info.name for info in pkgutil.iter_modules([package_dir]))
        self.assertIn("service", names)
        self.assertIn("daemon", names)
        missing = [name for name in OPTIONAL_DEPENDENCIES if not dependency_available(name)]
        for name in names:
            with self.subTest(module=name):
                try:
                    importlib.import_module("obscura_capd." + name)
                except ImportError as error:
                    root = (error.name or "").split(".")[0]
                    if root in missing:
                        self.skipTest("obscura_capd." + name + " needs " + root + ", not installed here")
                    raise


if __name__ == "__main__":
    unittest.main()
