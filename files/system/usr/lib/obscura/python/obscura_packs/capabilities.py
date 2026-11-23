"""What the capability service says about this device, for readiness.

Presence comes from org.obscura.Capabilities1 (List). Kinds and summaries come from the
same declaration files capd loads (absent capabilities have no DBus object to carry
them), read with capd's own loader so the two never disagree.
"""

import os

from obscura_capd import report
from obscura_capd.constants import BUS_NAME, MANAGER_INTERFACE, MANAGER_PATH, VOCABULARY_DIR
from obscura_capd.vocabulary import load_vocabulary


def vocabulary_directory():
    """capd's declaration directory; the same override capd honours, for tests."""
    try:
        return os.environ.get("OBSCURA_CAPD_VOCABULARY_DIR", VOCABULARY_DIR)
    except Exception as error:
        report.failure("capabilities.vocabulary_directory", error)
        raise


def capability_vocabulary():
    """{name: Declaration}. Invalid declarations are reported and skipped by capd's loader."""
    try:
        return load_vocabulary(vocabulary_directory())
    except Exception as error:
        report.failure("capabilities.capability_vocabulary", error)
        raise


def present_capabilities():
    """Names capd reports present, or None if capd can't be asked (reported). None makes
    readiness 'couldn't evaluate' for any pack with requirements, never Ready."""
    try:
        try:
            from dasbus.connection import SystemMessageBus

            from obscura_capd.errors import ERROR_MAPPER

            bus = SystemMessageBus(error_mapper=ERROR_MAPPER)
            proxy = bus.get_proxy(BUS_NAME, MANAGER_PATH, MANAGER_INTERFACE)
            return frozenset(proxy.List())
        except Exception as error:
            report.problem("capabilities", "capability service unavailable: " + str(error))
            return None
    except Exception as error:
        report.failure("capabilities.present_capabilities", error)
        return None
