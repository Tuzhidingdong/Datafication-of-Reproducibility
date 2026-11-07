from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from dor.canonical import validate_canonical_bundle

def valid_bundle():
    return {
        "schema_version":"1.0","project_id":"P1","mapping_version":"map-v1",
        "studies":[{"study_id":"ST1","doi":"10.1000/example","source_locators":[]}],
        "systems":[{"system_id":"SY1","study_ids":["ST1"],"system_type":"battery_cell"}],
        "conditions":[{"condition_id":"CO1","system_ids":["SY1"],"condition_type":"temperature",
            "raw_value":25,"raw_unit":"degC","value_state":"REPORTED"}],
        "experiments":[{"experiment_id":"EX1","study_id":"ST1","system_id":"SY1","condition_ids":["CO1"]}],
        "observations":[{"observation_id":"OB1","experiment_id":"EX1","target_id":"TARGET_CAPACITY",
            "raw_value":120,"raw_unit":"mAh g-1","value_state":"REPORTED","evidence_ids":["EV1"]}],
        "comparisons":[],
        "evidence":[{"evidence_id":"EV1","study_id":"ST1","source_locator":{
            "source_file":"paper.pdf","source_sha256":"a"*64,"locator_type":"pdf_page","locator":"p.4"},
            "evidence_type":"table_value","extraction_status":"VERIFIED"}]
    }

class CanonicalBundleTests(unittest.TestCase):
    def test_valid_bundle_passes(self):
        report=validate_canonical_bundle(valid_bundle())
        self.assertTrue(report["valid"]); self.assertEqual(report["error_count"],0)
        self.assertEqual(report["counts"]["observations"],1)
    def test_broken_references_are_reported(self):
        bundle=valid_bundle(); bundle["observations"][0]["experiment_id"]="MISSING"
        report=validate_canonical_bundle(bundle)
        self.assertFalse(report["valid"])
        self.assertTrue(any(e["code"]=="BROKEN_REFERENCE" for e in report["errors"]))
    def test_duplicate_ids_are_rejected(self):
        bundle=valid_bundle(); bundle["studies"].append(copy.deepcopy(bundle["studies"][0]))
        report=validate_canonical_bundle(bundle)
        self.assertTrue(any(e["code"]=="DUPLICATE_RECORD_ID" for e in report["errors"]))
    def test_unknown_missingness_is_rejected(self):
        bundle=valid_bundle(); bundle["observations"][0]["value_state"]="ZERO"
        report=validate_canonical_bundle(bundle)
        self.assertTrue(any(e["code"]=="INVALID_MISSINGNESS_STATE" for e in report["errors"]))
    def test_input_is_not_mutated(self):
        bundle=valid_bundle(); before=copy.deepcopy(bundle)
        validate_canonical_bundle(bundle)
        self.assertEqual(bundle,before)
    def test_unhashable_reference_is_reported_not_raised(self):
        bundle=valid_bundle(); bundle["observations"][0]["experiment_id"]=["EX1"]
        report=validate_canonical_bundle(bundle)
        self.assertFalse(report["valid"])
    def test_non_object_bundle_returns_report(self):
        report=validate_canonical_bundle(["not","an","object"])
        self.assertFalse(report["valid"]); self.assertEqual(report["errors"][0]["code"],"BUNDLE_NOT_OBJECT")

if __name__=="__main__": unittest.main()
