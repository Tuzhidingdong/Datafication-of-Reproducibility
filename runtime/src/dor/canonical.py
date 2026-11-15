"""Structural and referential-integrity validation for canonical research bundles."""
from __future__ import annotations
from collections import defaultdict
from typing import Any

ENTITY_KEYS = {
    "studies": ("study_id", None),
    "systems": ("system_id", "study_ids"),
    "conditions": ("condition_id", "system_ids"),
    "experiments": ("experiment_id", "condition_ids"),
    "observations": ("observation_id", "evidence_ids"),
    "comparisons": ("comparison_id", "observation_ids"),
    "evidence": ("evidence_id", None),
}
MISSINGNESS = {"REPORTED", "NOT_REPORTED", "NOT_APPLICABLE", "AMBIGUOUS", "CONFLICTING", "NOT_ASSESSED"}
LOCATOR_TYPES = {"csv_row", "csv_column", "json_path", "json_pointer", "pdf_page", "table_cell", "figure_panel", "supplementary_item", "other"}
REQUIRED_FIELDS = {
    "studies": {"study_id", "source_locators"},
    "systems": {"system_id", "study_ids", "system_type"},
    "conditions": {"condition_id", "system_ids", "condition_type", "value_state"},
    "experiments": {"experiment_id", "study_id", "system_id", "condition_ids"},
    "observations": {"observation_id", "experiment_id", "target_id", "value_state", "evidence_ids"},
    "comparisons": {"comparison_id", "observation_ids", "comparison_type"},
    "evidence": {"evidence_id", "study_id", "source_locator", "evidence_type"},
}

def validate_canonical_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return all detectable structural/reference errors; never repairs or mutates input."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(bundle, dict):
        return {"valid": False, "errors": [{"code":"BUNDLE_NOT_OBJECT","path":"$","message":"Bundle must be a JSON object."}], "warnings":[]}
    if bundle.get("schema_version") != "1.0":
        errors.append({"code":"UNSUPPORTED_SCHEMA_VERSION","path":"schema_version","message":"Expected schema_version 1.0."})
    ids: dict[str, set[str]] = {}
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for collection, (id_field, _) in ENTITY_KEYS.items():
        rows = bundle.get(collection)
        if not isinstance(rows, list):
            errors.append({"code":"COLLECTION_NOT_ARRAY","path":collection,"message":f"{collection} must be an array."})
            rows = []
        ids[collection] = set()
        records[collection] = {}
        for index, row in enumerate(rows):
            path = f"{collection}[{index}]"
            if not isinstance(row, dict):
                errors.append({"code":"RECORD_NOT_OBJECT","path":path,"message":"Record must be an object."})
                continue
            missing_fields = REQUIRED_FIELDS[collection] - row.keys()
            for field in sorted(missing_fields):
                errors.append({"code":"MISSING_REQUIRED_FIELD","path":f"{path}.{field}","message":f"Required field {field} is missing."})
            identifier = row.get(id_field)
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append({"code":"MISSING_RECORD_ID","path":path,"message":f"{id_field} must be a non-empty string."})
                continue
            if identifier in ids[collection]:
                errors.append({"code":"DUPLICATE_RECORD_ID","path":path,"message":f"Duplicate {id_field}: {identifier}."})
            ids[collection].add(identifier)
            records[collection][identifier] = row
    def ref(path: str, value: Any, collection: str) -> None:
        if not isinstance(value, str) or value not in ids[collection]:
            errors.append({"code":"BROKEN_REFERENCE","path":path,"message":f"Reference {value!r} not found in {collection}."})
    def refs(path: str, values: Any, collection: str) -> None:
        if not isinstance(values, list):
            errors.append({"code":"REFERENCE_LIST_NOT_ARRAY","path":path,"message":"Expected an array of IDs."})
            return
        for i, value in enumerate(values): ref(f"{path}[{i}]", value, collection)
    for i, row in enumerate(records["systems"].values()):
        refs(f"systems[{i}].study_ids", row.get("study_ids"), "studies")
        if not isinstance(row.get("study_ids"), list) or not row.get("study_ids"):
            errors.append({"code":"SYSTEM_WITHOUT_STUDY","path":f"systems[{i}].study_ids","message":"A system must link to at least one study."})
    for i, row in enumerate(records["conditions"].values()):
        refs(f"conditions[{i}].system_ids", row.get("system_ids", []), "systems")
        if not isinstance(row.get("system_ids"), list) or not row.get("system_ids"):
            errors.append({"code":"CONDITION_WITHOUT_SYSTEM","path":f"conditions[{i}].system_ids","message":"A condition must link to at least one system."})
        if not isinstance(row.get("value_state"), str) or row.get("value_state") not in MISSINGNESS:
            errors.append({"code":"INVALID_MISSINGNESS_STATE","path":f"conditions[{i}].value_state","message":"Unknown value_state."})
        if row.get("value_state") == "REPORTED" and row.get("raw_value") is None:
            warnings.append({"code":"REPORTED_CONDITION_WITHOUT_RAW_VALUE","path":f"conditions[{i}]","message":"Reported condition has no raw_value; inspect missing source paths and evidence."})
    for i, row in enumerate(records["experiments"].values()):
        ref(f"experiments[{i}].study_id", row.get("study_id"), "studies")
        ref(f"experiments[{i}].system_id", row.get("system_id"), "systems")
        refs(f"experiments[{i}].condition_ids", row.get("condition_ids"), "conditions")
        system = records["systems"].get(row.get("system_id")) if isinstance(row.get("system_id"), str) else None
        if system and row.get("study_id") not in system.get("study_ids", []):
            errors.append({"code":"EXPERIMENT_SYSTEM_STUDY_MISMATCH","path":f"experiments[{i}]","message":"Experiment study_id is not linked to its system."})
        condition_ids = row.get("condition_ids", [])
        for condition_id in condition_ids if isinstance(condition_ids, list) else []:
            condition = records["conditions"].get(condition_id) if isinstance(condition_id, str) else None
            if condition and row.get("system_id") not in condition.get("system_ids", []):
                errors.append({"code":"EXPERIMENT_CONDITION_SYSTEM_MISMATCH","path":f"experiments[{i}].condition_ids","message":f"Condition {condition_id} is not linked to the experiment system."})
    for i, row in enumerate(records["observations"].values()):
        ref(f"observations[{i}].experiment_id", row.get("experiment_id"), "experiments")
        refs(f"observations[{i}].evidence_ids", row.get("evidence_ids"), "evidence")
        if not isinstance(row.get("value_state"), str) or row.get("value_state") not in MISSINGNESS:
            errors.append({"code":"INVALID_MISSINGNESS_STATE","path":f"observations[{i}].value_state","message":"Unknown value_state."})
        if row.get("value_state") == "REPORTED" and row.get("raw_value") is None:
            warnings.append({"code":"REPORTED_WITHOUT_RAW_VALUE","path":f"observations[{i}]","message":"Reported observation has no raw_value field."})
        experiment = records["experiments"].get(row.get("experiment_id")) if isinstance(row.get("experiment_id"), str) else None
        if experiment is not None and isinstance(row.get("evidence_ids"), list):
            for evidence_id in row["evidence_ids"]:
                evidence = records["evidence"].get(evidence_id) if isinstance(evidence_id, str) else None
                if evidence is not None and evidence.get("study_id") != experiment.get("study_id"):
                    errors.append({
                        "code": "OBSERVATION_EVIDENCE_STUDY_MISMATCH",
                        "path": f"observations[{i}].evidence_ids",
                        "message": f"Evidence {evidence_id!r} belongs to a different Study than its linked Experiment.",
                    })
        if row.get("value_state") != "REPORTED" and row.get("raw_value") == 0:
            warnings.append({"code":"ZERO_ON_NON_REPORTED_STATE","path":f"observations[{i}].raw_value","message":"A zero value is present despite a non-REPORTED state; review rather than infer."})
    for i, row in enumerate(records["comparisons"].values()):
        refs(f"comparisons[{i}].observation_ids", row.get("observation_ids"), "observations")
        comparison_refs = row.get("observation_ids", [])
        if not isinstance(comparison_refs, list) or len(comparison_refs) < 2:
            errors.append({"code":"COMPARISON_TOO_SMALL","path":f"comparisons[{i}].observation_ids","message":"A comparison must reference at least two observations."})
    for i, row in enumerate(records["evidence"].values()):
        ref(f"evidence[{i}].study_id", row.get("study_id"), "studies")
        locator = row.get("source_locator")
        if not isinstance(locator, dict):
            errors.append({"code":"INVALID_EVIDENCE_LOCATOR","path":f"evidence[{i}].source_locator","message":"Evidence requires a locator object."})
            continue
        source_file = locator.get("source_file")
        source_sha256 = locator.get("source_sha256")
        locator_type = locator.get("locator_type")
        locator_value = locator.get("locator")
        if not isinstance(source_file, str) or not source_file.strip():
            errors.append({"code":"INVALID_EVIDENCE_SOURCE_FILE","path":f"evidence[{i}].source_locator.source_file","message":"Evidence source_file must be a non-empty string."})
        if not isinstance(source_sha256, str) or len(source_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in source_sha256):
            errors.append({"code":"INVALID_EVIDENCE_SOURCE_HASH","path":f"evidence[{i}].source_locator.source_sha256","message":"Evidence source_sha256 must be a 64-character hexadecimal SHA-256."})
        if not isinstance(locator_type, str) or locator_type not in LOCATOR_TYPES:
            errors.append({"code":"INVALID_EVIDENCE_LOCATOR_TYPE","path":f"evidence[{i}].source_locator.locator_type","message":"Evidence locator_type is not supported."})
        if not isinstance(locator_value, str) or not locator_value.strip():
            errors.append({"code":"INVALID_EVIDENCE_LOCATOR_VALUE","path":f"evidence[{i}].source_locator.locator","message":"Evidence locator must be a non-empty string."})
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings),
        "errors": errors, "warnings": warnings,
        "counts": {name: len(ids[name]) for name in ENTITY_KEYS},
        "validation_scope": "STRUCTURAL_AND_REFERENTIAL_ONLY_NOT_SCIENTIFIC_VALIDATION"}
