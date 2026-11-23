# Camera Obscura Systems — Build Brief

**Version:** 5.1
**Date:** 2026-11-21
**Companion documents:** ARCHITECTURE.md v3.1 (design rationale — read that for *why*),
PACKS.md (pack catalog and dependencies)

**Changes from v5.0:** base OS decided — Universal Blue, built with BlueBuild, on the
Aurora base image (§5); task 0.1 unblocked. The pocket computer is x86-64 and runs the same
universal image, so task 2.3 is no longer an OS port. `windows-apps` and `android-apps`
are provided by packs. "Foldable phone" renamed "pocket computer" throughout. R8 and R21
closed.

**Changes from v4.0:** the pack system, dispatcher, compatibility database, per-app
overrides, typed action API, Plasma shell, Settings app shell, coprocessor interface, and
hidden Windows VM move into **Stage 0** (tasks 0.21–0.31), so every platform is built in
pack form from day one. Added **Stage 1.5** — settings assistant and automations (tasks
1.5.1–1.5.8). Base OS decision reopened (§5). Tests T-70 to T-89, risks R18–R22, success
criteria S18–S22, second GPU and Windows license added to parts and budget.

**Changes from v3.0:** added Stage 0.5 — console emulation plus the static-recompilation
and lifter-generator track (tasks 0.5.1–0.5.8), tiered `console-emu` and `remote-compute`
capabilities, tests T-60 to T-67, risks R14–R17. See ARCHITECTURE.md §10.5 for reasoning.

**Changes from v2.0:** added the capability model (§2), the telephony subsystem
throughout, modem parts and budget, WBS tasks 0.17–0.19 and 1.10, tests T-40 to T-46,
risks R10–R13.

---

## 0. INSTRUCTIONS FOR CLAUDE DESIGN

Build an **interactive project dashboard** from this document. Required views:

1. **Schedule** — waterfall/Gantt from §6. Three stages, dependencies shown, critical
   path highlighted. Stage gates visually blocking: Stage 1 cannot start until all
   Stage 0 gate tests pass.
2. **Parts list** — filterable by stage, checkboxes for acquired/not, "verify price"
   flag on every row (all prices are stale estimates).
3. **Budget** — roll-up by stage, low/expected/high columns, running total.
4. **Test matrix** — from §7. Checkbox per test, pass/fail/blocked state, grouped by
   stage, gate tests visually distinct.
5. **Capability matrix** — §2.2, which capabilities are present per build. `console-emu`
   must render as **tiered** (§2.3), not a single flag, with the pocket computer's tier 3–4 cells
   showing the `remote-compute` fallback rather than a bare ✘.
6. **OS decision** — §5 as a decided record (Universal Blue Aurora), with the comparison
   shown as side-by-side history cards.
7. **Lifter-generator track** — Stage 0.5 tasks 0.5.5–0.5.8 with their **ordering rule
   made visually explicit**: the differential fuzzer (0.5.5) blocks everything after it,
   and T-62 is a go/no-go gate on continuing past 0.5.6. Show R14's 20-week timebox as a
   budget bar, not a footnote — it is the project's main schedule risk.
8. **Stage 0 foundation track** — tasks 0.21–0.31 as a second parallel chain alongside
   the Neo chain. Both must finish before 0.20 (integration).
9. **Stage 1.5** — settings assistant and automations, shown after the Stage 1 gate.

**Design constraints:** dark theme. Dense, technical, no marketing gloss. A workbench
tool, not a pitch deck. Persist state so checkboxes survive sessions.

**Do not invent data.** Every price, part number, and duration is an estimate to be
verified. Render them as editable fields, not fixed values.

---

## 1. Project in one paragraph

A Linux OS that runs Windows, macOS, and Android applications as ordinary native windows.
Windows and Android are solved in software (Wine/Proton, Waydroid). macOS requires a
hardware coprocessor — a headless MacBook Neo (A18 Pro) logic board — because Apple's
services authenticate against real silicon and cannot be reimplemented. Telephony is a
capability, not a form factor: any build with a cellular module can make calls, desktop
included. All coprocessors are treated as untrusted and have no network path except
through an Obscura-controlled allowlist. One OS image; capabilities activate wherever the
hardware exists. Three builds in sequence: desktop, thick laptop, pocket computer.

Every implementation is an installable **pack**, grouped into system bundles; a dispatcher
picks the right pack per app, and the user can override it with right-click "Run with"
(SolidWorks → hidden Windows VM). Software that Wine can't run goes to a hidden Windows VM
mirrored window by window. The UI is GUI-first on KDE Plasma — no task requires a terminal
— with a local settings assistant and an automation engine (both later, in Stage 1.5)
built on one typed action API.

---

## 2. Capability model

### 2.1 The rule

One image ships to every device. A capability is a declared feature + a hardware
detection rule + the services it activates. Detected hardware turns it on; absent
hardware leaves it **absent, not broken** — no greyed-out dialer, no error dialogs, no
half-initialized services.

### 2.2 Capability matrix

| Capability | Detection | Desktop | Laptop | Pocket computer |
|---|---|---|---|---|
| `windows-apps` | `pack-wine` installed and ready | ✔ | ✔ | ✔ |
| `android-apps` | `pack-waydroid` installed and ready | ✔ | ✔ | ✔ |
| `apple-coprocessor` | link peer responds | ✔ | ✔ | ✔ |
| `telephony` | udev: modem on USB | ✔ (module) | ✔ | ✔ |
| `console-emu` tier 1–2 | always (x86-64) | ✔ | ✔ | ✔ |
| `console-emu` tier 3–4 | dGPU + sustained power | ✔ | ~ | ✘ |
| `remote-compute` | peer reachable | ✔ host | ✔ | ✔ client |
| `battery` | `/sys/class/power_supply` | — | ✔ | ✔ |
| `touch` | udev: touchscreen | opt | opt | ✔ |
| `gps` | ModemManager / udev | opt | ✔ | ✔ |
| `camera` | udev: UVC / CSI | ✔ | ✔ | ✔ |

### 2.3 Console emulation tiers

Tiering is required because emulation multiplies the workload 5–20x, and the pocket computer's
6–9 W skin-limited budget cannot absorb that on an already-large base workload. Tiers 1–2
run everywhere because their base workload is tiny. Tiers 3–4 route to `remote-compute`
(Sunshine host / Moonlight client over WireGuard) on the pocket computer — **the capability is
present everywhere; only the execution site moves.**

| Tier | Consoles | Technique |
|---|---|---|
| 1 | PS1, PSP | Full emulation, trivial cost |
| 2 | PS2, GameCube | Full emulation, throttled on the pocket computer |
| 3 | PS3, Xbox 360 | Full emulation (RPCS3, Xenia) **or static recompilation (XenonRecomp)** |
| 4 | PS4 | API reimplementation (shadPS4) — x86-64, no CPU translation |

PS5 and Xbox One/Series: nothing exists. Not a tier.

---

## 3. Success criteria

| # | Criterion | Verified by |
|---|---|---|
| S1 | Double-clicking a `.exe` opens a normal Obscura window, no VM chrome | T-01, T-02 |
| S2 | Android apps appear as native windows | T-04 |
| S3 | Mac app windows appear individually, not as a nested desktop | T-08 |
| S4 | Apple coprocessor cannot reach the internet except via allowlist | T-06, T-07 |
| S5 | Foreign apps have no network by default | T-03 |
| S6 | iMessage / FaceTime / iCloud / GarageBand all functional | T-10 – T-13 |
| S7 | One clipboard, one filesystem, one notification bus across all environments | T-14, T-15 |
| S8 | **Desktop can place and receive voice calls with a modem fitted** | T-40, T-41 |
| S9 | **Same image boots on a machine without a modem; telephony cleanly absent** | T-43 |
| S10 | **Modem has no DMA and no route except through Obscura** | T-42 |
| S11 | Laptop idles all day with all coprocessors asleep | T-20, T-21, T-44 |
| S12 | Pocket computer stays within skin-temperature limits under load | T-30 |
| S13 | **One USB stick boots all three devices with correct capabilities, zero failed units** | T-50 |
| S14 | **Console games launch by double-click; tier 3–4 reach the pocket computer via `remote-compute`** | T-60, T-66 |
| S15 | **The lifter generator is verified, not trusted — a known-wrong opcode is caught mechanically** | T-61, T-62 |
| S16 | **No proprietary blob in the Android native path** | T-65 |
| S17 | **Zero decompiled vendor binaries anywhere in the tree** | T-67 |
| S18 | **Every pack that can't run tells the user why and how to fix it** | T-70 |
| S19 | **SolidWorks opens in the hidden Windows VM by default, as a normal window** | T-73, T-75 |
| S20 | **No normal task requires a terminal** | T-76 |
| S21 | **The settings assistant can't act on anything but the user's typed request, and can't weaken security** | T-81, T-82 |
| S22 | **Call settings apply during any call, on any platform, and revert afterward** | T-84, T-85 |

---

## 4. Parts list

> **All prices are August 2026 estimates and must be re-verified.**

### 4.1 Stage 0 — Desktop (bench build)

| Part | Suggested | Est. USD | Notes |
|---|---|---|---|
| Obscura CPU | AMD Ryzen 7 8700G or 9600X | 250–350 | **AMD required** — open amdgpu driver, Wayland-clean. Avoid Nvidia |
| Motherboard | B650 mini-ITX, 2.5GbE onboard | 180–250 | Needs 2× NIC total |
| RAM | 32 GB DDR5 | 90–130 | 64 GB if Waydroid + Wine + VMs concurrently |
| Storage | 2 TB NVMe | 110–160 | |
| Second NIC | 2.5GbE PCIe or USB | 25–40 | Dedicated link to Apple coprocessor |
| PSU | 550 W SFX/ATX | 80–120 | Will later power both boards |
| Case | Any mini-ITX | 60–100 | Open bench frame is better for Stage 0 |
| **Apple coprocessor** | **MacBook Neo (A18 Pro)** | **599** | Buy whole; don't source bare boards yet |
| Spare Neo board | Donor / cracked-screen unit | 150–350 | **Budget one to kill.** See R2 |
| Monitor for Neo setup | Any, or KVM | 0–150 | Needed for TCC consent dialogs |
| USB4/TB4 cable | 40 Gbps certified | 30–50 | |
| Cat6 patch cable | Short | 5 | |
| Webcam + mic | Any UVC | 40–80 | Feeds virtual camera into macOS |
| **Telephony** | | | |
| Cellular module | **SIMCom A7600 series on Waveshare breakout** | 40–90 | Voice + USB audio; ModemManager simtech plugin |
| Alt. module | Quectel EG25-G breakout | 50–100 | Buy **both** — see R10 |
| Antennas | LTE main + diversity, SMA | 10–25 | |
| SIM | Physical SIM, VoLTE-capable plan | ~15/mo | **Test carrier IMS before designing around it** |
| eUICC card (optional) | 5ber / EasyEUICC | 25–50 | Stage 1+ — verify third-party LPA keys first |
| USB isolator (optional) | ADuM-based | 30–50 | Extra isolation on the modem bus |
| **Test equipment** | | | |
| Power analyzer | Nordic PPK2 or INA260 breakouts | 100–150 | **Non-optional** — see R4 |
| USB-C PD tester | Inline meter | 25–40 | |
| Logic analyzer | 8-ch USB | 30–60 | |
| Multimeter | Any decent DMM | 40–80 | |
| SDR (optional) | RTL-SDR | 30–40 | Sanity-check modem TX behaviour |
| **Stage 0.5 — lifter track** | | | |
| dGPU | RX 7800 XT or better | 400–600 | Required for console tiers 3–4. Stay AMD for RADV |
| Reference boards | MIPS + ARM SBCs for differential testing | 50–150 | Ground truth for T-62/T-63. QEMU works for a first pass but real silicon settles disputes |
| Donor console (optional) | For legally dumping titles you own | 50–150 | See the legal note in §9 |
| HDMI capture device | UVC, 1080p60 | 50–130 | For `pack-switch-capture` |
| RP2040 board | Pad-emulation firmware | 5–10 | For `pack-switch-capture` |
| **Stage 0 — foundation** | | | |
| Second GPU for the Windows VM | Mid-range AMD card for passthrough | 200–400 | For SolidWorks/Adobe in the VM (task 0.30). Skip if SR-IOV proves out |
| IOMMU-friendly motherboard | Clean IOMMU groups | (already in board budget) | **Check before buying the desktop board** |
| Windows 11 license | Retail | ~140 | User-supplied for `pack-windows-vm` |

**Stage 0 subtotal: ~$2,300 – $3,750** (desktop bench + foundation; Stage 0.5 items listed above are budgeted separately)

### 4.2 Stage 1 — Thick laptop

| Part | Suggested | Est. USD | Notes |
|---|---|---|---|
| Obscura mainboard | Framework 13 AMD mainboard (bare) | 400–700 | **Recommended** — documented pinouts, open EC, built for custom chassis |
| Display panel | Framework or generic eDP | 100–200 | |
| Battery | Framework 61 Wh or custom pack | 70–150 | |
| Keyboard / trackpad | Framework input kit | 80–150 | |
| Apple coprocessor | Neo board from Stage 0 spare | — | Reuse |
| Cellular module | M.2 3042/3052 **USB-attached** WWAN | 60–120 | **Verify USB, not PCIe/MHI** — see R11 |
| Antennas | Laptop-style, in-lid | 15–30 | |
| Chassis | 3D printed → CNC | 100–400 | Iterate in print first |
| Internal link | USB4 flex / board-to-board | 30–80 | |
| Thermal | Heat pipes, graphite, vapor chamber | 40–100 | |
| Power management | Custom PMIC board / BQ-series | 50–150 | Arbitrates two coprocessors on one pack |

**Stage 1 subtotal: ~$1,000 – $2,100**

### 4.3 Stage 2 — Pocket computer

> **Deliberately incomplete.** Do not commit until Stage 1 thermal and power data exists.

| Part | Options to investigate | Est. USD | Notes |
|---|---|---|---|
| Obscura compute | LattePanda Mu (N100/N150) on a custom carrier (ARCHITECTURE.md §9.1) | 200–600 | **x86-64** — runs the same universal image. Verify price |
| Cellular module | M.2 or soldered, USB-attached | 60–150 | Band support must match target carrier |
| Foldable panel | **Hardest single sourcing item** | 200–600 | Flexible OLED supply is not hobbyist-friendly |
| Hinge | Custom machined | 150–500 | |
| Apple coprocessor | Neo board | — | Reuse or third board |
| Battery | Custom pack, ~60–70 Wh | 80–200 | ~100 cm³, ~240 g of cells |
| Hinge flex | USB4-capable, cycle-rated | 50–200 | **Ethernet through a hinge is not viable** |
| Antennas | Phone-class, fold-aware | 30–80 | Fold state changes antenna behaviour |
| Chassis | CNC aluminium | 300–800 | Unrecoverable if thermals are wrong |

**Stage 2 subtotal: ~$1,100 – $3,200+ (low confidence)**

### 4.4 Budget roll-up

| Stage | Low | Expected | High |
|---|---|---|---|
| 0 — Desktop + foundation | 2,300 | 2,950 | 3,750 |
| 0.5 — Console + lifter track | 570 | 830 | 1,060 |
| 1 — Laptop | 1,000 | 1,550 | 2,100 |
| 1.5 — Assistant + automations | 0 | 0 | 0 |
| 2 — Pocket computer | 1,100 | 2,100 | 3,200+ |
| Contingency (25%) | 1,240 | 1,860 | 2,530 |
| **Total** | **6,210** | **9,290** | **12,640+** |

Stage 1.5 is software only. Stage 0's increase is the second GPU and the Windows license.

Stage 0.5's cost is almost entirely the dGPU. The lifter-generator work itself is labor,
not parts — which is precisely why R14 (schedule, not budget) is the risk that matters.

---

## 5. Base OS decision

### 5.0 Decided: Universal Blue Aurora, built with BlueBuild

**Base image:** `ghcr.io/ublue-os/aurora`, `stable` stream, defined in `recipes/recipe.yml`
and built with BlueBuild. Chosen over NixOS because the GUI-first rule (ARCHITECTURE.md
§19) matters more than maximal reproducibility: Plasma built in, atomic updates and
rollback, GUI-driven updates. Full comparison: ARCHITECTURE.md §5.

**One universal image, capabilities detected at runtime** — never per-host composition —
for every build, the pocket computer included. That rule overrides the "each build is a
composition" wording in the history below.

§5.1–§5.2 are kept as the record of the decision, not as open options.

### 5.1 Original recommendation: NixOS (history)

- The whole system is declared in a flake. Camera Obscura becomes *a set of Nix modules*,
  and each build is a composition of the capabilities its hardware supports — which is
  exactly the §2 model expressed in config.
- Reproducible builds are a stated goal. Nix gives this natively, not as a bolt-on.
- Atomic rollback. When a display-stack change breaks the compositor at 2 a.m., boot the
  previous generation.
- Wine, Waydroid, ModemManager, and bubblewrap/Flatpak all packaged.

**Cost:** steep curve; Nix's language is its own time sink. **Timebox: 3 weeks.**

### 5.2 Alternatives considered (history)

| Option | For | Against |
|---|---|---|
| **NixOS** | Declarative, reproducible, atomic rollback, capabilities = modules | Steep curve; Nix language is its own project |
| **Fedora Silverblue / Universal Blue** | Immutable, ostree, closest shipping analogue; Bazzite bundles Wine/Proton | Less declarative; customization fights the image model |
| **Arch** | Newest Wine/Mesa/kernel/ModemManager, best docs, AUR | Mutable, no rollback, drift across three machines |
| **Debian minimal** | Boring, stable | Old packages — bad on the Wayland/Wine/telephony edge |
| **Alpine / postmarketOS** | Strongest mobile telephony story | Not suitable for Stages 0–1; moot for Stage 2 now that the pocket computer is x86-64 on the universal image |

**Fallback:** if NixOS still costs more than it returns after 3 weeks, switch to Arch and
accept drift. Shipping beats purity.

### 5.3 Stack components

| Layer | Choice |
|---|---|
| Base | Universal Blue Aurora (`stable`), built with BlueBuild |
| Desktop shell | KDE Plasma, stripped and themed |
| Display | Wayland — KWin (draws decorations for mirrored windows) |
| Audio | PipeWire — single clock domain, non-negotiable |
| Windows | `pack-wine`, `pack-proton` (Wine + Proton, DXVK, VKD3D-Proton); `pack-windows-vm` (KVM/libvirt, FreeRDP RemoteApp). Core supplies `binfmt_misc` and KVM |
| Android | `pack-waydroid` (Waydroid, LXC). Core supplies mainline binder/binderfs |
| Dispatch | `binfmt_misc` + dispatcher + compatibility database |
| Packs | Pack manager daemon (DBus), signed packs and system bundles |
| Settings plumbing | Typed action API (DBus) |
| Sandbox | bubblewrap + XDG portals |
| Scheduling | cgroups v2 + rtkit for `SCHED_FIFO` |
| Firewall | nftables, default-deny outbound |
| Telephony | ModemManager + `q6voiced`-style voice audio bridge |
| Dialer/SMS UI | gnome-calls / Chatty as reference, or custom |
| eSIM | lpac |
| Capability activation | udev → systemd → DBus |

---

## 6. Work breakdown

### Stage 0 — Desktop (target: 9–13 months)

| ID | Task | Depends on | Est. weeks |
|---|---|---|---|
| 0.1 | **Universal-image skeleton:** BlueBuild recipe on Universal Blue Aurora (`stable`), signed image builds, boots on the desktop | — | 3 |
| 0.2 | **Capability module framework** (udev → systemd → DBus) — ✅ **done** (PR #2, 2026-11-22; open VM tests tracked in §7, "Stage 0 — capability framework") | 0.1 | 3 |
| 0.2b | **Static capabilities:** `x86-64-v3` and `vulkan-1.3` (notes below the table). Needed for `pack-wine` to reach Ready | 0.2 | 2 |
| 0.3 | **KDE Plasma shell:** strip, theme, Windows-style layout | 0.1 | 2 |
| 0.4 | Wine + binfmt_misc dispatch, `.exe` → window — **delivered as `pack-wine`** | 0.3, 0.21 | 3 |
| 0.5 | Wine sandbox: bubblewrap, no-network default | 0.4 | 2 |
| 0.6 | Waydroid integration, native window surfaces — **delivered as `pack-waydroid`** | 0.3, 0.21 | 3 |
| 0.7 | Neo board bench-up, headless boot, baseline | — | 2 |
| 0.8 | Link layer abstraction + Obscura-as-sole-route | 0.7 | 2 |
| 0.9 | nftables allowlist + deny logging | 0.8 | 2 |
| 0.10 | **ScreenCaptureKit agent** — per-window HEVC streams | 0.7 | 6 |
| 0.11 | Wayland surface per remote window, decode path | 0.10, 0.3 | 4 |
| 0.12 | Input injection (`CGEventPost`) round-trip | 0.11 | 3 |
| 0.13 | **Menu bar strategy** — prototype both, pick one | 0.12 | 6 |
| 0.14 | Virtual camera (`CMIOExtension`) + virtual audio | 0.8 | 5 |
| 0.15 | Shared clipboard across all environments | 0.6, 0.11 | 3 |
| 0.16 | Shared filesystem + path translation | 0.5, 0.8 | 3 |
| 0.17 | **Modem bring-up: ModemManager, data, SMS** | 0.2 | 3 |
| 0.18 | **Voice path: IMS registration + USB audio bridge** | 0.17 | 5 |
| 0.19 | **Dialer/SMS UI wired to the telephony capability** | 0.18 | 3 |
| 0.20 | Integration, Stage 0 test pass | all | 4 |
| **Foundation track** | | | |
| 0.21 | **Pack format v1:** manifest schema, `api` version, readiness evaluation | 0.2 | 4 |
| 0.22 | **Pack manager daemon (DBus) + CLI:** install, update, remove, pin, rollback | 0.21 | 5 |
| 0.23 | System bundles + signed repository (index on GitHub Releases). Signed repository packs become eligible to declare `runtime = true` (until then only factory packs may, §17.4) | 0.22 | 2 |
| 0.24 | **Dispatcher:** precedence rules, compatibility database v0, overrides keyed on product + publisher | 0.21, 0.4 | 4 |
| 0.25 | **Typed action API v1 (DBus):** schemas, tiers, undo, logging; first actions for audio, display, power | 0.2 | 5 |
| 0.26 | Pack manager GUI + right-click "Run with" | 0.22, 0.24, 0.3 | 4 |
| 0.27 | Settings app shell on the action API; devices panel | 0.25, 0.3 | 3 |
| 0.28 | **Coprocessor interface v1**; Neo delivered as `pack-macos-neo` on it | 0.8, 0.21 | 2 |
| 0.29 | **`pack-windows-vm`:** KVM/libvirt/OVMF/swtpm, RemoteApp per-window mirroring, firewalled as an untrusted coprocessor | 0.28, 0.9 | 6 |
| 0.30 | VM GPU acceleration: passthrough vs SR-IOV; SolidWorks as the acceptance app | 0.29 | 3 |
| 0.31 | Telephony delivered as `pack-telephony`, publishing call and SMS events | 0.19, 0.21 | 1 |

**0.2b notes.** The two capabilities need different mechanisms.

- **`x86-64-v3` is a fixed CPU fact.** Try pure systemd conditions first: one
  `ConditionCPUFeature=` line per v3 feature (avx, avx2, bmi1, bmi2, f16c, fma,
  lzcnt/abm, movbe, xsave/osxsave). systemd ANDs repeated conditions together, so no
  oneshot service is needed.
  - **Check first:** which flag names `ConditionCPUFeature=` accepts (e.g. whether LZCNT
    is `abm`), whether every v3 feature is in its table, and that Aurora's systemd
    supports it.
  - **Starting the target.** A condition only gates a start, so something still has to
    start the target. The proposal is a static `multi-user.target.wants/` symlink for
    **static** targets only. The target file itself still has no `[Install]`.
    `tests/unit/test_repo_consistency.py` gains a rule that only static targets may be
    wanted this way.
  - A failed condition leaves the target inactive (absent, nothing failed).
- **`vulkan-1.3` depends on the graphics driver**, so it can't be a systemd condition. It
  needs a probe after the GPU's DRM render node appears.
  - **The capability means a hardware-accelerated Vulkan 1.3 device.** Mesa's lavapipe
    reports Vulkan 1.3 on any CPU, including the VMware test VM. Accept only a device
    with `apiVersion ≥ 1.3`, `deviceType` INTEGRATED_GPU or DISCRETE_GPU, and a driver
    that isn't lavapipe or llvmpipe.
  - **Excluded:** `VK_PHYSICAL_DEVICE_TYPE_CPU`, **`VIRTUAL_GPU`** (VMware SVGA,
    virtio-gpu/venus; decided), and software drivers.
  - **Mechanism constraints:** nothing but detection pulls in the target; "no accelerated
    Vulkan" ends as an inactive target, never a failed unit (an `ExecCondition=` skip
    still satisfies dependents, and an `ExecStart` failure shows in `systemctl
    --failed`); re-probe on GPU add and remove; no Vulkan initialisation inside a udev
    worker.
  - **Kind and attachable:** pick the kind that fits the mechanism (it may end up as
    `probe` or `device`). Readiness no longer depends on the kind: both declarations set
    `attachable = false`, so an absence is "Insufficient hardware", never "connect a
    device".
- **Capability names with dots.** `vulkan-1.3` (like any `x.y` version name) can't be
  declared yet. capd's `NAME_PATTERN` allows only `[a-z0-9-]`, and its object-path
  mapping (hyphen → underscore) has no encoding for `.`. 0.2b widens the pattern and
  picks a one-to-one escaping for object paths (e.g. systemd-style `_2e` for `.` and
  `_2d` for `-`; the current "hyphen → underscore" mapping can't take a second
  character). Pack manifests already accept dotted names (task 0.21).
- **Tests:**
  - CI: the acceptance rule against recorded `vulkaninfo --json` fixtures (lavapipe
    only; lavapipe + RADV; VMware SVGA; discrete + integrated), and a lint that every v3
    feature condition is present.
  - VM: `vulkan-1.3` is **absent** although lavapipe reports 1.3 (the key negative
    test), and `x86-64-v3` is present exactly when `/proc/cpuinfo` has the v3 flags.
  - Desktop: both present.

**0.22 note: readiness runs in the user's session.** Readiness is per user, because the
user-supplied files are in `~`. The evaluation therefore runs in the user's session, as a
systemd user service or in the GUI. The system pack daemon only installs, updates,
removes, pins, and rolls back.

**Two parallel chains, both required before 0.20:**
- **Neo chain (critical path):** 0.1 → 0.2 → 0.7 → 0.10 → 0.11 → 0.12 → 0.13 → 0.20
- **Foundation chain:** 0.1 → 0.2 → 0.21 → 0.22 → 0.24 → 0.26 → 0.20, with 0.25 → 0.27 and 0.28 → 0.29 → 0.30 alongside

**Why the foundation is Stage 0:** the pack model is decided, so every platform is built
as a pack from the start instead of retrofitted. The action API is in Stage 0 because the
GUI, the assistant, and automations all sit on it.

**Telephony runs in parallel** and does not gate the critical path — but **start 0.17 early**
so carrier IMS problems (R10) surface with time to change modules.

### Stage 0.5 — Console emulation and static recompilation (target: 4–6 months, parallel)

Runs after the Stage 0 gate, before Stage 1. Touches nothing load-bearing. See
ARCHITECTURE.md §10.5.

| ID | Task | Depends on | Est. weeks |
|---|---|---|---|
| 0.5.1 | Emulator integration (RPCS3, shadPS4, Xenia-under-Wine, DuckStation/PCSX2) | Stage 0 gate | 3 |
| 0.5.2 | `binfmt_misc` dispatch for SELF/EBOOT/XEX magic | 0.5.1 | 2 |
| 0.5.3 | Tiered `console-emu` capability + `remote-compute` (Sunshine/Moonlight) | 0.5.1 | 3 |
| 0.5.4 | XenonRecomp evaluation on one known-good title | 0.5.1 | 4 |
| 0.5.5 | **Differential fuzz harness — BUILD THIS FIRST within the lifter track** | — | 6 |
| 0.5.6 | AI-drafted SLEIGH from a prose manual, ISA with a known-good spec (MIPS/ARM) | 0.5.5 | 6 |
| 0.5.7 | Point the pipeline at an undocumented ISA | 0.5.6 | 8 |
| 0.5.8 | **Android native bridge investigation (ARM `.so` → x86-64)** | 0.5.6 | 8 |

**Ordering rule:** 0.5.5 before 0.5.6, always. Without the fuzzer, 0.5.6 is an AI guessing
at opcodes. With it, it is a verified spec generator. The harness *is* the product.

**0.5.8 is the only item on this track with architectural value** — it closes the
proprietary-blob hole (R15). Everything else is capability expansion.

### Stage 1 — Laptop (target: 6–9 months)

| ID | Task | Depends on | Est. weeks |
|---|---|---|---|
| 1.1 | Framework mainboard bring-up on the universal image | Stage 0 gate | 3 |
| 1.2 | Power instrumentation on all boards | 1.1 | 2 |
| 1.3 | Internal link (USB4 board-to-board) | 1.1 | 4 |
| 1.4 | Apple coprocessor deep-sleep + wake-on-demand | 1.3, 1.2 | 5 |
| 1.5 | Battery authority + thermal arbitration | 1.4 | 5 |
| 1.6 | Suspend/resume across the link | 1.4 | 4 |
| 1.7 | Chassis: 3D print iterations | 1.1 | 6 |
| 1.8 | Chassis: CNC final | 1.7, 1.5 | 4 |
| 1.9 | Integration, Stage 1 test pass | all | 4 |
| 1.10 | **M.2 modem integration + cellular standby tuning** | 1.2, 1.5 | 4 |

### Stage 1.5 — Settings assistant and automations (target: 4–6 months)

After the Stage 1 gate; may overlap Stage 1 chassis work. Both are packs on the Stage 0
action API — nothing new is needed from the core. See ARCHITECTURE.md §21–§22.

| ID | Task | Depends on | Est. weeks |
|---|---|---|---|
| 1.5.1 | **Automation engine:** When / While / If / Do, scheduler, event listeners (UPower, NetworkManager, BlueZ, udev, KWin, PipeWire, ModemManager, dispatcher) | Stage 1 gate, 0.25 | 6 |
| 1.5.2 | Automation builder page in Settings; pause-all; run log with undo | 1.5.1, 0.27 | 4 |
| 1.5.3 | Call automations: telephony triggers + `microphone_in_use`; "While" auto-revert | 1.5.1, 0.31 | 2 |
| 1.5.4 | Assistant runtime: model selection (1–2B), llama.cpp Vulkan, load on demand | 0.25 | 3 |
| 1.5.5 | Capability manifest generated from action schemas and installed packs; retrieval | 1.5.4 | 3 |
| 1.5.6 | Assistant UI in Settings: constrained decoding, feedback buttons, deep links to settings | 1.5.5, 0.27 | 4 |
| 1.5.7 | Deterministic fast-path parser for common commands | 1.5.6 | 2 |
| 1.5.8 | Ship default automations (all off): Night Mode, Docked, Low battery, On a call, Focus, Headphones | 1.5.3 | 1 |

### Stage 2 — Pocket computer (target: 12–18 months, low confidence)

| ID | Task | Depends on | Est. weeks |
|---|---|---|---|
| 2.1 | Carrier board + modem selection research | Stage 1 gate | 8 |
| 2.2 | **Foldable panel sourcing — start during Stage 1** | — | 12 |
| 2.3 | Bring-up on the universal image: drivers, capability modules, touch shell | 2.1 | 10 |
| 2.4 | Hinge design + flex qualification | 2.2 | 10 |
| 2.5 | Antenna design, fold-state aware | 2.4 | 6 |
| 2.6 | Thermal model from Stage 1 data + margin | Stage 1 gate | 4 |
| 2.7 | Chassis CNC — **irreversible** | 2.4, 2.6 | 6 |
| 2.8 | Assembly + integration | all | 8 |

---

## 7. Manual test plan

**Legend:** 🚪 = stage gate (blocks the next stage) · ⏱ = repeat after every major change

### Stage 0 — core

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-01 🚪 | `.exe` launches natively | Double-click a Win32 app | Window opens; no VM chrome, no launcher dialog, no nested desktop |
| T-02 🚪 | Host owns placement | Tile, stack, alt-tab, move the window | Identical to a native app; never overrides the compositor |
| T-03 🚪 | Wine sandbox holds | Run a known phone-home app; `tcpdump` all interfaces | Zero outbound packets; attempt appears in deny log |
| T-04 🚪 | Android native windows | Launch a Waydroid app | Own Wayland surface; tiles and focuses natively |
| T-05 | Neo headless boot | Power on with no display; reach over link | Boots to login, reachable, no display needed |
| T-06 🚪 | **Coprocessor cannot self-route** | Unplug Obscura's uplink. From Neo: ping, DNS, arbitrary host | All fail. Confirm Wi-Fi/BT firmware-disabled, not merely off |
| T-07 🚪 | Deny logging works | Trigger 10 blocked connections | All 10 logged with destination and timestamp |
| T-08 🚪 | Per-window mirroring | Open Messages and GarageBand together | Two independent Obscura windows, independently movable. **Not** one desktop rectangle |
| T-09 | Input round-trip | Type, click, scroll, drag in a mirrored window | Correct; no modifier or scroll-direction inversion |
| T-10 🚪 | Menu bar | Open GarageBand's File → Edit → Track | Menus reachable and functional from within Obscura |
| T-11 🚪 | Virtual camera | Start a FaceTime call | Remote party sees Obscura's webcam; audio bidirectional |
| T-12 🚪 | iMessage | Send/receive, including an attachment | Delivered both directions; attachment opens |
| T-13 | Mirror latency | Photograph a ms-timer and its mirrored copy together | Record the number. Target <50 ms; flag if >80 ms |
| T-14 | Unified clipboard | Copy in each environment, paste into the others | All combinations work, text and image |
| T-15 | Unified filesystem | File dialog in Wine, Waydroid, and Mac apps | All see the same `~/Documents` with correct paths |
| T-16 ⏱ | Audio clock | Play from Linux, Wine, and Waydroid simultaneously | No crackle, drift, or resampling artifacts |
| T-17 | Scheduling under load | Wine game while compiling | No audio dropouts; input lag subjectively flat |
| T-18 | TCC survival | Apply a macOS point update, reboot | Note whether consent survives. **Expected to fail** — document recovery |

### Stage 0 — capability framework (task 0.2)

Task 0.2 passed its VM run on the branch image (`ghcr.io/e-halfon/obscura:315e4e2-45`,
VMware Workstation). The C-tests are defined in `tests/vm/capabilities.sh` and
`tests/vm/README.md`. These were **not run** in that pass and stay open until they are:

| ID | Test | Why it hasn't run | Unblocked by |
|---|---|---|---|
| C-2 | `virt` present when `/dev/kvm` exists | Nested virtualization is unavailable in VMware while Hyper-V is on in the Windows host | Nested VT-x/AMD-V in the VM (Hyper-V off on the host), or bare metal |
| C-3 | Camera hotplug ×10, one Added/Removed per cycle | Needs a USB webcam passed through to the VM | A webcam connected through *VM → Removable Devices* |
| C-4 | Battery hotplug ×10 | Uses the `test_power` module, which Fedora's kernel very likely doesn't ship (`CONFIG_TEST_POWER` off) | Run on the laptop (Stage 1 hardware) |
| C-4b | Battery present (`state --present battery`) | Needs VMware's *Report battery information to guest* on a host with a battery | A laptop host, or the laptop itself |
| C-8 (hardware) | mcelog skipped, not failed, on AMD | Bare-metal AMD only; a VM can't show it (ARCHITECTURE.md §12 item 14) | Boot the image on the Ryzen desktop |

T-50 (one USB stick boots all three devices with correct capabilities and no failed units)
also remains open until the hardware exists.

### Stage 0 — pack format (task 0.21)

Defined in `tests/vm/packs.sh` and `tests/vm/README.md`. The unit and integration tests
run in CI (`capd-tests`).

| ID | Test | Pass condition |
|---|---|---|
| P-1 | Factory manifests | Every manifest in `/usr/share/obscura/packs` validates; `obscura-pack list` shows `pack-wine` from the factory root |
| P-2 | pack-wine on the VM | **Insufficient hardware.** Before 0.2b: `capability-unknown` for `x86-64-v3` and `vulkan-1.3`. After 0.2b: `vulkan-1.3` absent (the VM has no accelerated Vulkan). Ready is checked on the bare-metal desktop |
| P-3 | No requirements | A fixture pack with no requirements is Ready |
| P-4 | Hardware hotplug | A fixture requiring `camera`: Missing hardware, then Ready after a webcam is connected (interactive) |
| P-5 | User files | A fixture with a user file: absent → Missing files; wrong content → Missing files (wrong dump); right content → Ready |
| P-6 | Removed marker | A `removed` marker hides pack-wine; deleting it restores it |
| P-7 | Malformed manifest | Skipped with one reported problem; no traceback, no failed units |

P-1…P-7 cover the user-files half of T-70. Its Neo half stays open until 0.28.

### Stage 0 — telephony

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-40 🚪 | **Capability activates on detection** | Boot with modem attached; `mmcli -L` | Modem detected, telephony unit active, dialer present within 30 s of boot |
| T-41 🚪 | **Outbound voice call** | Place a call to a known number; hold 2 min | Connects; audio clean **both directions**; no dropout; hangs up cleanly |
| T-42 🚪 | **Modem isolation** | Verify USB not PCIe (`lspci` vs `lsusb`); confirm no IOMMU-mapped DMA; check routing | USB-attached, no DMA, no independent default route, traffic subject to nftables |
| T-43 🚪 | **Absence is clean** | Boot the **same image** on a machine with no modem | No dialer, no error dialogs, no failed units in `systemctl --failed`, no log spam |
| T-44 | Inbound call and SMS | Call and text the device from another phone | Both arrive; notification fires; call answerable from the UI |
| T-45 | Hotplug | Attach and remove the modem while running, ×10 | Capability appears and disappears cleanly each time; no stuck state |
| T-46 | Carrier IMS acceptance | Register on the actual target carrier | IMS registration succeeds with the module's own IMEI. **If this fails, the module choice changes — see R10** |
| T-47 | eSIM profile (Stage 1+) | Download a profile with lpac to a removable eUICC | Profile installs, activates, and survives reboot |
| T-48 | Audio routing conflict | Take a call while Wine audio and a Mac window are active | Call audio takes priority; other streams duck or pause; nothing crashes |

### Stage 0.5 — console emulation and static recompilation

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-60 | Console dispatch | Double-click a game file for each supported console | Correct emulator launches via `binfmt_misc`; no launcher UI |
| T-61 🚪 | **Fuzzer catches a bad opcode** | Deliberately corrupt one SLEIGH definition; run the differential harness | Caught within the fuzz budget. **If the harness misses a known-wrong definition, the whole lifter track is invalid — stop and fix the harness** |
| T-62 🚪 | **Method proof on a known-good ISA** | Regenerate MIPS or ARM semantics from the prose manual; diff against Sail/SLEIGH reference | Equivalent on every opcode, or every divergence explained. **This is what justifies continuing to 0.5.7** |
| T-63 | Undocumented-ISA run | Point the pipeline at an ISA with no formal spec | Definitions pass differential fuzzing against real hardware. Record coverage % — partial is a real result |
| T-64 | Static recompile vs emulation | Run one XenonRecomp title and the same title under Xenia | Native build matches emulated behaviour; record the frame-rate and power delta |
| T-65 🚪 | **Android ARM `.so` on x86-64** | Install an ARM-only Android app on Waydroid with **no proprietary bridge** | App runs. **This is the only architecturally load-bearing test on the track — see R15** |
| T-66 | Tiered capability correctness | Boot on desktop, laptop, pocket computer | Tiers 1–2 active everywhere; tiers 3–4 active only where a dGPU exists; `remote-compute` fills the gap on the pocket computer |
| T-67 | Clean-room audit | Review every input to the lifter generator | Every source is a public ISA manual or reference hardware. **Zero decompiled vendor binaries in the tree** |

### Stage 0 — foundation (packs, dispatcher, action API, Windows VM)

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-70 🚪 | **Readiness explains itself** | Install the macOS pack with no Neo connected; install a pack whose firmware is missing | Each reports *why* in plain language, with the fix. No silent failure, no crash |
| T-71 | Bundle install / single-pack removal | Install the Windows bundle; remove 86Box only | Wine and Proton untouched; Wine installed once even when another bundle also uses it |
| T-72 | Pin and roll back | Pin a pack version; update all; roll back another pack | Pinned pack unchanged; rollback restores the previous version |
| T-73 🚪 | **Override survives an update** | "Run with → Windows VM, always" for SolidWorks; update or reinstall SolidWorks | Still routes to the VM; the override matched product + publisher, not the path |
| T-74 | Dispatcher fallback | Open an app whose preferred pack isn't ready on this device | Falls back to the next option and says why |
| T-75 🚪 | **SolidWorks in the VM** | Open a SolidWorks assembly from Obscura | Appears as an ordinary Obscura window with usable 3D performance; no Windows desktop visible |
| T-76 🚪 | **No-terminal audit** | Do the §19.1 task list in ARCHITECTURE.md (install, run, update, undo update, check hardware, diagnose, recover) | Every task completed without opening a terminal |
| T-77 🚪 | **Action API tiers** | Call a confirm-tier and a show-only action programmatically | Confirm-tier waits for approval; show-only refuses and opens the setting. Every action logged and undoable |
| T-78 | VM isolation | Repeat T-06 against the Windows VM | No route except through Obscura; denies logged |

### Stage 1.5 — settings assistant and automations

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-80 | Conversational adjust | "lower the volume a bit," then Quieter / Good | Correct step; test tone plays; converges in ≤3 clicks |
| T-81 🚪 | **Assistant input isolation** | Inspect the assistant's sandbox; try to make it read a file or URL | It has no file, network, or notification access. Its only input is the Settings text box |
| T-82 🚪 | **Assistant can't weaken security** | Ask it to disable the firewall or flip a kill switch | It opens the setting and changes nothing |
| T-83 | Macro without the model | Night Mode fires at sunset | Runs with the model unloaded |
| T-84 🚪 | **Call automation reverts** | Take a cellular call with "On a call" enabled; hang up | Settings applied during the call; **everything restored** after |
| T-85 | Any-platform calls | FaceTime on the Neo, Teams in the VM, Discord under Wine | `microphone_in_use` fires for each |
| T-86 🚪 | **Unattended safety** | Network-message trigger whose automation includes a confirm-tier action | The confirm-tier step is refused and logged; free-tier steps run |
| T-87 | Pause all | Enable pause; fire several triggers | Nothing runs; log shows paused |
| T-88 | Cooldown | Flap a display cable 10× in 10 s | Automation fires once within its cooldown |
| T-89 | Assistant power cost | Measure draw on the pocket computer, assistant idle | Model unloaded; no measurable idle cost |

### Stage 1

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-20 🚪 | **Apple coprocessor deep sleep** | Close all Mac windows; log current 8 h | Reaches and *stays at* ~0.1 W. Every wake event attributable |
| T-21 🚪 | All-day idle | Full charge, coprocessors asleep, light use | ≥8 h. Record the actual figure |
| T-22 | Wake latency | Click a Mac app from cold sleep, 20 trials | Window visible <3 s, consistently |
| T-23 🚪 | Thermal arbitration | Load both SoCs 30 min | Skin <48 °C; Obscura demonstrably throttles the coprocessor |
| T-24 | Suspend/resume | Lid ×20, including with Mac windows open | Windows restore; link re-establishes; no orphaned streams |
| T-25 | Power path audit | Review 7 days of logged current | No unexplained wakes; every daemon keeping the Neo awake documented |
| T-26 | Link stability | 72 h continuous with mirrored windows | Zero drops; any drop root-caused before Stage 2 |
| T-27 🚪 | **Cellular standby drain** | Modem registered, idle, screen off, 8 h | Standby cost quantified and within budget. Record the number |
| T-28 | **Call while suspended** | Suspend, then call the device | Wakes and rings, or fails *predictably*. Document actual behaviour |

### Stage 2

| ID | Test | Method | Pass condition |
|---|---|---|---|
| T-30 🚪 | Skin temperature | Sustained load; thermal camera or 6 thermocouples | <48 °C at every point |
| T-31 🚪 | Total power envelope | Whole-device draw under realistic load | ≤6–9 W sustained |
| T-32 | Hinge flex endurance | 10,000 fold cycles with link active | No link degradation, no flex fatigue |
| T-33 | Field battery | A normal day of use | Record hours. No fixed target — establish the real number |
| T-34 | Drop / flex | Modest drop test on a non-final chassis | Nothing structural fails before committing to CNC |
| T-35 🚪 | **Antenna vs fold state** | Signal strength open and closed, several locations | No unacceptable degradation in either state |
| T-36 | **Call quality on battery** | 30-min call, screen on, on battery | Audio clean throughout; no thermal throttle mid-call |

---

## 8. Risk register

| ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Menu bar approach looks bolted-on, or takes 3× the estimate | Stage 0 slip | Prototype both in weeks 1–2 of task 0.13 |
| R2 | Neo board bricked during headless / parts-pairing work | $600 + weeks | **Spare board budgeted from day one.** Never experiment on the only unit |
| R3 | Neo demands a real battery management IC, not a bare rail | Stage 1 redesign | Characterize on the bench in 0.7, not in the laptop |
| R4 | Coprocessor never reliably reaches deep sleep | Kills pocket-computer viability | T-20 is a hard gate; power instrumentation from day one |
| R5 | macOS update breaks the ScreenCaptureKit agent or TCC grants | Recurring outage | Pin macOS version; test updates on the spare board first |
| R6 | Foldable panel unsourceable at hobbyist scale | Stage 2 blocked | Start 2.2 during Stage 1, not after |
| R7 | Pocket-computer thermals exceed budget after CNC | Unrecoverable | Add margin to Stage 1 figures; validate on a printed chassis |
| R8 | ~~NixOS learning curve eats months~~ | — | **Closed:** base OS is Universal Blue (§5) |
| R9 | Apple changes activation or service endpoints | Feature loss | Log all traffic; keep libimobiledevice/BlueBubbles fallbacks documented |
| **R10** | **Carrier refuses IMS to the module's IMEI** | **No voice calls at all** | **Buy two modules (SIMCom + Quectel). Test with a real SIM in task 0.17, early. If both fail, voice may need a SIP bridge over data instead** |
| **R11** | **M.2 modem turns out PCIe/MHI, not USB** | **DMA exposure; violates principle 4** | **Verify attachment before purchase; `lsusb` vs `lspci` on arrival is T-42** |
| **R12** | **Modem keeps the host awake in standby** | **Battery target missed** | **T-27 quantifies it on the laptop, before the pocket computer depends on it** |
| **R13** | **eUICC card keys stop permitting third-party LPAs** | **eSIM path closes** | **Physical SIM is the Stage 0 baseline; eSIM stays optional. Verify before buying cards** |
| **R14** | **The lifter generator eats the project** | **Stage 1 and 2 never happen** | **Hardest risk on the board — generality is where tooling projects die. Timebox 0.5.5–0.5.7 to 20 weeks total. T-62 is the go/no-go: if the method can't regenerate a known-good spec, stop. Stage 1 does not wait on this track** |
| **R15** | **No clean-room path for ARM `.so` on x86-64** | **`android-apps` permanently depends on an abandoned proprietary blob** | **T-65 is the measure. If 0.5.8 fails, document the gap honestly in the capability matrix rather than shipping libhoudini silently — it contradicts tenet 2** |
| **R16** | **AI-drafted specs pass fuzzing but miss rare paths** | **Silent wrong behaviour in recompiled output** | **Fuzz budget per opcode, not per ISA. Target edge cases explicitly: carry boundaries, denormals, overflow, alignment faults. Record coverage; never claim an unfuzzed opcode is correct** |
| **R17** | **Existing formal specs (Sail/ASL/SLEIGH) make the generator redundant** | **Months spent on a solved problem** | **Survey prior art before 0.5.5. The generator only justifies itself on ISAs with no formal spec — scope it there from the start** |
| **R18** | **Pack API v1 is wrong** | **Every pack needs rework later** | **Build Wine, Waydroid, the Neo, and the VM as packs from day one so v1 is tested by real use; version the API from the start** |
| **R19** | **UI, assistant, and automation work crowds out the core** | **Stage 0 slips; nothing runs foreign software** | **Only the action API, Settings shell, and pack GUI are Stage 0. The assistant and automations wait for Stage 1.5** |
| R20 | No usable GPU acceleration for the VM on the laptop | SolidWorks laptop-local not possible | Second GPU on desktop; SR-IOV evaluated in 0.30; laptop routes to desktop via `remote-compute` |
| R21 | ~~Base-OS decision churns~~ | — | **Closed:** decided — Universal Blue Aurora (§5) |
| R22 | Small model is unreliable at tool calls | Wrong settings changed | Constrained decoding, deterministic fast path, undo on every action, confirm-tier for anything consequential |

---

## 9. Constraints carried forward — do not relitigate

- Apple **cannot** be given zero network access; iMessage/FaceTime/iCloud are clients for
  Apple's servers. Goal is one allowlisted path, not zero.
- Content inspection is impossible (certificate pinning). Allowlist by SNI/domain only.
- Metadata (Apple ID, device list, online times, contact graph) is visible to Apple.
- **Do not implement a host-side IMS/SIP stack.** Choose a modem whose firmware does IMS.
- **Modems attach over USB, never PCIe** — no DMA from unauditable firmware.
- **Never modify a modem's IMEI.** Use pre-certified modules only.
- Anti-cheat circumvention is out of scope — incompatible with the sandboxing model.
- Windows `.sys` drivers do not load into the Linux kernel. Userspace shim only.
- **No AI in the opcode translation path without differential validation.** Plausible ≠
  equivalent. The fuzzer is what makes the method sound.
- **No AI decompilation of vendor binaries, ever.** No verification oracle, and it poisons
  clean-room. The lifter generator reads public ISA manuals, not shipped binaries.
- **The lifter generator is a lifter generator, not a recompiler.** Lifting is ~10–20% of a
  static-recompilation project; the runtime/HLE layer is the rest.
- macOS 26 Tahoe is the last Intel release; the Neo is the only board with a future.
- Steady-state pocket-computer thermal is bound by **skin area, not volume**.
- **Every implementation is a pack**; no platform is hardcoded into the core.
- **No normal task may require a terminal.**
- **The settings assistant is local, takes input only from the Settings text box, and acts
  only through the action API within its tiers.**
- **Unattended automations run free-tier actions only.**
- **One universal image, runtime capability detection** — never per-host composition.
