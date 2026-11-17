"""Synthetic entry-point tests for the FULL_ANALYSIS Virtual Query dual path.

These tests exercise the real G2 packet validator, Worker authorization, Review
validator and Publication plan/assembly/audit validators. No real data, Worker,
Gate approval or publication is used; all artifacts are synthetic and live in a
temporary Run workspace.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.mapping import sha256_file
from dor.publication import (
    audit_publication_package_files, build_publication_package_files,
    validate_publication_plan_files,
)
from dor.review import validate_reviewed_findings_files, validate_run_review_packet_files
from dor.run_manager import (
    _manifest_context, authorize_worker, initialize_run, record_stage_status,
)
from dor.virtual_query_state import (
    VirtualQueryNotReadyError, NOT_APPLICABLE, PENDING, FAILED_OR_INVALID,
)


def _w(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class VQConsumerEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dor-vq-consumer-")
        self.root = Path(self.tmp.name)
        self.source_root = self.root / "src"
        self.source_root.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.adapter = self.source_root / "adapter.json"
        _w(self.adapter, {"adapter": "synthetic"})
        self.plan_path = self.root / "run_plan.json"
        self.run_root = self.root / "run"
        self.manifest_path = self.run_root / "run_manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- plan / run helpers ----------
    def _plan(self, g2_inputs):
        return {
            "schema_version": "1.0",
            "project_id": "P_VQ_CONSUMER",
            "execution_profile": "FULL_ANALYSIS",
            "source_roots": [str(self.source_root.resolve())],
            "source_artifacts": [{"artifact_id": "adapter_package_manifest", "path": str(self.adapter.resolve())}],
            "stages": [
                {"stage_id": "modeling_setup", "executor": "local", "depends_on": [],
                 "inputs": ["adapter_package_manifest"],
                 "outputs": [
                     {"artifact_id": "modeling_task", "path": "05_scope/modeling_task.json"},
                     {"artifact_id": "research_scope_record", "path": "05_scope/research_scope_record.json"},
                 ]},
                {"stage_id": "virtual_query_preparation", "executor": "manual", "depends_on": ["modeling_setup"],
                 "inputs": ["modeling_task"],
                 "outputs": [{"artifact_id": "virtual_query_decision", "path": "08_vq/virtual_query_decision.json"}]},
                {"stage_id": "virtual_query_materialization", "executor": "local",
                 "depends_on": ["modeling_setup", "virtual_query_preparation"],
                 "inputs": ["modeling_task", "virtual_query_decision"],
                 "activation": {"artifact_id": "virtual_query_decision", "json_pointer": "/decision",
                                "operator": "equals", "value": "RUN_PREDICTION"},
                 "outputs": [
                     {"artifact_id": "virtual_query_input", "path": "08_vq/virtual_query_input.json"},
                     {"artifact_id": "virtual_query_validation", "path": "08_vq/virtual_query_validation.json"},
                 ]},
                {"stage_id": "g2_review_packet", "executor": "manual",
                 "depends_on": ["modeling_setup", "virtual_query_preparation", "virtual_query_materialization"],
                 "inputs": g2_inputs,
                 "outputs": [
                     {"artifact_id": "g2_review_packet", "path": "04_g2/g2_review_packet.json"},
                     {"artifact_id": "g2_review_packet_validation", "path": "04_g2/g2_review_packet_validation.json"},
                 ]},
                {"stage_id": "baseline_model_fit", "executor": "local", "depends_on": ["g2_review_packet", "modeling_setup"],
                 "inputs": ["modeling_task"],
                 "outputs": [
                     {"artifact_id": "model_artifact", "path": "06_model/model_artifact.json"},
                     {"artifact_id": "model_report", "path": "06_model/model_report.json"},
                     {"artifact_id": "reproducibility_evaluation", "path": "06_model/reproducibility_evaluation.json"},
                     {"artifact_id": "interaction_report", "path": "06_model/interaction_report.json"},
                     {"artifact_id": "robustness_report", "path": "06_model/robustness_report.json"},
                     {"artifact_id": "interaction_selection", "path": "06_model/interaction_selection.json"},
                     {"artifact_id": "cohort_review_record", "path": "06_model/cohort_review_record.json"},
                     {"artifact_id": "cohort_review_validation", "path": "06_model/cohort_review_validation.json"},
                 ]},
                {"stage_id": "virtual_condition_prediction", "executor": "local",
                 "depends_on": ["baseline_model_fit", "virtual_query_materialization", "virtual_query_preparation"],
                 "inputs": ["virtual_query_decision", "model_artifact", "virtual_query_input", "virtual_query_validation"],
                 "activation": {"artifact_id": "virtual_query_decision", "json_pointer": "/decision",
                                "operator": "equals", "value": "RUN_PREDICTION"},
                 "outputs": [{"artifact_id": "virtual_prediction", "path": "08_vq/virtual_prediction.json"}]},
                {"stage_id": "independent_result_review", "executor": "worker", "depends_on": ["baseline_model_fit"],
                 "worker_task": {"objective": "Review synthetic results.",
                                 "permitted_actions": ["Read declared inputs", "Write review JSON"],
                                 "forbidden_actions": ["Change artifacts"]},
                 "inputs": ["model_report"],
                 "outputs": [{"artifact_id": "worker_review_output",
                              "path": "worker_staging/independent_result_review/review.json", "kind": "worker_staging"}]},
                {"stage_id": "human_review_and_promotion", "executor": "manual",
                 "depends_on": ["independent_result_review", "baseline_model_fit"],
                 "inputs": ["worker_review_output", "model_report"],
                 "outputs": [
                     {"artifact_id": "reviewed_findings", "path": "09_review/reviewed_findings.json"},
                     {"artifact_id": "reviewed_findings_validation", "path": "09_review/reviewed_findings_validation.json"},
                 ]},
                {"stage_id": "publication_plan_preparation", "executor": "manual",
                 "depends_on": ["human_review_and_promotion", "virtual_query_preparation"],
                 "inputs": ["virtual_query_decision"],
                 "outputs": [
                     {"artifact_id": "publication_plan", "path": "10_publication/publication_package_plan.json"},
                     {"artifact_id": "publication_plan_validation", "path": "10_publication/publication_plan_validation.json"},
                 ]},
            ],
        }

    def _init(self, g2_inputs):
        plan = self._plan(g2_inputs)
        _w(self.plan_path, plan)
        initialize_run(self.plan_path, self.run_root, "RUN_VQ_CONSUMER")
        return plan

    def _decision(self, value, *, reason="Synthetic virtual query decision."):
        task_path = self.run_root / "05_scope/modeling_task.json"
        payload = {
            "schema_version": "1.0", "decision": value, "reason": reason,
            "task_id": "TASK_VQ", "target_id": "TARGET_VQ", "endpoint_definition": "endpoint_vq",
            "modeling_task_sha256": sha256_file(task_path),
            "reviewer": "synthetic-reviewer", "decided_at": "2026-11-16T00:00:00Z",
        }
        if value == "RUN_PREDICTION":
            payload["source_query_path"] = "08_vq/source_query.json"
        return payload

    def _run_modeling(self):
        record_stage_status(self.manifest_path, "modeling_setup", "RUNNING", "local", command="setup")
        _w(self.run_root / "05_scope/modeling_task.json", {
            "schema_version": "1.0", "task_id": "TASK_VQ", "target_id": "TARGET_VQ",
            "endpoint_definition": "endpoint_vq", "modeling_strategy": "regression",
            "feature_bindings": [
                {"feature_id": "f1", "value_type": "NUMERIC", "expected_unit": "mol"},
                {"feature_id": "f2", "value_type": "NUMERIC", "expected_unit": "K"},
            ],
        })
        _w(self.run_root / "05_scope/research_scope_record.json", {"scope": "synthetic"})
        record_stage_status(self.manifest_path, "modeling_setup", "SUCCEEDED", "local")

    def _run_preparation(self, value, *, reason="Synthetic virtual query decision."):
        record_stage_status(self.manifest_path, "virtual_query_preparation", "RUNNING", "manual")
        _w(self.run_root / "08_vq/virtual_query_decision.json", self._decision(value, reason=reason))
        record_stage_status(self.manifest_path, "virtual_query_preparation", "SUCCEEDED", "manual")

    def _run_materialization(self):
        query = {
            "schema_version": "1.0", "task_id": "TASK_VQ", "target_id": "TARGET_VQ",
            "endpoint_definition": "endpoint_vq",
            "features": {"f1": {"value": 1.0, "unit": "mol"}, "f2": {"value": 300.0, "unit": "K"}},
        }
        _w(self.run_root / "08_vq/source_query.json", query)
        record_stage_status(self.manifest_path, "virtual_query_materialization", "RUNNING", "local", command="vq")
        from dor.virtual_reproduction import prepare_virtual_query_files
        prepare_virtual_query_files(
            task_path=self.run_root / "05_scope/modeling_task.json",
            decision_path=self.run_root / "08_vq/virtual_query_decision.json",
            output_path=self.run_root / "08_vq/virtual_query_input.json",
            report_path=self.run_root / "08_vq/virtual_query_validation.json",
            query_path=self.run_root / "08_vq/source_query.json",
        )
        record_stage_status(self.manifest_path, "virtual_query_materialization", "SUCCEEDED", "local")

    def _skip_materialization(self):
        record_stage_status(self.manifest_path, "virtual_query_materialization", "SKIPPED", "local",
                            reason="Decision is NOT_APPLICABLE.")

    def _run_g2(self, g2_inputs, finalize=True):
        record_stage_status(self.manifest_path, "g2_review_packet", "RUNNING", "manual")
        bindings = []
        for artifact_id in g2_inputs:
            from dor.run_manager import _artifact_definitions, _artifact_path
            definitions, _ = _artifact_definitions(json.loads(self.plan_path.read_text(encoding="utf-8")))
            path = _artifact_path(self.run_root, definitions[artifact_id])
            bindings.append({"artifact_id": artifact_id, "path": str(path), "sha256": sha256_file(path)})
        packet = {
            "schema_version": "1.0", "run_id": "RUN_VQ_CONSUMER", "project_id": "P_VQ_CONSUMER",
            "stage_id": "g2_review_packet", "prepared_at": "2026-11-16T00:00:00Z",
            "packet_status": "AWAITING_HUMAN_REVIEW", "artifact_bindings": bindings,
            "review_items": [{"item_id": "all", "question": "Reviewed all inputs?",
                              "artifact_ids": list(g2_inputs), "mandatory": True}],
            "unresolved_questions": [],
        }
        _w(self.run_root / "04_g2/g2_review_packet.json", packet)
        if finalize:
            # For packet-evidence tests the validator needs the stage still RUNNING.
            _w(self.run_root / "04_g2/g2_review_packet_validation.json", {"placeholder": True})
            record_stage_status(self.manifest_path, "g2_review_packet", "SUCCEEDED", "manual")

    def _run_baseline(self):
        record_stage_status(self.manifest_path, "baseline_model_fit", "RUNNING", "local", command="fit")
        names = ["model_artifact", "model_report", "reproducibility_evaluation", "interaction_report",
                 "robustness_report", "interaction_selection", "cohort_review_record", "cohort_review_validation"]
        from dor.run_manager import _artifact_definitions, _artifact_path
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        definitions, _ = _artifact_definitions(plan)
        for name in names:
            _w(_artifact_path(self.run_root, definitions[name]), {"artifact_id": name, "task_id": "TASK_VQ"})
        _w(self.run_root / "06_model/interaction_selection.json", {
            "schema_version": "1.1", "task_id": "TASK_VQ", "interaction_report_sha256": "a" * 64,
            "robustness_report_sha256": "b" * 64, "selected_interaction_ids": [],
            "not_selected_interaction_ids": [], "reviewer": "synthetic-reviewer",
            "reviewed_at": "2026-11-16T00:00:00Z", "rationale": "No candidates.",
        })
        record_stage_status(self.manifest_path, "baseline_model_fit", "SUCCEEDED", "local")

    def _run_prediction(self, *, task_id="TASK_VQ", finalize=True):
        record_stage_status(self.manifest_path, "virtual_condition_prediction", "RUNNING", "local", command="predict")
        _w(self.run_root / "08_vq/virtual_prediction.json", {
            "schema_version": "1.0", "task_id": task_id, "target_id": "TARGET_VQ",
            "endpoint_definition": "endpoint_vq", "prediction": 1.0,
            "query_sha256": sha256_file(self.run_root / "08_vq/virtual_query_input.json"),
        })
        if finalize:
            record_stage_status(self.manifest_path, "virtual_condition_prediction", "SUCCEEDED", "local")

    def _skip_prediction(self):
        record_stage_status(self.manifest_path, "virtual_condition_prediction", "SKIPPED", "local",
                            reason="Decision is NOT_APPLICABLE.")

    def _auth(self):
        return authorize_worker(
            self.manifest_path, "independent_result_review", "reviewer", "provider", "model",
            self.project, "synthetic-reviewer", "Synthetic authorization.",
        )

    def _setup_rp(self, g2_finalize=True, baseline=True):
        plan = self._init(["modeling_task", "virtual_query_decision", "virtual_query_input", "virtual_query_validation"])
        self._run_modeling()
        self._run_preparation("RUN_PREDICTION")
        self._run_materialization()
        self._run_g2(plan["stages"][3]["inputs"], finalize=g2_finalize)
        if baseline:
            self._run_baseline()
        return plan

    def _setup_na(self, g2_finalize=True, skip_prediction=True, baseline=True):
        plan = self._init(["modeling_task", "virtual_query_decision"])
        self._run_modeling()
        self._run_preparation("NOT_APPLICABLE", reason="No applicable virtual condition.")
        self._skip_materialization()
        self._run_g2(plan["stages"][3]["inputs"], finalize=g2_finalize)
        if baseline:
            self._run_baseline()
        if skip_prediction:
            self._skip_prediction()
        return plan

    # ---------- G2 packet evidence ----------
    def test_g2_packet_na_evidence_comes_from_real_events(self):
        self._setup_na(g2_finalize=False, baseline=False)
        packet = self.run_root / "04_g2/g2_review_packet.json"
        report = self.run_root / "04_g2/g2_review_packet_validation.json"
        report.unlink(missing_ok=True)
        result = validate_run_review_packet_files(packet, self.manifest_path, report)
        self.assertTrue(result["valid"], result["errors"])
        ev = result["virtual_query_evidence"]
        self.assertEqual(ev["contract"], "RUN_VIRTUAL_QUERY_EVIDENCE")
        self.assertEqual(ev["status"], NOT_APPLICABLE)
        self.assertEqual(ev["decision"]["reason"], "No applicable virtual condition.")
        self.assertEqual(ev["materialization"]["status"], "SKIPPED")
        self.assertIn("activation_evaluation", ev["materialization"])
        self.assertEqual(ev["materialization"]["output_artifacts"], [])
        self.assertTrue(ev["artifact_absence_check"]["all_absent"])
        self.assertTrue(ev["materialization"]["event_hash"])
        self.assertEqual(ev["decision"]["sha256"], sha256_file(self.run_root / "08_vq/virtual_query_decision.json"))

    def test_g2_packet_run_prediction_evidence_binds_query_validation(self):
        self._setup_rp(g2_finalize=False, baseline=False)
        packet = self.run_root / "04_g2/g2_review_packet.json"
        report = self.run_root / "04_g2/g2_review_packet_validation.json"
        report.unlink(missing_ok=True)
        result = validate_run_review_packet_files(packet, self.manifest_path, report)
        self.assertTrue(result["valid"], result["errors"])
        ev = result["virtual_query_evidence"]
        self.assertEqual(ev["status"], "QUERY_REVIEW_READY")
        self.assertFalse(ev["prediction_consumer_ready"])
        self.assertTrue(ev["query"]["present"])
        self.assertTrue(ev["validation"]["present"])
        self.assertEqual(ev["query"]["sha256"], sha256_file(self.run_root / "08_vq/virtual_query_input.json"))
        self.assertTrue(ev["task_identity_match"])
        self.assertTrue(ev["feature_binding_check"]["valid"])
        self.assertTrue(ev["feature_binding_check"]["expected_units_match"])

    def test_g2_packet_rejects_pending_decision_state(self):
        # Missing decision -> no valid VQ state -> G2 packet must reject.
        self._setup_na(g2_finalize=False, baseline=False)
        (self.run_root / "08_vq/virtual_query_decision.json").unlink()
        _, _, _, events = _manifest_context(self.manifest_path)
        packet = self.run_root / "04_g2/g2_review_packet.json"
        report = self.run_root / "04_g2/g2_review_packet_validation.json"
        report.unlink(missing_ok=True)
        result = validate_run_review_packet_files(packet, self.manifest_path, report)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] == "VIRTUAL_QUERY_NOT_QUERY_REVIEW_READY" for item in result["errors"]), result["errors"])

    # ---------- Worker authorization ----------
    def test_worker_auth_run_prediction_ready(self):
        self._setup_rp()
        self._run_prediction()
        result = self._auth()
        packet = result["task_packet"]
        ids = {item["artifact_id"] for item in packet["input_artifacts"]}
        self.assertTrue({"virtual_query_decision", "virtual_query_input", "virtual_query_validation", "virtual_prediction"}.issubset(ids))
        ev = packet["virtual_query_evidence"]
        self.assertEqual(ev["status"], "PREDICTION_READY")
        self.assertTrue(ev["prediction_consumer_ready"])
        self.assertEqual(ev["prediction"]["sha256"], sha256_file(self.run_root / "08_vq/virtual_prediction.json"))

    def test_worker_auth_run_prediction_not_ready_is_rejected(self):
        self._setup_rp()
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertEqual(ctx.exception.status, PENDING)
        self.assertEqual(ctx.exception.failed_stage, "virtual_condition_prediction")
        self.assertIn("virtual_prediction", ctx.exception.artifacts)

    def test_worker_auth_na_all_skipped_evidence(self):
        self._setup_na()
        result = self._auth()
        packet = result["task_packet"]
        ids = {item["artifact_id"] for item in packet["input_artifacts"]}
        self.assertIn("virtual_query_decision", ids)
        self.assertFalse({"virtual_query_input", "virtual_query_validation", "virtual_prediction"} & ids)
        ev = packet["virtual_query_evidence"]
        self.assertEqual(ev["status"], NOT_APPLICABLE)
        self.assertEqual(ev["materialization"]["status"], "SKIPPED")
        self.assertEqual(ev["prediction_stage"]["status"], "SKIPPED")
        self.assertTrue(ev["artifact_absence_check"]["all_absent"])

    def test_worker_auth_na_missing_one_skipped_evidence_is_rejected(self):
        # Materialization SKIPPED is present but prediction SKIPPED evidence is absent.
        self._setup_na(skip_prediction=False)
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertIn(ctx.exception.status, {PENDING, FAILED_OR_INVALID})
        self.assertEqual(ctx.exception.failed_stage, "virtual_condition_prediction")

    def test_worker_auth_missing_decision_is_rejected(self):
        self._setup_rp()
        self._run_prediction()
        (self.run_root / "08_vq/virtual_query_decision.json").unlink()
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertIn("virtual_query_decision", ctx.exception.artifacts)

    def test_worker_auth_decision_task_hash_mismatch_is_rejected(self):
        self._setup_rp()
        self._run_prediction()
        path = self.run_root / "08_vq/virtual_query_decision.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["modeling_task_sha256"] = "0" * 64
        _w(path, data)
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertEqual(ctx.exception.status, FAILED_OR_INVALID)

    def test_worker_auth_query_validation_hash_mismatch_is_rejected(self):
        self._setup_rp()
        self._run_prediction()
        path = self.run_root / "08_vq/virtual_query_input.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["features"]["f1"]["value"] = 999.0
        _w(path, data)
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertEqual(ctx.exception.status, FAILED_OR_INVALID)

    def test_worker_auth_prediction_failed_stage_is_rejected(self):
        self._setup_rp()
        record_stage_status(self.manifest_path, "virtual_condition_prediction", "RUNNING", "local", command="predict")
        record_stage_status(self.manifest_path, "virtual_condition_prediction", "FAILED", "local",
                            reason="Synthetic prediction failure.")
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertEqual(ctx.exception.status, FAILED_OR_INVALID)

    def test_worker_auth_prediction_lineage_mismatch_is_rejected(self):
        self._setup_rp()
        self._run_prediction(task_id="OTHER_TASK")
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            self._auth()
        self.assertEqual(ctx.exception.status, FAILED_OR_INVALID)

    # ---------- Review consumer ----------
    def _run_worker_and_review(self, *, include_vp=False):
        auth = self._auth()
        task_id = auth["worker_task_id"] if "worker_task_id" in auth else auth["task_packet"]["task_id"]
        record_stage_status(self.manifest_path, "independent_result_review", "RUNNING", "worker",
                            role="reviewer", provider="provider", model="model", project_root=str(self.project))
        _w(self.run_root / "worker_staging/independent_result_review/review.json", {
            "schema_version": "1.0", "task_id": task_id, "status": "completed",
            "summary": "Synthetic review.", "findings": [], "artifacts": [],
            "warnings": [], "unresolved_questions": [],
        })
        record_stage_status(self.manifest_path, "independent_result_review", "SUCCEEDED", "worker")
        record_stage_status(self.manifest_path, "human_review_and_promotion", "RUNNING", "manual")
        reviewed_ids = ["model_report", "virtual_query_decision"]
        if include_vp:
            reviewed_ids += ["virtual_query_input", "virtual_query_validation", "virtual_prediction"]
        from dor.run_manager import _artifact_definitions, _artifact_path
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        definitions, _ = _artifact_definitions(plan)
        reviewed = []
        for aid in reviewed_ids:
            path = _artifact_path(self.run_root, definitions[aid])
            reviewed.append({"artifact_id": aid, "path": str(path), "sha256": sha256_file(path)})
        worker_path = self.run_root / "worker_staging/independent_result_review/review.json"
        record = {
            "schema_version": "1.0", "run_id": "RUN_VQ_CONSUMER", "project_id": "P_VQ_CONSUMER",
            "reviewer": "synthetic-reviewer", "reviewed_at": "2026-11-16T00:00:00Z",
            "worker_output": {"artifact_id": "worker_review_output", "path": str(worker_path), "sha256": sha256_file(worker_path)},
            "reviewed_artifacts": reviewed, "findings": [], "promotion_decision": "DO_NOT_PROMOTE",
            "overall_rationale": "No findings to promote.",
        }
        _w(self.run_root / "09_review/reviewed_findings.json", record)

    def _validate_and_finalize_review(self):
        report_path = self.run_root / "09_review/reviewed_findings_validation.json"
        report = validate_reviewed_findings_files(
            self.run_root / "09_review/reviewed_findings.json", self.manifest_path, report_path,
        )
        _w(report_path, report)
        record_stage_status(self.manifest_path, "human_review_and_promotion", "SUCCEEDED", "manual")
        return report

    def _run_publication_prep(self):
        record_stage_status(self.manifest_path, "publication_plan_preparation", "RUNNING", "manual")

    def test_review_consumer_run_prediction(self):
        self._setup_rp()
        self._run_prediction()
        self._run_worker_and_review(include_vp=True)
        report = self._validate_and_finalize_review()
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["virtual_query_evidence"]["status"], "PREDICTION_READY")

    def test_review_consumer_na(self):
        self._setup_na()
        self._run_worker_and_review(include_vp=False)
        report = self._validate_and_finalize_review()
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["virtual_query_evidence"]["status"], NOT_APPLICABLE)
        self.assertTrue(report["virtual_query_evidence"]["artifact_absence_check"]["all_absent"])

    def test_review_consumer_pending_is_rejected(self):
        self._setup_rp()
        self._run_prediction()
        self._run_worker_and_review(include_vp=True)
        # Make prediction lineage invalid after review -> consumer not ready
        path = self.run_root / "08_vq/virtual_condition_prediction.json"
        _, _, _, events = _manifest_context(self.manifest_path)
        pred_events = [e for e in events if e.get("stage_id") == "virtual_condition_prediction" and e.get("status") == "SUCCEEDED"]
        self.assertTrue(pred_events)
        data = json.loads((self.run_root / "08_vq/virtual_prediction.json").read_text(encoding="utf-8"))
        data["task_id"] = "BROKEN"
        _w(self.run_root / "08_vq/virtual_prediction.json", data)
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            validate_reviewed_findings_files(
                self.run_root / "09_review/reviewed_findings.json", self.manifest_path,
                self.run_root / "09_review/reviewed_findings_validation.json",
            )
        self.assertEqual(ctx.exception.status, FAILED_OR_INVALID)

    # ---------- Publication plan / assembly / audit ----------
    def _write_publication_plan(self, *, na):
        from dor.run_manager import _artifact_definitions, _artifact_path
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        definitions, _ = _artifact_definitions(plan)
        entries = []
        sources = {
            "WORKER_REVIEW_RECORD": "worker_review_output",
            "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
            "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
            "COHORT_REVIEW_RECORD": "cohort_review_record",
            "COHORT_REVIEW_VALIDATION": "cohort_review_validation",
            "MODEL_ARTIFACT_001": "model_artifact",
            "MODEL_REPORT_001": "model_report",
            "REPRODUCIBILITY_EVALUATION_001": "reproducibility_evaluation",
            "INTERACTION_REPORT_001": "interaction_report",
            "INTERACTION_ROBUSTNESS_001": "robustness_report",
            "INTERACTION_SELECTION_001": "interaction_selection",
            "VIRTUAL_PREDICTION_001": "virtual_prediction",
        }
        for package_id, artifact_id in sources.items():
            if na and artifact_id == "virtual_prediction":
                entries.append({
                    "artifact_id": package_id, "path": "artifacts/virtual_prediction_001.json",
                    "source_path": None, "source_artifact_id": None, "type": "prediction",
                    "description": "Virtual prediction not applicable.", "status": "not_applicable",
                    "linked_record_ids": [], "manuscript_sections": [],
                })
                continue
            source_path = _artifact_path(self.run_root, definitions[artifact_id])
            entries.append({
                "artifact_id": package_id, "path": "artifacts/" + artifact_id + ".json",
                "source_path": source_path.relative_to(self.run_root).as_posix(),
                "source_artifact_id": artifact_id, "type": "result",
                "description": "Synthetic publication source.", "status": "complete",
                "linked_record_ids": [], "manuscript_sections": [],
            })
        final_plan = {
            "schema_version": "1.0", "project_id": "P_VQ_CONSUMER", "run_id": "RUN_VQ_CONSUMER",
            "package_version": "synthetic-1", "artifacts": entries,
        }
        path = self.run_root / "10_publication/publication_package_plan.json"
        _w(path, final_plan)
        return path

    def _publication_plan_report(self, *, na):
        plan_path = self._write_publication_plan(na=na)
        report_path = self.run_root / "10_publication/publication_plan_validation.json"
        report_path.unlink(missing_ok=True)
        report = validate_publication_plan_files(plan_path, self.manifest_path, report_path)
        return plan_path, report_path, report

    def test_publication_plan_assembly_audit_run_prediction(self):
        self._setup_rp()
        self._run_prediction()
        self._run_worker_and_review(include_vp=True)
        self._validate_and_finalize_review()
        self._run_publication_prep()
        plan_path, report_path, report = self._publication_plan_report(na=False)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["virtual_query_evidence"]["status"], "PREDICTION_READY")
        vp = next(item for item in report["source_artifacts"] if item["package_artifact_id"] == "VIRTUAL_PREDICTION_001")
        self.assertEqual(vp["artifact_id"], "virtual_prediction")
        package_dir = self.root / "package_rp"
        build = build_publication_package_files(plan_path, self.run_root, package_dir, validation_path=report_path)
        self.assertTrue(build["valid"])
        self.assertTrue((package_dir / "artifacts/virtual_prediction.json").is_file())
        manifest = json.loads((package_dir / "package_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["virtual_query_evidence"]["status"], "PREDICTION_READY")
        audit = audit_publication_package_files(package_dir)
        self.assertTrue(audit["valid"], audit["errors"])

    def test_publication_plan_assembly_audit_na(self):
        self._setup_na()
        self._run_worker_and_review(include_vp=False)
        self._validate_and_finalize_review()
        self._run_publication_prep()
        plan_path, report_path, report = self._publication_plan_report(na=True)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["virtual_query_evidence"]["status"], NOT_APPLICABLE)
        self.assertFalse(any(item["artifact_id"] == "virtual_prediction" for item in report["source_artifacts"]))
        package_dir = self.root / "package_na"
        build = build_publication_package_files(plan_path, self.run_root, package_dir, validation_path=report_path)
        self.assertTrue(build["valid"])
        self.assertFalse((package_dir / "artifacts/virtual_prediction.json").exists())
        audit = audit_publication_package_files(package_dir)
        self.assertTrue(audit["valid"], audit["errors"])

    def test_unknown_execution_profile_fails_closed(self):
        plan = self._plan(["modeling_task", "virtual_query_decision"])
        plan["execution_profile"] = "EXPERIMENTAL_PROFILE"
        _w(self.plan_path, plan)
        from dor.virtual_query_state import is_full_analysis_plan
        with self.assertRaisesRegex(ValueError, "Unsupported Run Plan execution_profile"):
            is_full_analysis_plan(plan)

    def test_controlled_single_study_plan_is_not_full_analysis(self):
        plan = self._plan(["modeling_task", "virtual_query_decision"])
        plan["execution_profile"] = "CONTROLLED_SINGLE_STUDY"
        from dor.virtual_query_state import is_full_analysis_plan
        self.assertFalse(is_full_analysis_plan(plan))

    def test_publication_plan_rejects_pending(self):
        self._setup_rp()
        # No prediction executed/consumer-ready -> PENDING rejection at publication entry.
        plan_path = self._write_publication_plan(na=False)
        report_path = self.run_root / "10_publication/publication_plan_validation.json"
        report_path.unlink(missing_ok=True)
        with self.assertRaises(VirtualQueryNotReadyError) as ctx:
            validate_publication_plan_files(plan_path, self.manifest_path, report_path)
        self.assertEqual(ctx.exception.status, PENDING)


if __name__ == "__main__":
    unittest.main()
