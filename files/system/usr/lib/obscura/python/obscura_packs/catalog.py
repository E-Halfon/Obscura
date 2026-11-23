"""The installed-pack catalog: which packs exist on this device, and from where.

Read side only (task 0.21); the pack manager (task 0.22) writes the installed root.
ARCHITECTURE.md §17.1:
  <factory>/<name>/pack.toml                     shipped in the image, read-only
  <installed>/<name>/<version>/pack.toml         installed by the pack manager
  <installed>/<name>/current -> <version>        the active installed version
  <installed>/<name>/removed                     hides the pack, factory copy included

An installed `current` wins over the factory copy. A broken `current` falls back to the
factory copy and is reported. Only factory packs may be runtime packs (`runtime = true`)
until signed repository packs (task 0.23); an installed one falls back to the factory copy.

Not yet checked: pack signatures (ARCHITECTURE.md §17.4). Factory packs are covered by the
image's signature. Installed packs are trusted as they are until task 0.23 adds signature
verification here and in the pack manager. Every bad manifest is reported and skipped; it never stops
the others from loading.
"""

import os
from dataclasses import dataclass, field

from obscura_capd import report
from obscura_packs.constants import (
    CURRENT_LINK,
    FACTORY_ROOT,
    INSTALLED_ROOT,
    MANIFEST_FILE,
    PACK_NAME_PATTERN,
    REMOVED_MARKER,
    VERSION_PATTERN,
)
from obscura_packs.manifest import load_manifest_file

FACTORY = "factory"
INSTALLED = "installed"
EXTRA = "extra"  # development and test roots only (obscura-pack --extra-root)


@dataclass(frozen=True)
class InstalledPack:
    manifest: object
    origin: str
    path: str


@dataclass
class Catalog:
    packs: dict = field(default_factory=dict)       # name -> InstalledPack
    problems: list = field(default_factory=list)    # (path, reason)

    def get(self, name):
        try:
            return self.packs.get(name)
        except Exception as error:
            report.failure("Catalog.get", error)
            raise

    def names(self):
        try:
            return sorted(self.packs)
        except Exception as error:
            report.failure("Catalog.names", error)
            raise


def _note(catalog, path, reason):
    """Record and report one problem with one pack."""
    try:
        catalog.problems.append((path, reason))
        report.problem("catalog", reason, OBSCURA_PATH=path)
    except Exception as error:
        report.failure("catalog._note", error)
        raise


def _pack_directories(root):
    """Names of the pack directories in a root. A missing root is simply empty."""
    try:
        try:
            entries = sorted(os.listdir(root))
        except (FileNotFoundError, NotADirectoryError):
            return []
        return [entry for entry in entries if os.path.isdir(os.path.join(root, entry))]
    except Exception as error:
        report.failure("catalog._pack_directories", error)
        raise


def _load_tree(root, signatures, origin, catalog):
    """{name: InstalledPack} for a factory-style root (<root>/<name>/pack.toml)."""
    try:
        packs = {}
        for name in _pack_directories(root):
            path = os.path.join(root, name, MANIFEST_FILE)
            if not PACK_NAME_PATTERN.match(name):
                _note(catalog, os.path.join(root, name), "not a pack directory name: " + name)
                continue
            manifest, reason = load_manifest_file(path, signatures)
            if manifest is None:
                _note(catalog, path, "skipping pack: " + reason)
                continue
            packs[name] = InstalledPack(manifest=manifest, origin=origin, path=os.path.join(root, name))
        return packs
    except Exception as error:
        report.failure("catalog._load_tree", error)
        raise


def _load_installed(base, name, signatures, catalog):
    """The pack `current` points at in <installed>/<name>, or None if there is none or it
    is broken (reported)."""
    try:
        link = os.path.join(base, CURRENT_LINK)
        if not os.path.lexists(link):
            return None
        if not os.path.islink(link):
            _note(catalog, link, "'current' is not a symlink")
            return None
        target = os.readlink(link)
        # current names a sibling version directory, nothing else.
        if not VERSION_PATTERN.match(target):
            _note(catalog, link, "'current' must point at a version directory beside it (points at " + repr(target) + ")")
            return None
        version_dir = os.path.join(base, target)
        manifest, reason = load_manifest_file(os.path.join(version_dir, MANIFEST_FILE), signatures,
                                              check_directory=False)
        if manifest is None:
            _note(catalog, version_dir, "installed version unusable: " + reason)
            return None
        if manifest.name != name:
            _note(catalog, version_dir, "installed manifest is for " + manifest.name + ", not " + name)
            return None
        if manifest.version != target:
            _note(catalog, version_dir, "installed manifest is version " + manifest.version + ", directory says " + target)
            return None
        return InstalledPack(manifest=manifest, origin=INSTALLED, path=version_dir)
    except Exception as error:
        report.failure("catalog._load_installed", error)
        raise


def _not_eligible_as_runtime(pack, catalog):
    """Only factory packs (shipped in the image) may declare runtime = true for now; signed
    repository packs become eligible with task 0.23 (ARCHITECTURE.md §17.4). Otherwise any
    installed pack could make itself a dependency target. Reports and returns None."""
    try:
        _note(catalog, pack.path, pack.manifest.name + " declares runtime = true, but only packs shipped in the"
              " image may be runtime packs (signed repository packs: task 0.23)")
        return None
    except Exception as error:
        report.failure("catalog._not_eligible_as_runtime", error)
        raise


def _check_dependencies(catalog):
    """Cross-pack rules (ARCHITECTURE.md §17.4): a pack may depend only on runtime packs.
    A dependency that isn't installed is fine here; readiness reports it. A pack that
    breaks the rule is reported and dropped."""
    try:
        for name in catalog.names():
            pack = catalog.packs[name]
            for dependency in pack.manifest.depends:
                target = catalog.packs.get(dependency)
                if target is not None and not target.manifest.runtime:
                    _note(catalog, pack.path, name + " depends on " + dependency
                          + ", which is not a runtime pack; packs depend only on runtime packs")
                    del catalog.packs[name]
                    break
    except Exception as error:
        report.failure("catalog._check_dependencies", error)
        raise


def load_catalog(signatures, factory_root=FACTORY_ROOT, installed_root=INSTALLED_ROOT, extra_roots=()):
    """Every pack on this device. Never raises for a bad pack: it's skipped and reported."""
    try:
        catalog = Catalog()
        factory = _load_tree(factory_root, signatures, FACTORY, catalog)

        names = set(factory) | {name for name in _pack_directories(installed_root) if PACK_NAME_PATTERN.match(name)}
        for name in sorted(names):
            base = os.path.join(installed_root, name)
            if os.path.lexists(os.path.join(base, REMOVED_MARKER)):
                continue
            installed = _load_installed(base, name, signatures, catalog)
            if installed is not None and installed.manifest.runtime:
                installed = _not_eligible_as_runtime(installed, catalog)
            chosen = installed or factory.get(name)
            if chosen is None:
                continue
            if installed is None and os.path.lexists(os.path.join(base, CURRENT_LINK)) and name in factory:
                report.notice("using the factory copy of " + name, OBSCURA_PACK=name)
            catalog.packs[name] = chosen

        for root in extra_roots:
            for name, pack in _load_tree(root, signatures, EXTRA, catalog).items():
                if pack.manifest.runtime:
                    _not_eligible_as_runtime(pack, catalog)
                    continue
                if name in catalog.packs:
                    _note(catalog, pack.path, "duplicate pack " + name + " (already loaded from " + catalog.packs[name].path + ")")
                    continue
                catalog.packs[name] = pack

        _check_dependencies(catalog)
        return catalog
    except Exception as error:
        report.failure("catalog.load_catalog", error)
        raise
