#!/usr/bin/env python3

import importlib.util
import json
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("integrate_campaign.py")
SPEC = importlib.util.spec_from_file_location("integrate_campaign", SCRIPT)
INTEGRATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTEGRATE)


class IntegrateCampaignTest(unittest.TestCase):
    def config(self):
        return {
            "tiers": {"unified": {"fixtures": ["a", "b"], "samples": 2}},
            "cold": {"samples": 2},
            "corunner": {"samples": 2},
        }

    def write_session(self, root, number, boot):
        directory = root / f"session-{number}"
        directory.mkdir()
        manifest = {
            "measurement_profile": "B",
            "campaign_id": "test",
            "campaign_config_hash": "config",
            "binary_hash": "binary",
            "cpp_commit": "commit",
            "rust_commit": "commit",
            "fixture_hashes": {"a": "hash-a", "b": "hash-b"},
            "compiler_flags": {"NDT_BUILD_TRACED": "OFF"},
            "boot_id": boot,
            "experiment_id": f"session-{number}/warm/a__cpp",
        }
        fixtures = {}
        for name in ("a", "b"):
            fixtures[name] = {
                "iter_match": True,
                "cpp": {"iteration_num": 3, "samples_ms": [1.0, 2.0]},
                "rust": {"iteration_num": 3, "samples_ms": [0.5, 1.0]},
            }
        (directory / "warm.json").write_text(json.dumps({
            "meta": {"manifest": manifest}, "fixtures": fixtures,
        }))
        return directory

    def test_pool_requires_and_records_three_equal_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            directories = [self.write_session(root, i, f"boot-{i}") for i in range(1, 4)]
            pooled, manifests, samples, _ = INTEGRATE.pool_series(
                "warm", directories, self.config())
            self.assertEqual(sorted(pooled), ["a", "b"])
            self.assertEqual(len(manifests), 3)
            self.assertEqual(samples["samples_per_session"], 2)
            self.assertEqual(samples["pooled_samples_per_fixture"], 6)
            self.assertEqual(len(pooled["a"]["cpp"]["samples_ms"]), 6)

    def test_pool_rejects_reused_boot_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            directories = [self.write_session(root, i, "same-boot") for i in range(1, 4)]
            with self.assertRaisesRegex(SystemExit, "distinct boot IDs"):
                INTEGRATE.pool_series("warm", directories, self.config())

    def test_pool_rejects_traced_timing_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            directories = [self.write_session(root, i, f"boot-{i}") for i in range(1, 4)]
            path = directories[1] / "warm.json"
            document = json.loads(path.read_text())
            document["meta"]["manifest"]["compiler_flags"]["NDT_BUILD_TRACED"] = "ON"
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(SystemExit, "NDT_BUILD_TRACED=OFF"):
                INTEGRATE.pool_series("warm", directories, self.config())


if __name__ == "__main__":
    unittest.main()
