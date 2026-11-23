"""Failure and notice reporting: always to stderr, plus a structured journal entry with a
fixed MESSAGE_ID when running under systemd.

CLAUDE.md requires every function to catch and report failures instead of letting them
escape silently. Each function catches, calls failure(), and re-raises (or handles).
An exception is reported once: failure() marks it, so callers further up the stack that
catch the same exception don't log it again.
"""

import os
import sys
import traceback

from obscura_capd.constants import MESSAGE_ID_FAILURE, MESSAGE_ID_NOTICE

_REPORTED_MARK = "_obscura_reported"

# Who is reporting: the stderr prefix and the journal SYSLOG_IDENTIFIER. Other Obscura
# components that reuse this module (obscura_packs) set their own name.
_identifier = "obscura-capd"

try:
    from systemd import journal as _journal
except ImportError:
    _journal = None


def _under_systemd():
    """True when systemd started this process (it sets INVOCATION_ID for every unit)."""
    try:
        return bool(os.environ.get("INVOCATION_ID"))
    except Exception:
        return False


def set_identifier(name):
    """Report as `name` (e.g. "obscura-pack") instead of obscura-capd."""
    global _identifier
    try:
        _identifier = str(name)
    except Exception as error:
        # Keep the previous identifier; say so on stderr, the one channel left that
        # doesn't depend on this module's state.
        try:
            print(_identifier + ": could not set report identifier: " + repr(error), file=sys.stderr, flush=True)
        except Exception:
            pass  # stderr itself is unusable: there is nowhere left to report


def _send(priority, message_id, message, fields):
    """Write one entry to stderr, always. Under systemd, stderr already reaches the
    journal; there we additionally send a structured entry carrying the MESSAGE_ID for
    the diagnostics page. The structured entry is never sent instead of stderr, so
    output is visible wherever capd runs (tests, a terminal, CI)."""
    try:
        extra = " ".join(key + "=" + str(value) for key, value in fields.items())
        print(_identifier + ": " + message + (" " + extra if extra else ""), file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        if _journal is not None and _under_systemd():
            _journal.send(
                message,
                MESSAGE_ID=message_id,
                PRIORITY=str(priority),
                SYSLOG_IDENTIFIER=_identifier,
                **fields,
            )
    except Exception:
        # Reporting must never take the service down; the stderr line above was written.
        try:
            print(_identifier + ": could not send structured journal entry: " + message,
                  file=sys.stderr, flush=True)
        except Exception:
            pass


def failure(where, error):
    """Report an unexpected exception raised in `where`, once per exception object."""
    try:
        if getattr(error, _REPORTED_MARK, False):
            return
        try:
            setattr(error, _REPORTED_MARK, True)
        except Exception:
            pass
        detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        _send(
            3,
            MESSAGE_ID_FAILURE,
            "failure in " + where + ": " + type(error).__name__ + ": " + str(error),
            {"OBSCURA_WHERE": where, "OBSCURA_TRACEBACK": detail},
        )
    except Exception:
        _send(3, MESSAGE_ID_FAILURE, "failure in " + where + " (details unavailable)", {})


def problem(where, message, **fields):
    """Report a detected problem that isn't an exception (e.g. a target that is missing)."""
    try:
        _send(4, MESSAGE_ID_FAILURE, where + ": " + message, dict(fields, OBSCURA_WHERE=where))
    except Exception as error:
        failure("report.problem", error)


def notice(message, **fields):
    """Report a normal but noteworthy event (e.g. a capability target masked by the admin)."""
    try:
        _send(5, MESSAGE_ID_NOTICE, message, fields)
    except Exception as error:
        failure("report.notice", error)
