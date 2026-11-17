"""Unified Virtual Query consumption state resolution for FULL_ANALYSIS.

Phase-aware readiness:
- phase="g2" (Query Review Ready): evaluates readiness for G2 review only.
  RUN_PREDICTION: valid decision bound to task + valid materialized query/validation.
    Prediction execution/state is NOT required. State: QUERY_REVIEW_READY.
  NOT_APPLICABLE: valid decision+reason + materialization formally SKIPPED + no
    query/validation artifacts. Prediction stage state is NOT required (it runs after G2).
    State: NOT_APPLICABLE (query-review ready; no prediction consumer readiness).

- phase="consumer" (Prediction Consumer Ready): evaluates readiness for G3/Review/G4/Publication.
  RUN_PREDICTION: G2-ready query artifacts + prediction stage SUCCEEDED + valid prediction artifact/provenance.
    State: PREDICTION_READY.
  NOT_APPLICABLE: valid decision+reason + materialization and prediction both formally SKIPPED +
    no query/validation/prediction artifacts. State: NOT_APPLICABLE.

States: QUERY_REVIEW_READY | PREDICTION_READY | NOT_APPLICABLE | PENDING | FAILED_OR_INVALID
QUERY_REVIEW_READY is never sufficient for downstream prediction consumption.
NA must never be inferred from missing prediction alone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dor.mapping import sha256_file


VQ_ARTIFACT_IDS = {
    "virtual_query_decision",
    "virtual_query_input",
    "virtual_query_validation",
    "virtual_prediction",
}
QUERY_REVIEW_READY = "QUERY_REVIEW_READY"
PREDICTION_READY = "PREDICTION_READY"
NOT_APPLICABLE = "NOT_APPLICABLE"
PENDING = "PENDING"
FAILED_OR_INVALID = "FAILED_OR_INVALID"


@dataclass
class VQState:
    status: str
    reason: str
    decision: dict[str, Any] | None = None
    decision_path: Path | None = None
    query_path: Path | None = None
    validation_path: Path | None = None
    prediction_path: Path | None = None
    materialization_stage_status: str | None = None
    prediction_stage_status: str | None = None
    phase: str = "consumer"
    details: dict[str, Any] | None = None

    @property
    def query_review_ready(self) -> bool:
        if self.phase == "g2":
            return self.status in {QUERY_REVIEW_READY, NOT_APPLICABLE}
        # consumer-phase NOT_APPLICABLE implies prior query-review conditions satisfied
        return self.status in {QUERY_REVIEW_READY, PREDICTION_READY, NOT_APPLICABLE}

    @property
    def prediction_consumer_ready(self) -> bool:
        return self.phase == "consumer" and self.status in {PREDICTION_READY, NOT_APPLICABLE}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _find_artifact_path(run_root: Path, plan: Mapping[str, Any], artifact_id: str) -> Path | None:
    # source artifacts
    for item in plan.get("source_artifacts", []) or []:
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id:
            p = Path(str(item.get("path", ""))).expanduser()
            return p.resolve(strict=False) if p.is_absolute() else (run_root / p).resolve(strict=False)
    # stage outputs
    for stage in plan.get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        for out in stage.get("outputs", []) or []:
            if isinstance(out, dict) and out.get("artifact_id") == artifact_id:
                p = Path(str(out.get("path", ""))).expanduser()
                return p.resolve(strict=False) if p.is_absolute() else (run_root / p).resolve(strict=False)
    return None


def _latest_stage_status(events: list[Mapping[str, Any]], stage_id: str) -> str | None:
    status = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") == "STAGE_STATUS" and ev.get("stage_id") == stage_id:
            s = ev.get("status")
            if isinstance(s, str):
                status = s
    return status


def _load_decision_safe(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from dor.virtual_reproduction import read_virtual_query_decision
        return read_virtual_query_decision(path), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def resolve_virtual_query_state(
    run_root: Path,
    plan: Mapping[str, Any],
    events: list[Mapping[str, Any]] | None = None,
    *,
    modeling_task_path: Path | None = None,
    phase: str = "consumer",
) -> VQState:
    """Resolve VQ state from run artifacts and event ledger.

    phase="g2"        -> Query Review Ready (G2). Prediction state not required.
    phase="consumer"  -> Prediction Consumer Ready (G3/Review/G4/Publication).
    Does not mutate artifacts or decisions.
    """
    if phase not in {"g2", "consumer"}:
        raise ValueError(f"Unsupported VQ readiness phase: {phase}")
    run_root = run_root.expanduser().resolve()
    events = list(events or [])

    decision_path = _find_artifact_path(run_root, plan, "virtual_query_decision")
    query_path = _find_artifact_path(run_root, plan, "virtual_query_input")
    validation_path = _find_artifact_path(run_root, plan, "virtual_query_validation")
    prediction_path = _find_artifact_path(run_root, plan, "virtual_prediction")
    mat_status = _latest_stage_status(events, "virtual_query_materialization")
    pred_status = _latest_stage_status(events, "virtual_condition_prediction")

    if decision_path is None or not decision_path.exists():
        return VQState(PENDING, "virtual_query_decision is missing.", materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)

    decision, derr = _load_decision_safe(decision_path)
    if derr or decision is None:
        return VQState(FAILED_OR_INVALID, f"virtual_query_decision is invalid: {derr}", decision_path=decision_path,
                       materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)

    task_path = modeling_task_path or _find_artifact_path(run_root, plan, "modeling_task")
    task_sha = None
    task = None
    if task_path is not None and task_path.exists():
        try:
            task = _read_json(task_path)
            task_sha = sha256_file(task_path)
        except Exception as exc:  # noqa: BLE001
            return VQState(FAILED_OR_INVALID, f"modeling_task cannot be read for VQ validation: {exc}", decision=decision,
                           decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
    if task is not None and isinstance(task, dict):
        if decision.get("modeling_task_sha256") != task_sha:
            return VQState(FAILED_OR_INVALID, "virtual_query_decision modeling_task_sha256 does not match current modeling_task.",
                           decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        for k in ("task_id", "target_id", "endpoint_definition"):
            if decision.get(k) != task.get(k):
                return VQState(FAILED_OR_INVALID, f"virtual_query_decision {k} does not match current modeling_task.",
                               decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)

    d = decision.get("decision")
    if d == NOT_APPLICABLE:
        reason = decision.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return VQState(FAILED_OR_INVALID, "NOT_APPLICABLE decision requires non-empty reason.", decision=decision,
                           decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if query_path and query_path.exists():
            return VQState(FAILED_OR_INVALID, "NOT_APPLICABLE decision must not have virtual_query_input artifact.", decision=decision,
                           decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if validation_path and validation_path.exists():
            return VQState(FAILED_OR_INVALID, "NOT_APPLICABLE decision must not have virtual_query_validation artifact.", decision=decision,
                           decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if prediction_path and prediction_path.exists():
            return VQState(FAILED_OR_INVALID, "NOT_APPLICABLE decision must not have virtual_prediction artifact.", decision=decision,
                           decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        # G2/Query Review Ready: only materialization must be formally SKIPPED (prediction runs after G2)
        if mat_status != "SKIPPED":
            return VQState(PENDING if mat_status in (None, "RUNNING") else FAILED_OR_INVALID,
                           f"NOT_APPLICABLE requires virtual_query_materialization to be formally SKIPPED (found {mat_status}).",
                           decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if phase == "consumer":
            if pred_status != "SKIPPED":
                return VQState(PENDING if pred_status in (None, "RUNNING") else FAILED_OR_INVALID,
                               f"NOT_APPLICABLE requires virtual_condition_prediction to be formally SKIPPED for downstream consumption (found {pred_status}).",
                               decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            details = {
                "query_review_ready": True,
                "prediction_consumer_ready": True,
                "formal_skip_evidence": {
                    "decision_reason": reason,
                    "materialization_stage_status": mat_status,
                    "prediction_stage_status": pred_status,
                    "output_artifacts": [],
                    "query_artifacts_absent": True,
                    "validation_artifacts_absent": True,
                    "prediction_artifacts_absent": True,
                },
            }
            return VQState(NOT_APPLICABLE, "Valid NOT_APPLICABLE decision with materialization/prediction formally SKIPPED and no query/validation/prediction artifacts.",
                           decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase, details=details)
        # phase g2: prediction stage state not required yet
        details = {
            "query_review_ready": True,
            "prediction_consumer_ready": False,
            "formal_skip_evidence": {
                "decision_reason": reason,
                "materialization_stage_status": mat_status,
                "prediction_stage_status": pred_status,
                "output_artifacts": [],
                "query_artifacts_absent": True,
                "validation_artifacts_absent": True,
            },
        }
        return VQState(NOT_APPLICABLE, "Valid NOT_APPLICABLE decision with materialization formally SKIPPED (prediction occurs after G2).",
                       decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase, details=details)

    if d == "RUN_PREDICTION":
        # Query/validation readiness required for both phases
        if query_path is None or not query_path.exists() or validation_path is None or not validation_path.exists():
            if mat_status in (None, "RUNNING"):
                return VQState(PENDING, "RUN_PREDICTION materialization/query artifacts are not yet ready.",
                               decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            if mat_status == "FAILED":
                return VQState(FAILED_OR_INVALID, "RUN_PREDICTION materialization failed.",
                               decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            return VQState(PENDING if mat_status == "SKIPPED" else FAILED_OR_INVALID,
                           "RUN_PREDICTION requires valid virtual_query_input and virtual_query_validation artifacts.",
                           decision=decision, decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        try:
            if task_path is None or task is None:
                return VQState(PENDING, "modeling_task required to validate RUN_PREDICTION artifacts is not available.",
                               decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                               materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            from dor.virtual_reproduction import validate_virtual_query_preparation_artifacts
            validate_virtual_query_preparation_artifacts(task_path=task_path, decision_path=decision_path, query_path=query_path, validation_path=validation_path)
        except Exception as exc:  # noqa: BLE001
            return VQState(FAILED_OR_INVALID, f"RUN_PREDICTION query/validation artifacts are invalid: {exc}",
                           decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                           materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if phase == "g2":
            # G2/query review ready: prediction not required yet
            if mat_status == "FAILED":
                return VQState(FAILED_OR_INVALID, "RUN_PREDICTION materialization failed.",
                               decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                               materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            details = {
                "query_review_ready": True,
                "prediction_consumer_ready": False,
                "prediction_required_for_g2": False,
            }
            return VQState(QUERY_REVIEW_READY, "RUN_PREDICTION query/validation ready for G2 review (prediction not yet required).",
                           decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                           materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase, details=details)

        # consumer phase: prediction must be complete and valid
        if prediction_path is None or not prediction_path.exists():
            if pred_status in (None, "RUNNING"):
                return VQState(PENDING, "RUN_PREDICTION prediction is not yet complete.",
                               decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                               materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            if pred_status == "FAILED":
                return VQState(FAILED_OR_INVALID, "virtual_condition_prediction failed.",
                               decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                               materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            if pred_status == "SKIPPED":
                return VQState(FAILED_OR_INVALID, "RUN_PREDICTION cannot have virtual_condition_prediction SKIPPED without a prediction artifact.",
                               decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                               materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
            return VQState(PENDING, "RUN_PREDICTION prediction artifact is missing.",
                           decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                           materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        if pred_status != "SUCCEEDED":
            return VQState(PENDING if pred_status in (None, "RUNNING") else FAILED_OR_INVALID,
                           f"RUN_PREDICTION requires virtual_condition_prediction SUCCEEDED for downstream consumption (found {pred_status}).",
                           decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                           prediction_path=prediction_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        try:
            pred = _read_json(prediction_path)
            if not isinstance(pred, dict):
                raise ValueError("prediction must be a JSON object")
            if task and isinstance(task, dict):
                for k in ("task_id", "target_id", "endpoint_definition"):
                    if pred.get(k) != task.get(k):
                        raise ValueError(f"prediction {k} does not match modeling_task")
        except Exception as exc:  # noqa: BLE001
            return VQState(FAILED_OR_INVALID, f"virtual_prediction artifact is invalid: {exc}",
                           decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                           prediction_path=prediction_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)
        details = {"query_review_ready": True, "prediction_consumer_ready": True}
        return VQState(PREDICTION_READY, "RUN_PREDICTION query/validation and prediction are ready for downstream consumption.",
                       decision=decision, decision_path=decision_path, query_path=query_path, validation_path=validation_path,
                       prediction_path=prediction_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase, details=details)

    return VQState(FAILED_OR_INVALID, f"Unsupported virtual_query_decision value: {d!r}", decision=decision,
                   decision_path=decision_path, materialization_stage_status=mat_status, prediction_stage_status=pred_status, phase=phase)


def is_full_analysis_plan(plan: Mapping[str, Any]) -> bool:
    """Resolve the Run Plan profile explicitly; never infer from a missing decision.

    The canonical key is ``execution_profile`` (FULL_ANALYSIS is represented by
    an absent key or the explicit value). ``domain_profile`` is accepted only as
    a legacy alias for older synthetic fixtures; it is not a real profile key.
    Unknown profiles fail closed.
    """
    profile = plan.get("execution_profile")
    if profile is None:
        profile = plan.get("domain_profile", "FULL_ANALYSIS")
    if profile not in {"FULL_ANALYSIS", "CONTROLLED_SINGLE_STUDY"}:
        raise ValueError(f"Unsupported Run Plan execution_profile for Virtual Query: {profile!r}.")
    return profile == "FULL_ANALYSIS"


class VirtualQueryNotReadyError(ValueError):
    """Raised at a consumer entry point when VQ readiness is not satisfied.

    Carries structured, auditable context so callers surface a concrete status,
    the failed/incomplete Stage, the affected Artifacts and the exact condition
    that must be met. Never raised for a valid NOT_APPLICABLE consumer state.
    """

    def __init__(self, *, status: str, stage_id: str, phase: str, failed_stage: str | None,
                 artifacts: list[str], requirement: str, detail: str):
        self.status = status
        self.stage_id = stage_id
        self.phase = phase
        self.failed_stage = failed_stage
        self.artifacts = artifacts
        self.requirement = requirement
        self.detail = detail
        message = (
            f"Virtual Query state {status} does not authorize consumer stage {stage_id!r} "
            f"(phase={phase}): {detail}. "
            f"Failed_or_incomplete_stage={failed_stage!r}, "
            f"affected_artifacts={artifacts!r}. Required: {requirement}"
        )
        super().__init__(message)


def latest_stage_event(events: list[Mapping[str, Any]] | None, stage_id: str) -> dict[str, Any] | None:
    """Return the latest STAGE_STATUS event for a Stage from the Run event record."""
    found: dict[str, Any] | None = None
    for event in events or []:
        if (isinstance(event, dict) and event.get("event_type") == "STAGE_STATUS"
                and event.get("stage_id") == stage_id):
            found = dict(event)
    return found


def require_vq_ready(
    run_root: Path,
    plan: Mapping[str, Any],
    events: list[Mapping[str, Any]] | None,
    stage_id: str,
    phase: str,
) -> VQState:
    """Resolve VQ state and require the phase-specific readiness capability.

    PENDING / FAILED_OR_INVALID are rejected here with a structured error. G2
    QUERY_REVIEW_READY is never sufficient for a consumer phase.
    """
    state = resolve_virtual_query_state(run_root, plan, events, phase=phase)
    ready_statuses = (
        {QUERY_REVIEW_READY, NOT_APPLICABLE} if phase == "g2"
        else {PREDICTION_READY, NOT_APPLICABLE}
    )
    if state.status in ready_statuses:
        return state

    failed_stage: str | None = None
    affected: list[str] = []
    low = state.reason.lower()
    if "prediction" in low and "materialization" not in low:
        failed_stage = "virtual_condition_prediction"
    elif "materialization" in low or "query" in low or "validation" in low:
        failed_stage = "virtual_query_materialization"
    elif "decision" in low or "task" in low:
        failed_stage = "virtual_query_preparation"
    elif state.status == PENDING:
        if state.materialization_stage_status in (None, "RUNNING"):
            failed_stage = "virtual_query_materialization"
        elif state.prediction_stage_status in (None, "RUNNING"):
            failed_stage = "virtual_condition_prediction"
        else:
            failed_stage = "virtual_query_preparation"
    else:
        failed_stage = "virtual_query_decision"

    if state.decision_path is None or not (state.decision_path.exists()):
        affected.append("virtual_query_decision")
    if state.query_path is None or not state.query_path.exists():
        affected.append("virtual_query_input")
    if state.validation_path is None or not state.validation_path.exists():
        affected.append("virtual_query_validation")
    if phase == "consumer" and (state.prediction_path is None or not state.prediction_path.exists()):
        affected.append("virtual_prediction")

    if phase == "g2":
        requirement = (
            "G2 Query Review Ready: a valid human virtual_query_decision bound to the current modeling_task, "
            "and either valid virtual_query_input/virtual_query_validation (RUN_PREDICTION) or a formally SKIPPED "
            "virtual_query_materialization with no query/validation artifacts (NOT_APPLICABLE)."
        )
    else:
        requirement = (
            "G3/G4 Prediction Consumer Ready: valid decision and prepared query/validation plus a SUCCEEDED "
            "virtual_condition_prediction with bound prediction/provenance (RUN_PREDICTION), or valid decision with "
            "formally SKIPPED materialization and prediction and no query/validation/prediction artifacts (NOT_APPLICABLE)."
        )
    raise VirtualQueryNotReadyError(
        status=state.status, stage_id=stage_id, phase=phase, failed_stage=failed_stage,
        artifacts=affected, requirement=requirement, detail=state.reason,
    )


def build_vq_evidence(
    run_root: Path,
    plan: Mapping[str, Any],
    events: list[Mapping[str, Any]] | None,
    state: VQState,
    phase: str,
) -> dict[str, Any]:
    """Build auditable VQ evidence from real files and Run events for a Review/worker packet.

    All paths, hashes and Stage statuses are derived from the active Run plan,
    the artifact resolver and the Run event record. No evidence is synthesized
    from the decision declaration alone.
    """
    run_root = run_root.expanduser().resolve()
    events = list(events or [])

    def file_fact(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {"present": False, "path": None, "sha256": None}
        resolved = path.expanduser().resolve(strict=False)
        if resolved.is_file() and not resolved.is_symlink():
            try:
                digest = sha256_file(resolved)
            except OSError:
                digest = None
            return {"present": True, "path": str(resolved), "sha256": digest}
        return {"present": False, "path": str(resolved), "sha256": None}

    def stage_fact(stage_id: str) -> dict[str, Any]:
        event = latest_stage_event(events, stage_id)
        if event is None:
            return {"stage_id": stage_id, "recorded": False, "status": None, "event_hash": None}
        return {
            "stage_id": stage_id,
            "recorded": True,
            "status": event.get("status"),
            "event_hash": event.get("event_hash"),
            "attempt": event.get("attempt"),
            "reason": event.get("reason"),
            "activation_evaluation": event.get("activation_evaluation"),
            "input_artifacts": event.get("input_artifacts", []),
            "output_artifacts": event.get("output_artifacts", []),
        }

    decision = state.decision or {}
    query_fact = file_fact(state.query_path)
    validation_fact = file_fact(state.validation_path)
    prediction_fact = file_fact(state.prediction_path)

    evidence: dict[str, Any] = {
        "contract": "RUN_VIRTUAL_QUERY_EVIDENCE",
        "phase": phase,
        "status": state.status,
        "query_review_ready": state.query_review_ready,
        "prediction_consumer_ready": state.prediction_consumer_ready,
        "run_id": plan.get("run_id"),
        "project_id": plan.get("project_id"),
        "execution_profile": plan.get("execution_profile", "FULL_ANALYSIS"),
        "decision": {
            "artifact_id": "virtual_query_decision",
            "path": str(state.decision_path) if state.decision_path else None,
            "sha256": sha256_file(state.decision_path) if state.decision_path and state.decision_path.is_file() else None,
            "decision": decision.get("decision"),
            "reason": decision.get("reason"),
            "task_id": decision.get("task_id"),
            "target_id": decision.get("target_id"),
            "endpoint_definition": decision.get("endpoint_definition"),
            "modeling_task_sha256": decision.get("modeling_task_sha256"),
            "reviewer": decision.get("reviewer"),
            "decided_at": decision.get("decided_at"),
            "source_query_path": decision.get("source_query_path"),
        },
        "modeling_task": file_fact(_find_artifact_path(run_root, plan, "modeling_task")),
        "materialization": stage_fact("virtual_query_materialization"),
        "prediction_stage": stage_fact("virtual_condition_prediction"),
        "query": {"artifact_id": "virtual_query_input", **query_fact},
        "validation": {"artifact_id": "virtual_query_validation", **validation_fact},
        "prediction": {"artifact_id": "virtual_prediction", **prediction_fact},
    }

    decision_value = decision.get("decision")
    if decision_value == "RUN_PREDICTION":
        binding_check: dict[str, Any] = {"performed": False, "valid": False}
        try:
            task_path = _find_artifact_path(run_root, plan, "modeling_task")
            if task_path and state.query_path and state.validation_path:
                from dor.virtual_reproduction import validate_virtual_query_preparation_artifacts
                summary = validate_virtual_query_preparation_artifacts(
                    task_path=task_path, decision_path=state.decision_path,
                    query_path=state.query_path, validation_path=state.validation_path,
                )
                query_doc = _read_json(state.query_path)
                task_doc = _read_json(task_path)
                expected_units = {
                    item.get("feature_id"): item.get("expected_unit")
                    for item in (task_doc.get("feature_bindings") or []) if isinstance(item, dict)
                }
                feature_units = {
                    fid: item.get("unit") for fid, item in (query_doc.get("features") or {}).items()
                    if isinstance(item, dict)
                }
                binding_check = {
                    "performed": True,
                    "valid": bool(summary.get("valid")) and feature_units == expected_units,
                    "contract": summary.get("contract"),
                    "valid_report": summary.get("valid"),
                    "expected_units": expected_units,
                    "query_feature_units": feature_units,
                    "feature_ids_match": set(feature_units) == set(expected_units),
                    "expected_units_match": feature_units == expected_units,
                }
        except Exception as exc:  # noqa: BLE001
            binding_check = {"performed": True, "valid": False, "error": str(exc)}
        evidence["feature_binding_check"] = binding_check
        task_identity_match = False
        try:
            task_path_local = _find_artifact_path(run_root, plan, "modeling_task")
            if task_path_local and task_path_local.is_file():
                task_doc_local = _read_json(task_path_local)
                task_identity_match = all(
                    decision.get(key) == task_doc_local.get(key)
                    for key in ("task_id", "target_id", "endpoint_definition")
                ) and decision.get("modeling_task_sha256") == sha256_file(task_path_local)
        except Exception:  # noqa: BLE001
            task_identity_match = False
        evidence["task_identity_match"] = task_identity_match
        evidence["identity_binding"] = {
            "task_id": decision.get("task_id"),
            "target_id": decision.get("target_id"),
            "endpoint_definition": decision.get("endpoint_definition"),
            "modeling_task_sha256": decision.get("modeling_task_sha256"),
            "resolver_status": state.status,
        }
    else:
        evidence["formal_skip_evidence"] = dict((state.details or {}).get("formal_skip_evidence") or {})
        evidence["artifact_absence_check"] = {
            "virtual_query_input_present": query_fact["present"],
            "virtual_query_validation_present": validation_fact["present"],
            "virtual_prediction_present": prediction_fact["present"],
            "all_absent": not (query_fact["present"] or validation_fact["present"] or prediction_fact["present"]),
        }
    return evidence


def effective_vq_input_artifacts(state: VQState) -> dict[str, Path]:
    """Return VQ artifact paths that should be supplied to consumers for the resolved phase/state."""
    if state.status == QUERY_REVIEW_READY:
        result: dict[str, Path] = {}
        if state.decision_path: result["virtual_query_decision"] = state.decision_path
        if state.query_path: result["virtual_query_input"] = state.query_path
        if state.validation_path: result["virtual_query_validation"] = state.validation_path
        return result
    if state.status == PREDICTION_READY:
        result = {}
        if state.decision_path: result["virtual_query_decision"] = state.decision_path
        if state.query_path: result["virtual_query_input"] = state.query_path
        if state.validation_path: result["virtual_query_validation"] = state.validation_path
        # prediction artifact only available/required in consumer-ready RUN_PREDICTION
        if state.phase == "consumer" and state.prediction_path:
            result["virtual_prediction"] = state.prediction_path
        return result
    if state.status == NOT_APPLICABLE:
        return {"virtual_query_decision": state.decision_path} if state.decision_path else {}
    return {}
