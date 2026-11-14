from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.interactions import discover_interactions_files
from test_modeling import make_bundle, make_task


def interaction_bundle():
    data=make_bundle()
    studies=data["studies"]
    systems=data["systems"]
    experiments=[]
    conditions=[]
    observations=[]
    for i,study in enumerate(studies):
        sid=study["study_id"]
        system_id=systems[i]["system_id"]
        for j,(x,z) in enumerate([(-1.0,-1.0),(-1.0,1.0),(1.0,-1.0),(1.0,1.0)]):
            exp_id="IX_"+str(i+1)+"_"+str(j+1)
            t_id="IT_"+str(i+1)+"_"+str(j+1)
            p_id="IP_"+str(i+1)+"_"+str(j+1)
            conditions.extend([
                {"condition_id":t_id,"system_ids":[system_id],"condition_type":"feature_01",
                 "raw_value":x,"raw_unit":"unit_01","normalized_value":x,"normalized_unit":"unit_01","value_state":"REPORTED"},
                {"condition_id":p_id,"system_ids":[system_id],"condition_type":"feature_02",
                 "raw_value":z,"raw_unit":"unit_02","normalized_value":z,"normalized_unit":"unit_02","value_state":"REPORTED"}
            ])
            experiments.append({"experiment_id":exp_id,"study_id":sid,"system_id":system_id,
                                 "condition_ids":[t_id,p_id]})
            y=x*z
            observations.append({"observation_id":"IO_"+str(i+1)+"_"+str(j+1),
                "experiment_id":exp_id,"target_id":"TARGET_Y","raw_value":y,"raw_unit":"unit-y",
                "normalized_value":y,"normalized_unit":"unit-y","value_state":"REPORTED",
                "endpoint_definition":"synthetic endpoint","evidence_ids":[]})
    data["conditions"]=conditions
    data["experiments"]=experiments
    data["observations"]=observations
    return data


def interaction_task():
    task=make_task()
    task["feature_bindings"]=[
        {"feature_id":"feature_01","condition_type":"feature_01","value_field":"normalized_value",
         "value_type":"NUMERIC","expected_unit":"unit_01"},
        {"feature_id":"feature_02","condition_type":"feature_02","value_field":"normalized_value",
         "value_type":"NUMERIC","expected_unit":"unit_02"}
    ]
    task["interaction_discovery"]={
        "minimum_joint_observations":16,"minimum_joint_studies":8,
        "minimum_positive_fold_fraction":0.6,"maximum_feature_pairs":10,
        "maximum_interaction_columns":100
    }
    task["modeling"]["ridge_alphas"]=[0.001,0.01,0.1,1.0]
    return task


class InteractionDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.bundle_path=self.root/"bundle.json"
        self.task_path=self.root/"task.json"
        self.cohort_dir=self.root/"cohort"
        self.bundle_path.write_text(json.dumps(interaction_bundle()),encoding="utf-8")
        self.task_path.write_text(json.dumps(interaction_task()),encoding="utf-8")
        built=build_modeling_cohort_files(self.bundle_path,self.task_path,self.cohort_dir)
        self.assertTrue(built["valid"],built)

    def _build_custom_cohort(self, task, name):
        task_path=self.root/(name+"_task.json")
        cohort_dir=self.root/(name+"_cohort")
        task_path.write_text(json.dumps(task),encoding="utf-8")
        result=build_modeling_cohort_files(self.bundle_path,task_path,cohort_dir)
        self.assertTrue(result["valid"],result)
        return task_path,cohort_dir

    def tearDown(self):
        self.temp.cleanup()

    def test_recovers_supported_bilinear_predictive_interaction(self):
        out=self.root/"interaction"
        result=discover_interactions_files(self.cohort_dir,self.task_path,out,folds=4,seed=19)
        report=result["report"]
        self.assertEqual(report["method"],"NESTED_STUDY_GROUPED_PAIRWISE_BILINEAR_RIDGE_ABLATION")
        self.assertEqual(report["eligible_pair_count"],1)
        candidate=report["interaction_catalogue"][0]
        self.assertEqual({candidate["feature_a"],candidate["feature_b"]},{"feature_02","feature_01"})
        self.assertEqual(candidate["interpretation_status"],"CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE")
        self.assertGreater(candidate["mean_fold_rmse_improvement"],0.5)
        self.assertGreaterEqual(candidate["positive_improvement_fold_fraction"],0.6)
        self.assertEqual(candidate["joint_coverage"]["study_count"],8)
        self.assertTrue((out/"interaction_catalogue.csv").is_file())
        self.assertTrue((out/"interaction_oof_predictions.csv").is_file())
        self.assertTrue((out/"interaction_discovery_manifest.json").is_file())

    def test_outer_test_studies_never_appear_in_inner_training_or_validation(self):
        report=discover_interactions_files(self.cohort_dir,self.task_path,self.root/"leakage",folds=4)["report"]
        held=[]
        for fold in report["fold_protocol"]:
            held.extend(fold["held_out_study_ids"])
            self.assertFalse(set(fold["held_out_study_ids"]) & set(fold["outer_training_study_ids"]))
            self.assertFalse(set(fold["held_out_study_ids"]) & set(fold["inner_training_study_ids"]))
            self.assertFalse(set(fold["held_out_study_ids"]) & set(fold["inner_validation_study_ids"]))
            self.assertFalse(set(fold["inner_training_study_ids"]) & set(fold["inner_validation_study_ids"]))
        self.assertEqual(sorted(held),["ST1","ST2","ST3","ST4","ST5","ST6","ST7","ST8"])

    def test_reproducible_results(self):
        a=discover_interactions_files(self.cohort_dir,self.task_path,self.root/"run_a",folds=4,seed=21)
        b=discover_interactions_files(self.cohort_dir,self.task_path,self.root/"run_b",folds=4,seed=21)
        self.assertEqual(a["report"]["interaction_catalogue"],b["report"]["interaction_catalogue"])
        self.assertEqual(a["report"]["fold_protocol"],b["report"]["fold_protocol"])

    def test_categorical_endpoint_is_rejected_explicitly(self):
        task=interaction_task()
        task["outcome_type"]="CATEGORICAL"
        task["outcome_unit"]="unit-y"
        task_path,cohort_dir=self._build_custom_cohort(task,"categorical")
        with self.assertRaisesRegex(ValueError,"NUMERIC endpoints only"):
            discover_interactions_files(cohort_dir,task_path,self.root/"categorical")

    def test_insufficient_joint_study_support_is_reported(self):
        task=interaction_task()
        task["interaction_discovery"]["minimum_joint_studies"]=9
        task_path,cohort_dir=self._build_custom_cohort(task,"strict")
        with self.assertRaisesRegex(ValueError,"No candidate feature pairs meet"):
            discover_interactions_files(cohort_dir,task_path,self.root/"strict")

    def test_unknown_or_duplicate_pair_is_rejected(self):
        task=interaction_task()
        task["interaction_discovery"]["feature_pairs"]=[
            {"feature_a":"feature_01","feature_b":"missing"}]
        task_path,cohort_dir=self._build_custom_cohort(task,"bad_pair")
        with self.assertRaisesRegex(ValueError,"feature_id values"):
            discover_interactions_files(cohort_dir,task_path,self.root/"bad_pair")

    def test_pair_count_cap_prevents_unbounded_combinatorics(self):
        task=interaction_task()
        task["interaction_discovery"]["maximum_feature_pairs"]=0
        task_path,cohort_dir=self._build_custom_cohort(task,"bad_cap")
        with self.assertRaisesRegex(ValueError,"maximum_feature_pairs"):
            discover_interactions_files(cohort_dir,task_path,self.root/"bad_cap")

    def test_pair_encoding_cap_excludes_pair_from_entire_cross_validation(self):
        task=interaction_task()
        task["feature_bindings"][1]["value_type"]="CATEGORICAL"
        task["interaction_discovery"]["maximum_interaction_columns"]=1
        task_path,cohort_dir=self._build_custom_cohort(task,"limited_encoding")
        report=discover_interactions_files(cohort_dir,task_path,self.root/"limited_encoding_out",folds=4)["report"]
        self.assertEqual(report["support_eligible_pair_count"],1)
        self.assertEqual(report["eligible_pair_count"],0)
        self.assertEqual(report["excluded_pair_count"],1)
        self.assertEqual(report["exclusions"][0]["reason"],"PAIR_INTERACTION_ENCODING_EXCEEDS_LIMIT")
        self.assertEqual(report["exclusions"][0]["folds"],[1,2,3,4])
        self.assertEqual(report["interaction_catalogue"],[])

    def test_inputs_remain_unchanged(self):
        paths=[self.task_path,self.cohort_dir/"modeling_cohort.csv",
               self.cohort_dir/"cohort_report.json",self.cohort_dir/"split_manifest.json",
               self.cohort_dir/"modeling_cohort_manifest.json"]
        before={path:path.read_bytes() for path in paths}
        discover_interactions_files(self.cohort_dir,self.task_path,self.root/"read_only",folds=4)
        self.assertEqual(before,{path:path.read_bytes() for path in paths})

    def test_nonempty_output_is_not_overwritten(self):
        out=self.root/"existing"; out.mkdir(); marker=out/"marker.txt"; marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            discover_interactions_files(self.cohort_dir,self.task_path,out,folds=4)
        self.assertEqual(marker.read_text(encoding="utf-8"),"keep")


if __name__=="__main__":
    unittest.main()
