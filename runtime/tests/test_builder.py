from __future__ import annotations
import csv, hashlib, json, tempfile, unittest
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
            writer.writerow(["DOI","Title","System","Temperature","ConditionType","ValueState","Experiment","Target","Value"])
            writer.writerow(["10.1000/a","Study A","Cell A","25","temperature","REPORTED","E1","capacity","100"])
            writer.writerow(["10.1000/a","Study A","Cell A","25","temperature","REPORTED","E2","capacity","110"])
        self.source_hash = sha256_file(self.source)
        columns = ["DOI","Title","System","Temperature","ConditionType","ValueState","Experiment","Target","Value"]
        self.inventory = {"schema_version":"1.0","items":[
            {"inventory_id":f"SRC_{name}","source_file":"source.csv","source_sha256":self.source_hash,
             "source_format":"csv","locator_type":"csv_column","locator":name}
            for name in columns]}
        rules = []
        def add(rule_id, source, entity, field, transform="IDENTITY", params=None):
            rules.append({"mapping_rule_id":rule_id,"source_item_id":f"SRC_{source}",
              "target_entity":entity,"target_field_id":field,"status":"APPROVED",
              "transformation":{"type":transform,"parameters":params or {}},
              "review":{"reviewer":"test reviewer","reviewed_at":"2026-11-07","decision_note":"Reviewed synthetic fixture."}})
        add("R_DOI","DOI","studies","doi")
        add("R_TITLE","Title","studies","title")
        add("R_SYS_TYPE","System","systems","system_type")
        add("R_COND_TYPE","ConditionType","conditions","condition_type")
        add("R_COND_STATE","ValueState","conditions","value_state")
        add("R_TEMP","Temperature","conditions","raw_value","NUMERIC_PARSE")
        add("R_TARGET","Target","observations","target_id")
        add("R_OBS_STATE","ValueState","observations","value_state")
        add("R_VALUE","Value","observations","raw_value","NUMERIC_PARSE")
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
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_DOI","SRC_System","SRC_Temperature"]},"field_rule_ids":["R_COND_TYPE","R_COND_STATE","R_TEMP"]},
            {"definition_id":"D_EXPERIMENT","entity_type":"experiments","source_file":"source.csv",
             "grouping":{"mode":"GROUP_BY_FIELDS","source_item_ids":["SRC_Experiment"]},"field_rule_ids":[]},
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

    def test_conflicting_values_within_group_fail_closed(self):
        self.spec["entity_definitions"][0]["field_rule_ids"]=["R_DOI","R_TITLE"]
        self.inventory["items"] = self.inventory["items"]
        content = self.source.read_text(encoding="utf-8").replace("10.1000/a,Study A,Cell A,25", "10.1000/a,Different title,Cell A,25", 1)
        self.source.write_text(content, encoding="utf-8")
        new_hash = sha256_file(self.source)
        for item in self.inventory["items"]:
            item["source_sha256"] = new_hash
        self.inventory_path_hash = "d"*64
        self.mapping["source_inventory_sha256"] = self.inventory_path_hash
        self.spec["source_inventory_sha256"] = self.inventory_path_hash
        bundle, report = build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="GROUP_FIELD_CONFLICT" for e in report["errors"]))

    def test_unapproved_mapping_cannot_build(self):
        self.mapping["rules"][0]["status"]="REVIEWED"
        bundle, report = build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertFalse(report["valid"])

    def test_empty_group_key_fails_closed(self):
        self.source.write_text(self.source.read_text(encoding="utf-8").replace("10.1000/a","",1),encoding="utf-8")
        new_hash=sha256_file(self.source)
        for item in self.inventory["items"]: item["source_sha256"]=new_hash
        self.inventory_path_hash="d"*64
        self.mapping["source_inventory_sha256"]=self.inventory_path_hash
        self.spec["source_inventory_sha256"]=self.inventory_path_hash
        bundle, report = build_canonical_bundle(self.mapping,self.inventory,self.spec,self.root,self.plan_hash,self.inventory_path_hash)
        self.assertIsNone(bundle)
        self.assertTrue(any(e["code"]=="EMPTY_GROUP_KEY" for e in report["errors"]))

if __name__=="__main__": unittest.main()
