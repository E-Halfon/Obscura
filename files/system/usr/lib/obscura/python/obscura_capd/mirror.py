"""Mirrors systemd target state into the presence table. Requires PyGObject (Linux only).

capd never detects hardware. For every declared capability it asks systemd to load the
target (LoadUnit, so an inactive target is reported as absent rather than missing) and
reads its state. It resyncs a target whenever a job on it finishes (udev starting it,
StopWhenUnneeded stopping it) and resyncs everything after a daemon-reload.

systemd is called through the bus's Gio connection with explicit signatures and signal
subscriptions rather than an introspected proxy: it needs no introspection round trip
and behaves the same against real systemd and the test mock.
"""

from gi.repository import Gio, GLib

from obscura_capd import report
from obscura_capd.constants import (
    SYSTEMD_BUS_NAME,
    SYSTEMD_MANAGER_INTERFACE,
    SYSTEMD_PATH,
    SYSTEMD_UNIT_INTERFACE,
)
from obscura_capd.state import interpret_unit

_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
_CALL_TIMEOUT_MS = 10000


class SystemdMirror:
    def __init__(self, connection, vocabulary, table, exporter):
        """`connection` is a Gio.DBusConnection to the system bus (dasbus: bus.connection)."""
        try:
            self._connection = connection
            self._vocabulary = vocabulary
            self._table = table
            self._exporter = exporter
            self._name_by_target = {declaration.target: name for name, declaration in vocabulary.items()}
            self._subscriptions = []
        except Exception as error:
            report.failure("SystemdMirror.__init__", error)
            raise

    def start(self):
        """Subscribe to systemd's signals, then do the first full sync.

        Signals are subscribed before Subscribe and before the first read, so a change
        that lands between reading and subscribing still triggers a resync.
        """
        try:
            for member, handler in (("JobRemoved", self._on_job_removed), ("Reloading", self._on_reloading)):
                self._subscriptions.append(self._connection.signal_subscribe(
                    SYSTEMD_BUS_NAME, SYSTEMD_MANAGER_INTERFACE, member, SYSTEMD_PATH,
                    None, Gio.DBusSignalFlags.NONE, handler,
                ))
            self._call(SYSTEMD_PATH, SYSTEMD_MANAGER_INTERFACE, "Subscribe", None, None)
            self.resync_all()
        except Exception as error:
            report.failure("SystemdMirror.start", error)
            raise

    def stop(self):
        try:
            for subscription in self._subscriptions:
                self._connection.signal_unsubscribe(subscription)
            self._subscriptions = []
        except Exception as error:
            report.failure("SystemdMirror.stop", error)
            raise

    def resync_all(self):
        try:
            for name in sorted(self._vocabulary):
                self.resync(name)
        except Exception as error:
            report.failure("SystemdMirror.resync_all", error)
            raise

    def resync(self, name):
        """Read one target and apply it.

        A DBus transport error (GLib.Error: timeout, systemd busy or restarting) keeps the
        previous state and is only reported, so a transient failure can't make a present
        capability flap Removed/Added. The next job or reload resyncs. At startup there is
        no previous state, so the capability stays absent. Any other error (a reply we
        can't interpret) is reported and the capability is treated as absent, the safe
        state."""
        try:
            declaration = self._vocabulary[name]
            try:
                load_state, active_state, since = self._read_target(declaration.target)
            except GLib.Error as error:
                report.failure("SystemdMirror.resync(" + name + "): transport error, keeping previous state", error)
                return
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

    def _call(self, path, interface, method, parameters, reply_type):
        try:
            reply = self._connection.call_sync(
                SYSTEMD_BUS_NAME, path, interface, method, parameters,
                GLib.VariantType.new(reply_type) if reply_type else None,
                Gio.DBusCallFlags.NONE, _CALL_TIMEOUT_MS, None,
            )
            return reply.unpack() if reply is not None else None
        except Exception as error:
            report.failure("SystemdMirror._call(" + method + ")", error)
            raise

    def _read_target(self, target):
        """Returns (LoadState, ActiveState, ActiveEnterTimestamp) from one GetAll call, so the
        three values are consistent with each other."""
        try:
            (path,) = self._call(SYSTEMD_PATH, SYSTEMD_MANAGER_INTERFACE, "LoadUnit",
                                 GLib.Variant("(s)", (target,)), "(o)")
            (values,) = self._call(path, _PROPERTIES_INTERFACE, "GetAll",
                                   GLib.Variant("(s)", (SYSTEMD_UNIT_INTERFACE,)), "(a{sv})")
            return (
                str(values.get("LoadState", "")),
                str(values.get("ActiveState", "")),
                int(values.get("ActiveEnterTimestamp", 0)),
            )
        except Exception as error:
            report.failure("SystemdMirror._read_target", error)
            raise

    def _apply(self, name, present, since):
        """Publish or unpublish first, commit to the table only if that succeeded, then
        announce. If publishing fails the table is untouched, so the next resync retries
        and List/Has never disagree with the object tree."""
        try:
            transition = self._table.transition_for(name, present)
            if transition is None:
                self._table.update(name, present, since)
                return
            try:
                self._exporter.apply(name, transition, since)
            except Exception as error:
                report.failure("SystemdMirror._apply(" + name + ")", error)
                return
            self._table.update(name, present, since)
            self._exporter.announce(name, transition, since)
        except Exception as error:
            report.failure("SystemdMirror._apply", error)
            raise

    def _on_job_removed(self, connection, sender, path, interface, signal, parameters):
        """JobRemoved(u id, o job, s unit, s result). Must never raise into the event loop."""
        try:
            unit = parameters.unpack()[2]
            name = self._name_by_target.get(unit)
            if name is not None:
                self.resync(name)
        except Exception as error:
            report.failure("SystemdMirror._on_job_removed", error)

    def _on_reloading(self, connection, sender, path, interface, signal, parameters):
        """Reloading(b active). Resync everything once a daemon-reload has finished."""
        try:
            (active,) = parameters.unpack()
            if not active:
                self.resync_all()
        except Exception as error:
            report.failure("SystemdMirror._on_reloading", error)
