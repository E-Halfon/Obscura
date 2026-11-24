"""Keep systemd units loaded while a gate test reads their properties (task 0.2b).

    python3 -I pin_units.py <ready-file> <unit>...

Calls org.freedesktop.systemd1.Manager.RefUnit for each unit, writes "pinned" to
<ready-file>, then waits until killed. While this process holds its bus connection, PID 1
won't garbage-collect the units ("Collecting."), so `systemctl show` keeps returning the
state of the object that ran (Result, ConditionTimestamp, ActiveEnterTimestamp,
InvocationID) instead of a freshly loaded one with defaults. The CI diagnostic run of
2026-11-24 on systemd 255 showed the stand-ins being collected right after each start.

RefUnit is a reference only: it starts nothing and pulls nothing into a transaction, so it
can't change what the test observes. The tests check that the pin held (InvocationID
matches the journal) before relying on any property.

Test helper (tests/ is exempt from the production try/except rule).
"""

import sys

from gi.repository import Gio, GLib


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: pin_units.py <ready-file> <unit>...\n")
        return 2
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    for unit in argv[2:]:
        bus.call_sync("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                      "org.freedesktop.systemd1.Manager", "RefUnit",
                      GLib.Variant("(s)", (unit,)), None, Gio.DBusCallFlags.NONE, -1, None)
    with open(argv[1], "w", encoding="ascii") as handle:
        handle.write("pinned\n")
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
