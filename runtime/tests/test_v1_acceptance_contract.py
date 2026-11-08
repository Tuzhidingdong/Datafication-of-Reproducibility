import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE_ORDER = [
    "source_selection",
    "source_integrity",
    "extraction_review",
    "semantic_mapping",
    "canonical_reconciliation",
    "cohort_feasibility",
    "modeling_validation",
    "publication_handoff",
]


class V1AcceptanceContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / "schemas/v1_acceptance_record.schema.json").read_text(encoding="utf-8"))
        self.example = json.loads((ROOT / "templates/v1_acceptance_record.example.json").read_text(encoding="utf-8"))

    def test_schema_and_example_parse(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(self.example["schema_version"], "1.0")

    def test_example_declares_all_stages_once_in_fixed_order(self):
        ids = [item["stage_id"] for item in self.example["stages"]]
        self.assertEqual(ids, STAGE_ORDER)
        self.assertEqual(len(ids), len(set(ids)))

    def test_single_study_scope_is_not_misrepresented_as_multistudy(self):
        self.assertEqual(self.example["scope"], "CONTROLLED_SINGLE_STUDY")
        self.assertEqual(self.example["source_snapshot"]["study_count"], 1)
        conditional = next(
            item for item in self.schema["allOf"]
            if item.get("if", {}).get("properties", {}).get("scope", {}).get("const") == "CONTROLLED_SINGLE_STUDY"
        )
        self.assertEqual(conditional["then"]["properties"]["source_snapshot"]["properties"]["study_count"]["const"], 1)

    def test_passing_stages_require_evidence(self):
        stage_schema = self.schema["properties"]["stages"]["items"]
        pass_rule = next(
            item for item in stage_schema["allOf"]
            if item.get("if", {}).get("properties", {}).get("status", {}).get("const") == "PASS"
        )
        self.assertEqual(pass_rule["then"]["properties"]["evidence"]["minItems"], 1)

    def test_not_applicable_requires_scientific_reason(self):
        stage_schema = self.schema["properties"]["stages"]["items"]
        na_rule = next(
            item for item in stage_schema["allOf"]
            if item.get("if", {}).get("properties", {}).get("status", {}).get("const") == "NOT_APPLICABLE"
        )
        self.assertIn("not_applicable_reason", na_rule["then"]["required"])

    def test_full_pass_requires_all_stages_to_pass(self):
        rule = next(
            item for item in self.schema["allOf"]
            if item.get("if", {}).get("properties", {}).get("final_assessment", {}).get("properties", {}).get("decision", {}).get("const") == "PASS"
        )
        self.assertEqual(rule["then"]["properties"]["stages"]["items"]["properties"]["status"]["const"], "PASS")


    def test_stage_check_contract_is_declared_and_example_initially_has_no_claimed_checks(self):
        stage_schema = self.schema["properties"]["stages"]["items"]
        check_schema = stage_schema["properties"]["checks"]["items"]
        self.assertEqual(check_schema["required"], ["check_id", "artifact_id", "json_pointer", "operator"])
        self.assertIn("gte", check_schema["properties"]["operator"]["enum"])
        self.assertTrue(all(stage["checks"] == [] for stage in self.example["stages"]))

    def test_acceptance_evidence_requires_declared_type(self):
        evidence = self.schema["properties"]["stages"]["items"]["properties"]["evidence"]["items"]
        self.assertIn("artifact_type", evidence["required"])
        self.assertIn("canonical_bundle", evidence["properties"]["artifact_type"]["enum"])
        self.assertIn("model_artifact", evidence["properties"]["artifact_type"]["enum"])
        self.assertIn("reproducibility_evaluation_manifest", evidence["properties"]["artifact_type"]["enum"])

    def test_modeling_stage_contract_requires_serialized_model_and_nested_evaluation(self):
        from dor.stage_contracts import STAGE_CONTRACTS
        self.assertEqual(
            STAGE_CONTRACTS["modeling_validation"]["required_artifact_types"],
            ["model_report", "model_artifact", "modeling_run_manifest",
             "reproducibility_evaluation", "reproducibility_evaluation_manifest"],
        )

    def test_study_ids_are_explicit_unique_and_required(self):
        snapshot = self.schema["properties"]["source_snapshot"]
        self.assertIn("study_ids", snapshot["required"])
        self.assertTrue(snapshot["properties"]["study_ids"]["uniqueItems"])
        self.assertGreaterEqual(snapshot["properties"]["study_ids"]["minItems"], 1)
        self.assertEqual(self.example["source_snapshot"]["study_count"], len(self.example["source_snapshot"]["study_ids"]))


if __name__ == "__main__":
    unittest.main()
