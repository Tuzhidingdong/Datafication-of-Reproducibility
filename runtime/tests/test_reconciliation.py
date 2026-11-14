from __future__ import annotations
import copy
import unittest

from dor.reconciliation import reconcile_canonical_bundle, validate_reconciliation_decisions


def bundle():
    return {
        "schema_version":"1.0","project_id":"P1","mapping_version":"map-v1",
        "studies":[{"study_id":"ST1","doi":"10.1000/example","source_locators":[]}],
        "systems":[{"system_id":"SY1","study_ids":["ST1"],"system_type":"system_type_01"}],
        "conditions":[{"condition_id":"CO1","system_ids":["SY1"],"condition_type":"temperature",
            "raw_value":25,"raw_unit":"degC","value_state":"REPORTED"}],
        "experiments":[{"experiment_id":"EX1","study_id":"ST1","system_id":"SY1","condition_ids":["CO1"]}],
        "observations":[{"observation_id":"OB1","experiment_id":"EX1","target_id":"TARGET_CAPACITY",
            "raw_value":120,"raw_unit":"unit-x","value_state":"REPORTED",
            "endpoint_definition":"response metric after interval 100",
            "timepoint":"interval 100","evidence_ids":["EV1"]}],
        "comparisons":[],
        "evidence":[{"evidence_id":"EV1","study_id":"ST1","source_locator":{
            "source_file":"paper.pdf","source_sha256":"a"*64,"locator_type":"pdf_page","locator":"p.4"},
            "evidence_type":"table_value","extraction_status":"VERIFIED","quoted_text":"120 unit-x"}]
    }


class ReconciliationTests(unittest.TestCase):
    def test_missing_endpoint_is_explicit_review_issue(self):
        data=bundle()
        data["observations"][0]["endpoint_definition"]=None
        report=reconcile_canonical_bundle(data,"a"*64)
        self.assertTrue(any(x["category"]=="ENDPOINT_DEFINITION_MISSING" for x in report["issues"]))

    def test_multiple_endpoint_definitions_are_kept_separate(self):
        data=bundle()
        second=copy.deepcopy(data["observations"][0])
        second.update({"observation_id":"OB2","endpoint_definition":"capacity retention after storage",
                       "raw_value":95})
        data["observations"].append(second)
        report=reconcile_canonical_bundle(data,"a"*64)
        issue=next(x for x in report["issues"] if x["category"]=="ENDPOINT_DEFINITION_VARIANTS")
        self.assertEqual(set(issue["entity_refs"]),{"OB1","OB2"})
        self.assertEqual(issue["status"],"OPEN")

    def test_value_variation_without_replicate_identity_is_not_called_conflict(self):
        data=bundle()
        second=copy.deepcopy(data["observations"][0])
        second.update({"observation_id":"OB2","raw_value":118})
        data["observations"].append(second)
        report=reconcile_canonical_bundle(data,"a"*64)
        categories={x["category"] for x in report["issues"]}
        self.assertIn("OBSERVATION_VARIATION_GRAIN_UNRESOLVED",categories)
        self.assertNotIn("VALUE_CONFLICT_SAME_REPLICATE_OR_SAMPLE",categories)

    def test_different_values_with_same_explicit_replicate_are_flagged(self):
        data=bundle()
        data["observations"][0]["replicate_id"]="R1"
        second=copy.deepcopy(data["observations"][0])
        second.update({"observation_id":"OB2","raw_value":118})
        data["observations"].append(second)
        report=reconcile_canonical_bundle(data,"a"*64)
        self.assertTrue(any(x["category"]=="VALUE_CONFLICT_SAME_REPLICATE_OR_SAMPLE" for x in report["issues"]))

    def test_same_evidence_locator_with_different_extraction_is_flagged(self):
        data=bundle()
        duplicate=copy.deepcopy(data["evidence"][0])
        duplicate.update({"evidence_id":"EV2","quoted_text":"118 unit-x"})
        data["evidence"].append(duplicate)
        report=reconcile_canonical_bundle(data,"a"*64)
        self.assertTrue(any(x["category"]=="EVIDENCE_EXTRACTION_DISAGREEMENT" for x in report["issues"]))

    def test_explicit_evidence_review_state_is_flagged(self):
        data=bundle()
        data["evidence"][0]["extraction_status"]="REVIEW_REQUIRED"
        report=reconcile_canonical_bundle(data,"a"*64)
        self.assertTrue(any(x["category"]=="EVIDENCE_VERIFICATION_REQUIRED" for x in report["issues"]))

    def test_reconciliation_does_not_mutate_bundle(self):
        data=bundle()
        before=copy.deepcopy(data)
        reconcile_canonical_bundle(data,"a"*64)
        self.assertEqual(data,before)

    def test_report_issue_ids_are_stable(self):
        data=bundle()
        data["observations"][0]["endpoint_definition"]=None
        first=reconcile_canonical_bundle(data,"a"*64)
        second=reconcile_canonical_bundle(data,"a"*64)
        self.assertEqual([x["issue_id"] for x in first["issues"]],
                         [x["issue_id"] for x in second["issues"]])

    def test_human_decision_requires_exact_report_and_bundle_hashes(self):
        data=bundle()
        report=reconcile_canonical_bundle(data,"a"*64)
        report["issues"]=[{
            "issue_id":"REC_0123456789ABCDEF0123",
            "category":"TEST","entity_refs":["OB1"],"evidence_refs":["EV1"]
        }]
        report["issue_count"] = 1
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,
          "decisions":[{"issue_id":"REC_0123456789ABCDEF0123","decision":"RESOLVED_WITH_EVIDENCE",
            "reviewer":"reviewer","reviewed_at":"2026-11-08T00:00:00Z","rationale":"Checked against source table.",
            "evidence_refs":["EV1"]}]}
        result=validate_reconciliation_decisions(decisions,report,data,"b"*64,"a"*64)
        self.assertTrue(result["valid"],result)
        stale=validate_reconciliation_decisions(decisions,report,data,"b"*64,"c"*64)
        self.assertFalse(stale["valid"])
        self.assertIn("STALE_CANONICAL_BUNDLE",[x["code"] for x in stale["errors"]])

    def test_critical_reconciliation_issue_cannot_remain_unresolved(self):
        data=bundle()
        report=reconcile_canonical_bundle(data,"a"*64)
        report["issues"]=[{
            "issue_id":"REC_CRITICAL",
            "severity":"CRITICAL",
            "entity_refs":[],
            "evidence_refs":[],
        }]
        report["issue_count"] = 1
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,
          "decisions":[{"issue_id":"REC_CRITICAL","decision":"REMAINS_UNRESOLVED",
            "reviewer":"reviewer","reviewed_at":"2026-11-08T00:00:00Z",
            "rationale":"Insufficient evidence to resolve this critical issue.",
            "evidence_refs":[]}]}
        result=validate_reconciliation_decisions(decisions,report,data,"b"*64,"a"*64)
        self.assertFalse(result["valid"])
        self.assertIn(
            "BLOCKING_RECONCILIATION_ISSUE_UNRESOLVED",
            [item["code"] for item in result["errors"]],
        )

    def test_reconciliation_decisions_reject_missing_issue_array_or_count_mismatch(self):
        data = bundle()
        report = reconcile_canonical_bundle(data, "a" * 64)
        decisions = {
            "schema_version": "1.0",
            "reconciliation_report_sha256": "b" * 64,
            "decisions": [],
        }
        missing_issues = dict(report)
        missing_issues.pop("issues")
        missing = validate_reconciliation_decisions(
            decisions, missing_issues, data, "b" * 64, "a" * 64
        )
        self.assertFalse(missing["valid"])
        self.assertIn(
            "RECONCILIATION_REPORT_FIELD_MISSING",
            [item["code"] for item in missing["errors"]],
        )

        inconsistent = dict(report)
        inconsistent["issue_count"] = 1
        count_result = validate_reconciliation_decisions(
            decisions, inconsistent, data, "b" * 64, "a" * 64
        )
        self.assertFalse(count_result["valid"])
        self.assertIn(
            "RECONCILIATION_ISSUE_COUNT_MISMATCH",
            [item["code"] for item in count_result["errors"]],
        )

    def test_reconciliation_decision_timestamp_requires_explicit_timezone(self):
        data=bundle()
        report=reconcile_canonical_bundle(data,"a"*64)
        report["issues"]=[{"issue_id":"REC_ISSUE_1","entity_refs":[],"evidence_refs":[]}]
        report["issue_count"] = 1
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,
          "decisions":[{"issue_id":"REC_ISSUE_1","decision":"REMAINS_UNRESOLVED",
            "reviewer":"reviewer","reviewed_at":"2026-11-08T00:00:00",
            "rationale":"Reviewed; retain as unresolved.","evidence_refs":[]}]}
        result=validate_reconciliation_decisions(decisions,report,data,"b"*64,"a"*64)
        self.assertFalse(result["valid"])
        self.assertIn("INVALID_DECISION_TIMESTAMP",[item["code"] for item in result["errors"]])

    def test_every_reported_issue_requires_an_explicit_human_decision(self):
        data=bundle()
        report=reconcile_canonical_bundle(data,"a"*64)
        report["issues"]=[
            {"issue_id":"REC_ISSUE_1","entity_refs":[],"evidence_refs":[]},
            {"issue_id":"REC_ISSUE_2","entity_refs":[],"evidence_refs":[]},
        ]
        report["issue_count"] = 2
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,
          "decisions":[{"issue_id":"REC_ISSUE_1","decision":"REMAINS_UNRESOLVED",
            "reviewer":"reviewer","reviewed_at":"2026-11-08T00:00:00Z",
            "rationale":"Reviewed; retain as unresolved.","evidence_refs":[]}]}
        result=validate_reconciliation_decisions(decisions,report,data,"b"*64,"a"*64)
        self.assertFalse(result["valid"])
        self.assertEqual(
            [item["code"] for item in result["errors"]],
            ["RECONCILIATION_ISSUE_NOT_REVIEWED"],
        )

    def test_malformed_report_is_rejected_without_exception(self):
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,"decisions":[]}
        result=validate_reconciliation_decisions(decisions,[],bundle(),"b"*64,"a"*64)
        self.assertFalse(result["valid"])
        self.assertTrue(any(x["code"]=="STALE_RECONCILIATION_REPORT" for x in result["errors"]))

    def test_resolved_with_evidence_requires_evidence_reference(self):
        data=bundle()
        report=reconcile_canonical_bundle(data,"a"*64)
        report["issues"]=[{"issue_id":"REC_0123456789ABCDEF0123","entity_refs":[],"evidence_refs":[]}]
        decisions={"schema_version":"1.0","reconciliation_report_sha256":"b"*64,
          "decisions":[{"issue_id":"REC_0123456789ABCDEF0123","decision":"RESOLVED_WITH_EVIDENCE",
            "reviewer":"reviewer","reviewed_at":"2026-11-08T00:00:00Z","rationale":"Reviewed but no evidence linked.",
            "evidence_refs":[]}]}
        result=validate_reconciliation_decisions(decisions,report,data,"b"*64,"a"*64)
        self.assertFalse(result["valid"])
        self.assertIn("RESOLUTION_EVIDENCE_REQUIRED",[x["code"] for x in result["errors"]])

if __name__=="__main__":
    unittest.main()
