import unittest

from dor.stage_contracts import CONTRACT_VERSION, STAGE_CONTRACTS, validate_stage_payload, validate_stage_evidence


class StageEvidenceContractTests(unittest.TestCase):
    def test_registry_covers_fixed_eight_stage_protocol_in_order(self):
        self.assertEqual(CONTRACT_VERSION, "1.0")
        self.assertEqual(tuple(STAGE_CONTRACTS), (
            "source_selection", "source_integrity", "extraction_review", "semantic_mapping",
            "canonical_reconciliation", "cohort_feasibility", "modeling_validation", "publication_handoff",
        ))

    def test_each_stage_has_nonempty_fixed_artifact_types_and_checks(self):
        for stage_id, contract in STAGE_CONTRACTS.items():
            with self.subTest(stage=stage_id):
                self.assertTrue(contract["required_artifact_types"])
                self.assertTrue(contract["checks"])

    def test_source_inventory_requires_real_locator_and_sha_fields(self):
        bad = {"schema_version": "1.0", "items": [{"inventory_id": "I1", "source_file": "x.csv"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "source_inventory", bad, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("SOURCE_INVENTORY_ITEM_INCOMPLETE", codes)
        self.assertIn("SOURCE_INVENTORY_HASH_INVALID", codes)

    def test_mapping_plan_does_not_accept_unreviewed_proposed_rules(self):
        payload = {"schema_version": "1.0", "mapping_version": "M1", "source_inventory_sha256": "a" * 64,
                   "rules": [{"mapping_rule_id": "R1", "source_item_id": "I1", "status": "PROPOSED"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "mapping_plan", payload, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("MAPPING_RULE_UNREVIEWED", codes)

    def test_canonical_bundle_reuses_canonical_graph_validator(self):
        payload = {"schema_version": "1.0", "studies": [], "systems": [], "conditions": [],
                   "experiments": [], "observations": [], "comparisons": [], "evidence": []}
        codes = {item["code"] for item in validate_stage_payload(
            "canonical_bundle", payload, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertTrue({"CANONICAL_BUNDLE_INVALID", "CANONICAL_BUNDLE_METADATA_INVALID"} & codes)

    def test_reconciliation_report_must_bind_exact_bundle_hash(self):
        payload = {"schema_version": "1.0", "bundle_sha256": "b" * 64, "valid_bundle": True,
                   "issue_count": 0, "issues": []}
        codes = {item["code"] for item in validate_stage_payload(
            "reconciliation_report", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, canonical_sha256="a" * 64
        )}
        self.assertIn("RECONCILIATION_BUNDLE_HASH_MISMATCH", codes)

    def test_split_manifest_rejects_study_leakage(self):
        payload = {"schema_version": "1.0", "study_to_split": {"S1": "train", "S2": "train", "S3": "test"},
                   "leakage_check": {"valid": True, "study_overlap_count": 0}}
        codes = {item["code"] for item in validate_stage_payload(
            "split_manifest", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"}
        )}
        self.assertIn("STUDY_SPLIT_PARTITION_MISSING", codes)

    def test_model_manifest_rejects_overlapping_studies(self):
        payload = {"schema_version": "1.0", "input_hashes": {key: "a" * 64 for key in (
                       "cohort_sha256", "cohort_report_sha256", "split_manifest_sha256",
                       "cohort_manifest_sha256", "task_sha256")},
                   "output_hashes": {"model_report.json": "b" * 64},
                   "study_ids_by_split": {"train": ["S1"], "validation": ["S1"], "test": ["S3"]}}
        codes = {item["code"] for item in validate_stage_payload(
            "modeling_run_manifest", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"}
        )}
        self.assertIn("MODELING_STUDY_LEAKAGE", codes)

    def test_stage_evidence_rejects_missing_fixed_artifact_types(self):
        errors = validate_stage_evidence(
            "source_selection", [], run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=[],
        )
        codes = {item["code"] for item in errors}
        self.assertIn("STAGE_REQUIRED_EVIDENCE_TYPE_MISSING", codes)

    def test_source_selection_manifest_must_match_selected_source_snapshot(self):
        payload = {
            "schema_version": "1.0", "selection_rationale": "Selected by user.",
            "scope_statement": "One-study pilot.", "study_ids": ["S1"],
            "selected_sources": [{
                "source_id": "paper", "role": "PRIMARY_PAPER", "path": "/tmp/paper.pdf",
                "sha256": "a" * 64,
            }],
            "excluded_sources": [],
        }
        errors = validate_stage_payload(
            "source_selection_manifest", payload, run_id="R1", project_id="P1",
            study_ids={"S1"},
            source_snapshot=[{
                "source_id": "paper", "role": "PRIMARY_PAPER", "path": "/tmp/other.pdf",
                "sha256": "a" * 64,
            }],
        )
        self.assertIn("SOURCE_SELECTION_NOT_BOUND_TO_SNAPSHOT", {item["code"] for item in errors})

    def test_cohort_report_requires_explicit_eligible_study_ids(self):
        payload = {
            "valid": True, "task_id": "T1", "target_id": "Y", "endpoint_definition": "endpoint",
            "eligible_observation_count": 3, "eligible_study_count": 3,
            "split_counts": {},
        }
        errors = validate_stage_payload(
            "cohort_report", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"},
        )
        self.assertIn("COHORT_REPORT_INVALID", {item["code"] for item in errors})

    def test_unknown_evidence_type_is_rejected(self):
        codes = {item["code"] for item in validate_stage_payload(
            "invented_type", {}, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("UNKNOWN_STAGE_ARTIFACT_TYPE", codes)


if __name__ == "__main__":
    unittest.main()
