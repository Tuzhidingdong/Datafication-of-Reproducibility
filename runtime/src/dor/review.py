"""Run-bound validation for human review and Worker promotion records."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from dor.run_manager import _latest_stage_events, _manifest_context, verify_run
from dor.virtual_query_state import (
    VirtualQueryNotReadyError, build_vq_evidence, require_vq_ready,
    is_full_analysis_plan, QUERY_REVIEW_READY, NOT_APPLICABLE,
)
from dor.worker_result import validate_worker_result_payload

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_REVIEW_STAGES = {"g0_review_packet", "g1_review_packet", "g2_review_packet"}
_WORKER_ID = "worker_review_output"
_PROMOTION_STAGE = "human_review_and_promotion"
_DISPOSITIONS = {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES", "REJECT", "DEFER"}
_DECISIONS = {"PROMOTE_ACCEPTED_ONLY", "PROMOTE_WITH_CHANGES", "DO_NOT_PROMOTE", "DEFER"}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(label + " must be a regular, non-symlink file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + " must be readable UTF-8 JSON: " + str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError(label + " must be a JSON object.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _resolve_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _run_context(manifest_path: Path):
    root, manifest, plan, events = _manifest_context(manifest_path)
    report = verify_run(manifest_path)
    rows = report.get("artifact_manifest", {}).get("artifacts")
    if not isinstance(rows, list):
        raise ValueError("Run Manager did not produce a valid artifact manifest.")
    artifacts: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("artifact_id"), str):
            raise ValueError("Run artifact manifest contains an invalid entry.")
        if row["artifact_id"] in artifacts:
            raise ValueError("Run artifact manifest contains duplicate artifact IDs.")
        artifacts[row["artifact_id"]] = row
    stages = {
        item["stage_id"]: item for item in plan.get("stages", [])
        if isinstance(item, dict) and isinstance(item.get("stage_id"), str)
    }
    return root, manifest, plan, events, artifacts, stages, report


def _expected_output_path(root: Path, stage: Mapping[str, Any], artifact_id: str) -> Path:
    matches = [
        item for item in stage.get("outputs", [])
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "Run Plan stage " + str(stage.get("stage_id"))
            + " must declare exactly one output artifact " + artifact_id + "."
        )
    path = _resolve_path(root, matches[0].get("path"))
    if path is None or not path.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Declared review output must remain inside the active Run workspace.")
    return path


def _check_record_and_report_paths(
    record_path: Path, report_path: Path, root: Path,
    stage: Mapping[str, Any], record_id: str, report_id: str,
) -> tuple[Path, Path]:
    supplied_record = record_path.expanduser()
    if supplied_record.is_symlink() or not supplied_record.is_file():
        raise ValueError("Review record must be a regular, non-symlink file.")
    actual_record = supplied_record.resolve(strict=True)
    expected_record = _expected_output_path(root, stage, record_id)
    if actual_record != expected_record:
        raise ValueError("Review record path differs from its exact Run Plan output path.")
    supplied_report = report_path.expanduser()
    if supplied_report.is_symlink() or supplied_report.exists():
        raise ValueError("Validation report must be a new file; existing files are never overwritten.")
    actual_report = supplied_report.resolve(strict=False)
    if actual_report != _expected_output_path(root, stage, report_id):
        raise ValueError("Validation report path differs from its exact Run Plan output path.")
    return actual_record, actual_report


def _binding_issues(
    binding: Mapping[str, Any], artifact_id: str, root: Path,
    artifacts: Mapping[str, Mapping[str, Any]], prefix: str,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    row = artifacts.get(artifact_id)
    if row is None:
        return [{"code": prefix + "_UNKNOWN_ARTIFACT", "message": "Unknown Run artifact: " + artifact_id}]
    actual_path = _resolve_path(root, binding.get("path"))
    run_path = Path(str(row.get("path", ""))).expanduser().resolve(strict=False)
    if actual_path is None or actual_path != run_path:
        issues.append({"code": prefix + "_PATH_MISMATCH", "message": "Path differs from the active Run artifact: " + artifact_id})
    digest = binding.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        issues.append({"code": prefix + "_INVALID_HASH", "message": "Invalid SHA-256: " + artifact_id})
    elif digest != row.get("actual_sha256"):
        issues.append({"code": prefix + "_HASH_MISMATCH", "message": "SHA-256 differs from the current artifact: " + artifact_id})
    if row.get("status") != "CURRENT":
        issues.append({"code": prefix + "_STALE_ARTIFACT", "message": "Run artifact is not current: " + artifact_id})
    current_path = Path(str(row.get("path", ""))).expanduser()
    try:
        current_hash = _sha256(current_path) if current_path.is_file() else None
    except OSError:
        current_hash = None
    if current_hash != digest:
        issues.append({"code": prefix + "_FILE_CHANGED_DURING_VALIDATION", "message": "Artifact file content no longer matches the bound SHA-256: " + artifact_id})
    return issues


def validate_run_review_packet_files(
    packet_path: Path, manifest_path: Path, report_path: Path,
) -> dict[str, Any]:
    root, manifest, _plan, events, artifacts, stages, run_report = _run_context(manifest_path)
    packet_file = packet_path.expanduser()
    packet = _read_json(packet_file, "Run review packet")
    stage_id = packet.get("stage_id")
    if not isinstance(stage_id, str) or stage_id not in _REVIEW_STAGES:
        raise ValueError("Review packet stage_id must be g0_review_packet, g1_review_packet, or g2_review_packet.")
    stage = stages.get(stage_id)
    if stage is None or stage.get("executor") != "manual":
        raise ValueError("Review packet must target a manual stage in the active Run Plan.")
    issues: list[dict[str, str]] = []
    vq_evidence: dict[str, Any] | None = None
    if stage_id == "g2_review_packet" and is_full_analysis_plan(_plan):
        # G2 packet must expose real, path/hash-bound evidence of the resolved
        # dual path. QUERY_REVIEW_READY is sufficient here; prediction execution
        # is deliberately NOT required for G2.
        try:
            vq_state = require_vq_ready(root, _plan, events, stage_id, "g2")
            vq_evidence = build_vq_evidence(root, _plan, events, vq_state, "g2")
        except VirtualQueryNotReadyError as exc:
            issues.append({
                "code": "VIRTUAL_QUERY_NOT_QUERY_REVIEW_READY",
                "message": str(exc),
            })
    latest_stage_event = _latest_stage_events(events).get(stage_id)
    if latest_stage_event is None or latest_stage_event.get("status") != "RUNNING":
        raise ValueError("Manual review packet stage must be recorded RUNNING before validation.")
    record_file, report_file = _check_record_and_report_paths(
        packet_file, report_path, root, stage, stage_id, stage_id + "_validation",
    )
    allowed = {
        "schema_version", "run_id", "project_id", "stage_id", "prepared_at",
        "packet_status", "artifact_bindings", "review_items",
        "unresolved_questions", "preparation_notes",
    }
    for key in sorted(set(packet) - allowed):
        issues.append({"code": "UNKNOWN_PROPERTY", "message": "Unknown review packet property: " + key})
    if packet.get("schema_version") != "1.0":
        issues.append({"code": "SCHEMA_VERSION", "message": "schema_version must be 1.0."})
    if packet.get("packet_status") != "AWAITING_HUMAN_REVIEW":
        issues.append({"code": "PACKET_STATUS", "message": "Review packet must remain AWAITING_HUMAN_REVIEW."})
    if packet.get("run_id") != manifest.get("run_id"):
        issues.append({"code": "RUN_ID_MISMATCH", "message": "Packet run_id differs from the active Run."})
    if packet.get("project_id") != manifest.get("project_id"):
        issues.append({"code": "PROJECT_ID_MISMATCH", "message": "Packet project_id differs from the active Run."})
    if not _aware_timestamp(packet.get("prepared_at")):
        issues.append({"code": "INVALID_TIMESTAMP", "message": "prepared_at must be a timezone-aware ISO-8601 timestamp."})
    operational_sources = run_report.get("source_artifacts", [])
    if not operational_sources or any(
        not isinstance(item, dict) or item.get("status") != "CURRENT"
        for item in operational_sources
    ):
        issues.append({
            "code": "OPERATIONAL_SOURCE_INTEGRITY_CHANGED",
            "message": "An operational Run source changed after initialization; provenance-only Acceptance sources are checked separately.",
        })

    bindings = packet.get("artifact_bindings")
    if not isinstance(bindings, list) or not bindings:
        issues.append({"code": "INVALID_BINDINGS", "message": "artifact_bindings must be a non-empty array."})
        bindings = []
    binding_ids: list[str] = []
    for item in bindings:
        if not isinstance(item, dict) or set(item) != {"artifact_id", "path", "sha256"}:
            issues.append({"code": "INVALID_BINDING", "message": "Every binding must contain exactly artifact_id, path, and sha256."})
            continue
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            issues.append({"code": "INVALID_BINDING_ID", "message": "artifact_id must be a non-empty string."})
            continue
        binding_ids.append(artifact_id)
        issues.extend(_binding_issues(item, artifact_id, root, artifacts, "BINDING"))
    if len(binding_ids) != len(set(binding_ids)):
        issues.append({"code": "DUPLICATE_BINDING", "message": "artifact_bindings contains duplicate artifact IDs."})
    expected_ids = set(stage.get("inputs", []))
    if vq_evidence is not None:
        # G2 Review consumes phase-resolved VQ inputs: the same shared conditional
        # input resolution used by worker authorization and Run events.
        from dor.run_manager import _effective_stage_inputs
        try:
            expected_ids = set(_effective_stage_inputs(root, manifest, _plan, dict(stage), events))
        except VirtualQueryNotReadyError:
            # The VQ-not-ready error has already been recorded above; keep the
            # static input set so the report is returned with actionable errors.
            pass
    supplied_ids = set(binding_ids)
    for artifact_id in sorted(expected_ids - supplied_ids):
        issues.append({"code": "MISSING_INPUT_BINDING", "message": "Missing declared stage input: " + artifact_id})
    for artifact_id in sorted(supplied_ids - expected_ids):
        issues.append({"code": "UNDECLARED_INPUT_BINDING", "message": "Binding is not a declared stage input: " + artifact_id})
    if vq_evidence is not None:
        # The G2 packet must visibly bind the dual-path VQ inputs: decision for
        # both paths, query/validation for RUN_PREDICTION, and NO query/validation
        # or prediction for NOT_APPLICABLE.
        if "virtual_query_decision" not in supplied_ids:
            issues.append({
                "code": "VQ_DECISION_NOT_BOUND",
                "message": "FULL_ANALYSIS G2 packet must bind virtual_query_decision.",
            })
        if vq_evidence["status"] == QUERY_REVIEW_READY:
            for artifact_id in ("virtual_query_input", "virtual_query_validation"):
                if artifact_id not in supplied_ids:
                    issues.append({
                        "code": "VQ_QUERY_INPUT_NOT_BOUND",
                        "message": "RUN_PREDICTION G2 packet must bind " + artifact_id + ".",
                    })
        elif vq_evidence["status"] == NOT_APPLICABLE:
            for artifact_id in ("virtual_query_input", "virtual_query_validation", "virtual_prediction"):
                if artifact_id in supplied_ids:
                    issues.append({
                        "code": "VQ_FORBIDDEN_ARTIFACT_BOUND",
                        "message": "NOT_APPLICABLE G2 packet must not bind " + artifact_id + ".",
                    })

    review_items = packet.get("review_items")
    if not isinstance(review_items, list) or not review_items:
        issues.append({"code": "INVALID_REVIEW_ITEMS", "message": "review_items must be a non-empty array."})
        review_items = []
    item_ids: list[str] = []
    for item in review_items:
        if not isinstance(item, dict) or set(item) != {"item_id", "question", "artifact_ids", "mandatory"}:
            issues.append({"code": "INVALID_REVIEW_ITEM", "message": "Each review item must contain exactly item_id, question, artifact_ids, and mandatory."})
            continue
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            issues.append({"code": "INVALID_REVIEW_ITEM_ID", "message": "Review item item_id must be non-empty."})
        else:
            item_ids.append(item_id)
        if not isinstance(item.get("question"), str) or not item["question"].strip():
            issues.append({"code": "INVALID_REVIEW_QUESTION", "message": "Review item question must be non-empty."})
        if type(item.get("mandatory")) is not bool:
            issues.append({"code": "INVALID_REVIEW_MANDATORY", "message": "Review item mandatory must be boolean."})
        refs = item.get("artifact_ids")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(value, str) or not value.strip() for value in refs)
                or len(refs) != len(set(refs))):
            issues.append({"code": "INVALID_REVIEW_REFERENCES", "message": "Review item artifact_ids must be a non-empty unique string array."})
        elif not set(refs).issubset(supplied_ids):
            issues.append({"code": "UNBOUND_REVIEW_REFERENCE", "message": "Review item references an artifact not bound in the packet."})
    if len(item_ids) != len(set(item_ids)):
        issues.append({"code": "DUPLICATE_REVIEW_ITEM_ID", "message": "review_items contains duplicate item IDs."})
    for name in ("unresolved_questions", "preparation_notes"):
        if name == "unresolved_questions" and name not in packet:
            issues.append({"code": "MISSING_UNRESOLVED_QUESTIONS", "message": "unresolved_questions is required by the review packet contract."})
        elif name in packet and (
            not isinstance(packet[name], list)
            or any(not isinstance(value, str) for value in packet[name])
        ):
            issues.append({"code": "INVALID_" + name.upper(), "message": name + " must be an array of strings."})

    return {
        "schema_version": "1.0", "contract": "RUN_REVIEW_PACKET",
        "valid": not issues, "run_id": manifest["run_id"],
        "project_id": manifest["project_id"], "stage_id": stage_id,
        "run_root": str(root.resolve(strict=True)),
        "record": {"path": str(record_file), "sha256": _sha256(record_file)},
        "checked_artifact_count": len(supplied_ids),
        "validation_report_path": str(report_file), "errors": issues,
        "virtual_query_evidence": vq_evidence,
        "interpretation": "A valid packet confirms review materials and provenance only; it is not a human decision or gate approval.",
    }


def _validate_worker_result(
    result: Mapping[str, Any], allowed_input_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Compatibility wrapper around the shared Worker Result contract."""
    return validate_worker_result_payload(result, allowed_input_ids)


def _promotion_decision(dispositions: list[str]) -> str:
    accepted = any(item in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"} for item in dispositions)
    changed = "ACCEPT_WITH_CHANGES" in dispositions
    deferred = "DEFER" in dispositions
    if accepted and changed:
        return "PROMOTE_WITH_CHANGES"
    if accepted:
        return "PROMOTE_ACCEPTED_ONLY"
    if deferred:
        return "DEFER"
    return "DO_NOT_PROMOTE"


def validate_reviewed_findings_files(
    record_path: Path, manifest_path: Path, report_path: Path,
) -> dict[str, Any]:
    root, manifest, _plan, events, artifacts, stages, run_report = _run_context(manifest_path)
    # Review is a prediction consumer. Use the shared phase-aware resolver and
    # reject PENDING/FAILED_OR_INVALID with a concrete, structured error. Never
    # infer NOT_APPLICABLE from a missing prediction file.
    vq_evidence: dict[str, Any] | None = None
    if is_full_analysis_plan(_plan):
        vq_state = require_vq_ready(root, _plan, events, _PROMOTION_STAGE, "consumer")
        vq_evidence = build_vq_evidence(root, _plan, events, vq_state, "consumer")
    record_file = record_path.expanduser()
    record = _read_json(record_file, "Reviewed findings record")
    stage = stages.get(_PROMOTION_STAGE)
    if stage is None or stage.get("executor") != "manual":
        raise ValueError("The active Run Plan must declare human_review_and_promotion as a manual stage.")
    latest_stage_event = _latest_stage_events(events).get(_PROMOTION_STAGE)
    if latest_stage_event is None or latest_stage_event.get("status") != "RUNNING":
        raise ValueError("Human promotion stage must be recorded RUNNING before validation.")
    actual_record, report_file = _check_record_and_report_paths(
        record_file, report_path, root, stage, "reviewed_findings", "reviewed_findings_validation",
    )
    issues: list[dict[str, str]] = []
    allowed = {
        "schema_version", "run_id", "project_id", "reviewer", "reviewed_at",
        "worker_output", "reviewed_artifacts", "findings", "promotion_decision",
        "overall_rationale",
    }
    for key in sorted(set(record) - allowed):
        issues.append({"code": "UNKNOWN_PROPERTY", "message": "Unknown reviewed findings property: " + key})
    if record.get("schema_version") != "1.0":
        issues.append({"code": "SCHEMA_VERSION", "message": "schema_version must be 1.0."})
    if record.get("run_id") != manifest.get("run_id"):
        issues.append({"code": "RUN_ID_MISMATCH", "message": "Reviewed record run_id differs from the active Run."})
    if record.get("project_id") != manifest.get("project_id"):
        issues.append({"code": "PROJECT_ID_MISMATCH", "message": "Reviewed record project_id differs from the active Run."})
    if not isinstance(record.get("reviewer"), str) or not record["reviewer"].strip():
        issues.append({"code": "REVIEWER_REQUIRED", "message": "reviewer must be non-empty."})
    if not _aware_timestamp(record.get("reviewed_at")):
        issues.append({"code": "INVALID_TIMESTAMP", "message": "reviewed_at must be timezone-aware ISO-8601."})
    if not isinstance(record.get("overall_rationale"), str) or not record["overall_rationale"].strip():
        issues.append({"code": "OVERALL_RATIONALE_REQUIRED", "message": "overall_rationale must be non-empty."})
    operational_sources = run_report.get("source_artifacts", [])
    if not operational_sources or any(
        not isinstance(item, dict) or item.get("status") != "CURRENT"
        for item in operational_sources
    ):
        issues.append({
            "code": "OPERATIONAL_SOURCE_INTEGRITY_CHANGED",
            "message": "An operational Run source changed after initialization; provenance-only Acceptance sources are checked separately.",
        })

    # FULL_ANALYSIS Review consumes the phase-resolved VQ artifacts, not just
    # the static plan inputs. Reuse the same shared conditional input resolution
    # used by worker authorization and Run events.
    expected_inputs = set(stage.get("inputs", []))
    if is_full_analysis_plan(_plan):
        from dor.run_manager import _effective_stage_inputs
        expected_inputs = set(_effective_stage_inputs(root, manifest, _plan, dict(stage), events))
    if _WORKER_ID not in expected_inputs:
        issues.append({"code": "WORKER_INPUT_NOT_DECLARED", "message": "Promotion stage must consume worker_review_output."})
    expected_reviewed = expected_inputs - {_WORKER_ID}
    raw_reviewed = record.get("reviewed_artifacts")
    reviewed = raw_reviewed if isinstance(raw_reviewed, list) else []
    reviewed_ids: set[str] = set()
    for item in reviewed:
        if (not isinstance(item, dict) or set(item) != {"artifact_id", "path", "sha256"}):
            issues.append({"code": "INVALID_REVIEWED_ARTIFACT", "message": "Each reviewed artifact requires exactly artifact_id, path, and sha256."})
            continue
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            issues.append({"code": "INVALID_REVIEWED_ARTIFACT_ID", "message": "Reviewed artifact ID must be non-empty."})
            continue
        if artifact_id in reviewed_ids:
            issues.append({"code": "DUPLICATE_REVIEWED_ARTIFACT", "message": "Duplicate reviewed artifact: " + artifact_id})
        reviewed_ids.add(artifact_id)
        issues.extend(_binding_issues(item, artifact_id, root, artifacts, "REVIEWED_ARTIFACT"))
    for artifact_id in sorted(expected_reviewed - reviewed_ids):
        issues.append({"code": "MISSING_REVIEWED_ARTIFACT", "message": "Missing human-reviewed stage input: " + artifact_id})
    for artifact_id in sorted(reviewed_ids - expected_reviewed):
        issues.append({"code": "UNDECLARED_REVIEWED_ARTIFACT", "message": "Human record includes undeclared artifact: " + artifact_id})
    if not reviewed:
        issues.append({"code": "EMPTY_REVIEWED_ARTIFACTS", "message": "reviewed_artifacts must be non-empty."})

    worker_binding = record.get("worker_output")
    if (not isinstance(worker_binding, dict)
            or set(worker_binding) != {"artifact_id", "path", "sha256"}):
        issues.append({"code": "INVALID_WORKER_BINDING", "message": "worker_output must contain exactly artifact_id, path, and sha256."})
        worker_binding = {}
    if worker_binding.get("artifact_id") != _WORKER_ID:
        issues.append({"code": "WORKER_ID_MISMATCH", "message": "worker_output.artifact_id must be worker_review_output."})
    issues.extend(_binding_issues(worker_binding, _WORKER_ID, root, artifacts, "WORKER_OUTPUT"))

    worker_row = artifacts.get(_WORKER_ID)
    worker_stage_id = worker_row.get("producer_stage_id") if worker_row else None
    worker_stage = stages.get(worker_stage_id) if isinstance(worker_stage_id, str) else None
    if worker_stage is None or worker_stage.get("executor") != "worker":
        issues.append({"code": "INVALID_WORKER_PRODUCER", "message": "worker_review_output must come from a declared Worker stage."})
        worker_stage = {}
    latest = _latest_stage_events(events)
    worker_event = latest.get(worker_stage_id) if isinstance(worker_stage_id, str) else None
    if not worker_event or worker_event.get("status") != "SUCCEEDED":
        issues.append({"code": "WORKER_NOT_SUCCEEDED", "message": "Worker stage must have a SUCCEEDED event before promotion review."})
    elif worker_row and worker_row.get("producer_event_hash") != worker_event.get("event_hash"):
        issues.append({"code": "WORKER_EVENT_MISMATCH", "message": "Worker output does not match the latest successful Worker event."})

    worker_findings: dict[str, dict[str, Any]] = {}
    worker_result: dict[str, Any] = {}
    if worker_row and worker_row.get("status") == "CURRENT":
        try:
            worker_result = _read_json(Path(str(worker_row["path"])).expanduser(), "Worker result")
            worker_findings = _validate_worker_result(
                worker_result, set(worker_stage.get("inputs", [])) if worker_stage else set()
            )
            reported_task = worker_event.get("producer", {}).get("task_id") if worker_event else None
            if reported_task and reported_task != worker_result.get("task_id"):
                issues.append({"code": "WORKER_TASK_ID_MISMATCH", "message": "Worker result task_id differs from the task recorded in the Run event."})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append({"code": "INVALID_WORKER_RESULT", "message": str(exc)})
    else:
        issues.append({"code": "WORKER_RESULT_NOT_CURRENT", "message": "Worker result is not a current Run artifact."})

    raw_findings = record.get("findings")
    human_findings = raw_findings if isinstance(raw_findings, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for item in human_findings:
        required_fields = {"worker_finding_id", "disposition", "reviewer_rationale", "supporting_artifact_ids"}
        allowed_fields = required_fields | {"revised_finding_summary"}
        if (not isinstance(item, dict) or not required_fields.issubset(item)
                or set(item) - allowed_fields):
            issues.append({"code": "INVALID_FINDING_DISPOSITION", "message": "Finding disposition has missing or unknown properties."})
            continue
        finding_id = item.get("worker_finding_id")
        if not isinstance(finding_id, str) or not finding_id.strip() or finding_id in by_id:
            issues.append({"code": "INVALID_OR_DUPLICATE_FINDING_ID", "message": "Human finding IDs must be non-empty and unique."})
            continue
        by_id[finding_id] = item
        disposition = item.get("disposition")
        if not isinstance(disposition, str) or disposition not in _DISPOSITIONS:
            issues.append({"code": "INVALID_DISPOSITION", "message": "Unsupported disposition for " + finding_id})
        if not isinstance(item.get("reviewer_rationale"), str) or not item["reviewer_rationale"].strip():
            issues.append({"code": "MISSING_FINDING_RATIONALE", "message": "Reviewer rationale is required for " + finding_id})
        supporting = item.get("supporting_artifact_ids")
        if (not isinstance(supporting, list)
                or any(not isinstance(x, str) or not x.strip() for x in supporting)
                or len(supporting) != len(set(supporting))):
            issues.append({"code": "INVALID_SUPPORTING_ARTIFACTS", "message": "Supporting artifact IDs must be a unique string array for " + finding_id})
            supporting = []
        if not set(supporting).issubset(reviewed_ids):
            issues.append({"code": "UNREVIEWED_SUPPORTING_ARTIFACT", "message": "Finding cites an artifact not bound in reviewed_artifacts: " + finding_id})
        if disposition in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"} and not supporting:
            issues.append({"code": "ACCEPTED_WITHOUT_SUPPORT", "message": "Accepted finding requires at least one reviewed supporting artifact: " + finding_id})
        if disposition == "ACCEPT_WITH_CHANGES":
            if not isinstance(item.get("revised_finding_summary"), str) or not item["revised_finding_summary"].strip():
                issues.append({"code": "REVISED_SUMMARY_REQUIRED", "message": "ACCEPT_WITH_CHANGES requires a revised summary: " + finding_id})
        elif "revised_finding_summary" in item:
            issues.append({"code": "UNEXPECTED_REVISED_SUMMARY", "message": "revised_finding_summary is allowed only for ACCEPT_WITH_CHANGES: " + finding_id})
        if disposition == "ACCEPT_AS_IS":
            original = worker_findings.get(finding_id)
            if original and set(supporting) != set(original.get("supporting_artifact_ids", [])):
                issues.append({"code": "ACCEPT_AS_IS_SUPPORT_CHANGED", "message": "ACCEPT_AS_IS must preserve original supporting artifact IDs: " + finding_id})

    missing = sorted(set(worker_findings) - set(by_id))
    extra = sorted(set(by_id) - set(worker_findings))
    if missing:
        issues.append({"code": "MISSING_WORKER_DISPOSITIONS", "message": "Missing dispositions for Worker findings: " + ", ".join(missing)})
    if extra:
        issues.append({"code": "UNKNOWN_WORKER_FINDINGS", "message": "Unknown Worker finding IDs: " + ", ".join(extra)})

    dispositions = [
        item.get("disposition") for item in human_findings
        if isinstance(item, dict) and item.get("disposition") in _DISPOSITIONS
    ]
    expected_decision = _promotion_decision(dispositions)
    supplied_decision = record.get("promotion_decision")
    if not isinstance(supplied_decision, str) or supplied_decision not in _DECISIONS or supplied_decision != expected_decision:
        issues.append({"code": "PROMOTION_DECISION_MISMATCH", "message": "promotion_decision must equal " + expected_decision + "."})
    if isinstance(worker_result.get("status"), str) and worker_result["status"] in {"blocked", "failed"} and any(
        item.get("disposition") in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"}
        for item in human_findings if isinstance(item, dict)
    ):
        issues.append({"code": "FAILED_WORKER_PROMOTED", "message": "Blocked or failed Worker results cannot have accepted findings."})

    return {
        "schema_version": "1.0", "contract": "REVIEWED_WORKER_FINDINGS",
        "valid": not issues, "run_id": manifest["run_id"],
        "project_id": manifest["project_id"], "stage_id": _PROMOTION_STAGE,
        "run_root": str(root.resolve(strict=True)),
        "record": {"path": str(actual_record), "sha256": _sha256(actual_record)},
        "worker_output": {
            "artifact_id": _WORKER_ID,
            "path": worker_binding.get("path"),
            "sha256": worker_binding.get("sha256"),
            "worker_status": worker_result.get("status"),
            "finding_count": len(worker_findings),
        },
        "reviewed_artifact_count": len(reviewed_ids),
        "promotion_decision": supplied_decision,
        "expected_promotion_decision": expected_decision,
        "validation_report_path": str(report_file),
        "errors": issues,
        "virtual_query_evidence": vq_evidence,
        "interpretation": "A valid record confirms human dispositions and provenance only; it does not create a G0-G4 approval or alter analysis artifacts.",
    }
