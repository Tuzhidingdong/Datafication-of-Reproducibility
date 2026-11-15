"""Validation of V1.0 controlled scientific acceptance records.

This validator checks the record's fixed stage protocol, decision semantics, run
binding, and the existence/content hashes of every cited source/evidence file.
It does not judge scientific correctness; human review remains mandatory.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from dor.acceptance_ledger import validate_acceptance_ledger
from dor.run_manager import _latest_stage_events, _manifest_context, verify_run
from dor.stage_contracts import validate_stage_evidence

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



def _json_pointer_get(document: Any, pointer: str) -> tuple[bool, Any]:
    """Resolve an RFC 6901 JSON Pointer without treating missing as null."""
    if pointer == "":
        return True, document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False, None
    current = document
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            return False, None
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _evaluate_assertion(operator: str, actual: Any, expected: Any = None) -> tuple[bool, str]:
    if operator == "exists":
        return True, "JSON Pointer resolves."
    if operator == "equals":
        ok = type(actual) is type(expected) and actual == expected
        return ok, "Value equals expected value." if ok else "Value differs from expected value."
    if operator == "not_equals":
        ok = not (type(actual) is type(expected) and actual == expected)
        return ok, "Value differs from forbidden value." if ok else "Value equals forbidden value."
    if operator in {"gte", "lte"}:
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return False, "Numeric comparison requires numeric actual and expected values."
        ok = actual >= expected if operator == "gte" else actual <= expected
        return ok, "Numeric bound satisfied." if ok else "Numeric bound violated."
    if operator == "non_empty":
        ok = isinstance(actual, (str, list, dict)) and len(actual) > 0
        return ok, "Value is non-empty." if ok else "Value is empty or not a string/array/object."
    if operator == "unique":
        if not isinstance(actual, list):
            return False, "Unique check requires an array."
        encoded = [json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for value in actual]
        ok = len(encoded) == len(set(encoded))
        return ok, "Array values are unique." if ok else "Array contains duplicate values."
    if operator == "contains":
        try:
            ok = expected in actual
        except TypeError:
            ok = False
        return ok, "Expected value is contained." if ok else "Expected value is not contained."
    return False, f"Unsupported assertion operator: {operator}."


def _validate_single_study_na_evidence(
    stage_id: str,
    evidence: list[dict[str, Any]],
    *,
    run_id: str,
    project_id: str,
    study_ids: list[str],
    expected_reason: Any,
    issue,
) -> None:
    """Require both single-Study NA stages to bind the same exact applicability review."""
    by_type: dict[str, dict[str, Any]] = {}
    for item in evidence:
        artifact_type = item.get("artifact_type")
        if artifact_type in by_type:
            issue("SINGLE_STUDY_NA_EVIDENCE_DUPLICATE",
                  f"{stage_id} contains duplicate {artifact_type} evidence.")
            continue
        if isinstance(artifact_type, str):
            by_type[artifact_type] = item

    required = {
        "single_study_applicability_record",
        "single_study_applicability_validation",
        "canonical_bundle",
        "modeling_task",
    }
    missing = sorted(required - set(by_type))
    if missing:
        issue("SINGLE_STUDY_NA_EVIDENCE_MISSING",
              f"{stage_id} requires the exact applicability record/validation, Canonical Bundle, and modeling task; missing: "
              + ", ".join(missing) + ".")
        return

    record_item = by_type["single_study_applicability_record"]
    validation_item = by_type["single_study_applicability_validation"]
    bundle_item = by_type["canonical_bundle"]
    task_item = by_type["modeling_task"]
    record_payload = record_item.get("payload")
    validation_payload = validation_item.get("payload")
    if not all(isinstance(value, dict) for value in (record_payload, validation_payload)):
        issue("SINGLE_STUDY_NA_EVIDENCE_UNREADABLE",
              f"{stage_id} applicability record and validation must be readable JSON objects.")
        return

    if record_payload.get("schema_version") != "1.0":
        issue("SINGLE_STUDY_NA_RECORD_SCHEMA_INVALID", "Single-study applicability record schema_version must be 1.0.")
    if (record_payload.get("run_id") != run_id or record_payload.get("project_id") != project_id
            or record_payload.get("scope") != "CONTROLLED_SINGLE_STUDY"
            or record_payload.get("applicability_status") != "NOT_APPLICABLE"):
        issue("SINGLE_STUDY_NA_RECORD_IDENTITY_INVALID",
              "Single-study applicability record must match this Run/Project and declare CONTROLLED_SINGLE_STUDY / NOT_APPLICABLE.")
    if record_payload.get("study_ids") != study_ids or record_payload.get("study_count") != 1:
        issue("SINGLE_STUDY_NA_STUDY_SCOPE_MISMATCH",
              "Single-study applicability record must bind the exact one Study in the Acceptance source snapshot.")
    if record_payload.get("canonical_bundle_sha256") != bundle_item.get("sha256"):
        issue("SINGLE_STUDY_NA_BUNDLE_HASH_MISMATCH",
              "Single-study applicability record does not bind this Acceptance evidence's exact Canonical Bundle.")
    if record_payload.get("modeling_task_sha256") != task_item.get("sha256"):
        issue("SINGLE_STUDY_NA_TASK_HASH_MISMATCH",
              "Single-study applicability record does not bind this Acceptance evidence's exact modeling task.")
    if validation_payload.get("valid") is not True or validation_payload.get("applicability_status") != "NOT_APPLICABLE":
        issue("SINGLE_STUDY_NA_VALIDATION_FAILED",
              "Single-study applicability validation must be valid and declare NOT_APPLICABLE.")
    if (validation_payload.get("run_id") != run_id
            or validation_payload.get("project_id") != project_id
            or validation_payload.get("applicability_record_sha256") != record_item.get("sha256")
            or validation_payload.get("canonical_bundle_sha256") != bundle_item.get("sha256")
            or validation_payload.get("modeling_task_sha256") != task_item.get("sha256")):
        issue("SINGLE_STUDY_NA_VALIDATION_BINDING_MISMATCH",
              "Single-study applicability validation must bind the exact Run, Project, record, Bundle, and task.")

    status_key, reason_key = (
        ("cohort_feasibility_status", "cohort_feasibility_reason")
        if stage_id == "cohort_feasibility"
        else ("modeling_validation_status", "modeling_validation_reason")
    )
    if record_payload.get(status_key) != "NOT_APPLICABLE":
        issue("SINGLE_STUDY_NA_STAGE_STATUS_MISMATCH",
              f"Applicability record {status_key} must be NOT_APPLICABLE.")
    reason = record_payload.get(reason_key)
    if not isinstance(reason, str) or not reason.strip():
        issue("SINGLE_STUDY_NA_REASON_MISSING",
              f"Applicability record {reason_key} must contain a scientific reason.")
    elif reason != expected_reason:
        issue("SINGLE_STUDY_NA_ACCEPTANCE_REASON_MISMATCH",
              f"{stage_id} not_applicable_reason must match the exact reason in the bound applicability record.")


def validate_acceptance_record(
    record_path: Path, run_manifest_path: Path, ledger_path: Path | None = None,
) -> dict[str, Any]:
    record_path = record_path.expanduser()
    if record_path.is_symlink():
        raise ValueError("Acceptance record must not be a symlink.")
    record_path = record_path.resolve()
    run_manifest_path = run_manifest_path.expanduser().resolve()
    record = _read_json(record_path, "Acceptance record")
    manifest = _read_json(run_manifest_path, "Run manifest")
    if ledger_path is None:
        ledger_path = record_path.with_name(record_path.stem + "_acceptance_events.jsonl")
    ledger_report = validate_acceptance_ledger(record_path, ledger_path)
    issues: list[dict[str, str]] = []
    source_checks: list[dict[str, Any]] = []
    evidence_checks: list[dict[str, Any]] = []
    assertion_checks: list[dict[str, Any]] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    if not ledger_report.get("valid"):
        for ledger_issue in ledger_report.get("issues", []):
            issue(ledger_issue.get("code", "ACCEPTANCE_LEDGER_INVALID"),
                  ledger_issue.get("message", "Acceptance revision history is invalid."))

    run_root = run_manifest_path.parent
    run_plan: dict[str, Any] = {}
    run_events: list[dict[str, Any]] = []
    run_report: dict[str, Any] = {}
    run_artifact_states: dict[str, dict[str, Any]] = {}
    try:
        run_root, manifest, run_plan, run_events = _manifest_context(run_manifest_path)
        run_report = verify_run(run_manifest_path)
        if run_report.get("source_integrity") != "CURRENT":
            issue("RUN_SOURCE_INTEGRITY_CHANGED", "At least one Run Manager source artifact changed after run initialization.")
        artifact_manifest = run_report.get("artifact_manifest")
        artifact_rows = artifact_manifest.get("artifacts") if isinstance(artifact_manifest, dict) else None
        if not isinstance(artifact_rows, list):
            issue("RUN_ARTIFACT_MANIFEST_MISSING", "Run Manager did not return a valid regenerated artifact manifest.")
        else:
            for row in artifact_rows:
                if not isinstance(row, dict) or not isinstance(row.get("artifact_id"), str):
                    issue("RUN_ARTIFACT_MANIFEST_ENTRY_INVALID", "Run artifact manifest contains an invalid artifact entry.")
                    continue
                artifact_id = row["artifact_id"]
                if artifact_id in run_artifact_states:
                    issue("RUN_ARTIFACT_MANIFEST_DUPLICATE_ID", f"Run artifact manifest contains duplicate artifact_id {artifact_id}.")
                    continue
                run_artifact_states[artifact_id] = row
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issue("RUN_INTEGRITY_INVALID", f"Run Manager manifest/plan/event chain is invalid: {exc}")

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
    manifest_sources = {
        item.get("artifact_id"): item
        for item in manifest.get("source_artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    }
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
        bound_source = manifest_sources.get(source_id)
        if bound_source is None:
            issue("SOURCE_NOT_DECLARED_IN_RUN", f"Source {source_id} is not declared in the Run Plan/Manifest.")
        else:
            bound_path = Path(bound_source.get("path", "")).expanduser().resolve(strict=False)
            if path != bound_path:
                issue("SOURCE_PATH_NOT_BOUND_TO_RUN", f"Source {source_id} path differs from the Run Manifest.")
            if expected != bound_source.get("sha256"):
                issue("SOURCE_HASH_NOT_BOUND_TO_RUN", f"Source {source_id} SHA-256 differs from the Run Manifest snapshot.")
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
    if source_ids != set(manifest_sources):
        issue("SOURCE_SET_DIFFERS_FROM_RUN", "Acceptance source_snapshot must include exactly the source artifacts declared by the Run Manifest.")

    study_ids = snapshot.get("study_ids", [])
    if (not isinstance(study_ids, list) or not study_ids
            or any(not isinstance(value, str) or not value.strip() for value in study_ids)
            or len(study_ids) != len(set(study_ids))):
        issue("INVALID_STUDY_IDS", "source_snapshot.study_ids must contain unique, non-empty explicit Study IDs.")
    elif study_count != len(study_ids):
        issue("STUDY_ID_COUNT_MISMATCH", "study_count must equal the number of explicit unique study_ids.")

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
    evidence_catalog: dict[str, dict[str, Any]] = {}
    for source in manifest.get("source_artifacts", []):
        evidence_catalog[source["artifact_id"]] = {
            "path": str(Path(source["path"]).expanduser().resolve(strict=False)),
            "sha256": source["sha256"],
        }
    if manifest_hash:
        evidence_catalog["run_manifest"] = {
            "path": str(run_manifest_path),
            "sha256": manifest_hash,
        }
    latest_events = _latest_stage_events(run_events) if run_events else {}
    for event in latest_events.values():
        if event.get("status") == "SUCCEEDED":
            for output in event.get("output_artifacts", []):
                evidence_catalog[output.get("artifact_id")] = {
                    "path": output.get("path"), "sha256": output.get("sha256"),
                }

    stage_statuses: dict[str, str] = {}
    accepted_stage_payloads: dict[str, dict[str, Any]] = {}
    accepted_gate_evidence: dict[str, dict[str, str]] = {}
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
        typed_evidence: list[dict[str, Any]] = []
        for artifact in evidence:
            if not isinstance(artifact, dict):
                issue("INVALID_EVIDENCE_ARTIFACT", f"Evidence artifact in {stage_id} must be an object.")
                continue
            artifact_id, raw_path, expected, artifact_type = (
                artifact.get("artifact_id"), artifact.get("path"), artifact.get("sha256"), artifact.get("artifact_type")
            )
            if not all(isinstance(value, str) and value.strip() for value in (artifact_id, raw_path, expected)):
                issue("INCOMPLETE_EVIDENCE_ARTIFACT", f"Evidence in {stage_id} requires artifact_id, path, and sha256.")
                continue
            if not isinstance(artifact_type, str) or not artifact_type.strip():
                issue("EVIDENCE_TYPE_MISSING", f"Evidence {artifact_id} in {stage_id} requires artifact_type.")
            path = _resolve_file(raw_path, record_path.parent)
            bound_evidence = evidence_catalog.get(artifact_id)
            if bound_evidence is None:
                issue("EVIDENCE_NOT_A_COMPLETED_RUN_ARTIFACT", f"Evidence {artifact_id} is not a source or successfully completed Run artifact.")
            else:
                bound_path = Path(bound_evidence.get("path", "")).expanduser().resolve(strict=False)
                if path != bound_path:
                    issue("EVIDENCE_PATH_NOT_BOUND_TO_RUN", f"Evidence {artifact_id} path differs from its Run artifact.")
                if expected != bound_evidence.get("sha256"):
                    issue("EVIDENCE_HASH_NOT_BOUND_TO_RUN", f"Evidence {artifact_id} SHA-256 differs from its Run event/source snapshot.")
            run_artifact_is_current = True
            if artifact_id != "run_manifest":
                run_artifact = run_artifact_states.get(artifact_id)
                if run_artifact is None:
                    run_artifact_is_current = False
                    issue("EVIDENCE_RUN_ARTIFACT_STATE_MISSING", f"Evidence {artifact_id} is absent from the regenerated Run artifact manifest.")
                elif run_artifact.get("status") != "CURRENT":
                    run_artifact_is_current = False
                    producer = run_artifact.get("producer_stage_id")
                    issue("EVIDENCE_RUN_ARTIFACT_NOT_CURRENT",
                          f"Evidence {artifact_id} is not reusable in the current Run state (status={run_artifact.get('status')}, producer_stage={producer}). Rebuild invalidated upstream/downstream stages before acceptance.")
            actual = None
            try:
                actual = _sha256(path)
            except OSError:
                issue("EVIDENCE_FILE_MISSING", f"Evidence file is missing or unreadable: {path}")
            if actual is not None and actual != expected:
                issue("EVIDENCE_HASH_MISMATCH", f"Evidence hash changed: {path}")
            evidence_checks.append({"stage_id": stage_id, "artifact_id": artifact_id,
                                    "artifact_type": artifact_type,
                                    "path": str(path), "expected_sha256": expected,
                                    "actual_sha256": actual,
                                    "status": "CURRENT" if actual == expected else "MISSING_OR_CHANGED"})
            if isinstance(artifact_type, str) and artifact_type.strip() and actual == expected and run_artifact_is_current:
                if artifact_type == "modeling_cohort_csv":
                    typed_evidence.append({**artifact, "path": str(path), "payload": None})
                else:
                    try:
                        payload = _read_json(path, f"Stage evidence {artifact_id}")
                        typed_evidence.append({**artifact, "path": str(path), "payload": payload})
                    except (OSError, ValueError, TypeError) as exc:
                        issue("STAGE_EVIDENCE_JSON_INVALID", f"Typed evidence {artifact_id} must be a readable JSON object: {exc}")

        if (status == "NOT_APPLICABLE"
                and scope == "CONTROLLED_SINGLE_STUDY"
                and stage_id in {"cohort_feasibility", "modeling_validation"}):
            _validate_single_study_na_evidence(
                stage_id, typed_evidence,
                run_id=str(manifest.get("run_id", "")),
                project_id=str(manifest.get("project_id", "")),
                study_ids=snapshot.get("study_ids", []) if isinstance(snapshot.get("study_ids"), list) else [],
                expected_reason=item.get("not_applicable_reason"),
                issue=issue,
            )

        if status == "PASS":
            contract_issues = validate_stage_evidence(
                stage_id, typed_evidence, run_id=str(manifest.get("run_id", "")),
                project_id=str(manifest.get("project_id", "")),
                study_ids=set(study_ids) if isinstance(study_ids, list) else set(),
                source_snapshot=snapshot.get("artifacts", []) if isinstance(snapshot.get("artifacts"), list) else [],
                prior_payloads=accepted_stage_payloads,
            )
            for contract_issue in contract_issues:
                issue(contract_issue["code"], contract_issue["message"])
            for typed_item in typed_evidence:
                accepted_stage_payloads[typed_item["artifact_type"]] = typed_item
                identity = {
                    "artifact_id": typed_item["artifact_id"],
                    "path": str(Path(typed_item["path"]).resolve(strict=False)),
                    "sha256": typed_item["sha256"],
                }
                prior_identity = accepted_gate_evidence.get(identity["artifact_id"])
                if prior_identity is not None and prior_identity != identity:
                    issue("ACCEPTANCE_EVIDENCE_IDENTITY_CONFLICT",
                          f"Accepted evidence artifact_id {identity['artifact_id']} has conflicting path/hash identities across stages.")
                else:
                    accepted_gate_evidence[identity["artifact_id"]] = identity

        checks = item.get("checks", [])
        if not isinstance(checks, list):
            issue("INVALID_STAGE_CHECKS", f"Checks for {stage_id} must be an array.")
            checks = []
        if status == "PASS" and not checks:
            issue("PASS_WITHOUT_DETERMINISTIC_CHECKS", f"Stage {stage_id} is PASS but has no deterministic content assertions.")
        seen_check_ids: set[str] = set()
        stage_evidence_ids = {
            entry.get("artifact_id") for entry in evidence
            if isinstance(entry, dict) and isinstance(entry.get("artifact_id"), str)
        }
        for check in checks:
            if not isinstance(check, dict):
                issue("INVALID_STAGE_CHECK", f"Every check in {stage_id} must be an object.")
                continue
            check_id = check.get("check_id")
            artifact_id = check.get("artifact_id")
            pointer = check.get("json_pointer")
            operator = check.get("operator")
            if not isinstance(check_id, str) or not check_id.strip():
                issue("INVALID_CHECK_ID", f"Check in {stage_id} requires a non-empty check_id.")
                continue
            if check_id in seen_check_ids:
                issue("DUPLICATE_CHECK_ID", f"Duplicate check_id {check_id} in {stage_id}.")
                continue
            seen_check_ids.add(check_id)
            if artifact_id not in stage_evidence_ids:
                issue("CHECK_ARTIFACT_NOT_STAGE_EVIDENCE", f"Check {check_id} must reference evidence listed on stage {stage_id}.")
                continue
            if not isinstance(pointer, str) or (pointer != "" and not pointer.startswith("/")):
                issue("INVALID_CHECK_JSON_POINTER", f"Check {check_id} requires an RFC 6901 JSON Pointer.")
                continue
            expected_required = operator in {"equals", "not_equals", "gte", "lte", "contains"}
            if operator not in {"exists", "equals", "not_equals", "gte", "lte", "non_empty", "unique", "contains"}:
                issue("INVALID_CHECK_OPERATOR", f"Check {check_id} uses an unsupported operator.")
                continue
            if expected_required and "expected" not in check:
                issue("CHECK_EXPECTED_VALUE_MISSING", f"Check {check_id} requires expected.")
                continue
            bound = evidence_catalog.get(artifact_id)
            check_result = {"stage_id": stage_id, "check_id": check_id, "artifact_id": artifact_id,
                            "json_pointer": pointer, "operator": operator, "passed": False}
            if bound is None:
                check_result["message"] = "Evidence is not bound to a completed Run artifact."
                issue("CHECK_ARTIFACT_NOT_RUN_BOUND", f"Check {check_id} references evidence not bound to this Run.")
                assertion_checks.append(check_result)
                continue
            try:
                payload = _read_json(Path(bound["path"]), f"Evidence JSON for check {check_id}")
                found, actual_value = _json_pointer_get(payload, pointer)
                if not found:
                    check_result["message"] = "JSON Pointer does not resolve."
                    issue("CHECK_POINTER_NOT_FOUND", f"JSON Pointer for check {check_id} does not resolve.")
                else:
                    passed, message = _evaluate_assertion(operator, actual_value, check.get("expected"))
                    check_result.update({"passed": passed, "message": message})
                    if "expected" in check:
                        check_result["expected"] = check["expected"]
                    if passed:
                        check_result["actual"] = actual_value
                    else:
                        issue("CONTENT_ASSERTION_FAILED", f"Deterministic content assertion failed: {check_id}.")
            except (OSError, ValueError, TypeError) as exc:
                check_result["message"] = str(exc)
                issue("CHECK_EVIDENCE_NOT_VALID_JSON", f"Check {check_id} evidence must be readable JSON: {exc}")
            assertion_checks.append(check_result)

    if scope == "CONTROLLED_SINGLE_STUDY" and stage_statuses.get("modeling_validation") == "PASS":
        issue("SINGLE_STUDY_MODEL_VALIDATION_INVALID", "A single Study cannot PASS cross-Study modelling validation.")

    assessment = record.get("final_assessment")
    if not isinstance(assessment, dict):
        assessment = {}
        issue("INVALID_FINAL_ASSESSMENT", "final_assessment must be an object.")
    decision = assessment.get("decision")
    run_event_binding = record.get("run_event_ledger")
    if decision == "PASS" and not isinstance(run_event_binding, dict):
        issue("RUN_EVENT_LEDGER_BINDING_REQUIRED",
              "A full PASS requires a hash-bound Run Event Ledger tip.")
    if run_event_binding is not None:
        if not isinstance(run_event_binding, dict):
            issue("RUN_EVENT_LEDGER_BINDING_INVALID", "run_event_ledger must be an object.")
        else:
            try:
                event_path_value = run_event_binding.get("path")
                expected_event_path = (run_root / manifest["event_ledger_path"]).resolve(strict=False)
                if not isinstance(event_path_value, str) or not event_path_value.strip():
                    raise ValueError("run_event_ledger.path must be a non-empty path.")
                supplied_event_path = Path(event_path_value).expanduser()
                if not supplied_event_path.is_absolute():
                    supplied_event_path = record_path.parent / supplied_event_path
                if supplied_event_path.is_symlink():
                    raise ValueError("Run Event Ledger must not be a symlink.")
                event_path = supplied_event_path.resolve(strict=True)
                if event_path != expected_event_path:
                    raise ValueError("Run Event Ledger path differs from the Run Manifest declaration.")
                if not event_path.is_file():
                    raise ValueError("Run Event Ledger is not a regular file.")
                actual_event_sha = _sha256(event_path)
                actual_event_count = len(run_events)
                actual_event_tip = run_events[-1]["event_hash"] if run_events else None
                if run_event_binding.get("sha256") != actual_event_sha:
                    issue("RUN_EVENT_LEDGER_CHANGED", "Run Event Ledger SHA-256 differs from the Acceptance binding.")
                if (type(run_event_binding.get("event_count")) is not int
                        or run_event_binding["event_count"] != actual_event_count
                        or run_event_binding.get("last_event_hash") != actual_event_tip):
                    issue("RUN_EVENT_LEDGER_TIP_CHANGED", "Run Event Ledger event count/tip differs from the Acceptance binding.")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                issue("RUN_EVENT_LEDGER_INVALID", str(exc))

    gate_binding = record.get("workflow_gate_ledger")
    if decision == "PASS" and not isinstance(gate_binding, dict):
        issue("WORKFLOW_GATE_BINDING_REQUIRED",
              "A full PASS requires a hash-bound G0-G4 workflow gate ledger.")
    if gate_binding is not None:
        if not isinstance(gate_binding, dict):
            issue("WORKFLOW_GATE_BINDING_INVALID", "workflow_gate_ledger must be an object.")
        else:
            gate_path_value = gate_binding.get("path")
            gate_digest = gate_binding.get("sha256")
            recorded_gate_hashes = gate_binding.get("gate_event_hashes")
            recorded_gate_artifacts = gate_binding.get("gate_artifacts")
            if not isinstance(gate_path_value, str) or not gate_path_value.strip():
                issue("WORKFLOW_GATE_PATH_MISSING", "workflow_gate_ledger.path must be a non-empty path.")
            if not isinstance(gate_digest, str) or len(gate_digest) != 64:
                issue("WORKFLOW_GATE_HASH_INVALID", "workflow_gate_ledger.sha256 must be a SHA-256 digest.")
            if not isinstance(recorded_gate_hashes, dict):
                issue("WORKFLOW_GATE_EVENT_HASHES_INVALID", "workflow_gate_ledger.gate_event_hashes must map G0-G4 to event hashes.")
            try:
                from dor.gates import GATE_ORDER, inspect_gate_ledger
                if isinstance(gate_path_value, str):
                    supplied_gate_path = Path(gate_path_value).expanduser()
                    unresolved_gate_path = (
                        supplied_gate_path if supplied_gate_path.is_absolute()
                        else record_path.parent / supplied_gate_path
                    )
                    if unresolved_gate_path.is_symlink():
                        raise ValueError("Workflow gate ledger must not be a symlink.")
                    gate_path = _resolve_file(gate_path_value, record_path.parent)
                else:
                    gate_path = None
                if gate_path is None or not gate_path.is_file():
                    raise ValueError("Workflow gate ledger does not resolve to a regular file.")
                actual_gate_digest = _sha256(gate_path)
                if gate_digest != actual_gate_digest:
                    issue("WORKFLOW_GATE_LEDGER_CHANGED",
                          "Workflow gate ledger SHA-256 differs from the Acceptance Record binding; reassessment is required.")
                gate_report = inspect_gate_ledger(gate_path)
                actual_gate_hashes = {
                    gate_id: gate_report["gates"][gate_id].get("event_hash")
                    for gate_id in GATE_ORDER
                }
                if recorded_gate_hashes != actual_gate_hashes:
                    issue("WORKFLOW_GATE_EVENTS_CHANGED",
                          "G0-G4 event hashes differ from the Acceptance Record binding; reassessment is required.")
                if not isinstance(recorded_gate_artifacts, dict) or set(recorded_gate_artifacts) != set(GATE_ORDER):
                    issue("WORKFLOW_GATE_ARTIFACTS_INVALID",
                          "workflow_gate_ledger.gate_artifacts must map exactly G0-G4 to artifact reference arrays.")
                else:
                    for gate_id in GATE_ORDER:
                        event = gate_report.get("events", {}).get(gate_id)
                        event_artifacts = event.get("artifacts") if isinstance(event, dict) else None
                        if not isinstance(event_artifacts, list):
                            issue("WORKFLOW_GATE_EVENT_ARTIFACTS_MISSING",
                                  f"Gate {gate_id} has no inspectable event artifact list.")
                            event_artifacts = []
                        normalized = []
                        seen_ids: set[str] = set()
                        for gate_artifact in event_artifacts:
                            if not isinstance(gate_artifact, dict):
                                issue("WORKFLOW_GATE_EVENT_ARTIFACT_INVALID", f"Gate {gate_id} has a malformed artifact reference.")
                                continue
                            artifact_id = gate_artifact.get("artifact_id")
                            artifact_path = gate_artifact.get("path")
                            artifact_sha = gate_artifact.get("sha256")
                            if (not isinstance(artifact_id, str) or not artifact_id.strip()
                                    or artifact_id in seen_ids or not isinstance(artifact_path, str)
                                    or not artifact_path.strip() or Path(artifact_path).is_symlink()
                                    or not isinstance(artifact_sha, str) or len(artifact_sha) != 64
                                    or any(char not in "0123456789abcdef" for char in artifact_sha)):
                                issue("WORKFLOW_GATE_EVENT_ARTIFACT_INVALID", f"Gate {gate_id} has an incomplete or duplicate artifact identity.")
                                continue
                            seen_ids.add(artifact_id)
                            normalized.append({"artifact_id": artifact_id,
                                               "path": str(Path(artifact_path).resolve(strict=False)),
                                               "sha256": artifact_sha})
                        if recorded_gate_artifacts.get(gate_id) != normalized:
                            issue("WORKFLOW_GATE_ARTIFACTS_CHANGED",
                                  f"Gate {gate_id} artifact references differ from the Acceptance Record binding.")
                        if decision == "PASS":
                            matched = 0
                            for reference in normalized:
                                accepted = accepted_gate_evidence.get(reference["artifact_id"])
                                if accepted is None:
                                    continue
                                if accepted != reference:
                                    issue("WORKFLOW_GATE_EVIDENCE_IDENTITY_MISMATCH",
                                          f"Gate {gate_id} artifact {reference['artifact_id']} differs from accepted Run Evidence path/hash.")
                                else:
                                    matched += 1
                            if matched == 0:
                                issue("WORKFLOW_GATE_HAS_NO_ACCEPTED_EVIDENCE",
                                      f"Gate {gate_id} has no artifact also accepted as current V1.0 Run Evidence.")
                if decision == "PASS":
                    not_approved = [gate_id for gate_id in GATE_ORDER
                                    if gate_report["gates"][gate_id]["status"] != "APPROVED"]
                    if not_approved:
                        issue("WORKFLOW_GATES_NOT_APPROVED",
                              "Full PASS requires every workflow gate currently APPROVED; blocked: "
                              + ", ".join(not_approved) + ".")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                issue("WORKFLOW_GATE_LEDGER_INVALID", f"Workflow gate ledger could not be verified: {exc}")
    if decision not in FINAL_DECISIONS:
        issue("INVALID_FINAL_DECISION", "final_assessment.decision is invalid.")
    statuses = [stage_statuses.get(stage_id) for stage_id in STAGE_ORDER]
    for index, status in enumerate(statuses):
        if status in {"IN_PROGRESS", "PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}:
            previous = statuses[:index]
            if any(value not in {"PASS", "NOT_APPLICABLE"} for value in previous):
                issue("STAGE_SEQUENCE_GAP", f"Stage {STAGE_ORDER[index]} cannot start before every earlier stage is PASS or NOT_APPLICABLE.")
            if any(value in {"FAIL", "BLOCKED"} for value in previous):
                issue("STAGE_AFTER_BLOCKER", f"Stage {STAGE_ORDER[index]} cannot proceed after an earlier FAIL or BLOCKED stage.")
    if scope == "CONTROLLED_SINGLE_STUDY":
        allowed_na = {"cohort_feasibility", "modeling_validation"}
        for stage_id, status in zip(STAGE_ORDER, statuses):
            if status == "NOT_APPLICABLE" and stage_id not in allowed_na:
                issue("SINGLE_STUDY_NA_NOT_ALLOWED", f"Single-study scope does not permit {stage_id} to be NOT_APPLICABLE.")
    if decision == "PASS" and assessment.get("blocking_issue_ids"):
        issue("FULL_PASS_HAS_BLOCKERS", "PASS cannot retain blocking_issue_ids.")
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
        "acceptance_ledger": ledger_report,
        "source_checks": source_checks,
        "evidence_checks": evidence_checks,
        "assertion_checks": assertion_checks,
        "issue_count": len(issues),
        "issues": issues,
        "scientific_review_required": True,
        "interpretation": "Structural, run-binding, and file-integrity checks only; this report does not establish scientific correctness.",
    }
