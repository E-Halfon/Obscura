# VM tests: capability framework (tasks 0.2 and 0.2b)

`capabilities.sh` checks the real udev → systemd → DBus path on the built image. The
unit and DBus integration tests (`tests/unit`, `tests/integration`) run in CI; these
need the image booted in a VM.

## VMware Workstation setup (Windows host)

1. Boot a VM from the built image (or `bootc switch` / `rpm-ostree rebase` an existing
   Fedora Atomic VM to `ghcr.io/<owner>/obscura:latest`), then reboot.
2. **Baseline hardware for C-1:** no webcam connected, *Options → Power → Report
   battery information to guest* off, *Processors → Virtualize Intel VT-x/EPT or
   AMD-V/RVI* off.
3. Copy `tests/vm/capabilities.sh` into the VM and run it as root.

## Tests

| ID | Command | Setup | Status |
|---|---|---|---|
| C-1 | `sudo ./capabilities.sh state` | Baseline: all absent, no failed units, no capd warnings | Ready |
| C-2 | `sudo ./capabilities.sh virt` | Nested virtualization on | **Blocked**: the option is unavailable while Hyper-V (VBS, WSL2, Credential Guard) is on in the host. The script skips until `/dev/kvm` exists |
| C-3 | `sudo ./capabilities.sh hotplug-camera 10` | USB controller set to USB 3.1; the script prompts you to use *VM → Removable Devices → (webcam) → Connect / Disconnect* each cycle | Ready (interactive) |
| C-4 | `sudo ./capabilities.sh hotplug-battery 10` | Uses the `test_power` module | **Likely skipped**: Fedora's kernel config has `# CONFIG_TEST_POWER is not set` (kernel-ark `common/generic`, no Fedora override). The script checks with `modinfo` and skips. Run C-4 on the laptop instead (unplug/replug isn't possible for an internal battery, so there it's a presence check plus a reboot with the battery reported) |
| C-4b | `sudo ./capabilities.sh state --present battery` | *Report battery information to guest* on (only gives a battery if the host has one; VM must be powered off to change it) | Presence only, no hotplug |
| C-5 | `sudo ./capabilities.sh restart` | Any | Ready |
| C-6 | `sudo ./capabilities.sh semantics` | Any | Ready |
| C-7 | `sudo ./capabilities.sh no-fake` | Any | Ready |
| C-9 | `sudo ./capabilities.sh bus-policy` | Any. Runs as `nobody`: List, Has, GetManagedObjects and Properties.GetAll succeed; Properties.Set is refused with AccessDenied. The CI bus is permissive, so this is the only check of the policy file | Ready |
| C-8 | `sudo ./capabilities.sh mcelog` | Any; also run on the Ryzen desktop (§12 item 14) | Ready |

`sudo ./capabilities.sh all` runs C-1, C-5 to C-13 (not the interactive ones) in one go.
Exit codes: 0 pass, 1 fail, 77 skipped.

With a webcam connected, check presence with `state --present camera`. With several
capabilities present: `state --present battery,camera`. Static capabilities
(`x86-64-v3`) aren't part of `state`'s baseline, because the tester can't change them;
C-10 checks them.

## Static capabilities (task 0.2b)

Build brief §7, "Stage 0 — static capabilities". **Run C-11 first after a fresh boot.**
For C-12, turn on *Display → Accelerate 3D graphics*, so the VM has a DRM render node
(vmwgfx) and the probe actually runs.

| ID | Command | Setup | Status |
|---|---|---|---|
| C-10 | `sudo ./capabilities.sh x86-64-v3` | Any. Each `ConditionCPUFeature=` line must agree with `/proc/cpuinfo` (FMA is `fma3` to systemd, `fma` to the kernel; `osxsave` is hidden by the kernel), glibc's `ld.so --help` must agree, and the capability must match | Ready |
| C-10b | `sudo ./capabilities.sh x86-64-v3` | Optional negative: power off, add `cpuid.7.ebx = "----:----:----:----:----:----:--0-:----"` to the .vmx (masks AVX2), boot. Expect absent, nothing failed. Remove the line afterwards | Optional |
| C-11 | `sudo ./capabilities.sh boot-order` | Fresh boot. sysinit.target and obscura-capd are ordered after the x86-64-v3 target, and capd started after its conditions ran | Ready |
| **C-12** | `sudo ./capabilities.sh vulkan-lavapipe` | 3D acceleration on. Skips unless `vulkaninfo --summary` shows llvmpipe at Vulkan ≥ 1.3. Then: vulkan-1.3 absent, the target inactive, every `obscura-cap-vulkan-1.3-probe@renderD*` inactive with Result `exec-condition`, a journal reason per node, no failed units. **Then record the fixture** (as your normal user, outside the repo): `python3 tests/fixtures/vulkan/capture.py ~/vulkan-capture --label vmware-lavapipe`, and commit the `real-vmware-lavapipe-*` files with README rows marked real | Ready |
| C-13 | `sudo ./capabilities.sh vulkan-no-fake` | Manual start of the target is refused; rerunning a probe leaves it absent; a probe for a nonexistent node never runs | Ready |
| C-14 | `sudo ./capabilities.sh unplug` | Webcam passthrough, as C-3. Builds a stand-in from the installed probe and target (only the device, target name and detection command swapped) bound to the webcam's video node, then checks that disconnecting it stops the target within 5 s without a reboot. The VM can't have a qualifying GPU, so the real unplug is D-3 on the desktop | Ready (interactive) |

The camera alternative to USB passthrough is the `vivid` virtual driver. Fedora builds it
(`CONFIG_VIDEO_VIVID=m`), but it may live in a modules package Aurora doesn't install:
check `modinfo vivid` in the VM.

# VM tests: pack format (task 0.21)

`packs.sh` checks pack manifests and readiness on the built image (P-1…P-7, build brief
§7 "Stage 0 — pack format"). The unit tests and `tests/integration/test_packs_capd.py`
run in CI.

1. Copy the whole `tests/` directory into the VM. The script reads `tests/fixtures/`, or
   set `OBSCURA_FIXTURES` to its location.
2. Run it as your **normal user**, not root: readiness is per user. It uses a scratch home
   and a scratch installed root, so your real `~/Obscura` and `/var/lib/obscura/packs`
   are never touched.

| ID | Command | Setup | Status |
|---|---|---|---|
| P-1 | `./packs.sh factory` | Any | Ready |
| P-2 | `./packs.sh wine` | Any. Expects **Insufficient hardware**. Before task 0.2b the reasons are `capability-unknown` for both capabilities; after 0.2b, `vulkan-1.3` is absent, because the VM has no hardware-accelerated Vulkan. Ready is checked on the bare-metal desktop | Ready |
| P-3 | `./packs.sh no-reqs` | Any | Ready |
| P-4 | `./packs.sh camera` | Webcam disconnected at start; the script asks you to connect and then disconnect it through *VM → Removable Devices* (as in C-3) | Ready (interactive) |
| P-5 | `./packs.sh files` | Any. Writes generated test content only, never real firmware | Ready |
| P-6 | `./packs.sh removed` | Any | Ready |
| P-7 | `./packs.sh malformed` | Any | Ready |

`./packs.sh all` runs everything except P-4. Exit codes: 0 pass, 1 fail, 77 skipped.
