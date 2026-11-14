"""Validated handoff routing for external, discipline-neutral adapter packages."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from dor.adapters import validate_adapter_package_files
from dor.canonical import validate_canonical_bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(package_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError("Adapter artifact paths must be package-relative.")
    resolved = (package_root / candidate).resolve()
    if not resolved.is_relative_to(package_root):
        raise ValueError(f"Adapter artifact path escapes package root: {raw_path!r}.")
    return resolved


def _source_path(package_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (package_root / candidate).resolve()
    if not candidate.is_absolute() and not resolved.is_relative_to(package_root):
        raise ValueError(f"Relative adapter source path escapes package root: {raw_path!r}.")
    return resolved


def _resolve_package_records(payload: dict[str, Any], package_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources = []
    for item in payload["sources"]:
        path = _source_path(package_root, item["path"])
        sources.append({
            "source_id": item["source_id"],
            "path": str(path),
            "package_path": item["path"],
            "format": item["format"],
            "role": item.get("role"),
            "sha256": item["sha256"].lower(),
        })

    artifacts = []
    for item in payload["artifacts"]:
        path = _artifact_path(package_root, item["path"])
        artifacts.append({
            "artifact_id": item["artifact_id"],
            "role": item["role"],
            "path": str(path),
            "package_path": item["path"],
            "format": item["format"],
            "media_type": item.get("media_type"),
            "sha256": item["sha256"].lower(),
        })
    return sources, artifacts


def _validate_declared_files(records: list[dict[str, Any]], label: str) -> None:
    for item in records:
        path = Path(item["path"])
        if not path.is_file():
            raise FileNotFoundError(f"{label} file is missing: {path}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"{label} SHA-256 mismatch: {item['package_path']}")


def prepare_adapter_handoff_files(
    manifest_path: Path,
    package_root: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a package and create one deterministic route description for DoR.

    The function checks delivery integrity and canonical structure only. It does not
    approve extraction quality, entity grain, mappings, scientific semantics, or
    suitability for analysis.
    """
    manifest_path = manifest_path.expanduser().resolve()
    root = (package_root.expanduser().resolve() if package_root else manifest_path.parent.resolve())
    validation = validate_adapter_package_files(manifest_path, root)
    if not validation.get("valid"):
        raise ValueError(
            "Adapter package validation failed: "
            + json.dumps(validation.get("errors", []), ensure_ascii=False)
        )

    manifest_hash = _sha256(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    sources, artifacts = _resolve_package_records(payload, root)
    _validate_declared_files(sources, "Adapter source")
    _validate_declared_files(artifacts, "Adapter artifact")
    if _sha256(manifest_path) != manifest_hash:
        raise RuntimeError("Adapter manifest changed while preparing the handoff.")

    canonical = [item for item in artifacts if item["role"] == "canonical_bundle"]
    if len(canonical) > 1:
        raise ValueError("An adapter package may declare at most one canonical_bundle artifact.")

    warnings: list[str] = []
    canonical_record: dict[str, Any] | None = None
    if canonical:
        canonical_record = canonical[0]
        if canonical_record["format"] != "json":
            raise ValueError("A canonical_bundle artifact must use JSON format.")
        bundle_path = Path(canonical_record["path"])
        bundle_hash = _sha256(bundle_path)
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Canonical bundle artifact is not valid JSON: {exc}") from exc
        bundle_validation = validate_canonical_bundle(bundle)
        if not bundle_validation.get("valid"):
            raise ValueError(
                "Adapter canonical_bundle failed structural/reference validation: "
                + json.dumps(bundle_validation.get("errors", [])[:20], ensure_ascii=False)
            )
        if _sha256(bundle_path) != bundle_hash:
            raise RuntimeError("Canonical bundle changed while preparing the handoff.")
        canonical_record = {
            **canonical_record,
            "validation": {
                "valid": True,
                "counts": bundle_validation.get("counts", {}),
                "warning_count": bundle_validation.get("warning_count", 0),
                "validation_scope": bundle_validation.get("validation_scope"),
            },
        }
        route = "CANONICAL_BUNDLE"
        standardized = [
            item for item in artifacts
            if item["role"] == "standardized_dataset" and item["format"] in {"csv", "json"}
        ]
        if any(item["role"] == "standardized_dataset" and item["format"] not in {"csv", "json"} for item in artifacts):
            warnings.append("Some standardized_dataset artifacts are not directly supported by the CSV/JSON structural audit.")
    else:
        standardized_all = [item for item in artifacts if item["role"] == "standardized_dataset"]
        standardized = [item for item in standardized_all if item["format"] in {"csv", "json"}]
        unsupported = [item for item in standardized_all if item["format"] not in {"csv", "json"}]
        if unsupported:
            warnings.append(
                "Unsupported standardized_dataset formats were not routed to dor audit: "
                + ", ".join(item["artifact_id"] for item in unsupported)
            )
        if not standardized:
            raise ValueError(
                "The package must provide one JSON canonical_bundle or at least one "
                "CSV/JSON standardized_dataset artifact."
            )
        route = "STRUCTURED_DATASET"

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "valid": True,
        "route": route,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "package_id": payload["package_id"],
        "adapter": payload["adapter"],
        "package_root": str(root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "sources": sources,
        "artifacts": artifacts,
        "standardized_datasets": standardized,
        "canonical_bundle": canonical_record,
        "warnings": warnings,
        "interpretation_boundary": (
            "PACKAGE_INTEGRITY_AND_CANONICAL_STRUCTURE_ONLY; "
            "NO_EXTRACTION_QUALITY_OR_SCIENTIFIC_SEMANTICS_APPROVED"
        ),
    }
    if output_path is not None:
        output = output_path.expanduser().resolve()
        if output == manifest_path or output.is_relative_to(root):
            raise ValueError("Adapter handoff output must be outside the protected package root.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def load_validated_adapter_handoff(handoff_path: Path) -> dict[str, Any]:
    """Load a handoff and re-check its manifest, declared paths, and exact file hashes."""
    handoff_path = handoff_path.expanduser().resolve()
    try:
        handoff = json.loads(handoff_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Adapter handoff must be readable JSON: {exc}") from exc
    if not isinstance(handoff, dict) or handoff.get("schema_version") != "1.0" or handoff.get("valid") is not True:
        raise ValueError("Adapter handoff is invalid or has an unsupported schema version.")

    manifest_path = Path(handoff.get("manifest_path", ""))
    if not manifest_path.is_file() or _sha256(manifest_path) != handoff.get("manifest_sha256"):
        raise ValueError("Adapter manifest is missing or differs from the handoff SHA-256.")
    package_root = Path(handoff.get("package_root", "")).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    expected_sources, expected_artifacts = _resolve_package_records(payload, package_root)

    for label, expected, supplied in (
        ("sources", expected_sources, handoff.get("sources")),
        ("artifacts", expected_artifacts, handoff.get("artifacts")),
    ):
        if not isinstance(supplied, list) or len(supplied) != len(expected):
            raise ValueError(f"Adapter handoff {label} do not match the package manifest.")
        expected_by_id = {
            item.get("source_id", item.get("artifact_id")): item for item in expected
        }
        supplied_by_id = {
            item.get("source_id", item.get("artifact_id")): item for item in supplied
            if isinstance(item, dict)
        }
        if set(expected_by_id) != set(supplied_by_id):
            raise ValueError(f"Adapter handoff {label} identifiers do not match the package manifest.")
        for identifier, expected_item in expected_by_id.items():
            supplied_item = supplied_by_id[identifier]
            for field in ("path", "package_path", "format", "sha256"):
                if supplied_item.get(field) != expected_item.get(field):
                    raise ValueError(f"Adapter handoff {label} entry {identifier!r} has a modified {field}.")
            if label == "artifacts" and supplied_item.get("role") != expected_item.get("role"):
                raise ValueError(f"Adapter handoff artifact {identifier!r} has a modified role.")
        _validate_declared_files(expected, f"Adapter {label[:-1]}")

    standardized_expected = [
        item for item in expected_artifacts
        if item["role"] == "standardized_dataset" and item["format"] in {"csv", "json"}
    ]
    if handoff.get("route") == "STRUCTURED_DATASET":
        if handoff.get("canonical_bundle") is not None:
            raise ValueError("Structured-data handoff must not declare a canonical bundle.")
        supplied_datasets = handoff.get("standardized_datasets")
        if not isinstance(supplied_datasets, list) or {
            item.get("artifact_id") for item in supplied_datasets if isinstance(item, dict)
        } != {item["artifact_id"] for item in standardized_expected}:
            raise ValueError("Adapter handoff standardized datasets do not match the package manifest.")
    elif handoff.get("route") == "CANONICAL_BUNDLE":
        canonical_expected = [item for item in expected_artifacts if item["role"] == "canonical_bundle"]
        if len(canonical_expected) != 1:
            raise ValueError("Canonical handoff must resolve to exactly one canonical_bundle.")
        supplied = handoff.get("canonical_bundle")
        if not isinstance(supplied, dict):
            raise ValueError("Canonical handoff lacks its canonical_bundle descriptor.")
        expected = canonical_expected[0]
        for field in ("artifact_id", "path", "package_path", "format", "sha256"):
            if supplied.get(field) != expected.get(field):
                raise ValueError(f"Canonical bundle descriptor has a modified {field}.")
        bundle = json.loads(Path(expected["path"]).read_text(encoding="utf-8-sig"))
        validation = validate_canonical_bundle(bundle)
        if not validation.get("valid"):
            raise ValueError("Canonical bundle no longer passes structural/reference validation.")
    else:
        raise ValueError(f"Unsupported adapter handoff route: {handoff.get('route')!r}.")
    return handoff


def canonical_bundle_from_handoff(handoff_path: Path) -> Path:
    handoff = load_validated_adapter_handoff(handoff_path)
    if handoff["route"] != "CANONICAL_BUNDLE" or not isinstance(handoff.get("canonical_bundle"), dict):
        raise ValueError("This adapter handoff does not provide a validated canonical_bundle.")
    return Path(handoff["canonical_bundle"]["path"])
