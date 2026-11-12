"""Validation of explicit, human-reviewed source-to-canonical mapping plans."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

STATUSES = {"PROPOSED", "REVIEWED", "APPROVED", "REJECTED", "UNRESOLVED"}
ENTITIES = {"studies", "systems", "conditions", "experiments", "observations", "comparisons", "evidence"}
TRANSFORMS = {"IDENTITY", "NUMERIC_PARSE", "UNIT_CONVERSION", "LOOKUP", "SPLIT", "CUSTOM"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _validate_transform(rule: dict[str, Any], path: str, errors: list[dict[str, str]]) -> None:
    transform = rule.get("transformation")
    if not isinstance(transform, dict):
        errors.append(_issue("APPROVED_TRANSFORM_REQUIRED", path, "Approved mapping requires an explicit transformation object."))
        return
    kind = transform.get("type")
    params = transform.get("parameters")
    if not isinstance(kind, str) or kind not in TRANSFORMS:
        errors.append(_issue("UNKNOWN_TRANSFORMATION", f"{path}.type", "Transformation type is not supported."))
        return
    if not isinstance(params, dict):
        errors.append(_issue("TRANSFORM_PARAMETERS_NOT_OBJECT", f"{path}.parameters", "Transformation parameters must be an object."))
        return
    if kind == "IDENTITY" and params:
        errors.append(_issue("IDENTITY_HAS_PARAMETERS", f"{path}.parameters", "IDENTITY must not silently apply conversion parameters."))
    elif kind == "UNIT_CONVERSION":
        required = {"source_unit", "target_unit", "factor"}
        missing = required - params.keys()
        if missing:
            errors.append(_issue("INCOMPLETE_UNIT_CONVERSION", f"{path}.parameters", f"UNIT_CONVERSION requires: {', '.join(sorted(missing))}."))
        factor = params.get("factor")
        offset = params.get("offset", 0)
        if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not math.isfinite(factor):
            errors.append(_issue("INVALID_CONVERSION_FACTOR", f"{path}.parameters.factor", "Conversion factor must be a finite number."))
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            errors.append(_issue("INVALID_CONVERSION_OFFSET", f"{path}.parameters.offset", "Conversion offset must be a finite number."))
        for key in ("source_unit", "target_unit"):
            if key in params and (not isinstance(params[key], str) or not params[key].strip()):
                errors.append(_issue("INVALID_CONVERSION_UNIT", f"{path}.parameters.{key}", "Unit labels must be non-empty strings."))
    elif kind in {"LOOKUP", "SPLIT", "CUSTOM"} and not params:
        errors.append(_issue("TRANSFORM_SPECIFICATION_REQUIRED", f"{path}.parameters", f"{kind} requires explicit parameters or a versioned specification reference."))
    elif kind == "NUMERIC_PARSE":
        decimal = params.get("decimal_separator", ".")
        thousands = params.get("thousands_separator")
        if not isinstance(decimal, str) or decimal not in {".", ","}:
            errors.append(_issue("INVALID_DECIMAL_SEPARATOR", f"{path}.parameters.decimal_separator", "Decimal separator must be '.' or ','."))
        if thousands is not None and (not isinstance(thousands, str) or len(thousands) != 1 or thousands == decimal):
            errors.append(_issue("INVALID_THOUSANDS_SEPARATOR", f"{path}.parameters.thousands_separator", "Thousands separator must be one character distinct from the decimal separator."))


def validate_mapping_plan(plan: Any, inventory: Any, inventory_sha256: str) -> dict[str, Any]:
    """Validate mapping references and approval gates; does not execute transformations."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {"valid": False, "errors": [_issue("PLAN_NOT_OBJECT", "$", "Mapping plan must be a JSON object.")], "warnings": [], "approved_rule_ids": [], "excluded_rule_ids": []}
    if plan.get("schema_version") != "1.0":
        errors.append(_issue("UNSUPPORTED_SCHEMA_VERSION", "schema_version", "Expected schema_version 1.0."))
    if not isinstance(plan.get("mapping_version"), str) or not plan["mapping_version"].strip():
        errors.append(_issue("MISSING_MAPPING_VERSION", "mapping_version", "A non-empty mapping_version is required."))
    if plan.get("source_inventory_sha256") != inventory_sha256:
        errors.append(_issue("STALE_SOURCE_INVENTORY", "source_inventory_sha256", "The plan does not reference the exact supplied source_inventory.json file."))
    items = inventory.get("items") if isinstance(inventory, dict) else None
    if not isinstance(items, list):
        errors.append(_issue("INVALID_SOURCE_INVENTORY", "inventory.items", "Inventory must contain an items array."))
        items = []
    inventory_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        path = f"inventory.items[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("inventory_id"), str) or not item["inventory_id"]:
            errors.append(_issue("INVALID_INVENTORY_ITEM", path, "Each inventory item requires a non-empty inventory_id."))
            continue
        if item["inventory_id"] in inventory_by_id:
            errors.append(_issue("DUPLICATE_INVENTORY_ID", path, f"Duplicate inventory ID {item['inventory_id']}."))
        inventory_by_id[item["inventory_id"]] = item

    rules = plan.get("rules")
    if not isinstance(rules, list):
        errors.append(_issue("RULES_NOT_ARRAY", "rules", "Mapping plan rules must be an array."))
        rules = []
    seen_ids: set[str] = set()
    approved: list[str] = []
    excluded: list[str] = []
    approved_targets: dict[tuple[str, str, str], str] = {}
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(_issue("RULE_NOT_OBJECT", path, "Mapping rule must be an object."))
            continue
        rule_id = rule.get("mapping_rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            errors.append(_issue("MISSING_RULE_ID", path, "mapping_rule_id must be a non-empty string."))
            rule_id = f"<invalid:{index}>"
        elif rule_id in seen_ids:
            errors.append(_issue("DUPLICATE_RULE_ID", f"{path}.mapping_rule_id", f"Duplicate mapping rule ID {rule_id}."))
        seen_ids.add(rule_id)
        status = rule.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(_issue("INVALID_MAPPING_STATUS", f"{path}.status", "Unknown mapping status."))
            excluded.append(rule_id)
            continue
        source_id = rule.get("source_item_id")
        source = inventory_by_id.get(source_id) if isinstance(source_id, str) else None
        if source is None:
            errors.append(_issue("UNKNOWN_SOURCE_ITEM", f"{path}.source_item_id", "Source item is not present in the supplied inventory."))
        if status != "APPROVED":
            excluded.append(rule_id)
            warnings.append(_issue("MAPPING_NOT_APPROVED", f"{path}.status", f"Rule {rule_id} is excluded from canonical construction because its status is {status}."))
            continue
        target_entity = rule.get("target_entity")
        target_field = rule.get("target_field_id")
        if not isinstance(target_entity, str) or target_entity not in ENTITIES:
            errors.append(_issue("INVALID_TARGET_ENTITY", f"{path}.target_entity", "Approved rule requires a supported canonical entity."))
        if not isinstance(target_field, str) or not target_field.strip():
            errors.append(_issue("INVALID_TARGET_FIELD", f"{path}.target_field_id", "Approved rule requires a non-empty canonical field ID."))
        review = rule.get("review")
        if not isinstance(review, dict) or any(not isinstance(review.get(key), str) or not review[key].strip() for key in ("reviewer", "reviewed_at", "decision_note")):
            errors.append(_issue("APPROVAL_METADATA_REQUIRED", f"{path}.review", "Approved rule requires reviewer, reviewed_at, and decision_note."))
        _validate_transform(rule, f"{path}.transformation", errors)
        if source is not None and isinstance(target_entity, str) and isinstance(target_field, str):
            locator_check = {
                "source_file": source.get("source_file"),
                "source_sha256": source.get("source_sha256"),
                "locator_type": source.get("locator_type"),
                "locator": source.get("locator"),
            }
            if any(value is None for value in locator_check.values()):
                errors.append(_issue("INCOMPLETE_SOURCE_PROVENANCE", f"{path}.source_item_id", "Inventory item lacks complete source locator/hash provenance."))
            key = (source_id, target_entity, target_field)
            previous = approved_targets.get(key)
            if previous is not None:
                errors.append(_issue("DUPLICATE_APPROVED_TARGET", path, f"Approved rules {previous} and {rule_id} map the same source item to the same target."))
            else:
                approved_targets[key] = rule_id
        if source is not None and isinstance(target_entity, str) and target_entity in ENTITIES and isinstance(target_field, str) and target_field.strip():
            approved.append(rule_id)

    valid = not errors
    return {
        "valid": valid,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "approved_rule_ids": approved if valid else [],
        "excluded_rule_ids": excluded,
        "approved_rule_count": len(approved) if valid else 0,
        "excluded_rule_count": len(excluded),
        "mapping_version": plan.get("mapping_version"),
        "source_inventory_sha256": inventory_sha256,
        "validation_scope": "MAPPING_REFERENCE_AND_APPROVAL_GATE_ONLY_TRANSFORMATIONS_NOT_EXECUTED",
    }


def validate_mapping_files(plan_path: Path, inventory_path: Path) -> dict[str, Any]:
    with inventory_path.open("r", encoding="utf-8-sig") as handle:
        inventory = json.load(handle)
    with plan_path.open("r", encoding="utf-8-sig") as handle:
        plan = json.load(handle)
    return validate_mapping_plan(plan, inventory, sha256_file(inventory_path))
