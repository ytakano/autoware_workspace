#!/usr/bin/env python3
"""Assemble paper/data/bridge.json for the Replay-to-Isolated bridge experiment.

Five inputs, both measurement configurations:
  synthetic (search_00, legal_worst, legal_osc):
    Replay leg: bench/campaign_runs/profileA/session-1/warm.json
    Isolated leg: campaign_runs/session-{1,2,3}/warm.json (pooled campaign)
  real (real_slowest, real_median):
    Replay leg: same profileA session
    Isolated leg: a dedicated warm.json (short controlled session)

Usage: assemble_bridge.py <isolated_real_warm.json>
"""
import json
import pathlib
import sys

B = pathlib.Path("/autoware_workspace/src/core/autoware_core/localization/"
                 "autoware_ndt_scan_matcher/bench")
DATA = pathlib.Path("/autoware_workspace/paper/data")
FIXTURES = ["search_00", "legal_worst", "legal_osc", "real_slowest", "real_median"]


def stats(samples):
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    return {"p50_ms": round(p50, 3), "max_ms": round(s[-1], 3), "n": n}


def main(isolated_real_path):
    # The Replay leg uses a matched-size pooled campaign: synthetic inputs have 3000
    # measurements and real-frame inputs have 100, matching their Isolated legs.
    replay_doc = json.loads((B / "campaign_runs/profileA/c3_pooled/warm.json").read_text())
    isolated_docs = [
        json.loads((B / f"campaign_runs/session-{index}/warm.json").read_text())
        for index in (1, 2, 3)
    ]
    isolated_real = json.loads(pathlib.Path(isolated_real_path).read_text())

    isolated_hashes = {
        doc["meta"]["manifest"]["binary_hash"] for doc in isolated_docs
    }
    if len(isolated_hashes) != 1:
        raise SystemExit("Isolated synthetic sessions use different binaries")

    isolated_pooled_manifest = dict(isolated_docs[0]["meta"]["manifest"])
    isolated_pooled_manifest["experiment_id"] = "bridge-isolated/pooled"
    isolated_pooled_manifest["sessions"] = [
        doc["meta"]["manifest"]["experiment_id"] for doc in isolated_docs
    ]

    out = {"meta": {
        "replay_manifest": replay_doc["meta"]["manifest"],
        "isolated_pooled_manifest": isolated_pooled_manifest,
        "isolated_real_manifest": isolated_real["meta"]["manifest"],
        "note": ("inflation = Replay latency / Isolated latency; the ratio is descriptive. "
                 "Synthetic legs are matched-size pooled three-session campaigns (n=3000) "
                 "in both configurations; real-frame legs are dedicated matched-size "
                 "sessions (n=100); all runs use the same 3.2 GHz "
                 "reference clock."),
    }, "inputs": {}}

    for fx in FIXTURES:
        replay_slot = replay_doc["fixtures"][fx]
        if fx in isolated_docs[0]["fixtures"]:
            isolated_slot = {}
            for eng in ("cpp", "rust"):
                iteration_counts = {
                    doc["fixtures"][fx][eng]["iteration_num"] for doc in isolated_docs
                }
                if len(iteration_counts) != 1:
                    raise SystemExit(f"{fx}/{eng}: iteration mismatch among Isolated sessions")
                isolated_slot[eng] = {
                    "iteration_num": iteration_counts.pop(),
                    "samples_ms": [
                        value
                        for doc in isolated_docs
                        for value in doc["fixtures"][fx][eng]["samples_ms"]
                    ],
                }
        else:
            isolated_slot = isolated_real["fixtures"][fx]
        entry = {}
        for eng in ("cpp", "rust"):
            replay = stats(replay_slot[eng]["samples_ms"])
            isolated = stats(isolated_slot[eng]["samples_ms"])
            entry[eng] = {
                "replay": replay,
                "isolated": isolated,
                "inflation_p50": round(replay["p50_ms"] / isolated["p50_ms"], 3),
                "inflation_max": round(replay["max_ms"] / isolated["max_ms"], 3),
                "abs_diff_max_ms": round(replay["max_ms"] - isolated["max_ms"], 3),
                "overrun_only_in_replay": replay["max_ms"] > 100.0 >= isolated["max_ms"],
            }
            if replay_slot[eng]["iteration_num"] != isolated_slot[eng]["iteration_num"]:
                raise SystemExit(f"{fx}/{eng}: iteration mismatch across configurations")
        out["inputs"][fx] = entry

    (DATA / "bridge.json").write_text(json.dumps(out, indent=1))
    print("wrote paper/data/bridge.json")
    for fx, e in out["inputs"].items():
        print(f"  {fx:13}", {eng: (e[eng]['inflation_p50'], e[eng]['inflation_max'])
                             for eng in ('cpp', 'rust')})


if __name__ == "__main__":
    main(sys.argv[1])
