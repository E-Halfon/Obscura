"""Readiness: can this pack run here, and if not, why and what fixes it (ARCHITECTURE.md §17.3).

evaluate() is pure. Its inputs are the manifest, the capabilities capd reports present,
capd's vocabulary (for each capability's kind and summary), the readiness of installed
runtime packs, and the user files' status. Every reason is collected, so the user sees
every fix at once. The state is then chosen by precedence: hardware, then runtime, then
files, then Ready.

It fails closed. Any unexpected exception gives UNEVALUABLE ("Couldn't evaluate"), with
the error reported through obscura_capd.report, and never READY.
"""

import os
from dataclasses import dataclass

from obscura_capd import report
from obscura_packs import userfiles
from obscura_packs.constants import (
    INSUFFICIENT_HARDWARE,
    MISSING_FILES,
    MISSING_HARDWARE,
    NEEDS_NEWER_OBSCURA,
    NEEDS_PACK,
    READY,
    REMOTE,
    UNEVALUABLE,
)

# Fixes: action identifiers the GUI (task 0.26) turns into buttons. No terminal (§19).
FIX_CONNECT_DEVICE = "connect-device"
FIX_UPDATE_OBSCURA = "update-obscura"
FIX_INSTALL_PACK = "install-pack"
FIX_OPEN_FILES_FOLDER = "open-files-folder"
FIX_COPY_DIAGNOSTICS = "copy-diagnostics"
FIX_RUN_HERE = "allow-on-this-device"


@dataclass(frozen=True)
class Reason:
    code: str
    subject: str
    message: str
    fix: str = ""


@dataclass(frozen=True)
class Readiness:
    pack: str
    state: str
    reasons: tuple = ()
    notes: tuple = ()


def _describe(name, vocabulary):
    """'a webcam (camera)' style text from the capability's summary, or the bare name."""
    try:
        declaration = vocabulary.get(name)
        if declaration is None:
            return name
        return declaration.summary + " (" + name + ")"
    except Exception as error:
        report.failure("readiness._describe", error)
        raise


def _hardware(manifest, present, vocabulary, not_on_this_device):
    """(reasons, fixable): reasons for every missing required capability, and whether
    connecting something could fix all of them. Each capability's declaration says whether
    it's attachable (independent of how it's detected). One absent capability that isn't
    attachable, or can't be detected, makes the whole result Insufficient hardware:
    telling the user to connect a device would not help."""
    try:
        reasons = []
        fixable = True
        for name in manifest.requires:
            if name in present:
                continue
            declaration = vocabulary.get(name)
            if declaration is None:
                fixable = False
                reasons.append(Reason("capability-unknown", name,
                                      "Needs " + name + ", which this version of Obscura can't detect yet.",
                                      FIX_UPDATE_OBSCURA))
            elif declaration.attachable is True:
                reasons.append(Reason("capability-absent", name,
                                      "Needs " + _describe(name, vocabulary) + ". None is connected or reachable.",
                                      FIX_CONNECT_DEVICE))
            else:
                fixable = False
                reasons.append(Reason("capability-absent", name,
                                      "Needs " + _describe(name, vocabulary) + ". This device doesn't have it."))
        if not_on_this_device:
            fixable = False
            reasons.append(Reason("not-on-this-device", manifest.name,
                                  "Set not to run on this device.", FIX_RUN_HERE))
        return reasons, fixable
    except Exception as error:
        report.failure("readiness._hardware", error)
        raise


def _runtimes(manifest, runtime_states, remote_ready):
    """(reasons, inherited state or None, remote). A dependency that isn't installed needs a
    pack. An installed runtime that isn't ready passes its state on. A runtime that only
    runs remotely is enough only if this pack may itself run remotely and a peer can run
    it (remote is then True); otherwise this pack can't run anywhere, which is
    Insufficient hardware, never Remote."""
    try:
        reasons = []
        inherited = None
        remote = False
        for name in manifest.depends:
            state = runtime_states.get(name)
            if state is None:
                reasons.append(Reason("needs-pack", name, "Needs the " + name + " pack, which isn't installed.",
                                      FIX_INSTALL_PACK))
                continue
            if state.state == READY:
                continue
            if state.state == REMOTE:
                if manifest.remote and remote_ready:
                    remote = True
                    continue
                reasons.append(Reason("runtime-remote-only", name,
                                      "Needs the " + name + " pack, which can only run on another of your devices,"
                                      " and this pack can't run remotely."))
                if inherited is None:
                    inherited = INSUFFICIENT_HARDWARE
                continue
            why = state.reasons[0].message if state.reasons else state.state
            reasons.append(Reason("runtime-not-ready", name, "Needs the " + name + " pack, which isn't ready: " + why,
                                  state.reasons[0].fix if state.reasons else ""))
            if inherited is None:
                inherited = state.state
        return reasons, inherited, remote
    except Exception as error:
        report.failure("readiness._runtimes", error)
        raise


def _files(manifest, file_status):
    """(reasons for required files, notes for optional ones)."""
    try:
        reasons = []
        notes = []
        for user_file in manifest.user_supplies:
            status = file_status[user_file.id]  # a missing entry is a bug: KeyError, fail closed
            if status.status == userfiles.OK:
                continue
            if status.status == userfiles.ABSENT:
                code, text = "file-absent", "Place the " + user_file.label + " (" + user_file.file + ") in " + _folder(status.path) + "."
            elif status.status == userfiles.WRONG_DUMP:
                code, text = "file-wrong-dump", ("The " + user_file.label + " in " + _folder(status.path)
                                                 + " isn't a known good copy (its checksum doesn't match).")
            elif status.status == userfiles.UNREADABLE:
                code, text = "file-unreadable", ("The " + user_file.label + " in " + _folder(status.path)
                                                 + " can't be read" + (": " + status.detail if status.detail else "") + ".")
            else:
                raise ValueError("unknown file status " + repr(status.status))
            if user_file.required:
                reasons.append(Reason(code, user_file.id, text, FIX_OPEN_FILES_FOLDER))
            else:
                notes.append("Optional: " + text)
        return reasons, notes
    except Exception as error:
        report.failure("readiness._files", error)
        raise


def _folder(path):
    try:
        return os.path.join(os.path.dirname(path), "")
    except Exception as error:
        report.failure("readiness._folder", error)
        raise


def _recommendations(manifest, present, vocabulary):
    try:
        notes = []
        for name in manifest.recommends:
            if name not in present:
                notes.append("Works better with " + _describe(name, vocabulary) + ".")
        return notes
    except Exception as error:
        report.failure("readiness._recommendations", error)
        raise


def _evaluate(manifest, present, vocabulary, runtime_states, file_status, not_on_this_device, remote_ready):
    try:
        if manifest.needs_newer:
            return Readiness(manifest.name, NEEDS_NEWER_OBSCURA, (Reason(
                "needs-newer-obscura", manifest.name,
                "This pack needs a newer version of Obscura.", FIX_UPDATE_OBSCURA),))
        # Only required capabilities can block a pack; recommended ones are notes (§17.1).
        if present is None and manifest.requires:
            return Readiness(manifest.name, UNEVALUABLE, (Reason(
                "capabilities-unavailable", "obscura-capd",
                "Obscura couldn't check this device's hardware (the capability service isn't answering).",
                FIX_COPY_DIAGNOSTICS),))
        capd_answered = present is not None
        present = frozenset(present or ())

        hardware, fixable = _hardware(manifest, present, vocabulary, not_on_this_device)
        runtime, inherited, runtime_remote = _runtimes(manifest, runtime_states, remote_ready)
        files, file_notes = _files(manifest, file_status)
        if capd_answered:
            recommendation_notes = _recommendations(manifest, present, vocabulary)
        elif manifest.recommends:
            recommendation_notes = ["Couldn't check for recommended hardware."]
        else:
            recommendation_notes = []
        notes = tuple(recommendation_notes + file_notes)
        reasons = tuple(hardware + runtime + files)

        if hardware:
            if manifest.remote and remote_ready:
                return Readiness(manifest.name, REMOTE, tuple(hardware),
                                 notes + ("Runs on another of your devices.",))
            state = MISSING_HARDWARE if fixable else INSUFFICIENT_HARDWARE
            return Readiness(manifest.name, state, reasons, notes)
        if runtime:
            return Readiness(manifest.name, inherited or NEEDS_PACK, reasons, notes)
        if runtime_remote:
            return Readiness(manifest.name, REMOTE, (), notes + ("Runs on another of your devices.",))
        if files:
            return Readiness(manifest.name, MISSING_FILES, reasons, notes)
        return Readiness(manifest.name, READY, (), notes)
    except Exception as error:
        report.failure("readiness._evaluate", error)
        raise


def unevaluable(name, error):
    """The fail-closed result: never Ready."""
    try:
        return Readiness(name, UNEVALUABLE, (Reason(
            "internal-error", name,
            "Obscura couldn't check this pack (" + type(error).__name__ + ").",
            FIX_COPY_DIAGNOSTICS),))
    except Exception:
        return Readiness(str(name), UNEVALUABLE)


def evaluate(manifest, present, vocabulary, runtime_states=None, file_status=None,
             not_on_this_device=False, remote_ready=False):
    """Readiness of one pack. Never raises; never Ready after an error.

    present: names capd reports present, or None if capd couldn't be asked.
    vocabulary: {name: Declaration} from obscura_capd.vocabulary.load_vocabulary.
    runtime_states: {runtime pack name: Readiness} for installed runtime packs.
    file_status: {user file id: userfiles.FileStatus}.
    """
    try:
        return _evaluate(manifest, present, vocabulary, runtime_states or {}, file_status or {},
                         not_on_this_device, remote_ready)
    except Exception as error:
        try:
            report.failure("readiness.evaluate", error)
        except Exception:
            pass
        return unevaluable(getattr(manifest, "name", "?"), error)


def evaluate_catalog(catalog, present, vocabulary, home, cache=None, not_on_this_device=(),
                     remote_ready=False, check_files=None):
    """{name: Readiness} for every pack in the catalog. Runtime packs first, so dependents
    can use their state. Each pack fails closed on its own; one bad pack never blocks the
    others."""
    try:
        check_files = check_files or userfiles.check_user_files
        results = {}
        packs = [catalog.packs[name] for name in catalog.names()]
        ordered = [pack for pack in packs if pack.manifest.runtime] + [pack for pack in packs if not pack.manifest.runtime]
        for pack in ordered:
            manifest = pack.manifest
            try:
                file_status = check_files(manifest, home, cache)
            except Exception as error:
                report.failure("readiness.evaluate_catalog", error)
                results[manifest.name] = unevaluable(manifest.name, error)
                continue
            runtimes = {name: results[name] for name in manifest.depends if name in results}
            results[manifest.name] = evaluate(manifest, present, vocabulary, runtimes, file_status,
                                              manifest.name in not_on_this_device, remote_ready)
        return results
    except Exception as error:
        report.failure("readiness.evaluate_catalog", error)
        raise
