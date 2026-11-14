import unittest

from dor.review import _promotion_decision, _validate_worker_result


class ReviewContractTests(unittest.TestCase):
    def test_promotion_decision_matches_gate_policy(self):
        self.assertEqual(_promotion_decision(["ACCEPT_AS_IS"]), "PROMOTE_ACCEPTED_ONLY")
        self.assertEqual(
            _promotion_decision(["ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"]),
            "PROMOTE_WITH_CHANGES",
        )
        self.assertEqual(_promotion_decision(["REJECT", "DEFER"]), "DEFER")
        self.assertEqual(_promotion_decision(["REJECT"]), "DO_NOT_PROMOTE")
        self.assertEqual(_promotion_decision([]), "DO_NOT_PROMOTE")

    def test_worker_findings_require_stable_ids_and_exact_evidence(self):
        result = {
            "schema_version": "1.0",
            "task_id": "task-1",
            "status": "completed",
            "summary": "Review completed.",
            "findings": [{
                "finding_id": "F-001",
                "summary": "A traceable finding.",
                "supporting_artifact_ids": ["model_report"],
                "evidence": [{"artifact_id": "model_report", "locator": "/metrics/example"}],
            }],
            "artifacts": [],
            "warnings": [],
            "unresolved_questions": [],
        }
        self.assertIn("F-001", _validate_worker_result(result, {"model_report"}))
        invalid_status = dict(result)
        invalid_status["status"] = {"unexpected": "object"}
        with self.assertRaisesRegex(ValueError, "status is invalid"):
            _validate_worker_result(invalid_status, {"model_report"})
        with self.assertRaisesRegex(ValueError, "not supplied to the Worker"):
            _validate_worker_result(result, {"interaction_report"})
        duplicate = dict(result)
        duplicate["findings"] = result["findings"] * 2
        with self.assertRaisesRegex(ValueError, "unique"):
            _validate_worker_result(duplicate, {"model_report"})


if __name__ == "__main__":
    unittest.main()
