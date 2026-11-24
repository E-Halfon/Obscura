"""obscura-cap: developer and test tool for the capability service.

Never required of users (ARCHITECTURE.md §19); the GUI reads the same DBus interface.

  obscura-cap list          present capabilities, one per line
  obscura-cap vocabulary    every declared capability
  obscura-cap has NAME      prints "present" (exit 0) or "absent" (exit 1); on an unknown
                            name or any error, prints nothing on stdout, says why on
                            stderr, and exits 2
  obscura-cap watch         print +NAME / -NAME as capabilities appear and disappear

Requires dasbus and PyGObject (Linux only).
"""

import argparse
import sys

from obscura_capd.constants import BUS_NAME, MANAGER_INTERFACE, MANAGER_PATH

EXIT_PRESENT = 0
EXIT_ABSENT = 1
EXIT_ERROR = 2


def _error(message):
    try:
        print("obscura-cap: " + message, file=sys.stderr)
    except Exception:
        pass


def _parse(argv):
    try:
        parser = argparse.ArgumentParser(prog="obscura-cap", description="Query Camera Obscura capabilities.")
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("list", help="present capabilities")
        commands.add_parser("vocabulary", help="every declared capability")
        has = commands.add_parser("has", help='print "present" (exit 0) or "absent" (exit 1); exit 2 on error')
        has.add_argument("name")
        commands.add_parser("watch", help="print +NAME / -NAME as capabilities change")
        return parser.parse_args(argv)
    except SystemExit:
        raise
    except Exception as error:
        _error("bad arguments: " + str(error))
        raise


def _proxy():
    try:
        from dasbus.connection import SystemMessageBus

        from obscura_capd.errors import ERROR_MAPPER

        bus = SystemMessageBus(error_mapper=ERROR_MAPPER)
        return bus.get_proxy(BUS_NAME, MANAGER_PATH, MANAGER_INTERFACE)
    except Exception as error:
        _error("cannot reach the capability service: " + str(error))
        raise


def _watch(proxy):
    try:
        from dasbus.loop import EventLoop

        def _added(name):
            try:
                print("+" + name, flush=True)
            except Exception as error:
                _error("watch: " + str(error))

        def _removed(name):
            try:
                print("-" + name, flush=True)
            except Exception as error:
                _error("watch: " + str(error))

        # Connect before listing, so nothing that changes in between is missed.
        proxy.Added.connect(_added)
        proxy.Removed.connect(_removed)
        for name in proxy.List():
            _added(name)
        try:
            EventLoop().run()
        except KeyboardInterrupt:
            pass
        return EXIT_PRESENT
    except Exception as error:
        _error("watch failed: " + str(error))
        return EXIT_ERROR


def main(argv=None):
    try:
        arguments = _parse(sys.argv[1:] if argv is None else argv)
        try:
            proxy = _proxy()
        except Exception:
            return EXIT_ERROR

        if arguments.command == "list":
            for name in proxy.List():
                print(name)
            return EXIT_PRESENT
        if arguments.command == "vocabulary":
            for name in proxy.Vocabulary():
                print(name)
            return EXIT_PRESENT
        if arguments.command == "has":
            from obscura_capd.errors import UnknownCapabilityError

            try:
                present = bool(proxy.Has(arguments.name))
                print("present" if present else "absent", flush=True)
                return EXIT_PRESENT if present else EXIT_ABSENT
            except UnknownCapabilityError:
                _error("unknown capability: " + arguments.name + " (see 'obscura-cap vocabulary')")
                return EXIT_ERROR
        if arguments.command == "watch":
            return _watch(proxy)
        _error("unknown command " + arguments.command)
        return EXIT_ERROR
    except SystemExit as exit_request:
        return EXIT_ERROR if exit_request.code not in (0, None) else EXIT_PRESENT
    except Exception as error:
        _error(type(error).__name__ + ": " + str(error))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
