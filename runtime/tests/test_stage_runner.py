from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.run_manager import build_resume_plan, initialize_run, verify_run
from dor.stage_runner import advance_run, execute_local_stage


class ContractBoundStageRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dor-stage-runner-")
        self.root = Path(self.temp.name)
        self.source_root = self.root / "sources"
        self.source_root.mkdir()
        self.source = self.source_root / "input.json"
        self.source.write_text(json.dumps({"records": [{"id": "SYN_1"}]}), encoding="utf-8")
        self.run_root = self.root / "runs" / "RUN_STAGE_RUNNER"
        self.plan_path = self.root / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"
        self.plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_STAGE_RUNNER",
            "source_roots": [str(self.source_root.resolve())],
            "source_artifacts": [{"artifact_id": "source_input", "path": str(self.source.resolve())}],
            "workflow_ledger_path": str((self.root / "workflow_gate_ledger.jsonl").resolve()),
            "stages": [
                {
                    "stage_id": "local_stage",
                    "executor": "local",
                    "depends_on": [],
                    "inputs": ["source_input"],
                    "outputs": [{"artifact_id": "local_output", "path": "01_output/result.json"}],
                },
                {
                    "stage_id": "manual_stage",
                    "executor": "manual",
                    "depends_on": [],
                    "inputs": ["source_input"],
                    "outputs": [{"artifact_id": "manual_output", "path": "02_manual/result.json"}],
                },
                {
                    "stage_id": "worker_stage",
                    "executor": "worker",
                    "depends_on": [],
                    "worker_task": {
                        "objective": "Review only the declared synthetic input.",
                        "permitted_actions": ["Read declared input", "Write review JSON"],
                        "forbidden_actions": ["Modify source input", "Approve a Gate"],
                    },
                    "inputs": ["source_input"],
                    "outputs": [{
                        "artifact_id": "worker_output",
                        "path": "worker_staging/worker_stage/review.json",
                        "kind": "worker_staging",
                    }],
                },
            ],
        }
        self.plan_path.write_text(json.dumps(self.plan, indent=2) + "\n", encoding="utf-8")
        initialize_run(self.plan_path, self.run_root, "RUN_STAGE_RUNNER")
        self.output = self.run_root / "01_output" / "result.json"

    def tearDown(self):
        self.temp.cleanup()

    def _bindings(self):
        return {"local_stage": {"runtime_command": "validate-bundle"}}

    def test_dry_run_returns_exact_argv_without_mutating_run(self):
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=self._bindings()):
            report = execute_local_stage(
                self.manifest_path,
                "local_stage",
                ["--input", str(self.source), "--out", str(self.output)],
                dry_run=True,
            )
        self.assertEqual(report["status"], "DRY_RUN")
        self.assertEqual(report["command_argv"][-4:], ["--input", str(self.source), "--out", str(self.output)])
        self.assertEqual(verify_run(self.manifest_path)["event_count"], 1)

    def test_gated_cli_arguments_are_bound_to_this_run_automatically(self):
        with patch(
            "dor.stage_runner.stage_action_bindings_for_plan",
            return_value={"local_stage": {"runtime_command": "fit-baselines"}},
        ):
            report = execute_local_stage(
                self.manifest_path,
                "local_stage",
                ["--cohort-dir", "cohort", "--task", "task.json", "--out-dir", "model_output"],
                dry_run=True,
            )
        argv = report["command_argv"]
        self.assertEqual(argv[-4:], [
            "--workflow-ledger", str(self.root / "workflow_gate_ledger.jsonl"),
            "--run-manifest", str(self.manifest_path.resolve()),
        ])

    def test_success_executes_bound_cli_and_records_stage_automatically(self):
        def fake_run(command, cwd, check, timeout):
            self.assertEqual(command[1:4], ["-m", "dor.cli", "validate-bundle"])
            self.assertEqual(cwd, str(self.run_root.resolve()))
            self.assertFalse(check)
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text('{"status":"synthetic-success"}\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with (
            patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=self._bindings()),
            patch("dor.stage_runner.subprocess.run", side_effect=fake_run) as run,
        ):
            report = execute_local_stage(
                self.manifest_path,
                "local_stage",
                ["--input", str(self.source), "--out", str(self.output)],
            )
        self.assertEqual(report["status"], "SUCCEEDED")
        self.assertEqual(run.call_count, 1)
        state = next(item for item in build_resume_plan(self.manifest_path)["stages"] if item["stage_id"] == "local_stage")
        self.assertEqual(state["action"], "REUSE")
        self.assertEqual(state["status"], "SUCCEEDED")

    def test_failed_command_archives_partial_outputs_and_allows_retry(self):
        def fake_run(command, cwd, check, timeout):
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text('{"partial":true}\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 3)

        with (
            patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=self._bindings()),
            patch("dor.stage_runner.subprocess.run", side_effect=fake_run),
        ):
            report = execute_local_stage(
                self.manifest_path,
                "local_stage",
                ["--input", str(self.source), "--out", str(self.output)],
            )
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["return_code"], 3)
        self.assertFalse(self.output.exists())
        archived = Path(report["archived_after"][0]["archive_path"])
        self.assertTrue(archived.is_file())
        state = next(item for item in build_resume_plan(self.manifest_path)["stages"] if item["stage_id"] == "local_stage")
        self.assertEqual(state["action"], "RETRY_REQUIRED")

    def test_manual_and_worker_stages_cannot_be_run_by_local_executor(self):
        with self.assertRaisesRegex(ValueError, "manual executed"):
            execute_local_stage(self.manifest_path, "manual_stage", [])
        with self.assertRaisesRegex(ValueError, "worker executed"):
            execute_local_stage(self.manifest_path, "worker_stage", [])

    def test_advance_runs_local_stage_then_pauses_for_human_boundary(self):
        arguments_dir = self.run_root / "stage_arguments"
        arguments_dir.mkdir()
        args_file = arguments_dir / "local_stage.json"
        args_file.write_text(
            json.dumps(["--input", str(self.source), "--out", str(self.output)]),
            encoding="utf-8",
        )

        def fake_run(command, cwd, check, timeout):
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text('{"status":"synthetic-success"}\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with (
            patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=self._bindings()),
            patch("dor.stage_runner.subprocess.run", side_effect=fake_run),
        ):
            report = advance_run(self.manifest_path, arguments_dir)

        self.assertEqual(report["status"], "PAUSED_FOR_HUMAN")
        self.assertEqual(report["completed_local_stages"][0]["stage_id"], "local_stage")
        self.assertEqual(report["stage_id"], "manual_stage")
        self.assertTrue(self.output.is_file())
        self.assertEqual(verify_run(self.manifest_path)["valid_manifest_and_event_chain"], True)

    def test_advance_stops_for_missing_local_arguments_without_starting_stage(self):
        arguments_dir = self.run_root / "empty_stage_arguments"
        arguments_dir.mkdir()
        report = advance_run(self.manifest_path, arguments_dir)
        self.assertEqual(report["status"], "ARGUMENTS_REQUIRED")
        self.assertEqual(report["stage_id"], "local_stage")
        self.assertFalse(self.output.exists())
        self.assertEqual(verify_run(self.manifest_path)["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
