import unittest

from dor.research_scope import validate_research_scope_record


class ResearchScopeValidationTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "signals": [
                {"signal_id": "SIG_01", "signal_type": "TYPE_A"},
                {"signal_id": "SIG_02", "signal_type": "TYPE_B"},
                {"signal_id": "SIG_03", "signal_type": "TYPE_C"},
            ]
        }
        self.task = {"task_id": "TASK_01", "target_id": "TARGET_01"}
        self.record = {
            "schema_version": "1.0",
            "scope_id": "SCOPE_01",
            "discovery_report_sha256": "a" * 64,
            "task_id": "TASK_01",
            "target_id": "TARGET_01",
            "scope_statement": "A bounded synthetic scope.",
            "selected_signal_ids": ["SIG_01", "SIG_03"],
            "not_selected_signal_ids": ["SIG_02"],
            "selection_rationale": "Select signals relevant to the declared synthetic task.",
            "reviewed_by": "synthetic-reviewer",
            "reviewed_at": "2026-11-14T00:00:00Z",
            "limitations": ["Synthetic fixture only."],
        }

    def validate(self, record=None, report=None, task=None, digest="a" * 64):
        return validate_research_scope_record(
            self.record if record is None else record,
            self.report if report is None else report,
            self.task if task is None else task,
            digest,
        )

    def test_exact_partition_and_task_binding_are_valid(self):
        result = self.validate()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["selected_signal_count"], 2)
        self.assertEqual(result["not_selected_signal_count"], 1)

    def test_unclassified_signal_is_rejected(self):
        record = dict(self.record)
        record["not_selected_signal_ids"] = []
        result = self.validate(record=record)
        self.assertFalse(result["valid"])
        self.assertIn("SCOPE_SIGNAL_UNCLASSIFIED", [item["code"] for item in result["errors"]])

    def test_unknown_and_overlapping_signal_ids_are_rejected(self):
        record = dict(self.record)
        record["not_selected_signal_ids"] = ["SIG_02", "SIG_01", "SIG_UNKNOWN"]
        result = self.validate(record=record)
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("SCOPE_SIGNAL_PARTITION_OVERLAP", codes)
        self.assertIn("SCOPE_SIGNAL_UNKNOWN", codes)

    def test_stale_discovery_hash_and_task_identity_are_rejected(self):
        record = dict(self.record)
        record["target_id"] = "TARGET_OTHER"
        result = self.validate(record=record, digest="b" * 64)
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("SCOPE_DISCOVERY_HASH_MISMATCH", codes)
        self.assertIn("SCOPE_TASK_IDENTITY_MISMATCH", codes)

    def test_scope_requires_at_least_one_selected_signal(self):
        record = dict(self.record)
        record["selected_signal_ids"] = []
        record["not_selected_signal_ids"] = ["SIG_01", "SIG_02", "SIG_03"]
        result = self.validate(record=record)
        self.assertIn("SCOPE_HAS_NO_SELECTED_SIGNAL", [item["code"] for item in result["errors"]])


    def test_dor_generated_opportunity_can_be_selected(self):
        report = {
            "signals": [{
                "signal_id": "OPP-ABC123",
                "signal_type": "WITHIN_STUDY_SYSTEM_CONDITION_OUTCOME_CONTRAST",
                "target_id": "TARGET_01",
            }]
        }
        record = dict(self.record)
        record["selected_signal_ids"] = ["OPP-ABC123"]
        record["not_selected_signal_ids"] = []
        result = self.validate(record=record, report=report)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["selected_opportunity_ids"], ["OPP-ABC123"])

    def test_between_system_opportunity_is_reported_as_a_selected_opportunity(self):
        report = {
            "signals": [{
                "signal_id": "OPP-BETWEEN",
                "signal_type": "WITHIN_STUDY_BETWEEN_SYSTEM_CONDITION_OUTCOME_CONTRAST",
                "target_id": "TARGET_01",
            }]
        }
        record = dict(self.record)
        record["selected_signal_ids"] = ["OPP-BETWEEN"]
        record["not_selected_signal_ids"] = []
        result = self.validate(record=record, report=report)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["selected_opportunity_ids"], ["OPP-BETWEEN"])

    def test_selected_opportunity_target_must_match_modeling_task(self):
        report = {
            "signals": [{
                "signal_id": "OPP-OTHER",
                "signal_type": "WITHIN_STUDY_SYSTEM_NUMERIC_CONDITION_TREND",
                "target_id": "TARGET_OTHER",
            }]
        }
        record = dict(self.record)
        record["selected_signal_ids"] = ["OPP-OTHER"]
        record["not_selected_signal_ids"] = []
        result = self.validate(record=record, report=report)
        self.assertFalse(result["valid"])
        self.assertIn(
            "SCOPE_SELECTED_SIGNAL_TARGET_MISMATCH",
            [item["code"] for item in result["errors"]],
        )


if __name__ == "__main__":
    unittest.main()
