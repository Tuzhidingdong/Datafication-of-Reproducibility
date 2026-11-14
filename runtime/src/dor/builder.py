"""Deterministic canonical construction from approved CSV and JSON mappings."""
from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.diagnostics import diagnose_canonical_bundle
from dor.mapping import sha256_file, validate_mapping_plan
from dor.selectors import (
    parse_json_pointer, parse_profile_path, render_json_pointer,
    resolve_tokens, select_records, selector_prefix_matches,
)

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


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_numeric(raw: Any, params: dict[str, Any]) -> int | float:
    decimal_sep = params.get("decimal_separator", ".")
    thousands_sep = params.get("thousands_separator")
    value = str(raw).strip()
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


def _transform(raw: Any, spec: dict[str, Any]) -> Any:
    kind = spec.get("type")
    params = spec.get("parameters", {})
    if raw is None or (isinstance(raw, str) and raw == ""):
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
        key = raw if isinstance(raw, str) else _stable(raw)
        if not isinstance(table, dict) or key not in table:
            raise ValueError(f"LOOKUP has no explicit mapping for value {key!r}.")
        return table[key]
    if kind == "SPLIT":
        if not isinstance(raw, str):
            raise ValueError("SPLIT requires a string source value.")
        delimiter = params.get("delimiter")
        if not isinstance(delimiter, str) or not delimiter:
            raise ValueError("SPLIT requires a non-empty delimiter.")
        maxsplit = params.get("maxsplit", -1)
        if isinstance(maxsplit, bool) or not isinstance(maxsplit, int) or maxsplit < -1:
            raise ValueError("SPLIT maxsplit must be an integer >= -1.")
        parts = raw.split(delimiter, maxsplit)
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


def _read_csv(path: Path, expected_hash: str) -> tuple[list[str], list[dict[str, str]], str]:
    if sha256_file(path) != expected_hash:
        raise ValueError(f"Source hash mismatch for {path.name}; inventory is stale.")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"CSV has no header: {path.name}") from exc
        if not header or any(not name.strip() for name in header) or len(set(header)) != len(header):
            raise ValueError(f"CSV header is empty, contains blank names, or has duplicate names: {path.name}")
        rows = []
        for row_number, values in enumerate(reader, start=1):
            if len(values) != len(header):
                raise ValueError(f"CSV row {row_number} in {path.name} has {len(values)} cells; expected {len(header)}.")
            rows.append(dict(zip(header, values)))
    if sha256_file(path) != expected_hash:
        raise ValueError(f"Source changed while being read: {path.name}")
    return header, rows, expected_hash


def _read_json(path: Path, expected_hash: str) -> tuple[Any, str]:
    if sha256_file(path) != expected_hash:
        raise ValueError(f"Source hash mismatch for {path.name}; inventory is stale.")
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if sha256_file(path) != expected_hash:
        raise ValueError(f"Source changed while being read: {path.name}")
    return payload, expected_hash


def _safe_source_path(root: Path, file_name: str) -> Path:
    root = root.expanduser().resolve()
    path = (root / file_name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Source file path escapes source root: {file_name}")
    return path


def _source_item_matches_definition(item: dict[str, Any], definition: dict[str, Any],
                                    selector_tokens: tuple[str, ...] | None) -> bool:
    fmt = definition.get("source_format", "csv")
    if item.get("source_file") != definition.get("source_file") or item.get("source_format") != fmt:
        return False
    if fmt == "csv":
        return item.get("locator_type") == "csv_column"
    if fmt == "json" and item.get("locator_type") == "json_path":
        try:
            return selector_tokens is not None and selector_prefix_matches(
                parse_profile_path(item["locator"]), selector_tokens)
        except (KeyError, ValueError):
            return False
    return False


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
        fmt = definition.get("source_format", "csv")
        if not isinstance(source_file, str) or not source_file:
            errors.append(_issue("INVALID_SOURCE_FILE", f"{path}.source_file", "source_file is required."))
        if not isinstance(fmt, str) or fmt not in {"csv", "json"}:
            errors.append(_issue("INVALID_SOURCE_FORMAT", f"{path}.source_format", "source_format must be csv or json."))
            fmt = "unsupported"
        selector_tokens = None
        if fmt == "json":
            try:
                selector_tokens = parse_json_pointer(definition.get("record_selector"))
                if "*" not in selector_tokens:
                    errors.append(_issue("JSON_SELECTOR_REQUIRES_WILDCARD", f"{path}.record_selector", "JSON record_selector must contain an explicit '*' array wildcard."))
            except ValueError as exc:
                errors.append(_issue("INVALID_JSON_RECORD_SELECTOR", f"{path}.record_selector", str(exc)))

        grouping = definition.get("grouping")
        if not isinstance(grouping, dict) or not isinstance(grouping.get("mode"), str) or grouping.get("mode") not in {"SOURCE_ROW", "GROUP_BY_FIELDS"}:
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
            if not item or not _source_item_matches_definition(item, definition, selector_tokens):
                errors.append(_issue("INVALID_GROUP_KEY_SOURCE", f"{path}.grouping.source_item_ids", f"{source_id} is not a compatible source field within {source_file}."))

        field_rule_ids = definition.get("field_rule_ids")
        if not isinstance(field_rule_ids, list):
            errors.append(_issue("FIELD_RULES_NOT_ARRAY", f"{path}.field_rule_ids", "field_rule_ids must be an array."))
            field_rule_ids = []
        seen_fields: set[str] = set()
        for rule_id in field_rule_ids:
            if not isinstance(rule_id, str):
                errors.append(_issue("INVALID_FIELD_RULE_ID", f"{path}.field_rule_ids", "Field rule IDs must be strings."))
                continue
            rule = rule_by_id.get(rule_id)
            if rule_id not in approved_ids or not rule:
                errors.append(_issue("RULE_NOT_ELIGIBLE", f"{path}.field_rule_ids", f"{rule_id} is not an approved, validated mapping rule."))
                continue
            source_item = item_by_id.get(rule.get("source_item_id"))
            if rule.get("target_entity") != etype:
                errors.append(_issue("RULE_ENTITY_MISMATCH", f"{path}.field_rule_ids", f"{rule_id} targets {rule.get('target_entity')}, not {etype}."))
            if not source_item or not _source_item_matches_definition(source_item, definition, selector_tokens):
                errors.append(_issue("UNSUPPORTED_OR_MISMATCHED_SOURCE", f"{path}.field_rule_ids", f"{rule_id} must reference a compatible source item in {source_file}."))
            field_id = rule.get("target_field_id")
            if field_id in seen_fields:
                errors.append(_issue("DUPLICATE_FIELD_RULE", f"{path}.field_rule_ids", f"Multiple rules target {field_id} in this entity definition."))
            seen_fields.add(field_id)
            if field_id in GENERATED_FIELDS.get(etype, set()):
                errors.append(_issue("GENERATED_FIELD_CANNOT_BE_MAPPED", f"{path}.field_rule_ids", f"{field_id} is generated by canonical identity/link logic and cannot be overwritten."))

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
        child_id = link.get("child_definition_id")
        parent_id = link.get("parent_definition_id")
        child = def_by_id.get(child_id) if isinstance(child_id, str) else None
        parent = def_by_id.get(parent_id) if isinstance(parent_id, str) else None
        if child is None or parent is None:
            errors.append(_issue("UNKNOWN_LINK_DEFINITION", path, "Child and parent definition IDs must exist."))
            continue
        field_id = link.get("field_id")
        expected = (child.get("entity_type"), field_id, parent.get("entity_type"))
        if not isinstance(field_id, str) or expected not in RELATIONSHIPS:
            errors.append(_issue("INVALID_CANONICAL_RELATIONSHIP", path, f"Unsupported canonical relationship {expected}."))
        match_mode = link.get("match_mode", "ROW_OVERLAP")
        if not isinstance(match_mode, str) or match_mode not in {"ROW_OVERLAP", "FIELD_EQUALITY"}:
            errors.append(_issue("INVALID_LINK_MATCH_MODE", f"{path}.match_mode", "match_mode must be ROW_OVERLAP or FIELD_EQUALITY."))
        if match_mode == "ROW_OVERLAP":
            if child.get("source_file") != parent.get("source_file") or child.get("source_format", "csv") != parent.get("source_format", "csv"):
                errors.append(_issue("ROW_OVERLAP_CROSS_SOURCE", path, "ROW_OVERLAP requires the same source file and format; use FIELD_EQUALITY for cross-source links."))
            if "child_key_field" in link or "parent_key_field" in link:
                errors.append(_issue("ROW_OVERLAP_HAS_KEYS", path, "ROW_OVERLAP must not declare equality key fields."))
        elif match_mode == "FIELD_EQUALITY":
            for key in ("child_key_field", "parent_key_field"):
                if not isinstance(link.get(key), str) or not link[key].strip():
                    errors.append(_issue("FIELD_EQUALITY_KEY_REQUIRED", f"{path}.{key}", "FIELD_EQUALITY requires explicit child_key_field and parent_key_field."))
            for definition, key_name, prefix in ((child, "child_key_field", "child"), (parent, "parent_key_field", "parent")):
                key_field = link.get(key_name)
                rules = [rule_by_id.get(rid) for rid in definition.get("field_rule_ids", []) if rid in rule_by_id]
                mapped_fields = {rule.get("target_field_id") for rule in rules if isinstance(rule, dict)}
                if isinstance(key_field, str) and key_field not in mapped_fields:
                    errors.append(_issue("JOIN_KEY_NOT_MAPPED", f"{path}.{key_name}", f"{prefix} join key must be populated by an explicit mapping rule in its entity definition."))
        key = (child_id, parent_id, field_id if isinstance(field_id, str) else repr(field_id))
        if key in seen_links:
            errors.append(_issue("DUPLICATE_LINK", path, "Duplicate link declaration."))
        seen_links.add(key)
    return errors


def _record_units(definition: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    if source["format"] == "csv":
        units = []
        for index, row in enumerate(source["rows"], start=1):
            units.append({"data": row, "locator_type": "csv_row", "locator": f"data_row:{index}",
                          "unit_key": f"csv_row:{index}", "row_number": index})
        return units
    selected = select_records(source["payload"], definition["record_selector"])
    return [{"data": record, "locator_type": "json_pointer", "locator": render_json_pointer(pointer),
             "unit_key": "json_pointer:" + render_json_pointer(pointer), "pointer_tokens": pointer}
            for record, pointer in selected]


def _resolve_item(item: dict[str, Any], definition: dict[str, Any], unit: dict[str, Any]) -> tuple[Any, str, str]:
    if definition.get("source_format", "csv") == "csv":
        column = item["locator"]
        value = unit["data"].get(column)
        return value, "csv_row", f"{unit['locator']};column:{column}"
    pattern_tokens = parse_profile_path(item["locator"])
    selector_tokens = parse_json_pointer(definition["record_selector"])
    if not selector_prefix_matches(pattern_tokens, selector_tokens):
        raise ValueError(f"JSON path {item['locator']!r} is outside record_selector {definition['record_selector']!r}.")
    relative_tokens = pattern_tokens[len(selector_tokens):]
    matches = resolve_tokens(unit["data"], relative_tokens)
    if not matches:
        return None, "json_pointer", unit["locator"]
    if len(matches) > 1:
        raise ValueError(f"JSON source path {item['locator']!r} resolves to multiple values inside one selected record; select a deeper record_selector.")
    value, relative_concrete = matches[0]
    absolute = tuple(unit["pointer_tokens"]) + relative_concrete
    return value, "json_pointer", render_json_pointer(absolute)


def _group_key(definition: dict[str, Any], unit: dict[str, Any], key_items: list[dict[str, Any]]) -> tuple[Any, ...]:
    if definition["grouping"]["mode"] == "SOURCE_ROW":
        return (unit["unit_key"],)
    values = []
    for item in key_items:
        value, _, _ = _resolve_item(item, definition, unit)
        if _is_blank(value) or isinstance(value, (dict, list)):
            raise ValueError(f"Grouping key {item['inventory_id']} is blank or non-scalar at {unit['locator']}.")
        values.append(value)
    return tuple(values)


def _source_fingerprint(value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise ValueError("FIELD_EQUALITY keys must be scalar values.")
    if _is_blank(value):
        raise ValueError("FIELD_EQUALITY key is blank; no implicit null-to-null match is allowed.")
    return _stable(value)


def build_canonical_bundle(mapping_plan: Any, inventory: Any, build_spec: Any,
                           source_root: Path, mapping_plan_sha256: str,
                           inventory_sha256: str, build_spec_sha256: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build only from validated approved mappings and explicit entity/link definitions."""
    mapping_validation = validate_mapping_plan(mapping_plan, inventory, inventory_sha256)
    errors = list(mapping_validation.get("errors", []))
    if not mapping_validation.get("valid"):
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_MAPPING_PLAN_INVALID"}
    errors.extend(_validate_build_spec(build_spec, mapping_plan, inventory, mapping_validation, mapping_plan_sha256, inventory_sha256))
    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_SPEC_INVALID"}

    item_by_id = {item["inventory_id"]: item for item in inventory["items"]}
    approved_set = set(mapping_validation["approved_rule_ids"])
    rule_by_id = {rule["mapping_rule_id"]: rule for rule in mapping_plan["rules"] if rule["mapping_rule_id"] in approved_set}
    source_cache: dict[str, dict[str, Any]] = {}
    for definition in build_spec["entity_definitions"]:
        filename = definition["source_file"]
        if filename in source_cache:
            continue
        matching = [item for item in inventory["items"] if item.get("source_file") == filename]
        hashes = {item.get("source_sha256") for item in matching}
        formats = {item.get("source_format") for item in matching}
        if not matching or len(hashes) != 1 or len(formats) != 1:
            errors.append(_issue("SOURCE_INVENTORY_AMBIGUOUS", filename, "Source file has no inventory items or inconsistent hashes/formats."))
            continue
        digest = next(iter(hashes))
        fmt = next(iter(formats))
        try:
            path = _safe_source_path(source_root, filename)
            if not path.is_file():
                raise FileNotFoundError(f"Source file not found: {path}")
            if fmt == "csv":
                header, rows, digest = _read_csv(path, digest)
                source_cache[filename] = {"format": "csv", "header": header, "rows": rows, "sha256": digest}
                headers = set(header)
                for item in matching:
                    if item.get("locator_type") == "csv_column" and item.get("locator") not in headers:
                        errors.append(_issue("SOURCE_COLUMN_NOT_FOUND", item.get("inventory_id", filename), f"CSV column {item.get('locator')!r} is absent from current file."))
            elif fmt == "json":
                payload, digest = _read_json(path, digest)
                source_cache[filename] = {"format": "json", "payload": payload, "sha256": digest}
                for item in matching:
                    if item.get("locator_type") == "json_path":
                        try:
                            parse_profile_path(item["locator"])
                        except (KeyError, ValueError) as exc:
                            errors.append(_issue("INVALID_JSON_INVENTORY_PATH", item.get("inventory_id", filename), str(exc)))
            else:
                errors.append(_issue("UNSUPPORTED_SOURCE_FORMAT", filename, f"Unsupported source format {fmt!r}."))
        except Exception as exc:
            errors.append(_issue("SOURCE_READ_FAILED", filename, str(exc)))

    if errors:
        return None, {"valid": False, "errors": errors, "warnings": [], "validation_scope": "NO_BUILD_SOURCE_VALIDATION_FAILED"}

    records_by_definition: dict[str, list[dict[str, Any]]] = {}
    unitsets_by_definition: dict[str, list[set[str]]] = {}
    definitions_by_id = {d["definition_id"]: d for d in build_spec["entity_definitions"]}
    for definition in build_spec["entity_definitions"]:
        filename = definition["source_file"]
        source = source_cache[filename]
        try:
            units = _record_units(definition, source)
        except Exception as exc:
            errors.append(_issue("RECORD_SELECTOR_FAILED", definition["definition_id"], str(exc)))
            continue
        if not units:
            errors.append(_issue("NO_SOURCE_RECORDS_SELECTED", definition["definition_id"], "The source selector returned no records; refusing to emit an empty entity collection silently."))
            continue
        grouping = definition["grouping"]
        key_items = [item_by_id[sid] for sid in grouping.get("source_item_ids", [])]
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for unit in units:
            try:
                key = _group_key(definition, unit, key_items)
            except Exception as exc:
                errors.append(_issue("INVALID_GROUP_KEY_VALUE", f"{definition['definition_id']}:{unit['locator']}", str(exc)))
                continue
            groups.setdefault(key, []).append(unit)

        records: list[dict[str, Any]] = []
        unitsets: list[set[str]] = []
        entity_type = definition["entity_type"]
        digest = source["sha256"]
        for key, grouped_units in groups.items():
            record: dict[str, Any] = {}
            for rule_id in definition["field_rule_ids"]:
                rule = rule_by_id[rule_id]
                item = item_by_id[rule["source_item_id"]]
                values: list[tuple[Any, Any, str, str]] = []
                for unit in grouped_units:
                    try:
                        raw, locator_type, locator = _resolve_item(item, definition, unit)
                        transformed = _transform(raw, rule["transformation"])
                    except Exception as exc:
                        errors.append(_issue("VALUE_TRANSFORM_FAILED", f"{definition['definition_id']}:{unit['locator']}", f"{rule_id}: {exc}"))
                        continue
                    values.append((raw, transformed, locator_type, locator))
                non_null = [transformed for _, transformed, _, _ in values if transformed is not None]
                unique_values = {_stable(value) for value in non_null}
                has_blank = any(raw is None or raw == "" for raw, _, _, _ in values)
                if len(unique_values) > 1 or (has_blank and non_null):
                    errors.append(_issue("GROUP_FIELD_CONFLICT", f"{definition['definition_id']}.{rule['target_field_id']}", f"Values for {rule_id} are not consistent within group {key!r}; define a finer entity grouping instead of selecting one."))
                    continue
                record[rule["target_field_id"]] = non_null[0] if non_null else None
                for raw, transformed, locator_type, locator in values:
                    record.setdefault("field_provenance", []).append({
                        "target_field_id": rule["target_field_id"],
                        "mapping_rule_id": rule_id,
                        "source_item_id": item["inventory_id"],
                        "source_file": filename,
                        "source_sha256": digest,
                        "locator_type": locator_type,
                        "locator": locator,
                        "raw_value": raw,
                        "transformed_value": transformed,
                        "transformation": rule["transformation"],
                        "cell_state": "MISSING_PATH" if raw is None else ("BLANK" if raw == "" else "PRESENT"),
                    })

            entity_key = list(key)
            entity_id = _canonical_id(digest, definition["definition_id"], entity_key)
            record[ID_FIELDS[entity_type]] = entity_id
            for generated_field in GENERATED_FIELDS.get(entity_type, set()):
                if generated_field.endswith("_ids"):
                    record.setdefault(generated_field, [])
            unit_keys = {unit["unit_key"] for unit in grouped_units}
            first_locator_type = grouped_units[0]["locator_type"] if grouped_units else ("csv_row" if source["format"] == "csv" else "json_pointer")
            locator_objects = [
                {"source_file": filename, "source_sha256": digest, "locator_type": unit["locator_type"], "locator": unit["locator"]}
                for unit in grouped_units
            ]
            record["_provenance"] = {
                "definition_id": definition["definition_id"],
                "source_file": filename,
                "source_format": source["format"],
                "source_sha256": digest,
                "source_record_locators": locator_objects,
                "mapping_version": mapping_plan["mapping_version"],
                "mapping_plan_sha256": mapping_plan_sha256,
                "source_inventory_sha256": inventory_sha256,
                **({"build_spec_sha256": build_spec_sha256} if build_spec_sha256 else {}),
            }
            if entity_type == "studies":
                record["source_locators"] = locator_objects
            if entity_type == "evidence":
                if len(locator_objects) != 1:
                    errors.append(_issue("EVIDENCE_REQUIRES_SINGLE_SOURCE_RECORD", entity_id, "Each Evidence entity must resolve to exactly one selected source record."))
                else:
                    record["source_locator"] = locator_objects[0]
            records.append(record)
            unitsets.append(unit_keys)
        records_by_definition[definition["definition_id"]] = records
        unitsets_by_definition[definition["definition_id"]] = unitsets

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
        child_records = records_by_definition[child_id]
        parent_records = records_by_definition[parent_id]
        match_mode = link.get("match_mode", "ROW_OVERLAP")
        if match_mode == "ROW_OVERLAP":
            parent_units = unitsets_by_definition[parent_id]
            for child_record, child_units in zip(child_records, unitsets_by_definition[child_id]):
                matching = [parent for parent, parent_keys in zip(parent_records, parent_units) if child_units.intersection(parent_keys)]
                parent_ids = [parent[ID_FIELDS[parent_type]] for parent in matching]
                if cardinality == "ONE":
                    if len(parent_ids) != 1:
                        errors.append(_issue("LINK_CARDINALITY_VIOLATION", child_record[ID_FIELDS[child_type]], f"{field_id} requires exactly one linked {parent_type}; found {len(parent_ids)}."))
                        continue
                    child_record[field_id] = parent_ids[0]
                else:
                    child_record[field_id] = sorted(set(parent_ids))
        else:
            child_key_field = link["child_key_field"]
            parent_key_field = link["parent_key_field"]
            index: dict[str, list[dict[str, Any]]] = {}
            for parent in parent_records:
                value = parent.get(parent_key_field)
                if _is_blank(value):
                    continue
                try:
                    fingerprint = _source_fingerprint(value)
                except ValueError as exc:
                    errors.append(_issue("INVALID_PARENT_JOIN_KEY", parent[ID_FIELDS[parent_type]], str(exc)))
                    continue
                index.setdefault(fingerprint, []).append(parent)
            for child in child_records:
                value = child.get(child_key_field)
                try:
                    fingerprint = _source_fingerprint(value)
                except ValueError as exc:
                    errors.append(_issue("INVALID_CHILD_JOIN_KEY", child[ID_FIELDS[child_type]], str(exc)))
                    continue
                matching = index.get(fingerprint, [])
                parent_ids = [parent[ID_FIELDS[parent_type]] for parent in matching]
                if cardinality == "ONE":
                    if len(parent_ids) != 1:
                        errors.append(_issue("JOIN_CARDINALITY_VIOLATION", child[ID_FIELDS[child_type]], f"{field_id} requires exactly one parent by {child_key_field}={value!r}; found {len(parent_ids)}."))
                        continue
                    child[field_id] = parent_ids[0]
                else:
                    child[field_id] = sorted(set(parent_ids))
                    if child_type == "comparisons" and field_id == "observation_ids" and len(child[field_id]) < 2:
                        errors.append(_issue("COMPARISON_REQUIRES_TWO_OBSERVATIONS", child[ID_FIELDS[child_type]], "Comparison join must resolve to at least two observations."))

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
        bundle[definition["entity_type"]].extend(records_by_definition[definition["definition_id"]])
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
        "relationship_diagnostics": diagnose_canonical_bundle(bundle),
        "mapping_plan_sha256": mapping_plan_sha256,
        "source_inventory_sha256": inventory_sha256,
        **({"build_spec_sha256": build_spec_sha256} if build_spec_sha256 else {}),
        "validation_scope": "DETERMINISTIC_CSV_JSON_BUILD_AND_CANONICAL_STRUCTURAL_REFERENTIAL_VALIDATION_NOT_SCIENTIFIC_VALIDATION",
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



def validate_build_spec_files(
    mapping_plan_path: Path,
    inventory_path: Path,
    build_spec_path: Path,
) -> dict[str, Any]:
    """Validate an explicit Build Spec without reading source data or building entities."""
    mapping_plan_path = mapping_plan_path.expanduser().resolve()
    inventory_path = inventory_path.expanduser().resolve()
    build_spec_path = build_spec_path.expanduser().resolve()

    hashes_before = {
        "mapping_plan_sha256": sha256_file(mapping_plan_path),
        "source_inventory_sha256": sha256_file(inventory_path),
        "build_spec_sha256": sha256_file(build_spec_path),
    }
    try:
        with mapping_plan_path.open("r", encoding="utf-8-sig") as handle:
            mapping_plan = json.load(handle)
        with inventory_path.open("r", encoding="utf-8-sig") as handle:
            inventory = json.load(handle)
        with build_spec_path.open("r", encoding="utf-8-sig") as handle:
            build_spec = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Mapping plan, source inventory, and build spec must be valid JSON: {exc}") from exc

    mapping_validation = validate_mapping_plan(
        mapping_plan, inventory, hashes_before["source_inventory_sha256"]
    ) if isinstance(mapping_plan, dict) else {
        "valid": False,
        "errors": [_issue("PLAN_NOT_OBJECT", "$", "Mapping plan must be a JSON object.")],
        "warnings": [],
        "approved_rule_ids": [],
    }
    errors = list(mapping_validation.get("errors", []))
    if mapping_validation.get("valid") is True:
        errors.extend(_validate_build_spec(
            build_spec,
            mapping_plan,
            inventory,
            mapping_validation,
            hashes_before["mapping_plan_sha256"],
            hashes_before["source_inventory_sha256"],
        ))

    hashes_after = {
        "mapping_plan_sha256": sha256_file(mapping_plan_path),
        "source_inventory_sha256": sha256_file(inventory_path),
        "build_spec_sha256": sha256_file(build_spec_path),
    }
    if hashes_after != hashes_before:
        raise RuntimeError("Mapping plan, source inventory, or build spec changed during validation.")

    return {
        "schema_version": "1.0",
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(mapping_validation.get("warnings", [])),
        "errors": errors,
        "warnings": mapping_validation.get("warnings", []),
        "mapping_plan_sha256": hashes_before["mapping_plan_sha256"],
        "source_inventory_sha256": hashes_before["source_inventory_sha256"],
        "build_spec_sha256": hashes_before["build_spec_sha256"],
        "mapping_version": (
            build_spec.get("mapping_version") if isinstance(build_spec, dict) else None
        ),
        "validation_scope": (
            "EXPLICIT_BUILD_SPEC_STRUCTURE_REFERENCE_GRAIN_AND_LINK_VALIDATION; "
            "NO_SOURCE_DATA_READ_AND_NO_CANONICAL_BUILD"
        ),
    }
