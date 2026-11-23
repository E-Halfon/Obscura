# Camera Obscura Systems: Pack Catalog

**Version:** 1.1
**Date:** 2026-10-15
**Companion documents:** ARCHITECTURE.md v3.0 (§17–§22 define packs, the dispatcher, the
action API, the settings assistant, and automations), CAMERA-OBSCURA-BUILD-BRIEF.md v5.0

**Changes from 1.0:** added system bundles (§1.4), Stage 0 pack list (§1.5), and
`pack-telephony`, `pack-automations`, `pack-settings-assistant` (§14).

This is the catalog of every planned **platform pack**: the installable units that let
Obscura run software from other systems. Each pack is one *implementation*. A platform can
have several packs (Windows has Wine and a hidden VM), and the dispatcher picks the best
installed, ready pack for each program.

iOS is out of scope. iPhone and iPad apps that Apple allows on Apple Silicon Macs are
covered by `pack-macos-neo`.

> **Everything here is a planning estimate.** Versions, requirements, and project status
> change fast. Treat each row as "verify before building."

---

## 1. How to read this document

### 1.1 Pack manifest fields

Every pack declares:

| Field | Meaning |
|---|---|
| **Platform** | Which system's software it runs |
| **Technique** | Reimplementation, containerization, emulation, static recompilation, hidden OS, coprocessor, or remote |
| **Software** | What the pack ships or installs |
| **Requires** | Capabilities the device must report (see §2) |
| **User supplies** | Files the user must provide. **Packs never bundle firmware, BIOS, ROMs, or keys** |
| **Status** | Mature, Usable, Experimental, or Planned |

These are the catalog's columns. The full manifest format (`pack.toml`, `api = 1`) is in
ARCHITECTURE.md §17.1. User-supplied files go in `~/Obscura/firmware/<files_dir>/`. Packs
for the same console share `files_dir`, named after the console (`ps1`, `ps2`, …), so a
BIOS is placed once.

### 1.2 Device columns

| Symbol | Meaning |
|---|---|
| ✔ | Runs locally |
| ~ | Runs locally with limits (lower resolution, some titles only, throttled) |
| → | Routes to `remote-compute` on another of your devices |
| ✘ | Not supported |

**D** = Desktop (Ryzen 8700G/9600X + dGPU), **L** = Laptop (Framework 13 AMD),
**P** = Pocket computer (LattePanda Mu N100/N150, 6–9 W total).

### 1.3 Dependency rules

- Packs depend on **core services**, not on each other.
- **The one exception is runtime packs.** `pack-wine` and `pack-proton` are runtimes, and
  other packs may depend on them, one level deep only. Example: Windows VR titles need
  `pack-steamvr` plus `pack-proton`.
- A missing requirement produces a **readiness message**, never a silent failure.

### 1.4 System bundles

Packs are grouped into **system bundles** ("megapackages"). A bundle is a list of packs,
not a container, so shared packs install once and every pack still updates and uninstalls
on its own. Optional packs need something from the user and are offered separately.

| Bundle | Default packs | Optional packs |
|---|---|---|
| `windows` | `pack-wine`, `pack-proton` | `pack-windows-vm`, `pack-dosbox`, `pack-86box` |
| `macos` | `pack-macos-neo` | `pack-darling`, `pack-classicmac` |
| `android` | `pack-waydroid` | `pack-android-armbridge-interim` |
| `linux-foreign` | `pack-qemu-user` | — |
| `sony` | `pack-duckstation`, `pack-pcsx2`, `pack-ppsspp`, `pack-chiaki` | `pack-rpcs3`, `pack-shadps4`, `pack-vita3k` |
| `nintendo` | `pack-mesen`, `pack-melonds`, `pack-dolphin` | `pack-mgba`, `pack-ares`, `pack-azahar`, `pack-cemu`, `pack-switch-capture`, `pack-n64recomp-*` |
| `xbox` | `pack-greenlight` | `pack-xemu`, `pack-xenia`, `pack-xenonrecomp-*` |
| `retro` | `pack-blastem`, `pack-fbneo`, `pack-vice`, `pack-hatari` | `pack-mednafen`, `pack-flycast`, `pack-mame`, `pack-amiga`, `pack-openmsx`, `pack-ruffle` |
| `vr` | `pack-openxr-monado` | `pack-steamvr`, `pack-alvr` |
| `system` | `pack-remote-compute` | `pack-telephony`, `pack-automations`, `pack-settings-assistant`, `pack-driver-shim`, `pack-device-routing`, `pack-library-bridge` |

In the pack manager, right-clicking an executable lists every installed pack in its
platform's bundle under **"Run with"**, with an "always use this for <app>" option.

### 1.5 Stage 0 packs

Because the pack model is decided, these are **built as packs from day one**, not
retrofitted:

| Pack | Build-brief task |
|---|---|
| `pack-wine` | 0.4 |
| `pack-waydroid` | 0.6 |
| `pack-macos-neo` | 0.28 |
| `pack-windows-vm` | 0.29–0.30 |
| `pack-telephony` | 0.31 |

Everything else in this catalog comes later: consoles in Stage 0.5, `pack-automations` and
`pack-settings-assistant` in Stage 1.5, the rest per the coverage roadmap
(ARCHITECTURE.md §23).

---

## 2. Capability vocabulary

Packs list requirements using these names. This is the **one** capability vocabulary;
ARCHITECTURE.md §4 and the build brief's capability matrix refer to it. The capability
service (`obscura-capd`, §3) reports each name per device as present or absent.

Capabilities are **hardware facts only**. Whether a platform is usable (`windows-apps`,
`android-apps`) is pack readiness, reported by the pack manager (ARCHITECTURE.md §17.3),
not by the capability service.

**Kind** says how the capability is detected: **static** (a fixed fact checked at boot),
**device** (udev; appears and disappears with hotplug), **probe** (a peer answers over a
link). The first three implemented are `virt`, `battery`, and `camera` (build-brief task 0.2).

| Capability | Kind | Meaning | D | L | P |
|---|---|---|---|---|---|
| `x86-64-v3` | static | AVX2, BMI2, FMA | ✔ | ✔ | ✔ |
| `avx512` | static | AVX-512 (helps RPCS3) | ✔ Zen 4/5 | ✔ Zen 4 | ✘ |
| `vulkan-1.3` | static | Vulkan 1.3 via Mesa (RADV/ANV) | ✔ | ✔ | ✔ |
| `dgpu` | device | Discrete GPU | ✔ | ✘ | ✘ |
| `virt` | device | AMD-V / VT-x, usable by KVM (`/dev/kvm` exists) | ✔ | ✔ | ✔ |
| `iommu` | static | AMD-Vi / VT-d with usable groups | ✔ | ✔ | ✔ |
| `gpu-passthrough` | static | Second GPU for a VM, or SR-IOV iGPU | ✔ | ~ | ✘ |
| `hw-encode` | static | Hardware video encode (VA-API) | ✔ | ✔ | ✔ |
| `hw-decode-hevc` | static | Hardware HEVC decode | ✔ | ✔ | ✔ |
| `apple-coprocessor` | probe | Neo board reachable over the coprocessor link | opt | opt | opt |
| `capture-device` | device | UVC/V4L2 HDMI capture at 1080p60 | opt | opt | ✘ |
| `controller-emulator` | device | RP2040-class board emulating a console pad | opt | opt | ✘ |
| `xr-headset` | device | VR headset supported by the OpenXR runtime | opt | opt | ✘ |
| `ram-16g` / `ram-32g` | static | Memory threshold | ✔ | ✔ | ~ |
| `network-lan` | probe | Local network to a peer device or console | ✔ | ✔ | ✔ |
| `battery` | device | System battery (`power_supply`, type Battery, not a peripheral's) | ✘ | ✔ | ✔ |
| `camera` | device | V4L2 video capture node (UVC or CSI) | ✔ | ✔ | ✔ |
| `touch` | device | Touchscreen | opt | opt | ✔ |
| `telephony` | device | USB-attached cellular modem with voice (IMS in modem firmware) | opt | ✔ | ✔ |
| `gps` | device | Location fix from the modem or a GNSS receiver | opt | ✔ | ✔ |

---

## 3. Core (not packs)

The core ships in every image and is what packs build on.

| Component | Software | Notes |
|---|---|---|
| Kernel | Linux mainline, `MODULES=most`, binder/binderfs, KVM, usbip, v4l2 | One universal image |
| Compositor | KDE Plasma (KWin, Wayland) | Draws decorations for every foreign window |
| Audio | PipeWire | Single clock domain |
| Dispatcher | `binfmt_misc` + routing policy + compatibility database | Picks the pack per program |
| Capability service | udev → systemd → DBus (`obscura-capd`) | Reports §2 per device; hardware only |
| Mirroring service | HEVC window-stream client, one Wayland surface per remote window | Used by coprocessor and VM packs |
| Coprocessor interface | Video out, input in, routed network, power control, kill switch | Shared by Neo, Windows VM, Switch |
| Firewall | nftables default-deny, single DNS resolver, query and deny logging | Every pack is untrusted by default |
| Sandbox | bubblewrap + XDG portals | |
| Pack manager | Signed packs, manifest validation, readiness reports, rollback | DBus daemon with GUI, "Run with", and CLI front ends (ARCHITECTURE.md §18.1) |
| Native Linux | ELF x86-64, Flatpak, AppImage, Nix packages | Linux software needs no pack |
| Language runtimes | OpenJDK, .NET, Python, Node, browser | Cross-platform runtimes run natively |

---

## 4. Windows

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-wine` *(runtime)* | Wine | Reimplementation | Wine (staging), wine-mono, wine-gecko, DXVK, VKD3D-Proton, Wine Wayland driver, component installer (VC++ runtimes, fonts) | `x86-64-v3`, `vulkan-1.3` | Nothing | ✔ | ✔ | ✔ | Mature |
| `pack-proton` *(runtime)* | Proton | Reimplementation | Proton (Valve or GE), umu-launcher, Steam runtime (pressure-vessel), DXVK, VKD3D-Proton, gamescope | `x86-64-v3`, `vulkan-1.3` | Nothing | ✔ | ✔ | ~ | Mature |
| `pack-windows-vm` | Hidden Windows 11 | Hidden OS | QEMU/KVM, libvirt, OVMF, swtpm (TPM 2.0), virtio-win drivers, FreeRDP 3 RemoteApp (WinApps-style), Looking Glass for passthrough | `virt`, `iommu`, `ram-32g`; `gpu-passthrough` for 3D apps | Windows ISO and license | ✔ | ~ | → | Usable |
| `pack-dosbox` | DOSBox-X | Emulation | DOSBox-X | none | DOS software; Win 3.x/9x install media if used | ✔ | ✔ | ✔ | Mature |
| `pack-86box` | 86Box | Full PC emulation | 86Box | `x86-64-v3` | Machine ROM set, OS install media | ✔ | ✔ | ~ | Mature |

**Dispatcher default for Windows:** `pack-wine` → `pack-proton` (games) → `pack-windows-vm` → remote.
SolidWorks, Adobe CC, and MSIX/Store apps should route straight to `pack-windows-vm`.

`pack-windows-vm` notes:
- The VM is an **untrusted coprocessor**. No route of its own, licensing endpoints
  allowlisted, all denies logged.
- 3D-heavy apps need a passed-through GPU. On the desktop that means a second GPU. On
  Intel iGPUs, SR-IOV may work but Linux support is still maturing, so verify first.
- On the pocket computer it always routes to the desktop.

---

## 5. macOS

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-macos-neo` | MacBook Neo board | Coprocessor | **Neo side:** macOS 27+, Obscura agent (ScreenCaptureKit, CGWindowList, AXUIElement, CGEventPost), CMIOExtension virtual camera, AudioServerPlugIn virtual audio, TCC grants. **Obscura side:** mirroring client, firewall allowlist (APNs, `gs.apple.com`, iCloud endpoints), DNS logging | `apple-coprocessor`, `hw-decode-hevc` | Apple ID | ✔ | ✔ | ✔ | Planned (Stage 0) |
| `pack-darling` | Darling | Reimplementation | Darling | `x86-64-v3` | Intel-only Mac apps | ✔ | ✔ | ✔ | Experimental |
| `pack-classicmac` | SheepShaver, Basilisk II, QEMU-PPC | Emulation | SheepShaver (PPC, Mac OS 7.5–9.0.4), Basilisk II (68k), qemu-system-ppc (Mac OS 9.2, early OS X) | none | Mac ROM files, Mac OS install media | ✔ | ✔ | ✔ | Mature |

**Dispatcher default for macOS:** `pack-macos-neo` → `pack-darling` (Intel-only apps).

`pack-macos-neo` notes:
- Hardware: MacBook Neo (A18 Pro) logic board, a link (2.5GbE on desktop, USB 3.2 Gen 2
  internal), power-control GPIO, physical kill switch.
- Covers iMessage, FaceTime, iCloud, GarageBand, the rest of the Mac catalog, and any
  iPhone/iPad apps the developer allows on Apple Silicon Macs.
- `pack-darling` matters once Rosetta 2 is removed (macOS 28). Obscura's x86-64 hardware
  runs Intel Mac code natively. GUI support in Darling is limited, so verify each app.

---

## 6. Android

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-waydroid` | Waydroid | Container | Waydroid, LXC, LineageOS-based image, F-Droid, Aurora Store | `x86-64-v3`, binder in kernel (core) | Nothing | ✔ | ✔ | ✔ | Mature |
| `pack-android-armbridge-interim` | libndk_translation | Translation (proprietary) | ndk-translation installed via waydroid_script | `pack-waydroid` installed | Nothing | ✔ | ✔ | ✔ | Usable, **opt-in** |
| `pack-android-armbridge` | Obscura lifter output | Static recompilation | Output of build-brief task 0.5.8 | `x86-64-v3` | Nothing | ✔ | ✔ | ✔ | Planned |

Notes:
- **Play Integrity fails under Waydroid.** Apps that require it (many banking apps,
  some games) will not run. Accepted.
- **The interim ARM bridge is a proprietary blob.** It is opt-in and flagged in the
  readiness report because it contradicts the no-proprietary-blobs tenet. It is the
  reason the clean `pack-android-armbridge` is the most valuable item on the lifter track.
- `pack-android-armbridge-interim` depends on `pack-waydroid`. That breaks the "no
  pack-to-pack dependencies" rule. Treat it as a temporary add-on, and remove it when the
  clean bridge lands.

---

## 7. Linux (non-native)

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-qemu-user` | QEMU user mode | Binary translation | qemu-user-static registered in `binfmt_misc` | none | Nothing | ✔ | ✔ | ✔ | Mature |

Runs ARM64, ARM32, RISC-V, and PPC Linux binaries. Slow, but complete enough for CLI tools
and most libraries.

---

## 8. Sony

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-duckstation` | PS1 | Emulation | DuckStation | none | PS1 BIOS from own console; games | ✔ | ✔ | ✔ | Mature |
| `pack-pcsx2` | PS2 | Emulation | PCSX2 | `x86-64-v3`, `vulkan-1.3` | PS2 BIOS from own console; games | ✔ | ✔ | ~ | Mature |
| `pack-ppsspp` | PSP | Emulation | PPSSPP | none | Games | ✔ | ✔ | ✔ | Mature |
| `pack-vita3k` | PS Vita | Emulation | Vita3K | `vulkan-1.3` | Vita firmware and font package; games | ✔ | ✔ | ~ | Experimental |
| `pack-rpcs3` | PS3 | Emulation | RPCS3 | `x86-64-v3` (`avx512` helps), 8+ threads, `ram-16g`, `vulkan-1.3`, `dgpu` recommended | PS3 system firmware (`PS3UPDAT.PUP`); games | ✔ | ~ | → | Mature for many titles |
| `pack-shadps4` | PS4 | Reimplementation | shadPS4 | `x86-64-v3`, `vulkan-1.3`, `dgpu` | Firmware modules and games dumped from own console | ✔ | ~ | → | Experimental |
| `pack-chiaki` | PS4/PS5 Remote Play | Remote | chiaki-ng | `network-lan`, `hw-decode-hevc` | Own console on the network; PSN account for registration | ✔ | ✔ | ✔ | Mature |

**PS5:** `pack-chiaki` is the only path today. PS5 is x86-64 like the PS4, so a future
local pack would likely be API reimplementation (shadPS4's category), not recompilation.

---

## 9. Nintendo

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-mesen` | NES, SNES, GB/GBC, GBA, PC Engine, SMS | Emulation | Mesen 2 | none | Games; GBA BIOS optional | ✔ | ✔ | ✔ | Mature |
| `pack-mgba` | GBA | Emulation | mGBA | none | Games; BIOS optional | ✔ | ✔ | ✔ | Mature |
| `pack-ares` | N64 and others | Emulation | ares | `vulkan-1.3` | Games | ✔ | ✔ | ~ | Mature |
| `pack-n64recomp-<title>` | Per-title N64 | Static recompilation | N64Recomp-based native build for that title | none | **Own ROM of that title** | ✔ | ✔ | ✔ | Usable (per title) |
| `pack-melonds` | DS | Emulation | melonDS | none | Games; BIOS/firmware optional (FreeBIOS built in) | ✔ | ✔ | ✔ | Mature |
| `pack-azahar` | 3DS | Emulation | Azahar | `vulkan-1.3` | System files and keys from own 3DS for encrypted titles | ✔ | ✔ | ~ | Usable |
| `pack-dolphin` | GameCube, Wii | Emulation | Dolphin | `vulkan-1.3` | Games | ✔ | ✔ | ~ | Mature |
| `pack-cemu` | Wii U | Emulation | Cemu | `vulkan-1.3`, `dgpu` recommended | Keys and online files from own Wii U; games | ✔ | ~ | → | Mature |
| `pack-switch-capture` | Switch / Switch 2 | Coprocessor (capture) | V4L2 capture-window service, input mapper, RP2040 pad-emulation firmware | `capture-device`, `controller-emulator` | **Own console + official dock** | ✔ | ~ | → | Planned |

**Switch emulation is deliberately excluded.** `pack-switch-capture` uses a stock
console as designed: no HDCP stripping, no firmware modification. Avoid third-party docks
in the signal path (some have bricked consoles).

Per-title recompilation packs (`pack-n64recomp-*`) are the lightest option in the catalog.
Where one exists, it beats emulation on every device, including the pocket computer.

---

## 10. Microsoft Xbox

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-xemu` | Original Xbox | Emulation | xemu | `vulkan-1.3` | MCPX boot ROM, flash BIOS, HDD image from own console; games | ✔ | ✔ | ~ | Usable |
| `pack-xenia` | Xbox 360 | Emulation | Xenia Canary | `x86-64-v3`, `vulkan-1.3`, `dgpu` | Games | ✔ | ~ | → | Experimental on Linux (verify; Wine build as fallback) |
| `pack-xenonrecomp-<title>` | Per-title 360 | Static recompilation | XenonRecomp-based native build for that title | `vulkan-1.3` | **Own game files of that title** | ✔ | ✔ | ~ | Usable (per title) |
| `pack-greenlight` | Xbox One / Series | Remote | Greenlight (xHome / xCloud client) | `network-lan`, `hw-decode-hevc` | Own console for xHome, or Game Pass Ultimate for xCloud; Microsoft account | ✔ | ✔ | ✔ | Usable |

**Xbox One / Series:** many exclusives also ship on PC (Play Anywhere), and those run
under `pack-proton`. Greenlight covers the rest. No local console pack is planned. The
board is large and draws 100 W+, which makes it the worst coprocessor candidate.

---

## 11. Sega, arcade, and retro computers

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-blastem` | Genesis / Mega Drive | Emulation | BlastEm | none | Games | ✔ | ✔ | ✔ | Mature |
| `pack-mednafen` | Saturn, PC Engine, others | Emulation | Mednafen | none | Saturn BIOS; games | ✔ | ✔ | ~ | Mature |
| `pack-flycast` | Dreamcast, Naomi | Emulation | Flycast | `vulkan-1.3` | Games; BIOS optional | ✔ | ✔ | ✔ | Mature |
| `pack-mame` | Arcade | Emulation | MAME | none | ROMs (some freely licensed) | ✔ | ✔ | ~ | Mature |
| `pack-fbneo` | Arcade (lighter) | Emulation | FinalBurn Neo | none | ROMs | ✔ | ✔ | ✔ | Mature |
| `pack-amiga` | Amiga | Emulation | Amiberry or FS-UAE | none | Kickstart ROM (or the free AROS replacement) | ✔ | ✔ | ✔ | Mature |
| `pack-vice` | Commodore 64 and family | Emulation | VICE | none | Software | ✔ | ✔ | ✔ | Mature |
| `pack-hatari` | Atari ST | Emulation | Hatari | none | Software (free EmuTOS included) | ✔ | ✔ | ✔ | Mature |
| `pack-openmsx` | MSX | Emulation | openMSX | none | Software (free C-BIOS included) | ✔ | ✔ | ✔ | Mature |

---

## 12. Other runtimes

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-ruffle` | Flash (SWF) | Reimplementation | Ruffle | none | SWF files | ✔ | ✔ | ✔ | Usable |

Java, .NET, web apps, and PWAs run natively in the core and need no pack.

---

## 13. VR

| Pack | Implementation | Technique | Software | Requires | User supplies | D | L | P | Status |
|---|---|---|---|---|---|---|---|---|---|
| `pack-openxr-monado` | OpenXR runtime | Native | Monado | `xr-headset`, `vulkan-1.3` | Headset | ✔ | ~ | ✘ | Usable |
| `pack-steamvr` | SteamVR | Native + Proton | SteamVR (Linux), depends on `pack-proton` for Windows titles | `xr-headset`, `dgpu` | Headset; Steam account | ✔ | ~ | ✘ | Usable |
| `pack-alvr` | Wireless Quest streaming | Remote | ALVR or WiVRn | `dgpu`, Wi-Fi 6 router, Quest headset | Quest headset | ✔ | ~ | ✘ | Usable |

Standalone Quest apps are Android APKs, but they depend on Quest hardware and Horizon OS
services. They are not a realistic `pack-waydroid` target.

---

## 14. Infrastructure packs

These don't run a platform's software directly, but other packs and the mission rely on them.

| Pack | Purpose | Software | Requires | D | L | P | Status |
|---|---|---|---|---|---|---|---|
| `pack-remote-compute` | Run heavy software on another of your devices | Sunshine (host), Moonlight (client), WireGuard | `hw-encode` on host, `hw-decode-hevc` on client, `network-lan` | host | host/client | client | Mature components |
| `pack-driver-shim` | Run Windows usermode drivers against real devices | Wine usermode driver host, libusb, uhid, uinput, usbmon tooling | `pack-wine` | ✔ | ✔ | ✔ | Planned |
| `pack-device-routing` | Hand a physical device to the environment that needs it | usbip, routing policy daemon | `virt` for VM targets | ✔ | ✔ | ~ | Planned |
| `pack-library-bridge` | Use other platforms' libraries from Obscura code | winelib; RPC bridge to the VM and Neo | `pack-wine`; VM or Neo for their libraries | ✔ | ✔ | ~ | Planned |
| `pack-telephony` | Calls, SMS, cellular data; publishes `call_incoming`, `call_answered`, `call_ended`, `sms_received` | ModemManager, voice audio bridge (`q6voiced`-style), dialer/SMS UI, lpac for eSIM | `telephony` capability (USB-attached modem with IMS in firmware) | opt | ✔ | ✔ | Planned (Stage 0) |
| `pack-automations` | When / While / If / Do automations and macros | Automation engine service, Settings builder page, run log | Action API (core) | ✔ | ✔ | ✔ | Planned (Stage 1.5) |
| `pack-settings-assistant` | Local settings assistant in the Settings text box | llama.cpp (Vulkan), 1–2B tool-calling model, capability-manifest generator, fast-path parser | Action API (core), `vulkan-1.3`, ~2 GB RAM while loaded | ✔ | ✔ | ✔ | Planned (Stage 1.5) |

`pack-automations` and `pack-settings-assistant` are independent: automations run without
the assistant, and the assistant only helps write them. Both reach the system **only
through the action API**. The assistant's sole input is the Settings text box.

---

## 15. Dispatcher defaults by platform

| Platform | Preferred order |
|---|---|
| Windows apps | `pack-wine` → `pack-windows-vm` → remote |
| Windows games | `pack-proton` → `pack-windows-vm` → remote |
| macOS | `pack-macos-neo` → `pack-darling` (Intel-only) |
| Android | `pack-waydroid` (+ ARM bridge when needed) |
| PS1 / PS2 / PSP | local emulator pack |
| PS3 | `pack-rpcs3` → remote |
| PS4 | `pack-shadps4` → `pack-chiaki` → remote |
| PS5 | `pack-chiaki` |
| N64 | `pack-n64recomp-<title>` if it exists → `pack-ares` |
| GC / Wii / Wii U | `pack-dolphin` / `pack-cemu` → remote |
| Switch | `pack-switch-capture` → remote |
| Xbox 360 | `pack-xenonrecomp-<title>` if it exists → `pack-xenia` → remote |
| Xbox One / Series | `pack-proton` (PC version) → `pack-greenlight` |

The compatibility database overrides these per title when another pack is known to work better.

---

## 16. External hardware implied by the catalog

| Hardware | Needed by | Notes |
|---|---|---|
| MacBook Neo logic board (+ spare) | `pack-macos-neo` | Already in the build brief |
| Discrete GPU (RX 7800 XT class) | RPCS3, shadPS4, Xenia, Cemu, VR | Already in the build brief |
| Second GPU, or SR-IOV-capable iGPU | `pack-windows-vm` with 3D apps | **New.** Needed for SolidWorks/Adobe in the VM |
| IOMMU-capable motherboard with clean groups | `pack-windows-vm` | Check before buying the desktop board |
| HDMI capture device (UVC, 1080p60) | `pack-switch-capture` | **New** |
| RP2040 board | `pack-switch-capture` | **New**, pad-emulation firmware |
| Owned consoles | Capture and remote-play packs | Switch, PS4/PS5, Xbox as desired |
| VR headset | VR packs | Optional |
| Wi-Fi 6 router | `pack-alvr`, remote play | Optional |

---

## 17. Known gaps

| Gap | Current answer |
|---|---|
| iOS-only apps | Out of scope; partly covered by `pack-macos-neo` |
| PS5 local | Remote Play only; a local pack would be shadPS4-class |
| Xbox One / Series local | PC versions + Greenlight; no local pack planned |
| Switch emulation | Deliberately excluded; capture coprocessor instead |
| Clean ARM bridge for Android | Interim proprietary pack until `pack-android-armbridge` lands |
| Play Integrity apps | Will not run under Waydroid |
| Kernel anti-cheat games | Out of scope unless the developer enables Linux support |
| Windows 3D apps on the pocket computer | Always remote |

---

## 18. Legal methodology, applied to packs

1. **Packs never bundle firmware, BIOS, ROMs, keys, or OS images.** They declare them by
   name and checksum, and the user supplies them.
2. **No decompiled vendor code in any pack.**
3. **Coprocessor and capture packs use stock hardware, as designed.** No HDCP stripping,
   no firmware modification.
4. **Per-title recompilation packs ship the recompiler and runtime.** The game file comes
   from the user.
