# Vulkan fixtures (task 0.2b)

`vulkaninfo --json` output used to test the `vulkan-1.3` acceptance rule
(`obscura_capd/vulkan_rule.py`). Build brief §7, "Stage 0 — static capabilities".

## Real and synthetic
- **`real-*.json`** are recordings from real machines, made with `capture.py`. Only real
  recordings count toward acceptance:
  - the lavapipe negative test reads `real-vmware-lavapipe.json` and nothing else;
  - the "vulkan-1.3 present" test reads only `real-*` files marked **real** below, and
    skips until one exists (open item in the build brief).
- **`synthetic-*.json`** are written by hand from the vulkaninfo schema to exercise the
  rule's branches. They never satisfy an acceptance test.

A lint (`tests/unit/test_vulkan_fixtures.py`) checks that every fixture has a row here, that
its prefix matches the row's Origin, and that no fixture contains a UUID or LUID key.

## Recording
On the machine to record (a Fedora live USB works):

    sudo dnf install -y vulkan-tools
    python3 capture.py ~/vulkan-capture --label <machine>-<driver>

The script removes every key containing `UUID` or `LUID` (and `deviceNodeMask`) and refuses
to write inside a git checkout. Review the output, copy the `real-*.json` files here, and
add a row for each. Put the `nodes.json` render-node map in the Notes column (or alongside,
as `real-<label>-nodes.json`).

## Files

| File | Origin | Source | Purpose |
|---|---|---|---|
