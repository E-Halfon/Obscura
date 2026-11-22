---
name: new-pack
description: Scaffold a new Camera Obscura platform pack (packs/<name>/pack.toml) following ARCHITECTURE.md §17 and register it in docs/PACKS.md. Use when adding support for a platform or a new implementation of one.
---

# Scaffold a new pack

A pack is one installable implementation that runs one platform's software
(ARCHITECTURE.md §17.1). Wine and the hidden Windows VM are two different packs for the
same platform.

## 1. Read first

- docs/ARCHITECTURE.md §17 (pack format and rules) and §14.2 (legal rules)
- docs/PACKS.md §2 (capability vocabulary) and the section for this platform, if a row
  for the pack already exists there

## 2. Ask the user (skip anything PACKS.md already answers)

1. Pack name: `pack-<implementation>`, lowercase, dashes
2. Platform it serves: windows, macos, android, linux-foreign, sony, nintendo, xbox,
   retro, vr, or system
3. Technique: reimplementation, container, emulation, static-recompilation, hidden-os,
   coprocessor, or remote
4. What it handles: binary signatures, installer formats, file extensions
5. Required capabilities, using only names from PACKS.md §2
6. Files the user must supply (firmware, BIOS, keys), each by name and SHA-256 checksum
7. Actions and automation triggers it adds (ARCHITECTURE.md §20, §22), if any

## 3. Write packs/<name>/pack.toml

```toml
[pack]
name      = "pack-example"
platform  = "example"
technique = "emulation"
version   = "0.1.0"
api       = 1

[handles]
magic      = []          # binary signatures the dispatcher matches
installers = []          # installer formats, e.g. ".msi"
extensions = []          # file extensions

[requires]
capabilities = []        # names from PACKS.md §2 only

# One table per user-supplied file. Never the file itself.
# [[user_supplies]]
# name   = "BIOS"
# file   = "scph1001.bin"
# sha256 = "<checksum>"
# where  = "~/Obscura/firmware/<platform>/"

[fallback]
remote = false           # true if it may run on another of the user's devices

[provides]
actions  = []
triggers = []
```

## 4. Rules to check before finishing

- `api = 1`. One platform per pack.
- Dependencies only on core services, or one level deep on `pack-wine` / `pack-proton`.
- **Never add firmware, BIOS, ROMs, keys, or OS images to the pack or the repo.** Declare
  them in `[[user_supplies]]` only. The repo guard will block them anyway.
- No decompiled vendor code.
- If the pack needs a kernel module, say so explicitly: it requires user approval.

## 5. Register it

- Add or update the pack's row in docs/PACKS.md (its platform section, the bundle table in
  §1.4, and §1.5 if it is Stage 0).
- If it changes a decision, update ARCHITECTURE.md §11 in the same commit.
- Commit message: `<task id>: add <pack name>`.
