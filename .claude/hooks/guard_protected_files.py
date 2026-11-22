#!/usr/bin/env python3
"""Keep firmware, BIOS, ROMs, keys, and OS images out of the repo.

Enforces ARCHITECTURE.md §14.2: packs declare user-supplied files by name and
checksum; the files themselves never enter the repository.

Modes:
  (no arguments)     Claude Code PreToolUse hook. Reads the hook JSON on stdin.
                     Exit 2 blocks the tool call; stderr is shown to Claude.
  --staged           git pre-commit hook. Checks staged files. Exit 1 blocks.
  --check PATH ...   Check the given paths and report. Exit 1 if any is protected.
"""

import json
import os
import subprocess
import sys

# Directories whose contents must never be committed.
PROTECTED_DIRS = {"firmware", "bios", "keys", "roms"}

# Exact file names that are always secrets.
PROTECTED_NAMES = {"cosign.key", "cosign.private", "prod.keys", "title.keys"}

# File types: keys, firmware, disk/OS images, and console game/ROM formats.
PROTECTED_SUFFIXES = {
    # keys and secrets
    ".key", ".keys", ".private", ".pem", ".p12", ".pfx",
    # firmware and BIOS
    ".bin", ".rom", ".pup", ".bios",
    # OS and disk images
    ".iso", ".img", ".qcow2", ".vhd", ".vhdx", ".vmdk", ".wim", ".esd",
    # console game and ROM formats
    ".nes", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".3ds", ".cia",
    ".n64", ".z64", ".v64", ".cso", ".chd", ".gcm", ".wbfs", ".rvz",
    ".wud", ".wux", ".xex", ".nsp", ".xci",
}

# Allowed despite matching a rule above.
ALLOWED_NAMES = {"cosign.pub"}

HOOK_BLOCK_EXIT = 2
GIT_BLOCK_EXIT = 1


def protection_reason(path):
    """Return why a path is protected, or None if it may be written/committed."""
    try:
        normalized = path.replace("\\", "/").strip()
        if not normalized:
            return None
        parts = [p for p in normalized.split("/") if p not in ("", ".")]
        if not parts:
            return None
        name = parts[-1].lower()
        if name in ALLOWED_NAMES:
            return None
        for part in parts[:-1]:
            if part.lower() in PROTECTED_DIRS:
                return "it is inside a protected '{}/' directory".format(part)
        if name in PROTECTED_NAMES:
            return "'{}' is a secret or key file".format(parts[-1])
        suffix = os.path.splitext(name)[1]
        if suffix in PROTECTED_SUFFIXES:
            return "'{}' files are firmware, keys, ROMs, or OS images".format(suffix)
        return None
    except Exception as error:  # report, and treat as protected: fail closed
        return "the guard could not check this path ({})".format(error)


def paths_from_hook_input(payload):
    """Extract the file paths a Claude Code tool call would write."""
    try:
        tool_input = payload.get("tool_input") or {}
        paths = []
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
        return paths
    except Exception as error:
        raise RuntimeError("could not read tool_input: {}".format(error)) from error


def relative_to_project(path):
    """Show a path relative to the project root when possible, for clearer messages."""
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if root and os.path.isabs(path):
            return os.path.relpath(path, root)
        return path
    except Exception:
        return path


def run_hook():
    """Claude Code PreToolUse mode: block writes to protected paths."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        blocked = []
        for path in paths_from_hook_input(payload):
            relative = relative_to_project(path)
            if relative.replace("\\", "/").startswith("../"):
                continue  # outside the repo: not ours to guard
            reason = protection_reason(relative)
            if reason:
                blocked.append((path, reason))
        if blocked:
            lines = ["Blocked by the Camera Obscura repo guard (ARCHITECTURE.md §14.2):"]
            for path, reason in blocked:
                lines.append("  - {}: {}".format(path, reason))
            lines.append("Packs declare user-supplied files by name and checksum; "
                         "the files themselves never go in the repo.")
            print("\n".join(lines), file=sys.stderr)
            return HOOK_BLOCK_EXIT
        return 0
    except Exception as error:
        print("Camera Obscura repo guard failed to run ({}). Blocking to be safe; "
              "fix .claude/hooks/guard_protected_files.py.".format(error), file=sys.stderr)
        return HOOK_BLOCK_EXIT


def staged_files():
    """List files staged for commit (added, copied, modified, renamed)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
            check=True, capture_output=True,
        )
        return [p for p in result.stdout.decode("utf-8", "replace").split("\0") if p]
    except Exception as error:
        raise RuntimeError("could not list staged files: {}".format(error)) from error


def report(paths, header, staged=False):
    """Print blocked paths and return the matching exit code for git/check modes."""
    try:
        blocked = []
        for path in paths:
            reason = protection_reason(path)
            if reason:
                blocked.append((path, reason))
        if blocked:
            print(header, file=sys.stderr)
            for path, reason in blocked:
                print("  - {}: {}".format(path, reason), file=sys.stderr)
            if staged:
                print("Unstage with: git restore --staged <file>", file=sys.stderr)
            return GIT_BLOCK_EXIT
        return 0
    except Exception as error:
        print("Repo guard error: {}".format(error), file=sys.stderr)
        return GIT_BLOCK_EXIT


def main(argv):
    """Dispatch to hook, pre-commit, or check mode."""
    try:
        if len(argv) == 0:
            return run_hook()
        if argv[0] == "--staged":
            return report(staged_files(),
                          "Commit blocked by the Camera Obscura repo guard (ARCHITECTURE.md §14.2):",
                          staged=True)
        if argv[0] == "--check" and len(argv) > 1:
            return report(argv[1:], "Protected paths:")
        print(__doc__, file=sys.stderr)
        return GIT_BLOCK_EXIT
    except Exception as error:
        print("Repo guard error: {}".format(error), file=sys.stderr)
        return GIT_BLOCK_EXIT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
