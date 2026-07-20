#!/usr/bin/env python3
"""Validate and pool the unified Profile-B campaign into paper/data."""

import argparse
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WS = ROOT.parent
BENCH = WS / "src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench"
DEFAULT_RUNS = BENCH / "campaign_runs/unified_3x1000"
DEFAULT_CONFIG = BENCH / "campaign_config_unified.json"
DATA = ROOT / "data"
SESSIONS = ["session-1", "session-2", "session-3"]
IDENTITY_FIELDS = (
    "campaign_id",
    "campaign_config_hash",
    "binary_hash",
    "cpp_commit",
    "rust_commit",
    "fixture_hashes",
)


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def fixture_names(config):
    names = [name for spec in config["tiers"].values() for name in spec["fixtures"]]
    if len(names) != len(set(names)):
        raise SystemExit("campaign config has duplicate fixture names")
    return sorted(names)


def expected_samples(config, series, name):
    if series == "warm":
        for spec in config["tiers"].values():
            if name in spec["fixtures"]:
                return spec["samples"]
        raise SystemExit(f"{name}: no timing tier")
    if series == "cold":
        return config["cold"]["samples"]
    if series.startswith("corunner_"):
        return config["corunner"]["samples"]
    raise SystemExit(f"unknown series {series}")


def manifest_of(doc, path):
    manifest = (doc.get("meta") or {}).get("manifest")
    if not manifest:
        raise SystemExit(f"{path}: missing meta.manifest")
    if manifest.get("measurement_profile") != "B":
        raise SystemExit(
            f"{path}: measurement_profile {manifest.get('measurement_profile')!r} != 'B'")
    return manifest


def assert_identity(reference, candidate, path):
    for field in IDENTITY_FIELDS:
        if candidate.get(field) != reference.get(field):
            raise SystemExit(f"{path}: campaign identity mismatch in {field}")


def pool_series(series, session_dirs, config, reference_identity=None):
    expected_names = fixture_names(config)
    docs = []
    for session_dir in session_dirs:
        path = session_dir / f"{series}.json"
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        document = load(path)
        if sorted(document.get("fixtures", {})) != expected_names:
            raise SystemExit(f"{path}: fixture set differs from the unified config")
        docs.append((path, document))

    manifests = [manifest_of(document, path) for path, document in docs]
    identity = reference_identity or manifests[0]
    for (path, _), manifest in zip(docs, manifests):
        assert_identity(identity, manifest, path)
    boot_ids = [manifest.get("boot_id") for manifest in manifests]
    if any(not value for value in boot_ids) or len(set(boot_ids)) != len(boot_ids):
        raise SystemExit(f"{series}: sessions must come from three distinct boot IDs")

    pooled = {}
    for name in expected_names:
        base = None
        per_session_median = {"cpp": [], "rust": []}
        for path, document in docs:
            fixture = document["fixtures"][name]
            if not fixture.get("iter_match", False):
                raise SystemExit(f"{path}: {name}: iter_match is false")
            if base is None:
                base = {key: value for key, value in fixture.items()
                        if key not in ("cpp", "rust")}
                base["cpp"] = {
                    "iteration_num": fixture["cpp"]["iteration_num"],
                    "allocs_per_align": -1,
                    "samples_ms": [],
                }
                base["rust"] = {
                    "iteration_num": fixture["rust"]["iteration_num"],
                    "allocs_per_align": -1,
                    "samples_ms": [],
                }
            expected = expected_samples(config, series, name)
            for engine in ("cpp", "rust"):
                samples = fixture[engine].get("samples_ms")
                if not isinstance(samples, list) or len(samples) != expected:
                    raise SystemExit(
                        f"{path}: {name}/{engine}: expected {expected} samples")
                if fixture[engine]["iteration_num"] != base[engine]["iteration_num"]:
                    raise SystemExit(
                        f"{path}: {name}/{engine}: iteration count changed across sessions")
                base[engine]["samples_ms"].extend(samples)
                per_session_median[engine].append(round(statistics.median(samples), 3))
        base["per_session_median"] = per_session_median
        pooled[name] = base

    per_session_counts = sorted({expected_samples(config, series, name)
                                 for name in expected_names})
    if len(per_session_counts) != 1:
        raise SystemExit(f"{series}: unified campaign has unequal sample counts")
    sample_meta = {
        "samples_per_session": per_session_counts[0],
        "session_count": len(session_dirs),
        "pooled_samples_per_fixture": per_session_counts[0] * len(session_dirs),
    }
    return pooled, manifests, sample_meta, identity


def top_manifest(manifests, note):
    manifest = dict(manifests[0])
    manifest.update({
        "experiment_id": "unified-campaign/pooled",
        "sessions": [item["experiment_id"] for item in manifests],
        "session_manifests": manifests,
        "pooling": "samples concatenated in session order; per-session medians retained",
        "notes": note,
    })
    return manifest


def emit(path, benchmark, meta, fixtures, check_only):
    if check_only:
        print(f"validated {path.name}: {len(fixtures)} fixtures")
        return
    document = {"benchmark": benchmark, "meta": meta, "fixtures": fixtures}
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(fixtures)} fixtures)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=pathlib.Path, default=DEFAULT_RUNS)
    parser.add_argument("--config", type=pathlib.Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=pathlib.Path, default=DATA)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    config = load(args.config)
    session_dirs = [args.runs_dir / name for name in SESSIONS]
    for directory in session_dirs:
        if not directory.is_dir():
            raise SystemExit(f"missing campaign session directory {directory}")

    warm, warm_manifests, warm_samples, identity = pool_series(
        "warm", session_dirs, config)
    warm_meta = {
        **warm_samples,
        "iters": f"{warm_samples['pooled_samples_per_fixture']} pooled across "
                 f"{warm_samples['session_count']} sessions",
        "warmup": config["warmup"],
        "num_threads": 1,
        "clock": "steady_clock",
        "unit": "ms",
        "alloc_counting": False,
        "cache_condition": "warm",
        "note": "align loop only; map and kd-tree built once per engine and fixture",
        "manifest": top_manifest(
            warm_manifests, "unified three-boot Profile-B warm campaign"),
    }
    emit(
        args.output_dir / "wcet.json",
        "WCET fixture replay (unified Profile-B campaign, pooled warm)",
        warm_meta,
        warm,
        args.check_only,
    )

    cold, cold_manifests, cold_samples, _ = pool_series(
        "cold", session_dirs, config, identity)
    cold_meta = {
        **warm_meta,
        **cold_samples,
        "iters": f"{cold_samples['pooled_samples_per_fixture']} pooled across "
                 f"{cold_samples['session_count']} sessions",
        "warmup": config["cold"]["warmup"],
        "cache_condition": "cold",
        "manifest": top_manifest(
            cold_manifests, "unified three-boot Profile-B cold campaign"),
    }
    emit(
        args.output_dir / "wcet_cold.json",
        "WCET fixture replay (unified Profile-B campaign, pooled cold)",
        cold_meta,
        cold,
        args.check_only,
    )

    modes = {}
    mode_manifests = []
    mode_samples = None
    for mode in config["corunner"]["modes"]:
        series = f"corunner_{mode}"
        fixtures, manifests, samples, _ = pool_series(
            series, session_dirs, config, identity)
        modes[mode] = fixtures
        mode_manifests.extend(manifests)
        mode_samples = samples
    corunner_doc = {
        "benchmark": "WCET fixture replay (unified Profile-B co-runner campaign)",
        "meta": {
            **(mode_samples or {}),
            "unit": "ms",
            "manifest": top_manifest(
                mode_manifests, "unified three-boot Profile-B co-runner campaign"),
        },
        "modes": modes,
    }
    output = args.output_dir / "wcet_corunner.json"
    if args.check_only:
        print(f"validated {output.name}: {len(modes)} modes x {len(warm)} fixtures")
    else:
        output.write_text(json.dumps(corunner_doc, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {output} ({len(modes)} modes x {len(warm)} fixtures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
