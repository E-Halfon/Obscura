"""The org.obscura.Capabilities1 DBus interfaces. Requires dasbus (Linux only).

Follows the ModemManager pattern: a capability's object exists only while it is present.
Everything is read-only; capabilities are facts, not settings, so nothing here goes
through or around the action API (ARCHITECTURE.md §20).
"""

from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Bool, Dict, Int, List, ObjPath, Str, UInt64, Variant, get_variant

from obscura_capd import report
from obscura_capd.constants import (
    API_VERSION,
    CAPABILITY_INTERFACE,
    MANAGER_INTERFACE,
)
from obscura_capd.errors import UnknownCapabilityError
from obscura_capd.state import object_path_for


def capability_properties(declaration, since):
    """The Capability interface's properties as variants (for ObjectManager)."""
    try:
        return {
            "Name": get_variant(Str, declaration.name),
            "Kind": get_variant(Str, declaration.kind),
            "Summary": get_variant(Str, declaration.summary),
            "Since": get_variant(UInt64, since),
        }
    except Exception as error:
        report.failure("service.capability_properties", error)
        raise


@dbus_interface(CAPABILITY_INTERFACE)
class Capability:
    """One present capability, at /org/obscura/Capabilities1/cap/<name>."""

    def __init__(self, declaration, since):
        try:
            self._declaration = declaration
            self._since = since
        except Exception as error:
            report.failure("Capability.__init__", error)
            raise

    @property
    def Name(self) -> Str:
        try:
            return self._declaration.name
        except Exception as error:
            report.failure("Capability.Name", error)
            raise

    @property
    def Kind(self) -> Str:
        try:
            return self._declaration.kind
        except Exception as error:
            report.failure("Capability.Kind", error)
            raise

    @property
    def Summary(self) -> Str:
        try:
            return self._declaration.summary
        except Exception as error:
            report.failure("Capability.Summary", error)
            raise

    @property
    def Since(self) -> UInt64:
        """When the target became active, in usec since the epoch (systemd realtime)."""
        try:
            return self._since
        except Exception as error:
            report.failure("Capability.Since", error)
            raise


@dbus_interface("org.freedesktop.DBus.ObjectManager")
class ObjectManager:
    """Standard ObjectManager, so generic DBus tools and libraries see the object tree."""

    def GetManagedObjects(self) -> Dict[ObjPath, Dict[Str, Dict[Str, Variant]]]:
        try:
            return self._managed_objects()
        except Exception as error:
            report.failure("ObjectManager.GetManagedObjects", error)
            raise

    def _managed_objects(self):
        raise NotImplementedError

    @dbus_signal
    def InterfacesAdded(self, object_path: ObjPath, interfaces: Dict[Str, Dict[Str, Variant]]):
        pass

    @dbus_signal
    def InterfacesRemoved(self, object_path: ObjPath, interfaces: List[Str]):
        pass


@dbus_interface(MANAGER_INTERFACE)
class Manager(ObjectManager):
    """/org/obscura/Capabilities1: query and watch the declared capabilities."""

    def __init__(self, vocabulary, table):
        try:
            self._vocabulary = vocabulary
            self._table = table
        except Exception as error:
            report.failure("Manager.__init__", error)
            raise

    @property
    def ApiVersion(self) -> Int:
        try:
            return API_VERSION
        except Exception as error:
            report.failure("Manager.ApiVersion", error)
            raise

    def List(self) -> List[Str]:
        """Names of the capabilities present on this device."""
        try:
            return self._table.present_names()
        except Exception as error:
            report.failure("Manager.List", error)
            raise

    def Vocabulary(self) -> List[Str]:
        """Every declared capability name, present or not."""
        try:
            return self._table.declared_names()
        except Exception as error:
            report.failure("Manager.Vocabulary", error)
            raise

    def Has(self, name: Str) -> Bool:
        """False for an absent capability (a normal answer). UnknownCapability error only
        for a name that isn't declared."""
        try:
            if not self._table.is_declared(name):
                raise UnknownCapabilityError("unknown capability: " + name)
            return self._table.is_present(name)
        except UnknownCapabilityError:
            raise
        except Exception as error:
            report.failure("Manager.Has", error)
            raise

    @dbus_signal
    def Added(self, name: Str):
        pass

    @dbus_signal
    def Removed(self, name: Str):
        pass

    def _managed_objects(self):
        try:
            objects = {}
            for name in self._table.present_names():
                declaration = self._vocabulary[name]
                objects[object_path_for(name)] = {
                    CAPABILITY_INTERFACE: capability_properties(declaration, self._table.since(name)),
                }
            return objects
        except Exception as error:
            report.failure("Manager._managed_objects", error)
            raise


class Exporter:
    """Publishes and removes capability objects as the presence table changes, then
    signals. Order matters: an object exists before Added is sent, and is gone before
    Removed is sent, so a client reacting to either signal sees a consistent tree."""

    def __init__(self, bus, manager, vocabulary, table):
        try:
            self._bus = bus
            self._manager = manager
            self._vocabulary = vocabulary
            self._table = table
        except Exception as error:
            report.failure("Exporter.__init__", error)
            raise

    def on_transition(self, name, transition):
        try:
            path = object_path_for(name)
            declaration = self._vocabulary[name]
            if transition == "added":
                since = self._table.since(name)
                self._bus.publish_object(path, Capability(declaration, since))
                self._manager.InterfacesAdded.emit(path, {CAPABILITY_INTERFACE: capability_properties(declaration, since)})
                self._manager.Added.emit(name)
                report.notice("capability present: " + name, OBSCURA_CAPABILITY=name)
            elif transition == "removed":
                self._bus.unpublish_object(path)
                self._manager.InterfacesRemoved.emit(path, [CAPABILITY_INTERFACE])
                self._manager.Removed.emit(name)
                report.notice("capability absent: " + name, OBSCURA_CAPABILITY=name)
            else:
                raise ValueError("unknown transition " + repr(transition))
        except Exception as error:
            report.failure("Exporter.on_transition", error)
            raise
