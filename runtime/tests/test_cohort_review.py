from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.cohort_review import validate_cohort_review_record
from dor.cli import build_parser


class CohortReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cohort_dir = self.root / "cohort"
        self.cohort_dir.mkdir()
        self.task_path = self.root / "modeling_task.json"
        self.manifest_path = self.root / "run_manifest.json"
        self.record_path = self.cohort_dir / "cohort_review_record.json"

        self.task = {"schema_version": "1.0", "task_id": "TASK_1"}
        self.task_path.write_text(json.dumps(self.task), encoding="utf-8")
        self.manifest_path.write_text(json.dumps({
            "run_id": "RUN_1", "project_id": "PROJECT_1",
            "workspace_root": str(self.root),
        }), encoding="utf-8")

        self.csv_path = self.cohort_dir / "modeling_cohort.csv"
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "cohort_row_id", "observation_id", "study_id", "split",
            ])
            writer.writeheader()
            writer.writerows([
                {"cohort_row_id": "ROW_1", "observation_id": "OBS_1", "study_id": "STUDY_1", "split": "train"},
                {"cohort_row_id": "ROW_2", "observation_id": "OBS_2", "study_id": "STUDY_2", "split": "test"},
            ])

        self.cohort_report = {
            "schema_version": "1.0", "valid": True, "task_id": "TASK_1",
            "eligible_observation_count": 2, "eligible_study_count": 2,
            "eligible_study_ids": ["STUDY_1", "STUDY_2"],
            "scientific_data_contract": {
                "warnings": [{"code": "REPEATED_RECORD_GRAIN_REVIEW"}],
            },
        }
        (self.cohort_dir / "cohort_report.json").write_text(
            json.dumps(self.cohort_report), encoding="utf-8",
        )
        self.split_manifest = {
            "schema_version": "1.0", "task_id": "TASK_1",
            "study_to_split": {"STUDY_1": "train", "STUDY_2": "test"},
            "leakage_check": {"valid": True, "study_overlap_count": 0},
        }
        (self.cohort_dir / "split_manifest.json").write_text(
            json.dumps(self.split_manifest), encoding="utf-8",
        )
        (self.cohort_dir / "modeling_cohort_manifest.json").write_text(
            json.dumps({"schema_version": "1.0", "task_id": "TASK_1"}),
            encoding="utf-8",
        )

        files = {
            "modeling_cohort.csv": self.csv_path,
            "cohort_report.json": self.cohort_dir / "cohort_report.json",
            "split_manifest.json": self.cohort_dir / "split_manifest.json",
            "modeling_cohort_manifest.json": self.cohort_dir / "modeling_cohort_manifest.json",
            "modeling_task.json": self.task_path,
        }
        hashes = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in files.items()
        }
        self.record = {
            "schema_version": "1.0",
            "review_id": "REVIEW_1",
            "run_id": "RUN_1",
            "project_id": "PROJECT_1",
            "task_id": "TASK_1",
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-15T10:00:00+08:00",
            "decision": "APPROVE_MODELING",
            "record_grain_assessment": "ACCEPTED",
            "independence_assessment": "SUPPORTED",
            "split_assessment": "ACCEPTED",
            "reviewed_warning_codes": ["REPEATED_RECORD_GRAIN_REVIEW"],
            "reviewed_study_count": 2,
            "reviewed_observation_count": 2,
            "artifact_sha256": hashes,
            "rationale": "The record grain, Study grouping, and split were explicitly reviewed.",
            "limitations": ["The reviewed cohort is limited to the declared task and source snapshot."],
        }
        self._write_record()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_record(self):
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")

    def _validate(self):
        return validate_cohort_review_record(
            self.record_path, self.cohort_dir, self.task_path, self.manifest_path,
        )

    def test_approved_review_passes_when_all_exact_inputs_are_bound(self):
        report = self._validate()
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["reviewed_study_count"], 2)
        self.assertEqual(report["reviewed_observation_count"], 2)

    def test_changed_cohort_input_invalidates_review(self):
        with self.csv_path.open("a", encoding="utf-8") as handle:
            handle.write("ROW_3,OBS_3,STUDY_3,validation\n")
        report = self._validate()
        self.assertFalse(report["valid"])
        self.assertIn("ARTIFACT_HASH_MISMATCH", {item["code"] for item in report["errors"]})

    def test_unestablished_independence_blocks_approval(self):
        self.record["independence_assessment"] = "NOT_ESTABLISHED"
        self._write_record()
        report = self._validate()
        self.assertFalse(report["valid"])
        self.assertIn("INDEPENDENCE_NOT_ESTABLISHED", {item["code"] for item in report["errors"]})

    def test_every_grain_warning_must_be_reviewed(self):
        self.record["reviewed_warning_codes"] = []
        self._write_record()
        report = self._validate()
        self.assertFalse(report["valid"])
        self.assertIn("GRAIN_WARNING_COVERAGE_MISMATCH", {item["code"] for item in report["errors"]})

    def test_observation_split_must_match_the_study_split_manifest(self):
        rows = list(csv.DictReader(self.csv_path.open("r", encoding="utf-8", newline="")))
        rows[0]["split"] = "test"
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.record["artifact_sha256"]["modeling_cohort.csv"] = hashlib.sha256(
            self.csv_path.read_bytes()
        ).hexdigest()
        self._write_record()
        report = self._validate()
        self.assertFalse(report["valid"])
        self.assertIn("COHORT_SPLIT_ASSIGNMENT_MISMATCH", {item["code"] for item in report["errors"]})

    def test_run_binding_is_mandatory_and_exact_when_manifest_is_supplied(self):
        self.record["run_id"] = "RUN_OTHER"
        self._write_record()
        report = self._validate()
        self.assertFalse(report["valid"])
        self.assertIn("RUN_ID_MISMATCH", {item["code"] for item in report["errors"]})

    def test_revise_decision_cannot_unlock_modelling(self):
        self.record["decision"] = "REVISE"
        self._write_record()
        report = self._validate()
        self.assertFalse(report["valid"])

    def test_cli_exposes_cohort_review_validation(self):
        args = build_parser().parse_args([
            "validate-cohort-review", "--record", "record.json",
            "--cohort-dir", "cohort", "--task", "task.json",
            "--manifest", "run_manifest.json", "--out", "validation.json",
        ])
        self.assertEqual(args.command, "validate-cohort-review")
        self.assertEqual(args.record, Path("record.json"))


if __name__ == "__main__":
    unittest.main()
