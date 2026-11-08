from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.reproducibility import evaluate_reproducibility_files
from test_modeling import make_bundle, make_task


class ReproducibilityEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.bundle_path=self.root/"bundle.json"
        self.task_path=self.root/"task.json"
        self.cohort_dir=self.root/"cohort"
        self.bundle_path.write_text(json.dumps(make_bundle()),encoding="utf-8")
        self.task_path.write_text(json.dumps(make_task()),encoding="utf-8")
        built=build_modeling_cohort_files(self.bundle_path,self.task_path,self.cohort_dir)
        self.assertTrue(built["valid"],built)

    def tearDown(self):
        self.temp.cleanup()

    def test_nested_grouped_evaluation_holds_each_study_out_once(self):
        out=self.root/"evaluation"
        result=evaluate_reproducibility_files(self.cohort_dir,self.task_path,out)
        self.assertTrue(result["valid"],result)
        report=result["report"]
        self.assertEqual(report["fold_count"],5)
        self.assertEqual(report["study_count"],8)
        self.assertEqual(report["observation_count"],8)
        self.assertIn("rmse",report["pooled_out_of_fold_metrics"])
        self.assertEqual(len(report["per_study_performance"]),8)
        self.assertEqual(len(list(out.glob("*"))),5)
        held=[]
        for fold in report["folds"]:
            held.extend(fold["test_study_ids"])
            self.assertFalse(set(fold["test_study_ids"]) & set(fold["outer_training_study_ids"]))
            self.assertFalse(set(fold["test_study_ids"]) & set(fold["inner_training_study_ids"]))
            self.assertFalse(set(fold["test_study_ids"]) & set(fold["inner_validation_study_ids"]))
            self.assertFalse(set(fold["inner_training_study_ids"]) & set(fold["inner_validation_study_ids"]))
        self.assertEqual(sorted(held),["ST1","ST2","ST3","ST4","ST5","ST6","ST7","ST8"])

    def test_categorical_nested_evaluation(self):
        bundle_path=self.root/"categorical_bundle.json"
        task_path=self.root/"categorical_task.json"
        cohort_dir=self.root/"categorical_cohort"
        bundle_path.write_text(json.dumps(make_bundle(categorical=True)),encoding="utf-8")
        task_path.write_text(json.dumps(make_task(categorical=True)),encoding="utf-8")
        built=build_modeling_cohort_files(bundle_path,task_path,cohort_dir)
        self.assertTrue(built["valid"],built)
        result=evaluate_reproducibility_files(cohort_dir,task_path,self.root/"categorical_evaluation")
        report=result["report"]
        self.assertEqual(report["outcome_type"],"CATEGORICAL")
        self.assertIn("macro_f1",report["pooled_out_of_fold_metrics"])
        self.assertIn("accuracy",report["pooled_baseline_metrics"])
        self.assertEqual(len(report["per_study_performance"]),8)

    def test_nested_cv_is_reproducible(self):
        one=evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"eval1")
        two=evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"eval2")
        self.assertEqual(one["report"]["folds"],two["report"]["folds"])
        self.assertEqual(one["report"]["per_study_performance"],two["report"]["per_study_performance"])
        self.assertEqual(one["report"]["pooled_out_of_fold_metrics"],two["report"]["pooled_out_of_fold_metrics"])

    def test_held_out_study_outside_numeric_range_is_flagged(self):
        data=make_bundle()
        for condition in data["conditions"]:
            if condition["condition_id"]=="CT8":
                condition["normalized_value"]=10000.0
                condition["raw_value"]=10000.0
        bundle_path=self.root/"outlier_bundle.json"
        bundle_path.write_text(json.dumps(data),encoding="utf-8")
        cohort_dir=self.root/"outlier_cohort"
        self.assertTrue(build_modeling_cohort_files(bundle_path,self.task_path,cohort_dir)["valid"])
        result=evaluate_reproducibility_files(cohort_dir,self.task_path,self.root/"outlier_eval")
        held_fold=next(f for f in result["report"]["folds"] if "ST8" in f["test_study_ids"])
        self.assertIn("ST8",held_fold["test_study_ids"])
        domain=json.loads((self.root/"outlier_eval"/"reproducibility_evaluation.json").read_text(encoding="utf-8"))
        row=next(x for x in domain["per_study_performance"] if x["study_id"]=="ST8")
        self.assertEqual(row["n"],1)
        domain_csv=(self.root/"outlier_eval"/"applicability_domain.csv").read_text(encoding="utf-8")
        self.assertIn("NUMERIC_FEATURE_OUTSIDE_REFERENCE_RANGE",domain_csv)

    def test_uncertainty_is_explicitly_not_calibrated(self):
        report=evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"uncertainty_eval")["report"]
        self.assertEqual(report["uncertainty"]["status"],"NOT_CALIBRATED")
        self.assertIn("not convert",report["uncertainty"]["reason"])

    def test_insufficient_studies_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"at least four eligible Studies"):
            evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"bad_eval",folds=3)

    def test_requested_folds_cannot_exceed_study_count(self):
        with self.assertRaisesRegex(ValueError,"exceed the number"):
            evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"bad_eval",folds=9)

    def test_nonempty_output_directory_is_protected(self):
        out=self.root/"keep"; out.mkdir(); marker=out/"marker.txt"; marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            evaluate_reproducibility_files(self.cohort_dir,self.task_path,out)
        self.assertEqual(marker.read_text(encoding="utf-8"),"keep")

    def test_cohort_inputs_remain_unchanged(self):
        paths=[self.task_path,self.cohort_dir/"modeling_cohort.csv",self.cohort_dir/"cohort_report.json",
               self.cohort_dir/"split_manifest.json",self.cohort_dir/"modeling_cohort_manifest.json"]
        before={path:path.read_bytes() for path in paths}
        evaluate_reproducibility_files(self.cohort_dir,self.task_path,self.root/"read_only_eval")
        self.assertEqual(before,{path:path.read_bytes() for path in paths})


if __name__=="__main__":
    unittest.main()
