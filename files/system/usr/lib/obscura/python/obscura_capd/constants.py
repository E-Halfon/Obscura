"""Names shared by the daemon, the CLI, and the tests. Changing any of these is an API
break for every consumer (pack manager, Settings, automations)."""

API_VERSION = 1

BUS_NAME = "org.obscura.Capabilities1"
MANAGER_PATH = "/org/obscura/Capabilities1"
MANAGER_INTERFACE = "org.obscura.Capabilities1"
CAPABILITY_PATH_PREFIX = "/org/obscura/Capabilities1/cap/"
CAPABILITY_INTERFACE = "org.obscura.Capabilities1.Capability"
ERROR_UNKNOWN_CAPABILITY = "org.obscura.Capabilities1.Error.UnknownCapability"

VOCABULARY_DIR = "/usr/share/obscura/capabilities.d"
TARGET_PREFIX = "obscura-cap-"
TARGET_SUFFIX = ".target"

KINDS = ("static", "device", "probe")

SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
SYSTEMD_PATH = "/org/freedesktop/systemd1"
SYSTEMD_MANAGER_INTERFACE = "org.freedesktop.systemd1.Manager"
SYSTEMD_UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"

# Journal MESSAGE_IDs, so the diagnostics page can find these entries (ARCHITECTURE.md §4:
# a broken detection is reported, but the capability is shown as absent, never broken).
MESSAGE_ID_FAILURE = "e57f838faebb4579bed482e6fb4885e3"
MESSAGE_ID_NOTICE = "530f5cc2657740d1847c5f78c5d301d8"
