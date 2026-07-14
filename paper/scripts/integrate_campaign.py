#!/usr/bin/env python3
"""Integrate the Isolated measurement-campaign output into paper/data (roadmap C4).

Reads the merged per-series JSONs produced by bench/wcet_campaign.py:

  <bench>/campaign_runs/session-{1,2,3}/{warm,cold,corunner_*}.json
  <bench>/campaign_runs/psweep/session-1/warm.json      (P-sweep, Isolated protocol)
  <bench>/campaign_runs/psweep/psweep_rust.json         (fresh counters at engine HEAD)
  <bench>/campaign_runs/alloc/wcet_alloc.json           (alloc pass re-verified)

and (re)writes the paper's frozen data files:

  paper/data/wcet.json          pooled warm samples (sessions concatenated in order),
                                meta.manifest = policy schema with per-session manifests
  paper/data/wcet_cold.json     pooled cold series
  paper/data/wcet_corunner.json co-runner series per mode
  paper/data/wcet_psweep.json   P-sweep timing (Isolated)
  paper/data/psweep_rust.json   P-sweep counters (engine HEAD)
  paper/data/wcet_alloc.json    allocation counts (environment-invariant; re-verified)

Guards: every merged input must carry measurement_profile "B"; iteration equality must hold
within every session and across sessions per fixture/engine; the script refuses to emit
otherwise. Re-running is idempotent (pure function of the campaign outputs).
"""

import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent  # paper/
WS = ROOT.parent
BENCH = (WS / "src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench")
RUNS = BENCH / "campaign_runs"
DATA = ROOT / "data"
SESSIONS = ["session-1", "session-2", "session-3"]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def manifest_of(doc, path):
    m = (doc.get("meta") or {}).get("manifest")
    if not m:
        raise SystemExit(f"{path}: missing meta.manifest")
    if m.get("measurement_profile") != "B":
        raise SystemExit(f"{path}: measurement_profile {m.get('measurement_profile')!r} != 'B'")
    return m


def pool_series(series_name, session_dirs):
    """Pool one series across sessions; returns (fixtures, manifests, iters_desc)."""
    docs = []
    for sd in session_dirs:
        p = sd / f"{series_name}.json"
        if not p.is_file():
            raise SystemExit(f"missing {p}")
        docs.append((p, load(p)))
    manifests = [manifest_of(d, p) for p, d in docs]

    names = sorted(docs[0][1]["fixtures"])
    pooled = {}
    for n in names:
        base = None
        per_session_median = {"cpp": [], "rust": []}
        for p, d in docs:
            fx = d["fixtures"].get(n)
            if fx is None:
                raise SystemExit(f"{p}: fixture {n} missing")
            if not fx.get("iter_match", False):
                raise SystemExit(f"{p}: {n}: iter_match is false")
            if base is None:
                base = {k: v for k, v in fx.items() if k not in ("cpp", "rust")}
                base["cpp"] = {"iteration_num": fx["cpp"]["iteration_num"],
                               "allocs_per_align": -1, "samples_ms": []}
                base["rust"] = {"iteration_num": fx["rust"]["iteration_num"],
                                "allocs_per_align": -1, "samples_ms": []}
            for eng in ("cpp", "rust"):
                if fx[eng]["iteration_num"] != base[eng]["iteration_num"]:
                    raise SystemExit(
                        f"{p}: {n}/{eng}: iteration_num "
                        f"{fx[eng]['iteration_num']} != {base[eng]['iteration_num']} "
                        "across sessions")
                base[eng]["samples_ms"].extend(fx[eng]["samples_ms"])
                per_session_median[eng].append(
                    round(statistics.median(fx[eng]["samples_ms"]), 3))
        base["per_session_median"] = per_session_median
        pooled[n] = base
    n_samples = sorted({len(f["cpp"]["samples_ms"]) for f in pooled.values()})
    iters_desc = "+".join(str(x) for x in n_samples) + " pooled across sessions"
    return pooled, manifests, iters_desc


def top_manifest(manifests, note):
    head = dict(manifests[0])
    head.update({
        "experiment_id": "campaign/pooled",
        "sessions": [m["experiment_id"] for m in manifests],
        "session_manifests": manifests,
        "pooling": "samples concatenated in session order; per-session medians retained "
                   "on each fixture for cross-session statistics",
        "notes": note,
    })
    return head


def emit(path, benchmark, meta, fixtures):
    doc = {"benchmark": benchmark, "meta": meta, "fixtures": fixtures}
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"wrote {path} ({len(fixtures)} fixtures)")


def main():
    session_dirs = [RUNS / s for s in SESSIONS]
    for sd in session_dirs:
        if not sd.is_dir():
            raise SystemExit(f"missing campaign session dir {sd}")

    # ---- warm (the paper's primary timing base) -> wcet.json ----
    warm, warm_manifests, iters_desc = pool_series("warm", session_dirs)
    meta = {
        "iters": iters_desc,
        "warmup": 10,
        "num_threads": 1,
        "clock": "steady_clock",
        "unit": "ms",
        "alloc_counting": False,
        "cache_condition": "warm",
        "note": "align loop only; map+kdtree built once per engine per fixture; "
                "Isolated configuration per plan/ndt_timing_measurement_policy.md",
        "manifest": top_manifest(
            warm_manifests,
            "primary timing base: pooled warm series of the 3-session Isolated campaign"),
    }
    emit(DATA / "wcet.json", "WCET fixture replay (Isolated campaign, pooled warm)",
         meta, warm)

    # ---- cold -> wcet_cold.json ----
    cold, cold_manifests, cold_iters = pool_series("cold", session_dirs)
    meta_cold = dict(meta)
    meta_cold.update({
        "iters": cold_iters,
        "warmup": 0,
        "cache_condition": "cold",
        "note": "between-sample software cache eviction (WCET_EVICT_BYTES; an approximation "
                "-- see the policy's Cache Measurement Policy); Isolated",
        "manifest": top_manifest(cold_manifests, "cold series of the Isolated campaign"),
    })
    emit(DATA / "wcet_cold.json", "WCET fixture replay (Isolated campaign, cold series)",
         meta_cold, cold)

    # ---- co-runner series -> wcet_corunner.json (modes nested) ----
    modes = {}
    mode_manifests = []
    for mode in ("membw", "llc", "fp"):
        fixtures, manifests, _ = pool_series(f"corunner_{mode}", session_dirs)
        modes[mode] = fixtures
        mode_manifests.extend(manifests)
    doc = {
        "benchmark": "WCET fixture replay (Isolated campaign, co-runner series)",
        "meta": {
            "unit": "ms",
            "note": "one-resource-at-a-time interference co-runner pinned to a different "
                    "physical core sharing the L3 (policy: Interference Sensitivity "
                    "Experiment); Isolated",
            "manifest": top_manifest(mode_manifests,
                                     "co-runner series of the Isolated campaign"),
        },
        "modes": modes,
    }
    (DATA / "wcet_corunner.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"wrote {DATA / 'wcet_corunner.json'} ({len(modes)} modes)")

    # ---- P-sweep (single Isolated session) -> wcet_psweep.json ----
    ps_dir = RUNS / "psweep" / "session-1"
    ps, ps_manifests, ps_iters = pool_series("warm", [ps_dir])
    meta_ps = dict(meta)
    meta_ps.update({
        "iters": ps_iters,
        "manifest": top_manifest(ps_manifests, "P-sweep under the Isolated protocol"),
        "note": "regenerated union-worst geometry per P (distinct fixture instances from "
                "the frozen search-00); Isolated",
    })
    emit(DATA / "wcet_psweep.json", "WCET P-sweep (Isolated campaign)", meta_ps, ps)

    # ---- P-sweep counters at engine HEAD ----
    src = RUNS / "psweep" / "psweep_rust.json"
    if not src.is_file():
        raise SystemExit(f"missing {src} (fresh wcet_frame output)")
    (DATA / "psweep_rust.json").write_text(src.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    print(f"wrote {DATA / 'psweep_rust.json'} (copied from campaign)")

    # ---- alloc counts (environment-invariant; re-verified under the new env) ----
    src = RUNS / "alloc" / "wcet_alloc.json"
    if not src.is_file():
        raise SystemExit(f"missing {src} (re-verified alloc pass)")
    alloc = load(src)
    alloc.setdefault("meta", {})["note"] = (
        "LD_PRELOAD interposer; allocation counts are deterministic and "
        "environment-invariant (re-verified under the Isolated environment)")
    (DATA / "wcet_alloc.json").write_text(json.dumps(alloc, indent=1), encoding="utf-8")
    print(f"wrote {DATA / 'wcet_alloc.json'}")

    print("integration complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
