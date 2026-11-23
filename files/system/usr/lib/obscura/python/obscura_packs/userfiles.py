"""User-supplied files (firmware, BIOS, keys, ROM sets, OS images): finding and checking them.

Files live in ~/Obscura/firmware/<files_dir>/<file> (ARCHITECTURE.md §17.1, §17.3). They
are never bundled. A file is accepted when its SHA-256 matches one of the manifest's
checksums, or, for kinds with no checksum (OS images, media), when it exists.

Hashing a multi-gigabyte image on every readiness check would be slow, so results are
cached per user in $XDG_CACHE_HOME/obscura/checksums.json (default ~/.cache), keyed on
the path and invalidated by any change in size, modification time, inode-change time,
or inode. The change time catches a same-size rewrite that restores the modification
time (e.g. `cp -p` over the file), which can't be faked from userspace.
"""

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass

from obscura_capd import report
from obscura_packs.constants import CHECKSUM_CACHE, USER_FILES_DIR

OK = "ok"
ABSENT = "absent"
WRONG_DUMP = "wrong-dump"
UNREADABLE = "unreadable"

_CHUNK = 1024 * 1024
_CACHE_VERSION = 2


@dataclass(frozen=True)
class FileStatus:
    id: str
    path: str
    status: str
    detail: str = ""


def files_directory(home, files_dir):
    """Where the user places files for packs with this files_dir."""
    try:
        return os.path.join(home, *USER_FILES_DIR, files_dir)
    except Exception as error:
        report.failure("userfiles.files_directory", error)
        raise


def sha256_of(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        raise
    except Exception as error:
        report.failure("userfiles.sha256_of", error)
        raise


class ChecksumCache:
    """path -> (size, mtime_ns, ctime_ns, inode, sha256). A missing or corrupt cache file is just an
    empty cache: the cost of losing it is re-hashing, never a wrong answer."""

    def __init__(self, path):
        try:
            self._path = path
            self._entries = {}
            self._dirty = False
            self._load()
        except Exception as error:
            report.failure("ChecksumCache.__init__", error)
            raise

    def _load(self):
        try:
            try:
                with open(self._path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except FileNotFoundError:
                return
            except (OSError, ValueError, UnicodeDecodeError) as error:
                report.notice("ignoring unreadable checksum cache: " + str(error), OBSCURA_PATH=self._path)
                return
            if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION:
                return
            entries = data.get("entries")
            if isinstance(entries, dict):
                self._entries = entries
        except Exception as error:
            report.failure("ChecksumCache._load", error)
            raise

    @staticmethod
    def _key(info):
        try:
            return [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
        except Exception as error:
            report.failure("ChecksumCache._key", error)
            raise

    def lookup(self, path, info):
        """The cached hash if the file hasn't changed since it was hashed, else None."""
        try:
            entry = self._entries.get(path)
            if isinstance(entry, dict) and entry.get("key") == self._key(info):
                value = entry.get("sha256")
                if isinstance(value, str):
                    return value
            return None
        except Exception as error:
            report.failure("ChecksumCache.lookup", error)
            raise

    def store(self, path, info, value):
        try:
            self._entries[path] = {"key": self._key(info), "sha256": value}
            self._dirty = True
        except Exception as error:
            report.failure("ChecksumCache.store", error)
            raise

    def save(self):
        """Write atomically (temp file + rename). A failure is reported, never fatal."""
        try:
            if not self._dirty:
                return
            directory = os.path.dirname(self._path)
            try:
                os.makedirs(directory, exist_ok=True)
                handle, temporary = tempfile.mkstemp(dir=directory, prefix=".checksums-")
                with os.fdopen(handle, "w", encoding="utf-8") as output:
                    json.dump({"version": _CACHE_VERSION, "entries": self._entries}, output)
                os.replace(temporary, self._path)
                self._dirty = False
            except OSError as error:
                report.notice("could not save checksum cache: " + str(error), OBSCURA_PATH=self._path)
        except Exception as error:
            report.failure("ChecksumCache.save", error)
            raise


def cache_for(home, environ=None):
    """The user's checksum cache: $XDG_CACHE_HOME/obscura/checksums.json when that is set
    to an absolute path (XDG Base Directory spec), else <home>/.cache/obscura/..."""
    try:
        environ = os.environ if environ is None else environ
        base = environ.get("XDG_CACHE_HOME", "")
        if not base or not os.path.isabs(base):
            base = os.path.join(home, CHECKSUM_CACHE[0])
        return ChecksumCache(os.path.join(base, *CHECKSUM_CACHE[1:]))
    except Exception as error:
        report.failure("userfiles.cache_for", error)
        raise


def check_file(user_file, directory, cache):
    """FileStatus for one [[user_supplies]] entry."""
    try:
        path = os.path.join(directory, user_file.file)
        try:
            info = os.stat(path)
        except FileNotFoundError:
            return FileStatus(user_file.id, path, ABSENT)
        except OSError as error:
            return FileStatus(user_file.id, path, UNREADABLE, str(error))
        if not stat.S_ISREG(info.st_mode):
            return FileStatus(user_file.id, path, UNREADABLE, "not a regular file")
        if not user_file.sha256:
            return FileStatus(user_file.id, path, OK)

        value = cache.lookup(path, info) if cache is not None else None
        if value is None:
            try:
                value = sha256_of(path)
            except OSError as error:
                return FileStatus(user_file.id, path, UNREADABLE, str(error))
            if cache is not None:
                cache.store(path, info, value)
        if value in user_file.sha256:
            return FileStatus(user_file.id, path, OK)
        return FileStatus(user_file.id, path, WRONG_DUMP, "sha256 " + value)
    except Exception as error:
        report.failure("userfiles.check_file", error)
        raise


def check_user_files(manifest, home, cache=None):
    """{id: FileStatus} for every file the pack declares. Saves the cache if it changed."""
    try:
        directory = files_directory(home, manifest.files_dir)
        statuses = {}
        for user_file in manifest.user_supplies:
            statuses[user_file.id] = check_file(user_file, directory, cache)
        if cache is not None:
            cache.save()
        return statuses
    except Exception as error:
        report.failure("userfiles.check_user_files", error)
        raise
