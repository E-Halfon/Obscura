"""DBus errors shared by the daemon and its clients. Requires dasbus (Linux only)."""

from dasbus.error import DBusError, ErrorMapper, get_error_decorator

from obscura_capd.constants import ERROR_UNKNOWN_CAPABILITY

ERROR_MAPPER = ErrorMapper()
_dbus_error = get_error_decorator(ERROR_MAPPER)


@_dbus_error(ERROR_UNKNOWN_CAPABILITY)
class UnknownCapabilityError(DBusError):
    """The name isn't in the vocabulary. That's a caller bug, unlike an absent capability,
    which is a normal answer (Has() returns false)."""
