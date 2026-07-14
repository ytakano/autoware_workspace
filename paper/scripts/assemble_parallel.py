#!/usr/bin/env python3
"""Assemble paper/data/parallel.json — the C8 parallel-feasibility campaign (plan/paper_fix2.md).

Reads the per-engine, per-k cells produced by bench/run_c8.sh (a directory of
<fixture>_k<k>_<engine>.json fixture-replay outputs) plus a calib.txt (fixed-work throttle
guard) and emits a single merged JSON with a manifest. Both engines run on the isolated cores
2,4,6,8 with per-worker pinning (OpenMP GOMP_CPU_AFFINITY; rayon NDT_PIN_RAYON_WORKERS +
init_thread_pool). Speedups are computed WITHIN this boot/configuration (k=1 baseline), never
against the frozen serial Isolated campaign (a different isolation set).

Guard: the Rust engine's iteration count must be identical across k for every fixture (the
parallel backend is order-preserving and bit-identical to serial; k only changes wall time).

Usage: assemble_parallel.py <c8_dir> <engine_commit>
"""
import json
import pathlib
import sys

FIXTURES = ["search_00", "legal_worst", "legal_osc"]
KS = [1, 2, 4]


def stats(samples):
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    return {"p50_ms": round(p50, 3), "max_ms": round(s[-1], 3), "n": n}


def main(c8_dir, commit):
    d = pathlib.Path(c8_dir)
    calib = (d / "calib.txt").read_text().splitlines()
    cb = next(int(x.split()[1]) for x in calib if x.startswith("calib_before"))
    ca = next(int(x.split()[1]) for x in calib if x.startswith("calib_after"))
    inputs = {}
    for fx in FIXTURES:
        cells = {}
        rust_iters, cpp_iters = set(), set()
        for k in KS:
            row = {}
            for e in ("cpp", "rust"):
                doc = json.loads((d / f"{fx}_k{k}_{e}.json").read_text())
                cell = doc["fixtures"][fx][e]
                (rust_iters if e == "rust" else cpp_iters).add(cell["iteration_num"])
                row[e] = stats(cell["samples_ms"]) | {"iteration_num": cell["iteration_num"]}
            cells[str(k)] = row
        if len(rust_iters) != 1:
            raise SystemExit(
                f"parallel: Rust iteration count varies with k on {fx} ({rust_iters}) -- "
                "the parallel backend is meant to be bit-identical to serial; investigate")
        # Speedups within this configuration (k=1 baseline).
        for e in ("cpp", "rust"):
            base = cells["1"][e]["p50_ms"]
            base_mx = cells["1"][e]["max_ms"]
            for k in KS:
                cells[str(k)][e]["speedup_p50"] = round(base / cells[str(k)][e]["p50_ms"], 3)
                cells[str(k)][e]["speedup_max"] = round(base_mx / cells[str(k)][e]["max_ms"], 3)
        inputs[fx] = cells
    out = {
        "meta": {
            "experiment": "C8 parallel feasibility (plan/paper_fix2.md)",
            "engine_commit": commit,
            "calib_before_ns": cb,
            "calib_after_ns": ca,
            "calib_drift_pct": round(100.0 * (ca - cb) / cb, 2),
            "cmdline_isolation": "isolcpus=2-9 nohz_full=2-9 rcu_nocbs=2-9; SMT siblings "
            "3,5,7,9 offline; governor performance, 3.2 GHz",
            "cores": {"1": "2", "2": "2,4", "4": "2,4,6,8"},
            "pinning": "C++: OMP_NUM_THREADS + GOMP_CPU_AFFINITY; Rust: RAYON_NUM_THREADS + "
            "NDT_PIN_RAYON_WORKERS (init_thread_pool pins worker i to the i-th cpuset CPU)",
            "note": "Throughput feasibility, NOT a multi-core WCET analysis: the serial engine "
            "remains the deterministic baseline. Speedups are within this boot (k=1 baseline); "
            "not comparable to the frozen serial Isolated series (a different isolation set). Rust "
            "iteration counts are k-invariant (parallel backend bit-identical to serial).",
        },
        "inputs": inputs,
    }
    (pathlib.Path("/autoware_workspace/paper/data") / "parallel.json").write_text(
        json.dumps(out, indent=1))
    print("wrote paper/data/parallel.json")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "?")
