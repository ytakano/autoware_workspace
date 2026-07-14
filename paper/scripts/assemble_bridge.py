#!/usr/bin/env python3
"""Assemble paper/data/bridge.json for the Replay-to-Isolated bridge experiment.

Five inputs, both profiles:
  synthetic (search_00, legal_worst, legal_osc):
    Replay leg: bench/campaign_runs/profileA/session-1/warm.json
    B-leg: paper/data/wcet.json (pooled 3-session campaign)
  real (real_slowest, real_median):
    Replay leg: same profileA session
    B-leg: bench/campaign_runs/<b_leg_session>/warm.json  (short controlled session)

Usage: assemble_bridge.py <b_leg_warm.json>
"""
import json
import sys
import pathlib

B = pathlib.Path("/autoware_workspace/src/core/autoware_core/localization/"
                 "autoware_ndt_scan_matcher/bench")
DATA = pathlib.Path("/autoware_workspace/paper/data")
FIXTURES = ["search_00", "legal_worst", "legal_osc", "real_slowest", "real_median"]


def stats(samples):
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    return {"p50_ms": round(p50, 3), "max_ms": round(s[-1], 3), "n": n}


def main(b_leg_path):
    # C3: the Replay leg uses the matched-n pooled campaign (synthetics at n=3000, the
    # 3 x 1000 pooled run; real-frame legs copied from the original session-1 at n=100, already
    # matched to their Isolated leg), so the synthetic max comparison is same-n.
    a_doc = json.loads((B / "campaign_runs/profileA/c3_pooled/warm.json").read_text())
    b_pool = json.loads((DATA / "wcet.json").read_text())
    b_real = json.loads(pathlib.Path(b_leg_path).read_text())

    out = {"meta": {
        "profile_a_manifest": a_doc["meta"]["manifest"],
        "profile_b_pooled_manifest": b_pool["meta"]["manifest"],
        "profile_b_real_manifest": b_real["meta"]["manifest"],
        "note": ("interference inflation = production-profile latency / controlled-profile "
                 "latency (descriptive only, per the measurement policy). Synthetic legs are "
                 "matched-n pooled 3-session campaigns (n=3000) on both profiles (C3); "
                 "real-frame legs are dedicated controlled sessions (n=100); same 3.2 GHz "
                 "reference clock."),
    }, "inputs": {}}

    for fx in FIXTURES:
        a_slot = a_doc["fixtures"][fx]
        b_slot = (b_pool["fixtures"] if fx in b_pool["fixtures"] else b_real["fixtures"])[fx]
        entry = {}
        for eng in ("cpp", "rust"):
            a, b = stats(a_slot[eng]["samples_ms"]), stats(b_slot[eng]["samples_ms"])
            entry[eng] = {
                "profile_a": a, "profile_b": b,
                "inflation_p50": round(a["p50_ms"] / b["p50_ms"], 3),
                "inflation_max": round(a["max_ms"] / b["max_ms"], 3),
                "abs_diff_max_ms": round(a["max_ms"] - b["max_ms"], 3),
                "overrun_only_in_a": a["max_ms"] > 100.0 >= b["max_ms"],
            }
            if a_slot[eng]["iteration_num"] != b_slot[eng]["iteration_num"]:
                raise SystemExit(f"{fx}/{eng}: iteration mismatch across profiles")
        out["inputs"][fx] = entry

    (DATA / "bridge.json").write_text(json.dumps(out, indent=1))
    print("wrote paper/data/bridge.json")
    for fx, e in out["inputs"].items():
        print(f"  {fx:13}", {eng: (e[eng]['inflation_p50'], e[eng]['inflation_max'])
                             for eng in ('cpp', 'rust')})


if __name__ == "__main__":
    main(sys.argv[1])
