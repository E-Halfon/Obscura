"""Pure state logic: interpreting systemd unit state and tracking presence.

No DBus here, so all of it can be unit-tested without a bus.
"""

from dataclasses import dataclass

from obscura_capd import report
from obscura_capd.constants import CAPABILITY_PATH_PREFIX


@dataclass(frozen=True)
class Reading:
    """What one systemd target says about one capability."""
    present: bool
    # None when the state is normal (active, or inactive because the hardware is absent).
    # Otherwise a short reason: a problem worth one journal entry, never shown as broken UI.
    problem: object = None
    # True when the problem is an admin choice (masked), reported as a notice not a problem.
    deliberate: bool = False


def interpret_unit(load_state, active_state):
    """Map a target's LoadState/ActiveState to presence.

    Only loaded+active is present. Everything else is absent; the unexpected cases also
    carry a problem so they reach the journal (ARCHITECTURE.md §4: absent, never broken).
    """
    try:
        if load_state == "masked":
            return Reading(present=False, problem="target is masked", deliberate=True)
        if load_state != "loaded":
            return Reading(present=False, problem="target LoadState is " + str(load_state))
        if active_state == "active":
            return Reading(present=True)
        if active_state in ("inactive", "activating", "deactivating"):
            return Reading(present=False)
        return Reading(present=False, problem="target ActiveState is " + str(active_state))
    except Exception as error:
        report.failure("state.interpret_unit", error)
        raise


def object_path_for(name):
    """Object path for a capability. Names never contain underscores, so this is one-to-one."""
    try:
        return CAPABILITY_PATH_PREFIX + name.replace("-", "_")
    except Exception as error:
        report.failure("state.object_path_for", error)
        raise


class PresenceTable:
    """Which declared capabilities are present, and since when (systemd realtime, usec)."""

    def __init__(self, names):
        try:
            self._names = frozenset(names)
            self._since = {}
            self._problems = {}
        except Exception as error:
            report.failure("PresenceTable.__init__", error)
            raise

    def transition_for(self, name, present):
        """What update() would return, without changing anything. Lets the caller publish
        first and commit to the table only once publishing has succeeded."""
        try:
            if name not in self._names:
                raise KeyError("undeclared capability " + repr(name))
            was_present = name in self._since
            if present and not was_present:
                return "added"
            if not present and was_present:
                return "removed"
            return None
        except Exception as error:
            report.failure("PresenceTable.transition_for", error)
            raise

    def update(self, name, present, since):
        """Record a reading. Returns "added", "removed", or None if nothing changed."""
        try:
            if name not in self._names:
                raise KeyError("undeclared capability " + repr(name))
            was_present = name in self._since
            if present and not was_present:
                self._since[name] = since
                return "added"
            if not present and was_present:
                del self._since[name]
                return "removed"
            if present:
                # Still present; keep the timestamp current in case systemd's changed.
                self._since[name] = since
            return None
        except Exception as error:
            report.failure("PresenceTable.update", error)
            raise

    def note_problem(self, name, problem):
        """Remember the latest problem. Returns True only when it differs from the last one,
        so a repeated state is logged once instead of on every resync (no log spam, T-43)."""
        try:
            if self._problems.get(name) == problem:
                return False
            if problem is None:
                self._problems.pop(name, None)
            else:
                self._problems[name] = problem
            return problem is not None
        except Exception as error:
            report.failure("PresenceTable.note_problem", error)
            raise

    def is_declared(self, name):
        try:
            return name in self._names
        except Exception as error:
            report.failure("PresenceTable.is_declared", error)
            raise

    def is_present(self, name):
        try:
            return name in self._since
        except Exception as error:
            report.failure("PresenceTable.is_present", error)
            raise

    def since(self, name):
        try:
            return self._since.get(name, 0)
        except Exception as error:
            report.failure("PresenceTable.since", error)
            raise

    def present_names(self):
        try:
            return sorted(self._since)
        except Exception as error:
            report.failure("PresenceTable.present_names", error)
            raise

    def declared_names(self):
        try:
            return sorted(self._names)
        except Exception as error:
            report.failure("PresenceTable.declared_names", error)
            raise
