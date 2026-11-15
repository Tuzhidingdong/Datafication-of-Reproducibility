from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.cli import main as cli_main
from dor.mapping import sha256_file


class CliRunWorkflowTests(unittest.TestCase):
    """Exercise a real CLI Run -> manual review -> artifact/resume lifecycle."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dor-cli-workflow-")
        self.root = Path(self.temp.name)
        self.source_root = self.root / "project_sources"
        self.source_root.mkdir()
        self.run_root = self.root / "runs" / "RUN_CLI_WORKFLOW"
        self.plan_path = self.root / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"

        source_payloads = {
            "dataset_manifest.json": {"schema_version": "1.0", "synthetic": True},
            "source_inventory.json": {"schema_version": "1.0", "items": []},
            "data_audit_report.md": "# Synthetic audit\n",
            "mapping_review_queue.csv": "inventory_id,mapping_status\n",
            "adapter_handoff.json": {"schema_version": "1.0", "valid": True},
        }
        self.source_artifacts = []
        for name, payload in source_payloads.items():
            path = self.source_root / name
            if name.endswith(".json"):
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            else:
                path.write_text(payload, encoding="utf-8")
            artifact_id = Path(name).stem
            self.source_artifacts.append({
                "artifact_id": artifact_id,
                "path": str(path.resolve()),
            })

        self.plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_SYNTHETIC_CLI_WORKFLOW",
            "source_roots": [str(self.source_root.resolve())],
            "source_artifacts": self.source_artifacts,
            "stages": [{
                "stage_id": "g0_review_packet",
                "executor": "manual",
                "depends_on": [],
                "inputs": [item["artifact_id"] for item in self.source_artifacts],
                "outputs": [
                    {
                        "artifact_id": "g0_review_packet",
                        "path": "01_audit/g0_review_packet.json",
                    },
                    {
                        "artifact_id": "g0_review_packet_validation",
                        "path": "01_audit/g0_review_packet_validation.json",
                    },
                ],
            }],
        }
        self.plan_path.write_text(
            json.dumps(self.plan, indent=2) + "\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["dor", *arguments]), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = cli_main()
        self.assertEqual(
            exit_code, 0,
            msg=(
                "CLI command failed: " + " ".join(arguments)
                + "\nstdout:\n" + stdout.getvalue()
                + "\nstderr:\n" + stderr.getvalue()
            ),
        )
        return stdout.getvalue()

    def test_run_stage_and_review_packet_execute_through_cli(self):
        # Initialize a separate Run workspace from immutable synthetic inputs.
        self.run_cli(
            "run-init",
            "--plan", str(self.plan_path),
            "--run-root", str(self.run_root),
            "--run-id", "RUN_CLI_WORKFLOW",
        )
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_id"], "RUN_CLI_WORKFLOW")

        # Before the manual action, the Run Manager exposes it as ready.
        initial = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        self.assertEqual(initial["stages"][0]["action"], "READY_TO_RUN")

        # Record RUNNING before creating/validating the human review packet.
        self.run_cli(
            "run-stage-record",
            "--manifest", str(self.manifest_path),
            "--stage", "g0_review_packet",
            "--status", "RUNNING",
            "--producer-kind", "manual",
        )

        packet_path = self.run_root / "01_audit" / "g0_review_packet.json"
        report_path = self.run_root / "01_audit" / "g0_review_packet_validation.json"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        bindings = [
            {
                "artifact_id": item["artifact_id"],
                "path": item["path"],
                "sha256": sha256_file(Path(item["path"])),
            }
            for item in self.source_artifacts
        ]
        packet = {
            "schema_version": "1.0",
            "run_id": manifest["run_id"],
            "project_id": manifest["project_id"],
            "stage_id": "g0_review_packet",
            "prepared_at": "2026-11-15T12:00:00+08:00",
            "packet_status": "AWAITING_HUMAN_REVIEW",
            "artifact_bindings": bindings,
            "review_items": [{
                "item_id": "review_all_inputs",
                "question": "Have the exact declared inputs and unresolved issues been reviewed?",
                "artifact_ids": [item["artifact_id"] for item in bindings],
                "mandatory": True,
            }],
            "unresolved_questions": [],
        }
        packet_path.write_text(
            json.dumps(packet, indent=2) + "\n", encoding="utf-8"
        )

        # Invoke the production validator; do not fabricate a valid report.
        validation_stdout = self.run_cli(
            "validate-run-review-packet",
            "--packet", str(packet_path),
            "--manifest", str(self.manifest_path),
            "--out", str(report_path),
        )
        validation = json.loads(validation_stdout)
        self.assertTrue(validation["valid"], validation.get("errors"))
        self.assertEqual(validation["stage_id"], "g0_review_packet")
        self.assertEqual(
            validation["checked_artifact_count"], len(self.source_artifacts)
        )
        self.assertTrue(report_path.is_file())

        # A validated packet is still not a scientific approval. Only stage
        # execution is completed here; no G0-G4 ledger is created or approved.
        self.run_cli(
            "run-stage-record",
            "--manifest", str(self.manifest_path),
            "--stage", "g0_review_packet",
            "--status", "SUCCEEDED",
            "--producer-kind", "manual",
        )
        verified = json.loads(self.run_cli(
            "run-verify", "--manifest", str(self.manifest_path)
        ))
        self.assertTrue(verified["valid_manifest_and_event_chain"])
        self.assertEqual(verified["source_integrity"], "CURRENT")

        resumed = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        self.assertEqual(resumed["stages"][0]["action"], "REUSE")
        event_lines = (self.run_root / "run_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        events = [json.loads(line) for line in event_lines]
        stage_statuses = [
            event["status"] for event in events
            if event.get("stage_id") == "g0_review_packet"
        ]
        self.assertEqual(stage_statuses, ["RUNNING", "SUCCEEDED"])
        self.assertFalse((self.run_root / "workflow_gate_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
