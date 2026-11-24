# Vulkan fixtures (task 0.2b)

`vulkaninfo --json` output used to test the `vulkan-1.3` acceptance rule
(`obscura_capd/vulkan_rule.py`). Build brief §7, "Stage 0 — static capabilities".

## Real and synthetic
- **`real-*.json`** are recordings from real machines, made with `capture.py`. Only real
  recordings count toward acceptance:
  - the lavapipe negative test reads the `real-vmware-lavapipe-*` files (`real-vmware-lavapipe-gpu<n>-<driver>-<api>.json` and `real-vmware-lavapipe-nodes.json`) and nothing else;
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
to write inside a git checkout. Review the output, copy the `real-*.json` files here
(device files and `real-<label>-nodes.json`), and add a row for each, with Origin `real`
and the Source from `capture-info.json` (machine class, Mesa and vulkaninfo versions,
date). Don't copy `capture-info.json` itself.

The VMware recording (`--label vmware-lavapipe`, VM test C-12) is the only input to the
lavapipe negative test. It was recorded on 2026-11-24 and is committed.

## Scenarios
Files group into scenarios by label: `<origin>-<label>-gpu<n>-<driver>-<api>.json` (one per
Vulkan device, as `capture.py` writes them) plus `<origin>-<label>-nodes.json` (the render
nodes). A scenario is real only if every one of its files is marked real.

## Files

| File | Origin | Source | Purpose |
|---|---|---|---|
| `real-vmware-lavapipe-gpu0-llvmpipe-1.4.json` | real | VMware VM on the 0.2b image (vmwgfx, renderD128), Mesa 26.2.7 (LLVM 23.1.5), Vulkan instance 1.4.350, kernel 7.3.4-300.fc45, capture.py 2026-11-24 | lavapipe claiming Vulkan 1.4 with no GPU: never counts (lavapipe negative test, C-10/C-12) |
| `real-vmware-lavapipe-nodes.json` | real | same recording | render node map: renderD128 on vmwgfx |
| `synthetic-radv-lavapipe-gpu0-radv-1.4.json` | synthetic | hand-written, task 0.2b | RADV discrete GPU on renderD128: accepted for its own node only |
| `synthetic-radv-lavapipe-gpu1-llvmpipe-1.4.json` | synthetic | hand-written, task 0.2b | lavapipe alongside it: never counts |
| `synthetic-radv-lavapipe-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
| `synthetic-discrete-integrated-gpu0-radv-1.4.json` | synthetic | hand-written, task 0.2b | discrete GPU on renderD128 |
| `synthetic-discrete-integrated-gpu1-intel-open-source-mesa-driver-1.4.json` | synthetic | hand-written, task 0.2b | integrated GPU on renderD129 |
| `synthetic-discrete-integrated-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
| `synthetic-venus-virtual-gpu0-venus-1.3.json` | synthetic | hand-written, task 0.2b | virtio-gpu Venus passing the host's `DISCRETE_GPU` type through, with a DRM node: rejected by driver ID `MESA_VENUS` |
| `synthetic-venus-virtual-gpu1-llvmpipe-1.4.json` | synthetic | hand-written, task 0.2b | lavapipe in the same guest: rejected |
| `synthetic-venus-virtual-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
| `synthetic-radv-no-drm-ext-gpu0-radv-1.4.json` | synthetic | hand-written, task 0.2b | a GPU without `VkPhysicalDeviceDrmPropertiesEXT`: rejected |
| `synthetic-radv-no-drm-ext-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
| `synthetic-gpu-api-1.2-gpu0-intel-open-source-mesa-driver-1.2.json` | synthetic | hand-written, task 0.2b | device apiVersion 1.2 under a 1.3 profile version: rejected |
| `synthetic-gpu-api-1.2-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
| `synthetic-wrong-type-other-gpu0-radv-1.3.json` | synthetic | hand-written, task 0.2b | device type `OTHER`: rejected |
| `synthetic-wrong-type-other-nodes.json` | synthetic | hand-written, task 0.2b | render node map |
