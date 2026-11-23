"""Camera Obscura pack format v1: manifests, the installed catalog, and readiness
(ARCHITECTURE.md §17, build-brief task 0.21).

Pure logic (manifest, readiness) is kept apart from I/O (catalog, userfiles,
capabilities) so it can be unit-tested without a bus or a real home directory.
Failures are reported through obscura_capd.report.
"""
