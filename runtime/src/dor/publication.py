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


def build_publication_package_files(plan_path: Path, workspace_root: Path, output_dir: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not plan_path.is_file():
        raise FileNotFoundError("Publication package plan is missing: " + str(plan_path))
    if not workspace_root.is_dir():
        raise NotADirectoryError("Workspace root is not a directory: " + str(workspace_root))
    plan = _read_json(plan_path)
    artifacts = _validate_plan(plan)
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
