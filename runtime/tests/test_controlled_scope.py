from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.controlled_scope import (
    validate_single_study_applicability_files,
    prepare_single_study_not_applicable_artifacts_files,
)
from test_cohort import fixture_bundle, task


class ControlledSingleStudyApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dor-single-study-")
        self.root = Path(self.temp.name)
        self.run_root = self.root / "run"
        self.run_root.mkdir()
        self.bundle_path = self.run_root / "03_canonical" / "canonical_bundle.json"
        self.task_path = self.run_root / "05_scope" / "modeling_task.json"
        self.record_path = self.run_root / "05_scope" / "single_study_applicability_record.json"
        self.validation_path = self.run_root / "05_scope" / "single_study_applicability_validation.json"
        self.output_dir = self.run_root / "06_modeling" / "not_applicable"
        self.manifest_path = self.run_root / "run_manifest.json"
        self.manifest_path.write_text("{}\\n", encoding="utf-8")

        bundle = fixture_bundle()
        bundle["studies"] = [item for item in bundle["studies"] if item["study_id"] == "ST1"]
        bundle["systems"] = [item for item in bundle["systems"] if item["system_id"] == "SY1"]
        bundle["conditions"] = [item for item in bundle["conditions"] if item["condition_id"] == "CO1"]
        bundle["experiments"] = [item for item in bundle["experiments"] if item["experiment_id"] == "EX1"]
        bundle["observations"] = [
            item for item in bundle["observations"]
            if item.get("experiment_id") == "EX1"
            and item.get("endpoint_definition") == "synthetic outcome definition"
            and item.get("value_state") == "REPORTED"
        ]
        self.bundle = bundle
        self.task = task()
        self._write_json(self.bundle_path, bundle)
        self._write_json(self.task_path, self.task)

        self.plan = {
            "execution_profile": "CONTROLLED_SINGLE_STUDY",
            "source_artifacts": [],
            "stages": [{
                "stage_id": "single_study_artifact_contract",
                "outputs": [
                    {"artifact_id": "canonical_bundle", "path": "03_canonical/canonical_bundle.json"},
                    {"artifact_id": "modeling_task", "path": "05_scope/modeling_task.json"},
                    {"artifact_id": "single_study_applicability_record", "path": "05_scope/single_study_applicability_record.json"},
                    {"artifact_id": "single_study_applicability_validation", "path": "05_scope/single_study_applicability_validation.json"},
                    {"artifact_id": "model_report", "path": "06_modeling/not_applicable/model_report.json"},
                    {"artifact_id": "reproducibility_evaluation", "path": "06_modeling/not_applicable/reproducibility_evaluation.json"},
                    {"artifact_id": "interaction_report", "path": "06_modeling/not_applicable/interaction_discovery_report.json"},
                    {"artifact_id": "interaction_manifest", "path": "06_modeling/not_applicable/interaction_discovery_manifest.json"},
                    {"artifact_id": "robustness_report", "path": "06_modeling/not_applicable/interaction_robustness_report.json"},
                    {"artifact_id": "robustness_manifest", "path": "06_modeling/not_applicable/interaction_robustness_manifest.json"},
                    {"artifact_id": "virtual_prediction", "path": "06_modeling/not_applicable/virtual_prediction.json"},
                ],
            }],
        }
        self.manifest = {"run_id": "RUN_SINGLE_1", "project_id": "PROJECT_SINGLE_1"}
        self.patches = (
            patch("dor.controlled_scope._manifest_context",
                  return_value=(self.run_root, self.manifest, self.plan, [])),
            patch("dor.controlled_scope.verify_run",
                  return_value={"source_integrity": "CURRENT"}),
        )
        for item in self.patches:
            item.start()
        self.addCleanup(self._stop_patches)

        self.record = {
            "schema_version": "1.0",
            "run_id": self.manifest["run_id"],
            "project_id": self.manifest["project_id"],
            "scope": "CONTROLLED_SINGLE_STUDY",
            "applicability_status": "NOT_APPLICABLE",
            "study_ids": ["ST1"],
            "study_count": 1,
            "canonical_bundle_sha256": self._sha(self.bundle_path),
            "modeling_task_sha256": self._sha(self.task_path),
            "cohort_feasibility_status": "NOT_APPLICABLE",
            "cohort_feasibility_reason": "One eligible Study cannot form independent train, validation, and test Study partitions.",
            "modeling_validation_status": "NOT_APPLICABLE",
            "modeling_validation_reason": "Cross-Study held-out model and nested reproducibility validation are not scientifically identifiable from one independent Study.",
            "reviewer": "synthetic-reviewer",
            "reviewed_at": "2026-11-15T12:00:00+08:00",
            "rationale": "Synthetic fixture only; no model or cross-Study validation is claimed.",
        }
        self._write_json(self.record_path, self.record)

    def tearDown(self):
        self.temp.cleanup()

    def _stop_patches(self):
        for item in reversed(self.patches):
            item.stop()

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")

    def test_exact_single_eligible_study_validates_and_generates_only_na_records(self):
        result = validate_single_study_applicability_files(
            self.record_path, self.bundle_path, self.task_path,
            self.manifest_path, self.validation_path,
        )
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["study_ids"], ["ST1"])
        self.assertEqual(result["eligible_study_count"], 1)
        self._write_json(self.validation_path, result)

        prepared = prepare_single_study_not_applicable_artifacts_files(
            self.record_path, self.validation_path, self.bundle_path,
            self.task_path, self.manifest_path, self.output_dir,
        )
        self.assertTrue(prepared["valid"], prepared)
        self.assertEqual(prepared["applicability_status"], "NOT_APPLICABLE")
        self.assertEqual(len(prepared["artifacts"]), 7)
        for artifact_id, item in prepared["artifacts"].items():
            path = Path(item["path"])
            self.assertTrue(path.is_file(), artifact_id)
            self.assertEqual(self._sha(path), item["sha256"], artifact_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["applicability_status"], "NOT_APPLICABLE")
            self.assertEqual(payload["study_ids"], ["ST1"])
            self.assertNotIn("validation_metrics", payload)
            self.assertNotIn("test_evaluation", payload)
            self.assertNotIn("predicted_value", payload)
            self.assertNotIn("folds", payload)
            self.assertNotIn("per_study_performance", payload)

    def test_two_studies_are_rejected_instead_of_being_marked_not_applicable(self):
        bundle = fixture_bundle()
        self._write_json(self.bundle_path, bundle)
        with self.assertRaisesRegex(ValueError, "exactly one Study"):
            validate_single_study_applicability_files(
                self.record_path, self.bundle_path, self.task_path,
                self.manifest_path, self.validation_path,
            )

    def test_task_with_no_eligible_study_is_not_misclassified_as_single_study(self):
        invalid_task = dict(self.task)
        invalid_task["endpoint_definition"] = "no matching endpoint"
        self._write_json(self.task_path, invalid_task)
        self.record["modeling_task_sha256"] = self._sha(self.task_path)
        self._write_json(self.record_path, self.record)
        with self.assertRaisesRegex(ValueError, "exactly one eligible Study"):
            validate_single_study_applicability_files(
                self.record_path, self.bundle_path, self.task_path,
                self.manifest_path, self.validation_path,
            )

    def test_record_with_stale_bundle_hash_is_rejected(self):
        self.record["canonical_bundle_sha256"] = "f" * 64
        self._write_json(self.record_path, self.record)
        with self.assertRaisesRegex(ValueError, "exact Canonical Bundle"):
            validate_single_study_applicability_files(
                self.record_path, self.bundle_path, self.task_path,
                self.manifest_path, self.validation_path,
            )

    def test_validation_output_path_must_match_run_plan(self):
        with self.assertRaisesRegex(ValueError, "differs from the exact active Run Plan"):
            validate_single_study_applicability_files(
                self.record_path, self.bundle_path, self.task_path,
                self.manifest_path, self.run_root / "wrong_validation.json",
            )

    def test_na_output_directory_must_match_all_seven_declared_output_paths(self):
        result = validate_single_study_applicability_files(
            self.record_path, self.bundle_path, self.task_path,
            self.manifest_path, self.validation_path,
        )
        self._write_json(self.validation_path, result)
        with self.assertRaisesRegex(ValueError, "output path differs"):
            prepare_single_study_not_applicable_artifacts_files(
                self.record_path, self.validation_path, self.bundle_path,
                self.task_path, self.manifest_path, self.run_root / "wrong_output",
            )

    def test_nonempty_na_output_directory_is_never_overwritten(self):
        result = validate_single_study_applicability_files(
            self.record_path, self.bundle_path, self.task_path,
            self.manifest_path, self.validation_path,
        )
        self._write_json(self.validation_path, result)
        self.output_dir.mkdir(parents=True)
        sentinel = self.output_dir / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            prepare_single_study_not_applicable_artifacts_files(
                self.record_path, self.validation_path, self.bundle_path,
                self.task_path, self.manifest_path, self.output_dir,
            )
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
