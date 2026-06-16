# Handoff: measure typing latency — XD75 (QMK/USB) vs Cascade (ZMK/BLE)

## Mission

Objectively compare input latency / smoothness between two keyboards and
determine why the **Cascade** feels more sluggish than the **XD75**, then
verify whether the firmware change already made (disabling BLE slave latency)
helps.

You are picking up a hardware-keyboard tuning investigation. Deliver a short
report with numbers, a verdict, and a recommendation.

## Background (what we already know)

| | XD75 | Cascade |
|---|---|---|
| Firmware | QMK | ZMK |
| Connection | **Wired USB, 1000 Hz** (`USB_POLLING_INTERVAL_MS 1`) | **Bluetooth LE** (nice!nano nRF52840) |
| Form | unibody ortho 5x15 | unibody (single controller, not a split) |
| NKRO | on | on |
| Debounce | 5 ms | 5 ms |
| VID:PID | `0x7844:0x7575` | unknown — enumerate it |

Findings so far in the investigation:

1. **Tap-hold settings are NOT the cause of the general feel.** Normal letters
   on both boards are plain keys that fire instantly. Tap-hold flavor /
   tapping-term only affect the dual-role keys (Tab, Z, X, the thumb cluster).
   The Cascade keymap was already aligned to the XD75 feel
   (`flavor=tap-preferred`, `tapping-term-ms=150`, `quick-tap-ms=0`).
2. **Primary suspect: the BLE link.** Wired USB = ~1 ms constant. BLE = a
   7.5-15 ms connection interval with jitter.
3. **Specific root cause identified:** ZMK defaults
   `CONFIG_BT_PERIPHERAL_PREF_LATENCY = 30` (slave latency), letting the
   keyboard skip up to ~30 connection intervals when idle → wake-up lag after
   short pauses. A fix was committed:
   `CONFIG_BT_PERIPHERAL_PREF_LATENCY=0` in `config/melody-one.conf`.
4. Secondary, keymap-level: the **Space** key is plain and in no combo, but it
   sits between thumb hold-tap keys; rolling from a hold-tap into Space can be
   briefly queued by ZMK until the hold-tap resolves. Minor, roll-specific.

## What to measure

Use `latency_probe.py` (same folder). It timestamps raw HID input-report
arrivals and reports inter-arrival interval stats + a histogram. This is a
pure-software proxy for "smoothness": it captures the BLE connection-interval
quantisation, jitter, and post-pause gaps. It does **not** measure absolute
end-to-end latency (see "Stretch goal").

### Steps

1. `pip install hidapi`. On macOS grant **Input Monitoring** permission to the
   terminal / Codex process (System Settings → Privacy & Security).
2. `python3 latency_probe.py list` → find each keyboard's VID:PID (rows marked
   `<- keyboard`). XD75 should be `0x7844:0x7575`.
3. **Run A — continuous fast typing (20 s each):**
   ```
   python3 latency_probe.py capture --vid 0x7844 --pid 0x7575 --seconds 20 --label xd75 --out xd75_A.json
   python3 latency_probe.py capture --vid 0xXXXX --pid 0xXXXX --seconds 20 --label cascade --out cascade_A.json
   python3 latency_probe.py compare xd75_A.json cascade_A.json
   ```
4. **Run B — wake-up test (20 s each):** type a burst, pause ~2 s, repeat.
   This stresses BLE slave latency. Capture the Cascade **twice**: once on the
   OLD firmware (latency=30) and once on the NEW firmware (latency=0), label
   them `cascade_old` / `cascade_new`, and compare.
   - Old firmware: flash an earlier build (commit `0cbb55a` or before).
   - New firmware: current `firmware-build/melody-one-nice_nano_v2-zmk.uf2`
     (commit `705d8c7`).

## Expected results / acceptance criteria

- **XD75:** `min_ms`/`median_ms` ≈ 1, low `stdev_ms`, histogram concentrated in
  the 1-4 ms bins.
- **Cascade (BLE):** `median_ms` in the ~8-15 ms range, higher `stdev_ms`,
  histogram clustered around the connection interval; `p99_ms`/`max_ms` much
  larger than median when slave-latency gaps occur.
- **Fix confirmation:** Cascade `cascade_new` should show smaller
  `p99_ms`/`max_ms` (fewer/smaller wake-up gaps) than `cascade_old` in Run B.
  Median may stay ~connection-interval — that part is BLE-inherent.

## Report back

1. The `compare` tables for Run A and Run B (old vs new firmware).
2. Verdict: how much of the "sluggish" feel is BLE-inherent (connection
   interval) vs the slave-latency gap that the firmware fix addresses.
3. Recommendation: e.g. keep `LATENCY=0`; optionally also pin the interval
   (`CONFIG_BT_PERIPHERAL_PREF_MIN_INT=6`, `..._MAX_INT=6`) for a fixed 7.5 ms;
   or accept that wired-USB-1000 Hz smoothness is not reachable over BLE and,
   if it matters, type wired (add `&out OUT_TOG`).

## Stretch goal — absolute latency (needs hardware)

Pure software cannot measure key-contact → on-screen latency. If hardware is
available: film key + screen with a 240 fps phone camera and count frames, or
use a microcontroller (e.g. a Pi Pico) wired across one switch that closes the
contact and timestamps the resulting HID report on the host. Report the delta
between USB and BLE. Optional; the jitter probe above already explains the
perceived difference.

## Constraints

- Do not change the keymap logic. Firmware config edits are limited to BLE
  connection parameters in `config/melody-one.conf`, and only if Run B shows
  they help.
- Builds run via GitHub Actions on the fork `raphaelmosaic/melody-1` (push to
  `main` triggers a build; download the `firmware` artifact). Do not push
  without the owner's go-ahead.
