# video4linux fixtures (task 0.2c)

Recorded udev events for video4linux nodes, used to test the `camera` capability rule
(`files/system/usr/lib/udev/rules.d/70-obscura-cap-camera.rules`) with the evaluator in
`tests/lib/udev_rules.py`. Build brief §6, 0.2c notes, and §7.

## Real and synthetic
- **`real-<label>-<kernel>.json`** are recordings made with `capture.py` on a real system
  (the VMware test VM). Acceptance tests read only real files marked **real** below.
- **`synthetic-<label>-<kernel>.json`** are written by hand in the same format to exercise
  branches that the VM can't produce (CSI, IR-only, hypothetical parents). They never
  satisfy an acceptance test.

## Recording
As root on the machine to record, into a directory outside any git checkout:

    sudo python3 tests/fixtures/v4l/capture.py /var/tmp/v4l-capture --label c920
    sudo python3 tests/fixtures/v4l/capture.py /var/tmp/v4l-capture --label loopback-streaming --action change --node /dev/video0

Only allowlisted udev properties and sysfs attributes are written (no serial numbers).
`fresh` is what `/usr/lib/udev/v4l_id` reports at recording time, which is what a udev
event would see. Review the files, copy the `real-*.json` ones here, and add a row for
each, with Origin `real` and the Source from `capture-info-<label>.json` (don't copy that
file).

`tests/lib/rule_crosscheck.py` checks the evaluator against real udev on the live nodes
(VM tests C-15 to C-17): it triggers an event and reads the database back. It doesn't use
`udevadm test`, which on systemd 262 skips `IMPORT{program}` and so never sees
`ID_V4L_CAPABILITIES`.

### Stale database
`properties` is udev's database, `fresh` is what an event would see now. They differ when
a node's capabilities changed without an event: v4l2loopback 0.15.4 sent no uevent when
ffmpeg started or stopped streaming (VM recon, 2026-11-24), so after a forced change
event during streaming the database kept `:capture:` (and, under the 0.2b rule, the
systemd tag) long after the stream stopped. `real-c920-video0.json` is that state, kept on
purpose: the loopback must not count from either value.

## Files

| File | Origin | Source | Purpose |
|---|---|---|---|
| `real-c920-video0.json` | real | VM, 0.2b image, udev 262, v4l2loopback 0.15.4, 2026-11-24 | OBS loopback with a **stale database** (db `:capture:`, fresh `:video_output:`), recorded beside the C920; must not count |
| `real-c920-video1.json` | real | same | Logitech C920 capture node (uvcvideo); counts |
| `real-c920-video2.json` | real | same | C920 metadata node (`:`); must not count |
| `real-loopback-streaming-video0.json` | real | same | OBS loopback while ffmpeg streams into it, after a change event (`:capture:`); the key negative test |
| `real-vm-idle-video0.json` | real | same | OBS loopback idle (`:video_output:`) |
| `real-vivid-video1.json` | real | same | vivid capture node, platform parent bound to `vivid` (`:capture:audio:tuner:`); must not count |
| `real-vivid-video2.json` | real | same | vivid video output node |
| `real-vivid-video3.json` | real | same | vivid metadata capture node |
| `real-vivid-video4.json` | real | same | vivid metadata output node |
| `synthetic-loopback-nocaps-video0.json` | synthetic | hand-written | v4l2loopback with exclusive_caps=0 (`:video_output:capture:`) |
| `synthetic-loopback-parent-video0.json` | synthetic | hand-written | a hypothetical v4l2loopback that registers a platform parent: only the DRIVERS line keeps it out |
| `synthetic-ipu6-video0.json` | synthetic | hand-written | Intel IPU6 isys CSI capture node (PCI, auxiliary device); counts |
| `synthetic-ir-only-video0.json` | synthetic | hand-written | an IR-only UVC sensor; counts for now (ARCHITECTURE.md §11) |
