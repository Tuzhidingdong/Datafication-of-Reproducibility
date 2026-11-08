from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.gates import inspect_gate_ledger, record_gate_decision, require_gate


class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / "workflow_gate_ledger.jsonl"
        self.files = {}
        for artifact_id in (
            "dataset_manifest", "source_inventory", "mapping_plan", "build_spec",
            "canonical_bundle", "reconciliation_report", "modeling_task",
            "interaction_report", "interaction_selection", "mechanism_plan",
            "publication_plan", "model_report",
        ):
            path = self.root / (artifact_id + ".json")
            path.write_text(json.dumps({"artifact": artifact_id}), encoding="utf-8")
            self.files[artifact_id] = path
        report_content = json.dumps({
            "schema_version": "1.0",
            "task_id": "TASK_GATE",
            "interaction_catalogue": [{"interaction_id": "INT_1"}],
        }, sort_keys=True, separators=(",", ":")) + "\n"
        self.files["interaction_report"].write_text(report_content, encoding="utf-8")
        report_hash = hashlib.sha256(self.files["interaction_report"].read_bytes()).hexdigest()
        self.files["interaction_selection"].write_text(json.dumps({
            "schema_version": "1.0",
            "task_id": "TASK_GATE",
            "interaction_report_sha256": report_hash,
            "selected_interaction_ids": ["INT_1"],
            "not_selected_interaction_ids": [],
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-08T00:00:00Z",
            "rationale": "Selected after reviewing support and counterexamples.",
        }), encoding="utf-8")
        self.files["mechanism_plan"].write_text(json.dumps({
            "schema_version": "1.0", "task_id": "TASK_GATE",
            "interaction_id": "INT_1",
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _record(self, gate, ids, decision="APPROVE"):
        return record_gate_decision(
            self.ledger, gate, decision, "human-reviewer",
            "Reviewed exact inputs and accept the documented scope.",
            [(item, self.files[item]) for item in ids],
        )

    def _complete_to_g2(self):
        self._record("G0", ["dataset_manifest", "source_inventory"])
        self._record("G1", ["mapping_plan", "source_inventory", "build_spec"])
        self._record("G2", ["canonical_bundle", "reconciliation_report", "modeling_task"])

    def test_complete_gate_chain_and_exact_artifact_binding(self):
        self._complete_to_g2()
        self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        self._record("G4", ["publication_plan", "model_report"])
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertTrue(snapshot["valid_ledger"])
        self.assertEqual(snapshot["workflow_status"], "READY_FOR_FINALIZATION")
        self.assertTrue(all(snapshot["gates"][gate]["status"] == "APPROVED"
                            for gate in ("G0", "G1", "G2", "G3", "G4")))
        require_gate(self.ledger, "G4", {"publication_plan": self.files["publication_plan"]})

    def test_cannot_skip_an_upstream_gate(self):
        with self.assertRaisesRegex(ValueError, "G0 must be currently approved"):
            self._record("G1", ["mapping_plan", "source_inventory", "build_spec"])
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 0)

    def test_missing_required_artifact_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires artifact IDs"):
            self._record("G0", ["dataset_manifest"])
        self.assertFalse(self.ledger.exists())

    def test_g4_requires_a_reviewed_scientific_result(self):
        self._complete_to_g2()
        self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        with self.assertRaisesRegex(ValueError, "G4 requires at least one reviewed result"):
            self._record("G4", ["publication_plan"])

    def test_changed_artifact_invalidates_its_gate_and_all_downstream_gates(self):
        self._complete_to_g2()
        self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        self._record("G4", ["publication_plan", "model_report"])
        self.files["canonical_bundle"].write_text('{"changed": true}', encoding="utf-8")
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertEqual(snapshot["gates"]["G2"]["status"], "STALE_ARTIFACT")
        self.assertEqual(snapshot["gates"]["G3"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G4"]["status"], "BLOCKED_UPSTREAM")
        with self.assertRaisesRegex(ValueError, "G2 is not currently approved"):
            require_gate(self.ledger, "G3")

    def test_new_upstream_decision_invalidates_old_downstream_approval(self):
        self._complete_to_g2()
        self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        self.files["dataset_manifest"].write_text('{"revised": true}', encoding="utf-8")
        self._record("G0", ["dataset_manifest", "source_inventory"], decision="APPROVE")
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertEqual(snapshot["gates"]["G0"]["status"], "APPROVED")
        self.assertEqual(snapshot["gates"]["G1"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G2"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G3"]["status"], "BLOCKED_UPSTREAM")


    def test_response_surface_interaction_must_be_selected_at_g3(self):
        self._complete_to_g2()
        self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        from dor.gates import require_selected_interaction_id
        require_selected_interaction_id(self.ledger, "INT_1")
        with self.assertRaisesRegex(ValueError, "was not selected"):
            require_selected_interaction_id(self.ledger, "INT_OTHER")

    def test_g3_requires_complete_selection_and_exact_report_hash(self):
        self._complete_to_g2()
        report_path = self.files["interaction_report"]
        report_path.write_text(json.dumps({
            "task_id": "TASK_GATE",
            "interaction_catalogue": [
                {"interaction_id": "INT_1"}, {"interaction_id": "INT_2"}
            ],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact interaction report SHA-256"):
            self._record("G3", ["interaction_report", "interaction_selection", "mechanism_plan"])
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 3)

    def test_g3_can_approve_no_mechanism_selection_without_plan(self):
        self._complete_to_g2()
        report_path = self.files["interaction_report"]
        report_path.write_text(json.dumps({
            "task_id": "TASK_GATE",
            "interaction_catalogue": [{"interaction_id": "INT_1"}],
        }), encoding="utf-8")
        report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        self.files["interaction_selection"].write_text(json.dumps({
            "schema_version": "1.0", "task_id": "TASK_GATE",
            "interaction_report_sha256": report_hash,
            "selected_interaction_ids": [],
            "not_selected_interaction_ids": ["INT_1"],
            "reviewer": "human-reviewer", "reviewed_at": "2026-11-08T00:00:00Z",
            "rationale": "No candidate met the predeclared support rule.",
        }), encoding="utf-8")
        self._record("G3", ["interaction_report", "interaction_selection"])
        self.assertEqual(inspect_gate_ledger(self.ledger)["gates"]["G3"]["status"], "APPROVED")

    def test_expected_artifact_path_must_match_approved_file(self):
        self._complete_to_g2()
        alternate = self.root / "alternate.json"
        alternate.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "path differs"):
            require_gate(self.ledger, "G2", {"modeling_task": alternate})

    def test_tampered_event_hash_chain_is_detected(self):
        self._record("G0", ["dataset_manifest", "source_inventory"])
        content = self.ledger.read_text(encoding="utf-8")
        content = content.replace("accept the documented scope", "silently altered")
        self.ledger.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "event hash mismatch"):
            inspect_gate_ledger(self.ledger)


    def test_stop_can_be_recorded_without_unavailable_artifacts(self):
        result = record_gate_decision(
            self.ledger, "G0", "STOP", "human-reviewer",
            "The proposed source scope is not approved.",
            [],
        )
        self.assertTrue(result["recorded"])
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertEqual(snapshot["gates"]["G0"]["status"], "STOP")
        self.assertEqual(snapshot["event_count"], 1)

    def test_revise_or_stop_decision_does_not_approve_a_gate(self):
        self._record("G0", ["dataset_manifest", "source_inventory"], decision="REVISE")
        self.assertEqual(inspect_gate_ledger(self.ledger)["gates"]["G0"]["status"], "REVISE")
        with self.assertRaisesRegex(ValueError, "G0 must be currently approved"):
            self._record("G1", ["mapping_plan", "source_inventory", "build_spec"])


if __name__ == "__main__":
    unittest.main()
