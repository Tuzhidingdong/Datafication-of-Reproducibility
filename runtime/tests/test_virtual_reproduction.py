from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.mapping import sha256_file
from dor.modeling import run_baseline_models_files
from dor.virtual_reproduction import predict_virtual_condition_files
from test_modeling import make_bundle, make_task


class VirtualReproductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle.json"
        self.task = self.root / "task.json"
        self.cohort = self.root / "cohort"
        self.model_dir = self.root / "model"
        self.query = self.root / "query.json"
        self.output = self.root / "prediction.json"
        self.bundle.write_text(json.dumps(make_bundle()), encoding="utf-8")
        self.task.write_text(json.dumps(make_task()), encoding="utf-8")
        self.assertTrue(build_modeling_cohort_files(self.bundle, self.task, self.cohort)["valid"])
        run_baseline_models_files(self.cohort, self.task, self.model_dir)

    def tearDown(self):
        self.temp.cleanup()

    def write_query(self, temperature=24.0, electrolyte="salt-A", unit="degC"):
        query = {
            "schema_version": "1.0",
            "task_id": "TASK_MODEL",
            "target_id": "TARGET_Y",
            "endpoint_definition": "exact endpoint A",
            "features": {
                "temperature": {"value": temperature, "unit": unit},
                "electrolyte": {"value": electrolyte, "unit": None}
            }
        }
        self.query.write_text(json.dumps(query), encoding="utf-8")

    def test_predicts_from_serialized_selected_model_and_reports_limits(self):
        self.write_query()
        result = predict_virtual_condition_files(self.model_dir, self.query, self.output)
        report = result["report"]
        self.assertTrue(result["valid"])
        self.assertIsInstance(report["prediction"], (int, float))
        self.assertEqual(report["uncertainty_status"], "NOT_CALIBRATED")
        self.assertEqual(report["support_assessment"]["per_feature"][0]["training_range"], [20.0, 25.0])
        self.assertFalse(report["provenance"]["test_set_used_for_fit_or_selection"])
        self.assertTrue(any("NOT_A_PHYSICAL_REPRODUCTION" in item for item in report["warnings"]))
        self.assertTrue(self.output.is_file())

    def test_out_of_range_and_unknown_category_are_not_silent(self):
        self.write_query(temperature=100.0, electrolyte="salt-Z")
        report = predict_virtual_condition_files(self.model_dir, self.query, self.output)["report"]
        statuses = {item["feature_id"]: item["status"] for item in report["support_assessment"]["per_feature"]}
        self.assertEqual(statuses["temperature"], "OUTSIDE_TRAINING_RANGE")
        self.assertEqual(statuses["electrolyte"], "UNKNOWN_CATEGORY")
        self.assertEqual(report["prediction_status"], "EXTRAPOLATIVE_OR_UNKNOWN_CATEGORY_SCENARIO")

    def test_exact_units_are_required(self):
        self.write_query(unit="K")
        with self.assertRaisesRegex(ValueError, "exactly match"):
            predict_virtual_condition_files(self.model_dir, self.query, self.output)

    def test_missing_and_extra_feature_ids_fail_closed(self):
        self.write_query()
        query = json.loads(self.query.read_text(encoding="utf-8"))
        query["features"].pop("electrolyte")
        self.query.write_text(json.dumps(query), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must match exactly"):
            predict_virtual_condition_files(self.model_dir, self.query, self.output)

    def test_stale_model_artifact_hash_is_rejected(self):
        self.write_query()
        artifact = self.model_dir / "model_artifact.json"
        artifact.write_text(artifact.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash is missing or stale"):
            predict_virtual_condition_files(self.model_dir, self.query, self.output)

    def test_prediction_refuses_to_overwrite_output(self):
        self.write_query()
        self.output.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            predict_virtual_condition_files(self.model_dir, self.query, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
