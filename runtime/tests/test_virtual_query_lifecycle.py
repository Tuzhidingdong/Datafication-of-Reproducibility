from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.run_manager import initialize_run, build_resume_plan, record_stage_status
from dor.stage_runner import advance_run
from dor.mapping import sha256_file
from dor.virtual_reproduction import prepare_virtual_query_files
from dor.virtual_query_state import (
    resolve_virtual_query_state, QUERY_REVIEW_READY, PREDICTION_READY, NOT_APPLICABLE, PENDING, FAILED_OR_INVALID,
)


def _w(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class VirtualQueryRunLevelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dor-vq-run-")
        self.root = Path(self.tmp.name)
        self.source_root = self.root / "src"
        self.source_root.mkdir()
        self.adapter = self.source_root / "adapter.json"
        _w(self.adapter, {"adapter": "x"})
        self.plan_path = self.root / "run_plan.json"
        self.run_root = self.root / "run"
        self.manifest_path = self.run_root / "run_manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self, plan):
        _w(self.plan_path, plan)
        initialize_run(self.plan_path, self.run_root, "RUN_VQ")
        return plan

    def _vq_plan(self):
        # Custom (non-supported-route) FULL_ANALYSIS plan to exercise VQ semantics.
        return {
            "schema_version": "1.0",
            "project_id": "P_VQ",
            "execution_profile": "FULL_ANALYSIS",
            "source_roots": [str(self.source_root.resolve())],
            "source_artifacts": [{"artifact_id": "adapter_package_manifest", "path": str(self.adapter.resolve())}],
            "stages": [
                {
                    "stage_id": "modeling_setup", "executor": "local", "depends_on": [],
                    "inputs": ["adapter_package_manifest"],
                    "outputs": [
                        {"artifact_id": "modeling_task", "path": "05_scope/modeling_task.json"},
                        {"artifact_id": "research_scope_record", "path": "05_scope/research_scope_record.json"},
                    ],
                },
                {
                    "stage_id": "virtual_query_preparation", "executor": "manual", "depends_on": ["modeling_setup"],
                    "inputs": ["modeling_task", "research_scope_record"],
                    "outputs": [{"artifact_id": "virtual_query_decision", "path": "08_vq/virtual_query_decision.json"}],
                },
                {
                    "stage_id": "virtual_query_materialization", "executor": "local", "depends_on": ["modeling_setup", "virtual_query_preparation"],
                    "inputs": ["modeling_task", "virtual_query_decision"],
                    "activation": {"artifact_id": "virtual_query_decision", "json_pointer": "/decision", "operator": "equals", "value": "RUN_PREDICTION"},
                    "outputs": [
                        {"artifact_id": "virtual_query_input", "path": "08_vq/virtual_query_input.json"},
                        {"artifact_id": "virtual_query_validation", "path": "08_vq/virtual_query_validation.json"},
                    ],
                },
                {
                    "stage_id": "g2_review_packet", "executor": "manual",
                    "depends_on": ["modeling_setup", "virtual_query_preparation", "virtual_query_materialization"],
                    "inputs": ["modeling_task", "virtual_query_decision"],
                    "outputs": [
                        {"artifact_id": "g2_review_packet", "path": "04_g2/g2_review_packet.json"},
                        {"artifact_id": "g2_review_packet_validation", "path": "04_g2/g2_review_packet_validation.json"},
                    ],
                },
                {
                    "stage_id": "baseline_model_fit", "executor": "local", "depends_on": ["modeling_setup", "g2_review_packet"],
                    "inputs": ["modeling_task"],
                    "outputs": [
                        {"artifact_id": "model_artifact", "path": "06_model/model.json"},
                        {"artifact_id": "baseline_run_manifest", "path": "06_model/baseline.json"},
                    ],
                },
                {
                    "stage_id": "virtual_condition_prediction", "executor": "local",
                    "depends_on": ["baseline_model_fit", "virtual_query_preparation", "virtual_query_materialization"],
                    "inputs": ["virtual_query_decision", "model_artifact", "baseline_run_manifest", "virtual_query_input", "virtual_query_validation"],
                    "activation": {"artifact_id": "virtual_query_decision", "json_pointer": "/decision", "operator": "equals", "value": "RUN_PREDICTION"},
                    "outputs": [{"artifact_id": "virtual_prediction", "path": "08_vq/virtual_prediction.json"}],
                },
            ],
        }

    def _modeling_task(self):
        return {
            "schema_version": "1.0",
            "task_id": "TASK_1",
            "target_id": "TARGET_1",
            "endpoint_definition": "endpoint_x",
            "modeling_strategy": "regression",
            "feature_bindings": [
                {"feature_id": "f1", "value_type": "NUMERIC", "expected_unit": "mol"},
                {"feature_id": "f2", "value_type": "NUMERIC", "expected_unit": "K"},
            ],
        }

    def _write_modeling(self):
        task = self._modeling_task()
        record_stage_status(self.manifest_path, "modeling_setup", "RUNNING", "local", command="setup")
        _w(self.run_root / "05_scope/modeling_task.json", task)
        _w(self.run_root / "05_scope/research_scope_record.json", {"scope": "s"})
        record_stage_status(self.manifest_path, "modeling_setup", "SUCCEEDED", "local")
        return task

    def _write_decision(self, decision, reason="n/a", query=None):
        task_path = self.run_root / "05_scope/modeling_task.json"
        dec = {
            "schema_version": "1.0",
            "decision": decision,
            "reason": reason,
            "task_id": "TASK_1",
            "target_id": "TARGET_1",
            "endpoint_definition": "endpoint_x",
            "modeling_task_sha256": sha256_file(task_path),
            "reviewer": "tester",
            "decided_at": "2026-01-01T00:00:00Z",
        }
        if decision == "RUN_PREDICTION" and query is not None:
            dec["source_query_path"] = "08_vq/source_query.json"
            _w(self.run_root / "08_vq/source_query.json", query)
        record_stage_status(self.manifest_path, "virtual_query_preparation", "RUNNING", "manual")
        _w(self.run_root / "08_vq/virtual_query_decision.json", dec)
        record_stage_status(self.manifest_path, "virtual_query_preparation", "SUCCEEDED", "manual")
        return dec

    def test_not_applicable_materialization_and_prediction_skipped_allows_g2(self):
        plan = self._vq_plan()
        self._init(plan)
        self._write_modeling()
        self._write_decision("NOT_APPLICABLE", reason="No applicable virtual condition for this task.")

        # advance should SKIP materialization (activation false)
        res1 = advance_run(self.manifest_path, max_local_stages=5)
        # materialization becomes SKIPPED; G2 is manual so advance pauses for human
        self.assertIn(res1["status"], {"PAUSED_FOR_HUMAN", "BLOCKED", "COMPLETE"})

        actions = {s["stage_id"]: s for s in build_resume_plan(self.manifest_path)["stages"]}
        self.assertEqual(actions["virtual_query_materialization"]["action"], "SKIPPED")
        self.assertFalse((self.run_root / "08_vq/virtual_query_input.json").exists())
        self.assertFalse((self.run_root / "08_vq/virtual_query_validation.json").exists())
        # G2 must not be blocked by skipped materialization (no consumed outputs)
        self.assertEqual(actions["g2_review_packet"]["action"], "READY_TO_RUN")

        # verify SKIPPED event has activation evidence and no outputs
        _, _, loaded_plan, events = __import__("dor.run_manager", fromlist=["_manifest_context"])._manifest_context(self.manifest_path)
        mat_events = [e for e in events if e.get("stage_id") == "virtual_query_materialization" and e.get("status") == "SKIPPED"]
        self.assertTrue(mat_events)
        self.assertIn("activation_evaluation", mat_events[-1])
        self.assertEqual(mat_events[-1]["output_artifacts"], [])

        # G2/query-review readiness at G2 time: materialization SKIPPED, prediction not yet run/SKIPPED
        g2_state = resolve_virtual_query_state(self.run_root, loaded_plan, events, phase="g2")
        self.assertEqual(g2_state.status, NOT_APPLICABLE)
        consumer_before_pred = resolve_virtual_query_state(self.run_root, loaded_plan, events, phase="consumer")
        self.assertIn(consumer_before_pred.status, {PENDING, NOT_APPLICABLE})

        # prediction remains downstream of g2/baseline; once deps satisfied and activation false it should be skippable
        # simulate g2 and baseline completion without running CLIs
        record_stage_status(self.manifest_path, "g2_review_packet", "RUNNING", "manual")
        _w(self.run_root / "04_g2/g2_review_packet.json", {"packet": 1})
        _w(self.run_root / "04_g2/g2_review_packet_validation.json", {"ok": True})
        record_stage_status(self.manifest_path, "g2_review_packet", "SUCCEEDED", "manual")
        record_stage_status(self.manifest_path, "baseline_model_fit", "RUNNING", "local", command="fit")
        _w(self.run_root / "06_model/model.json", {"m": 1})
        _w(self.run_root / "06_model/baseline.json", {"b": 1})
        record_stage_status(self.manifest_path, "baseline_model_fit", "SUCCEEDED", "local")

        actions2 = {s["stage_id"]: s for s in build_resume_plan(self.manifest_path)["stages"]}
        # prediction activation is false (decision NA); should be SKIP_REQUIRED now deps done
        self.assertEqual(actions2["virtual_condition_prediction"]["action"], "SKIP_REQUIRED")
        # advance records SKIPPED for local skip-required stage
        res2 = advance_run(self.manifest_path, max_local_stages=5)
        actions3 = {s["stage_id"]: s for s in build_resume_plan(self.manifest_path)["stages"]}
        self.assertEqual(actions3["virtual_condition_prediction"]["action"], "SKIPPED")
        self.assertFalse((self.run_root / "08_vq/virtual_prediction.json").exists())

        # reload events for state
        _, _, p2, ev2 = __import__("dor.run_manager", fromlist=["_manifest_context"])._manifest_context(self.manifest_path)
        consumer_state = resolve_virtual_query_state(self.run_root, p2, ev2, phase="consumer")
        self.assertEqual(consumer_state.status, NOT_APPLICABLE)

    def test_run_prediction_materialization_creates_artifacts_and_state_pending_until_prediction(self):
        plan = self._vq_plan()
        self._init(plan)
        self._write_modeling()
        query = {
            "schema_version": "1.0",
            "task_id": "TASK_1", "target_id": "TARGET_1", "endpoint_definition": "endpoint_x",
            "features": {
                "f1": {"value": 1.0, "unit": "mol"},
                "f2": {"value": 300.0, "unit": "K"},
            },
        }
        # write decision as RUN_PREDICTION
        task_path = self.run_root / "05_scope/modeling_task.json"
        dec = {
            "schema_version": "1.0", "decision": "RUN_PREDICTION", "reason": "Need prediction",
            "task_id": "TASK_1", "target_id": "TARGET_1", "endpoint_definition": "endpoint_x",
            "modeling_task_sha256": sha256_file(task_path), "reviewer": "tester", "decided_at": "2026-01-01T00:00:00Z",
            "source_query_path": "08_vq/source_query.json",
        }
        _w(self.run_root / "08_vq/source_query.json", query)
        record_stage_status(self.manifest_path, "virtual_query_preparation", "RUNNING", "manual")
        _w(self.run_root / "08_vq/virtual_query_decision.json", dec)
        record_stage_status(self.manifest_path, "virtual_query_preparation", "SUCCEEDED", "manual")

        # execute materialization via direct call (local stage CLI in real runner would call this action)
        record_stage_status(self.manifest_path, "virtual_query_materialization", "RUNNING", "local", command="vq")
        prepare_virtual_query_files(
            task_path=task_path,
            decision_path=self.run_root / "08_vq/virtual_query_decision.json",
            output_path=self.run_root / "08_vq/virtual_query_input.json",
            report_path=self.run_root / "08_vq/virtual_query_validation.json",
            query_path=self.run_root / "08_vq/source_query.json",
        )
        # record as succeeded to reflect execution
        record_stage_status(self.manifest_path, "virtual_query_materialization", "SUCCEEDED", "local")
        self.assertTrue((self.run_root / "08_vq/virtual_query_input.json").exists())
        self.assertTrue((self.run_root / "08_vq/virtual_query_validation.json").exists())

        _, _, p, ev = __import__("dor.run_manager", fromlist=["_manifest_context"])._manifest_context(self.manifest_path)
        consumer_state = resolve_virtual_query_state(self.run_root, p, ev, phase="consumer")
        self.assertEqual(consumer_state.status, PENDING)  # prediction not done
        g2_state = resolve_virtual_query_state(self.run_root, p, ev, phase="g2")
        self.assertEqual(g2_state.status, QUERY_REVIEW_READY)  # query/validation ready for G2, prediction not required
        self.assertTrue(g2_state.query_review_ready)
        self.assertFalse(g2_state.prediction_consumer_ready)

        actions = {s["stage_id"]: s for s in build_resume_plan(self.manifest_path)["stages"]}
        self.assertEqual(actions["g2_review_packet"]["action"], "READY_TO_RUN")


if __name__ == "__main__":
    unittest.main()
