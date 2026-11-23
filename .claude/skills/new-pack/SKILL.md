---
name: new-pack
description: Scaffold a new Camera Obscura platform pack (pack.toml, manifest v1) following ARCHITECTURE.md §17 and register it in docs/PACKS.md. Use when adding support for a platform or a new implementation of one.
---

# Scaffold a new pack

A pack is one installable implementation that runs one platform's software
(ARCHITECTURE.md §17.1). Wine and the hidden Windows VM are two different packs for the
same platform.

## 1. Read first

- docs/ARCHITECTURE.md §17 (manifest v1 format, readiness, rules) and §14.2 (legal rules)
- docs/PACKS.md §2 (capability vocabulary) and the section for this platform, if a row
  for the pack already exists there

## 2. Ask the user (skip anything PACKS.md already answers)

1. Pack name: `pack-<implementation>`, lowercase, dashes
2. Platform it serves: windows, macos, android, linux-foreign, sony, nintendo, xbox,
   retro, vr, or system
3. Technique: reimplementation, container, emulation, static-recompilation, hidden-os,
   coprocessor, or remote
4. What it handles: binary signatures (names from
   `files/system/usr/share/obscura/signatures.toml`; add a new signature there if
   needed), installer formats, file extensions
5. Required capabilities, and recommended ones, using only names from PACKS.md §2
6. Files the user must supply (firmware, BIOS, keys, ROM sets, OS images), each by file
   name and SHA-256 checksum
7. Actions and automation triggers it adds (ARCHITECTURE.md §20, §22), if any
8. Whether it's a runtime pack (only Wine and Proton are), or depends on one

## 3. Write the manifest

A pack shipped in the image goes in
`files/system/usr/share/obscura/packs/<name>/pack.toml`. The directory name must equal
`pack.name`. Validate it with
`PYTHONPATH=files/system/usr/lib/obscura/python python3 -m obscura_packs.cli validate <dir>`.

```toml
[pack]
name      = "pack-example"
api       = 1
# api_minor = 0              # feature level; raise only when using fields from a newer level (§17.4)
version   = "0.1.0"
platform  = "retro"
technique = "emulation"
summary   = "One plain-language sentence for the pack manager."
status    = "experimental"   # mature | usable | experimental | planned
# runtime  = true            # only for runtime packs (pack-wine, pack-proton)
# files_dir = "ps1"          # see the files_dir convention below

[handles]
magic      = []          # names from signatures.toml only; never magic bytes
installers = []          # e.g. ".msi"
extensions = []          # e.g. ".cue"

[requires]
capabilities = []        # names from PACKS.md §2 only

[recommends]
capabilities = []        # missing ones produce a note, not a readiness failure

# [depends]
# runtime = ["pack-proton"]   # runtime packs only, one level deep

# One table per user-supplied file. Never the file itself.
# [[user_supplies]]
# id       = "bios-us"
# label    = "PlayStation BIOS (US)"
# kind     = "bios"          # firmware | bios | keys | rom-set | os-image | media
# file     = "scph1001.bin"
# sha256   = ["<64 lowercase hex>"]   # required except for os-image and media
# required = true

[fallback]
remote = false           # true if it may run on another of the user's devices

[provides]
actions  = []
triggers = []

[touches]
kernel_modules = []      # non-empty means installing needs explicit approval
devices        = []      # e.g. "/dev/dri"
```

The manifest is strict. An unknown key or table is an error.

### files_dir convention

User files go in `~/Obscura/firmware/<files_dir>/`. **Packs for the same console share
`files_dir`, named after the console** (`ps1`, `ps2`, `ps3`, `psp`, `gc`, `wii`, `n64`,
`nds`, `saturn`, `dreamcast`, …), so the user places a BIOS once. For example,
`pack-duckstation` and `pack-mednafen` both set `files_dir = "ps1"`. Packs that aren't
console emulators keep the default: the pack name without `pack-`.

## 4. Rules to check before finishing

- `api = 1`. One platform per pack.
- Dependencies only on core services, or one level deep on a runtime pack (`pack-wine`,
  `pack-proton`).
- **Never add firmware, BIOS, ROMs, keys, or OS images to the pack or the repo.** Declare
  them in `[[user_supplies]]` only. The repo guard blocks them anyway.
- No decompiled vendor code.
- If the pack needs a kernel module, list it in `touches.kernel_modules`. Installing it
  then needs user approval.
- `tests/unit/test_pack_consistency.py` must pass.

## 5. Register it

- Add or update the pack's row in docs/PACKS.md (its platform section, the bundle table in
  §1.4, and §1.5 if it is Stage 0).
- If it changes a decision, update ARCHITECTURE.md §11 in the same commit.
- Commit message: `<task id>: add <pack name>`.
