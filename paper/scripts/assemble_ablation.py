#!/usr/bin/env python3
"""Assemble paper/data/search_ablation.json from B4 run summaries + frontier timing.

Inputs (scratchpad/b4/):
  hill_default.json, hill_<seed>.json x3, random_<seed>.json x3,
  time_run1.json, time_run2.json, pareto_default_counters.json
  <campaign session dir>/merged.json  (frontier timing, Profile B)

Provenance: runs produced by realtime_ndt_scan_matcher/examples/wcet_search.rs
(WCET_SEARCH_MODE/FITNESS/JSON/PARETO_DIR), timing by bench/wcet_campaign.py
under the Profile-B environment of the main campaign.

Archived for provenance: the run JSONs it consumed were one-time B4 session artifacts
(this file's directory was the session scratchpad at run time); re-running the search
with the documented env switches regenerates them.
"""
import json
import sys
import glob
import os
import datetime

S = os.path.dirname(os.path.abspath(__file__))
ANALYTIC_NBR_MAX = 2000 * 64 * 31  # P * K_max * (N_iter+1)

def load(p):
    with open(p) as f:
        return json.load(f)

def run_summary(d):
    b = d["best"]
    return {
        "mode": d["mode"],
        "fitness": d["fitness"],
        "seed": d["seed"],
        "budget": d["budget"],
        "best": {"iter": b["iter"], "nbr": b["nbr"], "kd": b["kd"]},
        "nbr_pct_of_max": round(100.0 * b["nbr"] / ANALYTIC_NBR_MAX, 1),
        "saturation_eval": d.get("saturation_eval"),
        "pareto_size": len(d.get("pareto", [])),
    }

def main(timing_merged):
    runs = []
    for pat in ("hill_default.json", "hill_1598313837.json", "hill_305419896.json",
                "hill_3735928559.json", "random_1598313837.json",
                "random_305419896.json", "random_3735928559.json",
                "time_run1.json", "time_run2.json"):
        runs.append(run_summary(load(os.path.join(S, pat))))

    t1, t2 = load(os.path.join(S, "time_run1.json")), load(os.path.join(S, "time_run2.json"))
    time_fitness = {
        "same_seed": t1["seed"] == t2["seed"],
        "seed": t1["seed"],
        "champion_kd": [t1["best"]["kd"], t2["best"]["kd"]],
        "reproducible": t1["best"] == t2["best"],
    }

    # Global frontier over union of all counter-based evaluations:
    # search_00 + the two kd-heavier default-run archive members.
    fx_counters = load(os.path.join(S, "pareto_default_counters.json"))["fixtures"]
    frontier = []
    for stem in ("pareto_00", "pareto_01", "pareto_02"):
        fx = fx_counters[stem]
        c = fx["counters"]
        frontier.append({
            "name": "search_00" if stem == "pareto_00" else stem,
            "iter": fx["iteration_num"],
            "nbr": c["sum_neighbors"],
            "kd": c["kd_nodes_visited"],
        })

    # Frontier timing (Profile B, warm, 100 samples). Engine cells carry raw samples.
    m = load(timing_merged)
    timing = {}
    for fxname, fx in m["fixtures"].items():
        timing[fxname] = {"iter_match": fx["iter_match"]}
        for eng in ("cpp", "rust"):
            s = sorted(fx[eng]["samples_ms"])
            n = len(s)
            p50 = (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)
            timing[fxname][eng] = {
                "max_ms": round(s[-1], 3), "p50_ms": round(p50, 3), "n": n,
                "iteration_num": fx[eng]["iteration_num"],
            }

    out = {
        "meta": {
            "generated": datetime.date.today().isoformat(),
            "tool": "realtime_ndt_scan_matcher/examples/wcet_search.rs "
                    "(WCET_SEARCH_MODE/FITNESS, pareto archive) + bench/wcet_campaign.py",
            "budget_evaluations": 126,
            "analytic_nbr_max": ANALYTIC_NBR_MAX,
            "analytic_nbr_max_expr": "P=2000 x K_max=64 x N_pass=31",
            "seeds": [1592614637, 1598313837, 305419896, 3735928559],
            "timing_profile": "B (isolated core, pinned 3.2 GHz; same host/env as wcet.json campaign)",
            "timing_samples_per_cell": 100,
            "timing_anchor": "search_00 re-measured in the same series (in-session baseline; "
                             "removes the cross-session shift confound)",
        },
        "runs": runs,
        "time_fitness_ablation": time_fitness,
        "frontier": frontier,
        "frontier_timing": timing,
    }
    dst = "/autoware_workspace/paper/data/search_ablation.json"
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", dst)

if __name__ == "__main__":
    main(sys.argv[1])
