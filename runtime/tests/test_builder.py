from __future__ import annotations
import csv, json, tempfile, unittest
from pathlib import Path
from dor.builder import build_canonical_bundle
from dor.mapping import sha256_file

class CanonicalBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.csv"
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["DOI","Title","System","Feature01","FeatureUnit","ConditionType","ValueState","Experiment","Target","Value"])
            writer.writerow(["10.1000/a","Study A","System A","25","unit_01","feature_01","REPORTED","E1","TARGET_01","100"])
            writer.writerow(["10.1000/a","Study A","System A","25","unit_01","feature_01","REPORTED","E2","TARGET_01","110"])
        self.source_hash = sha256_file(self.source)
        columns = ["DOI","Title","System","Feature01","FeatureUnit","ConditionType","ValueState","Experiment","Target","Value"]
        self.inventory = {"schema_version":"1.0","items":[
            {"inventory_id":f"SRC_{name}","source_file":"source.csv","source_sha256":self.source_hash,
             "source_format":"csv","locator_type":"csv_column","locator":name}
            for name in columns]}
        rules = []
        def add(rule_id, source, entity, field, transform="IDENTITY", params=None, source_item=None):
            rules.append({"mapping_rule_id":rule_id,"source_item_id":source_item or f"SRC_{source}",
              "target_entity":entity,"target_field_id":field,"status":"APPROVED",
              "transformation":{"type":transform,"parameters":params or {}},
              "review":{"reviewer":"test reviewer","reviewed_at":"2026-11-07","decision_note":"Reviewed synthetic fixture."}})
        add("R_DOI","DOI","studies","doi")
        add("R_TITLE","Title","studies","title")
        add("R_SYS_TYPE","System","systems","system_type")
        add("R_COND_TYPE","ConditionType","conditions","condition_type")
        add("R_COND_STATE","ValueState","conditions","value_state")
        add("R_FEATURE_01","Feature01","conditions","raw_value","NUMERIC_PARSE")
        add("R_RAW_UNIT","FeatureUnit","conditions","raw_unit")
        add("R_NORMALIZED_FEATURE","Feature01","conditions","normalized_value","UNIT_CONVERSION",
            {"source_unit":"unit_01","target_unit":"unit_02","unit_source_item_id":"SRC_FeatureUnit","factor":2.0,"offset":0.0})
        add("R_EXP_KEY","Experiment","experiments","source_experiment_key")
        add("R_TARGET","Target","observations","target_id")
        add("R_OBS_STATE","ValueState","observations","value_state")
        add("R_VALUE","Value","observations","raw_value","NUMERIC_PARSE")
        self.add_rule = add
        self.mapping = {"schema_version":"1.0","mapping_version":"map-1",
          "source_inventory_sha256":"placeholder","rules":rules}
        self.inventory_path_hash = "b"*64
        self.plan_hash = "c"*64
        self.spec_hash = "e"*64
        self.spec = {
          "schema_version":"1.0","project_id":"TEST","mapping_version":"map-1",
          "mapping_plan_sha256":self.plan_hash,"source_inventory_sha256":self.inventory_path_hash,
          "entity_definitions":[
            {"definition_id":"D_STUDY","entity_type":"studies","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_DOI"]},"field_rule_ids":["R_DOI","R_TITLE"]},
            {"definition_id":"D_SYSTEM","entity_type":"systems","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_DOI","SRC_System"]},"field_rule_ids":["R_SYS_TYPE"]},
            {"definition_id":"D_CONDITION","entity_type":"conditions","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_DOI","SRC_System","SRC_Feature01"]},"field_rule_ids":["R_COND_TYPE","R_COND_STATE","R_FEATURE_01","R_RAW_UNIT","R_NORMALIZED_FEATURE"]},
            {"definition_id":"D_EXPERIMENT","entity_type":"experiments","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_Experiment"]},"field_rule_ids":["R_EXP_KEY"]},
            {"definition_id":"D_OBSERVATION","entity_type":"observations","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_Experiment","SRC_Target"]},"field_rule_ids":["R_TARGET","R_OBS_STATE","R_VALUE"]}
          ],
          "links":[
            {"child_definition_id":"D_SYSTEM","parent_definition_id":"D_STUDY","field_id":"study_ids"},
            {"child_definition_id":"D_CONDITION","parent_definition_id":"D_SYSTEM","field_id":"system_ids"},
            {"child_definition_id":"D_EXPERIMENT","parent_definition_id":"D_STUDY","field_id":"study_id"},
            {"child_definition_id":"D_EXPERIMENT","parent_definition_id":"D_SYSTEM","field_id":"system_id"},
            {"child_definition_id":"D_EXPERIMENT","parent_definition_id":"D_CONDITION","field_id":"condition_ids"},
            {"child_definition_id":"D_OBSERVATION","parent_definition_id":"D_EXPERIMENT","field_id":"experiment_id"}
          ]}
        self.mapping["source_inventory_sha256"] = self.inventory_path_hash

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_grouped_entities_and_explicit_links(self):
        bundle, report = build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,self.plan_hash,self.inventory_path_hash,self.spec_hash)
        self.assertTrue(report["valid"], report)
        self.assertEqual(len(bundle["studies"]),1)
        self.assertEqual(len(bundle["systems"]),1)
        self.assertEqual(len(bundle["experiments"]),2)
        self.assertEqual(len(bundle["observations"]),2)
        self.assertEqual(bundle["observations"][0]["raw_value"],100)
        self.assertEqual(bundle["experiments"][0]["study_id"],bundle["studies"][0]["study_id"])
        self.assertEqual(bundle["build_provenance"]["build_spec_sha256"],self.spec_hash)
        self.assertEqual(bundle["observations"][0]["_provenance"]["mapping_plan_sha256"],self.plan_hash)
        condition=bundle["conditions"][0]
        self.assertEqual(condition["normalized_value"],50)
        self.assertEqual(condition["normalized_unit"],"unit_02")
        conversion=next(item for item in condition["field_provenance"] if item["target_field_id"]=="normalized_value")
        self.assertEqual(conversion["source_unit_provenance"]["source_unit"],"unit_01")

    def _switch_observations_to_json(self):
        json_path = self.root / "observations.json"
        payload = {"observations":[
            {"experiment_ref":"E1","target":"TARGET_01","state":"REPORTED","value":"101"},
            {"experiment_ref":"E2","target":"TARGET_01","state":"REPORTED","value":"111"}
        ]}
        json_path.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
        digest=sha256_file(json_path)
        sources=[
            ("J_EXP","$['observations'][]['experiment_ref']","experiment_ref"),
            ("J_TARGET","$['observations'][]['target']","target"),
            ("J_STATE","$['observations'][]['state']","state"),
            ("J_VALUE","$['observations'][]['value']","value")
        ]
        for suffix, locator, field in sources:
            self.inventory["items"].append({
                "inventory_id":f"SRC_{suffix}","source_file":"observations.json","source_sha256":digest,
                "source_format":"json","locator_type":"json_path","locator":locator,
                "observed_types":["string"],"coverage":None,"mapping_status":"UNRESOLVED"
            })
        self.add_rule("R_J_EXP","unused","observations","experiment_ref",source_item="SRC_J_EXP")
        self.add_rule("R_J_TARGET","unused","observations","target_id",source_item="SRC_J_TARGET")
        self.add_rule("R_J_STATE","unused","observations","value_state",source_item="SRC_J_STATE")
        self.add_rule("R_J_VALUE","unused","observations","raw_value","NUMERIC_PARSE",source_item="SRC_J_VALUE")
        observation=self.spec["entity_definitions"][-1]
        observation.update({"source_file":"observations.json","source_format":"json",
                            "record_selector":"/observations/*",
                            "grouping":{"mode":"SOURCE_ROW","source_item_ids":[]},
                            "field_rule_ids":["R_J_EXP","R_J_TARGET","R_J_STATE","R_J_VALUE"]})
        link=self.spec["links"][-1]
        link.update({"match_mode":"FIELD_EQUALITY","child_key_field":"experiment_ref",
                     "parent_key_field":"source_experiment_key"})
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash

    def test_json_records_and_cross_file_equality_join(self):
        self._switch_observations_to_json()
        bundle, report = build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                                 self.plan_hash,self.inventory_path_hash,self.spec_hash)
        self.assertTrue(report["valid"], report)
        self.assertEqual(len(bundle["observations"]),2)
        self.assertEqual({row["raw_value"] for row in bundle["observations"]},{101,111})
        self.assertTrue(all(row["experiment_id"] for row in bundle["observations"]))
        pointers={item["locator"] for row in bundle["observations"] for item in row["field_provenance"]}
        self.assertIn("/observations/0/value",pointers)
        self.assertIn("/observations/1/value",pointers)

    def test_cross_file_join_with_missing_key_fails_closed(self):
        self._switch_observations_to_json()
        json_path=self.root/"observations.json"
        payload=json.loads(json_path.read_text(encoding="utf-8"))
        payload["observations"][0]["experiment_ref"]="NO_MATCH"
        json_path.write_text(json.dumps(payload),encoding="utf-8")
        new_hash=sha256_file(json_path)
        for item in self.inventory["items"]:
            if item["source_file"]=="observations.json":
                item["source_sha256"]=new_hash
        self.inventory_path_hash="d"*64
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash
        self.spec["source_inventory_sha256"]=self.inventory_path_hash
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="JOIN_CARDINALITY_VIOLATION" for e in report["errors"]))

    def test_json_selector_that_resolves_multiple_leaf_values_fails(self):
        self._switch_observations_to_json()
        json_path=self.root/"observations.json"
        payload=json.loads(json_path.read_text(encoding="utf-8"))
        payload["observations"][0]["values"]=["1","2"]
        json_path.write_text(json.dumps(payload),encoding="utf-8")
        new_hash=sha256_file(json_path)
        for item in self.inventory["items"]:
            if item["source_file"]=="observations.json":
                item["source_sha256"]=new_hash
        # Replace only the numeric mapping with a structural path that resolves to two leaves.
        self.inventory["items"]=[item for item in self.inventory["items"] if item["inventory_id"]!="SRC_J_VALUE"]
        self.inventory["items"].append({"inventory_id":"SRC_J_VALUE_MULTI","source_file":"observations.json",
            "source_sha256":new_hash,"source_format":"json","locator_type":"json_path",
            "locator":"$['observations'][]['values'][]","observed_types":["string"],"coverage":None,
            "mapping_status":"UNRESOLVED"})
        value_rule=next(rule for rule in self.mapping["rules"] if rule["mapping_rule_id"]=="R_J_VALUE")
        value_rule["source_item_id"]="SRC_J_VALUE_MULTI"
        self.inventory_path_hash="d"*64
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash
        self.spec["source_inventory_sha256"]=self.inventory_path_hash
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="VALUE_TRANSFORM_FAILED" for e in report["errors"]))

    def test_conflicting_values_within_group_fail_closed(self):
        content=self.source.read_text(encoding="utf-8").replace("10.1000/a,Study A,System A,25", "10.1000/a,Different title,System A,25", 1)
        self.source.write_text(content,encoding="utf-8")
        new_hash=sha256_file(self.source)
        for item in self.inventory["items"]:
            item["source_sha256"]=new_hash
        self.inventory_path_hash="d"*64
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash
        self.spec["source_inventory_sha256"]=self.inventory_path_hash
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="GROUP_FIELD_CONFLICT" for e in report["errors"]))

    def test_custom_transform_is_rejected_by_mapping_validation(self):
        rule=next(item for item in self.mapping["rules"] if item["mapping_rule_id"]=="R_VALUE")
        rule["transformation"]={"type":"CUSTOM","parameters":{"implementation":"not-installed"}}
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="UNKNOWN_TRANSFORMATION" for e in report["errors"]))

    def test_unit_conversion_rejects_a_source_unit_mismatch(self):
        content=self.source.read_text(encoding="utf-8").replace("unit_01","unit_wrong")
        self.source.write_text(content,encoding="utf-8")
        new_hash=sha256_file(self.source)
        for item in self.inventory["items"]:
            item["source_sha256"]=new_hash
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any("SOURCE_UNIT_MISMATCH" in e["message"] for e in report["errors"]))

    def test_unapproved_mapping_cannot_build(self):
        self.mapping["rules"][0]["status"]="REVIEWED"
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertFalse(report["valid"])

    def test_empty_group_key_fails_closed(self):
        self.source.write_text(self.source.read_text(encoding="utf-8").replace("10.1000/a","",1),encoding="utf-8")
        new_hash=sha256_file(self.source)
        for item in self.inventory["items"]:
            item["source_sha256"]=new_hash
        self.inventory_path_hash="d"*64
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash
        self.spec["source_inventory_sha256"]=self.inventory_path_hash
        bundle, report=build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,
                                              self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="INVALID_GROUP_KEY_VALUE" for e in report["errors"]))

if __name__=="__main__":
    unittest.main()
