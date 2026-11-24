# video4linux fixtures (task 0.2c)

Recorded udev events for video4linux nodes, used to test the `camera` capability rule
(`files/system/usr/lib/udev/rules.d/70-obscura-cap-camera.rules`) with the evaluator in
`tests/lib/udev_rules.py`. Build brief §6, 0.2c notes, and §7.

## Real and synthetic
- **`real-<label>-<kernel>.json`** are recordings made with `capture.py` on a real system
  (the VMware test VM). Acceptance tests read only real files marked **real** below.
- **`synthetic-<label>-<kernel>.json`** are written by hand in the same format to exercise
  branches that the VM can't produce (CSI, vivid if the image lacks it, hypothetical
  parents). They never satisfy an acceptance test.

## Recording
As root on the machine to record, into a directory outside any git checkout:

    sudo python3 tests/fixtures/v4l/capture.py /var/tmp/v4l-capture --label c920
    sudo python3 tests/fixtures/v4l/capture.py /var/tmp/v4l-capture --label loopback-streaming --action change --node /dev/video0

Only allowlisted udev properties and sysfs attributes are written (no serial numbers).
`fresh` is what `/usr/lib/udev/v4l_id` reports at recording time, which is what a udev
event would see. Review the files, copy the `real-*.json` ones here, and add a row for
each, with Origin `real` and the Source from `capture-info-<label>.json` (don't copy that
file).

`tests/lib/rule_crosscheck.py` checks the evaluator against real `udevadm test` on the
live nodes (VM tests C-15 to C-17).

## Files

| File | Origin | Source | Purpose |
|---|---|---|---|
