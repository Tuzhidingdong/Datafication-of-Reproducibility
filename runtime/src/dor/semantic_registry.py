"""Validated, external semantic metadata registry for generic Canonical attributes.

The registry is an independent, read-only data asset. Applying it creates an
in-memory overlay for one analysis and never edits the Canonical Bundle.
"""
from __future__ import annotations

import copy
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_ENTITY_TYPES = {"TARGET", "TARGET_ENDPOINT", "CONDITION"}
_REVIEW_STATES = {"APPROVED", "PENDING", "REJECTED", "UNREVIEWED"}
_METADATA_FIELDS = {
    "canonical_concept_id", "display_name", "definition", "measurement_basis",
    "measurement_context", "derivation_type", "derived_from", "review_status",
    "reviewer", "reviewed_at", "review_rationale", "source_refs",
}
_UNIT_DEFINITION_FIELDS = {
    "unit_id", "dimension_id", "canonical_unit", "unit_symbols", "review_status",
    "reviewer", "reviewed_at", "review_rationale", "source_refs",
}
_CORE_COMPARISON_FIELDS = (
    "canonical_concept_id", "display_name", "definition", "measurement_basis",
    "measurement_context", "derivation_type", "derived_from", "review_status",
)


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _validate_source_refs(source_refs: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(source_refs, list):
        errors.append(f"{prefix} must be an array.")
        return
    for source_index, source_ref in enumerate(source_refs):
        source_prefix = f"{prefix}[{source_index}]"
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


def _decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def validate_semantic_registry_data(registry: Any) -> dict[str, Any]:
    """Validate semantic and optional unit definitions without interpreting their science."""
    errors: list[str] = []
    if not isinstance(registry, dict):
        return {"valid": False, "errors": ["Registry root must be an object."]}
    schema_version = registry.get("schema_version")
    if schema_version not in {"1.0", "1.1"}:
        errors.append("schema_version must be '1.0' or '1.1'.")
    if not isinstance(registry.get("registry_id"), str) or not registry["registry_id"].strip():
        errors.append("registry_id must be a non-empty string.")
    allowed_root_fields = {"schema_version", "registry_id", "records"}
    if schema_version == "1.1":
        allowed_root_fields.add("unit_definitions")
    if set(registry) - allowed_root_fields:
        errors.append("Registry root contains unsupported fields: " + ", ".join(sorted(set(registry) - allowed_root_fields)) + ".")
    if schema_version == "1.0" and "unit_definitions" in registry:
        errors.append("unit_definitions requires semantic registry schema_version '1.1'.")

    records = registry.get("records")
    if not isinstance(records, list):
        errors.append("records must be an array.")
        records = []

    seen: set[tuple[str, ...]] = set()
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
            errors.append(f"{prefix}.entity_type must be TARGET, TARGET_ENDPOINT, or CONDITION.")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{prefix}.canonical_identifier must be a non-empty exact identifier.")
        elif entity_type in _ENTITY_TYPES:
            if entity_type == "TARGET_ENDPOINT":
                if "endpoint_definition" not in record or "timepoint" not in record:
                    errors.append(f"{prefix} TARGET_ENDPOINT requires exact endpoint_definition and timepoint fields.")
                endpoint = record.get("endpoint_definition")
                timepoint = record.get("timepoint")
                if endpoint is not None and not isinstance(endpoint, str):
                    errors.append(f"{prefix}.endpoint_definition must be a string or null.")
                if timepoint is not None and (isinstance(timepoint, bool) or not isinstance(timepoint, (str, int, float))):
                    errors.append(f"{prefix}.timepoint must be a string, number, or null.")
                key = (entity_type, identifier, _json_key(endpoint), _json_key(timepoint))
            else:
                if "endpoint_definition" in record or "timepoint" in record:
                    errors.append(f"{prefix} endpoint_definition/timepoint are only valid for TARGET_ENDPOINT.")
                key = (entity_type, identifier)
            if key in seen:
                errors.append(f"{prefix} duplicates {entity_type} scope for identifier {identifier!r}.")
            seen.add(key)
        allowed_record_fields = {"entity_type", "canonical_identifier", "semantic_metadata"}
        if entity_type == "TARGET_ENDPOINT":
            allowed_record_fields |= {"endpoint_definition", "timepoint"}
        if set(record) - allowed_record_fields:
            errors.append(f"{prefix} contains unsupported fields: {', '.join(sorted(set(record) - allowed_record_fields))}.")
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
        if "source_refs" in metadata:
            _validate_source_refs(metadata["source_refs"], f"{prefix}.semantic_metadata.source_refs", errors)
        if review_status == "APPROVED":
            approved_count += 1
            for field in ("canonical_concept_id", "reviewer", "reviewed_at", "review_rationale"):
                if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                    errors.append(f"{prefix}.semantic_metadata.{field} is required for APPROVED metadata.")
            if not isinstance(metadata.get("source_refs"), list) or not metadata["source_refs"]:
                errors.append(f"{prefix}.semantic_metadata.source_refs requires at least one hash-bound source reference for APPROVED metadata.")

    unit_definitions = registry.get("unit_definitions", []) if schema_version == "1.1" else []
    if not isinstance(unit_definitions, list):
        errors.append("unit_definitions must be an array in schema version 1.1.")
        unit_definitions = []
    seen_unit_ids: set[str] = set()
    seen_dimension_ids: set[str] = set()
    seen_symbols: set[str] = set()
    approved_unit_count = 0
    for index, definition in enumerate(unit_definitions):
        prefix = f"unit_definitions[{index}]"
        if not isinstance(definition, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        unknown = sorted(set(definition) - _UNIT_DEFINITION_FIELDS)
        if unknown:
            errors.append(f"{prefix} contains unsupported fields: {', '.join(unknown)}.")
        for field in ("unit_id", "dimension_id", "canonical_unit"):
            value = definition.get(field)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty exact string without surrounding whitespace.")
        unit_id = definition.get("unit_id")
        dimension_id = definition.get("dimension_id")
        if isinstance(unit_id, str) and unit_id:
            if unit_id in seen_unit_ids:
                errors.append(f"{prefix}.unit_id duplicates {unit_id!r}.")
            seen_unit_ids.add(unit_id)
        if isinstance(dimension_id, str) and dimension_id:
            if dimension_id in seen_dimension_ids:
                errors.append(f"{prefix}.dimension_id duplicates {dimension_id!r}; define one conversion table per dimension.")
            seen_dimension_ids.add(dimension_id)
        symbols = definition.get("unit_symbols")
        if not isinstance(symbols, list) or not symbols:
            errors.append(f"{prefix}.unit_symbols must be a non-empty array.")
            symbols = []
        canonical_rows: list[tuple[Decimal, Decimal]] = []
        for symbol_index, symbol in enumerate(symbols):
            symbol_prefix = f"{prefix}.unit_symbols[{symbol_index}]"
            if not isinstance(symbol, dict):
                errors.append(f"{symbol_prefix} must be an object.")
                continue
            if set(symbol) - {"symbol", "scale_to_canonical", "offset_to_canonical"}:
                errors.append(f"{symbol_prefix} contains unsupported fields.")
            name = symbol.get("symbol")
            if not isinstance(name, str) or not name.strip() or name != name.strip():
                errors.append(f"{symbol_prefix}.symbol must be a non-empty exact string without surrounding whitespace.")
            elif name in seen_symbols:
                errors.append(f"{symbol_prefix}.symbol duplicates the globally defined symbol {name!r}.")
            elif isinstance(name, str):
                seen_symbols.add(name)
            raw_scale = symbol.get("scale_to_canonical")
            raw_offset = symbol.get("offset_to_canonical", 0)
            scale = _decimal_value(raw_scale) if isinstance(raw_scale, (int, float)) and not isinstance(raw_scale, bool) else None
            offset = _decimal_value(raw_offset) if isinstance(raw_offset, (int, float)) and not isinstance(raw_offset, bool) else None
            if scale is None or scale <= 0:
                errors.append(f"{symbol_prefix}.scale_to_canonical must be a finite positive number.")
            if offset is None:
                errors.append(f"{symbol_prefix}.offset_to_canonical must be a finite number when supplied.")
            if name == definition.get("canonical_unit") and scale is not None and offset is not None:
                canonical_rows.append((scale, offset))
        if not any(
            isinstance(symbol, dict) and symbol.get("symbol") == definition.get("canonical_unit")
            for symbol in symbols
        ):
            errors.append(f"{prefix}.canonical_unit must appear in unit_symbols.")
        if canonical_rows != [(Decimal("1"), Decimal("0"))]:
            errors.append(f"{prefix}.canonical_unit must have scale_to_canonical=1 and offset_to_canonical=0.")
        review_status = definition.get("review_status")
        if review_status not in _REVIEW_STATES:
            errors.append(f"{prefix}.review_status is invalid.")
        if "source_refs" in definition:
            _validate_source_refs(definition["source_refs"], f"{prefix}.source_refs", errors)
        if review_status == "APPROVED":
            approved_unit_count += 1
            for field in ("reviewer", "reviewed_at", "review_rationale"):
                if not isinstance(definition.get(field), str) or not definition[field].strip():
                    errors.append(f"{prefix}.{field} is required for APPROVED unit definitions.")
            if not isinstance(definition.get("source_refs"), list) or not definition["source_refs"]:
                errors.append(f"{prefix}.source_refs requires at least one hash-bound source reference for APPROVED unit definitions.")

    return {
        "valid": not errors,
        "schema_version": schema_version,
        "registry_id": registry.get("registry_id"),
        "record_count": len(records),
        "approved_record_count": approved_count,
        "unit_definition_count": len(unit_definitions),
        "approved_unit_definition_count": approved_unit_count,
        "approved_unit_symbol_count": sum(
            len(item.get("unit_symbols", []))
            for item in unit_definitions
            if isinstance(item, dict) and item.get("review_status") == "APPROVED"
        ),
        "errors": errors,
    }


def approved_unit_symbol_lookup(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return exact symbol definitions from approved v1.1 unit definitions only."""
    if registry is None:
        return {}
    report = validate_semantic_registry_data(registry)
    if not report["valid"]:
        raise ValueError("Semantic Registry validation failed: " + "; ".join(report["errors"][:12]))
    if registry.get("schema_version") != "1.1":
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for definition in registry.get("unit_definitions", []):
        if definition.get("review_status") != "APPROVED":
            continue
        for symbol in definition["unit_symbols"]:
            lookup[symbol["symbol"]] = {
                "unit_id": definition["unit_id"],
                "dimension_id": definition["dimension_id"],
                "canonical_unit": definition["canonical_unit"],
                "scale_to_canonical": str(symbol["scale_to_canonical"]),
                "offset_to_canonical": str(symbol.get("offset_to_canonical", 0)),
            }
    return lookup


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
    """Apply exact-scope reviewed metadata to an in-memory copy, never the source Bundle."""
    report = validate_semantic_registry_data(registry)
    if not report["valid"]:
        raise ValueError("Semantic Registry validation failed: " + "; ".join(report["errors"][:12]))
    result = copy.deepcopy(bundle)
    target_records: dict[str, dict[str, Any]] = {}
    endpoint_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    condition_records: dict[str, dict[str, Any]] = {}
    for record in registry["records"]:
        entity_type = record["entity_type"]
        identifier = record["canonical_identifier"]
        metadata = record["semantic_metadata"]
        if entity_type == "TARGET":
            target_records[identifier] = metadata
        elif entity_type == "TARGET_ENDPOINT":
            endpoint_records[(
                identifier,
                _json_key(record.get("endpoint_definition")),
                _json_key(record.get("timepoint")),
            )] = metadata
        else:
            condition_records[identifier] = metadata

    matched_targets: set[str] = set()
    matched_endpoint_scopes: set[tuple[str, str, str]] = set()
    matched_conditions: set[str] = set()

    for item in result.get("observations", []):
        identifier = item.get("target_id")
        endpoint_key = (
            identifier,
            _json_key(item.get("endpoint_definition")),
            _json_key(item.get("timepoint")),
        )
        endpoint_metadata = endpoint_records.get(endpoint_key)
        target_metadata = target_records.get(identifier)
        if target_metadata is not None:
            matched_targets.add(identifier)
        if endpoint_metadata is not None:
            matched_endpoint_scopes.add(endpoint_key)
        effective_metadata = {**(target_metadata or {}), **(endpoint_metadata or {})}
        if not effective_metadata:
            continue
        existing = item.get("semantic_metadata")
        if existing is not None and not isinstance(existing, dict):
            raise ValueError(f"Canonical semantic_metadata for TARGET:{identifier!r} is not an object.")
        existing = existing or {}
        conflicts = [
            field for field in _CORE_COMPARISON_FIELDS
            if field in existing and field in effective_metadata and existing[field] != effective_metadata[field]
        ]
        if conflicts:
            raise ValueError(
                f"Semantic Registry conflicts with inline Canonical metadata for TARGET:{identifier!r}: "
                + ", ".join(conflicts)
            )
        item["semantic_metadata"] = {**existing, **effective_metadata}

    for item in result.get("conditions", []):
        identifier = item.get("condition_type")
        metadata = condition_records.get(identifier)
        if metadata is None:
            continue
        matched_conditions.add(identifier)
        existing = item.get("semantic_metadata")
        if existing is not None and not isinstance(existing, dict):
            raise ValueError(f"Canonical semantic_metadata for CONDITION:{identifier!r} is not an object.")
        existing = existing or {}
        conflicts = [
            field for field in _CORE_COMPARISON_FIELDS
            if field in existing and field in metadata and existing[field] != metadata[field]
        ]
        if conflicts:
            raise ValueError(
                f"Semantic Registry conflicts with inline Canonical metadata for CONDITION:{identifier!r}: "
                + ", ".join(conflicts)
            )
        item["semantic_metadata"] = {**existing, **metadata}

    missing_targets = sorted(set(target_records) - matched_targets)
    missing_conditions = sorted(set(condition_records) - matched_conditions)
    missing_endpoints = sorted(set(endpoint_records) - matched_endpoint_scopes)
    missing = (
        [f"TARGET:{item}" for item in missing_targets]
        + [f"CONDITION:{item}" for item in missing_conditions]
        + [f"TARGET_ENDPOINT:{item[0]}:{item[1]}:{item[2]}" for item in missing_endpoints]
    )
    if missing:
        raise ValueError("Semantic Registry entries do not match any Canonical records: " + "; ".join(missing[:12]))

    summary = {
        "status": (
            "VALIDATED_EMPTY_REGISTRY" if not registry["records"]
            else "VALIDATED_AND_APPLIED_IN_MEMORY"
        ),
        "registry_id": registry["registry_id"],
        "record_count": len(registry["records"]),
        "approved_record_count": report["approved_record_count"],
        "applied_record_count": len(matched_targets) + len(matched_endpoint_scopes) + len(matched_conditions),
        "target_record_count": len(matched_targets),
        "target_endpoint_record_count": len(matched_endpoint_scopes),
        "condition_record_count": len(matched_conditions),
        "bundle_modified": False,
        "source_locators_dereferenced": False,
    }
    return result, summary
