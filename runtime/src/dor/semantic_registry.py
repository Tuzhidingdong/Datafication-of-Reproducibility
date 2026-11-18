"""Validated, external semantic metadata registry for generic Canonical attributes.

The registry is an independent, read-only data asset. Applying it creates an
in-memory overlay for one analysis and never edits the Canonical Bundle.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_ENTITY_TYPES = {"TARGET", "CONDITION"}
_REVIEW_STATES = {"APPROVED", "PENDING", "REJECTED", "UNREVIEWED"}
_METADATA_FIELDS = {
    "canonical_concept_id", "display_name", "definition", "measurement_basis",
    "measurement_context", "derivation_type", "derived_from", "review_status",
    "reviewer", "reviewed_at", "review_rationale", "source_refs",
}
_CORE_COMPARISON_FIELDS = (
    "canonical_concept_id", "display_name", "definition", "measurement_basis",
    "measurement_context", "derivation_type", "derived_from", "review_status",
)


def validate_semantic_registry_data(registry: Any) -> dict[str, Any]:
    """Validate registry structure and provenance without interpreting its science."""
    errors: list[str] = []
    if not isinstance(registry, dict):
        return {"valid": False, "errors": ["Registry root must be an object."]}
    if registry.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'.")
    if not isinstance(registry.get("registry_id"), str) or not registry["registry_id"].strip():
        errors.append("registry_id must be a non-empty string.")
    records = registry.get("records")
    if not isinstance(records, list):
        errors.append("records must be an array.")
        records = []

    seen: set[tuple[str, str]] = set()
    approved_count = 0
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        entity_type = record.get("entity_type")
        identifier = record.get("canonical_identifier")
        metadata = record.get("semantic_metadata")
        if entity_type not in _ENTITY_TYPES:
            errors.append(f"{prefix}.entity_type must be TARGET or CONDITION.")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{prefix}.canonical_identifier must be a non-empty exact identifier.")
        elif entity_type in _ENTITY_TYPES:
            key = (entity_type, identifier)
            if key in seen:
                errors.append(f"{prefix} duplicates {entity_type} identifier {identifier!r}.")
            seen.add(key)
        if not isinstance(metadata, dict):
            errors.append(f"{prefix}.semantic_metadata must be an object.")
            continue
        unknown = sorted(set(metadata) - _METADATA_FIELDS)
        if unknown:
            errors.append(f"{prefix}.semantic_metadata has unsupported fields: {', '.join(unknown)}.")
        review_status = metadata.get("review_status")
        if review_status not in _REVIEW_STATES:
            errors.append(f"{prefix}.semantic_metadata.review_status is invalid.")
        if metadata.get("derivation_type") not in (None, "MEASURED", "CALCULATED", "UNKNOWN"):
            errors.append(f"{prefix}.semantic_metadata.derivation_type is invalid.")
        if "derived_from" in metadata and (
            not isinstance(metadata["derived_from"], list)
            or any(not isinstance(item, str) or not item for item in metadata["derived_from"])
        ):
            errors.append(f"{prefix}.semantic_metadata.derived_from must be an array of exact non-empty identifiers.")
        if "source_refs" in metadata and not isinstance(metadata["source_refs"], list):
            errors.append(f"{prefix}.semantic_metadata.source_refs must be an array.")
        source_refs = metadata.get("source_refs", [])
        if isinstance(source_refs, list):
            for source_index, source_ref in enumerate(source_refs):
                source_prefix = f"{prefix}.semantic_metadata.source_refs[{source_index}]"
                if not isinstance(source_ref, dict):
                    errors.append(f"{source_prefix} must be an object.")
                    continue
                if not isinstance(source_ref.get("source_id"), str) or not source_ref["source_id"].strip():
                    errors.append(f"{source_prefix}.source_id is required.")
                if not isinstance(source_ref.get("source_sha256"), str) or not _SHA256.fullmatch(source_ref["source_sha256"]):
                    errors.append(f"{source_prefix}.source_sha256 must be a 64-character SHA-256 hex string.")
                if not isinstance(source_ref.get("locator"), str) or not source_ref["locator"].strip():
                    errors.append(f"{source_prefix}.locator is required and remains an opaque reference.")
                if set(source_ref) - {"source_id", "source_sha256", "locator"}:
                    errors.append(f"{source_prefix} contains unsupported fields.")
        if review_status == "APPROVED":
            approved_count += 1
            for field in ("canonical_concept_id", "reviewer", "reviewed_at", "review_rationale"):
                if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                    errors.append(f"{prefix}.semantic_metadata.{field} is required for APPROVED metadata.")
            if not source_refs:
                errors.append(f"{prefix}.semantic_metadata.source_refs requires at least one hash-bound source reference for APPROVED metadata.")

    return {
        "valid": not errors,
        "registry_id": registry.get("registry_id"),
        "record_count": len(records),
        "approved_record_count": approved_count,
        "errors": errors,
    }


def load_semantic_registry(path: Path) -> dict[str, Any]:
    """Load and validate a registry file without dereferencing its source locators."""
    path = path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    report = validate_semantic_registry_data(payload)
    if not report["valid"]:
        raise ValueError("Semantic Registry validation failed: " + "; ".join(report["errors"][:12]))
    return payload


def validate_semantic_registry_file(path: Path) -> dict[str, Any]:
    """Return a deterministic validation report for a registry file."""
    path = path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"valid": False, "registry_path": str(path), "errors": [str(exc)]}
    report = validate_semantic_registry_data(payload)
    return {**report, "registry_path": str(path)}


def overlay_semantic_registry(
    bundle: dict[str, Any], registry: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply reviewed metadata to an in-memory copy, keyed by exact canonical IDs."""
    report = validate_semantic_registry_data(registry)
    if not report["valid"]:
        raise ValueError("Semantic Registry validation failed: " + "; ".join(report["errors"][:12]))
    result = copy.deepcopy(bundle)
    applied: list[tuple[str, str]] = []
    for record in registry["records"]:
        entity_type = record["entity_type"]
        identifier = record["canonical_identifier"]
        key_field = "target_id" if entity_type == "TARGET" else "condition_type"
        collection = "observations" if entity_type == "TARGET" else "conditions"
        matches = [
            item for item in result.get(collection, [])
            if item.get(key_field) == identifier
        ]
        if not matches:
            raise ValueError(
                f"Semantic Registry entry {entity_type}:{identifier!r} does not match any Canonical record."
            )
        metadata = record["semantic_metadata"]
        for item in matches:
            existing = item.get("semantic_metadata")
            if existing is not None and not isinstance(existing, dict):
                raise ValueError(f"Canonical semantic_metadata for {entity_type}:{identifier!r} is not an object.")
            existing = existing or {}
            conflicts = [
                field for field in _CORE_COMPARISON_FIELDS
                if field in existing and field in metadata and existing[field] != metadata[field]
            ]
            if conflicts:
                raise ValueError(
                    f"Semantic Registry conflicts with inline metadata for {entity_type}:{identifier!r}: "
                    + ", ".join(conflicts)
                )
            item["semantic_metadata"] = {**existing, **metadata}
        applied.append((entity_type, identifier))

    summary = {
        "status": "VALIDATED_AND_APPLIED_IN_MEMORY",
        "registry_id": registry["registry_id"],
        "record_count": len(registry["records"]),
        "approved_record_count": report["approved_record_count"],
        "applied_record_count": len(applied),
        "target_record_count": sum(entity_type == "TARGET" for entity_type, _ in applied),
        "condition_record_count": sum(entity_type == "CONDITION" for entity_type, _ in applied),
        "bundle_modified": False,
        "source_locators_dereferenced": False,
    }
    return result, summary
