from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.interactions import discover_interactions_files
from dor.robustness import assess_interaction_robustness_files
from dor.response_surface import generate_interaction_surface_files
from test_interactions import interaction_bundle, interaction_task


class InteractionResponseSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle_path = self.root / "bundle.json"
        self.task_path = self.root / "task.json"
        self.cohort_dir = self.root / "cohort"
        self.interaction_dir = self.root / "interactions"
        self.bundle_path.write_text(json.dumps(interaction_bundle()), encoding="utf-8")
        self.task = interaction_task()
        self.task["interaction_surface"] = {"grid_size": 9, "background_max_observations": 100}
        self.task_path.write_text(json.dumps(self.task), encoding="utf-8")
        built = build_modeling_cohort_files(self.bundle_path, self.task_path, self.cohort_dir)
        self.assertTrue(built["valid"], built)
        discovered = discover_interactions_files(self.cohort_dir, self.task_path, self.interaction_dir, folds=4, seed=19)
        self.interaction_id = discovered["report"]["interaction_catalogue"][0]["interaction_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_generates_surface_support_and_marginal_effects(self):
        output = self.root / "surface"
        result = generate_interaction_surface_files(self.cohort_dir, self.task_path,
            self.interaction_dir, self.interaction_id, output)
        report = result["report"]
        self.assertEqual(report["prediction_mode"], "PARTIAL_DEPENDENCE_AVERAGED_OVER_EMPIRICAL_BACKGROUND")
        self.assertEqual(report["grid"]["grid_point_count"], 81)
        self.assertEqual(report["cohort"]["study_count"], 8)
        self.assertGreater(report["empirical_support"]["distance_threshold"], 0)
        self.assertLessEqual(report["cohort"]["partial_dependence_prediction_evaluations"], 500000)
        self.assertAlmostEqual(report["marginal_effects"]["cross_partial_derivative"], 1.0, places=2)
        with (output / "interaction_response_surface.csv").open(encoding="utf-8") as handle:
            rows = list(__import__("csv").DictReader(handle))
        center = min(rows, key=lambda item: abs(float(item["feature_a_value"])) + abs(float(item["feature_b_value"])))
        self.assertAlmostEqual(float(center["predicted_mean"]), 0.0, places=5)
        self.assertIn("SUPPORTED_EMPIRICAL_2D_REGION", {item["support_status"] for item in rows})
        for filename in ("interaction_observed_support.csv", "interaction_marginal_effects.csv",
                         "interaction_response_surface_manifest.json"):
            self.assertTrue((output / filename).is_file())

    def test_optional_robustness_status_is_linked(self):
        robustness_dir = self.root / "robustness"
        robust = assess_interaction_robustness_files(self.cohort_dir, self.task_path,
            robustness_dir, seeds=[11, 23, 42], folds=4)
        output = self.root / "with_robustness"
        result = generate_interaction_surface_files(self.cohort_dir, self.task_path,
            self.interaction_dir, self.interaction_id, output, robustness_dir=robustness_dir)
        self.assertEqual(result["report"]["robustness_status"], "SEED_STABLE_PREDICTIVE_INTERACTION_CANDIDATE")

    def test_rejects_categorical_feature_pair(self):
        task = interaction_task()
        task["feature_bindings"][1]["value_type"] = "CATEGORICAL"
        task_path = self.root / "categorical_task.json"
        cohort_dir = self.root / "categorical_cohort"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        built = build_modeling_cohort_files(self.bundle_path, task_path, cohort_dir)
        self.assertTrue(built["valid"], built)
        interaction_dir = self.root / "categorical_interactions"
        discovered = discover_interactions_files(cohort_dir, task_path, interaction_dir, folds=4)
        iid = discovered["report"]["interaction_catalogue"][0]["interaction_id"]
        with self.assertRaisesRegex(ValueError, "numeric × numeric"):
            generate_interaction_surface_files(cohort_dir, task_path, interaction_dir, iid, self.root / "categorical_surface")

    def test_rejects_mismatched_interaction_manifest(self):
        report_path = self.interaction_dir / "interaction_discovery_report.json"
        report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            generate_interaction_surface_files(self.cohort_dir, self.task_path,
                self.interaction_dir, self.interaction_id, self.root / "bad_hash")

    def test_inputs_remain_unchanged(self):
        paths = [self.task_path, self.cohort_dir / "modeling_cohort.csv",
                 self.cohort_dir / "cohort_report.json", self.cohort_dir / "split_manifest.json",
                 self.cohort_dir / "modeling_cohort_manifest.json",
                 self.interaction_dir / "interaction_discovery_report.json",
                 self.interaction_dir / "interaction_discovery_manifest.json"]
        before = {path: path.read_bytes() for path in paths}
        generate_interaction_surface_files(self.cohort_dir, self.task_path,
            self.interaction_dir, self.interaction_id, self.root / "readonly")
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_partial_dependence_work_is_bounded(self):
        task = dict(self.task)
        task["interaction_surface"] = {"grid_size": 61, "background_max_observations": 5000}
        task_path = self.root / "large_task.json"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        cohort_dir = self.root / "large_cohort"
        built = build_modeling_cohort_files(self.bundle_path, task_path, cohort_dir)
        self.assertTrue(built["valid"], built)
        interaction_dir = self.root / "large_interactions"
        discovered = discover_interactions_files(cohort_dir, task_path, interaction_dir, folds=4)
        iid = discovered["report"]["interaction_catalogue"][0]["interaction_id"]
        with self.assertRaisesRegex(ValueError, "bounded partial-dependence evaluation budget"):
            generate_interaction_surface_files(cohort_dir, task_path, interaction_dir, iid,
                self.root / "large_surface")

    def test_nonempty_output_is_not_overwritten(self):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            generate_interaction_surface_files(self.cohort_dir, self.task_path,
                self.interaction_dir, self.interaction_id, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
