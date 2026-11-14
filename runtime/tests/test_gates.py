from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.builder import validate_build_spec_files
from dor.gates import (
    inspect_gate_ledger,
    record_gate_decision,
    require_gate,
    require_selected_interaction_id,
)
from dor.mapping import sha256_file, validate_mapping_plan


class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / "workflow_gate_ledger.jsonl"
        self.files: dict[str, Path] = {}

        def make_file(artifact_id: str, value: dict):
            path = self.root / (artifact_id + ".json")
            path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            self.files[artifact_id] = path

        make_file("dataset_manifest", {"schema_version": "1.0", "audit_id": "AUDIT_TEST"})
        make_file("source_inventory", {
            "schema_version": "1.0",
            "items": [{
                "inventory_id": "SRC_TEST_1",
                "source_file": "records.csv",
                "source_sha256": "a" * 64,
                "source_format": "csv",
                "locator_type": "csv_column",
                "locator": "record_id",
                "observed_types": ["string"],
                "coverage": 1.0,
            }],
        })
        inventory_hash = sha256_file(self.files["source_inventory"])
        mapping_plan = {
            "schema_version": "1.0",
            "mapping_version": "MAPPING_TEST_1",
            "source_inventory_sha256": inventory_hash,
            "rules": [],
        }
        make_file("mapping_plan", mapping_plan)
        mapping_validation = validate_mapping_plan(
            mapping_plan,
            json.loads(self.files["source_inventory"].read_text(encoding="utf-8")),
            inventory_hash,
        )
        make_file("mapping_validation", mapping_validation)
        make_file("build_spec", {
            "schema_version": "1.0",
            "project_id": "PROJECT_TEST",
            "mapping_version": mapping_plan["mapping_version"],
            "mapping_plan_sha256": sha256_file(self.files["mapping_plan"]),
            "source_inventory_sha256": inventory_hash,
            "entity_definitions": [{
                "definition_id": "D_STUDY",
                "entity_type": "studies",
                "source_file": "records.csv",
                "source_format": "csv",
                "grouping": {"mode": "SOURCE_ROW", "source_item_ids": []},
                "field_rule_ids": [],
            }],
            "links": [],
        })
        make_file("build_spec_validation", validate_build_spec_files(
            self.files["mapping_plan"], self.files["source_inventory"], self.files["build_spec"]
        ))
        make_file("canonical_bundle", {
            "schema_version": "1.0",
            "build_provenance": {
                "mapping_plan_sha256": sha256_file(self.files["mapping_plan"]),
                "source_inventory_sha256": inventory_hash,
                "build_spec_sha256": sha256_file(self.files["build_spec"]),
            },
        })
        make_file("canonical_validation_report", {"valid": True, "errors": [], "warnings": []})
        make_file("reconciliation_report", {
            "schema_version": "1.0",
            "bundle_sha256": sha256_file(self.files["canonical_bundle"]),
            "valid_bundle": True,
            "validation_error_count": 0,
            "validation_warning_count": 0,
            "issue_count": 0,
            "severity_counts": {"CRITICAL": 0, "REVIEW_REQUIRED": 0, "WARNING": 0, "INFO": 0},
            "issues": [],
            "decision_policy": "HUMAN_REVIEW_ONLY_NO_CANONICAL_DATA_MUTATION",
            "validation_scope": "DETERMINISTIC_CANDIDATE_DETECTION_NOT_SCIENTIFIC_RECONCILIATION",
        })
        make_file("reconciliation_decisions", {
            "schema_version": "1.0",
            "reconciliation_report_sha256": sha256_file(self.files["reconciliation_report"]),
            "decisions": [],
        })
        make_file("modeling_task", {
            "schema_version": "1.0",
            "task_id": "TASK_GATE",
            "target_id": "TARGET_GATE",
            "endpoint_definition": "test endpoint definition",
        })
        make_file("discovery_report", {
            "schema_version": "1.0",
            "signals": [
                {"signal_id": "SIG_01", "signal_type": "TYPE_A"},
                {"signal_id": "SIG_02", "signal_type": "TYPE_B"},
            ],
        })
        make_file("research_scope_record", {
            "schema_version": "1.0",
            "scope_id": "SCOPE_GATE",
            "discovery_report_sha256": sha256_file(self.files["discovery_report"]),
            "task_id": "TASK_GATE",
            "target_id": "TARGET_GATE",
            "scope_statement": "Synthetic bounded analysis scope.",
            "selected_signal_ids": ["SIG_01"],
            "not_selected_signal_ids": ["SIG_02"],
            "selection_rationale": "Selected one synthetic signal and explicitly excluded the other.",
            "reviewed_by": "human-reviewer",
            "reviewed_at": "2026-11-14T00:00:00Z",
            "limitations": ["Synthetic gate fixture."],
        })
        make_file("publication_plan", {"schema_version": "1.0", "artifacts": []})
        make_file("model_report", {"task_id": "TASK_GATE", "selected_model": "TEST_MODEL"})
        make_file("worker_review_output", {
            "schema_version": "1.0",
            "task_id": "WORKER_TASK_GATE",
            "status": "completed",
            "summary": "Synthetic review fixture.",
            "findings": [{"finding_id": "WF_001", "summary": "Synthetic finding."}],
            "artifacts": [],
            "warnings": [],
            "unresolved_questions": [],
        })
        make_file("reviewed_findings", {
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-14T00:00:00Z",
            "worker_output": {
                "artifact_id": "worker_review_output",
                "path": str(self.files["worker_review_output"]),
                "sha256": sha256_file(self.files["worker_review_output"]),
            },
            "reviewed_artifacts": [
                {
                    "artifact_id": "model_report",
                    "path": str(self.files["model_report"]),
                    "sha256": sha256_file(self.files["model_report"]),
                },
                {
                    "artifact_id": "interaction_selection",
                    "path": str(self.files["interaction_selection"]),
                    "sha256": sha256_file(self.files["interaction_selection"]),
                },
            ],
            "findings": [{
                "worker_finding_id": "WF_001",
                "disposition": "ACCEPT_AS_IS",
                "reviewer_rationale": "The finding is supported by the exact reviewed result.",
                "supporting_artifact_ids": ["model_report"],
            }],
            "promotion_decision": "PROMOTE_ACCEPTED_ONLY",
            "overall_rationale": "Only the accepted finding is promoted.",
        })
        make_file("mechanism_plan", {
            "schema_version": "1.0", "task_id": "TASK_GATE",
            "interaction_id": "INT_1",
        })
        # G3 report/manifest/selection artifacts are overwritten with internally
        # consistent fixtures by _prepare_g3, but must first be registered.
        for artifact_id in (
            "interaction_report", "interaction_manifest",
            "robustness_report", "robustness_manifest",
            "interaction_selection",
        ):
            make_file(artifact_id, {})
        self._prepare_g3(["INT_1"], ["INT_1"])

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, artifact_id: str, value: dict):
        self.files[artifact_id].write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

    def _prepare_g3(self, all_ids: list[str], selected_ids: list[str]):
        task_hash = sha256_file(self.files["modeling_task"])
        shared_inputs = {
            "task_sha256": task_hash,
            "cohort_sha256": "1" * 64,
            "cohort_report_sha256": "2" * 64,
            "split_manifest_sha256": "3" * 64,
            "cohort_manifest_sha256": "4" * 64,
        }
        interaction_report = {
            "schema_version": "1.0",
            "task_id": "TASK_GATE",
            "interaction_catalogue": [{"interaction_id": item} for item in all_ids],
        }
        self._write("interaction_report", interaction_report)
        interaction_report_hash = sha256_file(self.files["interaction_report"])
        self._write("interaction_manifest", {
            "schema_version": "1.0",
            "task_id": "TASK_GATE",
            "input_hashes": dict(shared_inputs),
            "output_hashes": {"interaction_discovery_report.json": interaction_report_hash},
        })
        robustness_report = {
            "schema_version": "1.0",
            "interaction_catalogue": [{"interaction_id": item} for item in all_ids],
        }
        self._write("robustness_report", robustness_report)
        robustness_report_hash = sha256_file(self.files["robustness_report"])
        self._write("robustness_manifest", {
            "schema_version": "1.0",
            "input_hashes": dict(shared_inputs),
            "output_hashes": {"interaction_robustness_report.json": robustness_report_hash},
        })
        self._write("interaction_selection", {
            "schema_version": "1.1",
            "task_id": "TASK_GATE",
            "interaction_report_sha256": interaction_report_hash,
            "robustness_report_sha256": robustness_report_hash,
            "selected_interaction_ids": selected_ids,
            "not_selected_interaction_ids": [item for item in all_ids if item not in selected_ids],
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-08T00:00:00Z",
            "rationale": "Reviewed the exact interaction and repeated-seed robustness reports.",
        })
        if selected_ids:
            self._write("mechanism_plan", {
                "schema_version": "1.0", "task_id": "TASK_GATE",
                "interaction_id": selected_ids[0],
            })

    def _record(self, gate, ids, decision="APPROVE"):
        return record_gate_decision(
            self.ledger, gate, decision, "human-reviewer",
            "Reviewed the exact inputs and approve/revise/stop the declared scope.",
            [(item, self.files[item]) for item in ids],
        )

    def _record_g0(self):
        return self._record("G0", ["dataset_manifest", "source_inventory"])

    def _record_g1(self):
        return self._record(
            "G1", ["mapping_plan", "mapping_validation", "source_inventory", "build_spec", "build_spec_validation"]
        )

    def _record_g2(self):
        return self._record(
            "G2", [
                "canonical_bundle", "canonical_validation_report",
                "reconciliation_report", "reconciliation_decisions",
                "discovery_report", "research_scope_record", "modeling_task",
            ]
        )

    def _record_g3(self, include_mechanism=True):
        ids = [
            "interaction_report", "interaction_manifest", "robustness_report",
            "robustness_manifest", "interaction_selection",
        ]
        if include_mechanism:
            ids.append("mechanism_plan")
        return self._record("G3", ids)

    def _complete_to_g2(self):
        self._record_g0()
        self._record_g1()
        self._record_g2()

    def test_g2_rejects_reconciliation_decisions_bound_to_an_old_report(self):
        self._record_g0()
        self._record_g1()
        report = json.loads(self.files["reconciliation_report"].read_text(encoding="utf-8"))
        report["issue_count"] = 1
        self._write("reconciliation_report", report)
        with self.assertRaisesRegex(ValueError, "reconciliation decisions"):
            self._record_g2()

    def test_g2_rejects_scope_record_bound_to_a_different_discovery_report(self):
        self._record_g0()
        self._record_g1()
        scope = json.loads(self.files["research_scope_record"].read_text(encoding="utf-8"))
        scope["discovery_report_sha256"] = "f" * 64
        self._write("research_scope_record", scope)
        with self.assertRaisesRegex(ValueError, "research_scope_record"):
            self._record_g2()

    def test_complete_gate_chain_and_exact_artifact_binding(self):
        self._complete_to_g2()
        self._record_g3()
        self._record("G4", ["publication_plan", "model_report", "interaction_selection", "worker_review_output", "reviewed_findings"])
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertTrue(snapshot["valid_ledger"])
        self.assertEqual(snapshot["workflow_status"], "READY_FOR_FINALIZATION")
        self.assertTrue(all(snapshot["gates"][gate]["status"] == "APPROVED"
                            for gate in ("G0", "G1", "G2", "G3", "G4")))
        require_gate(self.ledger, "G4", {"publication_plan": self.files["publication_plan"]})

    def test_cannot_skip_an_upstream_gate(self):
        with self.assertRaisesRegex(ValueError, "G0 must be currently approved"):
            self._record_g1()
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 0)

    def test_missing_required_artifact_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires artifact IDs"):
            self._record("G0", ["dataset_manifest"])
        self.assertFalse(self.ledger.exists())

    def test_g1_rejects_build_spec_bound_to_another_mapping_plan(self):
        self._record_g0()
        spec = json.loads(self.files["build_spec"].read_text(encoding="utf-8"))
        spec["mapping_plan_sha256"] = "f" * 64
        self._write("build_spec", spec)
        with self.assertRaisesRegex(ValueError, "exact approved mapping_plan hash"):
            self._record_g1()
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 1)

    def test_g2_rejects_reconciliation_for_another_canonical_bundle(self):
        self._record_g0()
        self._record_g1()
        report = json.loads(self.files["reconciliation_report"].read_text(encoding="utf-8"))
        report["bundle_sha256"] = "e" * 64
        self._write("reconciliation_report", report)
        with self.assertRaisesRegex(ValueError, "exact approved canonical_bundle hash"):
            self._record_g2()
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 2)

    def test_g4_requires_a_reviewed_scientific_result(self):
        self._complete_to_g2()
        self._record_g3()
        with self.assertRaisesRegex(ValueError, "G4 requires at least one reviewed result"):
            self._record("G4", ["publication_plan", "worker_review_output", "reviewed_findings"])

    def test_g4_requires_every_worker_finding_to_have_one_human_disposition(self):
        self._complete_to_g2()
        self._record_g3()
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["findings"] = []
        self._write("reviewed_findings", reviewed)
        with self.assertRaisesRegex(ValueError, "cover every Worker finding exactly once"):
            self._record("G4", ["publication_plan", "model_report", "interaction_selection", "worker_review_output", "reviewed_findings"])

    def test_g4_rejects_promotion_decision_inconsistent_with_dispositions(self):
        self._complete_to_g2()
        self._record_g3()
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["promotion_decision"] = "DO_NOT_PROMOTE"
        self._write("reviewed_findings", reviewed)
        with self.assertRaisesRegex(ValueError, "inconsistent with the individual human finding dispositions"):
            self._record("G4", ["publication_plan", "model_report", "interaction_selection", "worker_review_output", "reviewed_findings"])

    def test_g4_requires_gate_bindings_for_every_human_reviewed_artifact(self):
        self._complete_to_g2()
        self._record_g3()
        with self.assertRaisesRegex(ValueError, "Gate event must bind reviewed artifact"):
            self._record("G4", ["publication_plan", "model_report", "worker_review_output", "reviewed_findings"])

    def test_changed_artifact_invalidates_its_gate_and_all_downstream_gates(self):
        self._complete_to_g2()
        self._record_g3()
        self._record("G4", ["publication_plan", "model_report", "interaction_selection", "worker_review_output", "reviewed_findings"])
        self.files["canonical_bundle"].write_text('{"changed": true}', encoding="utf-8")
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertEqual(snapshot["gates"]["G2"]["status"], "STALE_ARTIFACT")
        self.assertEqual(snapshot["gates"]["G3"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G4"]["status"], "BLOCKED_UPSTREAM")
        with self.assertRaisesRegex(ValueError, "G2 is not currently approved"):
            require_gate(self.ledger, "G3")

    def test_new_upstream_decision_invalidates_old_downstream_approval(self):
        self._complete_to_g2()
        self._record_g3()
        self.files["dataset_manifest"].write_text('{"revised": true}', encoding="utf-8")
        self._record("G0", ["dataset_manifest", "source_inventory"], decision="APPROVE")
        snapshot = inspect_gate_ledger(self.ledger)
        self.assertEqual(snapshot["gates"]["G0"]["status"], "APPROVED")
        self.assertEqual(snapshot["gates"]["G1"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G2"]["status"], "BLOCKED_UPSTREAM")
        self.assertEqual(snapshot["gates"]["G3"]["status"], "BLOCKED_UPSTREAM")

    def test_response_surface_interaction_must_be_selected_at_g3(self):
        self._complete_to_g2()
        self._record_g3()
        require_selected_interaction_id(self.ledger, "INT_1")
        with self.assertRaisesRegex(ValueError, "was not selected"):
            require_selected_interaction_id(self.ledger, "INT_OTHER")

    def test_g3_requires_exact_interaction_report_hash(self):
        self._complete_to_g2()
        report = json.loads(self.files["interaction_report"].read_text(encoding="utf-8"))
        report["interaction_catalogue"].append({"interaction_id": "INT_2"})
        self._write("interaction_report", report)
        with self.assertRaisesRegex(ValueError, "exact interaction report SHA-256"):
            self._record_g3()
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 3)

    def test_g3_requires_robustness_manifest_from_the_g2_task(self):
        self._complete_to_g2()
        manifest = json.loads(self.files["robustness_manifest"].read_text(encoding="utf-8"))
        manifest["input_hashes"]["task_sha256"] = "d" * 64
        self._write("robustness_manifest", manifest)
        with self.assertRaisesRegex(ValueError, "exact G2-approved modeling_task"):
            self._record_g3()
        self.assertEqual(inspect_gate_ledger(self.ledger)["event_count"], 3)

    def test_g3_can_approve_no_mechanism_selection_without_plan(self):
        self._complete_to_g2()
        self._prepare_g3(["INT_1"], [])
        self._record_g3(include_mechanism=False)
        self.assertEqual(inspect_gate_ledger(self.ledger)["gates"]["G3"]["status"], "APPROVED")

    def test_expected_artifact_path_must_match_approved_file(self):
        self._complete_to_g2()
        alternate = self.root / "alternate.json"
        alternate.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "path differs"):
            require_gate(self.ledger, "G2", {"modeling_task": alternate})

    def test_tampered_event_hash_chain_is_detected(self):
        self._record_g0()
        content = self.ledger.read_text(encoding="utf-8")
        content = content.replace("approve/revise/stop", "silently altered")
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
            self._record_g1()


if __name__ == "__main__":
    unittest.main()
