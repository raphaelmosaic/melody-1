#!/usr/bin/env python3
"""
Keyboard input-latency / jitter probe (macOS / Linux).

WHAT THIS MEASURES (and what it does not)
-----------------------------------------
It records the arrival timestamps of raw HID *input reports* coming from a
keyboard and analyses their inter-arrival timing. This directly exposes the
real difference between the two boards under test:

  * XD75   -> wired USB, 1000 Hz polling  -> reports quantised to ~1 ms,
             near-zero jitter, smooth/continuous interval distribution.
  * Cascade-> BLE (nice!nano / ZMK)        -> reports quantised to the BLE
             connection interval (~7.5-15 ms) with visible jitter; ZMK's
             slave-latency lets it skip intervals when idle, adding a
             wake-up gap after pauses.

It does NOT measure absolute end-to-end latency (key contact -> pixel on
screen). True absolute latency needs a hardware reference (a high-speed
camera at 240/1000 fps filming key + screen, or a microcontroller that
presses the switch and timestamps the USB/HID report). That is out of scope
for a pure-software probe. Inter-report cadence + jitter is, however, exactly
what "smoothness" subjectively is, so it is the right software proxy.

REQUIREMENTS
------------
    pip install hidapi
    # macOS: grant the terminal/Codex process "Input Monitoring" permission
    # (System Settings > Privacy & Security > Input Monitoring).

USAGE
-----
    # 1. List candidate keyboard HID interfaces:
    python3 latency_probe.py list

    # 2. Capture ~20 s while you type FAST on the target board.
    #    Pick the device by vendor:product (hex) shown in `list`.
    python3 latency_probe.py capture --vid 0x7844 --pid 0x7575 \
        --seconds 20 --label xd75 --out xd75.json

    python3 latency_probe.py capture --vid 0xXXXX --pid 0xXXXX \
        --seconds 20 --label cascade --out cascade.json

    # 3. Compare two captures:
    python3 latency_probe.py compare xd75.json cascade.json

TEST PROTOCOL (run identically on both boards)
----------------------------------------------
  A. Continuous fast typing: type the same paragraph as fast as you can for
     the whole capture window. -> reveals the interval floor + jitter.
  B. Wake-up test: during a SECOND capture, type a burst, pause ~2 s, type a
     burst, repeat. -> the post-pause gap exposes BLE slave-latency. Run this
     on the Cascade with the OLD firmware (LATENCY=30) and the NEW firmware
     (LATENCY=0) to confirm the fix.
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter


def _require_hid():
    try:
        import hid  # type: ignore
        return hid
    except Exception:
        sys.exit("Missing dependency. Install with:  pip install hidapi")


def cmd_list(_args):
    hid = _require_hid()
    rows = []
    for d in hid.enumerate():
        rows.append(
            (
                d.get("vendor_id", 0),
                d.get("product_id", 0),
                d.get("interface_number", -1),
                d.get("usage_page", 0),
                d.get("usage", 0),
                (d.get("manufacturer_string") or "").strip(),
                (d.get("product_string") or "").strip(),
                d.get("path"),
            )
        )
    # Keyboards report usage_page 0x01 (Generic Desktop), usage 0x06 (Keyboard).
    print(f"{'VID':>6} {'PID':>6} {'if':>3} {'uPage':>6} {'usage':>5}  product")
    print("-" * 72)
    for vid, pid, iface, up, us, man, prod, _path in sorted(rows):
        flag = " <- keyboard" if (up == 0x01 and us == 0x06) else ""
        print(f"0x{vid:04x} 0x{pid:04x} {iface:3d} 0x{up:04x} 0x{us:04x}  {man} {prod}{flag}")
    print(
        "\nPick the row marked '<- keyboard'. Use its VID/PID with `capture`.\n"
        "If several interfaces share a VID/PID, capture targets the keyboard one."
    )


def _open_keyboard(hid, vid, pid):
    """Open the HID interface that actually delivers keyboard input reports."""
    best_path = None
    for d in hid.enumerate(vid, pid):
        if d.get("usage_page") == 0x01 and d.get("usage") == 0x06:
            best_path = d.get("path")
            break
    dev = hid.Device(path=best_path) if best_path else hid.Device(vid, pid)
    return dev


def cmd_capture(args):
    hid = _require_hid()
    dev = _open_keyboard(hid, args.vid, args.pid)
    dev.nonblocking = True

    print(
        f"[{args.label}] Capturing {args.seconds}s of HID reports — TYPE NOW (fast).",
        flush=True,
    )
    stamps_ns = []
    t0 = time.perf_counter()
    deadline = t0 + args.seconds
    try:
        while time.perf_counter() < deadline:
            data = dev.read(64)  # non-blocking: [] when nothing pending
            if data:
                stamps_ns.append(time.perf_counter_ns())
    finally:
        dev.close()

    if len(stamps_ns) < 5:
        sys.exit(
            f"Only {len(stamps_ns)} reports captured. Did you type? On macOS, grant "
            "Input Monitoring permission to the terminal/Codex process."
        )

    deltas_ms = [
        (b - a) / 1_000_000 for a, b in zip(stamps_ns, stamps_ns[1:])
    ]
    result = {
        "label": args.label,
        "seconds": args.seconds,
        "report_count": len(stamps_ns),
        "deltas_ms": deltas_ms,
        "stats": _stats(deltas_ms),
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[{args.label}] {len(stamps_ns)} reports -> {args.out}")
    _print_stats(args.label, result["stats"], deltas_ms)


def _stats(deltas):
    s = sorted(deltas)
    n = len(s)

    def pct(p):
        return s[min(n - 1, int(p / 100 * n))]

    return {
        "n_intervals": n,
        "min_ms": round(s[0], 3),
        "median_ms": round(statistics.median(s), 3),
        "mean_ms": round(statistics.fmean(s), 3),
        "p95_ms": round(pct(95), 3),
        "p99_ms": round(pct(99), 3),
        "max_ms": round(s[-1], 3),
        "stdev_ms": round(statistics.pstdev(s), 3),
    }


def _histogram(deltas, edges=(1, 2, 4, 8, 12, 16, 24, 32, 50, 100, 250, 1e9)):
    c = Counter()
    for d in deltas:
        for e in edges:
            if d <= e:
                c[e] += 1
                break
    lines, lo = [], 0
    for e in edges:
        hi = "inf" if e > 1e8 else f"{e:g}"
        bar = "#" * c[e]
        lines.append(f"  {lo:>4}-{hi:>4} ms | {c[e]:4d} {bar}")
        lo = e if e <= 1e8 else lo
    return "\n".join(lines)


def _print_stats(label, st, deltas):
    print(f"\n== {label}: inter-report interval ==")
    for k in ("min_ms", "median_ms", "mean_ms", "p95_ms", "p99_ms", "max_ms", "stdev_ms"):
        print(f"  {k:10s} {st[k]}")
    print("  histogram (lower & tighter = snappier, smoother):")
    print(_histogram(deltas))


def cmd_compare(args):
    a = json.load(open(args.a))
    b = json.load(open(args.b))
    print(f"{'metric':12s} {a['label']:>14s} {b['label']:>14s}")
    print("-" * 44)
    for k in ("min_ms", "median_ms", "mean_ms", "p95_ms", "p99_ms", "max_ms", "stdev_ms"):
        print(f"{k:12s} {a['stats'][k]:>14} {b['stats'][k]:>14}")
    print(
        "\nInterpretation:\n"
        "  * min_ms/median_ms near 1 and low stdev  -> wired-like, smooth.\n"
        "  * median ~8-15 ms + high stdev + clusters -> BLE connection interval.\n"
        "  * large p99_ms/max_ms vs median           -> wake-up gaps (slave latency).\n"
        "  Re-run the Cascade before/after the LATENCY=0 firmware: p99_ms/max_ms\n"
        "  should drop noticeably if slave latency was the cause."
    )


def main():
    p = argparse.ArgumentParser(description="Keyboard HID report jitter probe")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list HID devices").set_defaults(func=cmd_list)

    c = sub.add_parser("capture", help="capture report timing")
    c.add_argument("--vid", type=lambda x: int(x, 0), required=True)
    c.add_argument("--pid", type=lambda x: int(x, 0), required=True)
    c.add_argument("--seconds", type=float, default=20.0)
    c.add_argument("--label", default="device")
    c.add_argument("--out", default="capture.json")
    c.set_defaults(func=cmd_capture)

    cm = sub.add_parser("compare", help="compare two captures")
    cm.add_argument("a")
    cm.add_argument("b")
    cm.set_defaults(func=cmd_compare)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
