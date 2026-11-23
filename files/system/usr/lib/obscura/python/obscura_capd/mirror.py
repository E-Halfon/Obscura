"""Mirrors systemd target state into the presence table. Requires dasbus (Linux only).

capd never detects hardware. For every declared capability it asks systemd to load the
target (LoadUnit, so an inactive target is reported as absent rather than missing) and
reads its state. It resyncs a target whenever a job on it finishes (udev starting it,
StopWhenUnneeded stopping it) and resyncs everything after a daemon-reload.
"""

from dasbus.typing import get_native

from obscura_capd import report
from obscura_capd.constants import (
    SYSTEMD_BUS_NAME,
    SYSTEMD_MANAGER_INTERFACE,
    SYSTEMD_PATH,
    SYSTEMD_UNIT_INTERFACE,
)
from obscura_capd.state import interpret_unit

_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"


class SystemdMirror:
    def __init__(self, bus, vocabulary, table, on_transition):
        try:
            self._bus = bus
            self._vocabulary = vocabulary
            self._table = table
            self._on_transition = on_transition
            self._name_by_target = {declaration.target: name for name, declaration in vocabulary.items()}
            self._manager = None
        except Exception as error:
            report.failure("SystemdMirror.__init__", error)
            raise

    def start(self):
        """Connect to systemd, subscribe, then do the first full sync.

        Signals are connected before Subscribe and before the first read, so a change that
        lands between reading and subscribing still triggers a resync.
        """
        try:
            self._manager = self._bus.get_proxy(SYSTEMD_BUS_NAME, SYSTEMD_PATH, SYSTEMD_MANAGER_INTERFACE)
            self._manager.JobRemoved.connect(self._on_job_removed)
            self._manager.Reloading.connect(self._on_reloading)
            self._manager.Subscribe()
            self.resync_all()
        except Exception as error:
            report.failure("SystemdMirror.start", error)
            raise

    def resync_all(self):
        try:
            for name in sorted(self._vocabulary):
                self.resync(name)
        except Exception as error:
            report.failure("SystemdMirror.resync_all", error)
            raise

    def resync(self, name):
        """Read one target and apply it. If systemd can't be read, the capability is treated
        as absent (and the failure is reported): absent is always the safe state."""
        try:
            declaration = self._vocabulary[name]
            try:
                load_state, active_state, since = self._read_target(declaration.target)
            except Exception as error:
                report.failure("SystemdMirror.resync(" + name + ")", error)
                self._apply(name, False, 0)
                return

            reading = interpret_unit(load_state, active_state)
            if self._table.note_problem(name, reading.problem):
                if reading.deliberate:
                    report.notice(name + ": " + reading.problem, OBSCURA_CAPABILITY=name)
                else:
                    report.problem("capability " + name, reading.problem, OBSCURA_CAPABILITY=name)
            self._apply(name, reading.present, since if reading.present else 0)
        except Exception as error:
            report.failure("SystemdMirror.resync", error)
            raise

    def _read_target(self, target):
        """Returns (LoadState, ActiveState, ActiveEnterTimestamp) from one GetAll call, so the
        three values are consistent with each other."""
        try:
            path = self._manager.LoadUnit(target)
            properties = self._bus.get_proxy(SYSTEMD_BUS_NAME, path, _PROPERTIES_INTERFACE)
            values = get_native(properties.GetAll(SYSTEMD_UNIT_INTERFACE))
            return (
                str(values.get("LoadState", "")),
                str(values.get("ActiveState", "")),
                int(values.get("ActiveEnterTimestamp", 0)),
            )
        except Exception as error:
            report.failure("SystemdMirror._read_target", error)
            raise

    def _apply(self, name, present, since):
        try:
            transition = self._table.update(name, present, since)
            if transition is not None:
                self._on_transition(name, transition)
        except Exception as error:
            report.failure("SystemdMirror._apply", error)
            raise

    def _on_job_removed(self, job_id, job_path, unit, result):
        """Signal handler. Must never raise into the event loop."""
        try:
            name = self._name_by_target.get(unit)
            if name is not None:
                self.resync(name)
        except Exception as error:
            report.failure("SystemdMirror._on_job_removed", error)

    def _on_reloading(self, active):
        """Signal handler. Resync everything once a daemon-reload has finished."""
        try:
            if not active:
                self.resync_all()
        except Exception as error:
            report.failure("SystemdMirror._on_reloading", error)
