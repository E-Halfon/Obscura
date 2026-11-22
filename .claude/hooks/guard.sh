#!/usr/bin/env sh
# Runs the Camera Obscura repo guard with whichever Python is available.
# Works in Git Bash on Windows (python / py) and on Linux (python3).
# Passes all arguments and stdin through. Blocks (exit 2) if no Python is found.

GUARD="$(dirname "$0")/guard_protected_files.py"

if command -v python3 >/dev/null 2>&1 && python3 -c "" >/dev/null 2>&1; then
    exec python3 "$GUARD" "$@"
fi

if command -v python >/dev/null 2>&1 && python -c "" >/dev/null 2>&1; then
    exec python "$GUARD" "$@"
fi

if command -v py >/dev/null 2>&1; then
    exec py -3 "$GUARD" "$@"
fi

echo "Camera Obscura repo guard: no Python found. Install Python 3 (winget install Python.Python.3.12)." >&2
exit 2
