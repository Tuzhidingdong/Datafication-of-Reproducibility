import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import io
import contextlib
import sys

from dor.acceptance import STAGE_ORDER, validate_acceptance_record
from dor.cli import build_parser, main
from dor.run_manager import initialize_run, record_stage_status


class AcceptanceValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_root = self.root / "sources"
        self.source_root.mkdir()
        self.paper = self.source_root / "paper.pdf"
        self.si = self.source_root / "paper_si.pdf"
        self.paper.write_bytes(b"synthetic paper bytes")
        self.si.write_bytes(b"synthetic SI bytes")

        self.run_root = self.root / "runs" / "RUN_1"
        self.plan_path = self.root / "run_plan.json"
        plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_1",
            "source_roots": [str(self.source_root)],
            "source_artifacts": [
                {"artifact_id": "paper", "path": str(self.paper)},
                {"artifact_id": "si", "path": str(self.si)},
            ],
            "stages": [{
                "stage_id": "acceptance_evidence",
                "executor": "local",
                "depends_on": [],
                "inputs": ["paper", "si"],
                "outputs": [{"artifact_id": "audit_report", "path": "01_audit/audit_report.json"}],
            }],
        }
        self.plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        initialized = initialize_run(self.plan_path, self.run_root, "RUN_1")
        self.manifest = Path(initialized["manifest_path"])
        self.evidence_path = self.run_root / "01_audit" / "audit_report.json"
        record_stage_status(
            self.manifest, "acceptance_evidence", "RUNNING", "local",
            command="synthetic acceptance fixture",
        )
        self.evidence_path.parent.mkdir(parents=True)
        self.evidence_path.write_text('{"synthetic": true}', encoding="utf-8")
        record_stage_status(self.manifest, "acceptance_evidence", "SUCCEEDED", "local")

        self.record_path = self.root / "acceptance.json"
        self.record = {
            "schema_version": "1.0",
            "acceptance_id": "ACC_1",
            "project_id": "PROJECT_1",
            "scope": "CONTROLLED_SINGLE_STUDY",
            "run_id": "RUN_1",
            "run_manifest_sha256": self.sha(self.manifest),
            "source_snapshot": {
                "study_count": 1,
                "study_ids": ["STUDY_1"],
                "artifacts": [
                    {"source_id": "paper", "role": "PRIMARY_PAPER", "path": str(self.paper), "sha256": self.sha(self.paper)},
                    {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": str(self.si), "sha256": self.sha(self.si)},
                ],
            },
            "stages": [
                {"stage_id": stage, "status": "NOT_STARTED", "evidence": [], "limitations": []}
                for stage in STAGE_ORDER
            ],
            "final_assessment": {
                "decision": "NOT_ASSESSED",
                "assessed_by": "reviewer",
                "rationale": "Not yet reviewed.",
                "blocking_issue_ids": [],
            },
        }
        self.write_record()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_record(self):
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")

    def set_stage(self, stage_id, status, evidence=True, **extra):
        stage = next(item for item in self.record["stages"] if item["stage_id"] == stage_id)
        stage["status"] = status
        stage.update(extra)
        if evidence:
            stage["evidence"] = [{
                "artifact_id": "audit_report",
                "path": str(self.evidence_path),
                "sha256": self.sha(self.evidence_path),
            }]
        self.write_record()

    def validate(self):
        return validate_acceptance_record(self.record_path, self.manifest)

    def test_initial_record_is_valid_but_not_scientifically_accepted(self):
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["final_decision"], "NOT_ASSESSED")
        self.assertTrue(report["scientific_review_required"])

    def test_all_pass_requires_evidence_and_supports_full_pass_only_when_all_stages_pass(self):
        self.record["scope"] = "MULTI_STUDY_PILOT"
        self.record["source_snapshot"]["study_count"] = 3
        self.record["source_snapshot"]["study_ids"] = ["STUDY_1", "STUDY_2", "STUDY_3"]
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.write_record()
        self.assertTrue(self.validate()["valid"], self.validate()["issues"])

    def test_multi_study_scope_requires_multiple_studies(self):
        self.record["scope"] = "MULTI_STUDY_PILOT"
        self.record["source_snapshot"]["study_count"] = 1
        self.write_record()
        self.assertIn("MULTI_STUDY_SCOPE_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_single_study_cannot_pass_model_validation(self):
        self.set_stage("modeling_validation", "PASS")
        report = self.validate()
        self.assertIn("SINGLE_STUDY_MODEL_VALIDATION_INVALID", {item["code"] for item in report["issues"]})

    def test_conditional_pass_allows_na_only_with_reason(self):
        for stage in STAGE_ORDER:
            if stage in {"cohort_feasibility", "modeling_validation"}:
                self.set_stage(stage, "NOT_APPLICABLE", evidence=False,
                    not_applicable_reason="Single Study cannot support Study-held-out validation.")
            else:
                self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "CONDITIONAL_PASS"
        self.write_record()
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])

    def test_na_without_reason_is_rejected(self):
        self.set_stage("modeling_validation", "NOT_APPLICABLE", evidence=False)
        report = self.validate()
        self.assertIn("NA_WITHOUT_REASON", {item["code"] for item in report["issues"]})

    def test_source_or_evidence_tampering_is_detected(self):
        self.set_stage("source_integrity", "PASS")
        self.evidence_path.write_text("tampered", encoding="utf-8")
        self.assertIn("EVIDENCE_HASH_MISMATCH", {item["code"] for item in self.validate()["issues"]})
        self.paper.write_bytes(b"changed paper")
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertTrue({"SOURCE_HASH_MISMATCH", "RUN_INTEGRITY_INVALID", "RUN_SOURCE_INTEGRITY_CHANGED"} & codes)

    def test_run_manifest_hash_mismatch_is_detected(self):
        self.record["run_manifest_sha256"] = "f" * 64
        self.write_record()
        self.assertIn("RUN_MANIFEST_HASH_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_stage_order_is_fixed(self):
        self.record["stages"].reverse()
        self.write_record()
        self.assertIn("STAGE_ORDER_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_cli_registers_and_executes_validator(self):
        parser = build_parser()
        subparsers = next(action.choices for action in parser._actions if hasattr(action, "choices") and action.choices)
        self.assertIn("validate-acceptance", subparsers)
        args = ["dor", "validate-acceptance", "--record", str(self.record_path), "--run-manifest", str(self.manifest)]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            code = main()
        self.assertEqual(code, 0)
        self.assertIn('"valid": true', stdout.getvalue())

    def test_acceptance_sources_must_exactly_match_run_snapshot(self):
        self.record["source_snapshot"]["artifacts"].pop()
        self.write_record()
        self.assertIn("SOURCE_SET_DIFFERS_FROM_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_source_path_cannot_be_repointed_outside_run_snapshot(self):
        self.record["source_snapshot"]["artifacts"][0]["path"] = str(self.si)
        self.record["source_snapshot"]["artifacts"][0]["sha256"] = self.sha(self.si)
        self.write_record()
        self.assertIn("SOURCE_PATH_NOT_BOUND_TO_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_evidence_must_be_a_successful_run_artifact(self):
        self.set_stage("source_integrity", "PASS")
        self.record["stages"][1]["evidence"] = [{
            "artifact_id": "invented_report",
            "path": str(self.evidence_path),
            "sha256": self.sha(self.evidence_path),
        }]
        self.write_record()
        self.assertIn("EVIDENCE_NOT_A_COMPLETED_RUN_ARTIFACT", {item["code"] for item in self.validate()["issues"]})

    def test_evidence_hash_must_match_success_event_snapshot(self):
        self.set_stage("source_integrity", "PASS")
        self.record["stages"][1]["evidence"][0]["sha256"] = "f" * 64
        self.write_record()
        self.assertIn("EVIDENCE_HASH_NOT_BOUND_TO_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_study_count_must_match_explicit_unique_study_ids(self):
        self.record["source_snapshot"]["study_count"] = 2
        self.write_record()
        self.assertIn("STUDY_ID_COUNT_MISMATCH", {item["code"] for item in self.validate()["issues"]})


if __name__ == "__main__":
    unittest.main()
