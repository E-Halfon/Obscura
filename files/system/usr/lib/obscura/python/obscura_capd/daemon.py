"""obscura-capd entry point: python3 -P -m obscura_capd.daemon (run by obscura-capd.service).

Requires dasbus and PyGObject (Linux only).
"""

import os
import signal
import sys

from obscura_capd import report
from obscura_capd.constants import BUS_NAME, MANAGER_PATH, VOCABULARY_DIR
from obscura_capd.state import PresenceTable
from obscura_capd.vocabulary import load_vocabulary


def _vocabulary_dir():
    """The declaration directory. Tests point OBSCURA_CAPD_VOCABULARY_DIR at a fixture."""
    try:
        return os.environ.get("OBSCURA_CAPD_VOCABULARY_DIR", VOCABULARY_DIR)
    except Exception as error:
        report.failure("daemon._vocabulary_dir", error)
        raise


def main():
    try:
        from dasbus.connection import SystemMessageBus
        from dasbus.loop import EventLoop
        from gi.repository import GLib

        from obscura_capd.errors import ERROR_MAPPER
        from obscura_capd.mirror import SystemdMirror
        from obscura_capd.service import Exporter, Manager

        vocabulary = load_vocabulary(_vocabulary_dir())
        table = PresenceTable(vocabulary.keys())
        bus = SystemMessageBus(error_mapper=ERROR_MAPPER)
        manager = Manager(vocabulary, table)
        exporter = Exporter(bus, manager, vocabulary, table)
        bus.publish_object(MANAGER_PATH, manager)

        # Sync with systemd before claiming the bus name, so the first caller (often the
        # one that DBus-activated us) already sees the real state.
        mirror = SystemdMirror(bus.connection, vocabulary, table, exporter)
        mirror.start()
        bus.register_service(BUS_NAME)

        loop = EventLoop()

        def _quit():
            try:
                loop.quit()
            except Exception as error:
                report.failure("daemon._quit", error)
            return GLib.SOURCE_REMOVE

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _quit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _quit)
        report.notice(
            "started; vocabulary: " + (", ".join(sorted(vocabulary)) or "(empty)"),
        )
        loop.run()
        mirror.stop()
        bus.disconnect()
        return 0
    except Exception as error:
        report.failure("daemon.main", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
