"""User-supplied file lookup and the checksum cache (obscura_packs.userfiles).

Fixture files use neutral names and generated content: never real firmware (§14.2).
"""

import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from obscura_capd import report
from obscura_packs import userfiles
from obscura_packs.manifest import UserFile
from obscura_packs.userfiles import ABSENT, OK, UNREADABLE, WRONG_DUMP, cache_for, check_user_files

CONTENT = b"obscura test file\n"
CONTENT_SHA = hashlib.sha256(CONTENT).hexdigest()


class FakeManifest:
    def __init__(self, files, files_dir="example"):
        self.user_supplies = tuple(files)
        self.files_dir = files_dir


def bios(file="test-dump.dat", sha=(CONTENT_SHA,), kind="bios", required=True, id="bios"):
    return UserFile(id=id, label="Test BIOS", kind=kind, file=file, sha256=tuple(sha), required=required)


class UserFilesTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(report, "_send", side_effect=lambda *args: self.sent.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = directory.name
        self.files = os.path.join(self.home, "Obscura", "firmware", "example")

    def place(self, content=CONTENT, name="test-dump.dat"):
        os.makedirs(self.files, exist_ok=True)
        path = os.path.join(self.files, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def check(self, *files, cache=None):
        return check_user_files(FakeManifest(files), self.home, cache)

    def test_absent(self):
        self.assertEqual(self.check(bios())["bios"].status, ABSENT)

    def test_match(self):
        self.place()
        status = self.check(bios())["bios"]
        self.assertEqual(status.status, OK)
        self.assertEqual(status.path, os.path.join(self.files, "test-dump.dat"))

    def test_any_listed_checksum_matches(self):
        self.place()
        self.assertEqual(self.check(bios(sha=("0" * 64, CONTENT_SHA)))["bios"].status, OK)

    def test_wrong_dump(self):
        self.place(b"something else\n")
        status = self.check(bios())["bios"]
        self.assertEqual(status.status, WRONG_DUMP)

    def test_presence_only_kinds(self):
        self.place(b"any image\n", "windows.iso.part")
        status = self.check(bios(file="windows.iso.part", sha=(), kind="os-image"))["bios"]
        self.assertEqual(status.status, OK)

    def test_directory_instead_of_file(self):
        os.makedirs(os.path.join(self.files, "test-dump.dat"))
        self.assertEqual(self.check(bios())["bios"].status, UNREADABLE)

    def test_files_dir_is_shared_by_console(self):
        # Two packs with files_dir "ps1" find the same file.
        os.makedirs(os.path.join(self.home, "Obscura", "firmware", "ps1"))
        with open(os.path.join(self.home, "Obscura", "firmware", "ps1", "test-dump.dat"), "wb") as handle:
            handle.write(CONTENT)
        for _ in range(2):
            statuses = check_user_files(FakeManifest([bios()], files_dir="ps1"), self.home)
            self.assertEqual(statuses["bios"].status, OK)

    def test_cache_hit_skips_hashing(self):
        self.place()
        self.assertEqual(self.check(bios(), cache=cache_for(self.home))["bios"].status, OK)
        cache_file = os.path.join(self.home, ".cache", "obscura", "checksums.json")
        self.assertTrue(os.path.exists(cache_file))
        with mock.patch.object(userfiles, "sha256_of", side_effect=AssertionError("re-hashed")):
            self.assertEqual(self.check(bios(), cache=cache_for(self.home))["bios"].status, OK)

    def test_cache_invalidated_when_the_file_changes(self):
        path = self.place()
        self.check(bios(), cache=cache_for(self.home))
        with open(path, "wb") as handle:
            handle.write(b"replaced with a different dump\n")
        info = os.stat(path)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000_000))
        self.assertEqual(self.check(bios(), cache=cache_for(self.home))["bios"].status, WRONG_DUMP)

    def test_cache_cannot_vouch_for_a_changed_size(self):
        path = self.place()
        cache = cache_for(self.home)
        self.check(bios(), cache=cache)
        info = os.stat(path)
        with open(path, "ab") as handle:
            handle.write(b"x")
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))  # same mtime, new size
        self.assertEqual(self.check(bios(), cache=cache)["bios"].status, WRONG_DUMP)

    def test_corrupt_cache_is_ignored(self):
        self.place()
        cache_file = os.path.join(self.home, ".cache", "obscura", "checksums.json")
        os.makedirs(os.path.dirname(cache_file))
        with open(cache_file, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.check(bios(), cache=cache_for(self.home))["bios"].status, OK)
        with open(cache_file, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 1)

    def test_poisoned_cache_entry_for_another_file_does_not_match(self):
        path = self.place(b"something else\n")
        cache = cache_for(self.home)
        cache._entries[path] = {"key": [0, 0, 0], "sha256": CONTENT_SHA}
        self.assertEqual(self.check(bios(), cache=cache)["bios"].status, WRONG_DUMP)


if __name__ == "__main__":
    unittest.main()
