from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from dor.cohort import build_modeling_cohort, build_modeling_cohort_files

def fixture_bundle():
    data={
        "schema_version":"1.0","project_id":"P1","mapping_version":"map-1",
        "studies":[],"systems":[],"conditions":[],"experiments":[],"observations":[],"comparisons":[],"evidence":[]
    }
    for i in range(4):
        sid="ST"+str(i+1); syid="SY"+str(i+1); cid="CO"+str(i+1); exid="EX"+str(i+1)
        data["studies"].append({"study_id":sid,"doi":"10.1000/"+str(i+1),"source_locators":[]})
        data["systems"].append({"system_id":syid,"study_ids":[sid],"system_type":"test_system"})
        data["conditions"].append({"condition_id":cid,"system_ids":[syid],"condition_type":"feature_01",
            "raw_value":20+i,"raw_unit":"unit_01","normalized_value":20+i,"normalized_unit":"unit_01","value_state":"REPORTED"})
        data["experiments"].append({"experiment_id":exid,"study_id":sid,"system_id":syid,"condition_ids":[cid]})
        data["observations"].append({"observation_id":"OB"+str(i+1),"experiment_id":exid,"target_id":"TARGET_01",
            "raw_value":90+i,"raw_unit":"unit_02","normalized_value":90+i,"normalized_unit":"unit_02",
            "value_state":"REPORTED","endpoint_definition":"synthetic outcome definition","evidence_ids":[]})
    data["observations"].append({"observation_id":"OB_STORAGE","experiment_id":"EX1","target_id":"TARGET_01",
        "raw_value":95,"raw_unit":"unit_02","normalized_value":95,"normalized_unit":"unit_02",
        "value_state":"REPORTED","endpoint_definition":"alternate synthetic outcome definition","evidence_ids":[]})
    data["observations"].append({"observation_id":"OB_MISSING","experiment_id":"EX1","target_id":"TARGET_01",
        "raw_value":None,"raw_unit":"unit_02","normalized_value":None,"normalized_unit":"unit_02",
        "value_state":"NOT_REPORTED","endpoint_definition":"synthetic outcome definition","evidence_ids":[]})
    return data

def task():
    return {
        "schema_version":"1.0","task_id":"TASK1","target_id":"TARGET_01",
        "endpoint_definition":"synthetic outcome definition","outcome_type":"NUMERIC",
        "outcome_value_field":"normalized_value","outcome_unit":"unit_02",
        "feature_bindings":[{"feature_id":"feature_01","condition_type":"feature_01",
            "value_field":"normalized_value","value_type":"NUMERIC","expected_unit":"unit_01"}],
        "split":{"strategy":"GROUPED_HOLDOUT","seed":42,"fractions":{"train":0.5,"validation":0.25,"test":0.25}}
    }

class ModelingCohortTests(unittest.TestCase):
    def test_exact_endpoint_and_missingness_are_kept_separate(self):
        rows,report,split=build_modeling_cohort(fixture_bundle(),task())
        self.assertTrue(report["valid"],report)
        self.assertEqual({r["observation_id"] for r in rows},{"OB1","OB2","OB3","OB4"})
        reasons={item["observation_id"]:item["reason"] for item in report["excluded"]}
        self.assertEqual(reasons["OB_STORAGE"],"ENDPOINT_DEFINITION_NOT_EXACT_MATCH")
        self.assertEqual(reasons["OB_MISSING"],"OUTCOME_NOT_REPORTED")

    def test_study_groups_never_cross_splits(self):
        rows,report,split=build_modeling_cohort(fixture_bundle(),task())
        by_study={}
        for row in rows:
            by_study.setdefault(row["study_id"],set()).add(row["split"])
        self.assertTrue(all(len(splits)==1 for splits in by_study.values()))
        self.assertEqual(split["leakage_check"]["study_overlap_count"],0)
        self.assertEqual(set(by_study),set(split["study_to_split"]))

    def test_seed_produces_reproducible_split(self):
        first=build_modeling_cohort(fixture_bundle(),task())[2]
        second=build_modeling_cohort(fixture_bundle(),task())[2]
        self.assertEqual(first["study_to_split"],second["study_to_split"])


    def test_repeated_observations_without_ids_are_flagged_but_never_collapsed(self):
        data=fixture_bundle()
        extra=copy.deepcopy(data["observations"][0])
        extra.update({"observation_id":"OB1_REPEAT","raw_value":88,"normalized_value":88})
        data["observations"].append(extra)
        rows,report,split=build_modeling_cohort(data,task())
        self.assertEqual(len(rows),5)
        grain=report["scientific_data_contract"]
        self.assertEqual(grain["observation_grain"]["groups_without_explicit_identity"],1)
        issue=next(item for item in grain["warnings"]
                   if item["code"]=="REPEATED_OBSERVATIONS_WITHOUT_EXPLICIT_IDENTITY")
        self.assertEqual(set(issue["observation_ids"]),{"OB1","OB1_REPEAT","OB_MISSING"})
        self.assertFalse(grain["observation_grain"]["automatic_observation_aggregation"])
        self.assertFalse(grain["observation_grain"]["assumed_independence"])

    def test_explicit_replicate_label_is_recorded_without_inferred_independence(self):
        data=fixture_bundle()
        extra=copy.deepcopy(data["observations"][0])
        extra.update({"observation_id":"OB1_REPEAT","raw_value":88,"normalized_value":88,
                      "replicate_id":"R2"})
        data["observations"][0]["replicate_id"]="R1"
        data["observations"][-1]["replicate_id"]="R0"
        data["observations"].append(extra)
        rows,report,split=build_modeling_cohort(data,task())
        self.assertEqual(len(rows),5)
        grain=report["scientific_data_contract"]
        self.assertEqual(grain["observation_grain"]["groups_with_explicit_identity_but_unverified_semantics"],1)
        issue=next(item for item in grain["warnings"]
                   if item["code"]=="EXPLICIT_IDENTIFIERS_PRESENT_SEMANTICS_UNVERIFIED")
        self.assertIn("not proof of independent replication",issue["interpretation"])
        self.assertFalse(grain["observation_grain"]["assumed_independence"])

    def test_multiple_observations_are_not_averaged_or_collapsed(self):
        data=fixture_bundle()
        extra=copy.deepcopy(data["observations"][0])
        extra.update({"observation_id":"OB1_REPEAT","raw_value":88,"normalized_value":88})
        data["observations"].append(extra)
        rows,report,split=build_modeling_cohort(data,task())
        self.assertEqual(len(rows),5)
        self.assertIn("OB1",{r["observation_id"] for r in rows})
        self.assertIn("OB1_REPEAT",{r["observation_id"] for r in rows})

    def test_multiple_linked_conditions_of_one_type_fail_closed(self):
        data=fixture_bundle()
        duplicate=copy.deepcopy(data["conditions"][0])
        duplicate["condition_id"]="CO1_DUP"
        data["conditions"].append(duplicate)
        data["experiments"][0]["condition_ids"].append("CO1_DUP")
        rows,report,split=build_modeling_cohort(data,task())
        self.assertEqual(len(rows),3)
        excluded={item["observation_id"]:item["reason"] for item in report["excluded"]}
        self.assertEqual(excluded["OB1"],"FEATURE_CONDITION_MULTIPLE")
        self.assertEqual(report["scientific_data_contract"]["condition_grain"]["multiple_same_type_groups"],1)
        self.assertIn("MULTIPLE_CONDITIONS_SAME_TYPE_IN_EXPERIMENT",
                      [item["code"] for item in report["scientific_data_contract"]["warnings"]])

    def test_units_must_match_exactly(self):
        data=fixture_bundle()
        data["conditions"][1]["normalized_unit"]="K"
        rows,report,split=build_modeling_cohort(data,task())
        excluded={item["observation_id"]:item["reason"] for item in report["excluded"]}
        self.assertEqual(excluded["OB2"],"FEATURE_UNIT_NOT_EXACT_MATCH")

    def test_explicit_study_split_is_validated(self):
        specification=task()
        specification["split"]={"strategy":"EXPLICIT_STUDIES","validation_study_ids":["ST2"],"test_study_ids":["ST4"]}
        rows,report,split=build_modeling_cohort(fixture_bundle(),specification)
        self.assertTrue(report["valid"],report)
        self.assertEqual(split["study_to_split"],{"ST1":"train","ST2":"validation","ST3":"train","ST4":"test"})

    def test_explicit_overlap_is_rejected(self):
        specification=task()
        specification["split"]={"strategy":"EXPLICIT_STUDIES","validation_study_ids":["ST2"],"test_study_ids":["ST2"]}
        rows,report,split=build_modeling_cohort(fixture_bundle(),specification)
        self.assertIsNone(rows)
        self.assertIn("STUDY_SPLIT_OVERLAP",[item["code"] for item in report["errors"]])

    def test_unknown_explicit_study_is_rejected(self):
        specification=task()
        specification["split"]={"strategy":"EXPLICIT_STUDIES","validation_study_ids":["ST2"],"test_study_ids":["NOT_A_STUDY"]}
        rows,report,split=build_modeling_cohort(fixture_bundle(),specification)
        self.assertIsNone(rows)
        self.assertIn("UNKNOWN_OR_INELIGIBLE_STUDY_ID",[item["code"] for item in report["errors"]])

    def test_invalid_canonical_bundle_is_rejected(self):
        data=fixture_bundle()
        data["observations"][0]["experiment_id"]="MISSING"
        rows,report,split=build_modeling_cohort(data,task())
        self.assertIsNone(rows)
        self.assertEqual(report["validation_scope"],"CANONICAL_INTEGRITY_REQUIRED")

    def test_input_bundle_is_not_mutated(self):
        data=fixture_bundle(); before=copy.deepcopy(data)
        build_modeling_cohort(data,task())
        self.assertEqual(data,before)

    def test_file_builder_writes_traceable_package_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); bundle_path=root/"bundle.json"; task_path=root/"task.json"; out=root/"out"
            bundle_path.write_text(json.dumps(fixture_bundle()),encoding="utf-8")
            task_path.write_text(json.dumps(task()),encoding="utf-8")
            before_bundle=bundle_path.read_bytes(); before_task=task_path.read_bytes()
            result=build_modeling_cohort_files(bundle_path,task_path,out)
            self.assertTrue(result["valid"],result)
            self.assertTrue((out/"modeling_cohort.csv").is_file())
            self.assertTrue((out/"split_manifest.json").is_file())
            self.assertEqual(bundle_path.read_bytes(),before_bundle)
            self.assertEqual(task_path.read_bytes(),before_task)

    def test_file_builder_refuses_nonempty_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); bundle_path=root/"bundle.json"; task_path=root/"task.json"; out=root/"out"
            bundle_path.write_text(json.dumps(fixture_bundle()),encoding="utf-8")
            task_path.write_text(json.dumps(task()),encoding="utf-8")
            out.mkdir(); (out/"keep.txt").write_text("keep",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build_modeling_cohort_files(bundle_path,task_path,out)

if __name__=="__main__":
    unittest.main()
