from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.canonical_discovery import run_canonical_discovery_scan, summarize_canonical_bundle
from dor.cli import build_parser


def make_bundle():
    bundle = {
        "schema_version": "1.0",
        "project_id": "generic-test",
        "mapping_version": "test-1",
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "comparisons": [],
        "evidence": [],
    }
    for index, value in enumerate((10.0, 20.0, 30.0), start=1):
        study_id = f"S{index}"
        system_id = f"SYS{index}"
        condition_id = f"C{index}"
        experiment_id = f"E{index}"
        bundle["studies"].append({"study_id": study_id, "source_locators": []})
        bundle["systems"].append({
            "system_id": system_id, "study_ids": [study_id], "system_type": "unspecified"
        })
        bundle["conditions"].append({
            "condition_id": condition_id, "system_ids": [system_id],
            "condition_type": "condition_type_x", "raw_value": "reported",
            "value_state": "REPORTED"
        })
        bundle["experiments"].append({
            "experiment_id": experiment_id, "study_id": study_id,
            "system_id": system_id, "condition_ids": [condition_id]
        })
        bundle["observations"].extend([
            {
                "observation_id": f"O{index}A", "experiment_id": experiment_id,
                "target_id": "TARGET_A", "value_state": "REPORTED",
                "raw_value": value, "normalized_value": value, "raw_unit": "unit-x",
                "normalized_unit": "unit-x", "evidence_ids": []
            },
            {
                "observation_id": f"O{index}B", "experiment_id": experiment_id,
                "target_id": "TARGET_B", "value_state": "REPORTED",
                "raw_value": value + 1, "normalized_value": value + 1, "raw_unit": "unit-y",
                "normalized_unit": "unit-y", "evidence_ids": []
            }
        ])
    return bundle


class CanonicalDiscoveryTests(unittest.TestCase):
    def test_profiles_generic_canonical_entities(self):
        result = summarize_canonical_bundle(make_bundle(), minimum_studies=3)
        self.assertEqual(result["profile"]["study_count"], 3)
        self.assertEqual(result["profile"]["observation_count"], 6)
        self.assertEqual(result["profile"]["reported_numeric_observation_count"], 6)
        variation = [item for item in result["signals"]
                     if item["signal_type"] == "CROSS_STUDY_DESCRIPTIVE_VARIATION"]
        self.assertEqual(len(variation), 2)
        pair = next(item for item in result["signals"]
                    if item["signal_type"] == "CO_OBSERVED_TARGET_PAIR")
        self.assertEqual(pair["supporting_study_count"], 3)
        self.assertEqual(pair["interpretation_status"], "CO_OBSERVATION_ONLY_NOT_AN_INTERACTION")

    def test_joint_support_excludes_unreported_observations(self):
        bundle = make_bundle()
        unreported = next(row for row in bundle["observations"] if row["observation_id"] == "O1B")
        unreported.update({"value_state": "NOT_REPORTED", "raw_value": None, "normalized_value": None})
        result = summarize_canonical_bundle(bundle, minimum_studies=3)
        pair = next(row for row in result["joint_rows"]
                    if row["target_a"] == "TARGET_A" and row["target_b"] == "TARGET_B")
        self.assertEqual(pair["supporting_study_count"], 2)
        self.assertFalse(any(item["signal_type"] == "CO_OBSERVED_TARGET_PAIR" for item in result["signals"]))

    def test_condition_coverage_requires_a_reported_value(self):
        bundle = make_bundle()
        bundle["conditions"][0]["raw_value"] = None
        bundle["conditions"][0]["value_state"] = "REPORTED"
        result = summarize_canonical_bundle(bundle, minimum_studies=3)
        row = next(item for item in result["condition_rows"] if item["target_id"] == "TARGET_A")
        self.assertEqual(row["study_count"], 2)
        self.assertFalse(any(item["signal_type"] == "CONDITION_COVERAGE" for item in result["signals"]))

    def test_normalized_value_without_normalized_unit_falls_back_as_a_pair(self):
        bundle = make_bundle()
        for row in bundle["observations"]:
            if row["target_id"] == "TARGET_A":
                row["normalized_value"] = row["raw_value"] / 10
                row["normalized_unit"] = None
        result = summarize_canonical_bundle(bundle, minimum_studies=3)
        target = next(item for item in result["target_rows"] if item["target_id"] == "TARGET_A")
        self.assertEqual(target["unit"], "unit-x")
        self.assertEqual(target["numeric_median"], 20.0)

    def test_scan_writes_aggregate_outputs_and_preserves_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(make_bundle()), encoding="utf-8")
            before = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            output = root / "discovery"
            result = run_canonical_discovery_scan(bundle_path, output)
            after = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(result["profile"]["study_count"], 3)
            self.assertTrue((output / "discovery_manifest.json").is_file())
            self.assertTrue((output / "target_support.csv").is_file())
            self.assertTrue((output / "condition_outcome_contrasts.csv").is_file())
            self.assertTrue((output / "condition_level_support.csv").is_file())
            self.assertTrue((output / "condition_outcome_correlations.csv").is_file())
            self.assertTrue((output / "research_opportunities.json").is_file())
            self.assertTrue((output / "evidence_ledger.jsonl").is_file())
            self.assertTrue((output / "scientific_analysis_profile.json").is_file())
            self.assertTrue((output / "agent_research_brief.md").is_file())
            discovery_report = json.loads((output / "discovery_report.json").read_text(encoding="utf-8"))
            self.assertEqual(discovery_report["schema_version"], "1.1")
            self.assertEqual(discovery_report["research_opportunity_count"], 0)
            brief = (output / "agent_research_brief.md").read_text(encoding="utf-8")
            self.assertNotIn("O1A", brief)
            manifest = json.loads((output / "discovery_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["source_files_modified"])
            self.assertFalse(manifest["raw_observations_in_agent_brief"])

    def test_cli_accepts_canonical_bundle_input(self):
        args = build_parser().parse_args([
            "discover-opportunities", "--bundle", "canonical_bundle.json", "--out-dir", "discovery"
        ])
        self.assertEqual(args.bundle, Path("canonical_bundle.json"))
        self.assertEqual(args.maximum_pairs, 250)
        self.assertEqual(args.minimum_paired_studies, 3)
        self.assertEqual(args.fdr_alpha, 0.10)
        self.assertEqual(args.bootstrap_iterations, 1000)
        self.assertEqual(args.maximum_opportunities, 500)
        self.assertEqual(args.maximum_levels_per_condition, 20)
        self.assertEqual(args.seed, 42)

    def test_profile_preserves_studies_without_observations(self):
        bundle = make_bundle()
        bundle["studies"].append({"study_id": "S_WITH_EXPERIMENT_NO_OBSERVATION", "source_locators": []})
        bundle["systems"].append({
            "system_id": "SYS_WITHOUT_OBSERVATION",
            "study_ids": ["S_WITH_EXPERIMENT_NO_OBSERVATION"],
            "system_type": "unspecified",
        })
        bundle["experiments"].append({
            "experiment_id": "E_WITHOUT_OBSERVATION",
            "study_id": "S_WITH_EXPERIMENT_NO_OBSERVATION",
            "system_id": "SYS_WITHOUT_OBSERVATION",
            "condition_ids": [],
        })
        result = summarize_canonical_bundle(bundle, minimum_studies=3)
        self.assertEqual(result["profile"]["study_count"], 4)
        self.assertEqual(result["profile"]["study_count_with_observations"], 3)
        self.assertEqual(result["profile"]["study_count_without_observations"], 1)

    def test_invalid_bundle_fails_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = root / "invalid.json"
            bundle_path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
            output = root / "out"
            with self.assertRaises(ValueError):
                run_canonical_discovery_scan(bundle_path, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
