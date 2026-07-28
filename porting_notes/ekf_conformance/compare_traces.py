#!/usr/bin/env python3
"""Fail-closed differential comparator for the EKF port (contract: ekf_port_contract.md).

Compares a C++ `ekf_replay` trace CSV against the Rust `examples/ekf_replay.rs` trace:
  - decisions exact: event kind + order, timestamps, delay_step, all gate booleans;
  - f64 chains: |a-b| <= rel_tol * max(|a|,|b|) + scale_floor, with
    scale_floor = abs_floor_scale * S_row and S_row = max(|x0|, |x1|, 1): the shared
    covariance recursion couples every field to the dominant position magnitude, so
    cancellation-formed fields (innovations, wz, mahalanobis) inherit absolute rounding
    drift at that scale (contract Section 3; NaN == NaN, Inf by sign);
  - yaw-like fields: the difference is wrapped to (-pi, pi] before the tolerance check.

Any unknown column, missing column, row-count mismatch, or unparseable value is a failure
(never an implicit ignore). Exit code 0 only on full agreement.

Usage:
  compare_traces.py cpp.csv rust.csv [--rel-tol 1e-9] [--abs-floor-scale 1e-12] [--yaw-abs 1e-9]
  compare_traces.py --self-test        # mutation audit of the comparator itself
"""

import argparse
import math
import sys

EXPECTED_HEADER = (
    "current_ns,measurement_ns,delay_s,delay_step,obs_x,obs_y,obs_yaw,"
    "pred_x,pred_y,pred_yaw,innovation_x,innovation_y,innovation_yaw,"
    "mahalanobis,delay_gate,mahalanobis_gate,accepted,post_x,post_y,post_yaw,"
    "event,x0,x1,x2,x3,x4,x5,p0,p1,p2,p3,p4,p5,z,roll,pitch,z_var,roll_var,pitch_var"
)
COLUMNS = EXPECTED_HEADER.split(",")

EXACT_INT = {"current_ns", "measurement_ns", "delay_step",
             "delay_gate", "mahalanobis_gate", "accepted"}
EXACT_STR = {"event"}
YAW_LIKE = {"obs_yaw", "pred_yaw", "innovation_yaw", "post_yaw", "x2", "roll", "pitch"}
# Every remaining column is a plain f64 chain. This enumeration is the fail-closed contract:
# a column in neither set below is a configuration error.
NUMERIC = set(COLUMNS) - EXACT_INT - EXACT_STR - YAW_LIKE
assert NUMERIC | EXACT_INT | EXACT_STR | YAW_LIKE == set(COLUMNS)


def wrap_angle(a):
    return math.atan2(math.sin(a), math.cos(a))


def num_equal(a, b, rel_tol, scale_floor, wrapped, yaw_abs):
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    if wrapped:
        d = abs(wrap_angle(a - b))
        return d <= yaw_abs + rel_tol * max(abs(a), abs(b))
    return abs(a - b) <= scale_floor + rel_tol * max(abs(a), abs(b))


def rel_err(a, b):
    if math.isnan(a) or math.isnan(b) or math.isinf(a) or math.isinf(b):
        return 0.0
    denom = max(abs(a), abs(b))
    return 0.0 if denom == 0.0 else abs(a - b) / denom


def load(path):
    with open(path) as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    if not lines:
        raise SystemExit(f"{path}: empty trace")
    if lines[0] != EXPECTED_HEADER:
        raise SystemExit(f"{path}: header mismatch (fail-closed):\n got {lines[0]}")
    rows = []
    for i, ln in enumerate(lines[1:], start=2):
        vals = ln.split(",")
        if len(vals) != len(COLUMNS):
            raise SystemExit(f"{path}:{i}: expected {len(COLUMNS)} columns, got {len(vals)}")
        rows.append(dict(zip(COLUMNS, vals)))
    return rows


def row_scale(row):
    """Dominant coupled state magnitude: position (x0, x1), floored at 1 (angle scale)."""
    try:
        return max(abs(float(row["x0"])), abs(float(row["x1"])), 1.0)
    except ValueError:
        return 1.0


def compare(cpp_rows, rust_rows, rel_tol, abs_floor_scale, yaw_abs, label=""):
    failures = []
    worst = {}  # field -> (rel_err, row_idx)
    if len(cpp_rows) != len(rust_rows):
        failures.append((0, "row_count", f"cpp={len(cpp_rows)} rust={len(rust_rows)}"))
        n = min(len(cpp_rows), len(rust_rows))
    else:
        n = len(cpp_rows)

    seen_events = set()
    for i in range(n):
        c, r = cpp_rows[i], rust_rows[i]
        seen_events.add(c["event"])
        scale_floor = abs_floor_scale * max(row_scale(c), row_scale(r))
        for col in COLUMNS:
            cv, rv = c[col], r[col]
            if col in EXACT_STR:
                if cv != rv:
                    failures.append((i, col, f"{cv!r} != {rv!r}"))
                continue
            if col in EXACT_INT:
                try:
                    ok = int(cv) == int(rv)
                except ValueError:
                    ok = False
                if not ok:
                    failures.append((i, col, f"{cv} != {rv}"))
                continue
            try:
                a, b = float(cv), float(rv)
            except ValueError:
                failures.append((i, col, f"unparseable: {cv!r} / {rv!r}"))
                continue
            wrapped = col in YAW_LIKE
            if not num_equal(a, b, rel_tol, scale_floor, wrapped, yaw_abs):
                failures.append((i, col, f"{a!r} vs {b!r} (rel={rel_err(a, b):.3e})"))
            e = rel_err(a, b)
            if e > worst.get(col, (0.0, -1))[0]:
                worst[col] = (e, i)
    return failures, worst, seen_events


def report(name, failures, worst, seen_events, n_rows):
    print(f"== {name}: {n_rows} rows, events seen: {sorted(seen_events)}")
    if worst:
        top = sorted(worst.items(), key=lambda kv: -kv[1][0])[:5]
        for col, (e, i) in top:
            print(f"   max rel {col:16s} {e:.3e} (row {i})")
        overall = max(e for e, _ in worst.values())
        print(f"   overall max rel: {overall:.3e}")
    if failures:
        by_field = {}
        for i, col, msg in failures:
            by_field.setdefault(col, []).append((i, msg))
        print(f"   FAIL: {len(failures)} mismatches")
        for col, items in sorted(by_field.items()):
            print(f"     {col}: {len(items)} (first at row {items[0][0]}: {items[0][1]})")
    else:
        print("   PASS")
    return not failures


def self_test(rel_tol, abs_floor_scale, yaw_abs):
    """Mutation audit: every observed field class must be able to fail the comparator."""
    base = {c: "0" for c in COLUMNS}
    base.update({"event": "pose", "current_ns": "100", "measurement_ns": "90",
                 "delay_s": "0.01", "delay_step": "1", "delay_gate": "1",
                 "mahalanobis_gate": "1", "accepted": "1", "obs_x": "1.0",
                 "obs_yaw": "3.14", "mahalanobis": "nan", "x2": "3.14"})
    ok = True

    def run(mut, must_fail, desc):
        nonlocal ok
        rows_a = [dict(base)]
        rows_b = [dict(base)]
        rows_b[0].update(mut)
        failures, _, _ = compare(rows_a, rows_b, rel_tol, abs_floor_scale, yaw_abs)
        failed = bool(failures)
        if failed != must_fail:
            print(f"self-test FAILED: {desc} (expected {'fail' if must_fail else 'pass'})")
            ok = False

    run({}, False, "identical rows pass")
    run({"event": "twist"}, True, "event kind change must fail")
    run({"accepted": "0"}, True, "accepted flip must fail")
    run({"delay_gate": "0"}, True, "delay gate flip must fail")
    run({"mahalanobis_gate": "0"}, True, "mahalanobis gate flip must fail")
    run({"delay_step": "2"}, True, "delay_step change must fail")
    run({"current_ns": "101"}, True, "current_ns change must fail")
    run({"measurement_ns": "91"}, True, "measurement_ns change must fail")
    run({"obs_x": "1.001"}, True, "numeric change above tol must fail")
    run({"obs_x": repr(1.0 * (1 + 1e-12))}, False, "numeric change below tol passes")
    run({"mahalanobis": "0.5"}, True, "NaN vs number must fail")
    run({"obs_yaw": repr(3.14 - 2 * math.pi)}, False, "yaw wrap-equal passes")
    run({"x2": repr(3.14 - 2 * math.pi)}, False, "state yaw wrap-equal passes")
    run({"obs_yaw": "3.10"}, True, "yaw change above tol must fail")
    run({"p0": "1e-9"}, True, "P diagonal change must fail")
    run({"z_var": "1e-9"}, True, "1D filter var change must fail")
    # Row-scale floor: at position magnitude 1e5, sub-ulp-drift differences pass and
    # semantic-size differences still fail.
    big = dict(base, x0="66000.0", x1="43000.0", obs_x="66000.0")
    rows_a = [dict(big)]
    rows_b = [dict(big, x5="5e-8")]  # |diff| = 5e-8 < 1e-12 * 66000 = 6.6e-8
    failures, _, _ = compare(rows_a, rows_b, rel_tol, abs_floor_scale, yaw_abs)
    if failures:
        print("self-test FAILED: sub-scale-floor wz drift should pass")
        ok = False
    rows_b = [dict(big, x5="1e-3")]
    failures, _, _ = compare(rows_a, rows_b, rel_tol, abs_floor_scale, yaw_abs)
    if not failures:
        print("self-test FAILED: semantic wz change must fail")
        ok = False
    # row-order / count sensitivity
    rows_a = [dict(base), dict(base, event="twist", obs_yaw="nan", x2="0")]
    rows_b = list(reversed(rows_a))
    failures, _, _ = compare(rows_a, rows_b, rel_tol, abs_floor_scale, yaw_abs)
    if not failures:
        print("self-test FAILED: event reorder must fail")
        ok = False
    failures, _, _ = compare(rows_a, rows_a[:1], rel_tol, abs_floor_scale, yaw_abs)
    if not failures:
        print("self-test FAILED: row-count mismatch must fail")
        ok = False

    print("self-test:", "PASS" if ok else "FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cpp", nargs="?")
    ap.add_argument("rust", nargs="?")
    ap.add_argument("--rel-tol", type=float, default=1e-9)
    ap.add_argument("--abs-floor-scale", type=float, default=1e-12)
    ap.add_argument("--yaw-abs", type=float, default=1e-9)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if self_test(args.rel_tol, args.abs_floor_scale, args.yaw_abs) else 1)
    if not args.cpp or not args.rust:
        ap.error("cpp and rust trace paths required (or --self-test)")

    cpp_rows = load(args.cpp)
    rust_rows = load(args.rust)
    failures, worst, seen = compare(cpp_rows, rust_rows,
                                    args.rel_tol, args.abs_floor_scale, args.yaw_abs)
    ok = report(f"{args.cpp} vs {args.rust}", failures, worst, seen, len(cpp_rows))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
