# VM tests: capability framework (tasks 0.2, 0.2b and 0.2c)

`capabilities.sh` checks the real udev → systemd → DBus path on the built image. The
unit and DBus integration tests (`tests/unit`, `tests/integration`) run in CI; these
need the image booted in a VM.

## VMware Workstation setup (Windows host)

1. Boot a VM from the built image (or `bootc switch` / `rpm-ostree rebase` an existing
   Fedora Atomic VM to `ghcr.io/<owner>/obscura:latest`), then reboot.
2. **Baseline hardware for C-1:** no webcam connected (C-1 still passes with one
   connected, but then it expects `camera` present), *Options → Power → Report
   battery information to guest* off, *Processors → Virtualize Intel VT-x/EPT or
   AMD-V/RVI* off.
3. **Disable automatic updates:** `sudo systemctl disable --now uupd.timer`. uupd stages
   new images (and Flatpak updates) on a timer, which can swap the image under test, and a
   failed uupd run (as on the 0.2b image: a denied Flatpak user update, upstream) fails
   every "no failed units" check. If it already failed this boot, also run
   `sudo systemctl reset-failed uupd.service`. The scripts print a warning while the timer
   is enabled. Whether Obscura keeps uupd is an open decision (build brief §6, Stage 0).
4. Copy `tests/` into the VM (the scripts source `tests/lib/`) and run
   `tests/vm/capabilities.sh` as root.

## Tests

| ID | Command | Setup | Status |
|---|---|---|---|
| C-1 | `sudo ./capabilities.sh state` | Baseline: other capabilities absent, no failed units, no capd warnings. `camera` is checked against ground truth, not assumed absent. It must be present if and only if some `/dev/video*` node is a capture node of a physical device: `/usr/lib/udev/v4l_id` run now reports `:capture:` (udev's database can be stale), the node isn't under `/sys/devices/virtual`, and no driver on it or a parent is `vivid` or `v4l2loopback` (`VIRTUAL_V4L_DRIVERS`); the script prints the matching nodes. So a connected webcam passes as present, and Aurora's "OBS Virtual Camera" (v4l2loopback) doesn't count, idle or streaming | Ready |
| C-2 | `sudo ./capabilities.sh virt` | Nested virtualization on | **Blocked**: the option is unavailable while Hyper-V (VBS, WSL2, Credential Guard) is on in the host. The script skips until `/dev/kvm` exists |
| C-3 | `sudo ./capabilities.sh hotplug-camera 10` | USB controller set to USB 3.1; the script prompts you to use *VM → Removable Devices → (webcam) → Connect / Disconnect* each cycle | Ready (interactive) |
| C-4 | `sudo ./capabilities.sh hotplug-battery 10` | Uses the `test_power` module | **Likely skipped**: Fedora's kernel config has `# CONFIG_TEST_POWER is not set` (kernel-ark `common/generic`, no Fedora override). The script checks with `modinfo` and skips. Run C-4 on the laptop instead (unplug/replug isn't possible for an internal battery, so there it's a presence check plus a reboot with the battery reported) |
| C-4b | `sudo ./capabilities.sh state --present battery` | *Report battery information to guest* on (only gives a battery if the host has one; VM must be powered off to change it) | Presence only, no hotplug |
| C-5 | `sudo ./capabilities.sh restart` | Any | Ready |
| C-6 | `sudo ./capabilities.sh semantics` | Any. `has` prints `present` (exit 0) or `absent` (exit 1); an unknown name exits 2 with nothing on stdout | Ready |
| C-7 | `sudo ./capabilities.sh no-fake` | Any | Ready |
| C-9 | `sudo ./capabilities.sh bus-policy` | Any. Runs as `nobody`: List, Has, GetManagedObjects and Properties.GetAll succeed; Properties.Set is refused with AccessDenied. The CI bus is permissive, so this is the only check of the policy file | Ready |
| C-8 | `sudo ./capabilities.sh mcelog` | Any; also run on the Ryzen desktop (§12 item 14) | Ready |

`sudo ./capabilities.sh all` runs C-1, C-5 to C-13, C-15 and C-17 (not the interactive ones)
in one go.
Exit codes: 0 pass, 1 fail, 77 skipped.

With a webcam connected, check presence with `state --present camera`. With several
capabilities present: `state --present battery,camera`. Static capabilities
(`x86-64-v3`) aren't part of `state`'s baseline, because the tester can't change them;
C-10 checks them.

## Static capabilities (task 0.2b)

Build brief §7, "Stage 0 — static capabilities". **Run C-11 first after a fresh boot.**
For C-12, turn on *Display → Accelerate 3D graphics*, so the VM has a DRM render node
(vmwgfx) and the probe actually runs. Run C-12 before C-13: C-12 checks that the target
never entered active this boot, and C-13 then restarts the probes. On VMware the probe now rejects the node
for its kernel driver (vmwgfx, a virtual GPU) and still logs why each Vulkan device,
lavapipe included, wouldn't count; the lavapipe rule itself is checked in CI against the
real recording.

| ID | Command | Setup | Status |
|---|---|---|---|
| C-10 | `sudo ./capabilities.sh x86-64-v3` | Any. Each `ConditionCPUFeature=` line must agree with `/proc/cpuinfo` (FMA is `fma3` to systemd, `fma` to the kernel; `osxsave` is hidden by the kernel), glibc's `ld.so --help` must agree, and the capability must match | Ready |
| C-10b | `sudo ./capabilities.sh x86-64-v3` | Optional negative: power off, add `cpuid.7.ebx = "----:----:----:----:----:----:--0-:----"` to the .vmx (masks AVX2), boot. Expect absent, nothing failed. Remove the line afterwards | Optional |
| C-11 | `sudo ./capabilities.sh boot-order` | Fresh boot. sysinit.target and obscura-capd are ordered after the x86-64-v3 target, and capd started after its conditions ran | Ready |
| **C-12** | `sudo ./capabilities.sh vulkan-lavapipe` | 3D acceleration on. Skips unless `vulkaninfo --summary` shows llvmpipe at Vulkan ≥ 1.3. Then: vulkan-1.3 absent, the target inactive and never active this boot: this boot's journal (by boot ID) logs at least one start of the target, each one a condition skip (255 or 262 wording), and no real "Reached target" (offending lines are printed on failure); no "capability present: vulkan-1.3" from capd; `ActiveEnterTimestamp` 0 is printed as a secondary note only, because a target unloaded and reloaded during the boot also reads 0, no accept marker under `/run/obscura-cap/vulkan-1.3/`, every `obscura-cap-vulkan-1.3-probe@renderD*` inactive with Result `exec-condition`, a journal reason per node, no failed units. The `real-vmware-lavapipe-*` fixture is committed (2026-11-24). Re-record it only if the base image's Mesa changes (as your normal user, outside the repo): `python3 tests/fixtures/vulkan/capture.py ~/vulkan-capture --label vmware-lavapipe` | Ready |
| C-13 | `sudo ./capabilities.sh vulkan-no-fake` | Manual start of the target is refused. Each probe is restarted 20 times: after each, the journal logs the target's start job as skipped by its condition and never a real "Reached target"; with the target and probes pinned (`Manager.RefUnit`, checked each round), it never entered active and `ConditionResult=no`; and `obscura-cap watch` never printed `+vulkan-1.3`. A probe for a nonexistent node never runs; the target's start job waits behind it, and cancelling the probe leaves the target inactive | Ready |
| C-14 | `sudo ./capabilities.sh unplug` | Webcam passthrough, as C-3. Disconnect the webcam before starting (the test needs to see it appear). Builds a stand-in from the installed probe and target with `tests/lib/stand-in.sh` (only the names, the marker path, the device and the detection command change) bound to the webcam's video node (it waits up to 15 s after Connect for a new active/plugged `dev-video*.device`; only the webcam's capture node gets one. If none appears it prints the before/after lists, the exact listing command and its raw output); it must write its marker and activate the stand-in target, and disconnecting the webcam must stop the target within 5 s, marker gone, without a reboot. The VM can't have a qualifying GPU, so the real unplug is D-3 on the desktop | Ready (interactive) |

## Virtual cameras (task 0.2c)

Build brief §6 (0.2c notes) and §7. Aurora loads v4l2loopback ("OBS Virtual Camera",
`exclusive_caps=Y`). The producer is **ffmpeg**, already in the image:
`ffmpeg -re -f lavfi -i testsrc2=size=640x480:rate=30 -pix_fmt yuyv422 -f v4l2 /dev/videoN`.
While it runs, `v4l_id` reports the node as `:capture:`. v4l2loopback 0.15.4 sends no
uevent when ffmpeg starts or stops, so the tests force one with
`udevadm trigger --action=change` and report natural events without requiring them.

| ID | Command | Setup | Status |
|---|---|---|---|
| **C-15** | `sudo ./capabilities.sh loopback` | Webcam disconnected (skips if a physical capture node exists or v4l2loopback isn't loaded). Streams into the loopback, then checks: after a change event udev's database has `:capture:` with no `systemd` tag and no `SYSTEMD_WANTS`; `camera` absent before, during and after the stream; C-1 passes while streaming; `rule_crosscheck.py` agrees; no real "Reached target obscura-cap-camera.target"; no `+camera` from `obscura-cap watch`. **On the 0.2b image this fails** (camera present after the change event): that's the bug, reproduced in the recon of 2026-11-24 | Passed on the 0.2c image (2026-11-24) |
| C-16 | `sudo ./capabilities.sh loopback-webcam` | Webcam passthrough, as C-3. The script asks you to disconnect the webcam, streams into the loopback, then asks you to connect and disconnect it: present within 15 s with only the webcam in the ground truth, absent within 5 s, exactly one `+camera` and one `-camera`, the stream running throughout | Passed (interactive) on the 0.2c image (2026-11-24) |
| C-17 | `sudo ./capabilities.sh rule-crosscheck` | Any; more useful with the webcam connected or vivid loaded. For each video node and for change and add events, `tests/lib/rule_crosscheck.py` triggers a real event, reads the database (CURRENT_TAGS, SYSTEMD_WANTS) and compares it with `tests/lib/udev_rules.py`'s verdict on the node recorded right after. `udevadm test` isn't used: on systemd 262 it skips `IMPORT{program}`, so `ID_V4L_CAPABILITIES` is never set | Passed on the 0.2c image (2026-11-24) |

The camera alternative to USB passthrough is the `vivid` virtual driver: it's in the
image (`sudo modprobe vivid`). It **must not** make `camera` present, since it's virtual
(a platform device bound to `vivid`, excluded by the rule's `DRIVERS==` line), so it
can't stand in for a webcam in C-3. Load it for C-17, then `sudo modprobe -r vivid`.

To re-record the v4l fixtures, see `tests/fixtures/v4l/README.md`.

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
