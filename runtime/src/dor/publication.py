"""Deterministic publication-package assembly and integrity auditing."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file

STATUSES = {"complete", "partial", "not_generated", "not_applicable", "requires_review"}
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
RESERVED = {"README_FOR_WRITING_SKILL.md", "package_manifest.json"}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _relative_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be a non-empty relative path.")
    candidate = Path(value)
    if (candidate.is_absolute() or re.match(r"^[A-Za-z]:", value)
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or candidate.as_posix() != value):
        raise ValueError(label + " must be a normalized relative path without traversal or drive prefix.")
    if "\\" in value:
        raise ValueError(label + " must use forward slashes.")
    return candidate


def _within(root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(label + " resolves outside its allowed root.")
    return resolved


def _validate_plan(plan: Any) -> list[dict[str, Any]]:
    if not isinstance(plan, dict):
        raise ValueError("Publication package plan must be a JSON object.")
    if plan.get("schema_version") != "1.0":
        raise ValueError("Publication package plan schema_version must be 1.0.")
    for key in ("project_id", "run_id", "package_version"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(key + " must be a non-empty string.")
    profile = plan.get("domain_profile")
    if profile is not None:
        _relative_path(profile, "domain_profile")
    source_hashes = plan.get("source_hashes", {})
    if not isinstance(source_hashes, dict):
        raise ValueError("source_hashes must be an object keyed by source IDs or relative labels.")
    for source_key, digest in source_hashes.items():
        if (not isinstance(source_key, str) or not source_key.strip()
                or Path(source_key).is_absolute() or re.match(r"^[A-Za-z]:", source_key)
                or "\\" in source_key or ".." in Path(source_key).parts):
            raise ValueError("source_hashes keys must not contain absolute local paths or traversal.")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError("source_hashes values must be 64-character SHA-256 digests.")
    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Publication package plan must contain at least one artifact entry.")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(artifacts):
        label = "artifacts[" + str(index) + "]"
        if not isinstance(item, dict):
            raise ValueError(label + " must be an object.")
        for key in ("artifact_id", "path", "type", "description", "status"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(label + "." + key + " must be a non-empty string.")
        if item["status"] not in STATUSES:
            raise ValueError(label + ".status is not a supported artifact status.")
        if item["artifact_id"] in seen_ids:
            raise ValueError("Duplicate artifact_id: " + item["artifact_id"])
        seen_ids.add(item["artifact_id"])
        relative = _relative_path(item["path"], label + ".path")
        path_text = relative.as_posix()
        if path_text in RESERVED or path_text == "package_integrity_report.json":
            raise ValueError("Artifact path is reserved: " + path_text)
        if path_text in seen_paths:
            raise ValueError("Duplicate package destination path: " + path_text)
        seen_paths.add(path_text)
        source = item.get("source_path")
        if item["status"] in {"complete", "partial"} and not isinstance(source, str):
            raise ValueError(label + " requires source_path for complete/partial artifacts.")
        if source is not None:
            _relative_path(source, label + ".source_path")
        if item["status"] in {"not_generated", "not_applicable"} and source is not None:
            raise ValueError(label + " must not supply source_path for not_generated/not_applicable artifacts.")
        for list_key in ("linked_record_ids", "manuscript_sections"):
            values = item.get(list_key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(label + "." + list_key + " must be a list of non-empty strings.")
    return artifacts



def validate_publication_plan_files(
    plan_path: Path, manifest_path: Path, report_path: Path,
) -> dict[str, Any]:
    """Validate a final Publication Plan against current artifacts in one Run.

    This is a MANUAL stage validator: the stage must already be RUNNING. A
    template is immutable Run input; the final plan is a separate Run artifact
    prepared after optional G3 branches and human promotion have settled.
    """
    from dor.run_manager import (
        _latest_stage_events, _manifest_context, build_artifact_manifest,
    )

    root, manifest, run_plan, events = _manifest_context(manifest_path)
    stage = next(
        (item for item in run_plan.get("stages", [])
         if item.get("stage_id") == "publication_plan_preparation"),
        None,
    )
    if stage is None or stage.get("executor") != "manual":
        raise ValueError("The active Run Plan must declare publication_plan_preparation as a manual stage.")
    latest = _latest_stage_events(events).get("publication_plan_preparation")
    if latest is None or latest.get("status") != "RUNNING":
        raise ValueError("Publication Plan preparation must be recorded RUNNING before validation.")

    def expected_output(artifact_id: str) -> Path:
        matches = [item for item in stage.get("outputs", []) if item.get("artifact_id") == artifact_id]
        if len(matches) != 1:
            raise ValueError("Publication Plan preparation must declare exactly one " + artifact_id + " output.")
        raw = matches[0].get("path")
        if not isinstance(raw, str):
            raise ValueError("Publication Plan output path is malformed: " + artifact_id)
        return (root / _relative_path(raw, "Run output " + artifact_id)).resolve(strict=False)

    supplied_plan = plan_path.expanduser()
    if supplied_plan.is_symlink() or not supplied_plan.is_file():
        raise ValueError("Final Publication Plan must be a regular, non-symlink file.")
    actual_plan = supplied_plan.resolve(strict=True)
    if actual_plan != expected_output("publication_plan"):
        raise ValueError("Final Publication Plan path differs from its exact Run Plan output path.")
    supplied_report = report_path.expanduser()
    if supplied_report.is_symlink() or supplied_report.exists():
        raise ValueError("Publication Plan validation report must be a new, non-symlink file.")
    actual_report = supplied_report.resolve(strict=False)
    if actual_report != expected_output("publication_plan_validation"):
        raise ValueError("Publication Plan validation report path differs from its exact Run Plan output path.")

    issues: list[dict[str, str]] = []
    try:
        plan = _read_json(actual_plan)
        artifacts = _validate_plan(plan)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        plan = {}
        artifacts = []
        issues.append({"code": "INVALID_PLAN", "message": str(exc)})

    if plan:
        if plan.get("run_id") != manifest.get("run_id"):
            issues.append({"code": "RUN_ID_MISMATCH", "message": "Publication Plan run_id differs from the active Run."})
        if plan.get("project_id") != manifest.get("project_id"):
            issues.append({"code": "PROJECT_ID_MISMATCH", "message": "Publication Plan project_id differs from the active Run."})

    artifact_manifest = build_artifact_manifest(manifest_path)
    if artifact_manifest.get("source_integrity") != "CURRENT":
        issues.append({
            "code": "SOURCE_INTEGRITY_CHANGED",
            "message": "An operational or provenance-only source changed after Run initialization.",
        })
    rows = {
        item.get("artifact_id"): item
        for item in artifact_manifest.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    }

    source_bindings: list[dict[str, str]] = []
    package_artifact_ids: set[str] = set()
    for index, item in enumerate(artifacts):
        package_id = item["artifact_id"]
        package_artifact_ids.add(package_id)
        source_path_value = item.get("source_path")
        source_artifact_id = item.get("source_artifact_id")
        if source_path_value is None:
            if source_artifact_id is not None:
                issues.append({
                    "code": "SOURCE_ID_WITHOUT_SOURCE_PATH",
                    "message": f"{package_id} declares source_artifact_id without source_path.",
                })
            continue
        if not isinstance(source_artifact_id, str) or not source_artifact_id.strip():
            issues.append({
                "code": "SOURCE_ARTIFACT_ID_REQUIRED",
                "message": f"{package_id} must identify the exact Run Artifact with source_artifact_id.",
            })
            continue
        row = rows.get(source_artifact_id)
        if row is None:
            issues.append({
                "code": "SOURCE_ARTIFACT_NOT_DECLARED",
                "message": f"{package_id} references an Artifact not declared by the active Run: {source_artifact_id}.",
            })
            continue
        if row.get("status") != "CURRENT":
            issues.append({
                "code": "SOURCE_ARTIFACT_NOT_CURRENT",
                "message": f"{package_id} references {source_artifact_id} with Run status {row.get('status')}.",
            })
            continue
        try:
            relative_source = _relative_path(source_path_value, package_id + ".source_path")
            source_path = (root / relative_source).resolve(strict=True)
        except (OSError, ValueError) as exc:
            issues.append({
                "code": "SOURCE_PATH_INVALID",
                "message": f"{package_id} source_path is invalid: {exc}",
            })
            continue
        if source_path.is_symlink() or not source_path.is_file():
            issues.append({
                "code": "SOURCE_FILE_INVALID",
                "message": f"{package_id} source must be a regular, non-symlink Run file.",
            })
            continue
        expected_path = Path(str(row.get("path", ""))).resolve(strict=False)
        if source_path != expected_path:
            issues.append({
                "code": "SOURCE_PATH_MISMATCH",
                "message": f"{package_id} source_path differs from the path of Run Artifact {source_artifact_id}.",
            })
            continue
        digest = row.get("expected_sha256")
        actual_digest = row.get("actual_sha256")
        if not isinstance(digest, str) or digest != actual_digest or sha256_file(source_path) != digest:
            issues.append({
                "code": "SOURCE_HASH_MISMATCH",
                "message": f"{package_id} source hash differs from the current Run Artifact {source_artifact_id}.",
            })
            continue
        source_bindings.append({
            "package_artifact_id": package_id,
            "artifact_id": source_artifact_id,
            "path": str(source_path),
            "sha256": digest,
        })

    required_package_ids = {
        "WORKER_REVIEW_RECORD", "HUMAN_DISPOSITION_RECORD",
        "HUMAN_DISPOSITION_VALIDATION",
    }
    if not required_package_ids.issubset(package_artifact_ids):
        missing = sorted(required_package_ids - package_artifact_ids)
        issues.append({
            "code": "REQUIRED_REVIEW_DELIVERY_MISSING",
            "message": "Publication Plan is missing required Worker/human review package entries: " + ", ".join(missing),
        })
    by_run_artifact = {
        binding["artifact_id"] for binding in source_bindings
    }
    required_run_artifacts = {
        "worker_review_output", "reviewed_findings", "reviewed_findings_validation",
    }
    missing_run_artifacts = sorted(required_run_artifacts - by_run_artifact)
    if missing_run_artifacts:
        issues.append({
            "code": "REQUIRED_REVIEW_ARTIFACTS_NOT_PACKAGED",
            "message": "Publication Plan does not package required Run artifacts: " + ", ".join(missing_run_artifacts),
        })

    run_plan_stages = {
        item.get("stage_id"): item for item in run_plan.get("stages", [])
        if isinstance(item, dict)
    }
    if "single_study_applicability_record" in rows:
        profile_required = {
            "SINGLE_STUDY_APPLICABILITY_RECORD": "single_study_applicability_record",
            "SINGLE_STUDY_APPLICABILITY_VALIDATION": "single_study_applicability_validation",
            "MODEL_NOT_APPLICABLE_RECORD": "model_report",
            "REPRODUCIBILITY_NOT_APPLICABLE_RECORD": "reproducibility_evaluation",
            "INTERACTION_NOT_APPLICABLE_RECORD": "interaction_report",
            "INTERACTION_NOT_APPLICABLE_MANIFEST": "interaction_manifest",
            "ROBUSTNESS_NOT_APPLICABLE_RECORD": "robustness_report",
            "ROBUSTNESS_NOT_APPLICABLE_MANIFEST": "robustness_manifest",
            "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD": "virtual_prediction",
            "INTERACTION_SELECTION": "interaction_selection",
        }
        for package_id, run_artifact_id in profile_required.items():
            source = next((item for item in artifacts if item["artifact_id"] == package_id), None)
            binding = next((item for item in source_bindings if item["package_artifact_id"] == package_id), None)
            if source is None or binding is None or binding["artifact_id"] != run_artifact_id:
                issues.append({
                    "code": "SINGLE_STUDY_PACKAGE_EVIDENCE_MISSING",
                    "message": f"Controlled single-Study Publication Plan must package {package_id} from Run Artifact {run_artifact_id}.",
                })
    else:
        optional_groups = {
            "response_surface_generation": {
                "RESPONSE_SURFACE_REPORT_001": "interaction_response_surface_report",
                "RESPONSE_SURFACE_DATA_001": "interaction_response_surface",
                "RESPONSE_SURFACE_SUPPORT_001": "interaction_observed_support",
                "RESPONSE_SURFACE_MARGINALS_001": "interaction_marginal_effects",
            },
            "mechanism_evidence_bridge": {
                "MECHANISM_BRIDGE_001": "mechanism_evidence_bridge_report",
                "MECHANISM_FINDINGS_001": "mechanism_findings",
                "MECHANISM_LEDGER_001": "mechanism_evidence_ledger",
                "MECHANISM_REVIEW_QUEUE_001": "mechanism_review_queue",
                "MECHANISM_MANIFEST_001": "mechanism_evidence_bridge_manifest",
            },
        }
        selection = rows.get("interaction_selection")
        selected_ids: list[str] = []
        if isinstance(selection, dict) and selection.get("status") == "CURRENT":
            try:
                selection_payload = _read_json(Path(str(selection["path"])))
                values = selection_payload.get("selected_interaction_ids")
                if isinstance(values, list) and all(isinstance(value, str) for value in values):
                    selected_ids = values
                else:
                    issues.append({
                        "code": "INTERACTION_SELECTION_INVALID",
                        "message": "The current interaction_selection must contain selected_interaction_ids as a string array.",
                    })
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                issues.append({"code": "INTERACTION_SELECTION_INVALID", "message": str(exc)})
        optional_active = bool(selected_ids)
        for stage_id, package_map in optional_groups.items():
            if stage_id not in run_plan_stages:
                continue
            resume_actions = {
                item["stage_id"]: item["action"]
                for item in artifact_manifest.get("resume_plan", {}).get("stages", [])
                if isinstance(item, dict) and isinstance(item.get("stage_id"), str)
            }
            expected_action = "REUSE" if optional_active else "SKIPPED"
            if resume_actions.get(stage_id) != expected_action:
                issues.append({
                    "code": "OPTIONAL_STAGE_STATE_MISMATCH",
                    "message": f"{stage_id} must be {expected_action} for the exact G3 interaction selection; found {resume_actions.get(stage_id)}.",
                })
            for package_id, run_artifact_id in package_map.items():
                entry = next((item for item in artifacts if item["artifact_id"] == package_id), None)
                binding = next((item for item in source_bindings if item["package_artifact_id"] == package_id), None)
                if optional_active:
                    if entry is None or binding is None or binding["artifact_id"] != run_artifact_id:
                        issues.append({
                            "code": "OPTIONAL_OUTPUT_NOT_PACKAGED",
                            "message": f"G3 selected an interaction; package {package_id} must include current Run Artifact {run_artifact_id}.",
                        })
                elif entry is None or entry.get("status") != "not_generated" or entry.get("source_path") is not None:
                    issues.append({
                        "code": "OPTIONAL_OUTPUT_SHOULD_BE_NOT_GENERATED",
                        "message": f"G3 selected no interaction; package {package_id} must remain not_generated without a source_path.",
                    })

    report = {
        "schema_version": "1.0",
        "contract": "RUN_BOUND_PUBLICATION_PLAN",
        "valid": not issues,
        "run_id": manifest["run_id"],
        "project_id": manifest["project_id"],
        "run_root": str(root),
        "plan": {"path": str(actual_plan), "sha256": sha256_file(actual_plan)},
        "checked_source_count": len(source_bindings),
        "source_artifacts": source_bindings,
        "validation_report_path": str(actual_report),
        "errors": issues,
        "interpretation": (
            "A valid report binds every package source to a current Run Artifact and resolves conditional G3 outputs. "
            "It is not G4 approval or a scientific acceptance decision."
        ),
    }
    actual_report.parent.mkdir(parents=True, exist_ok=True)
    actual_report.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return report

def build_publication_package_files(
    plan_path: Path, workspace_root: Path, output_dir: Path,
    validation_path: Path | None = None,
) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not plan_path.is_file():
        raise FileNotFoundError("Publication package plan is missing: " + str(plan_path))
    if not workspace_root.is_dir():
        raise NotADirectoryError("Workspace root is not a directory: " + str(workspace_root))
    plan = _read_json(plan_path)
    artifacts = _validate_plan(plan)
    if validation_path is not None:
        supplied_validation = validation_path.expanduser()
        if supplied_validation.is_symlink() or not supplied_validation.is_file():
            raise ValueError("Publication Plan validation must be a regular, non-symlink file.")
        validation_report = _read_json(supplied_validation)
        if validation_report.get("contract") != "RUN_BOUND_PUBLICATION_PLAN" or validation_report.get("valid") is not True:
            raise ValueError("Publication Plan validation report is not valid.")
        if validation_report.get("plan", {}).get("path") != str(plan_path):
            raise ValueError("Publication Plan validation report references another plan path.")
        if validation_report.get("plan", {}).get("sha256") != sha256_file(plan_path):
            raise ValueError("Publication Plan changed after validation.")
        source_bindings = validation_report.get("source_artifacts")
        if not isinstance(source_bindings, list):
            raise ValueError("Publication Plan validation report lacks source_artifacts bindings.")
        for binding in source_bindings:
            if not isinstance(binding, dict):
                raise ValueError("Publication Plan validation has a malformed source binding.")
            source_file = Path(str(binding.get("path", "")))
            if (not source_file.is_file() or source_file.is_symlink()
                    or sha256_file(source_file) != binding.get("sha256")):
                raise ValueError("A Publication Plan source changed after validation: " + str(binding.get("artifact_id")))
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty publication package directory: " + str(output_dir))

    guide_source_value = plan.get("writing_guide_source")
    if guide_source_value is None:
        guide_source = Path(__file__).resolve().parents[3] / "templates" / "README_FOR_WRITING_SKILL.md"
    else:
        guide_source = _within(workspace_root, workspace_root / _relative_path(guide_source_value, "writing_guide_source"),
                               "writing_guide_source")
    if not guide_source.is_file():
        raise FileNotFoundError("Writing Skill guide source is missing: " + str(guide_source))

    output_dir.mkdir(parents=True, exist_ok=True)
    guide_target = output_dir / "README_FOR_WRITING_SKILL.md"
    guide_before = sha256_file(guide_source)
    shutil.copyfile(guide_source, guide_target)
    if sha256_file(guide_source) != guide_before or sha256_file(guide_target) != guide_before:
        raise ValueError("Writing guide changed during packaging or failed its copied-file hash check.")

    manifest_artifacts: list[dict[str, Any]] = []
    unresolved: list[str] = []
    copied_sources: list[tuple[Path, str]] = []
    for item in artifacts:
        relative = _relative_path(item["path"], "artifact.path")
        destination = _within(output_dir, output_dir / relative, "artifact destination")
        status = item["status"]
        record: dict[str, Any] = {
            "artifact_id": item["artifact_id"],
            "path": relative.as_posix(),
            "type": item["type"],
            "description": item["description"],
            "status": status,
            "linked_record_ids": item.get("linked_record_ids", []),
            "manuscript_sections": item.get("manuscript_sections", [])
        }
        source_value = item.get("source_path")
        if source_value is not None:
            source = _within(workspace_root, workspace_root / _relative_path(source_value, "artifact.source_path"),
                             "artifact source")
            if not source.is_file():
                raise FileNotFoundError("Declared publication artifact is missing: " + str(source_value))
            source_hash = sha256_file(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if sha256_file(source) != source_hash or sha256_file(destination) != source_hash:
                raise ValueError("Artifact changed during packaging or failed its copied-file hash check: " + item["artifact_id"])
            record["sha256"] = source_hash
            copied_sources.append((source, source_hash))
        elif status in {"complete", "partial"}:
            raise ValueError("Complete/partial artifact has no source: " + item["artifact_id"])
        if status != "complete" and status != "not_applicable":
            unresolved.append(item["artifact_id"] + " [" + status + "]: " + item["description"])
        manifest_artifacts.append(record)

    for source, expected in copied_sources:
        if sha256_file(source) != expected:
            raise ValueError("An input artifact changed before package finalization: " + str(source))

    has_review = any(item["status"] == "requires_review" for item in manifest_artifacts)
    has_partial = any(item["status"] in {"partial", "not_generated"} for item in manifest_artifacts)
    completeness_status = "requires_review" if has_review else ("partial" if has_partial else "complete")
    manifest = {
        "schema_version": "1.0",
        "project_id": plan["project_id"],
        "run_id": plan["run_id"],
        "package_version": plan["package_version"],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_hashes": plan.get("source_hashes", {}),
        "writing_guide": "README_FOR_WRITING_SKILL.md",
        "writing_guide_sha256": guide_before,
        "artifacts": manifest_artifacts,
        "completeness": {"status": completeness_status, "unresolved_items": unresolved}
    }
    if plan.get("domain_profile") is not None:
        manifest["domain_profile"] = plan["domain_profile"]
    _write_json(output_dir / "package_manifest.json", manifest)
    return {"valid": True, "manifest": manifest, "output_dir": str(output_dir),
            "artifact_count": len(manifest_artifacts), "copied_artifact_count": len(copied_sources)}


def audit_publication_package_files(package_dir: Path) -> dict[str, Any]:
    package_dir = package_dir.expanduser().resolve()
    manifest_path = package_dir / "package_manifest.json"
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not package_dir.is_dir():
        raise NotADirectoryError("Publication package path is not a directory: " + str(package_dir))
    if manifest_path.is_symlink():
        raise ValueError("package_manifest.json must not be a symbolic link.")
    if not manifest_path.is_file():
        raise FileNotFoundError("package_manifest.json is missing.")
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise ValueError("Unsupported or invalid publication package manifest.")
    guide_value = manifest.get("writing_guide")
    if guide_value != "README_FOR_WRITING_SKILL.md":
        errors.append("writing_guide must be README_FOR_WRITING_SKILL.md.")
    guide_path = package_dir / "README_FOR_WRITING_SKILL.md"
    expected_guide_hash = manifest.get("writing_guide_sha256")
    if guide_path.is_symlink():
        errors.append("Writing Skill guide must not be a symbolic link.")
    else:
        try:
            guide_path = _within(package_dir, guide_path, "Writing Skill guide")
        except ValueError as exc:
            errors.append(str(exc))
    if not guide_path.is_file() or guide_path.is_symlink():
        errors.append("Writing Skill guide is missing or is not a regular file.")
    elif (not isinstance(expected_guide_hash, str)
          or not SHA256_RE.fullmatch(expected_guide_hash)
          or sha256_file(guide_path) != expected_guide_hash):
        errors.append("Writing Skill guide SHA-256 missing, invalid, or mismatched.")

    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("Manifest artifacts must be an array.")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    indexed_files = {"README_FOR_WRITING_SKILL.md", "package_manifest.json"}
    for item in records:
        if not isinstance(item, dict):
            errors.append("Manifest contains a non-object artifact entry.")
            continue
        aid = item.get("artifact_id")
        rel = item.get("path")
        status = item.get("status")
        if status not in STATUSES:
            errors.append("Unsupported artifact status for " + str(aid) + ": " + str(status))
        if not isinstance(aid, str) or aid in seen_ids:
            errors.append("Artifact IDs are missing or duplicated: " + str(aid))
        seen_ids.add(str(aid))
        try:
            relative = _relative_path(rel, "manifest artifact path")
            rel_text = relative.as_posix()
            if rel_text in seen_paths or rel_text in RESERVED:
                errors.append("Artifact paths are duplicated or reserved: " + rel_text)
                continue
            seen_paths.add(rel_text)
            target = _within(package_dir, package_dir / relative, "manifest artifact path")
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        exists = target.is_file()
        expected = item.get("sha256")
        if status in {"complete", "partial"} and not exists:
            errors.append("Required artifact is missing: " + rel_text)
        if status in {"not_generated", "not_applicable"} and exists:
            errors.append("Artifact marked " + str(status) + " unexpectedly exists: " + rel_text)
        if status in {"not_generated", "not_applicable"} and expected:
            errors.append("Artifact marked " + str(status) + " must not carry a file hash: " + rel_text)
        if status == "requires_review" and not exists and expected:
            errors.append("Missing requires_review artifact has a SHA-256: " + rel_text)
        if exists:
            indexed_files.add(rel_text)
            actual = sha256_file(target)
            ok = isinstance(expected, str) and bool(SHA256_RE.fullmatch(expected)) and actual == expected
            if not ok:
                errors.append("Artifact SHA-256 missing/invalid/mismatched: " + rel_text)
        else:
            ok = status in {"not_generated", "not_applicable"}
        checks.append({"artifact_id": aid, "path": rel_text, "status": status,
                       "exists": exists, "hash_valid": ok if exists else None})
    package_entries = list(package_dir.rglob("*"))
    for entry in package_entries:
        if entry.is_symlink():
            errors.append("Symbolic links are not permitted in publication packages: "
                          + entry.relative_to(package_dir).as_posix())
    actual_files = {
        path.relative_to(package_dir).as_posix()
        for path in package_entries if path.is_file() and not path.is_symlink()
    }
    for extra in sorted(actual_files - indexed_files):
        errors.append("Unindexed file exists in package: " + extra)
    return {"valid": not errors, "package_dir": str(package_dir),
            "artifact_count": len(records), "checked_file_count": len(indexed_files.intersection(actual_files)),
            "errors": errors, "artifact_checks": checks,
            "completeness": manifest.get("completeness")}


def audit_publication_package_file(package_dir: Path, report_path: Path | None = None) -> dict[str, Any]:
    report = audit_publication_package_files(package_dir)
    if report_path is not None:
        report_path = report_path.expanduser().resolve()
        if report_path.is_relative_to(package_dir):
            raise ValueError("Package integrity report must be written outside the package directory.")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(report_path, report)
        report["report_path"] = str(report_path)
    return report
