"""Phase A: real CLI -> Stage Runner -> Run Manifest wiring for Virtual Query.

All artifacts are synthetic and live under a controlled temp root. The CLI is
invoked as a real child process; the materialization stage is executed by the
real Stage Runner (execute_local_stage / advance_run). No helper is called as a
substitute for the CLI, and no SUCCEEDED event is hand-written for the stage
under test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.execution_contract import stage_action_bindings_for_plan
from dor.mapping import sha256_file
from dor.run_manager import (
    _artifact_definitions, _artifact_path, _manifest_context, build_artifact_manifest,
    build_resume_plan, initialize_run, record_stage_status,
)
from dor.stage_runner import _runtime_environment, advance_run, execute_local_stage
from dor.virtual_query_state import (
    resolve_virtual_query_state, QUERY_REVIEW_READY, NOT_APPLICABLE,
)

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "src" / "dor" / "stage_execution_contract.json").read_text(encoding="utf-8")
)


def _w(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _controlled_temp_dir(prefix: str) -> tempfile.TemporaryDirectory:
    """Keep synthetic artifacts under the project-controlled temp root when set."""
    root = os.environ.get("DOR_TEST_TEMP_ROOT")
    if root and Path(root).is_dir():
        return tempfile.TemporaryDirectory(prefix=prefix, dir=root)
    return tempfile.TemporaryDirectory(prefix=prefix)


def _real_materialization_binding() -> dict:
    """The genuine contract binding for the materialization stage (no invention)."""
    binding = next(s for s in CONTRACT["stages"] if s["stage_id"] == "virtual_query_materialization")
    variant = next(v for v in binding["route_variants"] if v["route"] == "STRUCTURED_DATASET")
    return {
        "virtual_query_materialization": {
            "runtime_command": binding["cli_command"],
            "argv_template": variant["argv_template"],
            "executor": variant["executor"],
        }
    }


class VQCliManifestWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _controlled_temp_dir("dor-vq-cli-manifest-")
        self.root = Path(self.tmp.name)
        self.source_root = self.root / "sources"
        self.source_root.mkdir()
        self.adapter = self.source_root / "adapter.json"
        _w(self.adapter, {"adapter": "synthetic"})
        self.run_root = self.root / "run"
        self.plan_path = self.root / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"
        self.prepared: list[tuple[str, Path]] = []  # (artifact_id, path) produced by real CLI

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- fixture ----------
    def _plan(self, decision_value: str):
        return {
            "schema_version": "1.0",
            "project_id": "P_VQ_CLI",
            "execution_profile": "FULL_ANALYSIS",
            "source_roots": [str(self.source_root.resolve())],
            "source_artifacts": [{"artifact_id": "adapter_package_manifest", "path": str(self.adapter.resolve())}],
            "stages": [
                {"stage_id": "modeling_setup", "executor": "manual", "depends_on": [],
                 "inputs": ["adapter_package_manifest"],
                 "outputs": [
                     {"artifact_id": "modeling_task", "path": "05_scope/modeling_task.json"},
                     {"artifact_id": "research_scope_record", "path": "05_scope/research_scope_record.json"},
                 ]},
                {"stage_id": "virtual_query_preparation", "executor": "manual", "depends_on": ["modeling_setup"],
                 "inputs": ["modeling_task", "research_scope_record"],
                 "outputs": [{"artifact_id": "virtual_query_decision", "path": "08_virtual_reproduction/virtual_query_decision.json"}]},
                {"stage_id": "virtual_query_materialization", "executor": "local", "depends_on": ["virtual_query_preparation", "modeling_setup"],
                 "inputs": ["modeling_task", "virtual_query_decision"],
                 "activation": {"artifact_id": "virtual_query_decision", "json_pointer": "/decision",
                                "operator": "equals", "value": "RUN_PREDICTION"},
                 "outputs": [
                     {"artifact_id": "virtual_query_input", "path": "08_virtual_reproduction/virtual_query_input.json", "kind": "derived"},
                     {"artifact_id": "virtual_query_validation", "path": "08_virtual_reproduction/virtual_query_validation.json", "kind": "derived"},
                 ]},
            ],
        }

    def _task(self):
        return {
            "schema_version": "1.0", "task_id": "TASK_CLI", "target_id": "TARGET_CLI",
            "endpoint_definition": "endpoint_cli", "modeling_strategy": "regression",
            "feature_bindings": [
                {"feature_id": "f1", "value_type": "NUMERIC", "expected_unit": "mol"},
                {"feature_id": "f2", "value_type": "NUMERIC", "expected_unit": "K"},
            ],
        }

    def _setup_run(self, decision_value: str, *, source_query_unit_ok=True):
        plan = self._plan(decision_value)
        _w(self.plan_path, plan)
        initialize_run(self.plan_path, self.run_root, "RUN_VQ_CLI")
        # Upstream setup (fixture, not the stage under test).
        record_stage_status(self.manifest_path, "modeling_setup", "RUNNING", "manual")
        task = self._task()
        _w(self.run_root / "05_scope/modeling_task.json", task)
        _w(self.run_root / "05_scope/research_scope_record.json", {"scope": "synthetic"})
        record_stage_status(self.manifest_path, "modeling_setup", "SUCCEEDED", "manual")

        task_path = self.run_root / "05_scope/modeling_task.json"
        query = {
            "schema_version": "1.0", "task_id": "TASK_CLI", "target_id": "TARGET_CLI",
            "endpoint_definition": "endpoint_cli",
            "features": {
                "f1": {"value": 1.0, "unit": "mol" if source_query_unit_ok else "WRONG"},
                "f2": {"value": 300.0, "unit": "K"},
            },
        }
        q_path = self.run_root / "08_virtual_reproduction/source_query.json"
        _w(q_path, query)
        decision = {
            "schema_version": "1.0", "decision": decision_value,
            "reason": "Synthetic decision for CLI wiring test.",
            "task_id": "TASK_CLI", "target_id": "TARGET_CLI", "endpoint_definition": "endpoint_cli",
            "modeling_task_sha256": sha256_file(task_path),
            "reviewer": "synthetic", "decided_at": "2026-11-17T00:00:00Z",
        }
        if decision_value == "RUN_PREDICTION":
            decision["source_query_path"] = str(q_path.resolve())
        record_stage_status(self.manifest_path, "virtual_query_preparation", "RUNNING", "manual")
        _w(self.run_root / "08_virtual_reproduction/virtual_query_decision.json", decision)
        record_stage_status(self.manifest_path, "virtual_query_preparation", "SUCCEEDED", "manual")
        return plan, task, q_path

    def _defs(self):
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        return _artifact_definitions(plan)

    # A2: real CLI child process
    def test_cli_run_prediction_produces_query_and_validation(self):
        self._setup_run("RUN_PREDICTION")
        defs, _ = self._defs()
        out = _artifact_path(self.run_root, defs["virtual_query_input"])
        report = _artifact_path(self.run_root, defs["virtual_query_validation"])
        cmd = [
            sys.executable, "-m", "dor.cli", "prepare-virtual-query",
            "--task", str(self.run_root / "05_scope/modeling_task.json"),
            "--decision", str(self.run_root / "08_virtual_reproduction/virtual_query_decision.json"),
            "--out", str(out), "--report", str(report),
        ]
        env = _runtime_environment()
        proc = subprocess.run(cmd, cwd=str(self.run_root), env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.is_file() and report.is_file())
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "validated")
        self.assertTrue(payload["valid"])
        query = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(query["schema_version"], "1.0")
        self.assertEqual(query["features"]["f1"]["value"], 1.0)
        self.assertEqual(query["features"]["f1"]["unit"], "mol")
        validation = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(validation["contract"], "VIRTUAL_QUERY_PREPARATION")
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["prepared_query_sha256"], sha256_file(out))
        # record evidence for the report
        for aid, p in (("virtual_query_input", out), ("virtual_query_validation", report)):
            self.prepared.append((aid, p))
        self._evidence = {
            "query": {"path": str(out), "size": out.stat().st_size, "sha256": sha256_file(out)},
            "validation": {"path": str(report), "size": report.stat().st_size, "sha256": sha256_file(report)},
        }
        # assert evidence available for subsequent manual inspection
        self.assertEqual(self._evidence["query"]["sha256"], validation["prepared_query_sha256"])

    def test_cli_na_decision_refuses_materialization(self):
        self._setup_run("NOT_APPLICABLE")
        defs, _ = self._defs()
        out = _artifact_path(self.run_root, defs["virtual_query_input"])
        report = _artifact_path(self.run_root, defs["virtual_query_validation"])
        cmd = [
            sys.executable, "-m", "dor.cli", "prepare-virtual-query",
            "--task", str(self.run_root / "05_scope/modeling_task.json"),
            "--decision", str(self.run_root / "08_virtual_reproduction/virtual_query_decision.json"),
            "--out", str(out), "--report", str(report),
        ]
        proc = subprocess.run(cmd, cwd=str(self.run_root), env=_runtime_environment(), capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN_PREDICTION", proc.stderr)
        self.assertFalse(out.exists())
        self.assertFalse(report.exists())

    # A3: real Stage Runner registers CLI-produced outputs
    def test_stage_runner_registers_cli_outputs_and_manifest_matches(self):
        self._setup_run("RUN_PREDICTION")
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=_real_materialization_binding()):
            result = execute_local_stage(self.manifest_path, "virtual_query_materialization")
        self.assertEqual(result["status"], "SUCCEEDED", result)
        self.assertEqual(result["return_code"], 0)
        defs, _ = self._defs()
        out = _artifact_path(self.run_root, defs["virtual_query_input"])
        report = _artifact_path(self.run_root, defs["virtual_query_validation"])
        self.assertTrue(out.is_file() and report.is_file())
        # Event ledger records actual outputs with real hashes.
        _r, _m, _p, events = _manifest_context(self.manifest_path)
        mat = next(e for e in events if e.get("stage_id") == "virtual_query_materialization" and e.get("status") == "SUCCEEDED")
        by_id = {o["artifact_id"]: o for o in mat["output_artifacts"]}
        self.assertEqual(set(by_id), {"virtual_query_input", "virtual_query_validation"})
        for aid, path in (("virtual_query_input", out), ("virtual_query_validation", report)):
            self.assertEqual(by_id[aid]["path"], str(path))
            self.assertEqual(by_id[aid]["sha256"], sha256_file(path))
        # Manifest (artifact view) resolves the same IDs/paths/hashes as CURRENT.
        report_manifest = build_artifact_manifest(self.manifest_path)
        rows = {r["artifact_id"]: r for r in report_manifest["artifacts"]}
        for aid in ("virtual_query_input", "virtual_query_validation"):
            self.assertEqual(rows[aid]["status"], "CURRENT")
            self.assertEqual(rows[aid]["path"], str(_artifact_path(self.run_root, defs[aid])))
            self.assertEqual(rows[aid]["expected_sha256"], sha256_file(_artifact_path(self.run_root, defs[aid])))
            self.assertEqual(rows[aid]["actual_sha256"], rows[aid]["expected_sha256"])
        # Validation report content bound to the formal query file.
        validation = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(validation["prepared_query_path"], str(out))
        self.assertEqual(validation["prepared_query_sha256"], sha256_file(out))

    def test_g2_state_and_snapshot_consume_same_artifacts(self):
        self._setup_run("RUN_PREDICTION")
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=_real_materialization_binding()):
            result = execute_local_stage(self.manifest_path, "virtual_query_materialization")
        self.assertEqual(result["status"], "SUCCEEDED")
        _r, _m, plan, events = _manifest_context(self.manifest_path)
        state = resolve_virtual_query_state(self.run_root, plan, events, phase="g2")
        self.assertEqual(state.status, QUERY_REVIEW_READY)
        defs, _ = _artifact_definitions(plan)
        self.assertEqual(state.query_path, _artifact_path(self.run_root, defs["virtual_query_input"]))
        self.assertEqual(state.validation_path, _artifact_path(self.run_root, defs["virtual_query_validation"]))
        # G2 input snapshot (real resolver) reads the same bound decision/query/validation.
        from dor.run_manager import _stage_input_snapshots
        g2_stage = next(s for s in plan["stages"] if s["stage_id"] == "g2_review_packet") if any(
            s["stage_id"] == "g2_review_packet" for s in plan["stages"]) else None
        if g2_stage is None:
            # add a temporary in-memory G2 stage to exercise the shared snapshot logic
            g2_stage = {
                "stage_id": "g2_review_packet", "executor": "manual",
                "inputs": ["modeling_task", "virtual_query_decision", "virtual_query_input", "virtual_query_validation"],
                "outputs": [],
            }
        snaps = _stage_input_snapshots(self.run_root, _m, plan, g2_stage, events)
        snap_ids = {s["artifact_id"]: s for s in snaps}
        for aid in ("virtual_query_decision", "virtual_query_input", "virtual_query_validation"):
            self.assertIn(aid, snap_ids)
            self.assertEqual(snap_ids[aid]["sha256"], sha256_file(Path(snap_ids[aid]["path"])))

    def test_missing_or_tampered_validation_output_is_rejected(self):
        self._setup_run("RUN_PREDICTION")
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=_real_materialization_binding()):
            result = execute_local_stage(self.manifest_path, "virtual_query_materialization")
        self.assertEqual(result["status"], "SUCCEEDED")
        report = build_artifact_manifest(self.manifest_path)
        vrow = next(r for r in report["artifacts"] if r["artifact_id"] == "virtual_query_validation")
        # Tamper the validation file -> artifact manifest must show STALE and verify_run source check holds.
        Path(vrow["path"]).write_text('{"tampered": true}\n', encoding="utf-8")
        report2 = build_artifact_manifest(self.manifest_path)
        vrow2 = next(r for r in report2["artifacts"] if r["artifact_id"] == "virtual_query_validation")
        self.assertEqual(vrow2["status"], "STALE_OR_MISSING")
        self.assertNotEqual(vrow2["actual_sha256"], vrow2["expected_sha256"])

    def test_cli_failure_cannot_create_succeeded_stage(self):
        self._setup_run("RUN_PREDICTION", source_query_unit_ok=False)
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=_real_materialization_binding()):
            result = execute_local_stage(self.manifest_path, "virtual_query_materialization")
        self.assertEqual(result["status"], "FAILED", result)
        self.assertNotEqual(result["return_code"], 0)
        _r, _m, _p, events = _manifest_context(self.manifest_path)
        statuses = [e.get("status") for e in events if e.get("stage_id") == "virtual_query_materialization"]
        self.assertNotIn("SUCCEEDED", statuses)
        self.assertIn("FAILED", statuses)

    # A4/A5: NA through real advance_run activation -> SKIPPED, no outputs
    def test_na_stage_skipped_no_outputs_and_manifest_has_no_query_validation(self):
        self._setup_run("NOT_APPLICABLE")
        result = advance_run(self.manifest_path, max_local_stages=5)
        self.assertIn(result["status"], {"PAUSED_FOR_HUMAN", "BLOCKED", "COMPLETE"})
        actions = {s["stage_id"]: s["action"] for s in build_resume_plan(self.manifest_path)["stages"]}
        self.assertEqual(actions["virtual_query_materialization"], "SKIPPED")
        defs, _ = self._defs()
        for aid in ("virtual_query_input", "virtual_query_validation"):
            self.assertFalse(_artifact_path(self.run_root, defs[aid]).exists())
        _r, _m, plan, events = _manifest_context(self.manifest_path)
        skipped = [e for e in events if e.get("stage_id") == "virtual_query_materialization" and e.get("status") == "SKIPPED"]
        self.assertTrue(skipped)
        self.assertEqual(skipped[-1]["output_artifacts"], [])
        self.assertIn("activation_evaluation", skipped[-1])
        manifest = build_artifact_manifest(self.manifest_path)
        rows = {r["artifact_id"]: r for r in manifest["artifacts"]}
        # Declared-but-not-created artifacts may appear as NOT_CREATED placeholders;
        # they must never be registered as CURRENT or carry a fabricated hash.
        for aid in ("virtual_query_input", "virtual_query_validation"):
            self.assertEqual(rows[aid]["status"], "NOT_CREATED")
            self.assertIsNone(rows[aid]["expected_sha256"])
            self.assertIsNone(rows[aid]["actual_sha256"])
        state = resolve_virtual_query_state(self.run_root, plan, events, phase="g2")
        self.assertEqual(state.status, NOT_APPLICABLE)

    def test_two_runs_are_isolated(self):
        # A separate RUN_PREDICTION run and NA run use different run roots.
        self._setup_run("RUN_PREDICTION")
        with patch("dor.stage_runner.stage_action_bindings_for_plan", return_value=_real_materialization_binding()):
            self.assertEqual(execute_local_stage(self.manifest_path, "virtual_query_materialization")["status"], "SUCCEEDED")
        rp_defs, _ = self._defs()
        rp_input = _artifact_path(self.run_root, rp_defs["virtual_query_input"])
        self.assertTrue(rp_input.is_file())
        rp_hash = sha256_file(rp_input)
        # New NA run in a different root
        tmp2 = _controlled_temp_dir("dor-vq-cli-na-")
        self.addCleanup(tmp2.cleanup)
        old_root, old_plan, old_manifest = self.run_root, self.plan_path, self.manifest_path
        self.run_root = Path(tmp2.name) / "run"
        self.plan_path = Path(tmp2.name) / "run_plan.json"
        self.manifest_path = self.run_root / "run_manifest.json"
        self.source_root = Path(tmp2.name) / "sources"
        self.source_root.mkdir()
        self.adapter = self.source_root / "adapter.json"
        _w(self.adapter, {"adapter": "synthetic-na"})
        self._setup_run("NOT_APPLICABLE")
        advance_run(self.manifest_path, max_local_stages=5)
        na_defs, _ = self._defs()
        self.assertFalse(_artifact_path(self.run_root, na_defs["virtual_query_input"]).exists())
        self.assertNotEqual(self.run_root, old_root)
        self.assertTrue(rp_input.is_file())
        self.assertEqual(sha256_file(rp_input), rp_hash)  # RP run untouched


if __name__ == "__main__":
    unittest.main()
