#!/usr/bin/env python3
"""Validate and pool a bounded Isolated campaign into paper/data."""

import argparse
import hashlib
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WS = ROOT.parent
BENCH = WS / "src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench"
DEFAULT_RUNS = BENCH / "campaign_runs/unified_bounded_3x1000"
DEFAULT_CONFIG = WS / "plan/campaign_config_unified_bounded.json"
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


def config_hash(config):
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    compiler_flags = manifest.get("compiler_flags") or {}
    if compiler_flags.get("NDT_BUILD_TRACED") != "OFF":
        raise SystemExit(
            f"{path}: timing campaign requires NDT_BUILD_TRACED=OFF")
    return manifest


def assert_identity(reference, candidate, path):
    for field in IDENTITY_FIELDS:
        if candidate.get(field) != reference.get(field):
            raise SystemExit(f"{path}: campaign identity mismatch in {field}")


def validate_campaign_locks(runs_dir, session_dirs, config):
    expected_hash = config_hash(config)
    lock_path = runs_dir / "campaign.lock.json"
    if not lock_path.is_file():
        raise SystemExit(f"missing {lock_path}")
    campaign_lock = load(lock_path)
    expected = {
        "campaign_id": config.get("campaign_id"),
        "config_hash": expected_hash,
        "sessions": len(session_dirs),
    }
    for field, value in expected.items():
        if campaign_lock.get(field) != value:
            raise SystemExit(
                f"{lock_path}: {field} {campaign_lock.get(field)!r} != {value!r}")

    boot_ids = []
    for number, session_dir in enumerate(session_dirs, start=1):
        path = session_dir / "session.lock.json"
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        lock = load(path)
        expected_session = {
            "campaign_id": config.get("campaign_id"),
            "config_hash": expected_hash,
            "session": number,
        }
        for field, value in expected_session.items():
            if lock.get(field) != value:
                raise SystemExit(f"{path}: {field} {lock.get(field)!r} != {value!r}")
        if not lock.get("boot_id"):
            raise SystemExit(f"{path}: missing boot_id")
        boot_ids.append(lock["boot_id"])
    if len(set(boot_ids)) != len(boot_ids):
        raise SystemExit("session locks must record three distinct boot IDs")
    return campaign_lock


def validate_sidecars(series, session_dirs, config, campaign_lock):
    expected_names = fixture_names(config)
    identity = {
        "campaign_id": campaign_lock["campaign_id"],
        "campaign_config_hash": campaign_lock["config_hash"],
        "binary_hash": campaign_lock["binary_hash"],
        "cpp_commit": campaign_lock["cpp_commit"],
        "rust_commit": campaign_lock["rust_commit"],
        "fixture_hashes": campaign_lock["fixture_hashes"],
    }
    expected_files = {
        f"{name}__{engine}.cell.json"
        for name in expected_names
        for engine in ("cpp", "rust")
    }
    for session_dir in session_dirs:
        directory = session_dir / series
        actual_files = {path.name for path in directory.glob("*.cell.json")}
        if actual_files != expected_files:
            raise SystemExit(
                f"{directory}: sidecar set differs from campaign plan; "
                f"missing={sorted(expected_files - actual_files)}, "
                f"extra={sorted(actual_files - expected_files)}")
        session_lock = load(session_dir / "session.lock.json")
        for filename in sorted(expected_files):
            path = directory / filename
            sidecar = load(path)
            if sidecar.get("problems"):
                raise SystemExit(f"{path}: measurement problems: {sidecar['problems']}")
            manifest = sidecar.get("manifest") or {}
            assert_identity(identity, manifest, path)
            if manifest.get("boot_id") != session_lock["boot_id"]:
                raise SystemExit(f"{path}: boot_id differs from session lock")


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
    campaign_id = manifest.get("campaign_id") or "campaign"
    manifest.update({
        "experiment_id": f"{campaign_id}/pooled",
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
    parser.add_argument("--warm-output-name", default="wcet.json")
    parser.add_argument("--warm-only", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    config = load(args.config)
    session_dirs = [args.runs_dir / name for name in SESSIONS]
    for directory in session_dirs:
        if not directory.is_dir():
            raise SystemExit(f"missing campaign session directory {directory}")
    campaign_lock = validate_campaign_locks(args.runs_dir, session_dirs, config)

    validate_sidecars("warm", session_dirs, config, campaign_lock)
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
            warm_manifests,
            f"three-boot Isolated warm campaign ({config['campaign_id']})"),
    }
    emit(
        args.output_dir / args.warm_output_name,
        "WCET fixture replay (Isolated campaign, pooled warm)",
        warm_meta,
        warm,
        args.check_only,
    )
    if args.warm_only:
        return 0

    validate_sidecars("cold", session_dirs, config, campaign_lock)
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
            cold_manifests,
            f"three-boot Isolated cold campaign ({config['campaign_id']})"),
    }
    emit(
        args.output_dir / "wcet_cold.json",
        "WCET fixture replay (unified Isolated campaign, pooled cold)",
        cold_meta,
        cold,
        args.check_only,
    )

    modes = {}
    mode_manifests = []
    mode_samples = None
    for mode in config["corunner"]["modes"]:
        series = f"corunner_{mode}"
        validate_sidecars(series, session_dirs, config, campaign_lock)
        fixtures, manifests, samples, _ = pool_series(
            series, session_dirs, config, identity)
        modes[mode] = fixtures
        mode_manifests.extend(manifests)
        mode_samples = samples
    corunner_doc = {
        "benchmark": "WCET fixture replay (unified Isolated co-runner campaign)",
        "meta": {
            **(mode_samples or {}),
            "unit": "ms",
            "manifest": top_manifest(
                mode_manifests,
                f"three-boot Isolated co-runner campaign ({config['campaign_id']})"),
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
