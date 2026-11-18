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
    def validate_value_candidates(path: str, row: dict[str, Any]) -> None:
        if "value_candidates" not in row:
            return
        candidates = row.get("value_candidates")
        if not isinstance(candidates, list):
            errors.append({"code":"VALUE_CANDIDATES_NOT_ARRAY","path":f"{path}.value_candidates","message":"value_candidates must be an array."})
            return
        seen_candidate_ids: set[str] = set()
        for candidate_index, candidate in enumerate(candidates):
            candidate_path = f"{path}.value_candidates[{candidate_index}]"
            if not isinstance(candidate, dict):
                errors.append({"code":"VALUE_CANDIDATE_NOT_OBJECT","path":candidate_path,"message":"A value candidate must be an object."})
                continue
            candidate_id = candidate.get("candidate_id")
            candidate_source = candidate.get("candidate_source")
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                errors.append({"code":"INVALID_VALUE_CANDIDATE_ID","path":f"{candidate_path}.candidate_id","message":"candidate_id must be a non-empty string."})
            elif candidate_id in seen_candidate_ids:
                errors.append({"code":"DUPLICATE_VALUE_CANDIDATE_ID","path":f"{candidate_path}.candidate_id","message":"candidate_id must be unique within its parent record."})
            else:
                seen_candidate_ids.add(candidate_id)
            if not isinstance(candidate_source, str) or not candidate_source.strip():
                errors.append({"code":"INVALID_VALUE_CANDIDATE_SOURCE","path":f"{candidate_path}.candidate_source","message":"candidate_source must be a non-empty string."})
            has_value = any(candidate.get(field) not in (None, "") for field in ("raw_value", "normalized_value"))
            metadata_for_value = candidate.get("source_metadata")
            has_metadata = isinstance(metadata_for_value, dict) and any(value not in (None, "") for value in metadata_for_value.values())
            has_quote = isinstance(candidate.get("quoted_text"), str) and bool(candidate["quoted_text"].strip())
            candidate_locators = candidate.get("source_locators")
            has_locator = isinstance(candidate_locators, list) and bool(candidate_locators)
            if not (has_value or has_metadata or has_quote or has_locator):
                errors.append({"code":"VALUE_CANDIDATE_WITHOUT_VALUE_OR_EVIDENCE","path":candidate_path,"message":"A candidate entry must contain a value, quoted text, source metadata, or a source locator."})
            locators = candidate.get("source_locators", [])
            if not isinstance(locators, list):
                errors.append({"code":"VALUE_CANDIDATE_LOCATORS_NOT_ARRAY","path":f"{candidate_path}.source_locators","message":"source_locators must be an array."})
            else:
                for locator_index, locator in enumerate(locators):
                    locator_path = f"{candidate_path}.source_locators[{locator_index}]"
                    if not isinstance(locator, dict):
                        errors.append({"code":"INVALID_VALUE_CANDIDATE_LOCATOR","path":locator_path,"message":"A source locator must be an object."})
                        continue
                    if not isinstance(locator.get("source_file"), str) or not locator.get("source_file", "").strip():
                        errors.append({"code":"INVALID_VALUE_CANDIDATE_LOCATOR_FILE","path":f"{locator_path}.source_file","message":"source_file must be a non-empty string."})
                    digest = locator.get("source_sha256")
                    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
                        errors.append({"code":"INVALID_VALUE_CANDIDATE_LOCATOR_HASH","path":f"{locator_path}.source_sha256","message":"source_sha256 must be a 64-character hexadecimal SHA-256."})
                    if locator.get("locator_type") not in LOCATOR_TYPES:
                        errors.append({"code":"INVALID_VALUE_CANDIDATE_LOCATOR_TYPE","path":f"{locator_path}.locator_type","message":"Unknown source locator type."})
                    if locator.get("locator") in (None, ""):
                        errors.append({"code":"INVALID_VALUE_CANDIDATE_LOCATOR_VALUE","path":f"{locator_path}.locator","message":"locator must be non-empty."})

            metadata = candidate.get("source_metadata")
            if metadata is not None:
                if not isinstance(metadata, dict):
                    errors.append({"code":"VALUE_CANDIDATE_METADATA_NOT_OBJECT","path":f"{candidate_path}.source_metadata","message":"source_metadata must be an object."})
                else:
                    for metadata_key, metadata_value in metadata.items():
                        if not isinstance(metadata_key, str) or not metadata_key.strip():
                            errors.append({"code":"VALUE_CANDIDATE_METADATA_KEY_INVALID","path":candidate_path,"message":"source_metadata keys must be non-empty strings."})
                        if isinstance(metadata_value, (dict, list)):
                            errors.append({"code":"VALUE_CANDIDATE_METADATA_VALUE_INVALID","path":f"{candidate_path}.source_metadata.{metadata_key}","message":"source_metadata values must be scalar values or null."})

    for i, row in enumerate(records["systems"].values()):
        refs(f"systems[{i}].study_ids", row.get("study_ids"), "studies")
        if not isinstance(row.get("study_ids"), list) or not row.get("study_ids"):
            errors.append({"code":"SYSTEM_WITHOUT_STUDY","path":f"systems[{i}].study_ids","message":"A system must link to at least one study."})
    for i, row in enumerate(records["conditions"].values()):
        validate_value_candidates(f"conditions[{i}]", row)
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
        validate_value_candidates(f"observations[{i}]", row)
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
