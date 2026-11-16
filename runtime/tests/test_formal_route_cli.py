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


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def empty_canonical_bundle() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "formal-route-cli-test",
        "mapping_version": "external-test-1",
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "comparisons": [],
        "evidence": [],
    }


class FormalRunPlanCliTests(unittest.TestCase):
    """Exercise both published Run Plans through real CLI stage transitions."""

    def run_cli(self, *arguments: str) -> str:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["dor", *arguments]), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = cli_main()
        self.assertEqual(
            exit_code,
            0,
            msg=(
                "CLI command failed: " + " ".join(arguments)
                + "\nstdout:\n" + stdout.getvalue()
                + "\nstderr:\n" + stderr.getvalue()
            ),
        )
        return stdout.getvalue()

    def _create_package(self, package_root: Path, route: str) -> Path:
        source_path = package_root / "sources" / "opaque_original.bin"
        source_path.parent.mkdir(parents=True)
        # Synthetic opaque provenance asset: the workflow hashes it but never parses it.
        source_path.write_bytes(b"synthetic opaque provenance bytes")

        dataset_path = package_root / "tables" / "records.csv"
        dataset_path.parent.mkdir(parents=True)
        with dataset_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["record_id", "study_key", "value", "unit"])
            writer.writerows([
                ["R1", "STUDY_A", "1.25", "a.u."],
                ["R2", "STUDY_B", "2.50", "a.u."],
            ])

        artifacts = [{
            "artifact_id": "synthetic-dataset",
            "role": "standardized_dataset",
            "path": "tables/records.csv",
            "sha256": digest(dataset_path),
            "format": "csv",
        }]
        if route == "CANONICAL_BUNDLE":
            role_payloads = (
                ("source_inventory", {
                    "schema_version": "1.0",
                    "items": [{
                        "inventory_id": "SYNTHETIC_OPAQUE_SOURCE",
                        "source_file": "sources/opaque_original.bin",
                        "source_sha256": digest(source_path),
                        "source_format": "binary",
                        "locator_type": "file",
                        "locator": "Opaque source file; metadata and hash only",
                        "mapping_status": "NOT_MAPPED",
                    }],
                }),
                ("mapping_plan", {"schema_version": "1.0", "mapping_version": "synthetic-1", "rules": []}),
                ("build_spec", {"schema_version": "1.0"}),
                ("canonical_bundle", empty_canonical_bundle()),
            )
            for role, payload in role_payloads:
                path = package_root / f"{role}.json"
                write_json(path, payload)
                artifacts.append({
                    "artifact_id": f"synthetic-{role}",
                    "role": role,
                    "path": path.relative_to(package_root).as_posix(),
                    "sha256": digest(path),
                    "format": "json",
                })

        manifest = {
            "schema_version": "1.0",
            "package_id": f"package.formal-{route.lower()}",
            "adapter": {"adapter_id": "test.formal-adapter", "adapter_version": "1.0"},
            "sources": [{
                "source_id": "synthetic-original",
                "path": "sources/opaque_original.bin",
                "sha256": digest(source_path),
                "format": "binary",
            }],
            "artifacts": artifacts,
        }
        manifest_path = package_root / "adapter_manifest.json"
        write_json(manifest_path, manifest)
        return manifest_path

    def _configured_plan(self, relative_path: str, root: Path, package_root: Path,
                         config_root: Path, manifest_path: Path) -> Path:
        plan = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        plan["source_roots"] = [str(package_root.resolve()), str(config_root.resolve())]
        plan["workflow_ledger_path"] = str((root / "workflow_gate_ledger.jsonl").resolve())
        source_paths = {
            "adapter_package_manifest": manifest_path,
            "virtual_query_input": config_root / "virtual_reproduction_query.json",
            "publication_plan": config_root / "publication_package_plan.json",
        }
        for artifact in plan["source_artifacts"]:
            artifact["path"] = str(source_paths[artifact["artifact_id"]].resolve())
        plan_path = root / "configured_run_plan.json"
        write_json(plan_path, plan)
        return plan_path

    def _record(
        self, manifest: Path, stage_id: str, status: str,
        command: str | None = None, producer_kind: str = "local",
    ) -> None:
        arguments = [
            "run-stage-record", "--manifest", str(manifest),
            "--stage", stage_id, "--status", status,
            "--producer-kind", producer_kind,
        ]
        if command:
            arguments.extend(["--command", command])
        self.run_cli(*arguments)

    def test_both_formal_routes_execute_through_g0_review_gate_boundary(self):
        routes = (
            (
                "STRUCTURED_DATASET",
                "templates/run_plan.example.json",
                "source_audit",
            ),
            (
                "CANONICAL_BUNDLE",
                "templates/run_plan.canonical_adapter.example.json",
                "adapter_artifact_materialization",
            ),
        )
        for index, (route, template, second_stage) in enumerate(routes):
            with self.subTest(route=route):
                with tempfile.TemporaryDirectory(prefix=f"dor-formal-{route.lower()}-") as temporary:
                    root = Path(temporary)
                    package_root = root / "adapter_package"
                    config_root = root / "configuration"
                    package_root.mkdir()
                    config_root.mkdir()
                    manifest_path = self._create_package(package_root, route)
                    write_json(config_root / "virtual_reproduction_query.json", {"schema_version": "1.0"})
                    write_json(config_root / "publication_package_plan.json", {"schema_version": "1.0"})
                    plan_path = self._configured_plan(
                        template, root, package_root, config_root, manifest_path,
                    )
                    run_root = root / "runs" / f"RUN_FORMAL_{index}"
                    manifest = run_root / "run_manifest.json"

                    preflight = json.loads(self.run_cli(
                        "validate-execution-contract", "--plan", str(plan_path),
                    ))
                    self.assertTrue(preflight["valid"])
                    self.assertEqual(preflight["route"], route)

                    self.run_cli(
                        "run-init", "--plan", str(plan_path),
                        "--run-root", str(run_root), "--run-id", f"RUN_FORMAL_{index}",
                    )
                    initial = json.loads(self.run_cli(
                        "run-resume-plan", "--manifest", str(manifest),
                    ))
                    self.assertEqual(initial["next_actions"][0]["stage_id"], "adapter_package_validation")
                    self.assertEqual(
                        initial["next_actions"][0]["action_binding"]["route"], route,
                    )

                    # Stage 1: validate the external package and create a Run-bound handoff.
                    self._record(manifest, "adapter_package_validation", "RUNNING",
                                 "dor prepare-adapter-handoff")
                    handoff = run_root / "00_adapter" / "adapter_handoff.json"
                    prepare_args = [
                        "prepare-adapter-handoff",
                        "--manifest", str(manifest_path),
                        "--package-root", str(package_root),
                        "--out", str(handoff),
                    ]
                    if route == "CANONICAL_BUNDLE":
                        prepare_args.extend([
                            "--dataset-manifest-out",
                            str(run_root / "00_adapter" / "dataset_manifest.json"),
                        ])
                    handoff_report = json.loads(self.run_cli(*prepare_args))
                    self.assertTrue(handoff_report["valid"])
                    self.assertEqual(handoff_report["route"], route)
                    self._record(manifest, "adapter_package_validation", "SUCCEEDED")

                    after_handoff = json.loads(self.run_cli(
                        "run-resume-plan", "--manifest", str(manifest),
                    ))
                    self.assertEqual(after_handoff["next_actions"][0]["stage_id"], second_stage)

                    # Stage 2: run the actual route-specific CLI operation and record its outputs.
                    self._record(manifest, second_stage, "RUNNING")
                    if route == "STRUCTURED_DATASET":
                        self.run_cli(
                            "audit", "--adapter-handoff", str(handoff),
                            "--out", str(run_root / "01_audit"),
                        )
                    else:
                        self.run_cli(
                            "materialize-adapter-artifacts",
                            "--adapter-handoff", str(handoff),
                            "--role", "source_inventory",
                            "--role", "mapping_plan",
                            "--role", "build_spec",
                            "--role", "canonical_bundle",
                            "--out-dir", str(run_root / "00_adapter" / "materialized"),
                        )
                    self._record(manifest, second_stage, "SUCCEEDED")

                    verification = json.loads(self.run_cli(
                        "run-verify", "--manifest", str(manifest),
                    ))
                    self.assertTrue(verification["valid_manifest_and_event_chain"])
                    self.assertEqual(verification["source_integrity"], "CURRENT")

                    resume = json.loads(self.run_cli(
                        "run-resume-plan", "--manifest", str(manifest),
                    ))
                    self.assertEqual(resume["next_actions"][0]["stage_id"], "g0_review_packet")
                    self.assertEqual(resume["next_actions"][0]["action"], "READY_TO_RUN")
                    self._record(
                        manifest, "g0_review_packet", "RUNNING", producer_kind="manual",
                    )

                    if route == "STRUCTURED_DATASET":
                        g0_dir = run_root / "01_audit"
                        input_paths = [
                            ("dataset_manifest", g0_dir / "dataset_manifest.json"),
                            ("source_inventory", g0_dir / "source_inventory.json"),
                            ("data_audit_report", g0_dir / "data_audit_report.md"),
                            ("mapping_review_queue", g0_dir / "mapping_review_queue.csv"),
                            ("adapter_handoff", handoff),
                        ]
                    else:
                        g0_dir = run_root / "01_review"
                        materialized_dir = run_root / "00_adapter" / "materialized"
                        input_paths = [
                            ("dataset_manifest", run_root / "00_adapter" / "dataset_manifest.json"),
                            ("source_inventory", materialized_dir / "source_inventory.json"),
                            ("adapter_handoff", handoff),
                            ("materialization_manifest", materialized_dir / "materialization_manifest.json"),
                        ]

                    packet_path = g0_dir / "g0_review_packet.json"
                    validation_path = g0_dir / "g0_review_packet_validation.json"
                    artifact_bindings = [
                        {
                            "artifact_id": artifact_id,
                            "path": str(path.resolve()),
                            "sha256": digest(path),
                        }
                        for artifact_id, path in input_paths
                    ]
                    packet = {
                        "schema_version": "1.0",
                        "run_id": f"RUN_FORMAL_{index}",
                        "project_id": json.loads(manifest.read_text(encoding="utf-8"))["project_id"],
                        "stage_id": "g0_review_packet",
                        "prepared_at": "2026-11-15T12:00:00+08:00",
                        "packet_status": "AWAITING_HUMAN_REVIEW",
                        "artifact_bindings": artifact_bindings,
                        "review_items": [{
                            "item_id": "review_all_exact_inputs",
                            "question": "Have all exact Run-bound inputs and limitations been reviewed?",
                            "artifact_ids": [item["artifact_id"] for item in artifact_bindings],
                            "mandatory": True,
                        }],
                        "unresolved_questions": [],
                    }
                    write_json(packet_path, packet)
                    validation = json.loads(self.run_cli(
                        "validate-run-review-packet",
                        "--packet", str(packet_path),
                        "--manifest", str(manifest),
                        "--out", str(validation_path),
                    ))
                    self.assertTrue(validation["valid"], validation.get("errors"))
                    self.assertEqual(validation["checked_artifact_count"], len(input_paths))
                    self._record(
                        manifest, "g0_review_packet", "SUCCEEDED", producer_kind="manual",
                    )

                    verification = json.loads(self.run_cli(
                        "run-verify", "--manifest", str(manifest),
                    ))
                    self.assertTrue(verification["valid_manifest_and_event_chain"])
                    self.assertEqual(verification["source_integrity"], "CURRENT")

                    # The next scientific stage is correctly blocked on an actual human G0 decision.
                    resume = json.loads(self.run_cli(
                        "run-resume-plan", "--manifest", str(manifest),
                    ))
                    g0_state = next(stage for stage in resume["stages"] if stage["stage_id"] == "g0_review_packet")
                    next_mapping = next(stage for stage in resume["stages"] if stage["stage_id"] == (
                        "mapping_preparation" if route == "STRUCTURED_DATASET" else "mapping_validation"
                    ))
                    self.assertEqual(g0_state["action"], "REUSE")
                    self.assertEqual(next_mapping["action"], "BLOCKED_GATE")
                    self.assertEqual(next_mapping["required_gate"], "G0")
                    self.assertEqual(resume["next_actions"], [])

                    artifact_manifest_path = run_root / "artifact_manifest.json"
                    artifact_manifest = json.loads(self.run_cli(
                        "run-artifacts", "--manifest", str(manifest),
                        "--out", str(artifact_manifest_path),
                    ))
                    statuses = {
                        item["artifact_id"]: item["status"]
                        for item in artifact_manifest["artifacts"]
                    }
                    self.assertEqual(statuses["adapter_handoff"], "CURRENT")
                    if route == "STRUCTURED_DATASET":
                        self.assertEqual(statuses["source_inventory"], "CURRENT")
                        self.assertEqual(statuses["data_audit_report"], "CURRENT")
                    else:
                        self.assertEqual(statuses["source_inventory"], "CURRENT")
                        self.assertEqual(statuses["canonical_bundle"], "CURRENT")

                    # The test stops before user approval. Runtime execution never creates a Gate decision.
                    self.assertFalse((root / "workflow_gate_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
