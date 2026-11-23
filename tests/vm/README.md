# VM tests: capability framework (task 0.2)

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

`sudo ./capabilities.sh all` runs C-1 and C-5 to C-9 in one go. Exit codes: 0 pass,
1 fail, 77 skipped.

With a webcam connected, check presence with `state --present camera`. With several
capabilities present: `state --present battery,camera`.

The camera alternative to USB passthrough is the `vivid` virtual driver. Fedora builds it
(`CONFIG_VIDEO_VIVID=m`), but it may live in a modules package Aurora doesn't install:
check `modinfo vivid` in the VM.
