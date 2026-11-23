"""obscura-pack: developer and test tool for pack manifests and readiness.

Never required of users (ARCHITECTURE.md §18.1, §19); the pack manager GUI (task 0.26)
shows the same results.

  obscura-pack validate PATH...      check manifests (a pack directory or a pack.toml)
  obscura-pack list [--json]         packs on this device and where they come from
  obscura-pack readiness [NAME...] [--json]
                                     readiness for this user on this device

Exit codes: validate: 0 all valid, 1 any invalid. readiness: 0 every listed pack is
ready or remote, 1 otherwise. 2 on usage errors or an unknown pack name.

--factory-root, --installed-root, --signatures, and --home override the standard
locations; --extra-root adds a root of test packs (never replaces a pack).
"""

import argparse
import json
import os
import sys
from dataclasses import asdict

from obscura_capd import report
from obscura_packs import capabilities, catalog as catalog_module, readiness, userfiles
from obscura_packs.constants import (
    FACTORY_ROOT,
    INSTALLED_ROOT,
    MANIFEST_FILE,
    RUNNABLE_STATES,
    SIGNATURES_FILE,
)
from obscura_packs.manifest import load_manifest_file, load_signatures

EXIT_OK = 0
EXIT_NOT_OK = 1
EXIT_USAGE = 2


def _print(text):
    try:
        print(text, flush=True)
    except Exception as error:
        # stdout is unusable (closed pipe, bad encoding): report on stderr instead.
        _error("could not write output: " + repr(error))


def _error(message):
    try:
        print("obscura-pack: " + message, file=sys.stderr, flush=True)
    except Exception:
        pass  # stderr itself is unusable: there is nowhere left to report


def _parse(argv):
    try:
        parser = argparse.ArgumentParser(prog="obscura-pack", description="Check Camera Obscura packs.")
        parser.add_argument("--factory-root", default=FACTORY_ROOT)
        parser.add_argument("--installed-root", default=INSTALLED_ROOT)
        parser.add_argument("--extra-root", action="append", default=[], help="extra pack root (tests only)")
        parser.add_argument("--signatures", default=SIGNATURES_FILE)
        parser.add_argument("--home", default=os.path.expanduser("~"))
        commands = parser.add_subparsers(dest="command", required=True)
        validate = commands.add_parser("validate", help="check manifests")
        validate.add_argument("paths", nargs="+")
        listing = commands.add_parser("list", help="packs on this device")
        listing.add_argument("--json", action="store_true")
        ready = commands.add_parser("readiness", help="readiness on this device")
        ready.add_argument("names", nargs="*")
        ready.add_argument("--json", action="store_true")
        return parser.parse_args(argv)
    except SystemExit:
        raise
    except Exception as error:
        _error("bad arguments: " + str(error))
        raise


def _validate(args, signatures):
    try:
        status = EXIT_OK
        for path in args.paths:
            manifest_path = os.path.join(path, MANIFEST_FILE) if os.path.isdir(path) else path
            manifest, reason = load_manifest_file(manifest_path, signatures)
            if manifest is None:
                _print("INVALID " + manifest_path + ": " + reason)
                status = EXIT_NOT_OK
            else:
                _print("OK " + manifest.name + " " + manifest.version + " (" + manifest_path + ")")
        return status
    except Exception as error:
        report.failure("cli._validate", error)
        raise


def _catalog(args, signatures):
    try:
        return catalog_module.load_catalog(signatures, args.factory_root, args.installed_root, args.extra_root)
    except Exception as error:
        report.failure("cli._catalog", error)
        raise


def _list(args, signatures):
    try:
        catalog = _catalog(args, signatures)
        rows = [{"name": name, "version": catalog.packs[name].manifest.version,
                 "origin": catalog.packs[name].origin, "path": catalog.packs[name].path}
                for name in catalog.names()]
        if args.json:
            _print(json.dumps({"packs": rows, "problems": [list(p) for p in catalog.problems]}, indent=2))
        else:
            for row in rows:
                _print(row["name"] + "\t" + row["version"] + "\t" + row["origin"] + "\t" + row["path"])
        return EXIT_OK
    except Exception as error:
        report.failure("cli._list", error)
        raise


def _readiness(args, signatures):
    try:
        catalog = _catalog(args, signatures)
        unknown = [name for name in args.names if catalog.get(name) is None]
        if unknown:
            _error("no such pack: " + ", ".join(unknown))
            return EXIT_USAGE
        # Ask capd only when some pack has hardware requirements.
        needs_capd = any(pack.manifest.requires or pack.manifest.recommends for pack in catalog.packs.values())
        present = capabilities.present_capabilities() if needs_capd else frozenset()
        vocabulary = {}
        if needs_capd:
            try:
                vocabulary = capabilities.capability_vocabulary()
            except Exception as error:
                # Without the vocabulary, hardware can't be judged: treat it like capd not
                # answering, so each affected pack is unevaluable and the rest still report.
                report.failure("cli._readiness", error)
                present = None
        results = readiness.evaluate_catalog(catalog, present, vocabulary, args.home,
                                             cache=userfiles.cache_for(args.home))
        names = args.names or catalog.names()
        if args.json:
            _print(json.dumps({name: asdict(results[name]) for name in names}, indent=2))
        else:
            for name in names:
                result = results[name]
                _print(name + ": " + result.state)
                for reason in result.reasons:
                    _print("  - " + reason.message + (" [" + reason.fix + "]" if reason.fix else "") + " (" + reason.code + ")")
                for note in result.notes:
                    _print("  note: " + note)
        return EXIT_OK if all(results[name].state in RUNNABLE_STATES for name in names) else EXIT_NOT_OK
    except Exception as error:
        report.failure("cli._readiness", error)
        raise


def main(argv=None):
    try:
        report.set_identifier("obscura-pack")
        args = _parse(sys.argv[1:] if argv is None else argv)
        signatures = load_signatures(args.signatures)
        if args.command == "validate":
            return _validate(args, signatures)
        if args.command == "list":
            return _list(args, signatures)
        if args.command == "readiness":
            return _readiness(args, signatures)
        _error("unknown command " + args.command)
        return EXIT_USAGE
    except SystemExit as exit_request:
        return exit_request.code if isinstance(exit_request.code, int) else EXIT_USAGE
    except Exception as error:
        report.failure("cli.main", error)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
