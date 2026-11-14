"""Validation of domain-neutral packages produced by external data adapters."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARTIFACT_ROLES = {
    "standardized_dataset", "discovery_dataset", "source_inventory",
    "mapping_plan", "build_spec", "canonical_bundle", "domain_profile",
    "evidence_index", "auxiliary",
}
_FORMATS = {"csv", "json", "jsonl", "tsv", "xml", "text", "binary", "other"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_package_artifact(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError("Adapter artifact paths must be relative to the package root.")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Adapter artifact path escapes the package root.")
    return resolved


def _resolve_source(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not candidate.is_absolute() and not resolved.is_relative_to(root):
        raise ValueError("Relative source path escapes the package root.")
    return resolved


def validate_adapter_package_files(
    manifest_path: Path,
    package_root: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Verify adapter package structure, safe paths, existence, and exact SHA-256 hashes.

    This validator deliberately does not interpret data semantics, approve mappings,
    or decide scientific suitability.
    """
    manifest_path = manifest_path.expanduser().resolve()
    root = (package_root.expanduser().resolve() if package_root else manifest_path.parent.resolve())
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    verified_sources = 0
    verified_artifacts = 0

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Adapter manifest does not exist: {manifest_path}")
    if not manifest_path.is_relative_to(root):
        raise ValueError("Adapter manifest must be inside the declared package root.")

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid adapter manifest JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Adapter manifest must be a JSON object.")

    if payload.get("schema_version") != "1.0":
        errors.append({"code": "SCHEMA_VERSION", "message": "Expected schema_version 1.0."})
    if not isinstance(payload.get("package_id"), str) or not payload["package_id"].strip():
        errors.append({"code": "PACKAGE_ID", "message": "package_id must be a non-empty string."})

    adapter = payload.get("adapter")
    if not isinstance(adapter, dict):
        errors.append({"code": "ADAPTER_DESCRIPTOR", "message": "adapter must be an object."})
    else:
        for field in ("adapter_id", "adapter_version"):
            if not isinstance(adapter.get(field), str) or not adapter[field].strip():
                errors.append({"code": "ADAPTER_DESCRIPTOR", "message": f"adapter.{field} must be a non-empty string."})
        digest = adapter.get("adapter_digest")
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            errors.append({"code": "ADAPTER_DIGEST", "message": "adapter_digest must be null or a 64-character SHA-256."})

    sources = payload.get("sources")
    artifacts = payload.get("artifacts")
    if not isinstance(sources, list) or not sources:
        errors.append({"code": "SOURCES_REQUIRED", "message": "sources must be a non-empty array."})
        sources = []
    if not isinstance(artifacts, list) or not artifacts:
        errors.append({"code": "ARTIFACTS_REQUIRED", "message": "artifacts must be a non-empty array."})
        artifacts = []

    source_ids: set[str] = set()
    artifact_ids: set[str] = set()

    for index, item in enumerate(sources):
        location = f"sources[{index}]"
        if not isinstance(item, dict):
            errors.append({"code": "SOURCE_ENTRY", "message": f"{location} must be an object."})
            continue
        source_id, raw_path, expected = item.get("source_id"), item.get("path"), item.get("sha256")
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id) or source_id in source_ids:
            errors.append({"code": "SOURCE_ID", "message": f"{location}.source_id is invalid or duplicated."})
        else:
            source_ids.add(source_id)
        if not isinstance(item.get("format"), str) or item["format"] not in _FORMATS:
            errors.append({"code": "SOURCE_FORMAT", "message": f"{location}.format is unsupported."})
        if not isinstance(raw_path, str) or not raw_path.strip() or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            errors.append({"code": "SOURCE_DESCRIPTOR", "message": f"{location} requires a path and 64-character SHA-256."})
            continue
        try:
            source_path = _resolve_source(root, raw_path)
            if not source_path.is_file():
                errors.append({"code": "SOURCE_MISSING", "message": f"{location} source file is missing: {raw_path}"})
            elif _sha256(source_path) != expected.lower():
                errors.append({"code": "SOURCE_HASH_MISMATCH", "message": f"{location} source hash differs: {raw_path}"})
            else:
                verified_sources += 1
        except (OSError, ValueError) as exc:
            errors.append({"code": "SOURCE_PATH_INVALID", "message": f"{location}: {exc}"})

    for index, item in enumerate(artifacts):
        location = f"artifacts[{index}]"
        if not isinstance(item, dict):
            errors.append({"code": "ARTIFACT_ENTRY", "message": f"{location} must be an object."})
            continue
        artifact_id, role = item.get("artifact_id"), item.get("role")
        raw_path, expected = item.get("path"), item.get("sha256")
        if not isinstance(artifact_id, str) or not _ID.fullmatch(artifact_id) or artifact_id in artifact_ids:
            errors.append({"code": "ARTIFACT_ID", "message": f"{location}.artifact_id is invalid or duplicated."})
        else:
            artifact_ids.add(artifact_id)
        if role not in _ARTIFACT_ROLES:
            errors.append({"code": "ARTIFACT_ROLE", "message": f"{location}.role is unsupported."})
        if not isinstance(item.get("format"), str) or item["format"] not in _FORMATS:
            errors.append({"code": "ARTIFACT_FORMAT", "message": f"{location}.format is unsupported."})
        if not isinstance(raw_path, str) or not raw_path.strip() or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            errors.append({"code": "ARTIFACT_DESCRIPTOR", "message": f"{location} requires a relative path and 64-character SHA-256."})
            continue
        try:
            artifact_path = _resolve_package_artifact(root, raw_path)
            if not artifact_path.is_file():
                errors.append({"code": "ARTIFACT_MISSING", "message": f"{location} artifact file is missing: {raw_path}"})
            elif _sha256(artifact_path) != expected.lower():
                errors.append({"code": "ARTIFACT_HASH_MISMATCH", "message": f"{location} artifact hash differs: {raw_path}"})
            else:
                verified_artifacts += 1
        except (OSError, ValueError) as exc:
            errors.append({"code": "ARTIFACT_PATH_INVALID", "message": f"{location}: {exc}"})

    report = {
        "schema_version": "1.0",
        "valid": not errors,
        "package_id": payload.get("package_id"),
        "adapter_id": adapter.get("adapter_id") if isinstance(adapter, dict) else None,
        "adapter_version": adapter.get("adapter_version") if isinstance(adapter, dict) else None,
        "manifest_path": str(manifest_path),
        "package_root": str(root),
        "source_count": len(sources),
        "verified_source_count": verified_sources,
        "artifact_count": len(artifacts),
        "verified_artifact_count": verified_artifacts,
        "artifact_roles": sorted({item.get("role") for item in artifacts if isinstance(item, dict) and isinstance(item.get("role"), str)}),
        "errors": errors,
        "warnings": warnings,
        "interpretation_boundary": "Validation proves package structure, path safety, file availability, and hash consistency only. It does not approve semantic mappings or scientific suitability.",
    }

    if report_path is not None:
        output = report_path.expanduser().resolve()
        if output == manifest_path or output.is_relative_to(root):
            raise ValueError("Validation report must be outside the adapter package and must not overwrite its manifest.")
        output.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = str(output)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
