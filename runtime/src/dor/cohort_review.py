"""Human review gate for modelling-cohort grain, independence, and split suitability."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

COHORT_OUTPUT_ARTIFACTS = (
    "modeling_cohort.csv",
    "cohort_report.json",
    "split_manifest.json",
)
REQUIRED_INPUTS = (*COHORT_OUTPUT_ARTIFACTS, "modeling_cohort_manifest.json")
REVIEWABLE_INPUTS = (*REQUIRED_INPUTS, "modeling_task.json")
ASSESSMENTS = {
    "record_grain_assessment": {"ACCEPTED", "UNRESOLVED", "REQUIRES_REVISION"},
    "independence_assessment": {"SUPPORTED", "NOT_APPLICABLE", "NOT_ESTABLISHED"},
    "split_assessment": {"ACCEPTED", "REQUIRES_REVISION"},
}


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


def _timestamp_is_timezone_aware(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _cohort_rows(path: Path) -> tuple[int, set[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required cohort input does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"cohort_row_id", "observation_id", "study_id", "split"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Modeling cohort CSV is missing required identity/split columns.")
        rows = list(reader)
    row_ids = [row.get("cohort_row_id", "") for row in rows]
    observation_ids = [row.get("observation_id", "") for row in rows]
    if any(not value for value in row_ids) or len(row_ids) != len(set(row_ids)):
        raise ValueError("Cohort row IDs must be non-empty and unique.")
    if any(not value for value in observation_ids) or len(observation_ids) != len(set(observation_ids)):
        raise ValueError("Cohort Observation IDs must be non-empty and unique.")
    if any(not row.get("study_id") for row in rows):
        raise ValueError("Every eligible cohort row must declare a Study ID.")
    return len(rows), {row["study_id"] for row in rows}, rows


def validate_cohort_review_record(
    record_path: Path,
    cohort_dir: Path,
    task_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Validate human review against exact, current modelling-cohort inputs."""
    record_path = record_path.expanduser()
    if record_path.is_symlink():
        raise ValueError("Cohort review record must not be a symlink.")
    record_path = record_path.resolve(strict=True)
    cohort_dir = cohort_dir.expanduser().resolve(strict=True)
    task_path = task_path.expanduser().resolve(strict=True)
    if not cohort_dir.is_dir():
        raise NotADirectoryError(f"Cohort directory is not a directory: {cohort_dir}")

    record_sha256_before = _sha256(record_path)
    record = _read_json(record_path, "Cohort review record")
    cohort_report = _read_json(cohort_dir / "cohort_report.json", "Cohort report")
    split_manifest = _read_json(cohort_dir / "split_manifest.json", "Split manifest")
    cohort_manifest = _read_json(cohort_dir / "modeling_cohort_manifest.json", "Cohort manifest")
    task = _read_json(task_path, "Modeling task")
    cohort_path = cohort_dir / "modeling_cohort.csv"

    errors: list[dict[str, str]] = []

    def issue(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if record.get("schema_version") != "1.0":
        issue("UNSUPPORTED_SCHEMA_VERSION", "Cohort review schema_version must be 1.0.")
    for field in ("review_id", "run_id", "project_id", "task_id", "reviewer", "rationale"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            issue("REQUIRED_FIELD_MISSING", f"{field} must be a non-empty string.")
    if not _timestamp_is_timezone_aware(record.get("reviewed_at")):
        issue("REVIEW_TIMESTAMP_INVALID", "reviewed_at must be an ISO-8601 timestamp with an explicit timezone.")

    if record.get("task_id") != task.get("task_id"):
        issue("TASK_ID_MISMATCH", "Cohort review task_id does not match the exact modeling task.")
    if cohort_report.get("task_id") != task.get("task_id"):
        issue("COHORT_TASK_ID_MISMATCH", "Cohort report task_id does not match the exact modeling task.")
    if cohort_manifest.get("task_id") != task.get("task_id"):
        issue("MANIFEST_TASK_ID_MISMATCH", "Cohort manifest task_id does not match the exact modeling task.")
    task_sha256 = _sha256(task_path)
    if cohort_report.get("task_sha256") != task_sha256:
        issue("COHORT_REPORT_TASK_HASH_MISMATCH", "Cohort report was not produced from the exact modeling task file.")
    if cohort_manifest.get("task_sha256") != task_sha256:
        issue("COHORT_MANIFEST_TASK_HASH_MISMATCH", "Cohort manifest was not produced from the exact modeling task file.")
    if cohort_report.get("bundle_sha256") != cohort_manifest.get("bundle_sha256"):
        issue("COHORT_BUNDLE_HASH_MISMATCH", "Cohort report and manifest do not bind the same Canonical Bundle hash.")
    if cohort_manifest.get("eligible_observation_count") != cohort_report.get("eligible_observation_count"):
        issue("COHORT_MANIFEST_COUNT_MISMATCH", "Cohort manifest Observation count differs from the Cohort report.")
    if cohort_manifest.get("eligible_study_count") != cohort_report.get("eligible_study_count"):
        issue("COHORT_MANIFEST_STUDY_COUNT_MISMATCH", "Cohort manifest Study count differs from the Cohort report.")
    if cohort_report.get("valid") is not True:
        issue("COHORT_REPORT_NOT_VALID", "Cohort report must declare valid=true before review.")
    if not isinstance(split_manifest.get("leakage_check"), dict) or split_manifest["leakage_check"].get("valid") is not True:
        issue("STUDY_SPLIT_NOT_VALID", "Split manifest must record a successful Study-level leakage check.")

    run_id = None
    project_id = None
    if manifest_path is not None:
        manifest_path = manifest_path.expanduser().resolve(strict=True)
        manifest = _read_json(manifest_path, "Run manifest")
        run_id, project_id = manifest.get("run_id"), manifest.get("project_id")
        if record.get("run_id") != run_id:
            issue("RUN_ID_MISMATCH", "Cohort review run_id does not match the active Run manifest.")
        if record.get("project_id") != project_id:
            issue("PROJECT_ID_MISMATCH", "Cohort review project_id does not match the active Run manifest.")

    try:
        row_count, study_ids, rows = _cohort_rows(cohort_path)
    except (OSError, ValueError) as exc:
        issue("COHORT_CSV_INVALID", str(exc))
        row_count, study_ids, rows = 0, set(), []

    reported_count = cohort_report.get("eligible_observation_count")
    reported_study_count = cohort_report.get("eligible_study_count")
    if type(reported_count) is not int or reported_count != row_count:
        issue("OBSERVATION_COUNT_MISMATCH", "Cohort CSV row count does not match cohort_report.eligible_observation_count.")
    if type(reported_study_count) is not int or reported_study_count != len(study_ids):
        issue("STUDY_COUNT_MISMATCH", "Cohort CSV Study count does not match cohort_report.eligible_study_count.")
    declared_studies = cohort_report.get("eligible_study_ids")
    if (not isinstance(declared_studies, list)
            or any(not isinstance(value, str) or not value for value in declared_studies)
            or set(declared_studies) != study_ids):
        issue("ELIGIBLE_STUDY_SET_MISMATCH", "Cohort CSV Study IDs do not match cohort_report.eligible_study_ids.")

    split_assignments = split_manifest.get("study_to_split")
    if not isinstance(split_assignments, dict):
        issue("SPLIT_ASSIGNMENTS_MISSING", "Split manifest must contain study_to_split.")
        split_assignments = {}
    if set(split_assignments) != study_ids:
        issue("SPLIT_STUDY_SET_MISMATCH", "Study IDs in split_manifest do not match the eligible cohort.")
    declared_observations = split_manifest.get("observation_ids_by_split")
    if not isinstance(declared_observations, dict):
        issue("SPLIT_OBSERVATION_IDS_MISSING", "Split manifest must declare observation_ids_by_split.")
        declared_observations = {}
    for split_name in ("train", "validation", "test"):
        observed_ids = sorted(row["observation_id"] for row in rows if row.get("split") == split_name)
        declared_ids = declared_observations.get(split_name)
        if not isinstance(declared_ids, list) or sorted(declared_ids) != observed_ids:
            issue("SPLIT_OBSERVATION_SET_MISMATCH", f"Cohort CSV Observation IDs for {split_name} do not match split_manifest.")
    if not {"train", "validation", "test"}.issubset({row.get("split") for row in rows}):
        issue("COHORT_PARTITION_EMPTY", "Cohort must contain at least one Observation in train, validation, and test.")
    for row in rows:
        if row.get("split") not in {"train", "validation", "test"}:
            issue("COHORT_SPLIT_LABEL_INVALID", f"Observation {row.get('observation_id')} has an invalid split label.")
            break
        if split_assignments.get(row.get("study_id")) != row.get("split"):
            issue("COHORT_SPLIT_ASSIGNMENT_MISMATCH", f"Observation {row.get('observation_id')} does not match the split manifest.")
            break

    artifact_hashes = record.get("artifact_sha256")
    expected_hashes: dict[str, str] = {}
    for name in REVIEWABLE_INPUTS:
        input_path = task_path if name == "modeling_task.json" else cohort_dir / name
        if not input_path.is_file():
            issue("REVIEW_INPUT_MISSING", f"Review input is missing: {name}.")
            continue
        expected_hashes[name] = _sha256(input_path)
    declared_cohort_hashes = cohort_manifest.get("artifact_sha256")
    if not isinstance(declared_cohort_hashes, dict):
        issue("COHORT_MANIFEST_HASHES_MISSING", "Cohort manifest must declare hashes for the CSV, report, and split manifest.")
    else:
        for name in COHORT_OUTPUT_ARTIFACTS:
            if name not in expected_hashes or declared_cohort_hashes.get(name) != expected_hashes[name]:
                issue("COHORT_MANIFEST_ARTIFACT_HASH_MISMATCH", f"Cohort manifest hash does not match the current {name}.")
    if not isinstance(artifact_hashes, dict):
        issue("ARTIFACT_HASHES_MISSING", "artifact_sha256 must bind every cohort and task input.")
    elif set(artifact_hashes) != set(REVIEWABLE_INPUTS):
        issue("ARTIFACT_HASH_SET_MISMATCH", "artifact_sha256 must contain exactly the four cohort files and the modeling task.")
    else:
        for name, expected in expected_hashes.items():
            if artifact_hashes.get(name) != expected:
                issue("ARTIFACT_HASH_MISMATCH", f"{name} changed after the human cohort review.")

    reviewed_study_count = record.get("reviewed_study_count")
    if type(reviewed_study_count) is not int or reviewed_study_count != len(study_ids):
        issue("REVIEWED_STUDY_COUNT_MISMATCH", "reviewed_study_count must be an exact integer equal to the eligible cohort Study count.")
    reviewed_observation_count = record.get("reviewed_observation_count")
    if type(reviewed_observation_count) is not int or reviewed_observation_count != row_count:
        issue("REVIEWED_OBSERVATION_COUNT_MISMATCH", "reviewed_observation_count must be an exact integer equal to the eligible cohort Observation count.")

    for field, allowed in ASSESSMENTS.items():
        if record.get(field) not in allowed:
            issue("ASSESSMENT_INVALID", f"{field} must be one of: {', '.join(sorted(allowed))}.")
    scientific_contract = cohort_report.get("scientific_data_contract")
    warning_items = scientific_contract.get("warnings", []) if isinstance(scientific_contract, dict) else []
    warning_codes = {
        item.get("code")
        for item in warning_items
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    }
    reviewed_codes = record.get("reviewed_warning_codes")
    if (not isinstance(reviewed_codes, list)
            or any(not isinstance(value, str) for value in reviewed_codes)
            or len(reviewed_codes) != len(set(reviewed_codes))
            or set(reviewed_codes) != warning_codes):
        issue("GRAIN_WARNING_COVERAGE_MISMATCH", "reviewed_warning_codes must classify every warning code in the cohort scientific_data_contract exactly once, with no omissions or additions.")

    if record.get("decision") not in {"APPROVE_MODELING", "REVISE", "STOP"}:
        issue("DECISION_INVALID", "decision must be APPROVE_MODELING, REVISE, or STOP.")
    elif record.get("decision") != "APPROVE_MODELING":
        issue("DECISION_DOES_NOT_APPROVE_MODELLING", "Only APPROVE_MODELING can unlock downstream model execution.")
    if record.get("decision") == "APPROVE_MODELING":
        if record.get("record_grain_assessment") != "ACCEPTED":
            issue("RECORD_GRAIN_NOT_ACCEPTED", "APPROVE_MODELING requires record_grain_assessment=ACCEPTED.")
        if record.get("independence_assessment") not in {"SUPPORTED", "NOT_APPLICABLE"}:
            issue("INDEPENDENCE_NOT_ESTABLISHED", "APPROVE_MODELING requires supported independence or an explicit NOT_APPLICABLE assessment.")
        if record.get("split_assessment") != "ACCEPTED":
            issue("SPLIT_NOT_ACCEPTED", "APPROVE_MODELING requires split_assessment=ACCEPTED.")

    record_sha256_after = _sha256(record_path)
    if record_sha256_after != record_sha256_before:
        issue("REVIEW_RECORD_CHANGED_DURING_VALIDATION", "The human review record changed while it was being validated.")

    return {
        "schema_version": "1.0",
        "valid": not errors,
        "record_sha256": record_sha256_after,
        "error_count": len(errors),
        "errors": errors,
        "review_id": record.get("review_id"),
        "run_id": record.get("run_id"),
        "project_id": record.get("project_id"),
        "task_id": task.get("task_id"),
        "decision": record.get("decision"),
        "cohort_sha256": expected_hashes.get("modeling_cohort.csv"),
        "cohort_report_sha256": expected_hashes.get("cohort_report.json"),
        "split_manifest_sha256": expected_hashes.get("split_manifest.json"),
        "cohort_manifest_sha256": expected_hashes.get("modeling_cohort_manifest.json"),
        "task_sha256": expected_hashes.get("modeling_task.json"),
        "reviewed_study_count": len(study_ids),
        "reviewed_observation_count": row_count,
        "scientific_data_contract_warning_count": len(warning_codes),
        "validation_scope": "HUMAN_COHORT_GRAIN_INDEPENDENCE_AND_SPLIT_REVIEW_BOUND_TO_EXACT_INPUT_HASHES",
    }


def enforce_cohort_review(cohort_dir: Path, task_path: Path, workflow_ledger_path: Path) -> dict[str, Any]:
    """Require both the signed-off review record and its current validator report."""
    cohort_dir = cohort_dir.expanduser().resolve(strict=True)
    ledger_path = workflow_ledger_path.expanduser().resolve(strict=True)
    manifest_path = ledger_path.parent / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Active Run manifest is required next to the workflow Gate Ledger for Cohort review enforcement.")
    record_path = cohort_dir / "cohort_review_record.json"
    validation_path = cohort_dir / "cohort_review_validation.json"
    if not record_path.is_file() or not validation_path.is_file():
        raise ValueError("Cohort human review is required before modelling: create cohort_review_record.json and validate it with dor validate-cohort-review.")
    result = validate_cohort_review_record(record_path, cohort_dir, task_path, manifest_path)
    saved_report = _read_json(validation_path, "Cohort review validation report")
    if result.get("valid") is not True or saved_report.get("valid") is not True:
        raise ValueError("Cohort review is not currently approved: " + json.dumps(result.get("errors", []), ensure_ascii=False))
    for key in ("record_sha256", "cohort_sha256", "cohort_report_sha256", "split_manifest_sha256",
                "cohort_manifest_sha256", "task_sha256", "review_id", "run_id", "project_id",
                "task_id", "decision", "reviewed_study_count", "reviewed_observation_count"):
        if saved_report.get(key) != result.get(key):
            raise ValueError("Saved Cohort review validation report is stale or differs from current inputs: " + key)
    return result
