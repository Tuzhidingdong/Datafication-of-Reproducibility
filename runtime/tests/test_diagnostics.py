from __future__ import annotations
import copy
import unittest
from dor.diagnostics import diagnose_canonical_bundle

def sample_bundle():
    return {
      "schema_version":"1.0","project_id":"P","mapping_version":"M",
      "studies":[{"study_id":"ST1","doi":"10.1000/a","source_locators":[]}],
      "systems":[{"system_id":"SY1","study_ids":["ST1"],"system_type":"cell"}],
      "conditions":[
        {"condition_id":"CO1","system_ids":["SY1"],"condition_type":"temperature","value_state":"REPORTED","raw_value":25},
        {"condition_id":"CO2","system_ids":["SY1"],"condition_type":"pressure","value_state":"REPORTED","raw_value":1}
      ],
      "experiments":[{"experiment_id":"EX1","study_id":"ST1","system_id":"SY1","condition_ids":["CO1"]}],
      "observations":[{"observation_id":"OB1","experiment_id":"EX1","target_id":"capacity","value_state":"REPORTED","raw_value":100,"evidence_ids":["EV1"]}],
      "comparisons":[],
      "evidence":[
        {"evidence_id":"EV1","study_id":"ST1","source_locator":{"source_file":"a.pdf","locator":"p.1"},"evidence_type":"table_value","quoted_text":"100"},
        {"evidence_id":"EV2","study_id":"ST1","source_locator":{"source_file":"b.pdf","locator":"p.2"},"evidence_type":"table_value","quoted_text":"100"}
      ]
    }

class CanonicalDiagnosticsTests(unittest.TestCase):
    def test_reports_unreferenced_entities_and_exact_duplicate_candidates(self):
        bundle=sample_bundle()
        before=copy.deepcopy(bundle)
        report=diagnose_canonical_bundle(bundle)
        self.assertTrue(report["valid_input"])
        self.assertIn("CO2",report["unreferenced"]["conditions_not_used_by_experiments"])
        self.assertIn("EV2",report["unreferenced"]["evidence_not_cited_by_observations"])
        self.assertEqual(report["duplicate_candidate_count"],1)
        self.assertEqual(report["duplicate_candidates"][0]["status"],"REVIEW_ONLY_NOT_MERGED")
        self.assertEqual(bundle,before)

    def test_malformed_relationship_fields_do_not_crash(self):
        bundle=sample_bundle()
        bundle["systems"][0]["study_ids"]="not-an-array"
        bundle["experiments"][0]["study_id"]=None
        bundle["experiments"][0]["condition_ids"]=None
        for evidence in bundle["evidence"]:
            evidence["study_id"]=None
        bundle["observations"][0]["evidence_ids"]=42
        report=diagnose_canonical_bundle(bundle)
        self.assertTrue(report["valid_input"])
        self.assertIn("ST1",report["unreferenced"]["studies_without_system_experiment_or_evidence_link"])

    def test_non_object_input_returns_diagnostic_error(self):
        report=diagnose_canonical_bundle([])
        self.assertFalse(report["valid_input"])

if __name__=="__main__": unittest.main()
