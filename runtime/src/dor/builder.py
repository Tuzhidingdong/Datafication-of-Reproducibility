"""Deterministic canonical bundle construction from approved CSV mappings."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.mapping import sha256_file, validate_mapping_plan

ENTITIES = {"studies", "systems", "conditions", "experiments", "observations", "comparisons", "evidence"}
ID_FIELDS = {"studies":"study_id", "systems":"system_id", "conditions":"condition_id",
             "experiments":"experiment_id", "observations":"observation_id",
             "comparisons":"comparison_id", "evidence":"evidence_id"}
RELATIONSHIPS = {
    ("systems", "study_ids", "studies"): "MANY",
    ("conditions", "system_ids", "systems"): "MANY",
    ("experiments", "study_id", "studies"): "ONE",
    ("experiments", "system_id", "systems"): "ONE",
    ("experiments", "condition_ids", "conditions"): "MANY",
    ("observations", "experiment_id", "experiments"): "ONE",
    ("observations", "evidence_ids", "evidence"): "MANY",
    ("comparisons", "observation_ids", "observations"): "MANY",
    ("evidence", "study_id", "studies"): "ONE",
}
GENERATED_FIELDS = {
    "studies": {"study_id", "source_locators"},
    "systems": {"system_id", "study_ids"},
    "conditions": {"condition_id", "system_ids"},
    "experiments": {"experiment_id", "study_id", "system_id", "condition_ids"},
    "observations": {"observation_id", "experiment_id", "evidence_ids"},
    "comparisons": {"comparison_id", "observation_ids"},
    "evidence": {"evidence_id", "study_id", "source_locator"},
}


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _parse_numeric(raw: str, params: dict[str, Any]) -> int | float:
    decimal_sep = params.get("decimal_separator", ".")
    thousands_sep = params.get("thousands_separator")
    value = raw.strip()
    if thousands_sep:
        value = value.replace(thousands_sep, "")
    if decimal_sep == ",":
        value = value.replace(",", ".")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse numeric value {raw!r}.") from exc
    if not number.is_finite():
        raise ValueError(f"Numeric value is not finite: {raw!r}.")
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _transform(raw: str, spec: dict[str, Any]) -> Any:
    kind = spec.get("type")
    params = spec.get("parameters", {})
    if raw == "":
        return None
    if kind == "IDENTITY":
        return raw
    if kind == "NUMERIC_PARSE":
        return _parse_numeric(raw, params)
    if kind == "UNIT_CONVERSION":
        number = Decimal(str(_parse_numeric(raw, params)))
        factor = Decimal(str(params["factor"]))
        offset = Decimal(str(params.get("offset", 0)))
        result = number * factor + offset
        if not result.is_finite():
            raise ValueError("Unit conversion produced a non-finite value.")
        if result == result.to_integral_value():
            return int(result)
        return float(result)
    if kind == "LOOKUP":
        table = params.get("mapping")
        if not isinstance(table, dict) or raw not in table:
            raise ValueError(f"LOOKUP has no explicit mapping for value {raw!r}.")
        return table[raw]
    if kind == "SPLIT":
        delimiter = params.get("delimiter")
        if not isinstance(delimiter, str) or not delimiter:
            raise ValueError("SPLIT requires a non-empty delimiter.")
        parts = raw.split(delimiter, params.get("maxsplit", -1))
        if params.get("strip_items", True):
            parts = [part.strip() for part in parts]
        if not params.get("keep_empty", False):
            parts = [part for part in parts if part != ""]
        return parts
    raise ValueError(f"Transformation {kind!r} is not executable by this builder.")


def _canonical_id(source_sha: str, definition_id: str, key: list[Any]) -> str:
    payload = json.dumps([source_sha, definition_id, key], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()
    return "DOR_" + digest


def _read_csv(path: Path, expected_hash: str) -> tuple[list[str], list[dict[str, str]]]:
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(f"Source hash mismatch for {path.name}; inventory is stale.")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"CSV has no header: {path.name}") from exc
        if not header or any(not name.strip() for name in header) or len(set(header)) != len(header):
            raise ValueError(f"CSV header is empty, contains blank names, or has duplicate names: {path.name}")
        rows: list[dict[str, str]] = []
        for row_number, values in enumerate(reader, start=1):
            if len(values) != len(header):
                raise ValueError(f"CSV row {row_number} in {path.name} has {len(values)} cells; expected {len(header)}.")
            rows.append(dict(zip(header, values)))
    if sha256_file(path) != expected_hash:
        raise ValueError(f"Source changed while being read: {path.name}")
    return header, rows


def _safe_source_path(root: Path, file_name: str) -> Path:
    root = root.expanduser().resolve()
    path = (root / file_name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Source file path escapes source root: {file_name}")
    return path


def _validate_build_spec(spec: Any, mapping_plan: dict[str, Any], inventory: dict[str, Any],
                         mapping_validation: dict[str, Any], plan_hash: str, inventory_hash: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(spec, dict):
        return [_issue("BUILD_SPEC_NOT_OBJECT", "$", "Build specification must be a JSON object.")]
    if spec.get("schema_version") != "1.0":
        errors.append(_issue("UNSUPPORTED_SCHEMA_VERSION", "schema_version", "Expected build spec schema_version 1.0."))
    for field, actual in (("mapping_plan_sha256", plan_hash), ("source_inventory_sha256", inventory_hash)):
        if spec.get(field) != actual:
            errors.append(_issue("STALE_BUILD_SPEC", field, f"Build specification must reference exact {field}."))    
    if spec.get("mapping_version") != mapping_plan.get("mapping_version"):
        errors.append(_issue("MAPPING_VERSION_MISMATCH", "mapping_version", "Build spec and mapping plan versions differ."))
    if not isinstance(spec.get("project_id"), str) or not spec["project_id"].strip():
        errors.append(_issue("MISSING_PROJECT_ID", "project_id", "A non-empty project_id is required."))
    inventory_items = inventory.get("items", []) if isinstance(inventory, dict) else []
    item_by_id = {item.get("inventory_id"): item for item in inventory_items if isinstance(item, dict)}
    rule_by_id = {rule.get("mapping_rule_id"): rule for rule in mapping_plan.get("rules", []) if isinstance(rule, dict)}
    approved_ids = set(mapping_validation.get("approved_rule_ids", []))
    definitions = spec.get("entity_definitions")
    if not isinstance(definitions, list) or not definitions:
        errors.append(_issue("ENTITY_DEFINITIONS_REQUIRED", "entity_definitions", "At least one entity definition is required."))
        definitions = []
    def_by_id: dict[str, dict[str, Any]] = {}
    for index, definition in enumerate(definitions):
        path = f"entity_definitions[{index}]"
        if not isinstance(definition, dict):
            errors.append(_issue("ENTITY_DEFINITION_NOT_OBJECT", path, "Entity definition must be an object."))
            continue
        did = definition.get("definition_id")
        etype = definition.get("entity_type")
        if not isinstance(did, str) or not did.strip():
            errors.append(_issue("INVALID_DEFINITION_ID", path, "definition_id must be a non-empty string."))
            continue
        if did in def_by_id:
            errors.append(_issue("DUPLICATE_DEFINITION_ID", path, f"Duplicate definition_id {did}."))
        def_by_id[did] = definition
        if not isinstance(etype, str) or etype not in ENTITIES:
            errors.append(_issue("INVALID_ENTITY_TYPE", f"{path}.entity_type", "Unsupported canonical entity type."))
        source_file = definition.get("source_file")
        grouping = definition.get("grouping")
        if not isinstance(source_file, str) or not source_file:
            errors.append(_issue("INVALID_SOURCE_FILE", f"{path}.source_file", "source_file is required."))
        if not isinstance(grouping, dict) or grouping.get("mode") not in {"SOURCE_ROW", "GROUP_BY_FIELDS"}:
            errors.append(_issue("INVALID_GROUPING", f"{path}.grouping", "Grouping mode must be SOURCE_ROW or GROUP_BY_FIELDS."))
            grouping = {}
        key_ids = grouping.get("source_item_ids", [])
        if not isinstance(key_ids, list) or any(not isinstance(x, str) for x in key_ids):
            errors.append(_issue("INVALID_GROUP_KEYS", f"{path}.grouping.source_item_ids", "Grouping source_item_ids must be an array of IDs."))
            key_ids = []
        if grouping.get("mode") == "SOURCE_ROW" and key_ids:
            errors.append(_issue("SOURCE_ROW_HAS_KEYS", f"{path}.grouping.source_item_ids", "SOURCE_ROW grouping must not declare key fields."))
        if grouping.get("mode") == "GROUP_BY_FIELDS" and not key_ids:
            errors.append(_issue("GROUP_KEYS_REQUIRED", f"{path}.grouping.source_item_ids", "GROUP_BY_FIELDS requires at least one explicit key field."))
        for source_id in key_ids:
            item = item_by_id.get(source_id)
            if not item or item.get("source_file") != source_file or item.get("locator_type") != "csv_column" or item.get("source_format") != "csv":
                errors.append(_issue("INVALID_GROUP_KEY_SOURCE", f"{path}.grouping.source_item_ids", f"{source_id} is not a CSV column from {source_file}."))
        field_rule_ids = definition.get("field_rule_ids")
        if not isinstance(field_rule_ids, list):
            errors.append(_issue("FIELD_RULES_NOT_ARRAY", f"{path}.field_rule_ids", "field_rule_ids must be an array; it may be empty when all fields are generated by declared relationships."))
            field_rule_ids = []
        seen_fields: set[str] = set()
        for rule_id in field_rule_ids:
            rule = rule_by_id.get(rule_id)
            if rule_id not in approved_ids or not rule:
                errors.append(_issue("RULE_NOT_ELIGIBLE", f"{path}.field_rule_ids", f"{rule_id} is not an approved, validated mapping rule."))
                continue
            source_item = item_by_id.get(rule.get("source_item_id"))
            if rule.get("target_entity") != etype:
                errors.append(_issue("RULE_ENTITY_MISMATCH", f"{path}.field_rule_ids", f"{rule_id} targets {rule.get('target_entity')}, not {etype}."))
            if not source_item or source_item.get("source_file") != source_file or source_item.get("source_format") != "csv" or source_item.get("locator_type") != "csv_column":
                errors.append(_issue("UNSUPPORTED_OR_MISMATCHED_SOURCE", f"{path}.field_rule_ids", f"{rule_id} must reference a CSV column in {source_file}."))
            field_id = rule.get("target_field_id")
            if field_id in seen_fields:
                errors.append(_issue("DUPLICATE_FIELD_RULE", f"{path}.field_rule_ids", f"Multiple rules target {field_id} in this entity definition."))
            seen_fields.add(field_id)
            if field_id in GENERATED_FIELDS.get(etype, set()):
                errors.append(_issue("GENERATED_FIELD_CANNOT_BE_MAPPED", f"{path}.field_rule_ids", f"{field_id} is created by the builder's identity/link contract and cannot be overwritten by a field rule."))
    links = spec.get("links")
    if not isinstance(links, list):
        errors.append(_issue("LINKS_NOT_ARRAY", "links", "links must be an array."))
        links = []
    seen_links: set[tuple[str, str, str]] = set()
    for index, link in enumerate(links):
        path = f"links[{index}]"
        if not isinstance(link, dict):
            errors.append(_issue("LINK_NOT_OBJECT", path, "Link declaration must be an object."))
            continue
        child = def_by_id.get(link.get("child_definition_id"))
        parent = def_by_id.get(link.get("parent_definition_id"))
        if child is None or parent is None:
            errors.append(_issue("UNKNOWN_LINK_DEFINITION", path, "Child and parent definition IDs must exist."))
            continue
        field_id = link.get("field_id")
        expected = (child.get("entity_type"), field_id, parent.get("entity_type"))
        if expected not in RELATIONSHIPS:
            errors.append(_issue("INVALID_CANONICAL_RELATIONSHIP", path, f"Unsupported canonical relationship {expected}."))
        if child.get("source_file") != parent.get("source_file"):
            errors.append(_issue("CROSS_FILE_LINK_UNSUPPORTED", path, "V0.2 builder supports row-overlap links within one source CSV only."))
        key = (link.get("child_definition_id"), link.get("parent_definition_id"), field_id)
        if key in seen_links:
            errors.append(_issue("DUPLICATE_LINK", path, "Duplicate link declaration."))
        seen_links.add(key)
    return errors


def build_canonical_bundle(mapping_plan: Any, inventory: Any, build_spec: Any,
                           source_root: Path, mapping_plan_sha256: str,
                           inventory_sha256: str, build_spec_sha256: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build only from validated APPROVED mappings and explicit entity/link definitions."""
    mapping_validation = validate_mapping_plan(mapping_plan, inventory, inventory_sha256)
    errors = list(mapping_validation.get("errors", []))
    if not mapping_validation.get("valid"):
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_MAPPING_PLAN_INVALID"}
    errors.extend(_validate_build_spec(build_spec, mapping_plan, inventory, mapping_validation, mapping_plan_sha256, inventory_sha256))
    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_SPEC_INVALID"}

    item_by_id = {item["inventory_id"]: item for item in inventory["items"]}
    rule_by_id = {rule["mapping_rule_id"]: rule for rule in mapping_plan["rules"] if rule["mapping_rule_id"] in set(mapping_validation["approved_rule_ids"])}
    source_cache: dict[str, tuple[list[str], list[dict[str, str]], str]] = {}
    for definition in build_spec["entity_definitions"]:
        filename = definition["source_file"]
        if filename in source_cache:
            continue
        matching = [item for item in inventory["items"] if item.get("source_file") == filename]
        hashes = {item.get("source_sha256") for item in matching}
        if not matching or len(hashes) != 1:
            errors.append(_issue("SOURCE_INVENTORY_AMBIGUOUS", filename, "Source file has no inventory items or inconsistent hashes."))
            continue
        digest = next(iter(hashes))
        try:
            path = _safe_source_path(source_root, filename)
            if not path.is_file():
                raise FileNotFoundError(f"Source file not found: {path}")
            header, rows = _read_csv(path, digest)
        except Exception as exc:
            errors.append(_issue("SOURCE_READ_FAILED", filename, str(exc)))
            continue
        source_cache[filename] = (header, rows, digest)
        for item in matching:
            if item.get("locator_type") == "csv_column" and item.get("locator") not in header:
                errors.append(_issue("SOURCE_COLUMN_NOT_FOUND", item.get("inventory_id", filename), f"CSV column {item.get('locator')!r} is absent from current file."))

    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_SOURCE_VALIDATION_FAILED"}

    records_by_definition: dict[str, list[dict[str, Any]]] = {}
    rowsets_by_definition: dict[str, list[set[int]]] = {}
    definitions_by_id = {d["definition_id"]: d for d in build_spec["entity_definitions"]}
    for definition in build_spec["entity_definitions"]:
        filename = definition["source_file"]
        header, rows, digest = source_cache[filename]
        grouping = definition["grouping"]
        key_columns = [item_by_id[sid]["locator"] for sid in grouping.get("source_item_ids", [])]
        groups: dict[tuple[Any, ...], list[int]] = {}
        for row_index, row in enumerate(rows, start=1):
            if grouping["mode"] == "SOURCE_ROW":
                key = ("__SOURCE_ROW__", row_index)
            else:
                values = tuple(row[column] for column in key_columns)
                if any(value == "" for value in values):
                    errors.append(_issue("EMPTY_GROUP_KEY", f"{definition['definition_id']}:row:{row_index}", "A grouping key is blank; refusing to merge or invent an entity identity."))
                    continue
                key = values
            groups.setdefault(key, []).append(row_index)
        records: list[dict[str, Any]] = []
        rowsets: list[set[int]] = []
        entity_type = definition["entity_type"]
        for key, row_numbers in groups.items():
            record: dict[str, Any] = {}
            row_set = set(row_numbers)
            for rule_id in definition["field_rule_ids"]:
                rule = rule_by_id[rule_id]
                item = item_by_id[rule["source_item_id"]]
                column = item["locator"]
                values: list[tuple[str, Any, int]] = []
                for row_number in row_numbers:
                    raw = rows[row_number - 1][column]
                    try:
                        transformed = _transform(raw, rule["transformation"])
                    except Exception as exc:
                        errors.append(_issue("VALUE_TRANSFORM_FAILED", f"{definition['definition_id']}:row:{row_number}:{column}", f"{rule_id}: {exc}"))
                        transformed = None
                    values.append((raw, transformed, row_number))
                non_null = [value for _, value, _ in values if value is not None]
                unique_values = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in non_null}
                has_blank = any(raw == "" for raw, _, _ in values)
                if len(unique_values) > 1 or (has_blank and non_null):
                    errors.append(_issue("GROUP_FIELD_CONFLICT", f"{definition['definition_id']}.{rule['target_field_id']}", f"Values for {rule_id} are not consistent within group {key!r}; define a finer entity grouping instead of selecting one."))
                    continue
                record[rule["target_field_id"]] = non_null[0] if non_null else None
                for raw, transformed, row_number in values:
                    record.setdefault("field_provenance", []).append({
                        "target_field_id": rule["target_field_id"],
                        "mapping_rule_id": rule_id,
                        "source_item_id": item["inventory_id"],
                        "source_file": filename,
                        "source_sha256": digest,
                        "locator_type": "csv_row",
                        "locator": f"data_row:{row_number};column:{column}",
                        "raw_value": raw,
                        "transformed_value": transformed,
                        "transformation": rule["transformation"],
                        "cell_state": "BLANK" if raw == "" else "PRESENT",
                    })
            entity_id = _canonical_id(digest, definition["definition_id"], list(key))
            record[ID_FIELDS[entity_type]] = entity_id
            for generated_field in GENERATED_FIELDS.get(entity_type, set()):
                if generated_field.endswith("_ids"):
                    record.setdefault(generated_field, [])
            record.setdefault("_provenance", {
                "definition_id": definition["definition_id"],
                "source_file": filename,
                "source_sha256": digest,
                "source_data_rows": sorted(row_set),
                "mapping_version": mapping_plan["mapping_version"],
                "mapping_plan_sha256": mapping_plan_sha256,
                "source_inventory_sha256": inventory_sha256,
                **({"build_spec_sha256": build_spec_sha256} if build_spec_sha256 else {}),
            })
            if entity_type == "studies":
                record["source_locators"] = [
                    {"source_file": filename, "source_sha256": digest, "locator_type": "csv_row", "locator": f"data_row:{n}"}
                    for n in sorted(row_set)
                ]
            if entity_type == "evidence":
                record["source_locator"] = {"source_file": filename, "source_sha256": digest,
                    "locator_type": "csv_row", "locator": f"data_row:{min(row_set)}"}
            records.append(record)
            rowsets.append(row_set)
        records_by_definition[definition["definition_id"]] = records
        rowsets_by_definition[definition["definition_id"]] = rowsets

    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_VALUE_OR_GROUP_CONFLICT"}

    for link in build_spec["links"]:
        child_id = link["child_definition_id"]
        parent_id = link["parent_definition_id"]
        child_def = definitions_by_id[child_id]
        parent_def = definitions_by_id[parent_id]
        child_type = child_def["entity_type"]
        parent_type = parent_def["entity_type"]
        field_id = link["field_id"]
        cardinality = RELATIONSHIPS[(child_type, field_id, parent_type)]
        parent_records = records_by_definition[parent_id]
        parent_rows = rowsets_by_definition[parent_id]
        for child_record, child_rows in zip(records_by_definition[child_id], rowsets_by_definition[child_id]):
            matching = [p for p, rows_for_parent in zip(parent_records, parent_rows) if child_rows.intersection(rows_for_parent)]
            parent_ids = [p[ID_FIELDS[parent_type]] for p in matching]
            if cardinality == "ONE":
                if len(parent_ids) != 1:
                    errors.append(_issue("LINK_CARDINALITY_VIOLATION", child_record[ID_FIELDS[child_type]], f"{field_id} requires exactly one linked {parent_type}; found {len(parent_ids)}."))
                    continue
                child_record[field_id] = parent_ids[0]
            else:
                child_record[field_id] = sorted(set(parent_ids))
                if child_type == "comparisons" and field_id == "observation_ids" and len(child_record[field_id]) < 2:
                    errors.append(_issue("COMPARISON_REQUIRES_TWO_OBSERVATIONS", child_record[ID_FIELDS[child_type]], "Comparison group must link to at least two observations."))

    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_RELATIONSHIP_ERRORS"}

    bundle = {
        "schema_version": "1.0",
        "project_id": build_spec["project_id"],
        "mapping_version": mapping_plan["mapping_version"],
        "build_provenance": {
            "mapping_plan_sha256": mapping_plan_sha256,
            "source_inventory_sha256": inventory_sha256,
            **({"build_spec_sha256": build_spec_sha256} if build_spec_sha256 else {}),
        },
        **{entity: [] for entity in ENTITIES},
    }
    for definition in build_spec["entity_definitions"]:
        entity = definition["entity_type"]
        bundle[entity].extend(records_by_definition[definition["definition_id"]])
    integrity = validate_canonical_bundle(bundle)
    if not integrity["valid"]:
        return None, {"valid": False, "errors": integrity["errors"], "warnings": integrity["warnings"],
                      "entity_counts": integrity["counts"], "validation_scope": "NO_BUILD_CANONICAL_INTEGRITY_FAILED"}
    return bundle, {
        "valid": True, "errors": [], "warnings": integrity["warnings"],
        "entity_counts": integrity["counts"],
        "mapping_rule_count": len(mapping_validation["approved_rule_ids"]),
        "entity_definition_count": len(build_spec["entity_definitions"]),
        "link_count": len(build_spec["links"]),
        "source_files": sorted(source_cache),
        "mapping_plan_sha256": mapping_plan_sha256,
        "source_inventory_sha256": inventory_sha256,
        **({"build_spec_sha256": build_spec_sha256} if build_spec_sha256 else {}),
        "validation_scope": "DETERMINISTIC_CSV_BUILD_AND_CANONICAL_STRUCTURAL_REFERENTIAL_VALIDATION_NOT_SCIENTIFIC_VALIDATION",
    }


def build_canonical_files(mapping_plan_path: Path, inventory_path: Path, build_spec_path: Path,
                          source_root: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    with mapping_plan_path.open("r", encoding="utf-8-sig") as handle:
        mapping_plan = json.load(handle)
    with inventory_path.open("r", encoding="utf-8-sig") as handle:
        inventory = json.load(handle)
    with build_spec_path.open("r", encoding="utf-8-sig") as handle:
        build_spec = json.load(handle)
    return build_canonical_bundle(mapping_plan, inventory, build_spec, source_root,
                                  sha256_file(mapping_plan_path), sha256_file(inventory_path),
                                  sha256_file(build_spec_path))
