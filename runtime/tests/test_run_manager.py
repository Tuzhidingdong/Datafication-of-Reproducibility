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
from dor.mapping import sha256_file
from dor.run_manager import (
    EVENT_GENESIS_HASH, _append_event, authorize_worker, build_artifact_manifest,
    build_resume_plan, build_run_usage_report, initialize_run, record_stage_status, verify_run,
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

    def test_run_lifecycle_connects_worker_retry_human_review_and_publication_manifest(self):
        lifecycle_root = self.root / "lifecycle"
        source_root = lifecycle_root / "sources"
        source_root.mkdir(parents=True)
        source = source_root / "structured_input.json"
        source.write_text(json.dumps({"records": [{"record_id": "SYN_1", "value": 1}]}), encoding="utf-8")
        project_root = lifecycle_root / "project"
        project_root.mkdir()
        run_root = lifecycle_root / "runs" / "RUN_LIFECYCLE"
        plan_path = lifecycle_root / "lifecycle_run_plan.json"
        manifest_path = run_root / "run_manifest.json"

        plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_LIFECYCLE",
            "source_roots": [str(source_root.resolve())],
            "source_artifacts": [{"artifact_id": "structured_input", "path": str(source.resolve())}],
            "stages": [
                {
                    "stage_id": "intake",
                    "executor": "local",
                    "depends_on": [],
                    "inputs": ["structured_input"],
                    "outputs": [{"artifact_id": "audit_report", "path": "01_intake/audit_report.json"}],
                },
                {
                    "stage_id": "analysis",
                    "executor": "local",
                    "depends_on": ["intake"],
                    "inputs": ["audit_report"],
                    "outputs": [{"artifact_id": "analysis_report", "path": "02_analysis/analysis_report.json"}],
                },
                {
                    "stage_id": "independent_review",
                    "executor": "worker",
                    "depends_on": ["intake", "analysis"],
                    "inputs": ["audit_report", "analysis_report"],
                    "worker_task": {
                        "objective": "Review the declared synthetic analysis artifacts and report traceable limitations.",
                        "permitted_actions": ["Read the two declared JSON inputs", "Write a structured review JSON"],
                        "forbidden_actions": ["Modify source inputs", "Approve any gate", "Write outside the worker staging path"],
                        "max_context_tokens": 4000,
                        "max_output_tokens": 1000,
                    },
                    "outputs": [{
                        "artifact_id": "worker_review_output",
                        "path": "worker_staging/independent_review/review.json",
                        "kind": "worker_staging",
                    }],
                },
                {
                    "stage_id": "human_review",
                    "executor": "manual",
                    "depends_on": ["independent_review"],
                    "inputs": ["worker_review_output"],
                    "outputs": [{"artifact_id": "reviewed_findings", "path": "03_review/reviewed_findings.json"}],
                },
                {
                    "stage_id": "publication_delivery",
                    "executor": "local",
                    "depends_on": ["intake", "analysis", "independent_review", "human_review"],
                    "inputs": ["structured_input", "audit_report", "analysis_report", "worker_review_output", "reviewed_findings"],
                    "outputs": [{"artifact_id": "publication_manifest", "path": "04_publication/package_manifest.json"}],
                },
            ],
        }
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        initialize_run(plan_path, run_root, "RUN_LIFECYCLE")

        def record_local(stage_id, artifact_id, payload):
            record_stage_status(manifest_path, stage_id, "RUNNING", "local", command=f"synthetic {stage_id}")
            output = next(item for item in next(s for s in plan["stages"] if s["stage_id"] == stage_id)["outputs"]
                          if item["artifact_id"] == artifact_id)
            path = run_root / output["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            record_stage_status(manifest_path, stage_id, "SUCCEEDED", "local")

        record_local("intake", "audit_report", {
            "schema_version": "1.0", "input_records": 1, "scope": "SYNTHETIC_ONLY",
        })
        record_local("analysis", "analysis_report", {
            "schema_version": "1.0", "result": "SYNTHETIC_ANALYSIS_COMPLETE",
            "source_artifact": "structured_input",
        })

        first_auth = authorize_worker(
            manifest_path, "independent_review", "independent_reviewer",
            "synthetic-provider", "synthetic-review-model",
            project_root, "human-operator", "Authorize the isolated synthetic review attempt.",
        )
        self.assertEqual(first_auth["attempt"], 1)
        self.assertEqual(len(first_auth["task_packet"]["inputs"]), 2)
        self.assertEqual(len(first_auth["task_packet"]["permitted_outputs"]), 1)
        worker_kwargs = {
            "role": "independent_reviewer",
            "provider": "synthetic-provider",
            "model": "synthetic-review-model",
            "project_root": str(project_root.resolve()),
        }
        record_stage_status(
            manifest_path, "independent_review", "RUNNING", "worker",
            **worker_kwargs,
        )
        failed_worker_output = run_root / "worker_staging" / "independent_review" / "review.json"
        failed_worker_output.parent.mkdir(parents=True, exist_ok=True)
        failed_worker_output.write_text(json.dumps({
            "schema_version": "1.0",
            "task_id": "DOR_RUN_LIFECYCLE_independent_review_ATTEMPT_0001",
            "status": "completed",
            "summary": "This packet deliberately omits required findings and must be rejected.",
            "artifacts": [],
            "warnings": [],
            "unresolved_questions": [],
        }, indent=2) + "\\n", encoding="utf-8")
        failed_attempt = record_stage_status(
            manifest_path, "independent_review", "SUCCEEDED", "worker",
            **worker_kwargs, job_id="synthetic-job-failed",
            input_tokens=80, output_tokens=20,
        )
        self.assertEqual(failed_attempt["status"], "FAILED")
        self.assertTrue(failed_attempt["automatic_failure"])
        self.assertFalse(failed_worker_output.exists())
        archived_review = run_root / failed_attempt["archived_outputs"][0]["archive_path"]
        self.assertTrue(archived_review.is_file())
        self.assertTrue((run_root / failed_attempt["archive_manifest"]["path"]).is_file())
        failed_resume = build_resume_plan(manifest_path)
        failed_state = next(item for item in failed_resume["stages"] if item["stage_id"] == "independent_review")
        self.assertEqual(failed_state["action"], "RETRY_REQUIRED")

        second_auth = authorize_worker(
            manifest_path, "independent_review", "independent_reviewer",
            "synthetic-provider", "synthetic-review-model",
            project_root, "human-operator", "Authorize a new attempt after the recorded failure.",
        )
        self.assertEqual(second_auth["attempt"], 2)
        record_stage_status(
            manifest_path, "independent_review", "RUNNING", "worker",
            **worker_kwargs,
        )
        worker_output = run_root / "worker_staging" / "independent_review" / "review.json"
        worker_output.parent.mkdir(parents=True, exist_ok=True)
        worker_output.write_text(json.dumps({
            "schema_version": "1.0",
            "task_id": "DOR_RUN_LIFECYCLE_independent_review_ATTEMPT_0002",
            "status": "completed",
            "summary": "The synthetic inputs are traceable and contain no unresolved blocker.",
            "findings": [],
            "artifacts": [],
            "warnings": [],
            "unresolved_questions": [],
        }, indent=2) + "\n", encoding="utf-8")
        record_stage_status(
            manifest_path, "independent_review", "SUCCEEDED", "worker",
            **worker_kwargs, job_id="synthetic-job-success",
            session_id="synthetic-session-success",
            input_tokens=200, output_tokens=50, reasoning_tokens=30,
            cache_read_tokens=40, cache_write_tokens=5,
        )

        record_stage_status(manifest_path, "human_review", "RUNNING", "manual")
        disposition = run_root / "03_review" / "reviewed_findings.json"
        disposition.parent.mkdir(parents=True, exist_ok=True)
        disposition.write_text(json.dumps({
            "schema_version": "1.0",
            "decision": "NO_FINDINGS_TO_PROMOTE",
            "reviewer": "human-operator",
            "worker_output_sha256": sha256_file(worker_output),
        }, indent=2) + "\n", encoding="utf-8")
        record_stage_status(manifest_path, "human_review", "SUCCEEDED", "manual")

        record_stage_status(manifest_path, "publication_delivery", "RUNNING", "local",
                            command="assemble synthetic publication manifest")
        publication = run_root / "04_publication" / "package_manifest.json"
        publication.parent.mkdir(parents=True, exist_ok=True)
        publication.write_text(json.dumps({
            "schema_version": "1.0",
            "run_id": "RUN_LIFECYCLE",
            "artifact_ids": [
                "audit_report", "analysis_report", "worker_review_output", "reviewed_findings",
            ],
        }, indent=2) + "\n", encoding="utf-8")
        record_stage_status(manifest_path, "publication_delivery", "SUCCEEDED", "local")

        verified = verify_run(manifest_path)
        self.assertTrue(verified["valid_manifest_and_event_chain"])
        self.assertEqual(verified["source_integrity"], "CURRENT")
        artifacts = build_artifact_manifest(manifest_path)
        statuses = {item["artifact_id"]: item["status"] for item in artifacts["artifacts"]}
        self.assertEqual(statuses["publication_manifest"], "CURRENT")
        self.assertEqual(statuses["worker_review_output"], "CURRENT")
        usage = build_run_usage_report(manifest_path)
        self.assertEqual(usage["terminal_attempt_count"], 6)
        self.assertEqual(usage["usage_summary"]["attempts_with_any_usage"], 2)
        self.assertEqual(usage["usage_summary"]["usage_coverage"], "PARTIAL")
        self.assertEqual(usage["usage_summary"]["token_totals"]["input_tokens"]["total"], 280)
        self.assertEqual(usage["usage_summary"]["token_totals"]["output_tokens"]["total"], 70)
        self.assertEqual(usage["usage_summary"]["token_totals"]["reasoning_tokens"]["total"], 30)
        self.assertEqual(usage["usage_summary"]["token_totals"]["cache_read_tokens"]["total"], 40)
        self.assertEqual(usage["usage_summary"]["token_totals"]["cache_write_tokens"]["total"], 5)
        final_resume = build_resume_plan(manifest_path)
        self.assertEqual(final_resume["next_actions"], [])
        self.assertTrue(all(item["action"] == "REUSE" for item in final_resume["stages"]))

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

    def test_run_usage_aggregates_only_terminal_stage_attempts(self):
        record_stage_status(
            self.manifest_path, "audit", "RUNNING", "local",
            command="dor audit", provider="test-provider", model="test-model",
        )
        self.write_outputs("audit")
        record_stage_status(
            self.manifest_path, "audit", "SUCCEEDED", "local",
            input_tokens=120, output_tokens=35, reasoning_tokens=20,
            cache_read_tokens=500, cache_write_tokens=25,
        )
        report = build_run_usage_report(self.manifest_path)
        self.assertEqual(report["terminal_attempt_count"], 1)
        self.assertEqual(report["running_event_count"], 1)
        self.assertEqual(report["usage_summary"]["token_totals"]["input_tokens"]["total"], 120)
        self.assertEqual(report["usage_summary"]["token_totals"]["output_tokens"]["total"], 35)
        self.assertEqual(report["usage_summary"]["token_totals"]["reasoning_tokens"]["total"], 20)
        self.assertEqual(report["usage_summary"]["token_totals"]["cache_read_tokens"]["total"], 500)
        self.assertEqual(report["usage_summary"]["input_plus_output_tokens"], 155)
        self.assertEqual(report["by_provider_model"][0]["provider"], "test-provider")
        self.assertEqual(report["by_provider_model"][0]["model"], "test-model")
        self.assertEqual(report["by_role"][0]["role"], "UNSPECIFIED")
        self.assertEqual(report["by_role_provider_model"][0]["provider"], "test-provider")
        self.assertEqual(report["accounting_policy"]["excluded_events"], ["RUNNING", "SKIPPED", "WORKER_AUTHORIZED"])

    def test_run_stage_rejects_boolean_token_counts(self):
        with self.assertRaisesRegex(ValueError, "input_tokens"):
            record_stage_status(
                self.manifest_path, "audit", "RUNNING", "local",
                input_tokens=True,
            )

    def test_run_usage_keeps_unreported_values_null(self):
        report = build_run_usage_report(self.manifest_path)
        self.assertEqual(report["terminal_attempt_count"], 0)
        self.assertIsNone(report["usage_summary"]["token_totals"]["input_tokens"]["total"])
        self.assertEqual(report["usage_summary"]["usage_coverage"], "NO_USAGE_REPORTED")

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

        artifact_manifest = build_artifact_manifest(self.manifest_path)
        artifact_states = {item["artifact_id"]: item["status"] for item in artifact_manifest["artifacts"]}
        for output in self.stage("mapping")["outputs"]:
            self.assertEqual(artifact_states[output["artifact_id"]], "STALE_OR_MISSING")
        for output in self.stage("independent_summary")["outputs"]:
            self.assertEqual(artifact_states[output["artifact_id"]], "CURRENT")

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
        with self.assertRaisesRegex(ValueError, "authorization packet"):
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

    def _prepare_gated_mapping_run(self, run_id):
        ledger = self.root / (run_id + "_workflow_gate_ledger.jsonl")
        self.plan["workflow_ledger_path"] = str(ledger)
        self.stage("mapping")["required_gate"] = "G0"
        self.write_plan()
        gated_root = self.root / "runs" / run_id
        initialize_run(self.plan_path, gated_root, run_id)
        gated_manifest = gated_root / "run_manifest.json"

        record_stage_status(gated_manifest, "audit", "RUNNING", "local", command="synthetic gated audit")
        for output in self.stage("audit")["outputs"]:
            path = gated_root / output["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"stage": "audit", "artifact": output["artifact_id"]}), encoding="utf-8")
        record_stage_status(gated_manifest, "audit", "SUCCEEDED", "local")
        inventory = gated_root / "01_audit" / "source_inventory.json"
        binding = {
            "artifact_id": "source_inventory",
            "path": str(inventory.resolve()),
            "sha256": sha256_file(inventory),
        }
        gate_snapshot = {
            "valid_ledger": True,
            "gates": {
                "G0": {"status": "APPROVED", "event_hash": "a" * 64},
            },
            "events": {
                "G0": {"artifacts": [binding]},
            },
        }
        return gated_manifest, inventory, gate_snapshot

    def test_gate_requirement_blocks_stage_without_approval(self):
        gated_manifest, _inventory, approved_snapshot = self._prepare_gated_mapping_run("RUN_GATED")
        with patch("dor.run_manager._gate_status", return_value=None):
            state = build_resume_plan(gated_manifest)
        mapping_state = next(item for item in state["stages"] if item["stage_id"] == "mapping")
        self.assertEqual(mapping_state["action"], "BLOCKED_GATE")

        with patch("dor.run_manager._gate_status", return_value=approved_snapshot):
            state = build_resume_plan(gated_manifest)
            mapping_state = next(item for item in state["stages"] if item["stage_id"] == "mapping")
            self.assertEqual(mapping_state["action"], "READY_TO_RUN")
            record_stage_status(gated_manifest, "mapping", "RUNNING", "local")

    def test_gate_approval_requires_the_exact_same_artifact_path(self):
        gated_manifest, inventory, approved_snapshot = self._prepare_gated_mapping_run("RUN_GATE_PATH")
        external_copy = self.root / "reviewed_source_inventory.json"
        external_copy.write_bytes(inventory.read_bytes())
        approved_snapshot["events"]["G0"]["artifacts"][0]["path"] = str(external_copy.resolve())
        with patch("dor.run_manager._gate_status", return_value=approved_snapshot):
            state = build_resume_plan(gated_manifest)
            mapping_state = next(item for item in state["stages"] if item["stage_id"] == "mapping")
            self.assertEqual(mapping_state["action"], "BLOCKED_GATE")
            self.assertTrue(any("path differs" in reason for reason in mapping_state["reasons"]))
            with self.assertRaisesRegex(ValueError, "BLOCKED_GATE"):
                record_stage_status(gated_manifest, "mapping", "RUNNING", "local")

    def test_gate_approval_requires_the_exact_same_artifact_sha256(self):
        gated_manifest, _inventory, approved_snapshot = self._prepare_gated_mapping_run("RUN_GATE_HASH")
        approved_snapshot["events"]["G0"]["artifacts"][0]["sha256"] = "f" * 64
        with patch("dor.run_manager._gate_status", return_value=approved_snapshot):
            state = build_resume_plan(gated_manifest)
            mapping_state = next(item for item in state["stages"] if item["stage_id"] == "mapping")
            self.assertEqual(mapping_state["action"], "BLOCKED_GATE")
            self.assertTrue(any("SHA-256 differs" in reason for reason in mapping_state["reasons"]))
            with self.assertRaisesRegex(ValueError, "BLOCKED_GATE"):
                record_stage_status(gated_manifest, "mapping", "RUNNING", "local")

    def test_new_gate_approval_invalidates_stage_that_used_previous_decision(self):
        gated_manifest, _inventory, first_snapshot = self._prepare_gated_mapping_run("RUN_GATE_REVISION")
        with patch("dor.run_manager._gate_status", return_value=first_snapshot):
            record_stage_status(gated_manifest, "mapping", "RUNNING", "local")
            for output in self.stage("mapping")["outputs"]:
                path = gated_manifest.parent / output["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            record_stage_status(gated_manifest, "mapping", "SUCCEEDED", "local")

        revised_snapshot = json.loads(json.dumps(first_snapshot))
        revised_snapshot["gates"]["G0"]["event_hash"] = "b" * 64
        with patch("dor.run_manager._gate_status", return_value=revised_snapshot):
            state = build_resume_plan(gated_manifest)
        mapping_state = next(item for item in state["stages"] if item["stage_id"] == "mapping")
        self.assertEqual(mapping_state["action"], "REBUILD_REQUIRED")
        self.assertTrue(any("gate decision changed" in reason.lower()
                            for reason in mapping_state["reasons"]))

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
        self.assertEqual(verify_run(self.manifest_path)["event_count"], 2)

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

    def test_event_sequence_rejects_boolean_even_when_hash_is_recomputed(self):
        from dor.run_manager import _hash_payload
        ledger = self.run_root / "run_events.jsonl"
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        events[0]["sequence"] = True
        payload = {key: value for key, value in events[0].items() if key != "event_hash"}
        events[0]["event_hash"] = _hash_payload(payload)
        ledger.write_text("\n".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events
        ) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sequence must be an exact integer"):
            verify_run(self.manifest_path)

    def test_stage_attempt_rejects_boolean_even_when_hash_is_recomputed(self):
        from dor.run_manager import _hash_payload
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local")
        ledger = self.run_root / "run_events.jsonl"
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        events[-1]["attempt"] = True
        payload = {key: value for key, value in events[-1].items() if key != "event_hash"}
        events[-1]["event_hash"] = _hash_payload(payload)
        ledger.write_text("\n".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events
        ) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "attempt .* exact positive integer"):
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

    def _initialize_conditional_plan(self, include_unavailable_dependency=False):
        conditional = {
            "stage_id": "optional_analysis",
            "executor": "local",
            "depends_on": ["audit"] + (["independent_summary"] if include_unavailable_dependency else []),
            "inputs": ["dataset_manifest"] + (["independent_summary"] if include_unavailable_dependency else []),
            "activation": {
                "artifact_id": "dataset_manifest",
                "json_pointer": "/selected_ids",
                "operator": "array_non_empty",
            },
            "outputs": [{
                "artifact_id": "optional_analysis_output",
                "path": "05_optional/analysis.json",
            }],
        }
        self.plan["stages"].append(conditional)
        self.write_plan()
        self.run_root = self.root / "runs" / (
            "RUN_CONDITIONAL_WITH_PENDING_DEP" if include_unavailable_dependency else "RUN_CONDITIONAL_REACTIVATION"
        )
        self.manifest_path = self.run_root / "run_manifest.json"
        initialize_run(
            self.plan_path,
            self.run_root,
            "RUN_CONDITIONAL_WITH_PENDING_DEP" if include_unavailable_dependency else "RUN_CONDITIONAL_REACTIVATION",
        )

    def _write_audit_outputs_with_selection(self, selected_ids):
        self.write_outputs("audit")
        manifest = self.run_root / "01_audit/dataset_manifest.json"
        manifest.write_text(
            json.dumps({"selected_ids": selected_ids}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _archive_stage_outputs(self, stage_id):
        for output in self.stage(stage_id)["outputs"]:
            path = self.run_root / output["path"]
            if path.exists():
                path.unlink()

    def _run_audit_with_selection(self, selected_ids):
        record_stage_status(self.manifest_path, "audit", "RUNNING", "local", command="audit")
        self._write_audit_outputs_with_selection(selected_ids)
        return record_stage_status(self.manifest_path, "audit", "SUCCEEDED", "local")

    def test_conditional_stage_can_be_skipped_without_non_activation_inputs(self):
        self._initialize_conditional_plan(include_unavailable_dependency=True)
        self._run_audit_with_selection([])
        resume = build_resume_plan(self.manifest_path)
        actions = {item["stage_id"]: item["action"] for item in resume["stages"]}
        self.assertEqual(actions["independent_summary"], "READY_TO_RUN")
        self.assertEqual(actions["optional_analysis"], "SKIP_REQUIRED")

        result = record_stage_status(
            self.manifest_path, "optional_analysis", "SKIPPED", "local",
            reason="The selection array is empty.",
        )
        self.assertEqual(result["status"], "SKIPPED")
        self.assertTrue(verify_run(self.manifest_path)["valid_manifest_and_event_chain"])
        actions = {
            item["stage_id"]: item["action"]
            for item in build_resume_plan(self.manifest_path)["stages"]
        }
        self.assertEqual(actions["optional_analysis"], "SKIPPED")

    def test_running_conditional_stage_cannot_be_closed_as_skipped(self):
        self._initialize_conditional_plan()
        self._run_audit_with_selection(["ITEM_1"])
        record_stage_status(
            self.manifest_path, "optional_analysis", "RUNNING", "local",
        )
        dataset_manifest = self.run_root / "01_audit/dataset_manifest.json"
        dataset_manifest.write_text('{"selected_ids":[]}\n', encoding="utf-8")
        # The unfinished process must be reconciled before a SKIPPED event can be appended.
        with self.assertRaisesRegex(ValueError, "cannot be skipped now"):
            record_stage_status(
                self.manifest_path, "optional_analysis", "SKIPPED", "local",
                reason="Condition became false.",
            )

    def test_skipped_stage_reactivates_and_requires_archiving_older_outputs(self):
        self._initialize_conditional_plan()
        self._run_audit_with_selection([])
        record_stage_status(
            self.manifest_path, "optional_analysis", "SKIPPED", "local",
            reason="No item was selected.",
        )

        # Change the activation value. The producer is stale until its outputs are rebuilt.
        dataset_manifest = self.run_root / "01_audit/dataset_manifest.json"
        dataset_manifest.write_text('{"selected_ids":["ITEM_1"]}\n', encoding="utf-8")
        actions = {
            item["stage_id"]: item["action"]
            for item in build_resume_plan(self.manifest_path)["stages"]
        }
        self.assertEqual(actions["audit"], "REBUILD_REQUIRED")
        self.assertEqual(actions["optional_analysis"], "WAITING_FOR_ACTIVATION_INPUT")

        self._archive_stage_outputs("audit")
        self._run_audit_with_selection(["ITEM_1"])
        actions = {
            item["stage_id"]: item["action"]
            for item in build_resume_plan(self.manifest_path)["stages"]
        }
        self.assertEqual(actions["optional_analysis"], "READY_TO_RUN")
        record_stage_status(self.manifest_path, "optional_analysis", "RUNNING", "local")
        self.write_outputs("optional_analysis")
        record_stage_status(self.manifest_path, "optional_analysis", "SUCCEEDED", "local")

        # A later false decision is recorded as a skip; old outputs remain historical.
        dataset_manifest.write_text('{"selected_ids":[]}\n', encoding="utf-8")
        self.assertEqual(
            next(item["action"] for item in build_resume_plan(self.manifest_path)["stages"]
                 if item["stage_id"] == "audit"),
            "REBUILD_REQUIRED",
        )
        self._archive_stage_outputs("audit")
        self._run_audit_with_selection([])
        self.assertEqual(
            next(item["action"] for item in build_resume_plan(self.manifest_path)["stages"]
                 if item["stage_id"] == "optional_analysis"),
            "SKIP_REQUIRED",
        )
        record_stage_status(
            self.manifest_path, "optional_analysis", "SKIPPED", "local",
            reason="Selection was withdrawn.",
        )

        # Reactivation cannot overwrite the successful output from the previous attempt.
        dataset_manifest.write_text('{"selected_ids":["ITEM_1"]}\n', encoding="utf-8")
        self._archive_stage_outputs("audit")
        self._run_audit_with_selection(["ITEM_1"])
        action = next(
            item["action"] for item in build_resume_plan(self.manifest_path)["stages"]
            if item["stage_id"] == "optional_analysis"
        )
        self.assertEqual(action, "REBUILD_REQUIRED")

    def test_cli_registers_run_manager_commands(self):
        parser = build_parser()
        subparsers = next(
            action.choices for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        for command in (
            "run-init", "run-status", "run-verify", "run-resume-plan", "run-artifacts",
            "run-usage", "validate-execution-contract",
            "run-worker-authorize", "run-stage-record",
        ):
            self.assertIn(command, subparsers)
        status_action = next(
            action for action in subparsers["run-stage-record"]._actions
            if action.dest == "status"
        )
        self.assertIn("SKIPPED", status_action.choices)

    def test_run_event_schema_declares_conditional_skip_evidence(self):
        root = Path(__file__).resolve().parents[2]
        schema = json.loads((root / "schemas" / "run_event.schema.json").read_text(encoding="utf-8"))
        self.assertIn("SKIPPED", schema["properties"]["status"]["enum"])
        self.assertIn("activation_evaluation", schema["properties"])
        skip_rule = next(
            item for item in schema["allOf"]
            if item.get("if", {}).get("properties", {}).get("status", {}).get("const") == "SKIPPED"
        )
        self.assertIn("activation_evaluation", skip_rule["then"]["required"])
        self.assertEqual(skip_rule["then"]["properties"]["input_artifacts"]["maxItems"], 1)


if __name__ == "__main__":
    unittest.main()
