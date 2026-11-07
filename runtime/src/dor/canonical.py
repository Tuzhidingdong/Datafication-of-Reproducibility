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
            identifier = row.get(id_field)
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append({"code":"MISSING_RECORD_ID","path":path,"message":f"{id_field} must be a non-empty string."})
                continue
            if identifier in ids[collection]:
                errors.append({"code":"DUPLICATE_RECORD_ID","path":path,"message":f"Duplicate {id_field}: {identifier}."})
            ids[collection].add(identifier)
            records[collection][identifier] = row
    def ref(path: str, value: Any, collection: str) -> None:
        if value not in ids[collection]:
            errors.append({"code":"BROKEN_REFERENCE","path":path,"message":f"Reference {value!r} not found in {collection}."})
    def refs(path: str, values: Any, collection: str) -> None:
        if not isinstance(values, list):
            errors.append({"code":"REFERENCE_LIST_NOT_ARRAY","path":path,"message":"Expected an array of IDs."})
            return
        for i, value in enumerate(values): ref(f"{path}[{i}]", value, collection)
    for i, row in enumerate(records["systems"].values()):
        refs(f"systems[{i}].study_ids", row.get("study_ids"), "studies")
    for i, row in enumerate(records["conditions"].values()):
        refs(f"conditions[{i}].system_ids", row.get("system_ids", []), "systems")
        if row.get("value_state") not in MISSINGNESS:
            errors.append({"code":"INVALID_MISSINGNESS_STATE","path":f"conditions[{i}].value_state","message":"Unknown value_state."})
    for i, row in enumerate(records["experiments"].values()):
        ref(f"experiments[{i}].study_id", row.get("study_id"), "studies")
        ref(f"experiments[{i}].system_id", row.get("system_id"), "systems")
        refs(f"experiments[{i}].condition_ids", row.get("condition_ids"), "conditions")
    for i, row in enumerate(records["observations"].values()):
        ref(f"observations[{i}].experiment_id", row.get("experiment_id"), "experiments")
        refs(f"observations[{i}].evidence_ids", row.get("evidence_ids"), "evidence")
        if row.get("value_state") not in MISSINGNESS:
            errors.append({"code":"INVALID_MISSINGNESS_STATE","path":f"observations[{i}].value_state","message":"Unknown value_state."})
        if row.get("value_state") == "REPORTED" and "raw_value" not in row:
            warnings.append({"code":"REPORTED_WITHOUT_RAW_VALUE","path":f"observations[{i}]","message":"Reported observation has no raw_value field."})
        if row.get("value_state") != "REPORTED" and row.get("raw_value") == 0:
            warnings.append({"code":"ZERO_ON_NON_REPORTED_STATE","path":f"observations[{i}].raw_value","message":"A zero value is present despite a non-REPORTED state; review rather than infer."})
    for i, row in enumerate(records["comparisons"].values()):
        refs(f"comparisons[{i}].observation_ids", row.get("observation_ids"), "observations")
        if len(row.get("observation_ids", [])) < 2:
            errors.append({"code":"COMPARISON_TOO_SMALL","path":f"comparisons[{i}].observation_ids","message":"A comparison must reference at least two observations."})
    for i, row in enumerate(records["evidence"].values()):
        ref(f"evidence[{i}].study_id", row.get("study_id"), "studies")
        locator = row.get("source_locator")
        if not isinstance(locator, dict) or not locator.get("source_file") or not locator.get("locator"):
            errors.append({"code":"INVALID_EVIDENCE_LOCATOR","path":f"evidence[{i}].source_locator","message":"Evidence requires a source file and locator."})
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings),
        "errors": errors, "warnings": warnings,
        "counts": {name: len(ids[name]) for name in ENTITY_KEYS},
        "validation_scope": "STRUCTURAL_AND_REFERENTIAL_ONLY_NOT_SCIENTIFIC_VALIDATION"}
