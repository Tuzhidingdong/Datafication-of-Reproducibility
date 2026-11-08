from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path

from dor.cli import build_parser
from dor.gates import record_gate_decision
from dor.mapping import sha256_file
from dor.run_manager import (
    EVENT_GENESIS_HASH, _append_event, authorize_worker, build_artifact_manifest,
    build_resume_plan, initialize_run, record_stage_status, verify_run,
)


class RunManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dor-run-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.source_root = self.project / "sources"
        self.source_root.mkdir(parents=True)
        self.raw = self.source_root / "records.csv"
        self.raw.write_text("study,value\nS1,1\n", encoding="utf-8")
        self.run_root = self.root / "runs" / "RUN_TEST"
        self.plan_path = self.root / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"
        self.plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_RUN_TEST",
            "source_roots": [str(self.source_root)],
            "source_artifacts": [{"artifact_id": "raw_records", "path": str(self.raw)}],
            "stages": [
                {
                    "stage_id": "audit", "executor": "local", "depends_on": [],
                    "inputs": ["raw_records"],
                    "outputs": [
                        {"artifact_id": "dataset_manifest", "path": "01_audit/dataset_manifest.json"},
                        {"artifact_id": "source_inventory", "path": "01_audit/source_inventory.json"},
                    ],
                },
                {
                    "stage_id": "mapping", "executor": "local", "depends_on": ["audit"],
                    "inputs": ["source_inventory"],
                    "outputs": [{"artifact_id": "mapping_plan", "path": "02_mapping/mapping_plan.json"}],
                },
                {
                    "stage_id": "worker_review", "executor": "worker", "depends_on": ["mapping"],
                    "worker_task": {
                        "objective": "Review the mapping report for unresolved semantic ambiguity.",
                        "permitted_actions": ["Read the declared mapping plan", "Write a structured review JSON"],
                        "forbidden_actions": ["Change mapping decisions", "Edit source files"],
                        "max_context_tokens": 12000, "max_output_tokens": 2000,
                    },
                    "inputs": ["mapping_plan"],
                    "outputs": [{
                        "artifact_id": "worker_review_packet",
                        "path": "worker_staging/worker_review/review.json",
                        "kind": "worker_staging",
                    }],
                },
                {
                    "stage_id": "promotion_review", "executor": "manual", "depends_on": ["worker_review"],
                    "inputs": ["worker_review_packet"],
                    "outputs": [{"artifact_id": "reviewed_result", "path": "03_review/reviewed_result.json"}],
                },
                {
                    "stage_id": "independent_summary", "executor": "local", "depends_on": [],
                    "inputs": ["raw_records"],
                    "outputs": [{"artifact_id": "independent_summary", "path": "04_summary/summary.json"}],
                },
            ],
        }
        self.write_plan()
        initialize_run(self.plan_path, self.run_root, "RUN_TEST")

    def tearDown(self):
        self.temp.cleanup()

    def write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan, indent=2) + "\n", encoding="utf-8")

    def stage(self, stage_id):
        return next(item for item in self.plan["stages"] if item["stage_id"] == stage_id)

    def write_outputs(self, stage_id):
        for output in self.stage(stage_id)["outputs"]:
            path = self.run_root / output["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"stage": stage_id, "artifact": output["artifact_id"]}) + "\n", encoding="utf-8")

    def run_local(self, stage_id):
        record_stage_status(self.manifest_path, stage_id, "RUNNING", "local", command=f"test {stage_id}")
        self.write_outputs(stage_id)
        return record_stage_status(self.manifest_path, stage_id, "SUCCEEDED", "local")

    def run_manual(self, stage_id):
        record_stage_status(self.manifest_path, stage_id, "RUNNING", "manual")
        self.write_outputs(stage_id)
        return record_stage_status(self.manifest_path, stage_id, "SUCCEEDED", "manual")

    def run_to_mapping(self):
        self.run_local("audit")
        self.run_local("mapping")

    def test_init_declares_stage_graph_and_does_not_touch_sources(self):
        before = self.raw.read_bytes()
        result = verify_run(self.manifest_path)
        self.assertTrue(result["valid_manifest_and_event_chain"])
        self.assertEqual(self.raw.read_bytes(), before)
        actions = {item["stage_id"]: item["action"] for item in result["resume_plan"]["stages"]}
        self.assertEqual(actions["audit"], "READY_TO_RUN")
        self.assertEqual(actions["mapping"], "WAITING_FOR_DEPENDENCIES")
        self.assertEqual(actions["worker_review"], "WAITING_FOR_DEPENDENCIES")
        self.assertEqual(actions["independent_summary"], "READY_TO_RUN")

    def test_artifact_manifest_tracks_sources_and_produced_artifacts(self):
        self.run_local("audit")
        artifact_manifest = build_artifact_manifest(self.manifest_path)
        by_id = {item["artifact_id"]: item for item in artifact_manifest["artifacts"]}
        self.assertEqual(artifact_manifest["source_integrity"], "CURRENT")
        self.assertEqual(by_id["raw_records"]["status"], "CURRENT")
        self.assertEqual(by_id["dataset_manifest"]["status"], "CURRENT")
        self.assertEqual(by_id["source_inventory"]["status"], "CURRENT")
        self.assertEqual(by_id["mapping_plan"]["status"], "NOT_CREATED")
        self.assertEqual(
            artifact_manifest["source_of_truth"],
            "RUN_PLAN_SOURCE_SNAPSHOTS_AND_HASH_CHAINED_RUN_EVENTS; THIS_MANIFEST_IS_A_REGENERABLE_VIEW",
        )
        (self.run_root / "01_audit/source_inventory.json").write_text("tampered\n", encoding="utf-8")
        refreshed = build_artifact_manifest(self.manifest_path)
        by_id = {item["artifact_id"]: item for item in refreshed["artifacts"]}
        self.assertEqual(by_id["source_inventory"]["status"], "STALE_OR_MISSING")

    def test_dependency_graph_reuses_completed_stages(self):
        self.run_local("audit")
        resume = build_resume_plan(self.manifest_path)
        actions = {item["stage_id"]: item["action"] for item in resume["stages"]}
        self.assertEqual(actions["audit"], "REUSE")
        self.assertEqual(actions["mapping"], "READY_TO_RUN")
        self.assertEqual(actions["worker_review"], "WAITING_FOR_DEPENDENCIES")

    def test_upstream_output_change_invalidates_only_dependent_stages(self):
        self.run_to_mapping()
        self.run_local("independent_summary")
        inventory = self.run_root / "01_audit/source_inventory.json"
        inventory.write_text('{"tampered": true}\n', encoding="utf-8")
        resume = build_resume_plan(self.manifest_path)
        actions = {item["stage_id"]: item["action"] for item in resume["stages"]}
        self.assertEqual(actions["audit"], "REBUILD_REQUIRED")
        self.assertEqual(actions["mapping"], "INVALIDATED_BY_UPSTREAM")
        self.assertEqual(actions["worker_review"], "WAITING_FOR_DEPENDENCIES")
        self.assertEqual(actions["independent_summary"], "REUSE")

    def test_stale_stage_can_be_rebuilt_as_new_attempt_without_overwrite(self):
        self.run_to_mapping()
        self.run_local("independent_summary")
        inventory = self.run_root / "01_audit/source_inventory.json"
        inventory.write_text('{"tampered": true}\n', encoding="utf-8")
        resume = build_resume_plan(self.manifest_path)
        self.assertEqual(resume["stages"][0]["action"], "REBUILD_REQUIRED")
        # Archive the old attempt's declared outputs before retrying; Runtime never overwrites.
        for output in self.stage("audit")["outputs"]:
            (self.run_root / output["path"]).unlink()
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local", command="rebuild audit")
        self.write_outputs("audit")
        record_stage_status(self.manifest_path, "audit", "SUCCEEDED", "local")
        actions = {item["stage_id"]: item["action"] for item in build_resume_plan(self.manifest_path)["stages"]}
        self.assertEqual(actions["audit"], "REUSE")
        # The rebuilt source_inventory is byte-identical, so the dependent mapping
        # stage can be reused by content hash rather than rerun by event chronology.
        self.assertEqual(actions["mapping"], "REUSE")
        self.assertEqual(actions["independent_summary"], "REUSE")

    def test_source_change_requires_a_new_run(self):
        self.raw.write_text("study,value\nS1,2\n", encoding="utf-8")
        result = verify_run(self.manifest_path)
        self.assertEqual(result["source_integrity"], "SOURCE_CHANGED_NEW_RUN_REQUIRED")
        self.assertEqual(result["resume_plan"]["stages"][0]["action"], "SOURCE_CHANGED_NEW_RUN_REQUIRED")
        with self.assertRaisesRegex(ValueError, "create a new run"):
            record_stage_status(self.manifest_path, "audit", "RUNNING", "local")

    def test_worker_requires_authorization_and_is_confined_to_staging(self):
        self.run_to_mapping()
        with self.assertRaisesRegex(ValueError, "authorization"):
            record_stage_status(
                self.manifest_path, "worker_review", "RUNNING", "worker",
                role="reviewer", provider="OpenCode Go", model="free-model",
                project_root=str(self.project),
            )
        packet = authorize_worker(
            self.manifest_path, "worker_review", "independent reviewer",
            "OpenCode Go", "free-model", self.project, "human-reviewer",
            "Approved this bounded review task.",
        )
        self.assertEqual(packet["task_packet"]["permitted_outputs"][0]["artifact_id"], "worker_review_packet")
        self.assertIn("mapping report", packet["task_packet"]["objective"])
        self.assertEqual(packet["task_packet"]["max_context_tokens"], 12000)
        self.assertIn("Do not modify source files", packet["task_packet"]["constraints"][1])
        with self.assertRaisesRegex(ValueError, "exactly match"):
            record_stage_status(
                self.manifest_path, "worker_review", "RUNNING", "worker",
                role="different role", provider="OpenCode Go", model="free-model",
                project_root=str(self.project),
            )
        record_stage_status(
            self.manifest_path, "worker_review", "RUNNING", "worker",
            role="independent reviewer", provider="OpenCode Go", model="free-model",
            project_root=str(self.project),
        )
        self.write_outputs("worker_review")
        result = record_stage_status(
            self.manifest_path, "worker_review", "SUCCEEDED", "worker",
            job_id="job-123", session_id="session-456", task_id="task-789",
            input_tokens=120, output_tokens=35, reasoning_tokens=20,
            cache_read_tokens=500,
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        events = (self.run_root / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
        final_event = json.loads(events[-1])
        self.assertEqual(final_event["producer"]["job_id"], "job-123")
        self.assertEqual(final_event["producer"]["input_tokens"], 120)
        self.assertEqual(final_event["producer"]["cache_read_tokens"], 500)

    def test_local_stage_cannot_overwrite_existing_output(self):
        output = self.run_root / "01_audit/dataset_manifest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("old result\n", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
            record_stage_status(self.manifest_path, "audit", "RUNNING", "local")

    def test_worker_cannot_overwrite_existing_staging_file(self):
        self.run_to_mapping()
        output = self.run_root / "worker_staging/worker_review/review.json"
        output.parent.mkdir(parents=True)
        output.write_text("pre-existing\n", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "refusing overwrite"):
            authorize_worker(
                self.manifest_path, "worker_review", "reviewer", "OpenCode Go",
                "free-model", self.project, "human-reviewer", "Approved.",
            )

    def test_failure_can_be_retried_as_a_new_attempt(self):
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        record_stage_status(
            self.manifest_path, "audit", "FAILED", "local",
            reason="Synthetic test failure.",
        )
        retry = build_resume_plan(self.manifest_path)
        self.assertEqual(retry["stages"][0]["action"], "RETRY_REQUIRED")
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        self.write_outputs("audit")
        result = record_stage_status(self.manifest_path, "audit", "SUCCEEDED", "local")
        self.assertEqual(result["attempt"], 2)

    def test_running_attempt_requires_explicit_abandoned_confirmation(self):
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        with self.assertRaisesRegex(ValueError, "cannot start a new attempt"):
            record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        record_stage_status(
            self.manifest_path, "audit", "RUNNING", "local", confirm_abandoned=True,
        )
        self.write_outputs("audit")
        record_stage_status(self.manifest_path, "audit", "SUCCEEDED", "local")

    def test_worker_abandoned_attempt_requires_fresh_authorization(self):
        self.run_to_mapping()
        authorize_worker(
            self.manifest_path, "worker_review", "reviewer", "OpenCode Go",
            "free-model", self.project, "human-reviewer", "Initial approval.",
        )
        record_stage_status(
            self.manifest_path, "worker_review", "RUNNING", "worker",
            role="reviewer", provider="OpenCode Go", model="free-model",
            project_root=str(self.project),
        )
        authorize_worker(
            self.manifest_path, "worker_review", "reviewer", "OpenCode Go",
            "free-model", self.project, "human-reviewer", "Re-authorized after process inspection.",
            confirm_abandoned=True,
        )
        record_stage_status(
            self.manifest_path, "worker_review", "RUNNING", "worker",
            role="reviewer", provider="OpenCode Go", model="free-model",
            project_root=str(self.project), confirm_abandoned=True,
        )
        self.write_outputs("worker_review")
        record_stage_status(self.manifest_path, "worker_review", "SUCCEEDED", "worker")

    def test_gate_requirement_blocks_stage_without_approval(self):
        ledger = self.root / "workflow_gate_ledger.jsonl"
        self.plan["workflow_ledger_path"] = str(ledger)
        self.stage("audit")["required_gate"] = "G0"
        self.write_plan()
        # Reinitialize into a fresh run because the plan is hash-bound at init.
        new_root = self.root / "runs" / "RUN_GATED"
        initialize_run(self.plan_path, new_root, "RUN_GATED")
        gated_manifest = new_root / "run_manifest.json"
        state = build_resume_plan(gated_manifest)
        self.assertEqual(state["stages"][0]["action"], "BLOCKED_GATE")
        dataset_manifest = self.source_root / "dataset_manifest.json"
        inventory = self.source_root / "inventory.json"
        dataset_manifest.write_text('{"audit": "ok"}\n', encoding="utf-8")
        inventory.write_text('{"items": []}\n', encoding="utf-8")
        record_gate_decision(
            ledger, "G0", "APPROVE", "human-reviewer", "Approved the source audit scope.",
            [("dataset_manifest", dataset_manifest), ("source_inventory", inventory)],
        )
        state = build_resume_plan(gated_manifest)
        self.assertEqual(state["stages"][0]["action"], "READY_TO_RUN")

    def test_new_gate_approval_invalidates_stage_that_used_previous_decision(self):
        ledger = self.root / "workflow_gate_ledger.jsonl"
        self.plan["workflow_ledger_path"] = str(ledger)
        self.stage("audit")["required_gate"] = "G0"
        self.write_plan()
        gated_root = self.root / "runs" / "RUN_GATE_REVISION"
        initialize_run(self.plan_path, gated_root, "RUN_GATE_REVISION")
        gated_manifest = gated_root / "run_manifest.json"
        dataset_manifest = self.source_root / "dataset_manifest.json"
        inventory = self.source_root / "inventory.json"
        dataset_manifest.write_text('{"audit": "ok"}\n', encoding="utf-8")
        inventory.write_text('{"items": []}\n', encoding="utf-8")
        record_gate_decision(
            ledger, "G0", "APPROVE", "reviewer-1", "Initial scope approval.",
            [("dataset_manifest", dataset_manifest), ("source_inventory", inventory)],
        )
        record_stage_status(gated_manifest, "audit", "RUNNING", "local")
        for output in self.stage("audit")["outputs"]:
            path = gated_root / output["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        record_stage_status(gated_manifest, "audit", "SUCCEEDED", "local")
        record_gate_decision(
            ledger, "G0", "APPROVE", "reviewer-2", "Re-reviewed scope decision.",
            [("dataset_manifest", dataset_manifest), ("source_inventory", inventory)],
        )
        state = build_resume_plan(gated_manifest)
        self.assertEqual(state["stages"][0]["action"], "REBUILD_REQUIRED")
        self.assertTrue(any("gate decision changed" in reason.lower()
                            for reason in state["stages"][0]["reasons"]))

    def test_concurrent_stale_event_append_is_rejected(self):
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        ledger = self.run_root / "run_events.jsonl"
        with self.assertRaisesRegex(ValueError, "changed concurrently"):
            _append_event(
                ledger, "RUN_TEST",
                {"event_type": "STAGE_STATUS", "stage_id": "audit", "status": "RUNNING"},
                EVENT_GENESIS_HASH,
            )
        self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(verify_run(self.manifest_path)["event_count"], 1)

    def test_run_artifact_manifest_cannot_be_written_into_source_root(self):
        from dor.cli import main
        arguments = [
            "dor", "run-artifacts", "--manifest", str(self.manifest_path),
            "--out", str(self.raw),
        ]
        stderr = io.StringIO()
        with patch.object(sys, "argv", arguments), contextlib.redirect_stderr(stderr):
            exit_code = main()
        self.assertEqual(exit_code, 2)
        self.assertIn("protected source_roots", stderr.getvalue())
        self.assertEqual(self.raw.read_text(encoding="utf-8"), "study,value\nS1,1\n")

    def test_event_chain_tampering_is_detected(self):
        self.run_local("audit")
        ledger = self.run_root / "run_events.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[0])
        event["reason"] = "rewritten"
        lines[0] = json.dumps(event)
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_run(self.manifest_path)

    def test_run_manifest_snapshot_is_bound_to_initialization_event(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["source_artifacts"][0]["sha256"] = "f" * 64
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RUN_INITIALIZED event snapshot"):
            verify_run(self.manifest_path)

    def test_plan_is_immutable_after_run_init(self):
        copied_plan = self.run_root / "run_plan.json"
        copied_plan.write_text(copied_plan.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            verify_run(self.manifest_path)

    def test_dependency_cycle_is_rejected_before_workspace_creation(self):
        self.plan["stages"][0]["depends_on"] = ["mapping"]
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "cycle"):
            initialize_run(self.plan_path, self.root / "runs" / "CYCLE", "CYCLE")
        self.assertFalse((self.root / "runs" / "CYCLE").exists())

    def test_workspace_cannot_be_nested_inside_a_protected_source_root(self):
        nested = self.source_root / "derived_run"
        with self.assertRaisesRegex(ValueError, "must be separate"):
            initialize_run(self.plan_path, nested, "NESTED")
        self.assertFalse(nested.exists())

    def test_failed_event_requires_a_reason_and_hash_chain_detects_bad_event_semantics(self):
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        ledger = self.run_root / "run_events.jsonl"
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        from dor.run_manager import _hash_payload
        payload = {
            "schema_version": "1.0", "run_id": "RUN_TEST", "sequence": 3,
            "recorded_at": "2026-11-08T00:00:00Z", "previous_event_hash": events[-1]["event_hash"],
            "event_type": "STAGE_STATUS", "stage_id": "audit", "status": "FAILED",
            "attempt": 1, "producer": {"kind": "local"}, "input_artifacts": events[-1]["input_artifacts"],
            "output_artifacts": [], "gate_approval": None, "reason": "",
        }
        forged = {**payload, "event_hash": _hash_payload(payload)}
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaisesRegex(ValueError, "non-empty reason"):
            verify_run(self.manifest_path)

    def test_worker_stage_requires_explicit_task_specification(self):
        bad = dict(self.plan)
        bad["stages"] = [dict(item) for item in self.plan["stages"]]
        bad["stages"][2] = dict(bad["stages"][2])
        bad["stages"][2].pop("worker_task", None)
        bad_path = self.root / "no_worker_task_plan.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "worker_task"):
            initialize_run(bad_path, self.root / "runs" / "NO_TASK", "NO_TASK")

    def test_duplicate_worker_authorization_is_rejected(self):
        self.run_to_mapping()
        authorize_worker(
            self.manifest_path, "worker_review", "reviewer", "OpenCode Go",
            "free-model", self.project, "human-reviewer", "Approved bounded task.",
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            authorize_worker(
                self.manifest_path, "worker_review", "reviewer", "OpenCode Go",
                "free-model", self.project, "human-reviewer", "Duplicate authorization.",
            )

    def test_worker_stage_cannot_write_to_derived_output(self):
        bad = dict(self.plan)
        bad["stages"] = [dict(item) for item in self.plan["stages"]]
        bad["stages"][2] = dict(bad["stages"][2])
        bad["stages"][2]["outputs"] = [{"artifact_id": "worker_output", "path": "02_worker/result.json", "kind": "derived"}]
        bad_path = self.root / "bad_plan.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "only to worker_staging"):
            initialize_run(bad_path, self.root / "runs" / "BAD", "BAD")

    def test_cli_registers_run_manager_commands(self):
        parser = build_parser()
        subparsers = next(
            action.choices for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        for command in (
            "run-init", "run-status", "run-verify", "run-resume-plan", "run-artifacts",
            "run-worker-authorize", "run-stage-record",
        ):
            self.assertIn(command, subparsers)


if __name__ == "__main__":
    unittest.main()
