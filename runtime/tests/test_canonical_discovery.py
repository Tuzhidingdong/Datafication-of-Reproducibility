from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.canonical_discovery import run_canonical_discovery_scan, summarize_canonical_bundle
from dor.cli import build_parser
from dor.canonical import validate_canonical_bundle


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
    bundle["observations"][0]["value_candidates"] = [
        {
            "candidate_id": "O1A-CAND-A",
            "candidate_source": "extractor-alpha",
            "raw_value": 10.0,
            "raw_unit": "unit-x",
            "quoted_text": "Synthetic structured quote A",
            "source_locators": [],
        },
        {
            "candidate_id": "O1A-CAND-B",
            "candidate_source": "extractor-beta",
            "raw_value": 12.0,
            "raw_unit": "unit-x",
        },
    ]
    bundle["observations"][2]["value_candidates"] = [
        {
            "candidate_id": "O2A-CAND-A1",
            "candidate_source": "extractor-alpha",
            "raw_value": 20.0,
            "raw_unit": "unit-x",
        },
        {
            "candidate_id": "O2A-CAND-A2",
            "candidate_source": "extractor-alpha",
            "raw_value": 200.0,
            "raw_unit": "unit-x",
        },
    ]
    bundle["conditions"][1]["value_candidates"] = [
        {
            "candidate_id": "C2-CAND-A",
            "candidate_source": "extractor-alpha",
            "raw_value": 2.0,
            "raw_unit": "unit-condition",
        }
    ]
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

    def test_candidate_values_are_inventoried_and_source_scenarios_are_isolated(self):
        bundle = make_bundle()
        result = summarize_canonical_bundle(bundle, minimum_studies=3)
        mining = result["candidate_mining"]
        self.assertEqual(mining["inventory_profile"]["candidate_record_count"], 3)
        self.assertEqual(mining["inventory_profile"]["candidate_value_count"], 5)
        self.assertEqual(mining["inventory_profile"]["candidate_source_count"], 2)
        self.assertEqual(result["profile"]["reported_numeric_observation_count"], 6)
        reconciliation = next(
            row for row in mining["reconciliation_rows"]
            if row["record_id"] == "O2A"
        )
        self.assertEqual(reconciliation["reconciliation_status"], "VALUE_CONFLICT")
        alpha = next(
            row for row in mining["sensitivity"]["scenarios"]
            if row["candidate_source"] == "extractor-alpha"
        )
        self.assertEqual(alpha["scenario_status"], "CANDIDATE_SOURCE_SENSITIVITY_ONLY_NOT_PRIMARY")
        self.assertEqual(alpha["overlay_counts"]["observations"], 1)
        self.assertEqual(alpha["overlay_counts"]["conditions"], 1)
        self.assertEqual(alpha["conflicting_candidate_records_skipped"]["observations"], 1)
        self.assertEqual(alpha["analysis_profile"]["numeric_observation_count_used"], 6)
        self.assertEqual(result["scientific"]["profile"]["numeric_observation_count_used"], 6)

    def test_canonical_validation_rejects_candidate_without_source_identity(self):
        bundle = make_bundle()
        bundle["observations"][0]["value_candidates"][0]["candidate_source"] = ""
        result = validate_canonical_bundle(bundle)
        self.assertFalse(result["valid"])
        self.assertIn("INVALID_VALUE_CANDIDATE_SOURCE", {item["code"] for item in result["errors"]})

    def test_scan_writes_candidate_outputs_without_exposing_rows_in_agent_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(make_bundle()), encoding="utf-8")
            before = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            output = root / "discovery"
            run_canonical_discovery_scan(bundle_path, output)
            self.assertEqual(before, hashlib.sha256(bundle_path.read_bytes()).hexdigest())
            for name in (
                "candidate_value_inventory.csv",
                "candidate_value_reconciliation.csv",
                "missingness_opportunity_profile.csv",
                "candidate_sensitivity_opportunities.json",
                "candidate_sensitivity_profile.json",
            ):
                self.assertTrue((output / name).is_file(), name)
            brief = (output / "agent_research_brief.md").read_text(encoding="utf-8")
            self.assertNotIn("Synthetic structured quote A", brief)
            report = json.loads((output / "discovery_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["candidate_value_record_count"], 3)
            self.assertEqual(report["candidate_sensitivity_scenario_count"], 2)
            manifest = json.loads((output / "discovery_manifest.json").read_text(encoding="utf-8"))
            output_names = {item["path"] for item in manifest["output_files"]}
            self.assertIn("candidate_value_inventory.csv", output_names)
            self.assertFalse(manifest["candidate_values_enter_primary_analysis"])
            self.assertFalse(manifest["candidate_alternatives_counted_as_independent_observations"])

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
            self.assertEqual(discovery_report["schema_version"], "1.3")
            self.assertEqual(discovery_report["related_opportunity_group_count"], 0)
            self.assertEqual(discovery_report["research_opportunity_count"], 0)
            opportunity_payload = json.loads((output / "research_opportunities.json").read_text(encoding="utf-8"))
            self.assertEqual(opportunity_payload["excluded_self_associations"], [])
            self.assertEqual(opportunity_payload["mirror_duplicates"], [])
            self.assertEqual(opportunity_payload["schema_version"], "1.1")
            self.assertEqual(opportunity_payload["related_opportunity_groups"], [])
            self.assertEqual(discovery_report["excluded_self_association_count"], 0)
            self.assertEqual(discovery_report["mirror_duplicate_opportunity_count"], 0)
            self.assertEqual(discovery_report["mirror_duplicate_group_count"], 0)
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
        self.assertIsNone(args.semantic_registry)

    def test_cli_accepts_optional_semantic_registry(self):
        args = build_parser().parse_args([
            "discover-opportunities", "--bundle", "canonical_bundle.json",
            "--semantic-registry", "semantic_registry.json", "--out-dir", "discovery"
        ])
        self.assertEqual(args.semantic_registry, Path("semantic_registry.json"))
        validation_args = build_parser().parse_args([
            "validate-semantic-registry", "--registry", "semantic_registry.json"
        ])
        self.assertEqual(validation_args.command, "validate-semantic-registry")
        self.assertEqual(validation_args.registry, Path("semantic_registry.json"))

    def test_scan_applies_external_registry_without_modifying_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = root / "bundle.json"
            registry_path = root / "semantic_registry.json"
            bundle_path.write_text(json.dumps(make_bundle()), encoding="utf-8")
            registry = {
                "schema_version": "1.0",
                "registry_id": "registry:scan-test",
                "records": [
                    {
                        "entity_type": "TARGET",
                        "canonical_identifier": "TARGET_A",
                        "semantic_metadata": {
                            "canonical_concept_id": "concept:target-a",
                            "review_status": "APPROVED",
                            "reviewer": "reviewer-label",
                            "reviewed_at": "2026-11-18T00:00:00Z",
                            "review_rationale": "Reviewed using the supplied source locator.",
                            "source_refs": [{
                                "source_id": "source:target-a",
                                "source_sha256": "b" * 64,
                                "locator": "opaque:target-a",
                            }],
                        },
                    },
                    {
                        "entity_type": "CONDITION",
                        "canonical_identifier": "condition_type_x",
                        "semantic_metadata": {
                            "canonical_concept_id": "concept:condition-x",
                            "review_status": "APPROVED",
                            "reviewer": "reviewer-label",
                            "reviewed_at": "2026-11-18T00:00:00Z",
                            "review_rationale": "Reviewed using the supplied source locator.",
                            "source_refs": [{
                                "source_id": "source:condition-x",
                                "source_sha256": "c" * 64,
                                "locator": "opaque:condition-x",
                            }],
                        },
                    },
                ],
            }
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            before = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
            output = root / "discovery"
            result = run_canonical_discovery_scan(
                bundle_path, output, semantic_registry_path=registry_path
            )
            after = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(result["semantic_registry"]["registry_id"], "registry:scan-test")
            self.assertEqual(result["semantic_registry"]["applied_record_count"], 2)
            manifest = json.loads((output / "discovery_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["semantic_registry_sha256"], registry_hash)
            self.assertFalse(manifest["semantic_registry"]["bundle_modified"])
            report = json.loads((output / "discovery_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "1.3")
            self.assertEqual(report["scientific_analysis"]["profile"]["semantic_registry"]["registry_id"], "registry:scan-test")

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
