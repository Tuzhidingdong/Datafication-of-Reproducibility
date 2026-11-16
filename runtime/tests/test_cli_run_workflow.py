from __future__ import annotations

import contextlib
import csv
import hashlib
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
    """Exercise Adapter Package -> audit -> manual review through the real CLI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dor-cli-workflow-")
        self.root = Path(self.temp.name)
        self.package_root = self.root / "adapter_package"
        self.package_root.mkdir()
        self.run_root = self.root / "runs" / "RUN_CLI_WORKFLOW"
        self.plan_path = self.root / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"

        self.snapshot_path = self.package_root / "sources" / "upstream_snapshot.bin"
        self.snapshot_path.parent.mkdir(parents=True)
        self.snapshot_path.write_bytes(b"synthetic upstream snapshot; opaque to this workflow test")

        self.csv_path = self.package_root / "tables" / "records.csv"
        self.csv_path.parent.mkdir(parents=True)
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["record_id", "study_key", "value", "unit"])
            writer.writerows([
                ["R1", "STUDY_A", "1.25", "a.u."],
                ["R2", "STUDY_B", "2.50", "a.u."],
            ])

        self.json_path = self.package_root / "records" / "conditions.json"
        self.json_path.parent.mkdir(parents=True)
        self.json_path.write_text(json.dumps({
            "records": [
                {"record_id": "R1", "condition": {"temperature": 298, "unit": "K"}},
                {"record_id": "R2", "condition": {"temperature": 303, "unit": "K"}},
            ]
        }, indent=2) + "\n", encoding="utf-8")

        self.adapter_manifest_path = self.package_root / "adapter_manifest.json"
        adapter_manifest = {
            "schema_version": "1.0",
            "package_id": "package.synthetic.cli-workflow",
            "adapter": {
                "adapter_id": "test.synthetic-adapter",
                "adapter_version": "1.0",
            },
            "sources": [{
                "source_id": "upstream-snapshot",
                "path": "sources/upstream_snapshot.bin",
                "sha256": sha256_file(self.snapshot_path),
                "format": "binary",
            }],
            "artifacts": [
                {
                    "artifact_id": "synthetic-records-csv",
                    "role": "standardized_dataset",
                    "path": "tables/records.csv",
                    "sha256": sha256_file(self.csv_path),
                    "format": "csv",
                },
                {
                    "artifact_id": "synthetic-records-json",
                    "role": "standardized_dataset",
                    "path": "records/conditions.json",
                    "sha256": sha256_file(self.json_path),
                    "format": "json",
                },
            ],
        }
        self.adapter_manifest_path.write_text(
            json.dumps(adapter_manifest, indent=2) + "\n", encoding="utf-8"
        )

        self.plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_SYNTHETIC_CLI_WORKFLOW",
            "source_roots": [str(self.package_root.resolve())],
            "source_artifacts": [{
                "artifact_id": "adapter_package_manifest",
                "path": str(self.adapter_manifest_path.resolve()),
            }],
            "stages": [
                {
                    "stage_id": "adapter_package_validation",
                    "executor": "local",
                    "depends_on": [],
                    "inputs": ["adapter_package_manifest"],
                    "outputs": [{
                        "artifact_id": "adapter_handoff",
                        "path": "00_adapter/adapter_handoff.json",
                    }],
                },
                {
                    "stage_id": "structured_dataset_audit",
                    "executor": "local",
                    "depends_on": ["adapter_package_validation"],
                    "inputs": ["adapter_handoff"],
                    "outputs": [
                        {"artifact_id": "dataset_manifest", "path": "01_audit/dataset_manifest.json"},
                        {"artifact_id": "source_inventory", "path": "01_audit/source_inventory.json"},
                        {"artifact_id": "data_audit_report", "path": "01_audit/data_audit_report.md"},
                        {"artifact_id": "column_coverage", "path": "01_audit/column_coverage.csv"},
                        {"artifact_id": "json_structure_paths", "path": "01_audit/json_structure_paths.csv"},
                        {"artifact_id": "mapping_review_queue", "path": "01_audit/mapping_review_queue.csv"},
                    ],
                },
                {
                    "stage_id": "g0_review_packet",
                    "executor": "manual",
                    "depends_on": ["adapter_package_validation", "structured_dataset_audit"],
                    "inputs": [
                        "dataset_manifest",
                        "source_inventory",
                        "data_audit_report",
                        "mapping_review_queue",
                        "adapter_handoff",
                    ],
                    "outputs": [
                        {"artifact_id": "g0_review_packet", "path": "01_audit/g0_review_packet.json"},
                        {"artifact_id": "g0_review_packet_validation", "path": "01_audit/g0_review_packet_validation.json"},
                    ],
                },
            ],
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

    def test_structured_adapter_entry_and_manual_review_execute_through_cli(self):
        self.run_cli(
            "run-init",
            "--plan", str(self.plan_path),
            "--run-root", str(self.run_root),
            "--run-id", "RUN_CLI_WORKFLOW",
        )
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_id"], "RUN_CLI_WORKFLOW")

        # Stage 1: validate the declared adapter package and create the hash-bound handoff.
        initial = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        self.assertEqual(initial["stages"][0]["action"], "READY_TO_RUN")
        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "adapter_package_validation",
            "--status", "RUNNING", "--producer-kind", "local",
            "--command", "dor prepare-adapter-handoff",
        )
        handoff_path = self.run_root / "00_adapter" / "adapter_handoff.json"
        self.run_cli(
            "prepare-adapter-handoff",
            "--manifest", str(self.adapter_manifest_path),
            "--package-root", str(self.package_root),
            "--out", str(handoff_path),
        )
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        self.assertTrue(handoff["valid"])
        self.assertEqual(handoff["route"], "STRUCTURED_DATASET")
        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "adapter_package_validation",
            "--status", "SUCCEEDED", "--producer-kind", "local",
        )

        # Stage 2: execute the normal adapter-handoff audit and record all outputs.
        resume = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        actions = {item["stage_id"]: item["action"] for item in resume["stages"]}
        self.assertEqual(actions["adapter_package_validation"], "REUSE")
        self.assertEqual(actions["structured_dataset_audit"], "READY_TO_RUN")
        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "structured_dataset_audit",
            "--status", "RUNNING", "--producer-kind", "local",
            "--command", "dor audit --adapter-handoff",
        )
        audit_dir = self.run_root / "01_audit"
        self.run_cli(
            "audit", "--adapter-handoff", str(handoff_path),
            "--out", str(audit_dir),
        )
        dataset_manifest = json.loads(
            (audit_dir / "dataset_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(dataset_manifest["audit_scope"], "READ_ONLY_STRUCTURAL_INSPECTION")
        self.assertEqual(len(dataset_manifest["sources"]), 2)
        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "structured_dataset_audit",
            "--status", "SUCCEEDED", "--producer-kind", "local",
        )

        # Stage 3: build and validate a real Run-bound human review packet.
        resume = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        actions = {item["stage_id"]: item["action"] for item in resume["stages"]}
        self.assertEqual(actions["g0_review_packet"], "READY_TO_RUN")
        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "g0_review_packet",
            "--status", "RUNNING", "--producer-kind", "manual",
        )

        packet_path = self.run_root / "01_audit" / "g0_review_packet.json"
        report_path = self.run_root / "01_audit" / "g0_review_packet_validation.json"
        bindings = []
        for artifact_id, path in [
            ("dataset_manifest", audit_dir / "dataset_manifest.json"),
            ("source_inventory", audit_dir / "source_inventory.json"),
            ("data_audit_report", audit_dir / "data_audit_report.md"),
            ("mapping_review_queue", audit_dir / "mapping_review_queue.csv"),
            ("adapter_handoff", handoff_path),
        ]:
            bindings.append({
                "artifact_id": artifact_id,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            })
        packet_path.write_text(json.dumps({
            "schema_version": "1.0",
            "run_id": manifest["run_id"],
            "project_id": manifest["project_id"],
            "stage_id": "g0_review_packet",
            "prepared_at": "2026-11-15T12:00:00+08:00",
            "packet_status": "AWAITING_HUMAN_REVIEW",
            "artifact_bindings": bindings,
            "review_items": [{
                "item_id": "review_all_exact_inputs",
                "question": "Have the exact declared inputs and unresolved issues been reviewed?",
                "artifact_ids": [item["artifact_id"] for item in bindings],
                "mandatory": True,
            }],
            "unresolved_questions": [],
        }, indent=2) + "\n", encoding="utf-8")

        validation_stdout = self.run_cli(
            "validate-run-review-packet",
            "--packet", str(packet_path),
            "--manifest", str(self.manifest_path),
            "--out", str(report_path),
        )
        validation = json.loads(validation_stdout)
        self.assertTrue(validation["valid"], validation.get("errors"))
        self.assertEqual(validation["checked_artifact_count"], len(bindings))

        self.run_cli(
            "run-stage-record", "--manifest", str(self.manifest_path),
            "--stage", "g0_review_packet",
            "--status", "SUCCEEDED", "--producer-kind", "manual",
        )
        verified = json.loads(self.run_cli(
            "run-verify", "--manifest", str(self.manifest_path)
        ))
        self.assertTrue(verified["valid_manifest_and_event_chain"])
        self.assertEqual(verified["source_integrity"], "CURRENT")

        artifact_manifest_path = self.root / "artifact_manifest.json"
        self.run_cli(
            "run-artifacts", "--manifest", str(self.manifest_path),
            "--out", str(artifact_manifest_path),
        )
        artifact_manifest = json.loads(
            artifact_manifest_path.read_text(encoding="utf-8")
        )
        artifact_states = {
            item["artifact_id"]: item["status"]
            for item in artifact_manifest["artifacts"]
        }
        for artifact_id in (
            "adapter_handoff", "dataset_manifest", "source_inventory",
            "g0_review_packet", "g0_review_packet_validation",
        ):
            self.assertEqual(artifact_states[artifact_id], "CURRENT")

        resumed = json.loads(self.run_cli(
            "run-resume-plan", "--manifest", str(self.manifest_path)
        ))
        self.assertTrue(all(
            item["action"] == "REUSE" for item in resumed["stages"]
        ))
        event_lines = (self.run_root / "run_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        events = [json.loads(line) for line in event_lines]
        for stage_id in (
            "adapter_package_validation", "structured_dataset_audit", "g0_review_packet"
        ):
            statuses = [
                event["status"] for event in events
                if event.get("stage_id") == stage_id
            ]
            self.assertEqual(statuses, ["RUNNING", "SUCCEEDED"])

        # This test exercises packet validation only; it deliberately does not
        # create a G0-G4 decision or claim scientific approval.
        self.assertFalse((self.run_root / "workflow_gate_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
