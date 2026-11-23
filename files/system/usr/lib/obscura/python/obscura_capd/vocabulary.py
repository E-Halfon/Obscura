"""Loading and validating capability declarations (/usr/share/obscura/capabilities.d/).

The declarations are the vocabulary: capd reports exactly these names, each as present or
absent. A bad declaration is reported and skipped; it never stops the other capabilities
from being reported.
"""

import os
import re
import tomllib
from dataclasses import dataclass

from obscura_capd import report
from obscura_capd.constants import API_VERSION, KINDS, TARGET_PREFIX, TARGET_SUFFIX

# Lowercase letters, digits, hyphens; no underscores, so the object-path mapping
# (hyphen -> underscore) stays one-to-one.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class DeclarationError(ValueError):
    """A declaration file is malformed. Expected, so it is reported as a problem, not a crash."""


@dataclass(frozen=True)
class Declaration:
    name: str
    api: int
    kind: str
    target: str
    summary: str
    source: str
    # Whether the user can fix an absence by connecting something (a webcam, a modem, the
    # Neo). Readiness uses it to choose Missing hardware over Insufficient hardware
    # (ARCHITECTURE.md §17.3). It's independent of `kind`, which says how it's detected.
    attachable: bool = False


def target_for(name):
    """The systemd target that represents capability `name`."""
    try:
        return TARGET_PREFIX + name + TARGET_SUFFIX
    except Exception as error:
        report.failure("vocabulary.target_for", error)
        raise


def parse_declaration(text, source):
    """Parse and validate one declaration. Raises DeclarationError if it is invalid."""
    try:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise DeclarationError("not valid TOML: " + str(error)) from error

        table = data.get("capability")
        if not isinstance(table, dict):
            raise DeclarationError("missing [capability] table")

        values = {}
        for key, kind in (("name", str), ("api", int), ("kind", str), ("target", str), ("summary", str)):
            if key not in table:
                raise DeclarationError("missing field '" + key + "'")
            value = table[key]
            # bool is a subclass of int in Python; `api = true` is not a version.
            if not isinstance(value, kind) or isinstance(value, bool):
                raise DeclarationError("field '" + key + "' must be " + kind.__name__)
            values[key] = value

        if "attachable" not in table:
            raise DeclarationError("missing field 'attachable'")
        if not isinstance(table["attachable"], bool):
            raise DeclarationError("field 'attachable' must be true or false")
        values["attachable"] = table["attachable"]

        if not NAME_PATTERN.match(values["name"]):
            raise DeclarationError("invalid name '" + values["name"] + "'")
        if values["api"] != API_VERSION:
            raise DeclarationError("unsupported api " + str(values["api"]))
        if values["kind"] not in KINDS:
            raise DeclarationError("unknown kind '" + values["kind"] + "'")
        if values["target"] != target_for(values["name"]):
            raise DeclarationError("target must be " + target_for(values["name"]))
        if not values["summary"].strip():
            raise DeclarationError("empty summary")

        return Declaration(source=source, **values)
    except DeclarationError:
        raise
    except Exception as error:
        report.failure("vocabulary.parse_declaration", error)
        raise


def load_vocabulary(directory):
    """Load every *.toml in `directory`. Returns {name: Declaration}, sorted by file name.

    Invalid files, duplicate names, and file/name mismatches are reported and skipped.
    A missing directory gives an empty vocabulary, reported as a problem.
    """
    try:
        vocabulary = {}
        try:
            entries = sorted(os.listdir(directory))
        except FileNotFoundError:
            report.problem("vocabulary", "declaration directory missing", OBSCURA_PATH=directory)
            return vocabulary

        for entry in entries:
            if not entry.endswith(".toml"):
                continue
            path = os.path.join(directory, entry)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    declaration = parse_declaration(handle.read(), path)
            except (DeclarationError, OSError, UnicodeDecodeError) as error:
                report.problem("vocabulary", "skipping declaration: " + str(error), OBSCURA_PATH=path)
                continue

            if entry != declaration.name + ".toml":
                report.problem("vocabulary", "file name must be " + declaration.name + ".toml", OBSCURA_PATH=path)
                continue
            if declaration.name in vocabulary:
                report.problem("vocabulary", "duplicate capability " + declaration.name, OBSCURA_PATH=path)
                continue
            vocabulary[declaration.name] = declaration
        return vocabulary
    except Exception as error:
        report.failure("vocabulary.load_vocabulary", error)
        raise
