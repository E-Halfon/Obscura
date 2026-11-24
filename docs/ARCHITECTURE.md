# Camera Obscura Systems — Architecture

**Status:** Stage 0 in progress
**Version:** 3.1
**Last updated:** 2026-11-23
**Companion documents:** CAMERA-OBSCURA-BUILD-BRIEF.md (plan), PACKS.md (pack catalog)

> **If you are an AI assistant reading this at the start of a session:** this document is
> the canonical record of the project. Assume the decisions in §11 are settled and the
> rejections there are settled *with reasons* — don't re-propose them. Open problems in
> §12 are where help is actually wanted. §17–§24 (added in v3.0) define the pack system,
> the user experience, and the automation layer.

---

## 0. Mission statement

> **Camera Obscura runs software from any operating system as part of one cohesive
> system. It reimplements the platform where it can and runs the real platform hidden
> where it can't, and the user never sees the difference.**

Two tenets, in the owner's words:
1. **Cross-platform integrability.** One black box that runs any other system's software,
   removing the need for other operating systems and unifying every device.
2. **No spying, no planned obsolescence.** No telemetry, no bloatware, no ads, no
   throttling to force upgrades.

The test of "one OS" is **what the user sees**, not whether any other OS code runs
anywhere. The Neo runs real macOS and the Windows VM runs real Windows; both are hidden
behind Obscura windows, so both are within the mission.

**Scope:** Windows, macOS, Android, Linux, and consoles. **iOS is out of scope**; iPhone
and iPad apps that Apple allows on Apple Silicon Macs are reached through the Neo.

**Three ways to run foreign software, in order of preference:**

| Tier | Pattern | Examples |
|---|---|---|
| 1. Reimplement | Run the software natively against reimplemented libraries | Wine, Waydroid, shadPS4, emulators, static recompilers |
| 2. Hidden real OS, integrated | The real OS runs hidden; an agent mirrors each window | Neo (macOS), hidden Windows VM |
| 3. Hidden real hardware, external | Real hardware runs stock; Obscura captures video and injects input, or streams it | Switch capture, PS Remote Play, Xbox streaming |

**Every implementation is a separate, installable pack** (§17). New platforms are added
by installing a pack, not by changing the OS.

---

## 1. What this is

A Linux-based operating system that runs Windows, macOS, Android, and console software
alongside native Linux software. Foreign applications appear as **ordinary windows in the
Obscura desktop** — no VM chrome, no nested desktop, no "app inside an app."

It is a personal project. **Never sold; open source.** Being non-commercial does not
remove legal exposure (§14) — open-source distribution is exactly where it arises.

**Motivations:**
- Escape the telemetry and bloatware of Windows and macOS
- Fix the cross-platform experience for someone using a PC alongside an iPhone
- Run hardware whose drivers only ship for other OSes
- Use libraries that have no Linux equivalent

**Target hardware:** three builds, in order — desktop, thick laptop, pocket computer.
**One OS image across all three.** Capabilities activate wherever the hardware exists.

---

## 2. Design principles

1. **One image, capability-gated.** The same OS ships to every device. Features light up
   when their hardware is detected and stay dormant otherwise. A desktop with a cellular
   module can make phone calls; a desktop without one simply has no dialer. See §4.
2. **The host owns the screen.** Guest environments request; Obscura decides placement,
   stacking, and focus. Never let a guest position its own windows on the real display.
3. **Default deny outbound.** Every foreign subsystem is sandboxed with no network unless
   explicitly allowlisted.
4. **Coprocessors are untrusted.** Obscura's central job is arbitrating between black
   boxes it cannot audit — the Apple board and the cellular baseband are two instances of
   one pattern, and both get the same treatment (§9).
5. **One transport abstraction.** Desktop uses a cable, laptop an internal bus, pocket
   computer a hinge flex. Nothing above the transport layer may care which.
6. **Reimplement locally, never impersonate remotely.** See §3.
7. **Every implementation is a pack.** Wine, Waydroid, the Neo, emulators — none are
   hardcoded into the core. Built-ins use the same pack format a future PS6 pack would (§17).
8. **No terminal required.** If a normal task requires a terminal, that's a bug. The
   terminal stays available but is never necessary (§19).
9. **No ads, suggestions, nags, or telemetry.** Not hidden behind toggles — absent.

---

## 3. The core insight: three problems, three techniques

The single most important thing to understand. "Run foreign binaries" is not one problem.

| Technique | What it does | Cost | Used for |
|---|---|---|---|
| **API reimplementation** | Supplies missing OS libraries; binary runs natively | ~none | Windows (Wine) |
| **Containerization** | Guest userspace on the host kernel | low | Android (Waydroid) |
| **User-mode binary translation** | Translates instruction stream, syscalls pass through | 1.1–2x | Cross-ISA only |
| **Static recompilation** | Lifts machine code to IR ahead of time, emits a native binary | ~none at runtime | Legacy consoles, Android ARM `.so` (§10.5) |
| **Full-system emulation** | Emulates CPU + chipset + boots a guest kernel | 5–20x | **avoided** |

An x86-64 Windows `.exe` is *already native code* on an x86-64 Linux box. Nothing needs
emulating. What's missing is `ntdll`, `kernel32`, the PE loader, the registry, and the
Win32 object manager — all of which Wine provides as ELF libraries.

### The rule that governs everything about Apple

> **API reimplementation works for local computation. It fails at network services with
> hardware attestation.**

Wine works because Win32 is a local ABI — nothing phones home to check you're on real
Windows. Apple's services always check, and the check is answered by silicon:

- **iMessage/FaceTime** route through APNs and authenticate via IDS using a device
  identity certificate derived from serial, board ID, ROM, MLB, and the Secure Enclave.
- **iCloud, Apple Pay, App Attest** — same pattern.

No amount of framework reimplementation produces that certificate. This is why the macOS
strategy is *hardware*, not software (§7).

### The parallel rule for telephony

> **Never implement a protocol stack the hardware already contains.**

IMS/VoLTE is unimplemented on the Linux host side across the entire mobile-Linux
ecosystem. The correct move is to select a modem whose firmware does IMS internally and
have Obscura handle only signaling and audio routing. See §8.

---

## 4. Capability architecture

The mechanism that makes one image work across three very different machines.

**A capability is:** a declared feature, a hardware detection rule, whether the user can
fix its absence by connecting something (`attachable`, used by pack readiness §17.3), the
services it activates, and the UI surfaces it exposes. Nothing more.

| Capability | Detection | Activates | Present on |
|---|---|---|---|
| `x86-64-v3` | static: `ConditionCPUFeature=` lines (psABI v2 + v3) checked at boot | lets `pack-wine`, `pack-proton` run | all |
| `vulkan-1.3` | udev: DRM render node appears → per-node probe (hardware GPU with Vulkan 1.3; lavapipe and virtual GPUs excluded) | lets `pack-wine`, `pack-proton` run (DXVK, VKD3D-Proton) | all |
| `virt` | udev: kvm misc device (`/dev/kvm`) appears | lets VM packs use KVM (e.g. `pack-windows-vm`) | all |
| `apple-coprocessor` | link peer responds | mirror client, virtual cam/audio, allowlist | opt-in per build |
| `telephony` | udev: modem on USB | ModemManager, voice audio bridge, dialer | opt-in per build |
| `battery` | `/sys/class/power_supply` | power arbitration, sleep policy | laptop, pocket computer |
| `touch` | udev: touchscreen | touch input, on-screen keyboard | pocket computer |
| `gps` | ModemManager or udev | location service (portal-gated) | opt-in |
| `camera` | udev: UVC or CSI | camera portal, virtual cam source | most |

Platform availability (`windows-apps`, `android-apps`) is not a capability and is not in
this table: it comes from packs, not the core (§17.4). The core supplies
only the kernel-level support they sit on: binder/binderfs, KVM, and `binfmt_misc`. Their
availability is pack readiness (§17.3), reported by the pack manager; the capability
service reports hardware only. The capability vocabulary is PACKS.md §2.

**Implementation:** udev detects → systemd activates the unit → the DBus interface
appears → the UI surface becomes reachable. This is how ModemManager already behaves:
per-feature DBus interfaces that simply aren't exported when the modem lacks the feature.
Follow that pattern rather than inventing one.

Concretely, each capability is a systemd target, `obscura-cap-<name>.target`: **active
means present, inactive means absent**, and nothing else is a source of truth. A udev rule
starts the target through `SYSTEMD_WANTS` when matching hardware appears;
`StopWhenUnneeded=yes` stops it when the last matching device goes; manual start and stop
are refused. Services that belong to a capability are `PartOf=` and `WantedBy=` its
target and never pull it in. `obscura-capd` (`org.obscura.Capabilities1` on the system
bus) loads the target for every declared capability (`/usr/share/obscura/capabilities.d/`)
and mirrors its state; it never detects anything itself. Upstream units that fail on
absent hardware get a drop-in condition (e.g. mcelog outside Intel hardware with
`/dev/mcelog`) so they are skipped, not failed.

Two variations keep the same rule (task 0.2b). A **static** capability is a fixed fact of
the machine: its target carries systemd conditions (`ConditionCPUFeature=` for
`x86-64-v3`), `sysinit.target` wants it through a drop-in, and a failed condition leaves
it inactive. The target is ordered before `sysinit.target` and capd after it, so capd
never sees a static target that hasn't been evaluated yet. A **probed** device capability
is one udev can't decide by itself, because the answer depends on a driver (`vulkan-1.3`).
udev starts a probe unit per device instead of the target. The probe runs its check as
`ExecCondition=`; only an accepting probe's `ExecStart=` writes
`/run/obscura-cap/<name>/<dev>/accepted`, in its `RuntimeDirectory=`, which systemd removes
whenever the probe goes inactive. The probe is `Before=` and `Upholds=` the target, and the
target is gated by `ConditionPathExistsGlob=` on those markers, so a rejecting probe can
never make it active, not even briefly: `Upholds=` pulls the target in like `Wants=`
whenever a probe starts, and `Before=` makes that start wait for the probe's decision. When
the check fails (or can't run), systemd skips the probe and nothing is failed. The marker
is read only by that condition; capd mirrors the target, as for every capability. The
probe is `BindsTo=` its device, so removing the last qualifying device stops the target
through `StopWhenUnneeded`, with no reboot.

**One universal image.** Capabilities are detected at **runtime**, never composed at
build time. Per-host composition (e.g. one NixOS flake per device) fails the flash-drive
test: copy the image to a USB stick, boot it on any of the three devices, and it must
work. The image therefore needs a generic kernel with `MODULES=most` in initramfs, both
`amdgpu` and `i915`/`xe`, UUID/LABEL mounts (never `/dev/sdX`), no hardware-specific kernel
parameters, UEFI boot, and all **hardware firmware** bundled. This is how live ISOs already
work.

**Two kinds of firmware — never confuse them:**
- **Hardware firmware** — `linux-firmware` blobs for GPUs, Wi-Fi, Bluetooth, and similar
  devices. Redistributable; shipped in the image through Fedora packages.
- **Platform firmware** — console and system firmware, BIOS files, keys. Never shipped in
  the image or any pack; the user supplies it (§14.2, §17.1).

Neither kind is ever committed to the repo.

**Architecture: x86-64 on every device.** AMD vs Intel is not an OS boundary — both
drivers ship in the image. ARM is rejected (§11): Wine would need translation and the
console emulators are x86-only.

**Rule:** a missing capability must be *absent*, never broken. No greyed-out dialer, no
error dialogs, no half-initialized services. Absence is the correct state.

---

## 5. Base OS

**Decided: Universal Blue, built with BlueBuild, on the Aurora base image**
(`ghcr.io/ublue-os/aurora`, `stable` stream). Aurora is Universal Blue's KDE Plasma image;
`recipes/recipe.yml` is the OS definition. See §11.

### History: the NixOS vs Fedora Kinoite / Universal Blue comparison

The GUI-first rule (§19) reopened the earlier NixOS choice. This comparison decided it and
is kept as the record of why.

| | NixOS | Fedora Kinoite / Universal Blue (Aurora, Bazzite) |
|---|---|---|
| Reproducibility | **Strongest** — whole system declared | Good — image-based |
| Atomic updates + rollback | Yes (generations) | Yes (ostree / bootc) |
| Universal image | Achievable; must avoid per-host flakes | Native to the model |
| GUI-first fit | **Poor** — config files and rebuild commands by nature; must be hidden behind the settings app | **Good** — updates and software already GUI-driven |
| Desktop | Any (Plasma available) | **KDE Plasma built in** |
| Head start on packs | Packages exist | Bazzite already ships Steam, Proton, Waydroid integration |
| Learning cost | High; 3-week timebox | Lower |

**Outcome: Universal Blue**, because the user-facing goals (§19) matter more than
maximal reproducibility.

The pocket computer is x86-64 and runs the same universal image (§4).

| Layer | Choice |
|---|---|
| Base | **Universal Blue Aurora** (`stable`), built with BlueBuild |
| Desktop shell | **KDE Plasma**, stripped and themed (§19) |
| Display | Wayland — **KWin**, which draws decorations for mirrored windows. The custom wlroots compositor is no longer needed |
| Audio | PipeWire — single clock domain, non-negotiable |
| Windows | `pack-wine`, `pack-proton` (Wine + Proton, DXVK, VKD3D-Proton); core supplies `binfmt_misc` and KVM |
| Android | `pack-waydroid` (Waydroid, LXC); core supplies mainline binder/binderfs |
| Dispatch | `binfmt_misc` + dispatcher + compatibility database (§18) |
| Packs | Pack manager daemon over DBus; signed packs and system bundles (§17) |
| Settings plumbing | Typed action API as DBus services (§20) |
| Assistant runtime | llama.cpp, Vulkan backend, 1–2B model loaded on demand (§21) |
| Sandbox | bubblewrap + XDG portals |
| Scheduling | cgroups v2 + rtkit for `SCHED_FIFO` |
| Firewall | nftables, default-deny outbound |
| Telephony | ModemManager + voice audio bridge |
| eSIM | lpac (open-source LPA) |

---

## 6. Windows and Android subsystems

### 6.1 Windows

- **Dispatch:** register `MZ` magic in `binfmt_misc` → Wine. Double-clicking a `.exe`
  works with no launcher shim.
- **Graphics:** DXVK (D3D9/10/11 → Vulkan), VKD3D-Proton (D3D12 → Vulkan).
- **Display:** Wine's Wayland driver. One Wayland surface per Win32 window, dmabuf-shared
  buffers. No framebuffer copies.
- **Sandbox:** bubblewrap, no network by default, portal-mediated file access.

**Friction:** Win32 priority classes don't map cleanly to Linux scheduling — map onto
cgroups v2 + `SCHED_FIFO` via rtkit; symptoms of failure are audio crackle and input lag.
Route all audio through PipeWire. Input integration is harder than output: layouts, IME
composition, modifier semantics, per-window HiDPI, scroll direction, gamepad hotplug.

**Out of scope:** kernel anti-cheat. Adversarial treadmill, breaks users unpredictably,
and fundamentally incompatible with principle #3. Proton + EAC/BattlEye already work when
developers opt in — the blocker is a per-title toggle, not technology.

**Wine is not enough on its own.** The project's own headline examples — SolidWorks and
Adobe Creative Cloud — are among the worst-behaved Windows apps under Wine, as are
MSIX/Microsoft Store apps. Those route to the **hidden Windows VM** (§10.6).

### 6.2 Android

Waydroid. Android userspace in an LXC container on the host kernel (binder mainline since
Linux 4.19). Already composites Android windows as native Wayland surfaces.

**Friction:** Android expects its own cgroup tiering and wakelock semantics. Play
Integrity will fail — accepted.

---

## 7. macOS subsystem — Apple coprocessor

**Scope:** four applications only — iMessage, FaceTime, iCloud, GarageBand.

### 7.1 The board

**Apple MacBook Neo logic board (A18 Pro).** Apple's $599 entry MacBook, torn down
March 2026. iFixit photographed its board beside an iPhone 16 Pro board — same A18 Pro
package footprint, described as "ruler-shaped" and smaller than an iPad 10's.

| | MacBook Neo | Mac mini M4 | Hackintosh x86 | Donor iPhone |
|---|---|---|---|---|
| Footprint | ~iPhone-scale | ~110 mm square | 70–85 mm SBCs | phone-scale |
| Idle power | ~1 W | 4–7 W | 2–4 W | ~1 W |
| Cooling | passive | active fan | fan/big sink | passive |
| Apple ID identity | **real** | real | spoofed SMBIOS | real |
| Headless capable | **yes** | yes | yes | **no** |
| Alive past 2028 | **yes** | yes | **no** | yes |

**Decisive:** genuine Apple ID identity (no SMBIOS spoofing, no burned serials); Apple
Silicon so it survives the Intel cutoff; and **macOS has Screen Sharing while iOS has no
headless mode** — which is what kills the donor-iPhone alternative.

### 7.2 Per-window mirroring

Not Screen Sharing — that yields one rectangle containing a whole desktop.

**On the Neo (agent):** `ScreenCaptureKit` with `SCContentFilter` per `SCWindow` → one
hardware-encoded HEVC stream per window; `CGWindowListCopyWindowInfo` for enumeration and
geometry; `AXUIElement` for titles, focus, lifecycle; `CGEventPost` for injected input.

**On Obscura:** one Wayland surface per remote window, host media engine decode.

**Never ship raw frames.** Uncompressed 1080p60 ≈ 3 Gbps; HEVC ≈ 20 Mbps.

### 7.3 Peripheral virtualization

Camera, mic, and speakers live on the **Obscura** side. FaceTime needs Obscura's real
sensors piped *into* macOS: a `CMIOExtension` virtual camera plus a virtual audio device
fed across the link. Most commonly underestimated part of the design.

---

## 8. Telephony subsystem

**Goal:** any Obscura device with a cellular module can place and receive calls, send
SMS, and use cellular data. Desktop included.

### 8.1 Voice is not data — three requirements

**1. A modem with voice support.** Many M.2 and USB WWAN modules have voice disabled in
firmware. Verify before buying.

**2. VoLTE/IMS.** Circuit-switched voice is dead in the US — AT&T, Verizon, and T-Mobile
completed 3G shutdown by 2022–24. There is **no CS fallback**. Voice means IMS.

> **Host-side IMS is rejected.** Ubuntu Touch's investigation found IMS unimplemented,
> with oFono's IMS API working only on the Intel xmm7modem and relying on the modem's own
> IMS implementation registered via AT commands. postmarketOS's position is that the QMI
> messages for IMS would need reverse-engineering. **Select a modem whose firmware does
> IMS internally.** Obscura handles signaling and audio only.

**3. An audio path.** Some modems expose voice only on PCM/I²S pins a USB dongle doesn't
break out. Require **USB Audio Class**. Reference implementation: the PinePhone-lineage
`q6voiced`, a daemon that listens for ModemManager call events over DBus and opens a
pseudo-ALSA device bridging the voice channel to speaker and mic.

### 8.2 Module candidates

| Module | For | Against |
|---|---|---|
| **SIMCom A7600 / A76xx** | ModemManager 1.24's simtech plugin added A760x support and fixed USB audio handling; cheap Waveshare breakouts; voice + audio codec | Less community history than EG25-G |
| **Quectel EG25-G** | Most thoroughly proven voice path in Linux mobile (PinePhone lineage) | LTE Cat 4, aging; VoLTE relies on community-patched firmware |
| Quectel RM520N / 5G modules | Fast data | Voice support poor to absent |
| Sierra EM7565, Fibocom laptop M.2 | Data | Usually data-only |

### 8.3 Attachment and isolation

**USB attachment, never PCIe.** A baseband is unauditable proprietary firmware; PCIe-
attached modems (MHI) have DMA to host RAM. USB gives no DMA and makes the modem a second
untrusted coprocessor behind a controlled interface — same posture, same nftables
treatment, same deny logging as the Apple board (§9).

### 8.4 eSIM

Requires an eUICC chip plus a Local Profile Assistant. Most embedded eUICCs accept only
GSMA-certified LPAs, which this project cannot be.

**Workable path:** a **removable eUICC card** (5ber, EasyEUICC) whose keys permit
third-party LPAs, driven by **lpac**, the open-source LPA.

**Stage 0 uses a physical SIM.** eSIM is a Stage 1+ refinement.

### 8.5 Constraints

- **Carrier IMEI whitelisting.** Carriers gate IMS provisioning on recognized device
  IMEIs. An unknown module may be denied VoLTE even when everything works locally.
  **Test with the actual carrier before committing to a design.**
- **Use a pre-certified module** — modular FCC approval covers personal use. **Never
  modify the IMEI**; it is a criminal offense in most jurisdictions.
- **One number across devices is a carrier problem, not a technical one.** Multi-device
  number sharing is typically restricted to carrier-approved hardware. Plan for separate
  lines, or a data plan plus a self-hosted SIP bridge.

---

## 9. Hardware topology and isolation

```
   ┌──────────────────┐        ┌─────────────────────┐        ┌──────────────┐
   │  Apple           │        │  Obscura board      │        │  Cellular    │
   │  coprocessor     │◄──────►│  (Linux)            │◄──────►│  module      │
   │  MacBook Neo     │  link  │                     │  USB   │  (untrusted) │
   │  A18 Pro         │        │  • sole DHCP server │  only  │              │
   │  headless        │        │  • sole default rte │        │  IMS in fw   │
   │  (untrusted)     │        │  • nftables         │        │  USB audio   │
   │                  │        │  • real cam/mic     │        │  no DMA      │
   │  NO Wi-Fi        │        │  • power authority  │        │              │
   │  NO Bluetooth    │        │  • Wine / Waydroid  │        │              │
   │  NO indep. route │        │  • ModemManager     │        │              │
   └──────────────────┘        └─────────────────────┘        └──────────────┘
```

Wi-Fi and Bluetooth disabled in the Apple board's **firmware**, not just the OS. Pull the
module physically where possible.

### 9.1 Per-build differences

| | Desktop | Laptop | Pocket computer |
|---|---|---|---|
| Compute | AMD Ryzen 8700G/9600X mini-ITX | Framework 13 AMD mainboard | LattePanda Mu (N100/N150), 200-pin SO-DIMM, open KiCad carrier files |
| Apple link | 2.5GbE direct, no switch | internal USB 3.2 Gen 2 | USB 3.2 Gen 2 over hinge flex |
| Modem | USB breakout, internal or external | M.2 (USB-attached) | M.2 (USB-attached) |
| Power | one ATX PSU | shared battery | shared battery |
| Coprocessor display | real monitor available | headless | headless |
| Thermal budget | irrelevant | moderate | **6–9 W total, skin-limited** |

**Ethernet through a hinge is not mechanically realistic** — the pocket computer's Apple link goes
over flex, carrying video, audio, and networking on one bus.

**USB4/Thunderbolt is not required.** HEVC window streams are ~20 Mbps each; USB 3.2 Gen 2's
10 Gbps is ample for a dozen plus audio and networking. Simpler flex, cheaper connectors,
fewer signal-integrity problems through a moving joint — and the Mu has no Thunderbolt.

### 9.2 Network isolation model

Apple **cannot** be given zero network access — iMessage, FaceTime, and iCloud are clients
for Apple's servers. Achievable goal:

> Apple gets exactly one path, through Obscura, to allowlisted endpoints. Nothing else.

**Stops:** telemetry, Siri analytics, diagnostics, ad attribution, Spotlight suggestions.

**Cannot stop:**
- **Content inspection.** Apple pins certificates; MITM fails closed. Allowlist by
  SNI/domain, not DPI.
- **Metadata.** Apple ID, registered devices, online times, contact graph. Inherent to
  routing. Enable Advanced Data Protection; accept the rest.
- **Modem↔tower traffic.** Opaque by construction. Isolation here is about DMA and host
  access, not about seeing what the baseband tells the network.

**Firewall shape:** default deny outbound. Allow APNs (`courier.push.apple.com`, 5223 with
443 fallback), Grand Slam auth (`gs.apple.com`), identity services, and only the iCloud
endpoints actually used. **Log every denied connection** — that log is the only evidence
isolation is holding.

GarageBand is pure local computation. Install, then block entirely.

### 9.3 Thermal reality (pocket computer)

Steady-state dissipation is bound by **skin area, not volume** — roughly **6–9 W
continuous for the whole device**, both SoCs, both displays, radio, everything. Extra
thickness buys transient buffer only. No fan (hinge, sealing, dust). Vapor chambers and
graphite spread heat; they don't remove it.

**Consequence:** Obscura holds power authority over every coprocessor — Apple board to
deep sleep (~0.1 W) when no Mac windows are open; modem to low-power when telephony is
idle; ability to throttle or suspend either under simultaneous load.

---

## 10. Driver strategy

Loading Windows `.sys` into the Linux kernel is **rejected**: IRPs vs `file_operations`,
IRQL vs preempt counts, DPCs vs workqueues, PE relocations expecting the NT loader, no
stable ABI, module signing, Secure Boot lockdown. Every bug is a kernel panic.
NDISwrapper did this in the 2000s; it was a maintenance catastrophe and it is dead.

**Preferred order:**

1. **Userspace drivers.** Most consumer hardware — HID, printers, scanners, audio
   interfaces, capture cards — is drivable from userspace via libusb, uhid, uinput, or
   VFIO. Run the vendor's Windows *usermode* driver under Wine with a shim transport to
   the real device. A crash kills a process, not the box. **The project's most novel
   potential contribution.**
2. **VFIO passthrough + functional re-export.** Give the device to a Windows VM, re-export
   its *function* to the host (capture card → `v4l2loopback`). Ugly, robust, ships.
3. **Reverse-engineer.** Vendor drivers are often a thin wrapper over a handful of USB
   control transfers. Wireshark + usbmon reveals more than expected.

eBPF is worth investigating — it enables much in userspace that once demanded kernel
modules.

---

## 10.5 Static recompilation and the lifter generator

A fourth technique, added to the §3 table. **Static recompilation** lifts machine code to
an IR (typically LLVM) and emits a native binary ahead of time. Not emulation — no runtime
interpretation, no 5–20x penalty — and not AI translation.

### 10.5.1 It is proven, and it is deterministic

**N64Recomp** (Zelda 64 Recompiled) and **XenonRecomp** (Sonic Unleashed Recompiled) are
shipping products. **XenonRecomp is Xbox 360 PowerPC → native x86**, which is exactly the
tier-3 console case the capability matrix otherwise excludes from the laptop.

They work because of three properties, all of which an LLM in the translation path
destroys:

1. **Deterministic lifting.** Same input, same output, provable IR-level semantics.
2. **A fixed, documented target platform.**
3. **A hand-written runtime** implementing the console's APIs — structurally the same role
   Wine plays for Win32.

### 10.5.2 Why AI does not belong in the translation path

**There is no verification oracle for a translated program.** Software that is 99%
correctly translated is worthless: one wrong instruction is a silent data-corruption bug
that surfaces hours later. LLMs produce *plausible* code, not *provably equivalent* code,
and checking would require the original behavior you are trying to recover.

Parts of the problem are **undecidable**, not merely hard — separating code from data in a
stripped binary, resolving indirect jump targets, handling self-modifying code. Model
capability does not close an undecidable gap.

And critically: **recompilation does not move the library boundary.** A perfectly
recompiled `.exe` still calls `CreateFileW`, still wants the registry, still expects the
Win32 object manager. You would still need Wine. This is Rule 1 again — the hard part was
never the instructions.

### 10.5.3 The lifter generator — where AI *does* work

At the **opcode** level the verification problem inverts, because a perfect oracle exists:
run the instruction on reference hardware with randomized register and flag state, run the
generated definition, diff. Fuzz each opcode across edge cases — carry boundaries,
denormals, overflow, alignment faults — and a wrong definition is caught mechanically.

It is also bounded: PowerPC ~400 instructions, ARM64 ~500, MIPS ~200. Each definition is
small and independent.

**Pipeline:** AI drafts opcode semantics from prose ISA manuals → emits **SLEIGH** → a
differential fuzzer validates against reference hardware → output feeds an existing lifter.

**Design rules:**
- **Output SLEIGH, not a new IR.** Inherits Ghidra's entire ecosystem; specs stay
  human-reviewable, which matters when AI drafted them.
- **Build the differential fuzzer first.** It is the actual product. Without it you have an
  AI guessing at opcodes; with it you have a verified spec generator.
- **Validate against an ISA that already has a good spec** (MIPS or ARM) before pointing it
  at one that doesn't. Regenerating a known-correct spec from prose is the proof of method.

**Prior art — check before building:** Sail (ARM, RISC-V, MIPS, CHERI; the ARM model is
generated from ARM's own machine-readable spec), ARM ASL, Ghidra SLEIGH (hundreds of
processors already specified), remill, and Stoke/Strata (synthesized x86-64 semantics
automatically, non-LLM). **For any mainstream ISA a deterministic generator from a formal
spec beats an AI draft** — correct by construction rather than correct-after-testing. x86
is the notable gap: Intel and AMD publish no machine-readable semantics.

**AI's genuine niche:** ISAs with no formal spec (obscure DSPs, custom console chips, old
embedded silicon — a 2,000-page prose PDF and nothing else), undocumented opcodes and chip
errata, and building the differential harness itself.

### 10.5.4 Highest-value target: the Android native bridge

**This is the one on the critical path.** The `android-apps` capability runs Waydroid on
x86-64, but a large fraction of Android apps ship **ARM-only `.so` files**. The two
existing native bridges — Intel libhoudini and Google ndk-translation — are proprietary
binaries in a licensing grey zone, installed via side scripts, and libhoudini is
effectively abandoned.

That is a proprietary blob inside a project whose premise is not depending on proprietary
blobs. A clean ARM→x86-64 path closes a real architectural hole.

**Lucky break:** ARM→x86 is the *easy* direction on memory ordering. Translating to a
stronger model (x86 TSO) avoids the §12.7 problem entirely.

### 10.5.5 Scope the claim honestly

**This is a lifter generator, not a recompiler.** In N64Recomp and XenonRecomp, opcode
lifting is ~10–20% of the work. The rest is the runtime/HLE layer, code discovery and
indirect-jump resolution (still undecidable, still per-title human work), GPU
command-stream translation, and memory model / MMIO / timing behavior.

Architectures with private local stores and explicit DMA resist lifting outright — PS3's
Cell has 6–8 SPEs with no cache coherence, and SPU is most of why RPCS3 took over a decade.
A perfect opcode spec would not have saved them a year.

**Generality is where tooling projects die.** What makes a pipeline uniform is often what
makes it mediocre on every target. ISAs resist uniformity: delay slots (MIPS, SH), ARM32
predication, condition-code side effects, VLIW bundles, SIMD saturation semantics,
endianness, alignment-fault behavior.

### 10.5.6 Other applications

- **Consoles:** PPC (360, GameCube, Wii), MIPS (N64, PS2), SH-4 (Dreamcast)
- **Driver shim (§10 item 3):** device firmware runs on DSPs and microcontrollers with
  poorly documented ISAs and no Ghidra support
- **Stranded industrial and scientific equipment** — working hardware nobody can read the
  firmware of. Squarely in the spirit of tenet 2.

**Apple is not an application.** macOS on Apple Silicon is ARM64 and the Neo board runs it
natively — there is nothing to translate. The blocker is Rule 1: frameworks and
attestation, not instructions.

---

## 10.6 Hidden Windows VM (tier 2)

For Windows software that Wine can't run well — SolidWorks, Adobe CC, MSIX/Store apps —
real Windows runs hidden in a VM and its windows are mirrored into Obscura one by one,
**exactly the Neo pattern applied to Windows.** The dispatcher routes those apps there
automatically (§18).

- **Stack:** QEMU/KVM, libvirt, OVMF, swtpm (TPM 2.0 for Windows 11), virtio-win drivers,
  FreeRDP 3 RemoteApp for seamless per-window display (the WinApps approach), Looking
  Glass when a GPU is passed through.
- **No second CPU is needed.** Windows runs on Obscura's own x86-64 CPU. Only systems with
  hardware identity (Apple) or no viable reimplementation (Switch) need physical silicon.
- **Graphics is the constraint.** 3D apps like SolidWorks need GPU acceleration in the VM:
  either a **second GPU passed through** (desktop), or **SR-IOV GPU sharing** on Intel iGPUs
  (Linux support still maturing — verify before relying on it).
- **It's the third untrusted coprocessor.** No route of its own, licensing endpoints
  allowlisted, every deny logged.
- **Per device:** desktop ✔; laptop limited (no 3D without SR-IOV); pocket computer always
  routes to the desktop via `remote-compute`.

---

## 10.7 Coprocessor interface and external hardware (tier 3)

### 10.7.1 One contract for every hidden system

Every hidden system — physical (Neo, Switch) or virtual (Windows VM) — presents the same
five things to Obscura:

1. **Video out** — per-window streams (Neo, VM) or a full-screen capture (Switch)
2. **Input in** — injected events, or an emulated controller
3. **Network** — routed only through Obscura's allowlist
4. **Power control** — Obscura can sleep, wake, and cut it
5. **Kill switch** — physical disconnect (physical coprocessors)

All coprocessor packs use this one code path. A future physical dock is then a hardware
realization of an interface already proven in software.

### 10.7.2 Capture coprocessors

For consoles with no reimplementation worth depending on — chiefly the **Switch** — a stock
console runs as designed and Obscura shows its output:

- **Video:** HDMI capture device (UVC/V4L2, 1080p60), wrapped as an ordinary window.
  The Switch doesn't apply HDCP to game output when docked.
- **Input:** an RP2040-class board emulating a Pro Controller / HORI pad, fed by Obscura.
  Mouse → stick mapping is lossy (relative vs absolute); mouse → gyro is better where
  supported; a real gamepad passed through avoids it entirely.
- **Latency:** ~1–3 frames (16–50 ms). Fine for most games; noticeable in rhythm/fighting.
- **Keep a genuine dock in the signal path.** The dock's USB-C power negotiation is
  proprietary; third-party docks have bricked consoles.
- **Legal conditions:** no HDCP stripping, no firmware modification. Online automation or
  macros may still violate Nintendo's terms of service.
- **Power:** a Switch board draws ~7–12 W — the pocket computer's entire budget. Desktop
  and laptop only; the pocket computer uses `remote-compute`.

### 10.7.3 Remote play

Stronger than capture where the vendor provides a streaming protocol:
- **PS4/PS5:** chiaki-ng (open-source client for Sony's Remote Play). The only PS5 path today.
- **Xbox One/Series:** Greenlight (xHome/xCloud client). Many Xbox exclusives also ship on
  PC (Play Anywhere) and run under Proton.

Nintendo has no remote-play protocol, which is why the Switch needs capture.

### 10.7.4 Minimize physical boards

Physical boards cost space, power, and money. After virtualizing Windows and streaming
PlayStation/Xbox, **only two physical modules remain: the Neo and the Switch.** The Neo
stays inside portable devices (small, ~1 W); the Switch belongs in a home coprocessor dock
(§24).

---

## 11. Decided / Rejected

### Decided
- One image, capability-gated activation (§4)
- Wine/Proton for Windows; Waydroid for Android; hardware coprocessor for macOS
- `binfmt_misc` for foreign-binary dispatch
- Host compositor owns window placement
- MacBook Neo A18 Pro board, headless, per-window mirroring
- Cellular telephony as an optional capability on every form factor, desktop included
- Modem attached over USB; IMS handled inside modem firmware
- All coprocessors untrusted; default-deny outbound; Obscura as sole route
- ~~NixOS for Stages 0–1~~ → reopened (§5) → **Universal Blue, built with BlueBuild, on the
  Aurora base image (`stable`), for every build including the pocket computer (§5)**
- Build order: desktop → thick laptop → pocket computer
- **Mission statement and three-tier model (§0)**
- **x86-64 on every device; AMD and Intel both supported; one universal image with
  runtime capability detection (§4)**
- **A capability is a systemd target (`obscura-cap-<name>.target`), started by udev and
  stopped by `StopWhenUnneeded`; `obscura-capd` mirrors the declared vocabulary over DBus
  and never detects. Capabilities are hardware only; pack availability (`windows-apps`,
  `android-apps`) is pack readiness from the pack manager (§4, §17.3, PACKS.md §2)**
- **Hidden Windows VM as tier 2 for apps Wine can't run (§10.6)**
- **One coprocessor interface for Neo, Windows VM, and Switch (§10.7)**
- **Switch via capture coprocessor; PlayStation/Xbox via remote play; no Switch emulation**
- **Every implementation is a separate pack; system bundles group them (§17)**
- **Pack system, dispatcher, compatibility database, and per-app overrides are Stage 0
  work, built in pack form from day one (§17–§18)**
- **Pack manifest v1 (task 0.21):**
  - strict TOML; invalid or unexpected means skipped and reported (fail closed)
  - `api_minor` feature level: above the supported level gives *Needs a newer Obscura*,
    not a validation error (§17.4)
  - magic names come from a core signature registry
  - factory packs live in `/usr/share/obscura/packs`; installed packs live in
    `/var/lib/obscura/packs` with an atomic `current` symlink and a `removed` marker
  - user files go in `~/Obscura/firmware/<files_dir>/`, shared per console (§17.1)
- **Readiness (task 0.21):** an absent capability that isn't attachable gives
  *Insufficient hardware*, which wins; *Missing hardware* only when every absent one is
  attachable. `attachable` is a field of each capability declaration, not inferred from
  its detection kind. Two states were added,
  *Needs another pack* and *Couldn't evaluate*, and an error never yields Ready (§17.3).
  Readiness is per user, so it's evaluated in the user's session, and the system pack
  daemon only installs (task 0.22)
- **Static and probed capabilities (task 0.2b, §4):**
  - a **static** capability (`x86-64-v3`) is a target gated by systemd conditions
    (`ConditionCPUFeature=`, spelled as in systemd's CPUID table). A drop-in makes
    `sysinit.target` want each static target, which is explicitly `Before=sysinit.target`;
    `obscura-capd` is `After=` each one, so it never reads a static target before its
    start job ran
  - where udev can't decide presence (`vulkan-1.3`), udev starts a per-device **probe**
    unit (`obscura-cap-<name>-probe@<dev>.service`). The probe runs as `ExecCondition=`,
    is `BindsTo=` its device, and is `Before=` and `Upholds=` its own target. This is the
    only exception, besides the static drop-in, to "nothing pulls in a capability", and it
    is **gated**: only an accepting probe writes `/run/obscura-cap/<name>/<dev>/accepted`
    (its `RuntimeDirectory=`), and the target has `ConditionPathExistsGlob=` on those
    markers. A bare `Upholds=` plus `ExecCondition=` was rejected: Upholds pulls the target
    in like Wants as soon as the probe starts, so `vulkan-1.3` became active in the VM
    before the probe rejected lavapipe (VM pass, 2026-11-23). A rejecting probe never makes
    the target active, absence is never a failed unit, the marker is never a source of
    truth for capd, and unplugging the last qualifying device stops the target without a
    reboot
  - `vulkan-1.3` means **hardware-accelerated** Vulkan 1.3: a device matched to the render
    node through `VK_EXT_physical_device_drm` (no DRM properties, no count), type
    integrated or discrete GPU, its own `apiVersion` ≥ 1.3. CPU (llvmpipe/lavapipe),
    `VIRTUAL_GPU` (VMware SVGA, virtio-gpu/venus) and `OTHER` never count, nor do drivers
    layered over a host API (Venus, Dozen, whatever type they report) or render nodes of
    virtual-GPU kernel drivers (virtio_gpu, vmwgfx, vkms, vgem). The probe fails closed
  - capability names may contain dots; object paths escape every byte outside `[a-z0-9]`
    as `_xx` (`vulkan-1.3` → `vulkan_2d1_2e3`)
- **GUI-first: no normal task requires a terminal (§19)**
- **KDE Plasma as the desktop shell, stripped and themed; no custom wlroots compositor**
- **Typed action API as the single path for changing settings (§20)**
- **Local settings assistant, input only from the Settings text box (§21)**
- **Automations: When / While / If / Do; macros are name-triggered automations (§22)**
- **Static recompilation (deterministic, XenonRecomp-class) for tier-3 consoles (§10.5)**
- **Lifter generator as a research track: AI drafts SLEIGH, differential fuzzer validates.
  Fuzzer built first; output is SLEIGH, not a new IR; method proven on a known-good ISA
  before an undocumented one**

### Rejected, with reasons — do not re-propose
| Rejected | Reason |
|---|---|
| Full-system emulation (QEMU TCG) | 5–20x slowdown, unnecessary on same-ISA |
| Darling for iMessage | Reimplements frameworks; cannot produce device identity |
| iOS app support | FairPlay encryption; DMCA §1201; UIKit unimplemented |
| Hackintosh (Intel) | Tahoe is last Intel release; macOS 27 ASi-only; EOL ~fall 2028 |
| VMware / VirtualBox macOS | No Metal-capable virtual GPU; same EOL |
| Mac mini M4 board in pocket computer | ~110 mm board, 50 mm stack, 4–7 W idle, needs a fan |
| Donor iPhone board | **iOS has no headless mode**; secure boot; activation |
| Windows `.sys` in Linux kernel | See §10 |
| **Host-side IMS/SIP stack** | **Unimplemented across mobile Linux; use modem firmware** |
| **PCIe-attached modem** | **DMA access to host RAM from unauditable firmware** |
| Embedded eUICC + own LPA | GSMA certification unobtainable; use removable eUICC + lpac |
| Anti-cheat circumvention | Adversarial treadmill; incompatible with sandboxing |
| Guest-controlled window placement | Focus fights, stacking violations, click-jacking |
| **AI decompile/recompile of applications** | **No verification oracle; undecidable sub-problems; doesn't move the library boundary; poisons clean-room (§14)** |
| **AI anywhere in the opcode translation path without differential validation** | **Plausible ≠ equivalent. The fuzzer is what makes it sound** |
| **A new IR for the lifter generator** | **SLEIGH inherits Ghidra's ecosystem and stays human-reviewable** |
| ARM for any build | Wine needs translation; console emulators are x86-only |
| Per-host OS composition | Fails the flash-drive test |
| Requiring AMD specifically | Not an OS boundary; deletes the sub-10 W x86 module market |
| Power switch that cuts rails | Filesystem corruption, fuel-gauge desync |
| Switch emulation | Legal exposure (Yuzu ended in a 2024 settlement); capture coprocessor instead |
| Xbox One/Series board as a coprocessor | Large, 100 W+; PC versions + Greenlight cover it |
| Multi-CPU custom motherboard (for now) | Windows needs no second CPU; carrier boards instead, later (§24) |
| Hardcoding any platform into the core | Every implementation is a pack (§17) |
| Pack-to-pack dependencies | Except one level on runtime packs (Wine, Proton) |
| Overrides keyed on file paths | Break on update/move; key on product + publisher (§18) |
| Writing a desktop shell from scratch | Years of work unrelated to the mission; use Plasma |
| Cloud model for the settings assistant | Sends requests off-device; contradicts tenet 2 |
| Assistant running shell commands | Typed action API only (§20) |
| Assistant reading files, web pages, or other input | Input is the Settings text box only (§21) |
| Unattended automations running confirm-tier actions | Only free-tier actions run without the user (§22) |

---

## 12. Open problems

1. **The macOS menu bar.** macOS apps own a single global menu bar that is not part of the
   window; capture the window alone and GarageBand's menus vanish. Options: (a) capture
   the menu bar as a second surface swapping on focus — easy, bolted-on; (b) walk the
   Accessibility tree and rebuild menus natively — correct, much more work. Read how the
   Linux global-menu projects handled it.
2. **Carrier IMS provisioning.** Whether the chosen module's IMEI is accepted for VoLTE on
   the target carrier. Unknowable without testing. **Highest-uncertainty item in the
   telephony subsystem.**
3. **Latency for GarageBand.** Capture → encode → link → decode → composite is 16–50 ms.
   Fine for Messages, fatal for live monitoring while tracking (>~10 ms is noticed).
   Instrument input may need to reach the Neo directly.
4. **TCC bootstrap.** Screen Recording and Accessibility need GUI consent dialogs —
   chicken-and-egg on a headless board. Attach a display for setup; expect to redo after
   macOS updates.
5. **Neo board parts pairing.** The board expects a recognized display, keyboard, trackpad,
   and battery. Unknown which connectors tolerate being empty. Bench work with a donor
   unit; **budget a spare board for the one killed learning.**
6. **Modem power arbitration.** Cellular standby on a device that also sleeps an Apple
   coprocessor — two independent low-power domains that must not wake each other.
7. ~~**Cross-ISA TSO.**~~ **Closed: §11 rejects ARM for every build, so x86 apps never run
   on ARM.** Kept for the record: x86 is TSO, ARM weakly ordered. Naive translation breaks nondeterministically. Apple used a hardware TSO mode;
   FEX/box64 use barriers (slow) or LSE atomics (gaps). Note the reverse direction
   (ARM→x86, §10.5.4) is the easy one — translating *to* a stronger model.
8. **Android native bridge.** ARM-only `.so` files on an x86-64 host currently require
   proprietary blobs (libhoudini, ndk-translation) in a licensing grey zone, one of them
   abandoned. **The only place in the architecture still dependent on an unauditable
   third-party binary.** See §10.5.4.
9. **Whether the lifter generator beats existing formal specs.** For mainstream ISAs,
   Sail/ASL/SLEIGH already exist and are correct by construction. The method must prove
   itself on an undocumented ISA to justify the effort. **Unproven until T-62 passes.**
10. ~~**Base OS choice.**~~ **Closed: Universal Blue Aurora, built with BlueBuild (§5, §11).**
11. **GPU acceleration for the Windows VM.** Second GPU vs SR-IOV. Decides whether
    SolidWorks runs locally on the laptop at all.
12. **Pack API stability.** The pack interface is the contract that must outlive any
    individual emulator. Getting v1 wrong is expensive; built-ins in pack form (§17) are
    how it gets tested before outside packs depend on it.
13. **Settings-assistant model choice.** A 1–2B model with reliable structured tool
    calling. Pick at build time; this space changes every few months.
14. **AMD hardware-error logging.** mcelog runs only on Intel CPUs with `/dev/mcelog`; it
    is skipped in VMs and on AMD (§4). AMD machine-check and EDAC reporting (rasdaemon)
    is a later item. **The skip still needs verifying on the Ryzen desktop:** mcelog
    skipped, not failed, in `systemctl --failed`.

---

## 13. Roadmap

**Stage 0 — Desktop.** Unlimited power and cooling, monitor attachable to the Neo for TCC
prompts, everything on a bench. Solve here: per-window capture, menu bar, virtual camera,
input injection, firewall allowlist, Wine/Waydroid integration, **and first telephony
bring-up — a desktop is the easiest place to debug a modem.** None of it gets easier later.

**Also Stage 0 — the foundations everything else plugs into.** Since the pack model is
decided, build it first rather than retrofitting it:
- **Pack format, pack manager daemon, and CLI** (§17–§18)
- **Dispatcher, compatibility database, and per-app overrides** (§18)
- **Wine, Proton, Waydroid, the Neo, and the Windows VM delivered as packs** from day one
- **The typed action API** (§20) — the GUI, the assistant, and automations all depend on it
- **Plasma shell, Settings app shell, and the pack manager GUI with "Run with"** (§19)

The settings assistant (§21) and automation engine (§22) are **in scope but built later**
(Stage 1.5). They need nothing new from the core except the action API, which is why the
action API has to exist in Stage 0.

**Stage 0.5 — Console emulation and static recompilation.** After the desktop passes its
gates, before the laptop. Low-risk, touches nothing load-bearing, and a good break between
the ScreenCaptureKit agent and the laptop's power engineering. Covers emulator integration,
`binfmt_misc` dispatch for SELF/EBOOT/XEX, XenonRecomp evaluation, and the first phase of
the lifter generator (§10.5.3) — **differential fuzzer first.**

**Stage 1 — Thick laptop.** Adds what the desktop cannot teach: real power budget, thermal
arbitration across two coprocessors, suspend/resume across the link, battery authority,
cellular standby drain. **Instrument the power path from day one.** The likely failure is
a coprocessor that never reliably reaches deep sleep, invisible without measurement.

**Stage 1.5 — Settings assistant and automations.** After the laptop gates, because the
call automations and power automations need the laptop's battery and telephony behavior
to be real. Both are packs built on the Stage 0 action API.

**Stage 2 — Pocket computer.** The only stage where a wrong call is unrecoverable — chassis
and hinge are machined before final firmware thermals are known. Add margin.

**Stage 3 — Hardening (later).** Update delivery for sealed devices, LUKS + TPM unlock,
self-enrolled Secure Boot keys, cross-device state sync (Syncthing), single local DNS
resolver with query logging, the transparency dashboard, and a documented end-of-life plan
for the Neo board.

**Also worth doing:** contribute upstream to Wine's Wayland driver, Waydroid's compositor
integration, or ModemManager's voice handling. Six months there teaches more than five
years from scratch, and provides reviewers who have hit every wall ahead.

---

## 14. Legal hygiene

- **Clean-room discipline.** Do not decompile Windows binaries or read leaked source.
  Wine's discipline is why Wine is distributable. **This explicitly includes AI decompilers
  (REA, LLM4Decompile-class tools).** Running one over a Windows or Apple binary and
  committing the output makes the tree legally untouchable, and it is hard to undo once
  derived code is in. The lifter generator (§10.5) is clean because it reads *public ISA
  manuals*, not somebody's shipped binary.
- macOS EULA restricts macOS to Apple-branded hardware (*Apple v. Psystar*, 2009). Using
  genuine Apple boards keeps this clean; Hackintosh did not.
- Apple frameworks and Google GApps are not licensable for redistribution.
- Cellular: pre-certified modules only; **never modify IMEI**.

### 14.1 Non-commercial does not mean safe

The project is open source and never sold, but that removes little legal exposure:
- **DMCA §1201 has no non-commercial exemption.** Circumventing DRM, or distributing tools
  that do, is unlawful whether or not money changes hands.
- **Copyright infringement doesn't require profit.**
- **Open source increases exposure**, because most risk comes from distribution, and a
  public repo is distribution to everyone.

Yuzu — an open-source Switch emulator — ended in a $2.4M settlement in 2024, centered on
its reliance on Switch encryption keys.

### 14.2 The four rules that keep the repo distributable

1. **Never put keys, platform firmware, BIOS files, OS images, or decryption code in the
   repo or in any pack.** Packs declare them by name and checksum; the user supplies them.
   *Platform firmware* means console and system firmware, BIOS files, and keys. *Hardware
   firmware* (`linux-firmware` blobs) is redistributable and ships in the image through
   Fedora packages (§4) — but it, too, is never committed to the repo.
2. **Never commit decompiled vendor code**, including AI-decompiled output.
3. **Per-title recompilation packs ship the recompiler and runtime only.** The game file
   comes from the user (the N64Recomp model).
4. **Coprocessor and capture packs use stock hardware, as designed.** Genuine Apple
   hardware for the Neo; no HDCP stripping or firmware modification for consoles.

---

## 15. Facts with expiry dates

Re-check before relying on these:

- macOS 26 Tahoe = last Intel release. macOS 27 "Golden Gate" (WWDC June 2026, ships
  ~Oct 2026) = Apple Silicon only. Intel security updates end ~fall 2028.
- Rosetta 2 removed on macOS 27 install (reinstallable); fully gone in macOS 28.
- MacBook Neo: A18 Pro, $599, ~1.23 kg, MediaTek Wi-Fi, iFixit repairability 6.
- ModemManager 1.24: simtech plugin gained A760x support and USB audio fixes. **Check the
  current release for VoLTE/IMS progress — this area is moving.**
- US 3G/CS voice shutdown complete (AT&T Feb 2022, Verizon Dec 2022, T-Mobile 2022–24).
  No CS fallback exists.
- lpac + removable eUICC is the current open eSIM path. Verify card keys still permit
  third-party LPAs before buying.
- EU Digital Markets Act interoperability mandates are forcing Apple to open AirDrop,
  AirPlay, and notification access. **The one wall that gets lower over time** — recheck
  when planning phone-side integration.
- AI decompilation tooling (REA "Reverse Engineer Anything", LLM4Decompile, Ghidra LLM
  plugins) is moving fast, and the decomp community is already skeptical about a flood of
  half-correct output. Current honest consensus: **AI works on decompiler output —
  naming, commenting, hypothesis generation — with human verification, not as an automatic
  translator.** Recheck before assuming the verification problem has been solved.
- N64Recomp and XenonRecomp are the reference static-recompilation projects. Check for
  newer targets before writing a lifter by hand.

---

## 16. Interoperability fallbacks

Mature and clean-room, if the coprocessor is unavailable:

- **libimobiledevice** — full USB/lockdownd stack; backups, file transfer, app management
- **OpenDrop / OWL** — AirDrop and AWDL reimplementation
- **BlueBubbles / OpenBubbles** — iMessage bridging via a relay Mac
- **KDE Connect** — cross-platform notification/clipboard/file sync

These also become the **Neo end-of-life plan**: when Apple drops A18 Pro support, the
coprocessor goes security-updates-only and then stops. That date should be tracked, with
these fallbacks (and whatever the EU DMA has opened by then) ready.

---

## 17. Platform packs

### 17.1 What a pack is

A **pack** is one installable implementation that runs one platform's software. Wine is a
pack; the hidden Windows VM is a different pack for the same platform. The full planned
catalog, with dependencies, is in **PACKS.md**.

Every pack declares:

| Field | Meaning |
|---|---|
| **Platform** | Which system's software it serves |
| **Handles** | Binary signatures, installer formats, file extensions — what the dispatcher routes to it |
| **Technique** | Reimplementation, container, emulation, static recompilation, hidden OS, coprocessor, remote |
| **Requires** | Capabilities the device must report (§4; vocabulary in PACKS.md §2) |
| **User supplies** | Firmware, BIOS, keys — by name and checksum, **never bundled** |
| **Actions and triggers** | What it adds to the action API (§20) and automation engine (§22) |
| **API version** | The pack-interface version it was written against |

```toml
[pack]
name      = "pack-macos-neo"
api       = 1
version   = "1.0"
platform  = "macos"
technique = "coprocessor"
summary   = "Runs Mac apps on the Apple coprocessor, in ordinary Obscura windows."

[handles]
magic      = ["mach-o", "mach-o-fat"]
installers = [".dmg", ".pkg"]

[requires]
capabilities = ["apple-coprocessor", "hw-decode-hevc"]

[fallback]
remote = true   # use a coprocessor on another of your devices if reachable
```

**Manifest v1 (`pack.toml`, `api = 1`, task 0.21).** The manifest is strict TOML: an
unknown table or key is an error, so a typo can't pass silently. A manifest that fails
validation is reported and skipped. It never stops other packs from loading, and it's
never shown as a broken pack. If anything unexpected happens during validation, the
manifest counts as invalid (fail closed). New fields within api 1 come with a new
feature level, `pack.api_minor` (§17.4).

| Table | Keys |
|---|---|
| `[pack]` | `name` (`pack-…`, equals its directory), `api`, `api_minor` (default 0), `version`, `platform`, `technique`, `summary`; optional `status`, `runtime` (true only for runtime packs), `files_dir` |
| `[handles]` | `magic` (names from the core signature registry `/usr/share/obscura/signatures.toml`: packs never define magic bytes), `installers`, `extensions` |
| `[requires]` / `[recommends]` | `capabilities`: PACKS.md §2 names. A missing recommended capability is a note, not a readiness failure |
| `[depends]` | `runtime`: only packs with `runtime = true`; a runtime pack has no `[depends]` |
| `[[user_supplies]]` | `id`, `label`, `kind` (firmware, bios, keys, rom-set, os-image, media), `file` (a bare file name), `sha256` (a list: required except for os-image and media), `required` |
| `[fallback]` | `remote` |
| `[provides]` | `actions`, `triggers` (names; schemas come from the action API, §20) |
| `[touches]` | `kernel_modules` (needs explicit approval), `devices` (under `/dev/`) |

**User-supplied files** go in `~/Obscura/firmware/<files_dir>/`. `files_dir` defaults to
the pack name without `pack-`. **Packs for the same console share `files_dir`, named after
the console** (`ps1`, `ps2`, `ps3`, `gc`, `n64`, …). For example, `pack-duckstation` and
`pack-mednafen` both use `ps1`, so the user places a BIOS once.

**On disk:** packs shipped in the image (the *factory* copy) live in
`/usr/share/obscura/packs/<name>/`. They're read-only and update and roll back with the
image. Packs the manager installs live in `/var/lib/obscura/packs/<name>/<version>/`, with
a `current` symlink swapped atomically. An installed `current` takes precedence over the
factory copy. A `removed` marker in `/var/lib/obscura/packs/<name>/` hides a factory pack
(like `systemctl mask`). A broken `current` falls back to the factory copy and is reported.

### 17.2 System bundles

A **system bundle** (a "megapackage") is a named list of packs for one system. It contains
no software of its own.

```toml
[bundle]
name    = "windows"
version = "2026.10"

[packs]
default  = ["pack-wine", "pack-proton"]
optional = ["pack-windows-vm", "pack-dosbox", "pack-86box"]
```

Optional packs are offered separately because they need something from the user (a
Windows ISO, a ROM set). Bundles as lists mean no duplication (Wine is installed once even
though several bundles use it), independent updates, and single-pack removal.

### 17.3 Readiness

Each device evaluates every installed pack against its own capabilities and reports one of:

| State | Example |
|---|---|
| **Ready** | Runs locally |
| **Remote** | "No Apple coprocessor here; running on your desktop's Neo" |
| **Missing hardware** | "macOS apps need an Apple coprocessor. None detected or reachable." |
| **Missing files** | "PS6 pack needs system firmware you supply. Place it in ~/Obscura/firmware/ps6." |
| **Insufficient hardware** | "Needs a dGPU with Vulkan 1.4. This device has an iGPU." |
| **Needs another pack** | "Steam VR games need the Proton pack. Install it?" |
| **Couldn't evaluate** | "Obscura couldn't check this pack. Copy diagnostics." Never treated as ready |
| **Needs a newer Obscura** | "This pack needs a newer version of Obscura. Update?" (its `api_minor` is higher than this Obscura supports) |

**How the state is chosen.** Every reason is collected, so the user sees every fix at
once. The state is then picked in this order:
1. **Hardware.** A required capability is absent, or the pack is marked "not on this
   device". If `fallback.remote` is set and a peer can run the pack, the state is
   **Remote**. Otherwise it's **Insufficient hardware** if any absent capability isn't
   attachable, or can't be detected by this Obscura, because telling the user to connect
   something wouldn't fix it. Only when every absent capability is attachable is it
   **Missing hardware**. Each capability declaration says `attachable = true/false`
   (PACKS.md §2), independently of how it's detected (`kind`): a discrete GPU is detected
   by udev but isn't attachable. "Not on this device" counts as not attachable.
2. **Runtime.** The runtime pack isn't installed: **Needs another pack**. It's installed
   but not ready: the dependent pack takes the runtime's state.
3. **Files.** A required user file is absent or matches no listed checksum: **Missing
   files**.
4. Otherwise **Ready**.

An unexpected error anywhere in evaluation gives **Couldn't evaluate**, never Ready, and
the error is reported. Readiness is per user, because the files are in `~`.

Installed packs sync across devices; each device judges its own readiness. A pack can be
marked "not on this device" (e.g. no Windows VM on the pocket computer). It then isn't
run locally. If the pack allows remote use (`fallback.remote`) and a peer can run it,
it shows as **Remote** ("runs on your desktop"). Otherwise it shows **Insufficient
hardware** with "Set not to run on this device" and a button to allow it here.

### 17.4 Rules

- **Every implementation is a pack, including the built-ins.** If Wine, Waydroid, and the
  Neo use the same format as a future PS6 pack, the format is tested by real use.
- **The image may ship packs preinstalled, but they remain real packs** — each with a
  manifest, and the pack manager can update or remove them like any other. The core holds
  only kernel-level support (binder/binderfs, KVM, and `binfmt_misc`), plus the signature
  registry (`/usr/share/obscura/signatures.toml`): the magic bytes that packs refer to
  by name, so no pack defines its own `binfmt_misc` handler (§17.1).
- **The pack API is the stable contract.** Versioned from day one (`api = 1`). It must
  outlive any individual emulator.
- **`api` is the major version; `api_minor` is the feature level within it.**
  - `api_minor` is an integer and defaults to 0. Each Obscura release defines the highest
    `api_minor` it supports. New optional manifest fields raise that level.
  - A manifest **at or below** the supported level is validated strictly: an unknown key
    is still an error, so typos are caught.
  - A manifest **above** the supported level isn't rejected for keys it doesn't know,
    because they may be the newer features. Only its `[pack]` identity is checked, and
    nothing else in it is used. It's listed with **Needs a newer Obscura** and an
    "update Obscura" fix, and never routed to. That matters because installed packs sync
    to devices that may run an older Obscura.
  - A higher `api` (major) is an invalid manifest that says it needs a newer Obscura.
- **Packs depend on core services, not on each other** — except one level deep on runtime
  packs (`pack-wine`, `pack-proton`).
  **Only factory packs (shipped in the image) may declare `runtime = true`** for now, so an
  installed pack can't make itself a dependency target. An installed runtime pack is
  rejected and the factory copy is used. Signed repository packs become eligible in
  task 0.23.
- **Packs are signed, run in userspace wherever possible, and declare what they touch.**
  A pack needing a kernel module requires explicit approval.
- **Packs never bundle copyrighted firmware, keys, or OS images** (§14.2).

**Prior art:** libretro's core info files (supported extensions, required BIOS with
checksums, a clear "missing file" report). Read it before designing the manifest.

---

## 18. Pack manager and dispatcher

### 18.1 The pack manager

One **daemon** owns installs, updates, readiness, pins, and overrides, and exposes them
over DBus. Three front ends talk to it:
- **The GUI** — the product (§19)
- **The right-click "Run with" menu** — a standard `.desktop` action first, so it works in
  existing file managers
- **A CLI** — for development and testing; never required of users

```
Windows                                    bundle 2026.10
  ✔ Wine              10.4      ready
  ✔ Proton            10.0-3    ready
  ✔ Windows VM        1.2       ready
  ⚠ 86Box             5.1       needs ROM set → ~/Obscura/firmware/86box

Sony                                       bundle 2026.10
  ✔ RPCS3             0.0.38    ready   📌 pinned
  → shadPS4           0.17      runs on desktop (no dGPU here)
```

Actions: install a bundle, add/remove a pack, update all, update one, **pin a version**
(emulators fix one game and break another), roll back.

**Repository:** start with a signed index plus pack archives on GitHub Releases. Third-party
repositories require explicit trust.

### 18.2 The dispatcher

When a file is opened, the dispatcher identifies its platform (`binfmt_misc` signatures,
installer type) and picks a pack. **Order of precedence:**

1. **"Run with" for this launch only**
2. **The user's saved override** for this app
3. **The compatibility database** entry for this app
4. **The bundle's default order** (e.g. Wine → Windows VM → remote)

**Only installed and ready packs take part.** Every level of the order is filtered to
packs that are installed and report Ready (or Remote) on this device (§17.3); an entry
naming a pack that isn't installed is skipped.

The user's choices always win; the compatibility database is a recommendation, never a
lock. If the chosen pack fails or isn't ready on this device, the dispatcher falls back to
the next installed, ready option and says why. When the next pack in the bundle's order
isn't installed, the readiness message offers to install it (e.g. "Wine couldn't run this.
Install the Windows VM pack?") rather than choosing it silently. `pack-windows-vm` stays an
optional pack (§17.2); nothing installs it without the user agreeing.

### 18.3 "Run with" and overrides

```
Run with ▸  ● Default (Wine)
            ○ Wine
            ○ Proton
            ○ Windows VM
            ○ Remote → Desktop
            ──────────────
            ☐ Always use this for SolidWorks
```

**Overrides key on the app's identity, not its path.** Windows executables carry product
name and publisher in their metadata; Mac apps carry a bundle ID. Keying on those means an
override survives updates and reinstalls:

```toml
[[override]]
match = { platform = "windows", product = "SOLIDWORKS", publisher = "Dassault Systemes" }
pack  = "pack-windows-vm"
```

### 18.4 The compatibility database

Per application: which pack works, how well, and with what tweaks — the ProtonDB idea
generalized to every platform. It's what lets the dispatcher route SolidWorks to the VM,
Notepad++ to Wine, and Bloodborne to shadPS4 on the desktop but `remote-compute` on the
pocket computer, without the user deciding each time. Stored locally; synced across your
devices.

### 18.5 Installers

`.msi`, `.msix`, `.dmg`, `.pkg`, `.apk`, and `.xapk` route on double-click like executables.
MSIX and Store packages go to the Windows VM by default.

---

## 19. User experience: GUI-first

### 19.1 The rule

> **If a normal task requires a terminal, that's a bug.** The terminal stays available
> for anyone who wants it, but nothing ever sends a user there.

| Task | Typical Linux today | Obscura |
|---|---|---|
| Install software | Package-manager commands | Double-click an installer, or the pack manager / app catalog |
| Run a foreign app | Wine prefixes, launch scripts | Double-click; right-click → "Run with" |
| Update | Terminal command | One updater for OS and packs; never forces a restart mid-work |
| Undo a bad update | Boot menu + terminal | "Undo last update" button, also offered at boot |
| Hardware | `lsusb`, `dmesg` | Devices panel: what's detected, which capabilities are active |
| Diagnose | `journalctl` | Plain-language error with a fix button; "Copy diagnostics" for depth |
| Firewall / privacy | nftables rules | Transparency dashboard |
| Recovery | Single-user shell | Graphical recovery mode |

### 19.2 "Like Windows, without the bloat"

- **One settings app**, every setting in one searchable place. No Settings/Control Panel split.
- **No ads, suggestions, recommended tiles, or account nags.** No telemetry, so no
  telemetry toggles.
- **Errors explain themselves and offer the fix** — the readiness-message pattern everywhere.
- **Familiar layout:** taskbar, start menu, file explorer, right-click menus,
  Windows-style shortcuts. A touch mode of the same shell on the pocket computer.

### 19.3 Built on KDE Plasma

Plasma is the most Windows-like Linux desktop, fully Wayland, with one System Settings app
and deep customization. **Strip and theme it; write the Obscura-specific parts as Qt apps
and Settings modules:** the pack manager, "Run with," the devices panel, the transparency
dashboard, the settings assistant, and automations.

Mirrored windows from the Neo and the Windows VM are ordinary Wayland clients, and KWin
draws their decorations, so every foreign window looks native. This replaces the custom
wlroots compositor from earlier versions.

---

## 20. The action API

The single, typed path for reading and changing system state. **The GUI, the settings
assistant, and automations all use it.** Nothing changes a setting any other way.

```toml
[action.set_volume]
params     = { level = "percent 0–100", relative = "bool" }
reads      = "get_volume"
reversible = true
tier       = "free"
```

Every action has a schema, limits, a matching read action, an undo, and a **safety tier**:

| Tier | Examples | Behavior |
|---|---|---|
| **Free** | Volume, brightness, color temperature, theme, power profile, audio routing, opening apps | Runs; offers undo |
| **Confirm** | Installing/removing packs, network changes, deleting files | Shows what it will do; user approves |
| **Show only** | Weakening the firewall, kill switches, security settings | Opens the setting; never changes it programmatically |

**Packs add their own actions** (and triggers, §22). Installing the Windows bundle adds
"run in VM" and "update Wine." Every action execution is logged and appears in the
transparency dashboard.

Implemented as DBus services. It is **Stage 0 work** because everything above it depends on it.

---

## 21. Settings assistant

A small local model in the Settings app that knows every capability of the OS and helps
the user change settings and write automations by typing.

### 21.1 Scope (hard boundaries)

> **The settings assistant runs locally, takes input only from the Settings text box,
> reads and changes the system only through the typed action API, and acts only within its
> safety tiers.**

- **Local only.** A cloud model would send requests off-device (tenet 2).
- **No other input.** No files, web pages, notifications, or messages. This removes the
  prompt-injection surface entirely: only the user, typing, can tell it to act.
- **Reads state through the action API** (`get_volume`, etc.) — system values, not outside input.
- **No shell.** It fills in typed action calls, enforced with constrained decoding.

### 21.2 What it does

- **Adjusts settings conversationally:**
  ```
  You:    lower the volume a bit
  Assist: Volume 60% → 50%.  ▶ test tone
          [Quieter]  [Good]  [Louder]
  ```
  "A bit" maps to a defined step; follow-up buttons narrow it without more typing.
- **Takes you to the setting** — opens the exact page with the control highlighted. When
  unsure, offers the two or three likeliest pages instead of guessing.
- **Authors automations and macros** (§22), shown as editable steps before saving.

### 21.3 How it knows the OS

No training on Obscura. A **capability manifest is generated automatically** from the
action schemas and installed packs, and retrieved at question time. It never goes stale:
install a pack and the assistant immediately knows its actions.

### 21.4 Model and hardware

- A **1–2B** instruct model with reliable tool calling, 4-bit quantized, under llama.cpp
  (Vulkan backend). Runs on the N100 iGPU.
- **Loaded on demand, unloaded after** — no idle cost on the pocket computer.
- **Fast path:** common commands ("volume down," "night mode") are matched by a
  deterministic parser before the model loads, so they respond instantly.
- Shipped as `pack-settings-assistant`. Optional.

---

## 22. Automations

### 22.1 Model

**When / While / If / Do.** A macro is just an automation whose only trigger is its name —
one system, one format, one page in Settings.

- **When** — a trigger fires once (a time, an event)
- **While** — a state holds; **everything reverts automatically when it ends**
- **If** — optional conditions
- **Do** — actions from the action API (§20)

```toml
[automation."Docked at desk"]
when = [{ event = "display_connected", match = "Dell U2723QE" }]
if   = [{ condition = "power_source", is = "ac" }]
do   = [
  { action = "set_power_profile", profile = "performance" },
  { action = "set_audio_output", device = "desk speakers" },
]

[automation."On a call"]
while = [{ state = "call_active" }]          # or "microphone_in_use" for any platform
do = [
  { action = "pause_media" },
  { action = "set_audio_output", device = "headset", fallback = "speakers" },
  { action = "set_mic_gain", percent = 70 },
  { action = "enable_noise_suppression" },
  { action = "enable_echo_cancellation", if_output = "speakers" },
  { action = "set_notifications", mode = "silent" },
]

[macro."Night Mode"]
trigger = ["name", "schedule:sunset"]
steps = [
  { action = "set_color_temperature", kelvin = 3400 },
  { action = "set_brightness", display = "internal", percent = 40 },
  { action = "set_brightness", display = "external", percent = 35 },  # DDC/CI
  { action = "set_theme", mode = "dark" },
]
```

The Settings page shows a When / While / If / Do builder with dropdowns. The settings
assistant can draft one from text (*"when I plug in my headphones, set volume to 30%"*);
the user reviews and saves. **Once saved, automations run without the assistant.**

### 22.2 Triggers

| Kind | Examples |
|---|---|
| **Time** | Specific time, days, intervals; sunrise/sunset from a location set in Settings (no network geolocation) |
| **Hardware** | Device plugged in/removed (headphones, monitor, dock, controller, drive); Bluetooth connect; AC vs battery; battery below X%; lid; ambient light; Neo connected |
| **System** | Login, idle, wake; Wi-Fi network joined/lost; **any app launched or closed, including foreign apps** (via the dispatcher) |
| **Telephony** (from the telephony pack) | `call_incoming` (with caller for conditions), `call_answered`, `call_ended`, `sms_received` |
| **Audio** | `microphone_in_use` — PipeWire sees any app open the mic, so it catches calls on **every** platform: cellular, FaceTime on the Neo, Teams in the VM, Discord under Wine |
| **Network messages** (optional) | Local MQTT or webhook, so other systems on your network can fire automations |
| **Pack-provided** | Packs add their own: "console turned on," "update available," etc. |

### 22.3 Rules

- **Unattended automations run only free-tier actions.** Confirm-tier actions need the
  user present; show-only actions can never be automated. This matters most for
  network-message triggers, the one input from outside the machine.
- **Conflicts resolve by priority**, logged. Each automation has a cooldown so a flickering
  cable can't fire it repeatedly.
- **"Pause all automations"** switch at the top of the page.
- **Every run is logged** — what fired, why, what changed — with undo, in the transparency
  dashboard.
- **Capability rules apply.** Automations sync; a "lid closed" trigger on the desktop shows
  as *not available on this device* rather than failing silently.
- **Caller information stays on the device** and is used only for conditions the user sets.

### 22.4 Implementation

One automation engine service listening to UPower, NetworkManager, BlueZ, udev, KWin,
PipeWire, ModemManager, and the dispatcher, with its own scheduler. Automations are
declarative files, synced like everything else. Shipped as `pack-automations`;
independent of the assistant.

### 22.5 Shipped defaults (all off until enabled)

| Automation | Trigger | Does |
|---|---|---|
| Night Mode | Sunset | Warm color, dim, dark theme |
| Docked | Monitor connected + on AC | Performance profile, desk audio, scaling |
| Low battery | Battery < 15% | Battery saver, dim, sleep the Neo |
| On a call | While call active / mic in use | Pause media, route audio, noise suppression, silence notifications |
| Focus | Chosen app launched | Silence notifications |
| Headphones | Headphones connected | Set volume, switch output |

---

## 23. Coverage roadmap

What the mission still needs beyond Stage 0, in priority order:

| Priority | Item | Why |
|---|---|---|
| 1 | Dispatcher + compatibility database | Turns the parts into one system *(Stage 0)* |
| 2 | Hidden Windows VM pack | The project's own example apps need it *(Stage 0)* |
| 3 | Installer routing | Users double-click installers more than executables |
| 4 | Intel-only Mac apps via `pack-darling` | Time-sensitive: Rosetta 2 is removed in macOS 28 |
| 5 | Device routing (USB/IP) | Unblocks dongle- and peripheral-locked software |
| 6 | Library bridging (winelib, RPC to VM/Neo) | Original goal: use other platforms' libraries in your own code |
| 7 | Cross-environment drag and drop | Next thing users try after shared clipboard and files |
| 8 | Legacy platforms, Flash, VR | Breadth; mostly mature software already |

Items 5 and below wait until the desktop works. Breadth before the core is solid is how
projects like this stall.

---

## 24. Long-term direction (later)

### 24.1 Software expandability — done by design

New platforms arrive as packs. A future PS6 pack is downloaded, installed, checked for
readiness, and run; nothing in the OS changes. This is why the pack API (§17.4) is the
contract to protect.

### 24.2 Hardware expandability — later

- **Home coprocessor dock.** A box at home holding physical modules (the Switch, future
  ones). Desktop and laptop connect directly; the pocket computer reaches it through
  `remote-compute`. Portable devices then carry only the Neo.
- **Carrier boards, not motherboards.** If integrated hardware is built, design carriers
  hosting existing modules (COM-HPC, SMARC, the Mu's SO-DIMM) with a PCIe switch between
  them. A true multi-SoC motherboard (high-speed PCIe, DDR routing, multi-rail power) is
  team-scale work. The Mu's open KiCad carrier files are the place to learn.
- **The coprocessor interface (§10.7.1) is the hardware contract.** A pack's
  `requires = ["apple-coprocessor"]` already points at it, so packs and hardware modules
  speak the same language when this arrives.
