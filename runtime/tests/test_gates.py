from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.builder import validate_build_spec_files
from dor.gates import (
    inspect_gate_ledger,
    record_gate_decision,
    require_gate,
    require_selected_interaction_id,
    _require_gate_binding,
    _validate_single_study_na_bundle,
    _validate_g4_publication_plan,
    _validate_g4_reviewed_findings,
)
from dor.mapping import sha256_file, validate_mapping_plan


class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / "workflow_gate_ledger.jsonl"
        self.files: dict[str, Path] = {}
        self.g4_source_temp: tempfile.TemporaryDirectory | None = None

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
        make_file("publication_plan_validation", {"schema_version": "1.0", "valid": False})
        make_file("model_artifact", {"schema_version": "1.0", "artifact_id": "MODEL_TEST"})
        make_file("model_report", {"task_id": "TASK_GATE", "selected_model": "TEST_MODEL"})
        make_file("reproducibility_evaluation", {"task_id": "TASK_GATE", "valid": True})
        make_file("cohort_review_record", {"schema_version": "1.0", "decision": "APPROVE_MODELING"})
        make_file("cohort_review_validation", {"schema_version": "1.0", "valid": True})
        make_file("virtual_prediction", {"task_id": "TASK_GATE", "status": "SYNTHETIC"})
        make_file("reviewed_findings_validation", {"schema_version": "1.0", "valid": True})
        make_file("worker_review_output", {
            "schema_version": "1.0",
            "task_id": "WORKER_TASK_GATE",
            "status": "completed",
            "summary": "Synthetic review fixture.",
            "findings": [{"finding_id": "WF_001", "summary": "Synthetic finding.", "supporting_artifact_ids": ["model_report"], "evidence": [{"artifact_id": "model_report", "locator": "/selected_model"}]}],
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
        make_file("virtual_query_decision", {
            "schema_version": "1.0",
            "decision": "NOT_APPLICABLE",
            "reason": "Virtual prediction not applicable for synthetic gate fixture.",
            "task_id": "TASK_GATE",
            "target_id": "TARGET_GATE",
            "endpoint_definition": "test endpoint definition",
            "modeling_task_sha256": sha256_file(self.files["modeling_task"]),
            "reviewer": "human-reviewer",
            "decided_at": "2026-11-14T00:00:00Z",
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
        self._run_context_patch = patch(
            "dor.run_manager._manifest_context",
            side_effect=self._fake_manifest_context,
        )
        self._run_context_patch.start()
        self.addCleanup(self._run_context_patch.stop)

    def _fake_manifest_context(self, manifest_path):
        run_root = Path(manifest_path).parent.resolve()
        manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
        plan = json.loads((run_root / "run_plan.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in (run_root / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return run_root, manifest, plan, events

    def tearDown(self):
        self.temp.cleanup()
        if self.g4_source_temp is not None:
            self.g4_source_temp.cleanup()

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
        self._refresh_reviewed_artifact_bindings()

    def _prepare_review_packet(self, gate, artifact_ids):
        stage_id = gate.lower() + "_review_packet"
        report_id = stage_id + "_validation"
        output_directory = {
            "G0": "01_audit",
            "G1": "02_mapping",
            "G2": "04_reconciliation",
        }[gate]
        output_root = self.root / output_directory
        output_root.mkdir(parents=True, exist_ok=True)
        packet_path = output_root / (stage_id + ".json")
        report_path = output_root / (report_id + ".json")
        packet_bindings = [
            {
                "artifact_id": artifact_id,
                "path": str(self.files[artifact_id].resolve()),
                "sha256": sha256_file(self.files[artifact_id]),
            }
            for artifact_id in artifact_ids
        ]
        packet = {
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "stage_id": stage_id,
            "prepared_at": "2026-11-14T00:00:00Z",
            "packet_status": "AWAITING_HUMAN_REVIEW",
            "artifact_bindings": packet_bindings,
            "review_items": [{
                "item_id": "review_all_bound_inputs",
                "question": "Have all exact input artifacts been inspected and any unresolved issues recorded?",
                "artifact_ids": list(artifact_ids),
                "mandatory": True,
            }],
            "unresolved_questions": [],
        }
        packet_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
        report = {
            "schema_version": "1.0",
            "contract": "RUN_REVIEW_PACKET",
            "valid": True,
            "run_id": packet["run_id"],
            "project_id": packet["project_id"],
            "stage_id": stage_id,
            "run_root": str(self.root.resolve()),
            "record": {
                "path": str(packet_path.resolve()),
                "sha256": sha256_file(packet_path),
            },
            "checked_artifact_count": len(artifact_ids),
            "validation_report_path": str(report_path.resolve()),
            "errors": [],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.files[stage_id] = packet_path
        self.files[report_id] = report_path
        return [stage_id, report_id]

    def _record(self, gate, ids, decision="APPROVE"):
        return record_gate_decision(
            self.ledger, gate, decision, "human-reviewer",
            "Reviewed the exact inputs and approve/revise/stop the declared scope.",
            [(item, self.files[item]) for item in ids],
        )

    def _refresh_g4_reviewed_findings_validation(self):
        report = json.loads(self.files["reviewed_findings_validation"].read_text(encoding="utf-8"))
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        worker = json.loads(self.files["worker_review_output"].read_text(encoding="utf-8"))
        report["record"]["sha256"] = sha256_file(self.files["reviewed_findings"])
        report["worker_output"]["sha256"] = sha256_file(self.files["worker_review_output"])
        report["worker_output"]["finding_count"] = len(worker.get("findings", []))
        report["promotion_decision"] = reviewed["promotion_decision"]
        report["expected_promotion_decision"] = reviewed["promotion_decision"]
        self._write("reviewed_findings_validation", report)

    def _prepare_g4_publication_plan(self, by_id, source_map, g3_event_hash, virtual_prediction_state="RUN_PREDICTION"):
        publication_root = self.root / "10_publication"
        publication_root.mkdir(parents=True, exist_ok=True)
        plan_path = publication_root / "publication_package_plan.json"
        validation_path = publication_root / "publication_plan_validation.json"
        entries = []
        report_sources = []
        # sourced entries
        for package_id, source_id in source_map.items():
            source = by_id[source_id]
            source_path = Path(source["path"]).resolve()
            relative_source = source_path.relative_to(self.root.resolve()).as_posix()
            entries.append({
                "artifact_id": package_id,
                "path": "artifacts/" + package_id.lower() + ".json",
                "source_path": relative_source,
                "source_artifact_id": source_id,
                "type": "json",
                "description": "Synthetic Run-bound G4 source fixture.",
                "status": "complete",
                "linked_record_ids": [],
                "manuscript_sections": [],
            })
            report_sources.append({
                "package_artifact_id": package_id,
                "artifact_id": source_id,
                "path": str(source_path),
                "sha256": source["sha256"],
            })
        # full-analysis virtual prediction delivery is decision-driven
        if virtual_prediction_state == "NOT_APPLICABLE":
            entries.append({
                "artifact_id": "VIRTUAL_PREDICTION_001",
                "path": "artifacts/virtual_prediction_001.json",
                "source_path": None,
                "source_artifact_id": None,
                "type": "json",
                "description": "Virtual prediction not applicable for this synthetic fixture.",
                "status": "not_applicable",
                "linked_record_ids": [],
                "manuscript_sections": [],
            })
        plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_TEST",
            "run_id": "RUN_GATE",
            "package_version": "TEST_1",
            "artifacts": entries,
        }
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        self.files["publication_plan"] = plan_path
        report = {
            "schema_version": "1.0",
            "contract": "RUN_BOUND_PUBLICATION_PLAN",
            "valid": True,
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "run_root": str(self.root.resolve()),
            "plan": {
                "path": str(plan_path.resolve()),
                "sha256": sha256_file(plan_path),
            },
            "checked_source_count": len(report_sources),
            "source_artifacts": report_sources,
            "validation_report_path": str(validation_path.resolve()),
            "errors": [],
        }
        validation_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.files["publication_plan_validation"] = validation_path
        source_output_definitions = []
        source_output_bindings = []
        for source_id in source_map.values():
            source_path = Path(by_id[source_id]["path"]).resolve()
            relative_source = source_path.relative_to(self.root.resolve()).as_posix()
            source_output_definitions.append({
                "artifact_id": source_id,
                "path": relative_source,
                "kind": "derived",
            })
            source_output_bindings.append({
                "artifact_id": source_id,
                "path": str(source_path),
                "sha256": by_id[source_id]["sha256"],
            })
        self.g4_source_temp = tempfile.TemporaryDirectory(prefix="dor-g4-sources-")
        fixture_source_root = Path(self.g4_source_temp.name).resolve()
        fixture_source_path = fixture_source_root / "run_source.json"
        fixture_source_path.write_text('{"fixture": true}\n', encoding="utf-8")
        source_snapshot = {
            "artifact_id": "g4_fixture_input",
            "path": str(fixture_source_path),
            "sha256": sha256_file(fixture_source_path),
        }
        (self.root / "run_manifest.json").write_text(json.dumps({
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "workspace_root": str(self.root.resolve()),
            "plan_path": "run_plan.json",
            "plan_sha256": "synthetic-plan-hash",
            "event_ledger_path": "run_events.jsonl",
            "workflow_ledger_path": None,
            "source_roots": [str(fixture_source_root)],
            "source_artifacts": [source_snapshot],
            "stage_order": ["g4_source_fixture", "publication_plan_preparation"],
        }, indent=2) + "\n", encoding="utf-8")
        (self.root / "run_plan.json").write_text(json.dumps({
            "schema_version": "1.0",
            "project_id": "PROJECT_TEST",
            "source_roots": [str(fixture_source_root)],
            "source_artifacts": [{
                "artifact_id": "g4_fixture_input",
                "path": str(fixture_source_path),
            }],
            "stages": [
                {
                    "stage_id": "g4_source_fixture",
                    "executor": "manual",
                    "depends_on": [],
                    "inputs": ["g4_fixture_input"],
                    "outputs": source_output_definitions,
                },
                {
                    "stage_id": "publication_plan_preparation",
                    "executor": "manual",
                    "required_gate": "G3",
                    "depends_on": ["g4_source_fixture"],
                    "inputs": ["g4_fixture_input"],
                    "outputs": [
                        {"artifact_id": "publication_plan", "path": "10_publication/publication_package_plan.json"},
                        {"artifact_id": "publication_plan_validation", "path": "10_publication/publication_plan_validation.json"},
                    ],
                },
            ],
        }, indent=2) + "\n", encoding="utf-8")
        run_events = [{
            "event_type": "STAGE_STATUS",
            "stage_id": "g4_source_fixture",
            "status": "SUCCEEDED",
            "attempt": 1,
            "event_hash": "SYNTHETIC_SOURCE_STAGE_EVENT",
            "input_artifacts": [source_snapshot],
            "output_artifacts": source_output_bindings,
            "gate_approval": None,
        }, {
            "event_type": "STAGE_STATUS",
            "stage_id": "publication_plan_preparation",
            "status": "SUCCEEDED",
            "attempt": 1,
            "event_hash": "SYNTHETIC_PUBLICATION_PREP_EVENT",
            "input_artifacts": [source_snapshot],
            "output_artifacts": [
                {
                    "artifact_id": "publication_plan",
                    "path": str(plan_path.resolve()),
                    "sha256": sha256_file(plan_path),
                },
                {
                    "artifact_id": "publication_plan_validation",
                    "path": str(validation_path.resolve()),
                    "sha256": sha256_file(validation_path),
                },
            ],
            "gate_approval": {
                "gate_id": "G3",
                "status": "APPROVED",
                "event_hash": g3_event_hash,
            },
        }]
        (self.root / "run_events.jsonl").write_text(
            "".join(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                for event in run_events
            ),
            encoding="utf-8",
        )
        by_id["publication_plan"] = {
            "artifact_id": "publication_plan",
            "path": str(plan_path.resolve()),
            "sha256": sha256_file(plan_path),
        }
        by_id["publication_plan_validation"] = {
            "artifact_id": "publication_plan_validation",
            "path": str(validation_path.resolve()),
            "sha256": sha256_file(validation_path),
        }

    def _g4_artifact_ids(self):
        # Default synthetic full-analysis fixtures record G2 as NOT_APPLICABLE (no vq query/validation artifacts).
        # Build a G4 fixture consistent with the current bound virtual query decision to avoid invalidating upstream gates.
        vq_state = "NOT_APPLICABLE"
        if "virtual_query_decision" in self.files and self.files["virtual_query_decision"].exists():
            try:
                vq_state = json.loads(self.files["virtual_query_decision"].read_text(encoding="utf-8")).get("decision", "NOT_APPLICABLE")
            except Exception:
                vq_state = "NOT_APPLICABLE"

        base_sources = {
            "MODEL_ARTIFACT_001": "model_artifact",
            "MODEL_REPORT_001": "model_report",
            "REPRODUCIBILITY_EVALUATION_001": "reproducibility_evaluation",
            "INTERACTION_REPORT_001": "interaction_report",
            "INTERACTION_ROBUSTNESS_001": "robustness_report",
            "INTERACTION_SELECTION_001": "interaction_selection",
            "COHORT_REVIEW_RECORD": "cohort_review_record",
            "COHORT_REVIEW_VALIDATION": "cohort_review_validation",
            "WORKER_REVIEW_RECORD": "worker_review_output",
            "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
            "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
        }
        source_map = dict(base_sources)
        if vq_state == "RUN_PREDICTION":
            source_map["VIRTUAL_PREDICTION_001"] = "virtual_prediction"
        by_id = {
            artifact_id: {
                "artifact_id": artifact_id,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
            for artifact_id, path in self.files.items()
        }
        gate_events = [
            json.loads(line)
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        g3_event = next(
            (item for item in reversed(gate_events) if item.get("gate_id") == "G3"),
            None,
        )
        if g3_event is None:
            raise AssertionError("The synthetic full-analysis G4 fixture requires a preceding G3 event.")
        self._prepare_g4_publication_plan(by_id, source_map, g3_event["event_hash"], virtual_prediction_state=vq_state)
        ids = [
            "publication_plan", "publication_plan_validation",
            "worker_review_output", "reviewed_findings", "reviewed_findings_validation",
            "model_report", "model_artifact", "reproducibility_evaluation",
            "interaction_report", "robustness_report", "interaction_selection",
            "cohort_review_record", "cohort_review_validation",
            "virtual_query_decision",
        ]
        if vq_state == "RUN_PREDICTION":
            ids.insert(ids.index("cohort_review_record"), "virtual_prediction")
        return ids

    def _ensure_virtual_query_decision(
        self,
        decision="NOT_APPLICABLE",
        reason="Virtual prediction not applicable for synthetic gate fixture.",
        source_query_path: str | None = None,
    ):
        task_path = self.files.get("modeling_task")
        if task_path is None or not task_path.exists():
            return
        task = json.loads(task_path.read_text(encoding="utf-8"))
        payload = {
            "schema_version": "1.0",
            "decision": decision,
            "reason": reason,
            "task_id": task.get("task_id"),
            "target_id": task.get("target_id"),
            "endpoint_definition": task.get("endpoint_definition"),
            "modeling_task_sha256": sha256_file(task_path),
            "reviewer": "human-reviewer",
            "decided_at": "2026-11-14T00:00:00Z",
        }
        if decision == "RUN_PREDICTION":
            payload["source_query_path"] = source_query_path or "08_virtual_reproduction/virtual_query_input.json"
        path = self.root / "virtual_query_decision.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.files["virtual_query_decision"] = path

    def _refresh_reviewed_artifact_bindings(self):
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        vq_state = "NOT_APPLICABLE"
        if "virtual_query_decision" in self.files and self.files["virtual_query_decision"].exists():
            try:
                vq_state = json.loads(self.files["virtual_query_decision"].read_text(encoding="utf-8")).get("decision", "NOT_APPLICABLE")
            except Exception:
                vq_state = "NOT_APPLICABLE"
        artifact_ids = [
            "model_artifact", "model_report", "reproducibility_evaluation",
            "interaction_report", "robustness_report", "interaction_selection",
        ]
        if vq_state == "RUN_PREDICTION":
            artifact_ids.append("virtual_prediction")
        artifact_ids.extend(["cohort_review_record", "cohort_review_validation"])
        if "virtual_query_decision" in self.files:
            artifact_ids.append("virtual_query_decision")
        reviewed["reviewed_artifacts"] = [
            {
                "artifact_id": artifact_id,
                "path": str(self.files[artifact_id]),
                "sha256": sha256_file(self.files[artifact_id]),
            }
            for artifact_id in artifact_ids
            if artifact_id in self.files
        ]
        self._write("reviewed_findings", reviewed)
        worker = json.loads(self.files["worker_review_output"].read_text(encoding="utf-8"))
        self._write("reviewed_findings_validation", {
            "schema_version": "1.0",
            "contract": "REVIEWED_WORKER_FINDINGS",
            "valid": True,
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "stage_id": "human_review_and_promotion",
            "run_root": str(self.root.resolve()),
            "record": {
                "path": str(self.files["reviewed_findings"].resolve()),
                "sha256": sha256_file(self.files["reviewed_findings"]),
            },
            "worker_output": {
                "artifact_id": "worker_review_output",
                "path": str(self.files["worker_review_output"].resolve()),
                "sha256": sha256_file(self.files["worker_review_output"]),
                "worker_status": worker["status"],
                "finding_count": len(worker["findings"]),
            },
            "reviewed_artifact_count": len(reviewed["reviewed_artifacts"]),
            "promotion_decision": reviewed["promotion_decision"],
            "expected_promotion_decision": reviewed["promotion_decision"],
            "validation_report_path": str(self.files["reviewed_findings_validation"].resolve()),
            "errors": [],
        })


    def _record_g0(self):
        ids = ["dataset_manifest", "source_inventory", "data_audit_report", "mapping_review_queue", "adapter_handoff"]
        for artifact_id in ids:
            if artifact_id not in self.files:
                path = self.root / (artifact_id + ".json")
                path.write_text(json.dumps({"schema_version": "1.0", "artifact_id": artifact_id}), encoding="utf-8")
                self.files[artifact_id] = path
        ids.extend(self._prepare_review_packet("G0", ids))
        return self._record("G0", ids)

    def _record_g1(self):
        ids = ["mapping_plan", "mapping_validation", "source_inventory", "build_spec", "build_spec_validation"]
        ids.extend(self._prepare_review_packet("G1", ids))
        return self._record("G1", ids)

    def _record_g2(self):
        ids = [
            "canonical_bundle", "canonical_validation_report",
            "reconciliation_report", "reconciliation_review_queue",
            "reconciliation_decisions", "reconciliation_decision_validation",
            "discovery_report", "research_scope_record", "modeling_task",
        ]
        for artifact_id in ids:
            if artifact_id not in self.files:
                path = self.root / (artifact_id + ".json")
                path.write_text(json.dumps({"schema_version": "1.0", "artifact_id": artifact_id}), encoding="utf-8")
                self.files[artifact_id] = path
        # FULL_ANALYSIS G2 now requires a valid virtual_query_decision; default fixtures use NOT_APPLICABLE.
        self._ensure_virtual_query_decision()
        if "virtual_query_decision" not in ids and "virtual_query_decision" in self.files:
            ids.append("virtual_query_decision")
        review_ids = list(ids)
        ids.extend(self._prepare_review_packet("G2", review_ids))
        return self._record("G2", ids)

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

    def _single_study_gate_fixture(self):
        def write(artifact_id, payload):
            path = self.root / (artifact_id + ".json")
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self.files[artifact_id] = path
            return {"artifact_id": artifact_id, "path": str(path.resolve()), "sha256": sha256_file(path)}

        bundle = {"schema_version": "1.0", "studies": [{"study_id": "STUDY_1"}]}
        task = {"schema_version": "1.0", "task_id": "TASK_GATE"}
        bundle_binding = write("canonical_bundle", bundle)
        task_binding = write("modeling_task", task)
        record = {
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "scope": "CONTROLLED_SINGLE_STUDY",
            "applicability_status": "NOT_APPLICABLE",
            "study_ids": ["STUDY_1"],
            "study_count": 1,
            "canonical_bundle_sha256": bundle_binding["sha256"],
            "modeling_task_sha256": task_binding["sha256"],
            "cohort_feasibility_status": "NOT_APPLICABLE",
            "cohort_feasibility_reason": "Only one independent Study is available.",
            "modeling_validation_status": "NOT_APPLICABLE",
            "modeling_validation_reason": "Cross-Study validation is not applicable.",
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-15T12:00:00+08:00",
            "rationale": "One independent Study only; no model or cross-Study result is claimed.",
        }
        record_binding = write("single_study_applicability_record", record)
        validation = {
            "schema_version": "1.0",
            "valid": True,
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "applicability_status": "NOT_APPLICABLE",
            "study_ids": ["STUDY_1"],
            "study_count": 1,
            "eligible_study_count": 1,
            "applicability_record_sha256": record_binding["sha256"],
            "canonical_bundle_sha256": bundle_binding["sha256"],
            "modeling_task_sha256": task_binding["sha256"],
        }
        validation_binding = write("single_study_applicability_validation", validation)
        base = {
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "task_id": "TASK_GATE",
            "applicability_status": "NOT_APPLICABLE",
            "scope": "CONTROLLED_SINGLE_STUDY",
            "study_ids": ["STUDY_1"],
            "study_count": 1,
            "eligible_study_count": 1,
            "canonical_bundle_sha256": bundle_binding["sha256"],
            "modeling_task_sha256": task_binding["sha256"],
            "applicability_record_sha256": record_binding["sha256"],
            "reason": "Cross-Study validation is not applicable.",
        }
        by_id = {
            "single_study_applicability_record": record_binding,
            "single_study_applicability_validation": validation_binding,
            "canonical_bundle": bundle_binding,
            "modeling_task": task_binding,
        }
        for artifact_id, type_name in (
            ("model_report", "model_report"),
            ("reproducibility_evaluation", "reproducibility_evaluation"),
            ("interaction_report", "interaction_report"),
            ("robustness_report", "robustness_report"),
            ("virtual_prediction", "virtual_prediction"),
        ):
            payload = {**base, "artifact_type": type_name}
            if type_name in {"interaction_report", "robustness_report"}:
                payload["interaction_catalogue"] = []
            by_id[artifact_id] = write(artifact_id, payload)

        for manifest_id, report_id, filename in (
            ("interaction_manifest", "interaction_report", "interaction_discovery_report.json"),
            ("robustness_manifest", "robustness_report", "interaction_robustness_report.json"),
        ):
            report_binding = by_id[report_id]
            manifest = {
                **base,
                "artifact_type": manifest_id,
                "input_hashes": {
                    "task_sha256": task_binding["sha256"],
                    "canonical_bundle_sha256": bundle_binding["sha256"],
                    "applicability_record_sha256": record_binding["sha256"],
                },
                "output_hashes": {filename: report_binding["sha256"]},
            }
            by_id[manifest_id] = write(manifest_id, manifest)

        selection = {
            "schema_version": "1.1",
            "task_id": "TASK_GATE",
            "interaction_report_sha256": by_id["interaction_report"]["sha256"],
            "robustness_report_sha256": by_id["robustness_report"]["sha256"],
            "selected_interaction_ids": [],
            "not_selected_interaction_ids": [],
            "applicability_status": "NOT_APPLICABLE",
            "not_applicable_reason": record["modeling_validation_reason"],
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-15T12:00:00+08:00",
            "rationale": "No interaction candidates were generated for a one-Study scope.",
        }
        by_id["interaction_selection"] = write("interaction_selection", selection)
        previous = {"artifacts": [bundle_binding, task_binding]}
        return by_id, previous

    def test_single_study_g3_gate_accepts_only_hash_bound_not_applicable_records(self):
        by_id, previous = self._single_study_gate_fixture()
        _validate_single_study_na_bundle(by_id, previous)
        tampered = json.loads(self.files["model_report"].read_text(encoding="utf-8"))
        tampered["validation_metrics"] = {"mae": 0.01}
        self._write("model_report", tampered)
        by_id["model_report"]["sha256"] = sha256_file(self.files["model_report"])
        with self.assertRaisesRegex(ValueError, "fabricated scientific result field"):
            _validate_single_study_na_bundle(by_id, previous)

    def _single_study_g4_fixture(self):
        by_id, previous = self._single_study_gate_fixture()
        def bind(artifact_id, payload):
            path = self.root / (artifact_id + ".json")
            path.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8",
            )
            self.files[artifact_id] = path
            return {
                "artifact_id": artifact_id,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }

        for artifact_id in (
            "adapter_handoff", "dataset_manifest", "source_inventory",
            "mapping_plan", "mapping_validation", "build_spec",
            "build_spec_validation", "canonical_validation_report",
            "reconciliation_report", "reconciliation_decisions",
            "reconciliation_decision_validation", "discovery_report",
            "research_scope_record", "g2_review_packet", "publication_plan",
        ):
            by_id[artifact_id] = bind(artifact_id, {"schema_version": "1.0", "artifact_id": artifact_id})

        worker = {
            "schema_version": "1.0",
            "task_id": "WORKER_SINGLE_STUDY",
            "status": "completed",
            "summary": "Reviewed exact provenance and NOT_APPLICABLE scope.",
            "findings": [],
            "artifacts": [],
            "warnings": [],
            "unresolved_questions": [],
        }
        by_id["worker_review_output"] = bind("worker_review_output", worker)
        reviewable_ids = {
            "single_study_applicability_record",
            "single_study_applicability_validation",
            "canonical_bundle",
            "canonical_validation_report",
            "reconciliation_report",
            "reconciliation_decisions",
            "research_scope_record",
            "modeling_task",
            "model_report",
            "reproducibility_evaluation",
            "interaction_report",
            "robustness_report",
            "interaction_selection",
            "virtual_prediction",
            "interaction_manifest",
            "robustness_manifest",
        }
        reviewed_artifacts = [
            {
                "artifact_id": artifact_id,
                "path": by_id[artifact_id]["path"],
                "sha256": by_id[artifact_id]["sha256"],
            }
            for artifact_id in sorted(reviewable_ids)
        ]
        reviewed = {
            "schema_version": "1.0",
            "run_id": "RUN_GATE",
            "project_id": "PROJECT_TEST",
            "reviewer": "human-reviewer",
            "reviewed_at": "2026-11-15T13:00:00+08:00",
            "worker_output": {
                "artifact_id": "worker_review_output",
                "path": by_id["worker_review_output"]["path"],
                "sha256": by_id["worker_review_output"]["sha256"],
            },
            "reviewed_artifacts": reviewed_artifacts,
            "findings": [],
            "promotion_decision": "DO_NOT_PROMOTE",
            "overall_rationale": "The Worker review returned no findings requiring promotion.",
        }
        by_id["reviewed_findings"] = bind("reviewed_findings", reviewed)
        validation_path = self.root / "reviewed_findings_validation.json"
        by_id["reviewed_findings_validation"] = bind(
            "reviewed_findings_validation",
            {
                "schema_version": "1.0",
                "contract": "REVIEWED_WORKER_FINDINGS",
                "valid": True,
                "run_id": "RUN_GATE",
                "project_id": "PROJECT_TEST",
                "stage_id": "human_review_and_promotion",
                "run_root": str(self.root.resolve()),
                "record": {
                    "path": by_id["reviewed_findings"]["path"],
                    "sha256": by_id["reviewed_findings"]["sha256"],
                },
                "worker_output": {
                    "artifact_id": "worker_review_output",
                    "path": by_id["worker_review_output"]["path"],
                    "sha256": by_id["worker_review_output"]["sha256"],
                    "worker_status": worker["status"],
                    "finding_count": len(worker["findings"]),
                },
                "reviewed_artifact_count": len(reviewed_artifacts),
                "promotion_decision": reviewed["promotion_decision"],
                "expected_promotion_decision": reviewed["promotion_decision"],
                "validation_report_path": str(validation_path.resolve()),
                "errors": [],
            },
        )
        single_source_map = {
            "ADAPTER_HANDOFF": "adapter_handoff",
            "DATASET_MANIFEST": "dataset_manifest",
            "SOURCE_INVENTORY": "source_inventory",
            "MAPPING_PLAN": "mapping_plan",
            "MAPPING_VALIDATION": "mapping_validation",
            "BUILD_SPEC": "build_spec",
            "BUILD_SPEC_VALIDATION": "build_spec_validation",
            "SINGLE_STUDY_APPLICABILITY_RECORD": "single_study_applicability_record",
            "SINGLE_STUDY_APPLICABILITY_VALIDATION": "single_study_applicability_validation",
            "MODEL_NOT_APPLICABLE_RECORD": "model_report",
            "REPRODUCIBILITY_NOT_APPLICABLE_RECORD": "reproducibility_evaluation",
            "INTERACTION_NOT_APPLICABLE_RECORD": "interaction_report",
            "INTERACTION_NOT_APPLICABLE_MANIFEST": "interaction_manifest",
            "ROBUSTNESS_NOT_APPLICABLE_RECORD": "robustness_report",
            "ROBUSTNESS_NOT_APPLICABLE_MANIFEST": "robustness_manifest",
            "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD": "virtual_prediction",
            "INTERACTION_SELECTION": "interaction_selection",
            "WORKER_REVIEW_RECORD": "worker_review_output",
            "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
            "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
            "CANONICAL_BUNDLE": "canonical_bundle",
            "CANONICAL_VALIDATION": "canonical_validation_report",
            "RECONCILIATION_REPORT": "reconciliation_report",
            "RECONCILIATION_DECISIONS": "reconciliation_decisions",
            "RECONCILIATION_VALIDATION": "reconciliation_decision_validation",
            "DISCOVERY_REPORT": "discovery_report",
            "RESEARCH_SCOPE_RECORD": "research_scope_record",
            "G2_REVIEW_PACKET": "g2_review_packet",
            "MODELING_TASK": "modeling_task",
        }
        self._prepare_g4_publication_plan(
            by_id, single_source_map, "G3_SYNTHETIC_EVENT",
        )
        previous_gate = {
            "gate_id": "G3",
            "event_hash": "G3_SYNTHETIC_EVENT",
            "artifacts": [
                by_id["canonical_bundle"],
                by_id["modeling_task"],
                by_id["interaction_selection"],
            ],
        }
        return by_id, previous_gate

    def test_single_study_g4_requires_only_its_profile_specific_review_set(self):
        by_id, _previous_gate = self._single_study_g4_fixture()
        bindings = [
            (artifact_id, Path(item["path"]))
            for artifact_id, item in by_id.items()
            if artifact_id != "virtual_prediction"
        ]
        with self.assertRaisesRegex(
            ValueError,
            "Gate G4 requires artifact IDs: virtual_prediction",
        ):
            record_gate_decision(
                self.ledger, "G4", "APPROVE", "human-reviewer",
                "Synthetic profile-specific Gate precondition check.",
                bindings,
            )
        self.assertFalse(self.ledger.exists())

    def test_single_study_g4_accepts_exact_worker_review_set_and_na_evidence(self):
        by_id, previous_gate = self._single_study_g4_fixture()
        _validate_g4_reviewed_findings(list(by_id.values()), previous_gate)

    def test_single_study_g4_rejects_missing_reviewed_na_artifact(self):
        by_id, previous_gate = self._single_study_g4_fixture()
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["reviewed_artifacts"] = [
            item for item in reviewed["reviewed_artifacts"]
            if item["artifact_id"] != "single_study_applicability_record"
        ]
        self._write("reviewed_findings", reviewed)
        self._refresh_g4_reviewed_findings_validation()
        by_id["reviewed_findings"]["sha256"] = sha256_file(self.files["reviewed_findings"])
        by_id["reviewed_findings_validation"]["sha256"] = sha256_file(self.files["reviewed_findings_validation"])
        with self.assertRaisesRegex(ValueError, "bind exactly the artifacts supplied"):
            _validate_g4_reviewed_findings(list(by_id.values()), previous_gate)

    def test_single_study_g3_rejects_bundle_with_multiple_studies(self):
        by_id, previous = self._single_study_gate_fixture()
        bundle_binding = next(item for item in previous["artifacts"] if item["artifact_id"] == "canonical_bundle")
        bundle = json.loads(Path(bundle_binding["path"]).read_text(encoding="utf-8"))
        bundle["studies"].append({"study_id": "STUDY_2"})
        Path(bundle_binding["path"]).write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        bundle_binding["sha256"] = sha256_file(Path(bundle_binding["path"]))
        record = json.loads(self.files["single_study_applicability_record"].read_text(encoding="utf-8"))
        record["canonical_bundle_sha256"] = bundle_binding["sha256"]
        self._write("single_study_applicability_record", record)
        by_id["single_study_applicability_record"]["sha256"] = sha256_file(self.files["single_study_applicability_record"])
        with self.assertRaisesRegex(ValueError, "exactly one explicit Study"):
            _validate_single_study_na_bundle(by_id, previous)

    def test_missing_gate_binding_reports_stage_and_artifact_instead_of_keyerror(self):
        with self.assertRaisesRegex(
            ValueError,
            "G3 approval is missing required artifact 'interaction_selection'",
        ):
            _require_gate_binding({}, "interaction_selection", "G3")

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

    def test_full_analysis_g2_requires_explicit_virtual_query_decision(self):
        self._record_g0()
        self._record_g1()
        ids = [
            "canonical_bundle", "canonical_validation_report",
            "reconciliation_report", "reconciliation_review_queue",
            "reconciliation_decisions", "reconciliation_decision_validation",
            "discovery_report", "research_scope_record", "modeling_task",
        ]
        for artifact_id in ids:
            if artifact_id not in self.files:
                path = self.root / (artifact_id + ".json")
                path.write_text(json.dumps({"schema_version": "1.0", "artifact_id": artifact_id}), encoding="utf-8")
                self.files[artifact_id] = path
        review_ids = list(ids)
        ids.extend(self._prepare_review_packet("G2", review_ids))
        with self.assertRaisesRegex(ValueError, "virtual_query_decision"):
            self._record("G2", ids)

    def test_complete_gate_chain_and_exact_artifact_binding(self):
        self._complete_to_g2()
        self._record_g3()
        self._record("G4", self._g4_artifact_ids())
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

    def test_g4_full_analysis_requires_serialized_model_and_all_review_inputs(self):
        self._complete_to_g2()
        self._record_g3()
        incomplete = [item for item in self._g4_artifact_ids() if item != "model_artifact"]
        with self.assertRaisesRegex(ValueError, "requires artifact IDs: model_artifact"):
            self._record("G4", incomplete)

    def test_g4_rejects_package_source_not_produced_at_the_declared_run_artifact_path(self):
        self._complete_to_g2()
        self._record_g3()
        artifact_ids = self._g4_artifact_ids()
        by_id = {
            artifact_id: {
                "artifact_id": artifact_id,
                "path": str(self.files[artifact_id].resolve()),
                "sha256": sha256_file(self.files[artifact_id]),
            }
            for artifact_id in artifact_ids
        }
        gate_events = [
            json.loads(line)
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        g3_event = next(
            event for event in reversed(gate_events) if event.get("gate_id") == "G3"
        )

        plan_path = self.files["publication_plan"]
        validation_path = self.files["publication_plan_validation"]
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        source_entry = next(
            item for item in plan["artifacts"]
            if item["artifact_id"] == "MODEL_ARTIFACT_001"
        )
        alternate_path = self.root / "alternate_model_artifact.json"
        alternate_path.write_bytes(self.files["model_artifact"].read_bytes())
        source_entry["source_path"] = alternate_path.relative_to(self.root).as_posix()
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

        report = json.loads(validation_path.read_text(encoding="utf-8"))
        report["plan"]["sha256"] = sha256_file(plan_path)
        source_report = next(
            item for item in report["source_artifacts"]
            if item["package_artifact_id"] == "MODEL_ARTIFACT_001"
        )
        source_report["path"] = str(alternate_path.resolve())
        source_report["sha256"] = sha256_file(alternate_path)
        validation_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        by_id["publication_plan"]["sha256"] = sha256_file(plan_path)
        by_id["publication_plan_validation"]["sha256"] = sha256_file(validation_path)
        by_id["model_artifact"] = {
            "artifact_id": "model_artifact",
            "path": str(alternate_path.resolve()),
            "sha256": sha256_file(alternate_path),
        }

        run_events_path = self.root / "run_events.jsonl"
        run_events = [
            json.loads(line)
            for line in run_events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        prep_event = next(
            event for event in run_events
            if event.get("stage_id") == "publication_plan_preparation"
        )
        for output in prep_event["output_artifacts"]:
            if output["artifact_id"] == "publication_plan":
                output["sha256"] = sha256_file(plan_path)
            elif output["artifact_id"] == "publication_plan_validation":
                output["sha256"] = sha256_file(validation_path)
        run_events_path.write_text(
            "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                    for event in run_events),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "differs from its declared Run Artifact path"):
            _validate_g4_publication_plan(by_id, g3_event)

    def test_g4_rejects_worker_findings_without_traceable_evidence(self):
        self._complete_to_g2()
        self._record_g3()
        worker = json.loads(self.files["worker_review_output"].read_text(encoding="utf-8"))
        worker["findings"][0]["evidence"] = []
        self._write("worker_review_output", worker)
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["worker_output"]["sha256"] = sha256_file(self.files["worker_review_output"])
        self._write("reviewed_findings", reviewed)
        self._refresh_g4_reviewed_findings_validation()
        with self.assertRaisesRegex(ValueError, "requires exact evidence locators"):
            self._record("G4", self._g4_artifact_ids())

    def test_g4_requires_every_worker_finding_to_have_one_human_disposition(self):
        self._complete_to_g2()
        self._record_g3()
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["findings"] = []
        self._write("reviewed_findings", reviewed)
        self._refresh_g4_reviewed_findings_validation()
        with self.assertRaisesRegex(ValueError, "cover every Worker finding exactly once"):
            self._record("G4", self._g4_artifact_ids())

    def test_g4_rejects_promotion_decision_inconsistent_with_dispositions(self):
        self._complete_to_g2()
        self._record_g3()
        reviewed = json.loads(self.files["reviewed_findings"].read_text(encoding="utf-8"))
        reviewed["promotion_decision"] = "DO_NOT_PROMOTE"
        self._write("reviewed_findings", reviewed)
        self._refresh_g4_reviewed_findings_validation()
        with self.assertRaisesRegex(ValueError, "inconsistent with the individual human finding dispositions"):
            self._record("G4", self._g4_artifact_ids())

    def test_g4_rejects_gate_event_missing_one_required_review_artifact(self):
        self._complete_to_g2()
        self._record_g3()
        incomplete = [item for item in self._g4_artifact_ids() if item != "robustness_report"]
        with self.assertRaisesRegex(ValueError, "requires artifact IDs"):
            self._record("G4", incomplete)

    def test_changed_artifact_invalidates_its_gate_and_all_downstream_gates(self):
        self._complete_to_g2()
        self._record_g3()
        self._record("G4", self._g4_artifact_ids())
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
        # Rebuild the mandatory G0 review packet against the revised inputs before
        # recording a new approval; a gate event may not bypass packet validation.
        self._record_g0()
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

    def test_g0_gate_requires_and_rechecks_its_run_review_packet(self):
        with self.assertRaisesRegex(ValueError, "g0_review_packet"):
            self._record("G0", ["dataset_manifest", "source_inventory"])
        self._record_g0()
        ids = ["dataset_manifest", "source_inventory", "data_audit_report", "mapping_review_queue", "adapter_handoff"]
        review_ids = ["g0_review_packet", "g0_review_packet_validation"]
        report = json.loads(self.files["g0_review_packet_validation"].read_text(encoding="utf-8"))
        report["valid"] = False
        self._write("g0_review_packet_validation", report)
        with self.assertRaisesRegex(ValueError, "valid=true"):
            self._record("G0", ids + review_ids)

    def test_g0_gate_cannot_omit_a_formal_run_plan_input(self):
        self._record_g0()
        partial_ids = [
            "dataset_manifest", "source_inventory",
            "g0_review_packet", "g0_review_packet_validation",
        ]
        with self.assertRaisesRegex(ValueError, "exact supported Run Plan input set"):
            self._record("G0", partial_ids)

    def test_g0_review_packet_must_cover_every_gate_bound_input(self):
        self._record_g0()
        ids = ["dataset_manifest", "source_inventory", "data_audit_report", "mapping_review_queue", "adapter_handoff"]
        review_ids = self._prepare_review_packet("G0", ids[:-1])
        with self.assertRaisesRegex(ValueError, "cover exactly the Gate-bound input artifacts"):
            self._record("G0", ids + review_ids)

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
