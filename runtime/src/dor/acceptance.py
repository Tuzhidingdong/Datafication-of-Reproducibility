"""Validation of V1.0 controlled scientific acceptance records.

This validator checks the record's fixed stage protocol, decision semantics, run
binding, and the existence/content hashes of every cited source/evidence file.
It does not judge scientific correctness; human review remains mandatory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STAGE_ORDER = (
    "source_selection",
    "source_integrity",
    "extraction_review",
    "semantic_mapping",
    "canonical_reconciliation",
    "cohort_feasibility",
    "modeling_validation",
    "publication_handoff",
)
STAGE_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
FINAL_DECISIONS = {"NOT_ASSESSED", "PASS", "CONDITIONAL_PASS", "FAIL"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _resolve_file(raw_path: str, record_dir: Path) -> Path:
    path = Path(raw_path).expanduser()
    return (path if path.is_absolute() else record_dir / path).resolve(strict=False)


def validate_acceptance_record(record_path: Path, run_manifest_path: Path) -> dict[str, Any]:
    record_path = record_path.expanduser().resolve()
    run_manifest_path = run_manifest_path.expanduser().resolve()
    record = _read_json(record_path, "Acceptance record")
    manifest = _read_json(run_manifest_path, "Run manifest")
    issues: list[dict[str, str]] = []
    source_checks: list[dict[str, Any]] = []
    evidence_checks: list[dict[str, Any]] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    if record.get("schema_version") != "1.0":
        issue("UNSUPPORTED_SCHEMA_VERSION", "schema_version must be 1.0.")
    if not isinstance(record.get("acceptance_id"), str) or not record["acceptance_id"].strip():
        issue("MISSING_ACCEPTANCE_ID", "acceptance_id must be a non-empty string.")
    if record.get("run_id") != manifest.get("run_id"):
        issue("RUN_ID_MISMATCH", "Acceptance record run_id does not match the supplied Run Manifest.")
    if record.get("project_id") != manifest.get("project_id"):
        issue("PROJECT_ID_MISMATCH", "Acceptance record project_id does not match the supplied Run Manifest.")

    try:
        manifest_hash = _sha256(run_manifest_path)
    except OSError as exc:
        manifest_hash = None
        issue("RUN_MANIFEST_UNREADABLE", str(exc))
    if manifest_hash and record.get("run_manifest_sha256") != manifest_hash:
        issue("RUN_MANIFEST_HASH_MISMATCH", "run_manifest_sha256 does not match the supplied Run Manifest.")

    scope = record.get("scope")
    snapshot = record.get("source_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
        issue("INVALID_SOURCE_SNAPSHOT", "source_snapshot must be an object.")
    study_count = snapshot.get("study_count")
    if not isinstance(study_count, int) or isinstance(study_count, bool) or study_count < 1:
        issue("INVALID_STUDY_COUNT", "source_snapshot.study_count must be a positive integer.")
    if scope == "CONTROLLED_SINGLE_STUDY" and study_count != 1:
        issue("SINGLE_STUDY_SCOPE_MISMATCH", "CONTROLLED_SINGLE_STUDY requires study_count=1.")
    if scope == "MULTI_STUDY_PILOT" and (not isinstance(study_count, int) or isinstance(study_count, bool) or study_count < 2):
        issue("MULTI_STUDY_SCOPE_MISMATCH", "MULTI_STUDY_PILOT requires at least two distinct Studies.")
    if scope not in {"CONTROLLED_SINGLE_STUDY", "MULTI_STUDY_PILOT"}:
        issue("INVALID_SCOPE", "scope must be CONTROLLED_SINGLE_STUDY or MULTI_STUDY_PILOT.")

    source_items = snapshot.get("artifacts", [])
    if not isinstance(source_items, list) or not source_items:
        issue("MISSING_SOURCE_ARTIFACTS", "source_snapshot.artifacts must be a non-empty array.")
        source_items = []
    source_ids: set[str] = set()
    source_roles: set[str] = set()
    for item in source_items:
        if not isinstance(item, dict):
            issue("INVALID_SOURCE_ARTIFACT", "Every source artifact must be an object.")
            continue
        source_id, role, raw_path, expected = (
            item.get("source_id"), item.get("role"), item.get("path"), item.get("sha256")
        )
        if not all(isinstance(value, str) and value.strip() for value in (source_id, role, raw_path, expected)):
            issue("INCOMPLETE_SOURCE_ARTIFACT", "Source artifact requires source_id, role, path, and sha256.")
            continue
        if source_id in source_ids:
            issue("DUPLICATE_SOURCE_ID", f"Duplicate source_id: {source_id}")
        source_ids.add(source_id)
        source_roles.add(role)
        path = _resolve_file(raw_path, record_path.parent)
        actual = None
        try:
            actual = _sha256(path)
        except OSError:
            issue("SOURCE_FILE_MISSING", f"Source file is missing or unreadable: {path}")
        if actual is not None and actual != expected:
            issue("SOURCE_HASH_MISMATCH", f"Source file hash changed: {path}")
        source_checks.append({"source_id": source_id, "path": str(path),
                              "expected_sha256": expected, "actual_sha256": actual,
                              "status": "CURRENT" if actual == expected else "MISSING_OR_CHANGED"})
    if scope == "CONTROLLED_SINGLE_STUDY":
        for required_role in ("PRIMARY_PAPER", "SUPPLEMENTARY_INFORMATION"):
            if required_role not in source_roles:
                issue("REQUIRED_SOURCE_ROLE_MISSING", f"Single-study pilot requires a {required_role} source.")

    stages = record.get("stages")
    if not isinstance(stages, list):
        stages = []
        issue("INVALID_STAGES", "stages must be an array.")
    stage_ids = [item.get("stage_id") if isinstance(item, dict) else None for item in stages]
    if tuple(stage_ids) != STAGE_ORDER:
        issue("STAGE_ORDER_MISMATCH", "Stages must appear exactly once in the fixed V1.0 order.")
    stage_statuses: dict[str, str] = {}
    for item in stages:
        if not isinstance(item, dict):
            issue("INVALID_STAGE", "Every stage must be an object.")
            continue
        stage_id, status = item.get("stage_id"), item.get("status")
        if status not in STAGE_STATUSES:
            issue("INVALID_STAGE_STATUS", f"Invalid status for stage {stage_id}.")
            continue
        if stage_id in stage_statuses:
            issue("DUPLICATE_STAGE", f"Duplicate stage: {stage_id}")
        stage_statuses[stage_id] = status
        if status == "PASS" and not item.get("evidence"):
            issue("PASS_WITHOUT_EVIDENCE", f"Stage {stage_id} is PASS but has no evidence.")
        if status == "NOT_APPLICABLE" and not (
            isinstance(item.get("not_applicable_reason"), str) and item["not_applicable_reason"].strip()
        ):
            issue("NA_WITHOUT_REASON", f"Stage {stage_id} is NOT_APPLICABLE without a reason.")
        if status in {"FAIL", "BLOCKED"} and not (
            isinstance(item.get("blocker_reason"), str) and item["blocker_reason"].strip()
        ):
            issue("BLOCKED_WITHOUT_REASON", f"Stage {stage_id} is {status} without a blocker_reason.")
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            issue("INVALID_EVIDENCE_LIST", f"Evidence for {stage_id} must be an array.")
            continue
        for artifact in evidence:
            if not isinstance(artifact, dict):
                issue("INVALID_EVIDENCE_ARTIFACT", f"Evidence artifact in {stage_id} must be an object.")
                continue
            artifact_id, raw_path, expected = (
                artifact.get("artifact_id"), artifact.get("path"), artifact.get("sha256")
            )
            if not all(isinstance(value, str) and value.strip() for value in (artifact_id, raw_path, expected)):
                issue("INCOMPLETE_EVIDENCE_ARTIFACT", f"Evidence in {stage_id} requires artifact_id, path, and sha256.")
                continue
            path = _resolve_file(raw_path, record_path.parent)
            actual = None
            try:
                actual = _sha256(path)
            except OSError:
                issue("EVIDENCE_FILE_MISSING", f"Evidence file is missing or unreadable: {path}")
            if actual is not None and actual != expected:
                issue("EVIDENCE_HASH_MISMATCH", f"Evidence hash changed: {path}")
            evidence_checks.append({"stage_id": stage_id, "artifact_id": artifact_id,
                                    "path": str(path), "expected_sha256": expected,
                                    "actual_sha256": actual,
                                    "status": "CURRENT" if actual == expected else "MISSING_OR_CHANGED"})

    if scope == "CONTROLLED_SINGLE_STUDY" and stage_statuses.get("modeling_validation") == "PASS":
        issue("SINGLE_STUDY_MODEL_VALIDATION_INVALID", "A single Study cannot PASS cross-Study modelling validation.")

    assessment = record.get("final_assessment")
    if not isinstance(assessment, dict):
        assessment = {}
        issue("INVALID_FINAL_ASSESSMENT", "final_assessment must be an object.")
    decision = assessment.get("decision")
    if decision not in FINAL_DECISIONS:
        issue("INVALID_FINAL_DECISION", "final_assessment.decision is invalid.")
    statuses = [stage_statuses.get(stage_id) for stage_id in STAGE_ORDER]
    if decision == "PASS" and statuses != ["PASS"] * len(STAGE_ORDER):
        issue("FULL_PASS_INCOMPLETE", "PASS requires every fixed acceptance stage to be PASS.")
    if decision == "CONDITIONAL_PASS":
        if not any(status == "NOT_APPLICABLE" for status in statuses):
            issue("CONDITIONAL_PASS_WITHOUT_NA", "CONDITIONAL_PASS requires at least one NOT_APPLICABLE stage.")
        if any(status not in {"PASS", "NOT_APPLICABLE"} for status in statuses):
            issue("CONDITIONAL_PASS_HAS_OPEN_STAGE", "CONDITIONAL_PASS permits only PASS or NOT_APPLICABLE stages.")
        if assessment.get("blocking_issue_ids"):
            issue("CONDITIONAL_PASS_HAS_BLOCKERS", "CONDITIONAL_PASS cannot retain blocking_issue_ids.")
    if decision == "FAIL" and not any(status == "FAIL" for status in statuses):
        issue("FAIL_WITHOUT_FAILED_STAGE", "FAIL requires at least one stage marked FAIL.")

    return {
        "valid": not issues,
        "acceptance_id": record.get("acceptance_id"),
        "project_id": record.get("project_id"),
        "run_id": record.get("run_id"),
        "scope": scope,
        "final_decision": decision,
        "source_checks": source_checks,
        "evidence_checks": evidence_checks,
        "issue_count": len(issues),
        "issues": issues,
        "scientific_review_required": True,
        "interpretation": "Structural, run-binding, and file-integrity checks only; this report does not establish scientific correctness.",
    }
