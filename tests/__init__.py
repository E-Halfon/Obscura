"""Camera Obscura tests. Run from the repo root: python3 -m unittest discover -s tests -t . -v

Unit tests need only Python 3.11+. Integration tests need dasbus, PyGObject, dbus-python,
python-dbusmock, and dbus-daemon (Linux); they skip themselves when those are missing.
VM tests (tests/vm/) run on the built image, not here.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE_ROOT = os.path.join(REPO_ROOT, "files", "system")
CAPD_PYTHONPATH = os.path.join(IMAGE_ROOT, "usr", "lib", "obscura", "python")
VOCABULARY_DIR = os.path.join(IMAGE_ROOT, "usr", "share", "obscura", "capabilities.d")
UNIT_DIR = os.path.join(IMAGE_ROOT, "usr", "lib", "systemd", "system")
UDEV_DIR = os.path.join(IMAGE_ROOT, "usr", "lib", "udev", "rules.d")

if CAPD_PYTHONPATH not in sys.path:
    sys.path.insert(0, CAPD_PYTHONPATH)

# Pack format (task 0.21).
FACTORY_PACKS_DIR = os.path.join(IMAGE_ROOT, "usr", "share", "obscura", "packs")
SIGNATURES_FILE = os.path.join(IMAGE_ROOT, "usr", "share", "obscura", "signatures.toml")
PACK_FIXTURES_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "packs")
PACK_FIXTURES_MALFORMED_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "packs-malformed")
