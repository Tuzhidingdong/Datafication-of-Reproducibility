"""Controlled single-study applicability records and explicit non-applicable outputs.

This module does not fit models or create scientific findings. It verifies that the
approved task has exactly one eligible independent Study, then emits hash-bound
NOT_APPLICABLE records so the limited-scope workflow can still be reviewed and
published without fabricating model, reproducibility, interaction, or prediction
results.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.cohort import build_modeling_cohort
from dor.run_manager import _artifact_definitions, _artifact_path, _manifest_context, verify_run
from dor.mapping import sha256_file


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing single-study artifact: {path}")
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.write_text(rendered, encoding="utf-8")
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _planned_artifact_path(root: Path, plan: dict[str, Any], artifact_id: str) -> Path:
    definitions, _producers = _artifact_definitions(plan)
    if artifact_id not in definitions:
        raise ValueError(f"Run Plan does not declare required artifact {artifact_id}.")
    return _artifact_path(root, definitions[artifact_id]).expanduser().resolve(strict=False)


def _require_planned_path(root: Path, plan: dict[str, Any], artifact_id: str, supplied: Path) -> Path:
    expected = _planned_artifact_path(root, plan, artifact_id)
    actual = supplied.expanduser().resolve(strict=False)
    if actual != expected:
        raise ValueError(f"{artifact_id} path differs from the exact active Run Plan artifact path.")
    return expected


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_single_study_applicability_files(
    record_path: Path,
    bundle_path: Path,
    task_path: Path,
    manifest_path: Path,
    validation_output_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a human-reviewed single-Study applicability declaration."""
    root, manifest, plan, _events = _manifest_context(manifest_path)
    if plan.get("execution_profile") != "CONTROLLED_SINGLE_STUDY":
        raise ValueError("The active Run Plan must declare execution_profile CONTROLLED_SINGLE_STUDY.")
    run_status = verify_run(manifest_path)
    if run_status.get("source_integrity") != "CURRENT":
        raise ValueError("Protected Run sources are not current; single-Study applicability cannot be approved.")

    bundle_file = _require_planned_path(root, plan, "canonical_bundle", bundle_path)
    task_file = _require_planned_path(root, plan, "modeling_task", task_path)
    record_file = _require_planned_path(root, plan, "single_study_applicability_record", record_path)
    if validation_output_path is not None:
        _require_planned_path(root, plan, "single_study_applicability_validation", validation_output_path)
    if not bundle_file.is_file() or not task_file.is_file() or not record_file.is_file():
        raise ValueError("A declared single-study applicability input or record is missing.")
    bundle_sha = sha256_file(bundle_file)
    task_sha = sha256_file(task_file)
    bundle = _read_json(bundle_file, "Canonical Bundle")
    task = _read_json(task_file, "Modeling task")
    record = _read_json(record_file, "Single-study applicability record")

    integrity = validate_canonical_bundle(bundle)
    if not integrity.get("valid"):
        raise ValueError("Canonical Bundle is invalid; single-Study applicability cannot be established.")
    studies = bundle.get("studies")
    if not isinstance(studies, list) or len(studies) != 1:
        raise ValueError("CONTROLLED_SINGLE_STUDY requires exactly one Study in the approved Canonical Bundle.")
    study_ids = [item.get("study_id") for item in studies if isinstance(item, dict)]
    if len(study_ids) != 1 or not isinstance(study_ids[0], str) or not study_ids[0].strip():
        raise ValueError("The single Canonical Study must have one explicit non-empty study_id.")

    _rows, cohort_report, _split = build_modeling_cohort(bundle, task, bundle_sha, task_sha)
    errors = cohort_report.get("errors", []) if isinstance(cohort_report, dict) else []
    expected_codes = {"INSUFFICIENT_STUDIES_FOR_THREE_WAY_SPLIT"}
    observed_codes = {
        item.get("code") for item in errors if isinstance(item, dict)
    }
    if (cohort_report.get("eligible_study_count") != 1
            or observed_codes != expected_codes):
        raise ValueError(
            "The approved modeling task must have exactly one eligible Study and fail only "
            "because three independent Study partitions cannot be formed. "
            f"Observed eligible_study_count={cohort_report.get('eligible_study_count')!r}, "
            f"errors={sorted(str(item) for item in observed_codes)}."
        )

    required = {
        "schema_version", "run_id", "project_id", "scope", "applicability_status",
        "study_ids", "study_count", "canonical_bundle_sha256", "modeling_task_sha256",
        "cohort_feasibility_status", "cohort_feasibility_reason",
        "modeling_validation_status", "modeling_validation_reason",
        "reviewer", "reviewed_at", "rationale",
    }
    if set(record) != required:
        missing = sorted(required - set(record))
        extra = sorted(set(record) - required)
        raise ValueError(f"Single-study applicability record properties differ from its fixed contract; missing={missing}, extra={extra}.")
    if record.get("schema_version") != "1.0":
        raise ValueError("Single-study applicability record schema_version must be 1.0.")
    if record.get("run_id") != manifest.get("run_id") or record.get("project_id") != manifest.get("project_id"):
        raise ValueError("Single-study applicability record Run/Project identity differs from the active Run.")
    if record.get("scope") != "CONTROLLED_SINGLE_STUDY" or record.get("applicability_status") != "NOT_APPLICABLE":
        raise ValueError("Single-study applicability record must explicitly declare CONTROLLED_SINGLE_STUDY / NOT_APPLICABLE.")
    if record.get("study_ids") != study_ids or type(record.get("study_count")) is not int or record.get("study_count") != 1:
        raise ValueError("Single-study applicability record must bind exactly the one Study in the Canonical Bundle.")
    if record.get("canonical_bundle_sha256") != bundle_sha or record.get("modeling_task_sha256") != task_sha:
        raise ValueError("Single-study applicability record must bind the exact Canonical Bundle and modeling task hashes.")
    for status_key, reason_key in (
        ("cohort_feasibility_status", "cohort_feasibility_reason"),
        ("modeling_validation_status", "modeling_validation_reason"),
    ):
        if record.get(status_key) != "NOT_APPLICABLE":
            raise ValueError(f"{status_key} must be NOT_APPLICABLE for a single-Study scope.")
        reason = record.get(reason_key)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{reason_key} must state why cross-Study validation is not applicable.")
    if not all(isinstance(record.get(key), str) and record[key].strip()
               for key in ("reviewer", "rationale")):
        raise ValueError("Single-study applicability record requires reviewer and rationale.")
    if not _aware_timestamp(record.get("reviewed_at")):
        raise ValueError("Single-study applicability reviewed_at must be a timezone-aware ISO-8601 timestamp.")

    return {
        "schema_version": "1.0",
        "valid": True,
        "run_id": manifest.get("run_id"),
        "project_id": manifest.get("project_id"),
        "scope": "CONTROLLED_SINGLE_STUDY",
        "applicability_status": "NOT_APPLICABLE",
        "study_ids": study_ids,
        "study_count": 1,
        "eligible_study_count": cohort_report.get("eligible_study_count"),
        "canonical_bundle_sha256": bundle_sha,
        "modeling_task_sha256": task_sha,
        "applicability_record_sha256": sha256_file(record_file),
        "cohort_feasibility_reason": record["cohort_feasibility_reason"],
        "modeling_validation_reason": record["modeling_validation_reason"],
        "validation_basis": "EXACT_TASK_COHORT_CHECK_CONFIRMED_ONE_ELIGIBLE_STUDY_ONLY",
        "errors": [],
    }


def prepare_single_study_not_applicable_artifacts_files(
    record_path: Path,
    validation_path: Path,
    bundle_path: Path,
    task_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Write explicit non-applicable JSON reports; never create model-like results."""
    root, _manifest, plan, _events = _manifest_context(manifest_path)
    validation = validate_single_study_applicability_files(
        record_path, bundle_path, task_path, manifest_path, validation_path,
    )
    supplied_validation = _read_json(validation_path, "Single-study applicability validation report")
    if supplied_validation.get("valid") is not True:
        raise ValueError("Single-study applicability validation report is not valid.")
    if supplied_validation.get("applicability_record_sha256") != validation["applicability_record_sha256"]:
        raise ValueError("Applicability validation report does not bind the current record.")
    if supplied_validation.get("canonical_bundle_sha256") != validation["canonical_bundle_sha256"]:
        raise ValueError("Applicability validation report does not bind the current Canonical Bundle.")
    if supplied_validation.get("modeling_task_sha256") != validation["modeling_task_sha256"]:
        raise ValueError("Applicability validation report does not bind the current modeling task.")

    record = _read_json(record_path, "Single-study applicability record")
    task = _read_json(task_path, "Modeling task")
    out = output_dir.expanduser().resolve()
    declared_ids = (
        "model_report", "reproducibility_evaluation", "interaction_report",
        "interaction_manifest", "robustness_report", "robustness_manifest",
        "virtual_prediction",
    )
    expected_paths = {
        artifact_id: _planned_artifact_path(root, plan, artifact_id)
        for artifact_id in declared_ids
    }
    if any(path.parent != out for path in expected_paths.values()):
        raise ValueError("All NOT_APPLICABLE output artifacts must share the declared --out-dir.")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Output directory must be new or empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    base = {
        "schema_version": "1.0",
        "run_id": record["run_id"],
        "project_id": record["project_id"],
        "task_id": task.get("task_id"),
        "applicability_status": "NOT_APPLICABLE",
        "scope": "CONTROLLED_SINGLE_STUDY",
        "study_ids": record["study_ids"],
        "study_count": 1,
        "eligible_study_count": 1,
        "canonical_bundle_sha256": validation["canonical_bundle_sha256"],
        "modeling_task_sha256": validation["modeling_task_sha256"],
        "applicability_record_sha256": validation["applicability_record_sha256"],
        "reason": record["modeling_validation_reason"],
        "prohibited_inference": "No model, cross-Study performance, interaction, mechanism, or virtual prediction result was generated.",
    }

    artifacts: dict[str, dict[str, Any]] = {}
    payloads = {
        "model_report": ("model_report.json", {**base, "artifact_type": "model_report"}),
        "reproducibility_evaluation": (
            "reproducibility_evaluation.json",
            {**base, "artifact_type": "reproducibility_evaluation"},
        ),
        "interaction_report": (
            "interaction_discovery_report.json",
            {**base, "artifact_type": "interaction_report", "interaction_catalogue": []},
        ),
        "robustness_report": (
            "interaction_robustness_report.json",
            {**base, "artifact_type": "robustness_report", "interaction_catalogue": []},
        ),
        "virtual_prediction": (
            "virtual_prediction.json",
            {**base, "artifact_type": "virtual_prediction"},
        ),
    }
    for artifact_id, (filename, payload) in payloads.items():
        path = out / filename
        digest = _write_json(path, payload)
        artifacts[artifact_id] = {"path": str(path), "sha256": digest}

    for artifact_id, report_name, filename in (
        ("interaction_manifest", "interaction_report", "interaction_discovery_manifest.json"),
        ("robustness_manifest", "robustness_report", "interaction_robustness_manifest.json"),
    ):
        report_path = Path(artifacts[report_name]["path"])
        manifest_payload = {
            **base,
            "artifact_type": artifact_id,
            "input_hashes": {
                "task_sha256": validation["modeling_task_sha256"],
                "canonical_bundle_sha256": validation["canonical_bundle_sha256"],
                "applicability_record_sha256": validation["applicability_record_sha256"],
            },
            "output_hashes": {
                report_path.name: artifacts[report_name]["sha256"],
            },
        }
        path = out / filename
        digest = _write_json(path, manifest_payload)
        artifacts[artifact_id] = {"path": str(path), "sha256": digest}

    return {
        "schema_version": "1.0",
        "valid": True,
        "applicability_status": "NOT_APPLICABLE",
        "artifacts": artifacts,
        "output_dir": str(out),
        "interpretation": "Explicit non-applicability records only; no scientific model or prediction result was fabricated.",
    }
