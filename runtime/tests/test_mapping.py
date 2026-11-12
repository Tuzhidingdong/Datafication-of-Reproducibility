from __future__ import annotations
import hashlib
import unittest
from dor.mapping import validate_mapping_plan

def inventory():
    return {"schema_version":"1.0","items":[
        {"inventory_id":"SRC_A","source_file":"data.csv","source_sha256":"a"*64,
         "locator_type":"csv_column","locator":"temperature","source_format":"csv"}]}

def plan(inv_hash):
    return {"schema_version":"1.0","mapping_version":"map-001","source_inventory_sha256":inv_hash,
        "rules":[{"mapping_rule_id":"MAP_A","source_item_id":"SRC_A","target_entity":"conditions",
          "target_field_id":"temperature","status":"APPROVED",
          "transformation":{"type":"UNIT_CONVERSION","parameters":{
              "source_unit":"degC","target_unit":"K","factor":1.0,"offset":273.15}},
          "review":{"reviewer":"human","reviewed_at":"2026-11-07","decision_note":"Checked against source method."}}]}

class MappingPlanTests(unittest.TestCase):
    def setUp(self):
        self.inv=inventory()
        self.digest="b"*64
        self.mapping=plan(self.digest)

    def test_approved_rule_passes(self):
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertTrue(result["valid"])
        self.assertEqual(result["approved_rule_ids"],["MAP_A"])

    def test_stale_inventory_is_rejected(self):
        result=validate_mapping_plan(self.mapping,self.inv,"c"*64)
        self.assertFalse(result["valid"])
        self.assertIn("STALE_SOURCE_INVENTORY",[e["code"] for e in result["errors"]])

    def test_unknown_source_item_is_rejected(self):
        self.mapping["rules"][0]["source_item_id"]="MISSING"
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertIn("UNKNOWN_SOURCE_ITEM",[e["code"] for e in result["errors"]])

    def test_unapproved_rule_is_excluded(self):
        self.mapping["rules"][0]["status"]="REVIEWED"
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertTrue(result["valid"])
        self.assertEqual(result["approved_rule_ids"],[])
        self.assertEqual(result["excluded_rule_ids"],["MAP_A"])

    def test_approved_rule_requires_review_metadata(self):
        del self.mapping["rules"][0]["review"]["reviewer"]
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertIn("APPROVAL_METADATA_REQUIRED",[e["code"] for e in result["errors"]])

    def test_unit_conversion_requires_units_and_factor(self):
        self.mapping["rules"][0]["transformation"]["parameters"]={"source_unit":"degC"}
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertIn("INCOMPLETE_UNIT_CONVERSION",[e["code"] for e in result["errors"]])

    def test_duplicate_approved_target_is_rejected(self):
        second=dict(self.mapping["rules"][0]); second["mapping_rule_id"]="MAP_B"
        self.mapping["rules"].append(second)
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertIn("DUPLICATE_APPROVED_TARGET",[e["code"] for e in result["errors"]])

    def test_identity_does_not_accept_hidden_parameters(self):
        self.mapping["rules"][0]["transformation"]={"type":"IDENTITY","parameters":{"factor":1000}}
        result=validate_mapping_plan(self.mapping,self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertIn("IDENTITY_HAS_PARAMETERS",[e["code"] for e in result["errors"]])

    def test_non_object_plan_returns_report(self):
        result=validate_mapping_plan([],self.inv,self.digest)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"],"PLAN_NOT_OBJECT")

if __name__=="__main__": unittest.main()
