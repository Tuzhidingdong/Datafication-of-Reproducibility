from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.robustness import assess_interaction_robustness_files
from test_interactions import interaction_bundle, interaction_task


class InteractionRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle_path = self.root / "bundle.json"
        self.task_path = self.root / "task.json"
        self.cohort_dir = self.root / "cohort"
        self.bundle_path.write_text(json.dumps(interaction_bundle()), encoding="utf-8")
        self.task_path.write_text(json.dumps(interaction_task()), encoding="utf-8")
        result = build_modeling_cohort_files(self.bundle_path, self.task_path, self.cohort_dir)
        self.assertTrue(result["valid"], result)

    def tearDown(self):
        self.temp.cleanup()

    def test_repeated_seed_screen_recovers_stable_bilinear_signal(self):
        result = assess_interaction_robustness_files(
            self.cohort_dir, self.task_path, self.root / "robust",
            seeds=[11, 23, 42], folds=4
        )
        report = result["report"]
        self.assertEqual(report["seed_count"], 3)
        self.assertEqual(report["seeds"], [11, 23, 42])
        self.assertEqual(len(report["interaction_catalogue"]), 1)
        candidate = report["interaction_catalogue"][0]
        self.assertEqual(candidate["robustness_status"], "SEED_STABLE_PREDICTIVE_INTERACTION_CANDIDATE")
        self.assertEqual(candidate["candidate_run_count"], 3)
        self.assertGreater(candidate["median_mean_fold_rmse_improvement"], 0.5)
        self.assertTrue((self.root / "robust" / "interaction_robustness_manifest.json").is_file())

    def test_requires_three_unique_integer_seeds(self):
        with self.assertRaisesRegex(ValueError, "At least three"):
            assess_interaction_robustness_files(self.cohort_dir, self.task_path, self.root / "few", seeds=[1, 2])
        with self.assertRaisesRegex(ValueError, "unique"):
            assess_interaction_robustness_files(self.cohort_dir, self.task_path, self.root / "dup", seeds=[1, 1, 2])

    def test_inputs_remain_unchanged(self):
        paths = [self.task_path, self.cohort_dir / "modeling_cohort.csv",
                 self.cohort_dir / "cohort_report.json", self.cohort_dir / "split_manifest.json",
                 self.cohort_dir / "modeling_cohort_manifest.json"]
        before = {path: path.read_bytes() for path in paths}
        assess_interaction_robustness_files(self.cohort_dir, self.task_path, self.root / "readonly",
                                            seeds=[5, 6, 7], folds=4)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_nonempty_output_is_not_overwritten(self):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            assess_interaction_robustness_files(self.cohort_dir, self.task_path, output, seeds=[1, 2, 3])
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
