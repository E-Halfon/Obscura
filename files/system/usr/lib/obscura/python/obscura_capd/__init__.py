"""Camera Obscura capability service (ARCHITECTURE.md §4, build-brief task 0.2).

obscura-capd mirrors the state of obscura-cap-<name>.target for every declared
capability onto the system bus as org.obscura.Capabilities1. It never detects hardware
itself: udev and systemd do that. Capabilities are hardware facts only; pack
availability belongs to the pack manager (PACKS.md §2).

Modules that import dasbus (bus, mirror, service, daemon, cli) only run on Linux.
The rest (constants, report, vocabulary, state) are pure Python so they can be tested
anywhere.
"""
