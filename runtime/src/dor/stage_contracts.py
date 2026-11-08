"""Versioned, implementation-owned V1.0 stage evidence contracts.

The registry fixes evidence types and executes structural/provenance checks. It
never infers scientific meaning, selects thresholds, or replaces human review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.0"

STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "source_selection": {
        "required_artifact_types": ["source_selection_manifest", "source_inventory"],
        "checks": ["selected_source_set_exact", "inventory_ids_unique", "source_hashes_present"],
        "scope": "User-selected source inventory and explicit exclusions; filenames are labels, not semantics.",
    },
    "source_integrity": {
        "required_artifact_types": ["run_manifest"],
        "checks": ["run_manifest_identity", "source_snapshot_exact"],
        "scope": "Run Manager source snapshot and hash-chain verification are authoritative.",
    },
    "extraction_review": {
        "required_artifact_types": ["extraction_review_record"],
        "checks": ["source_hash_bindings", "exact_review_locators", "human_review_decision"],
        "scope": "DOR-owned human spot-check record; no assumption about an upstream parser's private schema.",
    },
    "semantic_mapping": {
        "required_artifact_types": ["mapping_plan"],
        "checks": ["inventory_hash_binding", "no_unreviewed_proposals", "approved_rules_explicit"],
        "scope": "Explicit source-item to canonical-field mappings, transformations, and review decisions.",
    },
    "canonical_reconciliation": {
        "required_artifact_types": ["canonical_bundle", "reconciliation_report"],
        "checks": ["canonical_entity_integrity", "cross_entity_references", "reconciliation_bundle_binding"],
        "scope": "Study/System/Condition/Experiment/Observation/Comparison/Evidence graph integrity.",
    },
    "cohort_feasibility": {
        "required_artifact_types": ["cohort_report", "split_manifest"],
        "checks": ["cohort_report_identity", "study_group_split_integrity", "split_study_coverage"],
        "scope": "Endpoint-specific cohort and explicit Study-level split feasibility.",
    },
    "modeling_validation": {
        "required_artifact_types": ["model_report", "modeling_run_manifest"],
        "checks": ["model_report_identity", "model_manifest_split_integrity", "study_leakage_absent"],
        "scope": "Model artifacts and metrics bound to the exact cohort/task and Study split; no performance threshold is invented.",
    },
    "publication_handoff": {
        "required_artifact_types": ["publication_package_manifest", "publication_integrity_report"],
        "checks": ["package_identity", "writing_guide_hash", "package_integrity_valid"],
        "scope": "Publication package, Writing Skill guide, hashes, and explicit completeness state.",
    },
}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def _error(code: str, message: str, artifact_type: str | None = None) -> dict[str, str]:
    item = {"code": code, "message": message}
    if artifact_type:
        item["artifact_type"] = artifact_type
    return item


def _validate_source_selection(payload: Any, source_snapshot: list[dict[str, Any]],
                               study_ids: set[str]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("SOURCE_SELECTION_SCHEMA_INVALID", "source_selection_manifest requires schema_version 1.0.", "source_selection_manifest")]
    if not _nonempty(payload.get("selection_rationale")) or not _nonempty(payload.get("scope_statement")):
        errors.append(_error("SOURCE_SELECTION_RATIONALE_MISSING", "A non-empty selection_rationale and scope_statement are required.", "source_selection_manifest"))
    selected = payload.get("selected_sources")
    if not isinstance(selected, list) or not selected:
        return errors + [_error("SOURCE_SELECTION_SOURCES_MISSING", "selected_sources must be a non-empty array.", "source_selection_manifest")]
    expected = {
        item.get("source_id"): item for item in source_snapshot
        if isinstance(item, dict) and _nonempty(item.get("source_id"))
    }
    seen: set[str] = set()
    for index, item in enumerate(selected):
        if not isinstance(item, dict) or not all(_nonempty(item.get(key)) for key in ("source_id", "role", "path")) or not _sha256(item.get("sha256")):
            errors.append(_error("SOURCE_SELECTION_ITEM_INVALID", f"selected_sources[{index}] requires source_id, role, path, and SHA-256.", "source_selection_manifest"))
            continue
        source_id = item["source_id"]
        if source_id in seen:
            errors.append(_error("SOURCE_SELECTION_DUPLICATE_ID", f"Duplicate selected source_id: {source_id}.", "source_selection_manifest"))
        seen.add(source_id)
        bound = expected.get(source_id)
        if bound is None or Path(str(bound.get("path", ""))).expanduser().resolve(strict=False) != Path(item["path"]).expanduser().resolve(strict=False) or bound.get("sha256") != item["sha256"] or bound.get("role") != item["role"]:
            errors.append(_error("SOURCE_SELECTION_NOT_BOUND_TO_SNAPSHOT", f"Selected source {source_id} differs from the acceptance source snapshot.", "source_selection_manifest"))
    if seen != set(expected):
        errors.append(_error("SOURCE_SELECTION_SET_MISMATCH", "selected_sources must contain exactly the acceptance source_snapshot IDs.", "source_selection_manifest"))
    if payload.get("study_ids") != sorted(study_ids):
        errors.append(_error("SOURCE_SELECTION_STUDY_SET_MISMATCH", "source_selection_manifest.study_ids must equal the sorted explicit acceptance Study IDs.", "source_selection_manifest"))
    exclusions = payload.get("excluded_sources")
    if not isinstance(exclusions, list):
        errors.append(_error("SOURCE_SELECTION_EXCLUSIONS_INVALID", "excluded_sources must be an array, even when empty.", "source_selection_manifest"))
    else:
        for index, entry in enumerate(exclusions):
            if not isinstance(entry, dict) or not _nonempty(entry.get("source_label")) or not _nonempty(entry.get("reason")):
                errors.append(_error("SOURCE_EXCLUSION_INCOMPLETE", f"excluded_sources[{index}] requires source_label and reason.", "source_selection_manifest"))
    return errors


def _validate_source_inventory(payload: Any, source_snapshot: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not isinstance(payload.get("items"), list) or not payload["items"]:
        return [_error("SOURCE_INVENTORY_SHAPE_INVALID", "source_inventory requires schema_version 1.0 and a non-empty items array.", "source_inventory")]
    snapshot_by_name_hash = {
        (Path(str(item.get("path", ""))).name, item.get("sha256"))
        for item in source_snapshot if isinstance(item, dict)
    }
    seen: set[str] = set()
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            errors.append(_error("SOURCE_INVENTORY_ITEM_INVALID", f"items[{index}] must be an object.", "source_inventory"))
            continue
        required = ("inventory_id", "source_file", "source_sha256", "source_format", "locator_type", "locator", "mapping_status")
        if any(not _nonempty(item.get(key)) for key in required):
            errors.append(_error("SOURCE_INVENTORY_ITEM_INCOMPLETE", f"items[{index}] lacks explicit inventory/locator/hash fields.", "source_inventory"))
        if not _sha256(item.get("source_sha256")):
            errors.append(_error("SOURCE_INVENTORY_HASH_INVALID", f"items[{index}].source_sha256 is not SHA-256.", "source_inventory"))
        elif (item.get("source_file"), item.get("source_sha256")) not in snapshot_by_name_hash:
            errors.append(_error("SOURCE_INVENTORY_SOURCE_NOT_SELECTED", f"items[{index}] does not point to a selected source file/hash.", "source_inventory"))
        identifier = item.get("inventory_id")
        if _nonempty(identifier):
            if identifier in seen:
                errors.append(_error("SOURCE_INVENTORY_ID_DUPLICATE", f"Duplicate inventory_id: {identifier}.", "source_inventory"))
            seen.add(identifier)
    return errors


def _validate_run_manifest(payload: Any, run_id: str, project_id: str,
                           source_snapshot: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return [_error("RUN_MANIFEST_SHAPE_INVALID", "run_manifest must be a JSON object.", "run_manifest")]
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != run_id or payload.get("project_id") != project_id:
        errors.append(_error("RUN_MANIFEST_IDENTITY_MISMATCH", "run_manifest schema/run/project identity does not match this acceptance.", "run_manifest"))
    actual = {
        item.get("artifact_id"): item for item in payload.get("source_artifacts", [])
        if isinstance(item, dict) and _nonempty(item.get("artifact_id"))
    } if isinstance(payload.get("source_artifacts"), list) else {}
    expected = {item.get("source_id"): item for item in source_snapshot if isinstance(item, dict)}
    if set(actual) != set(expected):
        errors.append(_error("RUN_MANIFEST_SOURCE_SET_MISMATCH", "run_manifest source_artifacts must exactly match source_snapshot IDs.", "run_manifest"))
    for source_id, item in expected.items():
        bound = actual.get(source_id)
        if bound is None:
            continue
        if (Path(str(bound.get("path", ""))).expanduser().resolve(strict=False) != Path(str(item.get("path", ""))).expanduser().resolve(strict=False)
                or bound.get("sha256") != item.get("sha256")):
            errors.append(_error("RUN_MANIFEST_SOURCE_BINDING_MISMATCH", f"Run Manifest source {source_id} path/hash differs from source_snapshot.", "run_manifest"))
    return errors


def _validate_extraction_review(payload: Any, source_snapshot: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("EXTRACTION_REVIEW_SCHEMA_INVALID", "extraction_review_record requires schema_version 1.0.", "extraction_review_record")]
    hashes = payload.get("source_hashes")
    expected = {item.get("source_id"): item.get("sha256") for item in source_snapshot if isinstance(item, dict)}
    if not isinstance(hashes, dict) or hashes != expected:
        errors.append(_error("EXTRACTION_SOURCE_HASH_BINDING_MISMATCH", "source_hashes must exactly match the selected source IDs and SHA-256 values.", "extraction_review_record"))
    locators = payload.get("reviewed_locators")
    if not isinstance(locators, list) or not locators:
        errors.append(_error("EXTRACTION_LOCATORS_MISSING", "reviewed_locators must be a non-empty array.", "extraction_review_record"))
    else:
        for index, locator in enumerate(locators):
            if not isinstance(locator, dict) or any(not _nonempty(locator.get(key)) for key in ("source_id", "locator_type", "locator", "review_status")):
                errors.append(_error("EXTRACTION_LOCATOR_INCOMPLETE", f"reviewed_locators[{index}] requires source_id, locator_type, locator, and review_status.", "extraction_review_record"))
                continue
            if locator["source_id"] not in expected:
                errors.append(_error("EXTRACTION_LOCATOR_SOURCE_UNKNOWN", f"reviewed_locators[{index}] references an unselected source_id.", "extraction_review_record"))
            if locator["review_status"] not in {"SPOT_CHECKED", "REVIEW_REQUIRED", "UNREADABLE", "NOT_APPLICABLE"}:
                errors.append(_error("EXTRACTION_REVIEW_STATUS_INVALID", f"reviewed_locators[{index}] has an unsupported review_status.", "extraction_review_record"))
    review = payload.get("human_review")
    if not isinstance(review, dict) or not all(_nonempty(review.get(key)) for key in ("reviewer", "reviewed_at", "decision")):
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_MISSING", "human_review requires reviewer, reviewed_at, and decision.", "extraction_review_record"))
    elif review.get("decision") not in {"ACCEPTED_WITH_LIMITATIONS", "REJECTED", "REQUIRES_FOLLOW_UP"}:
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_DECISION_INVALID", "human_review.decision is not an explicit supported decision.", "extraction_review_record"))
    return errors


def _validate_mapping_plan(payload: Any, source_inventory: dict[str, Any] | None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not _nonempty(payload.get("mapping_version")):
        return [_error("MAPPING_PLAN_SHAPE_INVALID", "mapping_plan requires schema_version 1.0 and mapping_version.", "mapping_plan")]
    if not _sha256(payload.get("source_inventory_sha256")):
        errors.append(_error("MAPPING_INVENTORY_HASH_INVALID", "mapping_plan must bind to source_inventory_sha256.", "mapping_plan"))
    elif source_inventory is None or payload.get("source_inventory_sha256") != source_inventory.get("sha256"):
        errors.append(_error("MAPPING_INVENTORY_HASH_MISMATCH", "mapping_plan.source_inventory_sha256 must equal the Run-bound source_inventory evidence hash.", "mapping_plan"))
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        return errors + [_error("MAPPING_RULES_MISSING", "mapping_plan.rules must be a non-empty array.", "mapping_plan")]
    inventory_payload = source_inventory.get("payload", {}) if source_inventory else {}
    inventory_ids = {
        item.get("inventory_id") for item in inventory_payload.get("items", [])
        if isinstance(item, dict) and _nonempty(item.get("inventory_id"))
    } if isinstance(inventory_payload, dict) else set()
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or not _nonempty(rule.get("mapping_rule_id")) or not _nonempty(rule.get("source_item_id")):
            errors.append(_error("MAPPING_RULE_INCOMPLETE", f"rules[{index}] requires mapping_rule_id and source_item_id.", "mapping_plan"))
            continue
        rule_id = rule["mapping_rule_id"]
        if rule_id in seen:
            errors.append(_error("MAPPING_RULE_ID_DUPLICATE", f"Duplicate mapping_rule_id: {rule_id}.", "mapping_plan"))
        seen.add(rule_id)
        if rule["source_item_id"] not in inventory_ids:
            errors.append(_error("MAPPING_SOURCE_ITEM_UNKNOWN", f"Rule {rule_id} references a source_item_id absent from source_inventory.", "mapping_plan"))
        if rule.get("status") == "PROPOSED":
            errors.append(_error("MAPPING_RULE_UNREVIEWED", f"Mapping rule {rule_id} remains PROPOSED.", "mapping_plan"))
        if rule.get("status") not in {"PROPOSED", "REVIEWED", "APPROVED", "REJECTED", "UNRESOLVED"}:
            errors.append(_error("MAPPING_RULE_STATUS_INVALID", f"Mapping rule {rule_id} has an unsupported status.", "mapping_plan"))
        if rule.get("status") == "APPROVED":
            review, transform = rule.get("review"), rule.get("transformation")
            if not all(_nonempty(rule.get(key)) for key in ("target_entity", "target_field_id")):
                errors.append(_error("APPROVED_MAPPING_TARGET_MISSING", f"Approved rule {rule_id} lacks explicit target entity/field.", "mapping_plan"))
            if not isinstance(transform, dict) or not _nonempty(transform.get("type")) or not isinstance(transform.get("parameters"), dict):
                errors.append(_error("APPROVED_MAPPING_TRANSFORM_MISSING", f"Approved rule {rule_id} lacks explicit transformation and parameters.", "mapping_plan"))
            if not isinstance(review, dict) or not all(_nonempty(review.get(key)) for key in ("reviewer", "reviewed_at", "decision_note")):
                errors.append(_error("APPROVED_MAPPING_REVIEW_MISSING", f"Approved rule {rule_id} lacks explicit human review.", "mapping_plan"))
    return errors


def _validate_canonical_bundle(payload: Any) -> list[dict[str, str]]:
    from dor.canonical import validate_canonical_bundle
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return [_error("CANONICAL_BUNDLE_INVALID", "canonical_bundle must be a JSON object.", "canonical_bundle")]
    if payload.get("schema_version") != "1.0" or not _nonempty(payload.get("project_id")) or not _nonempty(payload.get("mapping_version")):
        errors.append(_error("CANONICAL_BUNDLE_METADATA_INVALID", "canonical_bundle requires schema_version 1.0, project_id, and mapping_version.", "canonical_bundle"))
    result = validate_canonical_bundle(payload)
    errors.extend(_error("CANONICAL_BUNDLE_INVALID", f"{item.get('path')}: {item.get('message')}", "canonical_bundle")
                  for item in result.get("errors", []))
    return errors


def _validate_reconciliation(payload: Any, canonical_sha256: str | None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("RECONCILIATION_REPORT_INVALID", "reconciliation_report requires schema_version 1.0.", "reconciliation_report")]
    if canonical_sha256 is None or payload.get("bundle_sha256") != canonical_sha256:
        errors.append(_error("RECONCILIATION_BUNDLE_HASH_MISMATCH", "reconciliation_report.bundle_sha256 must equal the cited canonical_bundle SHA-256.", "reconciliation_report"))
    if payload.get("valid_bundle") is not True:
        errors.append(_error("RECONCILIATION_BUNDLE_NOT_VALID", "reconciliation_report does not report valid_bundle=true.", "reconciliation_report"))
    if not isinstance(payload.get("issues"), list) or payload.get("issue_count") != len(payload.get("issues", [])):
        errors.append(_error("RECONCILIATION_ISSUE_COUNT_MISMATCH", "reconciliation_report issue_count must equal issues length.", "reconciliation_report"))
    return errors


def _validate_cohort_report(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "eligible_observation_count", "eligible_study_count", "eligible_study_ids", "split_counts")
    if not isinstance(payload, dict) or payload.get("valid") is not True or any(key not in payload for key in required):
        return [_error("COHORT_REPORT_INVALID", "cohort_report must expose a valid endpoint-specific task, explicit Study IDs, counts, and split_counts.", "cohort_report")]
    study_ids = payload.get("eligible_study_ids")
    if not isinstance(study_ids, list) or any(not _nonempty(value) for value in study_ids) or len(study_ids) != len(set(study_ids)):
        return [_error("COHORT_ELIGIBLE_STUDY_IDS_INVALID", "eligible_study_ids must be a unique list of non-empty Study IDs.", "cohort_report")]
    if payload.get("eligible_study_count") != len(study_ids):
        return [_error("COHORT_STUDY_COUNT_MISMATCH", "eligible_study_count must equal eligible_study_ids length.", "cohort_report")]
    return []


def _validate_split_manifest(payload: Any, eligible_study_ids: set[str] | None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("SPLIT_MANIFEST_INVALID", "split_manifest requires schema_version 1.0.", "split_manifest")]
    mapping, leakage = payload.get("study_to_split"), payload.get("leakage_check")
    if not isinstance(mapping, dict) or not mapping or not isinstance(leakage, dict):
        return [_error("STUDY_SPLIT_LEAKAGE_INVALID", "split_manifest must contain study_to_split and leakage_check objects.", "split_manifest")]
    if any(not _nonempty(sid) or not isinstance(partition, str) or partition not in {"train", "validation", "test"} for sid, partition in mapping.items()):
        errors.append(_error("STUDY_SPLIT_MAPPING_INVALID", "study_to_split must map explicit Study IDs to train/validation/test.", "split_manifest"))
    if eligible_study_ids is not None and set(mapping) != eligible_study_ids:
        errors.append(_error("STUDY_SPLIT_COVERAGE_MISMATCH", "split_manifest Study IDs must exactly match cohort_report.eligible_study_ids.", "split_manifest"))
    if not {"train", "validation", "test"}.issubset(set(mapping.values())):
        errors.append(_error("STUDY_SPLIT_PARTITION_MISSING", "A modelling split must include non-empty train/validation/test Study groups.", "split_manifest"))
    if leakage.get("valid") is not True or leakage.get("study_overlap_count") != 0:
        errors.append(_error("STUDY_SPLIT_LEAKAGE_INVALID", "leakage_check must report valid=true and study_overlap_count=0.", "split_manifest"))
    expected_groups = {
        name: sorted(sid for sid, partition in mapping.items() if partition == name)
        for name in ("train", "validation", "test")
    }
    if leakage.get("study_ids_by_split") != expected_groups:
        errors.append(_error("STUDY_SPLIT_GROUPS_MISMATCH", "leakage_check.study_ids_by_split must equal study_to_split.", "split_manifest"))
    return errors


def _validate_model_report(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "selected_model", "selected_candidate_id", "validation_comparison", "test_evaluation")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("MODEL_REPORT_INVALID", "model_report lacks task identity, selection, validation, or test fields.", "model_report")]
    if not isinstance(payload.get("validation_comparison"), list) or not payload["validation_comparison"]:
        errors = [_error("MODEL_VALIDATION_COMPARISON_MISSING", "model_report.validation_comparison must be non-empty.", "model_report")]
    else:
        errors = []
    if not isinstance(payload.get("test_evaluation"), dict) or not payload["test_evaluation"]:
        errors.append(_error("MODEL_TEST_EVALUATION_MISSING", "model_report.test_evaluation must be non-empty.", "model_report"))
    return errors


def _validate_model_manifest(payload: Any) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("MODELING_RUN_MANIFEST_INVALID", "modeling_run_manifest requires schema_version 1.0.", "modeling_run_manifest")]
    inputs, outputs, splits = payload.get("input_hashes"), payload.get("output_hashes"), payload.get("study_ids_by_split")
    input_keys = ("cohort_sha256", "cohort_report_sha256", "split_manifest_sha256", "cohort_manifest_sha256", "task_sha256")
    if not isinstance(inputs, dict) or not all(_sha256(inputs.get(key)) for key in input_keys):
        errors.append(_error("MODELING_INPUT_HASHES_INCOMPLETE", "modeling_run_manifest must bind all five cohort/task input hashes.", "modeling_run_manifest"))
    if not isinstance(outputs, dict) or not outputs or any(not _sha256(value) for value in outputs.values()):
        errors.append(_error("MODELING_OUTPUT_HASHES_INVALID", "modeling_run_manifest output_hashes must contain SHA-256 values.", "modeling_run_manifest"))
    if not isinstance(splits, dict) or not all(isinstance(splits.get(key), list) and splits[key] for key in ("train", "validation", "test")):
        errors.append(_error("MODELING_SPLIT_IDS_MISSING", "modeling_run_manifest requires non-empty train/validation/test Study ID lists.", "modeling_run_manifest"))
    elif any(any(not _nonempty(value) for value in splits[key]) for key in ("train", "validation", "test")):
        errors.append(_error("MODELING_SPLIT_IDS_INVALID", "Model split Study IDs must be non-empty strings.", "modeling_run_manifest"))
    elif (set(splits["train"]) & set(splits["validation"]) or set(splits["train"]) & set(splits["test"])
          or set(splits["validation"]) & set(splits["test"])):
        errors.append(_error("MODELING_STUDY_LEAKAGE", "Study IDs overlap across train/validation/test.", "modeling_run_manifest"))
    return errors


def _validate_publication_manifest(payload: Any, run_id: str, project_id: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("PUBLICATION_MANIFEST_INVALID", "publication_package_manifest requires schema_version 1.0.", "publication_package_manifest")]
    if payload.get("run_id") != run_id or payload.get("project_id") != project_id:
        errors.append(_error("PUBLICATION_PACKAGE_IDENTITY_MISMATCH", "Publication package run_id/project_id does not match this acceptance.", "publication_package_manifest"))
    if payload.get("writing_guide") != "README_FOR_WRITING_SKILL.md" or not _sha256(payload.get("writing_guide_sha256")):
        errors.append(_error("PUBLICATION_WRITING_GUIDE_INVALID", "Publication package must hash-bind README_FOR_WRITING_SKILL.md.", "publication_package_manifest"))
    if not isinstance(payload.get("artifacts"), list) or not isinstance(payload.get("completeness"), dict):
        errors.append(_error("PUBLICATION_PACKAGE_CONTENT_INVALID", "Publication package requires artifacts and completeness.", "publication_package_manifest"))
    elif payload["completeness"].get("status") not in {"complete", "partial", "requires_review"} or not isinstance(payload["completeness"].get("unresolved_items"), list):
        errors.append(_error("PUBLICATION_COMPLETENESS_INVALID", "Publication completeness requires a supported status and unresolved_items array.", "publication_package_manifest"))
    return errors


def validate_stage_payload(artifact_type: str, payload: Any, *, run_id: str, project_id: str,
                           study_ids: set[str], source_snapshot: list[dict[str, Any]] | None = None,
                           canonical_sha256: str | None = None,
                           eligible_study_ids: set[str] | None = None) -> list[dict[str, str]]:
    """Validate one typed evidence payload using fixed V1.0 implementation rules."""
    sources = source_snapshot or []
    if artifact_type == "source_selection_manifest":
        return _validate_source_selection(payload, sources, study_ids)
    if artifact_type == "source_inventory":
        return _validate_source_inventory(payload, sources)
    if artifact_type == "run_manifest":
        return _validate_run_manifest(payload, run_id, project_id, sources)
    if artifact_type == "extraction_review_record":
        return _validate_extraction_review(payload, sources)
    if artifact_type == "mapping_plan":
        return _validate_mapping_plan(payload, None)
    if artifact_type == "canonical_bundle":
        return _validate_canonical_bundle(payload)
    if artifact_type == "reconciliation_report":
        return _validate_reconciliation(payload, canonical_sha256)
    if artifact_type == "cohort_report":
        return _validate_cohort_report(payload)
    if artifact_type == "split_manifest":
        return _validate_split_manifest(payload, eligible_study_ids)
    if artifact_type == "model_report":
        return _validate_model_report(payload)
    if artifact_type == "modeling_run_manifest":
        return _validate_model_manifest(payload)
    if artifact_type == "publication_package_manifest":
        return _validate_publication_manifest(payload, run_id, project_id)
    if artifact_type == "publication_integrity_report":
        if (not isinstance(payload, dict) or payload.get("valid") is not True
                or not isinstance(payload.get("errors"), list) or payload["errors"]
                or not isinstance(payload.get("checked_file_count"), int) or payload["checked_file_count"] < 1):
            return [_error("PUBLICATION_INTEGRITY_AUDIT_FAILED", "publication_integrity_report must report valid=true, checked files, and an empty errors array.", artifact_type)]
        return []
    return [_error("UNKNOWN_STAGE_ARTIFACT_TYPE", f"Unsupported fixed evidence type: {artifact_type}.", artifact_type)]


def validate_stage_evidence(stage_id: str, evidence: list[dict[str, Any]], *, run_id: str,
                            project_id: str, study_ids: set[str],
                            source_snapshot: list[dict[str, Any]],
                            prior_payloads: dict[str, dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Enforce required typed evidence and cross-stage bindings for a PASS stage."""
    contract = STAGE_CONTRACTS.get(stage_id)
    if contract is None:
        return [_error("UNKNOWN_ACCEPTANCE_STAGE", f"No fixed evidence contract exists for stage {stage_id}.")]
    by_type: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    seen_artifact_ids: set[str] = set()
    for item in evidence:
        artifact_type = item.get("artifact_type")
        artifact_id = item.get("artifact_id")
        if not _nonempty(artifact_type):
            errors.append(_error("STAGE_EVIDENCE_TYPE_MISSING", f"Evidence {artifact_id} must declare artifact_type."))
            continue
        if artifact_type not in contract["required_artifact_types"]:
            errors.append(_error("STAGE_EVIDENCE_TYPE_NOT_ALLOWED", f"{artifact_type} is not a required evidence type for {stage_id}.", artifact_type))
            continue
        if artifact_type in by_type:
            errors.append(_error("STAGE_EVIDENCE_TYPE_DUPLICATE", f"Stage {stage_id} contains duplicate {artifact_type} evidence.", artifact_type))
            continue
        if not _nonempty(artifact_id) or artifact_id in seen_artifact_ids:
            errors.append(_error("STAGE_EVIDENCE_ID_MISSING_OR_DUPLICATE", f"Stage {stage_id} has a missing or duplicate artifact_id."))
            continue
        seen_artifact_ids.add(artifact_id)
        if "payload" not in item:
            errors.append(_error("STAGE_EVIDENCE_PAYLOAD_UNREADABLE", f"Evidence {artifact_id} has no parsed JSON payload.", artifact_type))
            continue
        by_type[artifact_type] = item
    for required_type in contract["required_artifact_types"]:
        if required_type not in by_type:
            errors.append(_error("STAGE_REQUIRED_EVIDENCE_TYPE_MISSING", f"Stage {stage_id} requires evidence type {required_type}.", required_type))

    all_payloads = dict(prior_payloads or {})
    all_payloads.update(by_type)
    canonical = all_payloads.get("canonical_bundle")
    canonical_sha = canonical.get("sha256") if canonical else None
    cohort = all_payloads.get("cohort_report")
    eligible_ids = None
    if cohort and isinstance(cohort.get("payload"), dict):
        values = cohort["payload"].get("eligible_study_ids")
        if isinstance(values, list) and all(_nonempty(value) for value in values):
            eligible_ids = set(values)

    for artifact_type, item in by_type.items():
        if artifact_type == "mapping_plan":
            continue
        errors.extend(validate_stage_payload(
            artifact_type, item["payload"], run_id=run_id, project_id=project_id,
            study_ids=study_ids, source_snapshot=source_snapshot,
            canonical_sha256=canonical_sha, eligible_study_ids=eligible_ids,
        ))

    if stage_id == "semantic_mapping" and "mapping_plan" in by_type:
        inventory = all_payloads.get("source_inventory")
        errors.extend(_validate_mapping_plan(by_type["mapping_plan"]["payload"], inventory))
    if stage_id == "canonical_reconciliation" and "canonical_bundle" in by_type:
        bundle = by_type["canonical_bundle"]["payload"]
        canonical_studies = {
            row.get("study_id") for row in bundle.get("studies", [])
            if isinstance(row, dict) and _nonempty(row.get("study_id"))
        } if isinstance(bundle, dict) else set()
        if canonical_studies != study_ids:
            errors.append(_error("CANONICAL_STUDY_SET_MISMATCH", "Canonical Study IDs must exactly match source_snapshot.study_ids.", "canonical_bundle"))
    if stage_id == "cohort_feasibility" and "cohort_report" in by_type and "split_manifest" in by_type:
        report, split = by_type["cohort_report"]["payload"], by_type["split_manifest"]["payload"]
        if isinstance(report, dict) and isinstance(split, dict):
            ids = report.get("eligible_study_ids", [])
            if isinstance(ids, list) and set(split.get("study_to_split", {})) != set(ids):
                errors.append(_error("COHORT_SPLIT_STUDY_SET_MISMATCH", "split_manifest Study IDs must exactly match cohort_report.eligible_study_ids.", "split_manifest"))
    if stage_id == "modeling_validation" and "model_report" in by_type and "modeling_run_manifest" in by_type:
        report_item, manifest_item = by_type["model_report"], by_type["modeling_run_manifest"]
        report, model_manifest = report_item["payload"], manifest_item["payload"]
        if isinstance(report, dict) and isinstance(model_manifest, dict):
            if report.get("task_id") != model_manifest.get("task_id") or report.get("selected_model") != model_manifest.get("selected_model"):
                errors.append(_error("MODEL_REPORT_MANIFEST_IDENTITY_MISMATCH", "model_report task_id/selected_model must match modeling_run_manifest.", "model_report"))
            expected_hash = model_manifest.get("output_hashes", {}).get("model_report.json")
            if expected_hash != report_item.get("sha256"):
                errors.append(_error("MODEL_REPORT_HASH_NOT_BOUND", "modeling_run_manifest.output_hashes.model_report.json must equal the cited model_report evidence hash.", "modeling_run_manifest"))
            split_item = all_payloads.get("split_manifest")
            if split_item and isinstance(split_item.get("payload"), dict):
                split_map = split_item["payload"].get("study_to_split", {})
                expected_groups = {
                    key: sorted(sid for sid, partition in split_map.items() if partition == key)
                    for key in ("train", "validation", "test")
                }
                actual_groups = model_manifest.get("study_ids_by_split", {})
                actual_groups = {key: sorted(values) for key, values in actual_groups.items()} if isinstance(actual_groups, dict) else {}
                if actual_groups != expected_groups:
                    errors.append(_error("MODEL_SPLIT_MANIFEST_MISMATCH", "modeling_run_manifest Study assignments must exactly match the accepted cohort split_manifest.", "modeling_run_manifest"))
    return errors
