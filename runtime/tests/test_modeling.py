from __future__ import annotations
import copy, csv, json, tempfile, unittest
from pathlib import Path
from dor.cohort import build_modeling_cohort_files
from dor.modeling import run_baseline_models_files

def make_bundle(categorical=False):
    data={"schema_version":"1.0","project_id":"P_MODEL","mapping_version":"map-1",
          "studies":[],"systems":[],"conditions":[],"experiments":[],"observations":[],"comparisons":[],"evidence":[]}
    for i in range(8):
        sid="ST"+str(i+1); syid="SY"+str(i+1); tempid="CT"+str(i+1); catid="CC"+str(i+1); exid="EX"+str(i+1)
        data["studies"].append({"study_id":sid,"doi":"10.2000/"+str(i+1),"source_locators":[]})
        data["systems"].append({"system_id":syid,"study_ids":[sid],"system_type":"test_system"})
        data["conditions"].append({"condition_id":tempid,"system_ids":[syid],"condition_type":"temperature",
            "raw_value":float(20+i),"raw_unit":"degC","normalized_value":float(20+i),"normalized_unit":"degC","value_state":"REPORTED"})
        data["conditions"].append({"condition_id":catid,"system_ids":[syid],"condition_type":"electrolyte",
            "raw_value":"salt-A" if i%2==0 else "salt-B","raw_unit":None,
            "normalized_value":"salt-A" if i%2==0 else "salt-B","normalized_unit":None,"value_state":"REPORTED"})
        data["experiments"].append({"experiment_id":exid,"study_id":sid,"system_id":syid,"condition_ids":[tempid,catid]})
        y=("A" if i%2==0 else "B") if categorical else float(2*i+1)
        data["observations"].append({"observation_id":"OB"+str(i+1),"experiment_id":exid,"target_id":"TARGET_Y",
            "raw_value":y,"raw_unit":"class" if categorical else "unit-y",
            "normalized_value":y,"normalized_unit":"class" if categorical else "unit-y",
            "value_state":"REPORTED","endpoint_definition":"exact endpoint A","evidence_ids":[]})
    return data

def make_task(categorical=False):
    return {
        "schema_version":"1.0","task_id":"TASK_MODEL","target_id":"TARGET_Y",
        "endpoint_definition":"exact endpoint A","outcome_type":"CATEGORICAL" if categorical else "NUMERIC",
        "outcome_value_field":"normalized_value","outcome_unit":"class" if categorical else "unit-y",
        "feature_bindings":[
            {"feature_id":"temperature","condition_type":"temperature","value_field":"normalized_value","value_type":"NUMERIC","expected_unit":"degC"},
            {"feature_id":"electrolyte","condition_type":"electrolyte","value_field":"normalized_value","value_type":"CATEGORICAL","expected_unit":None}
        ],
        "split":{"strategy":"EXPLICIT_STUDIES","validation_study_ids":["ST5","ST6"],"test_study_ids":["ST7","ST8"]},
        "modeling":{"ridge_alphas":[0.01,0.1,1.0,10.0],"max_iter":2000,"tolerance":1e-8,
                    "naive_bayes_smoothing":[0.1,1.0,10.0],"naive_bayes_variance_floor":1e-6}
    }

class BaselineModelEngineTests(unittest.TestCase):
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

    def test_numeric_engine_selects_on_validation_and_evaluates_test(self):
        out=self.root/"model"
        result=run_baseline_models_files(self.cohort_dir,self.task_path,out)
        self.assertTrue(result["valid"],result)
        report=result["report"]
        self.assertEqual(report["outcome_type"],"NUMERIC")
        self.assertEqual(report["validation_observation_count"],2)
        self.assertEqual(report["test_observation_count"],2)
        self.assertEqual(len(report["validation_comparison"]),5)
        self.assertIn("rmse",report["test_evaluation"]["selected_model"])
        self.assertIn("mean_baseline",report["test_evaluation"])
        self.assertTrue((out/"model_artifact.json").is_file())
        self.assertTrue((out/"test_predictions.csv").is_file())
        self.assertTrue((out/"validation_model_comparison.csv").is_file())
        self.assertTrue((out/"modeling_run_manifest.json").is_file())

    def test_final_model_artifact_excludes_test_observations_from_fit(self):
        result=run_baseline_models_files(self.cohort_dir,self.task_path,self.root/"model")
        artifact=result["artifact"]
        self.assertNotIn("OB7",artifact["training_observation_ids"])
        self.assertNotIn("OB8",artifact["training_observation_ids"])
        self.assertEqual(set(artifact["test_observation_ids"]),{"OB7","OB8"})
        self.assertEqual(set(artifact["training_observation_ids"]),{"OB1","OB2","OB3","OB4","OB5","OB6"})

    def test_categorical_engine_compares_majority_and_mixed_naive_bayes(self):
        task_path=self.root/"categorical_task.json"
        task_path.write_text(json.dumps(make_task(categorical=True)),encoding="utf-8")
        categorical_bundle=self.root/"categorical_bundle.json"
        categorical_bundle.write_text(json.dumps(make_bundle(categorical=True)),encoding="utf-8")
        cohort_dir=self.root/"categorical_cohort"
        built=build_modeling_cohort_files(categorical_bundle,task_path,cohort_dir)
        self.assertTrue(built["valid"],built)
        result=run_baseline_models_files(cohort_dir,task_path,self.root/"categorical_model")
        self.assertTrue(result["valid"],result)
        self.assertEqual(result["report"]["outcome_type"],"CATEGORICAL")
        self.assertEqual(len(result["report"]["validation_comparison"]),4)
        self.assertIn("macro_f1",result["report"]["test_evaluation"]["selected_model"])
        self.assertEqual(len(result["artifact"]["test_observation_ids"]),2)

    def test_test_set_values_do_not_change_validation_model_selection(self):
        first=run_baseline_models_files(self.cohort_dir,self.task_path,self.root/"model1")
        altered=make_bundle()
        altered["observations"][6]["normalized_value"]=1000000.0
        altered["observations"][7]["normalized_value"]=-1000000.0
        bundle2=self.root/"bundle2.json"; bundle2.write_text(json.dumps(altered),encoding="utf-8")
        cohort2=self.root/"cohort2"
        self.assertTrue(build_modeling_cohort_files(bundle2,self.task_path,cohort2)["valid"])
        second=run_baseline_models_files(cohort2,self.task_path,self.root/"model2")
        self.assertEqual(first["report"]["selected_candidate_id"],second["report"]["selected_candidate_id"])
        self.assertEqual(first["report"]["validation_comparison"],second["report"]["validation_comparison"])

    def test_stale_cohort_csv_hash_is_rejected(self):
        path=self.cohort_dir/"modeling_cohort.csv"
        path.write_text(path.read_text(encoding="utf-8")+"\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"hash is missing or stale"):
            run_baseline_models_files(self.cohort_dir,self.task_path,self.root/"model")

    def test_task_hash_mismatch_is_rejected(self):
        task=self.root/"changed_task.json"
        changed=make_task(); changed["modeling"]["ridge_alphas"]=[0.5,2.0]
        task.write_text(json.dumps(changed),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"task hash"):
            run_baseline_models_files(self.cohort_dir,task,self.root/"model")

    def test_split_study_assignment_tampering_is_rejected(self):
        split_path=self.cohort_dir/"split_manifest.json"
        split=json.loads(split_path.read_text(encoding="utf-8"))
        split["study_to_split"]["ST1"]="test"
        split_path.write_text(json.dumps(split),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"hash is missing or stale"):
            run_baseline_models_files(self.cohort_dir,self.task_path,self.root/"model")

    def test_input_files_are_not_modified(self):
        before={p:p.read_bytes() for p in (self.task_path,self.cohort_dir/"modeling_cohort.csv",
            self.cohort_dir/"cohort_report.json",self.cohort_dir/"split_manifest.json",
            self.cohort_dir/"modeling_cohort_manifest.json")}
        run_baseline_models_files(self.cohort_dir,self.task_path,self.root/"model")
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_nonempty_output_directory_is_never_overwritten(self):
        out=self.root/"existing"; out.mkdir(); marker=out/"marker.txt"; marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            run_baseline_models_files(self.cohort_dir,self.task_path,out)
        self.assertEqual(marker.read_text(),"keep")

    def test_numeric_strings_are_not_silently_parsed_as_canonical_features(self):
        data=make_bundle()
        data["conditions"][0]["normalized_value"]="20.0"
        bundle_path=self.root/"numeric_string_bundle.json"
        bundle_path.write_text(json.dumps(data),encoding="utf-8")
        cohort_dir=self.root/"numeric_string_cohort"
        result=build_modeling_cohort_files(bundle_path,self.task_path,cohort_dir)
        self.assertTrue(result["valid"],result)
        excluded={item["observation_id"]:item["reason"] for item in result["report"]["excluded"]}
        self.assertEqual(excluded["OB1"],"FEATURE_VALUE_NOT_VALID_NUMERIC")

if __name__=="__main__":
    unittest.main()
