"""Names and limits of pack format v1. Changing any of these is an API break for every
pack (ARCHITECTURE.md §17.4: the pack API is the stable contract)."""

import re

API_VERSION = 1
# Highest manifest feature level (pack.api_minor) this Obscura understands. A manifest
# with a higher api_minor isn't rejected for keys it doesn't know; its readiness is
# "Needs a newer Obscura" (ARCHITECTURE.md §17.4).
API_MINOR = 0

# Hyphenated lowercase names: files_dir, user-file ids, signature names.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Capability names as PACKS.md §2 spells them, which includes dots (vulkan-1.3). The same
# rule as capd's (obscura_capd.vocabulary.NAME_PATTERN); a unit test keeps them equal.
CAPABILITY_NAME_PATTERN = re.compile(r"^[a-z0-9]+([.-][a-z0-9]+)*$")
PACK_NAME_PATTERN = re.compile(r"^pack-[a-z0-9]+(-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+~-]*$")
SUFFIX_PATTERN = re.compile(r"^\.[a-z0-9]+$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
KERNEL_MODULE_PATTERN = re.compile(r"^[a-z0-9_-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HEX_PATTERN = re.compile(r"^(?:[0-9a-f]{2})+$")

MAX_MANIFEST_BYTES = 64 * 1024
MANIFEST_FILE = "pack.toml"

PLATFORMS = ("windows", "macos", "android", "linux-foreign", "sony", "nintendo", "xbox",
             "retro", "vr", "system")
TECHNIQUES = ("reimplementation", "container", "emulation", "static-recompilation",
              "hidden-os", "coprocessor", "remote")
STATUSES = ("mature", "usable", "experimental", "planned")
FILE_KINDS = ("firmware", "bios", "keys", "rom-set", "os-image", "media")
# A checksum identifies one known dump. OS images and media differ per build or per copy,
# so for those a present file is enough (ARCHITECTURE.md §17.1).
CHECKSUM_OPTIONAL_KINDS = ("os-image", "media")

# Readiness states (ARCHITECTURE.md §17.3).
READY = "ready"
REMOTE = "remote"
MISSING_HARDWARE = "missing-hardware"
INSUFFICIENT_HARDWARE = "insufficient-hardware"
NEEDS_PACK = "needs-pack"
MISSING_FILES = "missing-files"
UNEVALUABLE = "unevaluable"
NEEDS_NEWER_OBSCURA = "needs-newer-obscura"
STATES = (READY, REMOTE, MISSING_HARDWARE, INSUFFICIENT_HARDWARE, NEEDS_PACK, MISSING_FILES,
          UNEVALUABLE, NEEDS_NEWER_OBSCURA)
# States in which the dispatcher may route to the pack (ARCHITECTURE.md §18.2).
RUNNABLE_STATES = (READY, REMOTE)

# Locations (ARCHITECTURE.md §17.1).
FACTORY_ROOT = "/usr/share/obscura/packs"
INSTALLED_ROOT = "/var/lib/obscura/packs"
SIGNATURES_FILE = "/usr/share/obscura/signatures.toml"
CURRENT_LINK = "current"
REMOVED_MARKER = "removed"
USER_FILES_DIR = ("Obscura", "firmware")                     # under the user's home
CHECKSUM_CACHE = (".cache", "obscura", "checksums.json")     # under $XDG_CACHE_HOME or ~/.cache
