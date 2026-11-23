"""Parsing and validating pack manifests (pack.toml, api 1) and the core signature registry.

The format is ARCHITECTURE.md §17.1. Validation is strict: an unknown table or key is an
error. It also fails closed: validate_manifest() returns a Manifest only when every check
passed, and any unexpected exception makes the manifest invalid and is reported, never a
half-checked Manifest.
"""

import os
import posixpath
import tomllib
from dataclasses import dataclass

from obscura_capd import report
from obscura_packs.constants import (
    API_MINOR,
    API_VERSION,
    CAPABILITY_NAME_PATTERN,
    CHECKSUM_OPTIONAL_KINDS,
    FILE_KINDS,
    HEX_PATTERN,
    IDENTIFIER_PATTERN,
    KERNEL_MODULE_PATTERN,
    MAX_MANIFEST_BYTES,
    NAME_PATTERN,
    PACK_NAME_PATTERN,
    PLATFORMS,
    SHA256_PATTERN,
    STATUSES,
    SUFFIX_PATTERN,
    TECHNIQUES,
    VERSION_PATTERN,
)


class ManifestError(ValueError):
    """A manifest is malformed. Expected, so it is reported as a problem, not a crash."""


@dataclass(frozen=True)
class UserFile:
    id: str
    label: str
    kind: str
    file: str
    sha256: tuple
    required: bool


@dataclass(frozen=True)
class Manifest:
    name: str
    api: int
    version: str
    platform: str
    technique: str
    summary: str
    status: str
    runtime: bool
    files_dir: str
    magic: tuple
    installers: tuple
    extensions: tuple
    requires: tuple
    recommends: tuple
    depends: tuple
    user_supplies: tuple
    remote: bool
    actions: tuple
    triggers: tuple
    kernel_modules: tuple
    devices: tuple
    source: str
    api_minor: int = 0
    # True when api_minor is higher than this Obscura supports: only [pack] was checked,
    # and readiness is "Needs a newer Obscura". Never routed to.
    needs_newer: bool = False


# Allowed keys per table. Anything else is an error (strict, catches typos).
_TABLE_KEYS = {
    "pack": {"name", "api", "api_minor", "version", "platform", "technique", "summary", "status", "runtime", "files_dir"},
    "handles": {"magic", "installers", "extensions"},
    "requires": {"capabilities"},
    "recommends": {"capabilities"},
    "depends": {"runtime"},
    "fallback": {"remote"},
    "provides": {"actions", "triggers"},
    "touches": {"kernel_modules", "devices"},
}
_USER_FILE_KEYS = {"id", "label", "kind", "file", "sha256", "required"}
_TOP_LEVEL = set(_TABLE_KEYS) | {"user_supplies"}


# -- typed field access -------------------------------------------------------------------

def _is_type(value, kind):
    """isinstance, except bool never counts as int (`api = true` is not a version)."""
    try:
        if kind is int and isinstance(value, bool):
            return False
        return isinstance(value, kind)
    except Exception as error:
        report.failure("manifest._is_type", error)
        raise


def _field(table, key, kind, where, default=None, required=False):
    """One field of `table`, type-checked. Missing optional fields give `default`."""
    try:
        if key not in table:
            if required:
                raise ManifestError("missing field '" + where + "." + key + "'")
            return default
        value = table[key]
        if not _is_type(value, kind):
            raise ManifestError("field '" + where + "." + key + "' must be " + _type_name(kind))
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._field", error)
        raise


def _type_name(kind):
    try:
        return {str: "a string", int: "an integer", bool: "true or false", list: "a list",
                dict: "a table"}.get(kind, kind.__name__)
    except Exception as error:
        report.failure("manifest._type_name", error)
        raise


def _string_list(table, key, where, pattern=None, check=None):
    """A list of unique strings, each matching `pattern` and passing `check` (if given)."""
    try:
        values = _field(table, key, list, where, default=[])
        seen = set()
        for value in values:
            if not isinstance(value, str):
                raise ManifestError("'" + where + "." + key + "' must be a list of strings")
            if pattern is not None and not pattern.match(value):
                raise ManifestError("invalid entry '" + value + "' in '" + where + "." + key + "'")
            if check is not None:
                check(value)
            if value in seen:
                raise ManifestError("duplicate entry '" + value + "' in '" + where + "." + key + "'")
            seen.add(value)
        return tuple(values)
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._string_list", error)
        raise


def _non_blank(value, where):
    try:
        if not value.strip():
            raise ManifestError("'" + where + "' is empty")
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._non_blank", error)
        raise


def _one_of(value, choices, where):
    try:
        if value not in choices:
            raise ManifestError("'" + where + "' must be one of " + ", ".join(choices) + " (got '" + str(value) + "')")
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._one_of", error)
        raise


def _tables(data):
    """Top-level tables, with unknown tables and keys rejected."""
    try:
        for key in data:
            if key not in _TOP_LEVEL:
                raise ManifestError("unknown table '" + key + "'")
        tables = {}
        for name, allowed in _TABLE_KEYS.items():
            table = data.get(name, {})
            if not isinstance(table, dict):
                raise ManifestError("'" + name + "' must be a table")
            for key in table:
                if key not in allowed:
                    raise ManifestError("unknown key '" + name + "." + key + "'")
            tables[name] = table
        if "pack" not in data:
            raise ManifestError("missing [pack] table")
        return tables
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._tables", error)
        raise


# -- section validators -------------------------------------------------------------------

def _validate_pack(table):
    try:
        values = {
            "name": _field(table, "name", str, "pack", required=True),
            "api": _field(table, "api", int, "pack", required=True),
            "version": _field(table, "version", str, "pack", required=True),
            "platform": _field(table, "platform", str, "pack", required=True),
            "technique": _field(table, "technique", str, "pack", required=True),
            "summary": _field(table, "summary", str, "pack", required=True),
            "status": _field(table, "status", str, "pack", default="experimental"),
            "runtime": _field(table, "runtime", bool, "pack", default=False),
        }
        if values["api"] > API_VERSION:
            raise ManifestError("api " + str(values["api"]) + " needs a newer Obscura")
        if values["api"] != API_VERSION:
            raise ManifestError("unsupported api " + str(values["api"]))
        if not PACK_NAME_PATTERN.match(values["name"]):
            raise ManifestError("invalid pack name '" + values["name"] + "' (pack-<lowercase-and-dashes>)")
        if not VERSION_PATTERN.match(values["version"]):
            raise ManifestError("invalid version '" + values["version"] + "'")
        _one_of(values["platform"], PLATFORMS, "pack.platform")
        _one_of(values["technique"], TECHNIQUES, "pack.technique")
        _one_of(values["status"], STATUSES, "pack.status")
        _non_blank(values["summary"], "pack.summary")

        files_dir = _field(table, "files_dir", str, "pack", default=values["name"][len("pack-"):])
        if not NAME_PATTERN.match(files_dir):
            raise ManifestError("invalid files_dir '" + files_dir + "' (one lowercase name, e.g. 'ps1')")
        values["files_dir"] = files_dir
        return values
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_pack", error)
        raise


def _validate_handles(table, platform, signatures):
    try:
        def registered(name):
            if name not in signatures:
                raise ManifestError("unknown signature '" + name + "' (not in the core signature registry)")

        magic = _string_list(table, "magic", "handles", NAME_PATTERN, registered)
        installers = _string_list(table, "installers", "handles", SUFFIX_PATTERN)
        extensions = _string_list(table, "extensions", "handles", SUFFIX_PATTERN)
        overlap = set(installers) & set(extensions)
        if overlap:
            raise ManifestError("listed as both installer and extension: " + ", ".join(sorted(overlap)))
        if platform != "system" and not (magic or installers or extensions):
            raise ManifestError("[handles] is empty: a " + platform + " pack must handle something")
        return magic, installers, extensions
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_handles", error)
        raise


def _validate_capabilities(tables):
    try:
        requires = _string_list(tables["requires"], "capabilities", "requires", CAPABILITY_NAME_PATTERN)
        recommends = _string_list(tables["recommends"], "capabilities", "recommends", CAPABILITY_NAME_PATTERN)
        both = set(requires) & set(recommends)
        if both:
            raise ManifestError("both required and recommended: " + ", ".join(sorted(both)))
        return requires, recommends
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_capabilities", error)
        raise


def _validate_depends(table, name, runtime):
    try:
        depends = _string_list(table, "runtime", "depends", PACK_NAME_PATTERN)
        if name in depends:
            raise ManifestError("a pack cannot depend on itself")
        if runtime and depends:
            raise ManifestError("a runtime pack cannot depend on other packs (one level deep only)")
        return depends
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_depends", error)
        raise


def _validate_file_name(value):
    """A bare file name: never a path, so a pack can't point outside its files directory."""
    try:
        bad = ("/" in value or "\\" in value or "\0" in value or value.startswith(".")
               or value != value.strip() or not value)
        if bad:
            raise ManifestError("user_supplies file '" + value + "' must be a plain file name")
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_file_name", error)
        raise


def _validate_user_supplies(entries):
    try:
        if not isinstance(entries, list):
            raise ManifestError("'user_supplies' must be an array of tables ([[user_supplies]])")
        files = []
        ids = set()
        names = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ManifestError("each [[user_supplies]] entry must be a table")
            for key in entry:
                if key not in _USER_FILE_KEYS:
                    raise ManifestError("unknown key 'user_supplies." + key + "'")
            file_id = _field(entry, "id", str, "user_supplies", required=True)
            label = _field(entry, "label", str, "user_supplies", required=True)
            kind = _field(entry, "kind", str, "user_supplies", required=True)
            file_name = _field(entry, "file", str, "user_supplies", required=True)
            required = _field(entry, "required", bool, "user_supplies", default=True)
            if not NAME_PATTERN.match(file_id):
                raise ManifestError("invalid user_supplies id '" + file_id + "'")
            if file_id in ids:
                raise ManifestError("duplicate user_supplies id '" + file_id + "'")
            _non_blank(label, "user_supplies.label")
            _one_of(kind, FILE_KINDS, "user_supplies.kind")
            _validate_file_name(file_name)
            if file_name in names:
                raise ManifestError("two user_supplies entries name the file '" + file_name + "'")
            sha256 = _string_list(entry, "sha256", "user_supplies." + file_id, SHA256_PATTERN)
            if not sha256 and kind not in CHECKSUM_OPTIONAL_KINDS:
                raise ManifestError("user_supplies '" + file_id + "' (" + kind + ") needs at least one sha256")
            ids.add(file_id)
            names.add(file_name)
            files.append(UserFile(id=file_id, label=label, kind=kind, file=file_name,
                                  sha256=sha256, required=required))
        return tuple(files)
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_user_supplies", error)
        raise


def _validate_device(value):
    try:
        normalized = posixpath.normpath(value)
        if not value.startswith("/dev/") or normalized != value or ".." in value.split("/"):
            raise ManifestError("touches.devices entry '" + value + "' must be a normalized path under /dev/")
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._validate_device", error)
        raise


# -- entry points -------------------------------------------------------------------------

def parse_manifest(text, source, signatures, directory_name=None):
    """Parse and validate one manifest. Returns a Manifest or raises ManifestError.

    `signatures` is the set of names in the core signature registry. `directory_name`, when
    given, must equal the pack name. Unexpected exceptions are reported and re-raised; use
    validate_manifest() for the fail-closed form.
    """
    try:
        if len(text.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest is larger than " + str(MAX_MANIFEST_BYTES) + " bytes")
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise ManifestError("not valid TOML: " + str(error)) from error

        api_minor = _api_minor(data)
        if api_minor > API_MINOR:
            return _parse_newer(data, source, directory_name, api_minor)

        tables = _tables(data)
        pack = _validate_pack(tables["pack"])
        if directory_name is not None and directory_name != pack["name"]:
            raise ManifestError("directory '" + directory_name + "' must be named after the pack ('" + pack["name"] + "')")
        magic, installers, extensions = _validate_handles(tables["handles"], pack["platform"], signatures)
        requires, recommends = _validate_capabilities(tables)
        depends = _validate_depends(tables["depends"], pack["name"], pack["runtime"])
        user_supplies = _validate_user_supplies(data.get("user_supplies", []))
        remote = _field(tables["fallback"], "remote", bool, "fallback", default=False)
        actions = _string_list(tables["provides"], "actions", "provides", IDENTIFIER_PATTERN)
        triggers = _string_list(tables["provides"], "triggers", "provides", IDENTIFIER_PATTERN)
        kernel_modules = _string_list(tables["touches"], "kernel_modules", "touches", KERNEL_MODULE_PATTERN)
        devices = _string_list(tables["touches"], "devices", "touches", check=_validate_device)

        return Manifest(
            magic=magic, installers=installers, extensions=extensions,
            requires=requires, recommends=recommends, depends=depends,
            user_supplies=user_supplies, remote=remote, actions=actions, triggers=triggers,
            kernel_modules=kernel_modules, devices=devices, source=source, api_minor=api_minor, **pack,
        )
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest.parse_manifest", error)
        raise


def _api_minor(data):
    """pack.api_minor: the manifest's feature level within api 1 (default 0)."""
    try:
        pack = data.get("pack")
        if not isinstance(pack, dict):
            raise ManifestError("missing [pack] table")
        value = _field(pack, "api_minor", int, "pack", default=0)
        if value < 0:
            raise ManifestError("'pack.api_minor' must not be negative")
        return value
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._api_minor", error)
        raise


def _parse_newer(data, source, directory_name, api_minor):
    """A manifest written for a newer Obscura (higher api_minor). Keys this Obscura doesn't
    know aren't errors here: they may be the newer features. Only the [pack] identity is
    validated, so the pack can be listed with "Needs a newer Obscura"; nothing else in it
    is trusted or used."""
    try:
        pack = _validate_pack(data["pack"])
        if directory_name is not None and directory_name != pack["name"]:
            raise ManifestError("directory '" + directory_name + "' must be named after the pack ('" + pack["name"] + "')")
        return Manifest(
            magic=(), installers=(), extensions=(), requires=(), recommends=(), depends=(),
            user_supplies=(), remote=False, actions=(), triggers=(), kernel_modules=(), devices=(),
            source=source, api_minor=api_minor, needs_newer=True, **pack,
        )
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest._parse_newer", error)
        raise


def validate_manifest(text, source, signatures, directory_name=None):
    """Fail-closed form of parse_manifest. Returns (Manifest, None) only if every check
    passed. Otherwise returns (None, reason) and never raises: a malformed manifest gives
    its reason, and an unexpected exception is reported through report.failure and makes
    the manifest invalid."""
    try:
        return parse_manifest(text, source, signatures, directory_name), None
    except ManifestError as error:
        return None, str(error)
    except Exception as error:
        try:
            report.failure("manifest.validate_manifest", error)
        except Exception:
            pass
        return None, "could not be checked (internal error: " + type(error).__name__ + ")"


def load_manifest_file(path, signatures, check_directory=True):
    """Read and validate a pack.toml. Returns (Manifest, None) or (None, reason); never
    raises. With check_directory, the containing directory must be named after the pack."""
    try:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES:
                return None, "manifest is larger than " + str(MAX_MANIFEST_BYTES) + " bytes"
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return None, "cannot read manifest: " + str(error)
        directory = os.path.basename(os.path.dirname(os.path.abspath(path))) if check_directory else None
        return validate_manifest(text, path, signatures, directory)
    except Exception as error:
        try:
            report.failure("manifest.load_manifest_file", error)
        except Exception:
            pass
        return None, "could not be checked (internal error: " + type(error).__name__ + ")"


@dataclass(frozen=True)
class Signature:
    name: str
    summary: str
    magic: str
    offset: int
    mask: str


def parse_signatures(text, source):
    """Parse the core signature registry. Returns {name: Signature} or raises ManifestError.

    [signature.<name>] tables with summary, magic (hex), optional offset and mask (hex, same
    length as magic). The dispatcher (task 0.24) turns these into binfmt_misc entries.
    """
    try:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise ManifestError("not valid TOML: " + str(error)) from error
        for key in data:
            if key not in ("api", "signature"):
                raise ManifestError("unknown key '" + key + "' in " + source)
        if _field(data, "api", int, "signatures", required=True) != API_VERSION:
            raise ManifestError("unsupported signature registry api")
        entries = _field(data, "signature", dict, "signatures", default={})
        signatures = {}
        for name, entry in entries.items():
            if not NAME_PATTERN.match(name):
                raise ManifestError("invalid signature name '" + name + "'")
            if not isinstance(entry, dict):
                raise ManifestError("signature '" + name + "' must be a table")
            for key in entry:
                if key not in ("summary", "magic", "offset", "mask"):
                    raise ManifestError("unknown key 'signature." + name + "." + key + "'")
            summary = _non_blank(_field(entry, "summary", str, "signature." + name, required=True), "signature." + name + ".summary")
            magic = _field(entry, "magic", str, "signature." + name, required=True)
            offset = _field(entry, "offset", int, "signature." + name, default=0)
            mask = _field(entry, "mask", str, "signature." + name, default="")
            if not HEX_PATTERN.match(magic):
                raise ManifestError("signature '" + name + "' magic must be lowercase hex bytes")
            if mask and (not HEX_PATTERN.match(mask) or len(mask) != len(magic)):
                raise ManifestError("signature '" + name + "' mask must be hex bytes, as long as magic")
            if offset < 0:
                raise ManifestError("signature '" + name + "' offset must not be negative")
            signatures[name] = Signature(name=name, summary=summary, magic=magic, offset=offset, mask=mask)
        return signatures
    except ManifestError:
        raise
    except Exception as error:
        report.failure("manifest.parse_signatures", error)
        raise


def load_signatures(path):
    """The registry's signature names. A missing or invalid registry is reported and gives
    an empty set, so every manifest that names a signature is invalid (fail closed)."""
    try:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return frozenset(parse_signatures(handle.read(), path))
        except (OSError, UnicodeDecodeError, ManifestError) as error:
            report.problem("signatures", "signature registry unusable: " + str(error), OBSCURA_PATH=path)
            return frozenset()
    except Exception as error:
        report.failure("manifest.load_signatures", error)
        return frozenset()
