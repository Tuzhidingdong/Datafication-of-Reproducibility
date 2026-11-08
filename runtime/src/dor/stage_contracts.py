"""Versioned, fixed V1.0 stage evidence contracts.

The registry defines evidence types and deterministic structural/relational checks.
It deliberately does not infer scientific meaning, choose thresholds, or replace
human review. Acceptance integration consumes these contracts by stage ID.
"""
from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "1.0"

# Required artifact types are fixed by the implementation, not supplied by an
# acceptance-record author. A contract may list alternatives only where the
# underlying workflow genuinely has alternative output forms.
STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "source_selection": {
        "required_artifact_types": ["source_inventory"],
        "checks": ["inventory_shape", "inventory_ids_unique", "source_hashes_present"],
        "scope": "Explicit inventory of selected source files and locators; filenames are labels, not semantics.",
    },
    "source_integrity": {
        "required_artifact_types": ["run_manifest"],
        "checks": ["run_manifest_identity", "source_snapshot_exact"],
        "scope": "Run Manager source snapshot and hash-chain verification are authoritative.",
    },
    "extraction_review": {
        "required_artifact_types": ["extraction_review_record"],
        "checks": ["review_record_shape", "locators_grounded", "human_review_decision"],
        "scope": "Human spot-check record; no assumption about an upstream extractor's private schema.",
    },
    "semantic_mapping": {
        "required_artifact_types": ["mapping_plan"],
        "checks": ["mapping_plan_shape", "no_unreviewed_proposals", "approved_rules_explicit"],
        "scope": "Explicit source-item to canonical-field mapping, exact transformations, and review decisions.",
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
        "scope": "Model outputs bound to cohort/task hashes and Study-grouped split; no performance threshold is invented.",
    },
    "publication_handoff": {
        "required_artifact_types": ["publication_package_manifest", "publication_integrity_report"],
        "checks": ["package_identity", "writing_guide_present", "package_integrity_valid"],
        "scope": "Publication package, Writing Skill guide, hashes, and explicit completeness state.",
    },
}


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def _error(code: str, message: str, artifact_type: str | None = None) -> dict[str, str]:
    item = {"code": code, "message": message}
    if artifact_type:
        item["artifact_type"] = artifact_type
    return item


def _validate_source_inventory(payload: Any) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not isinstance(payload.get("items"), list):
        return [_error("SOURCE_INVENTORY_SHAPE_INVALID", "source_inventory requires schema_version 1.0 and an items array.", "source_inventory")]
    seen = set()
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            errors.append(_error("SOURCE_INVENTORY_ITEM_INVALID", f"items[{index}] must be an object.", "source_inventory"))
            continue
        required = ("inventory_id", "source_file", "source_sha256", "source_format", "locator_type", "locator", "mapping_status")
        if any(not _is_nonempty_string(item.get(key)) for key in required):
            errors.append(_error("SOURCE_INVENTORY_ITEM_INCOMPLETE", f"items[{index}] lacks required explicit locator/hash fields.", "source_inventory"))
        if not _is_sha256(item.get("source_sha256")):
            errors.append(_error("SOURCE_INVENTORY_HASH_INVALID", f"items[{index}].source_sha256 is not SHA-256.", "source_inventory"))
        identifier = item.get("inventory_id")
        if _is_nonempty_string(identifier):
            if identifier in seen:
                errors.append(_error("SOURCE_INVENTORY_ID_DUPLICATE", f"Duplicate inventory_id: {identifier}.", "source_inventory"))
            seen.add(identifier)
    return errors


def _validate_run_manifest(payload: Any, run_id: str, project_id: str) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict):
        return [_error("RUN_MANIFEST_SHAPE_INVALID", "run_manifest must be a JSON object.", "run_manifest")]
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != run_id or payload.get("project_id") != project_id:
        errors.append(_error("RUN_MANIFEST_IDENTITY_MISMATCH", "run_manifest schema/run/project identity does not match this acceptance.", "run_manifest"))
    if not isinstance(payload.get("source_artifacts"), list) or not payload["source_artifacts"]:
        errors.append(_error("RUN_MANIFEST_SOURCES_MISSING", "run_manifest must contain the initialized source_artifacts snapshot.", "run_manifest"))
    return errors


def _validate_extraction_review(payload: Any) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("EXTRACTION_REVIEW_SCHEMA_INVALID", "extraction_review_record requires schema_version 1.0.", "extraction_review_record")]
    hashes = payload.get("source_hashes")
    locators = payload.get("reviewed_locators")
    review = payload.get("human_review")
    if not isinstance(hashes, dict) or not hashes or any(not _is_sha256(value) for value in hashes.values()):
        errors.append(_error("EXTRACTION_SOURCE_HASHES_INVALID", "source_hashes must map source IDs to SHA-256 values.", "extraction_review_record"))
    if not isinstance(locators, list) or not locators:
        errors.append(_error("EXTRACTION_LOCATORS_MISSING", "reviewed_locators must be a non-empty array.", "extraction_review_record"))
    else:
        for index, locator in enumerate(locators):
            if not isinstance(locator, dict) or any(not _is_nonempty_string(locator.get(key)) for key in ("source_id", "locator_type", "locator", "review_status")):
                errors.append(_error("EXTRACTION_LOCATOR_INCOMPLETE", f"reviewed_locators[{index}] requires source_id, locator_type, locator, and review_status.", "extraction_review_record"))
                continue
            if locator["source_id"] not in hashes:
                errors.append(_error("EXTRACTION_LOCATOR_SOURCE_UNKNOWN", f"reviewed_locators[{index}] references an un-hashed source_id.", "extraction_review_record"))
            if locator["review_status"] not in {"SPOT_CHECKED", "REVIEW_REQUIRED", "UNREADABLE", "NOT_APPLICABLE"}:
                errors.append(_error("EXTRACTION_REVIEW_STATUS_INVALID", f"reviewed_locators[{index}] has an unsupported review_status.", "extraction_review_record"))
    if not isinstance(review, dict) or not all(_is_nonempty_string(review.get(key)) for key in ("reviewer", "reviewed_at", "decision")):
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_MISSING", "human_review requires reviewer, reviewed_at, and decision.", "extraction_review_record"))
    elif review.get("decision") not in {"ACCEPTED_WITH_LIMITATIONS", "REJECTED", "REQUIRES_FOLLOW_UP"}:
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_DECISION_INVALID", "human_review.decision is not a supported explicit decision.", "extraction_review_record"))
    return errors


def _validate_mapping_plan(payload: Any) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not _is_nonempty_string(payload.get("mapping_version")):
        return [_error("MAPPING_PLAN_SHAPE_INVALID", "mapping_plan requires schema_version 1.0 and mapping_version.", "mapping_plan")]
    if not _is_sha256(payload.get("source_inventory_sha256")):
        errors.append(_error("MAPPING_INVENTORY_HASH_INVALID", "mapping_plan must bind to source_inventory_sha256.", "mapping_plan"))
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        return errors + [_error("MAPPING_RULES_MISSING", "mapping_plan.rules must be a non-empty array.", "mapping_plan")]
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or not _is_nonempty_string(rule.get("mapping_rule_id")) or not _is_nonempty_string(rule.get("source_item_id")):
            errors.append(_error("MAPPING_RULE_INCOMPLETE", f"rules[{index}] requires mapping_rule_id and source_item_id.", "mapping_plan"))
            continue
        if rule.get("status") == "PROPOSED":
            errors.append(_error("MAPPING_RULE_UNREVIEWED", f"Mapping rule {rule['mapping_rule_id']} remains PROPOSED.", "mapping_plan"))
        if rule.get("status") == "APPROVED":
            review = rule.get("review")
            transform = rule.get("transformation")
            if not all(_is_nonempty_string(rule.get(key)) for key in ("target_entity", "target_field_id")):
                errors.append(_error("APPROVED_MAPPING_TARGET_MISSING", f"Approved rule {rule['mapping_rule_id']} lacks explicit target entity/field.", "mapping_plan"))
            if not isinstance(transform, dict) or not _is_nonempty_string(transform.get("type")) or not isinstance(transform.get("parameters"), dict):
                errors.append(_error("APPROVED_MAPPING_TRANSFORM_MISSING", f"Approved rule {rule['mapping_rule_id']} lacks explicit transformation and parameters.", "mapping_plan"))
            if not isinstance(review, dict) or not all(_is_nonempty_string(review.get(key)) for key in ("reviewer", "reviewed_at", "decision_note")):
                errors.append(_error("APPROVED_MAPPING_REVIEW_MISSING", f"Approved rule {rule['mapping_rule_id']} lacks explicit human review.", "mapping_plan"))
    return errors


def _validate_canonical_bundle(payload: Any) -> list[dict[str, str]]:
    from dor.canonical import validate_canonical_bundle
    errors = []
    if not isinstance(payload, dict):
        return [_error("CANONICAL_BUNDLE_INVALID", "canonical_bundle must be a JSON object.", "canonical_bundle")]
    if payload.get("schema_version") != "1.0" or not _is_nonempty_string(payload.get("project_id")) or not _is_nonempty_string(payload.get("mapping_version")):
        errors.append(_error("CANONICAL_BUNDLE_METADATA_INVALID", "canonical_bundle requires schema_version 1.0, project_id, and mapping_version.", "canonical_bundle"))
    result = validate_canonical_bundle(payload)
    errors.extend(_error("CANONICAL_BUNDLE_INVALID", f"{item.get('path')}: {item.get('message')}", "canonical_bundle")
                  for item in result.get("errors", []))
    return errors


def _validate_reconciliation(payload: Any, canonical_sha256: str) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("RECONCILIATION_REPORT_INVALID", "reconciliation_report requires schema_version 1.0.", "reconciliation_report")]
    if payload.get("bundle_sha256") != canonical_sha256:
        errors.append(_error("RECONCILIATION_BUNDLE_HASH_MISMATCH", "reconciliation_report.bundle_sha256 must equal the cited canonical_bundle SHA-256.", "reconciliation_report"))
    if payload.get("valid_bundle") is not True:
        errors.append(_error("RECONCILIATION_BUNDLE_NOT_VALID", "reconciliation_report does not report valid_bundle=true.", "reconciliation_report"))
    if not isinstance(payload.get("issues"), list) or payload.get("issue_count") != len(payload.get("issues", [])):
        errors.append(_error("RECONCILIATION_ISSUE_COUNT_MISMATCH", "reconciliation_report issue_count must equal issues length.", "reconciliation_report"))
    return errors


def _validate_cohort_report(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "eligible_observation_count", "eligible_study_count", "split_counts")
    if not isinstance(payload, dict) or payload.get("valid") is not True or any(key not in payload for key in required):
        return [_error("COHORT_REPORT_INVALID", "cohort_report must be a valid endpoint-specific cohort report with explicit counts and split_counts.", "cohort_report")]
    return []


def _validate_split_manifest(payload: Any, study_ids: set[str]) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("SPLIT_MANIFEST_INVALID", "split_manifest requires schema_version 1.0.", "split_manifest")]
    mapping = payload.get("study_to_split")
    leakage = payload.get("leakage_check")
    if not isinstance(mapping, dict) or not mapping or not isinstance(leakage, dict) or leakage.get("valid") is not True or leakage.get("study_overlap_count") != 0:
        return [_error("STUDY_SPLIT_LEAKAGE_INVALID", "split_manifest must contain study_to_split and a valid zero-overlap leakage_check.", "split_manifest")]
    if set(mapping) != study_ids:
        errors.append(_error("STUDY_SPLIT_COVERAGE_MISMATCH", "split_manifest study IDs must exactly match the acceptance source_snapshot.study_ids.", "split_manifest"))
    if not {"train", "validation", "test"}.issubset(set(mapping.values())):
        errors.append(_error("STUDY_SPLIT_PARTITION_MISSING", "A modelling split must include train, validation, and test Study groups.", "split_manifest"))
    return errors


def _validate_model_report(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "selected_model", "selected_candidate_id", "validation_comparison", "test_evaluation")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("MODEL_REPORT_INVALID", "model_report lacks required task identity, selection, validation, or test fields.", "model_report")]
    if not isinstance(payload.get("validation_comparison"), list) or not payload["validation_comparison"]:
        return [_error("MODEL_VALIDATION_COMPARISON_MISSING", "model_report.validation_comparison must be non-empty.", "model_report")]
    if not isinstance(payload.get("test_evaluation"), dict) or not payload["test_evaluation"]:
        return [_error("MODEL_TEST_EVALUATION_MISSING", "model_report.test_evaluation must be non-empty.", "model_report")]
    return []


def _validate_model_manifest(payload: Any) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("MODELING_RUN_MANIFEST_INVALID", "modeling_run_manifest requires schema_version 1.0.", "modeling_run_manifest")]
    inputs, outputs, splits = payload.get("input_hashes"), payload.get("output_hashes"), payload.get("study_ids_by_split")
    if not isinstance(inputs, dict) or not all(_is_sha256(inputs.get(key)) for key in ("cohort_sha256", "cohort_report_sha256", "split_manifest_sha256", "cohort_manifest_sha256", "task_sha256")):
        errors.append(_error("MODELING_INPUT_HASHES_INCOMPLETE", "modeling_run_manifest must bind all five cohort/task input hashes.", "modeling_run_manifest"))
    if not isinstance(outputs, dict) or not outputs or any(not _is_sha256(value) for value in outputs.values()):
        errors.append(_error("MODELING_OUTPUT_HASHES_INVALID", "modeling_run_manifest output_hashes must contain SHA-256 values.", "modeling_run_manifest"))
    if not isinstance(splits, dict) or not all(isinstance(splits.get(key), list) and splits[key] for key in ("train", "validation", "test")):
        errors.append(_error("MODELING_SPLIT_IDS_MISSING", "modeling_run_manifest requires non-empty train/validation/test Study ID lists.", "modeling_run_manifest"))
    elif set(splits["train"]) & set(splits["validation"]) or set(splits["train"]) & set(splits["test"]) or set(splits["validation"]) & set(splits["test"]):
        errors.append(_error("MODELING_STUDY_LEAKAGE", "Study IDs overlap across train/validation/test.", "modeling_run_manifest"))
    return errors


def _validate_publication_manifest(payload: Any, run_id: str, project_id: str) -> list[dict[str, str]]:
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("PUBLICATION_MANIFEST_INVALID", "publication_package_manifest requires schema_version 1.0.", "publication_package_manifest")]
    if payload.get("run_id") != run_id or payload.get("project_id") != project_id:
        errors.append(_error("PUBLICATION_PACKAGE_IDENTITY_MISMATCH", "Publication package run_id/project_id does not match this acceptance.", "publication_package_manifest"))
    if payload.get("writing_guide") != "README_FOR_WRITING_SKILL.md" or not _is_sha256(payload.get("writing_guide_sha256")):
        errors.append(_error("PUBLICATION_WRITING_GUIDE_INVALID", "Publication package must hash-bind README_FOR_WRITING_SKILL.md.", "publication_package_manifest"))
    if not isinstance(payload.get("artifacts"), list) or not isinstance(payload.get("completeness"), dict):
        errors.append(_error("PUBLICATION_PACKAGE_CONTENT_INVALID", "Publication package requires artifacts and completeness.", "publication_package_manifest"))
    return errors


def validate_stage_payload(artifact_type: str, payload: Any, *, run_id: str, project_id: str,
                           study_ids: set[str], canonical_sha256: str | None = None) -> list[dict[str, str]]:
    """Validate one typed evidence payload using the fixed implementation contract."""
    if artifact_type == "source_inventory":
        return _validate_source_inventory(payload)
    if artifact_type == "run_manifest":
        return _validate_run_manifest(payload, run_id, project_id)
    if artifact_type == "extraction_review_record":
        return _validate_extraction_review(payload)
    if artifact_type == "mapping_plan":
        return _validate_mapping_plan(payload)
    if artifact_type == "canonical_bundle":
        return _validate_canonical_bundle(payload)
    if artifact_type == "reconciliation_report":
        if canonical_sha256 is None:
            return [_error("CANONICAL_BUNDLE_HASH_REQUIRED", "A reconciliation report must be paired with the exact canonical_bundle evidence hash.", artifact_type)]
        return _validate_reconciliation(payload, canonical_sha256)
    if artifact_type == "cohort_report":
        return _validate_cohort_report(payload)
    if artifact_type == "split_manifest":
        return _validate_split_manifest(payload, study_ids)
    if artifact_type == "model_report":
        return _validate_model_report(payload)
    if artifact_type == "modeling_run_manifest":
        return _validate_model_manifest(payload)
    if artifact_type == "publication_package_manifest":
        return _validate_publication_manifest(payload, run_id, project_id)
    if artifact_type == "publication_integrity_report":
        if not isinstance(payload, dict) or payload.get("valid") is not True or not isinstance(payload.get("errors"), list) or payload["errors"]:
            return [_error("PUBLICATION_INTEGRITY_AUDIT_FAILED", "publication_integrity_report must report valid=true and an empty errors array.", artifact_type)]
        return []
    return [_error("UNKNOWN_STAGE_ARTIFACT_TYPE", f"Unsupported fixed evidence type: {artifact_type}.", artifact_type)]
