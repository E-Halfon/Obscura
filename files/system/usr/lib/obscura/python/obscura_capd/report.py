"""Failure and notice reporting to the journal, with fixed MESSAGE_IDs.

CLAUDE.md requires every function to catch and report failures instead of letting them
escape silently. Each function catches, calls failure(), and re-raises (or handles).
An exception is reported once: failure() marks it, so callers further up the stack that
catch the same exception don't log it again.
"""

import sys
import traceback

from obscura_capd.constants import MESSAGE_ID_FAILURE, MESSAGE_ID_NOTICE

_REPORTED_MARK = "_obscura_reported"

try:
    from systemd import journal as _journal
except ImportError:
    _journal = None


def _send(priority, message_id, message, fields):
    """Write one entry to the journal, or to stderr when python3-systemd is missing."""
    try:
        if _journal is not None:
            _journal.send(
                message,
                MESSAGE_ID=message_id,
                PRIORITY=str(priority),
                SYSLOG_IDENTIFIER="obscura-capd",
                **fields,
            )
        else:
            extra = " ".join(key + "=" + str(value) for key, value in fields.items())
            print("obscura-capd: " + message + (" " + extra if extra else ""), file=sys.stderr)
    except Exception:
        # Reporting must never take the service down; stderr still reaches the journal.
        try:
            print("obscura-capd: could not report: " + message, file=sys.stderr)
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
