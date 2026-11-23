# Camera Obscura

A Linux OS (Universal Blue base, built with BlueBuild) that runs software from any
operating system as one cohesive system. It reimplements a platform where it can and runs
the real platform hidden where it can't, and the user never sees the difference.

Design docs: docs/ARCHITECTURE.md (why), docs/CAMERA-OBSCURA-BUILD-BRIEF.md (plan,
tasks, tests), docs/PACKS.md (pack catalog). Read the relevant section before changing
anything it covers. Decisions in ARCHITECTURE.md §11 are settled; don't re-propose
rejected options.

## Hard rules
- Every implementation is a pack (§17). Nothing platform-specific in the core.
- One universal x86-64 image; capabilities detected at runtime, never per-device builds (§4).
- No normal task may require a terminal (§19).
- Settings change only through the typed action API (§20).
- Never commit firmware, BIOS, ROMs, keys, OS images, or decompiled vendor code (§14.2).
  A hook in .claude/settings.json and the git pre-commit hook in .githooks/ enforce this.
- Coprocessors (Neo, Windows VM, modem) are untrusted: no route except Obscura's allowlist.

## Coding standards
- Every `if` and `else` has braces, even single-line bodies.
- Every function has a try/catch (or the language's equivalent) that catches and reports
  failures such as index out of range, rather than letting them escape silently.
- Test functions (tests/) are exempt from the try/catch rule: assertions and exceptions
  must propagate so the test framework can report them. Production code still follows it.

## Repo layout
- recipes/recipe.yml: the BlueBuild OS definition
- files/system/: files copied into the image root; files/scripts/: build-time scripts
- packs/: pack manifests and pack code (scaffold new ones with /new-pack)
- src/: pack manager, dispatcher, action API, Settings modules
- docs/: the three design documents

## Workflow
- Work one build-brief task at a time; put the task ID in commit messages ("0.21: ...").
- Before merging, run the architecture-reviewer agent on the diff.
- When a decision changes, update ARCHITECTURE.md §11 in the same commit.
- Ask before anything irreversible: pushing to main, deleting files, touching secrets.
