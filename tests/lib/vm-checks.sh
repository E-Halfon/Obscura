# shellcheck shell=bash
# Camera Obscura: preconditions shared by the VM test scripts (tests/vm/*.sh).

# warn_auto_update: Universal Blue's uupd.timer stages new images (and Flatpak, brew and
# distrobox updates) on its own schedule. During testing that can swap the image under
# test, and a failed uupd.service run (as with a denied Flatpak user update on the 0.2b
# image) fails every "no failed units" check. A warning only, never a failure or a skip.
# Whether Obscura keeps uupd is an open decision (build brief §6, Stage 0).
warn_auto_update() {
    local enabled active
    if ! systemctl cat uupd.timer >/dev/null 2>&1; then
        return 0
    fi
    enabled=$(systemctl is-enabled uupd.timer 2>/dev/null || true)
    active=$(systemctl is-active uupd.timer 2>/dev/null || true)
    if [ "$enabled" = enabled ] || [ "$active" = active ]; then
        echo "WARNING: uupd.timer is $enabled/$active: the VM may auto-update (stage a new image) during testing."
        echo "         Disable it in test VMs: sudo systemctl disable --now uupd.timer"
        echo "         (and sudo systemctl reset-failed uupd.service if an earlier run failed)"
    fi
    return 0
}
