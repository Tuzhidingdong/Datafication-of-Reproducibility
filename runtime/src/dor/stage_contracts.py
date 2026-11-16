"""Versioned, implementation-owned V1.0 stage evidence contracts.

The registry fixes evidence types and executes structural/provenance checks. It
never infers scientific meaning, selects thresholds, or replaces human review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.1"

STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "source_selection": {
        "required_artifact_types": ["source_selection_manifest", "source_inventory"],
        "checks": ["selected_excluded_partition_exact", "selected_source_set_matches_run_snapshot", "excluded_source_reasons_present", "inventory_references_selected_sources_only"],
        "scope": "Agent-selected source inventory from declared structured-input metadata and explicit exclusions; filenames are labels, not semantics.",
    },
    "source_integrity": {
        "required_artifact_types": ["run_manifest"],
        "checks": ["run_manifest_identity", "source_snapshot_exact"],
        "scope": "Run Manager source snapshot and hash-chain verification are authoritative.",
    },
    "extraction_review": {
        "required_artifact_types": ["extraction_review_record"],
        "checks": ["source_hash_bindings", "exact_structured_record_locators", "human_structured_data_review_decision"],
        "scope": "Human review of delivered structured records and opaque upstream locator metadata only; original source-document contents are never accessed or verified by DoR.",
    },
    "semantic_mapping": {
        "required_artifact_types": ["mapping_plan"],
        "checks": ["inventory_hash_binding", "no_unreviewed_proposals", "approved_rules_explicit"],
        "scope": "Explicit source-item to canonical-field mappings, transformations, and review decisions.",
    },
    "canonical_reconciliation": {
        "required_artifact_types": ["canonical_bundle", "reconciliation_report", "reconciliation_decisions"],
        "checks": ["canonical_entity_integrity", "cross_entity_references", "reconciliation_bundle_binding"],
        "scope": "Study/System/Condition/Experiment/Observation/Comparison/Evidence graph integrity.",
    },
    "cohort_feasibility": {
        "required_artifact_types": ["modeling_task", "cohort_report", "split_manifest", "modeling_cohort_manifest", "modeling_cohort_csv"],
        "checks": ["cohort_report_identity", "study_group_split_integrity", "split_study_coverage"],
        "scope": "Endpoint-specific cohort and explicit Study-level split feasibility.",
    },
    "modeling_validation": {
        "required_artifact_types": ["model_report", "model_artifact", "modeling_run_manifest", "reproducibility_evaluation", "reproducibility_evaluation_manifest"],
        "checks": ["model_report_identity", "model_manifest_split_integrity", "study_leakage_absent"],
        "scope": "Model artifacts and metrics bound to the exact cohort/task and Study split; no performance threshold is invented.",
    },
    "publication_handoff": {
        "required_artifact_types": ["publication_package_manifest", "publication_integrity_report"],
        "checks": ["package_identity", "package_manifest_path_exact", "writing_guide_sha256_verified", "independent_package_tree_audit"],
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

    expected: dict[str, dict[str, Any]] = {}
    for item in source_snapshot:
        if isinstance(item, dict) and _nonempty(item.get("source_id")):
            source_id = item["source_id"]
            if source_id in expected:
                errors.append(_error("SOURCE_SNAPSHOT_DUPLICATE_ID", f"Run source snapshot contains duplicate source_id {source_id}.", "source_selection_manifest"))
            expected[source_id] = item

    selected = payload.get("selected_sources")
    if not isinstance(selected, list) or not selected:
        errors.append(_error("SOURCE_SELECTION_SOURCES_MISSING", "selected_sources must be a non-empty array.", "source_selection_manifest"))
        selected = []
    exclusions = payload.get("excluded_sources")
    if not isinstance(exclusions, list):
        errors.append(_error("SOURCE_SELECTION_EXCLUSIONS_INVALID", "excluded_sources must be an array, even when empty.", "source_selection_manifest"))
        exclusions = []

    assigned: dict[str, str] = {}

    def check_binding(item: Any, index: int, collection: str, required: tuple[str, ...]) -> None:
        if not isinstance(item, dict) or any(not _nonempty(item.get(key)) for key in required) or not _sha256(item.get("sha256")):
            errors.append(_error("SOURCE_SELECTION_ITEM_INVALID", f"{collection}[{index}] requires source_id, role, path, SHA-256" + (", and reason." if collection == "excluded_sources" else "."), "source_selection_manifest"))
            return
        source_id = item["source_id"]
        if source_id in assigned:
            errors.append(_error("SOURCE_SELECTION_DUPLICATE_OR_OVERLAPPING_ID", f"Source {source_id} is duplicated or appears in both selected_sources and excluded_sources.", "source_selection_manifest"))
        assigned[source_id] = collection
        bound = expected.get(source_id)
        if (bound is None
                or Path(str(bound.get("path", ""))).expanduser().resolve(strict=False) != Path(item["path"]).expanduser().resolve(strict=False)
                or bound.get("sha256") != item["sha256"]
                or bound.get("role") != item["role"]):
            errors.append(_error("SOURCE_SELECTION_NOT_BOUND_TO_SNAPSHOT", f"{collection}[{index}] source {source_id} differs from the acceptance source snapshot.", "source_selection_manifest"))

    for index, item in enumerate(selected):
        check_binding(item, index, "selected_sources", ("source_id", "role", "path"))
    for index, item in enumerate(exclusions):
        check_binding(item, index, "excluded_sources", ("source_id", "role", "path", "reason"))

    if set(assigned) != set(expected):
        missing = sorted(set(expected) - set(assigned))
        unknown = sorted(set(assigned) - set(expected))
        errors.append(_error("SOURCE_SELECTION_PARTITION_MISMATCH", f"selected_sources and excluded_sources must partition the exact Run source snapshot; missing={missing}, unknown={unknown}.", "source_selection_manifest"))
    if payload.get("study_ids") != sorted(study_ids):
        errors.append(_error("SOURCE_SELECTION_STUDY_SET_MISMATCH", "source_selection_manifest.study_ids must equal the sorted explicit acceptance Study IDs.", "source_selection_manifest"))
    return errors


def _validate_source_inventory(payload: Any, source_snapshot: list[dict[str, Any]],
                               selected_source_ids: set[str] | None = None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not isinstance(payload.get("items"), list) or not payload["items"]:
        return [_error("SOURCE_INVENTORY_SHAPE_INVALID", "source_inventory requires schema_version 1.0 and a non-empty items array.", "source_inventory")]
    selected_snapshot = [
        item for item in source_snapshot if isinstance(item, dict)
        and (selected_source_ids is None or item.get("source_id") in selected_source_ids)
    ]
    snapshot_by_name_hash = {
        (Path(str(item.get("path", ""))).name, item.get("sha256"))
        for item in selected_snapshot
    }
    source_ids_by_name_hash: dict[tuple[str, Any], set[str]] = {}
    for item in selected_snapshot:
        source_id = item.get("source_id")
        if _nonempty(source_id):
            key = (Path(str(item.get("path", ""))).name, item.get("sha256"))
            source_ids_by_name_hash.setdefault(key, set()).add(source_id)
    for (source_name, source_hash), source_ids in source_ids_by_name_hash.items():
        if len(source_ids) > 1:
            errors.append(_error(
                "SOURCE_INVENTORY_SOURCE_ID_AMBIGUOUS",
                f"Selected sources {sorted(source_ids)} share the same filename and hash ({source_name}); inventory locators cannot distinguish their source identity.",
                "source_inventory",
            ))
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
    acceptance_sources = payload.get("acceptance_source_artifacts")
    if acceptance_sources is not None:
        if not isinstance(acceptance_sources, list):
            errors.append(_error("RUN_MANIFEST_SOURCE_SET_MISMATCH", "run_manifest.acceptance_source_artifacts must be an array.", "run_manifest"))
            acceptance_sources = []
        source_entries = [
            {
                "artifact_id": item.get("source_id"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "role": item.get("role"),
            }
            for item in acceptance_sources if isinstance(item, dict)
        ]
    else:
        source_entries = payload.get("source_artifacts")
    actual: dict[str, dict[str, Any]] = {}
    if not isinstance(source_entries, list):
        errors.append(_error("RUN_MANIFEST_SOURCE_SET_MISMATCH", "Run Manifest acceptance/source artifact set must be an array.", "run_manifest"))
        source_entries = []
    for index, artifact in enumerate(source_entries):
        if not isinstance(artifact, dict) or not _nonempty(artifact.get("artifact_id")):
            errors.append(_error("RUN_MANIFEST_SOURCE_ENTRY_INVALID", f"source_artifacts[{index}] requires an explicit source/artifact ID.", "run_manifest"))
            continue
        artifact_id = artifact["artifact_id"]
        if artifact_id in actual:
            errors.append(_error("RUN_MANIFEST_SOURCE_ID_DUPLICATE", f"run_manifest contains duplicate source artifact ID {artifact_id}.", "run_manifest"))
            continue
        actual[artifact_id] = artifact
    expected = {item.get("source_id"): item for item in source_snapshot if isinstance(item, dict)}
    if set(actual) != set(expected):
        errors.append(_error("RUN_MANIFEST_SOURCE_SET_MISMATCH", "run_manifest source_artifacts must exactly match source_snapshot IDs.", "run_manifest"))
    for source_id, item in expected.items():
        bound = actual.get(source_id)
        if bound is None:
            continue
        if (Path(str(bound.get("path", ""))).expanduser().resolve(strict=False) != Path(str(item.get("path", ""))).expanduser().resolve(strict=False)
                or bound.get("sha256") != item.get("sha256")
                or ("role" in bound and bound.get("role") != item.get("role"))):
            errors.append(_error("RUN_MANIFEST_SOURCE_BINDING_MISMATCH", f"Run Manifest source {source_id} role/path/hash differs from source_snapshot.", "run_manifest"))
    return errors


def _validate_extraction_review(payload: Any, source_snapshot: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("EXTRACTION_REVIEW_SCHEMA_INVALID", "extraction_review_record requires schema_version 1.0.", "extraction_review_record")]
    hashes = payload.get("source_hashes")
    expected = {item.get("source_id"): item.get("sha256") for item in source_snapshot if isinstance(item, dict)}
    if not isinstance(hashes, dict) or hashes != expected:
        errors.append(_error("EXTRACTION_SOURCE_HASH_BINDING_MISMATCH", "source_hashes must exactly match the selected source IDs and SHA-256 values.", "extraction_review_record"))
    locator_source_ids: set[str] = set()
    structured_sources_with_review: set[str] = set()
    source_roles = {
        item.get("source_id"): item.get("role")
        for item in source_snapshot if isinstance(item, dict)
    }
    locators = payload.get("reviewed_locators")
    if not isinstance(locators, list) or not locators:
        errors.append(_error("EXTRACTION_LOCATORS_MISSING", "reviewed_locators must be a non-empty array.", "extraction_review_record"))
    else:
        for index, locator in enumerate(locators):
            if not isinstance(locator, dict) or any(not _nonempty(locator.get(key)) for key in ("source_id", "locator_type", "locator", "review_status")):
                errors.append(_error("EXTRACTION_LOCATOR_INCOMPLETE", f"reviewed_locators[{index}] requires source_id, locator_type, locator, and review_status.", "extraction_review_record"))
                continue
            source_id = locator["source_id"]
            status = locator["review_status"]
            role = source_roles.get(source_id)
            if source_id not in expected:
                errors.append(_error("EXTRACTION_LOCATOR_SOURCE_UNKNOWN", f"reviewed_locators[{index}] references a source outside the selected source set.", "extraction_review_record"))
            else:
                locator_source_ids.add(source_id)
            if status not in {"STRUCTURED_RECORD_REVIEWED", "UPSTREAM_EXTRACTION_UNVERIFIED", "REVIEW_REQUIRED", "NOT_APPLICABLE"}:
                errors.append(_error("EXTRACTION_REVIEW_STATUS_INVALID", f"reviewed_locators[{index}] has an unsupported review_status for structured-data-only review.", "extraction_review_record"))
            elif status == "REVIEW_REQUIRED":
                errors.append(_error("EXTRACTION_LOCATOR_REVIEW_REQUIRED", f"reviewed_locators[{index}] remains unresolved and blocks extraction_review PASS.", "extraction_review_record"))
            if role in {"PRIMARY_PAPER", "SUPPLEMENTARY_INFORMATION"} and status == "STRUCTURED_RECORD_REVIEWED":
                errors.append(_error(
                    "ORIGINAL_DOCUMENT_CONTENT_REVIEW_FORBIDDEN",
                    f"Source {source_id} is provenance-only; paper/SI content must never be marked as inspected or reviewed.",
                    "extraction_review_record",
                ))
            if role == "STRUCTURED_DATA" and status == "STRUCTURED_RECORD_REVIEWED":
                structured_sources_with_review.add(source_id)
    for source_id, role in source_roles.items():
        if role == "STRUCTURED_DATA" and source_id in expected and source_id not in structured_sources_with_review:
            errors.append(_error(
                "STRUCTURED_SOURCE_REVIEW_MISSING",
                f"Selected structured source {source_id} needs at least one reviewed row/field locator.",
                "extraction_review_record",
            ))
    review = payload.get("human_review")
    if not isinstance(review, dict) or not all(_nonempty(review.get(key)) for key in ("reviewer", "reviewed_at", "decision")):
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_MISSING", "human_review requires reviewer, reviewed_at, and decision.", "extraction_review_record"))
    elif review.get("decision") not in {"ACCEPTED_WITH_LIMITATIONS", "REJECTED", "REQUIRES_FOLLOW_UP"}:
        errors.append(_error("EXTRACTION_HUMAN_REVIEW_DECISION_INVALID", "human_review.decision is not an explicit supported decision.", "extraction_review_record"))
    elif review.get("decision") != "ACCEPTED_WITH_LIMITATIONS":
        errors.append(_error("EXTRACTION_REVIEW_NOT_ACCEPTED", "A PASS extraction_review stage requires ACCEPTED_WITH_LIMITATIONS; rejected or follow-up decisions must remain FAIL/BLOCKED.", "extraction_review_record"))
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
    provenance = payload.get("build_provenance")
    if (not isinstance(provenance, dict)
            or not _sha256(provenance.get("mapping_plan_sha256"))
            or not _sha256(provenance.get("source_inventory_sha256"))):
        errors.append(_error("CANONICAL_BUILD_PROVENANCE_INVALID", "canonical_bundle requires exact mapping_plan and source_inventory SHA-256 provenance.", "canonical_bundle"))
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
    issues = payload.get("issues")
    issue_count = payload.get("issue_count")
    if (not isinstance(issues, list) or not isinstance(issue_count, int)
            or isinstance(issue_count, bool) or issue_count != len(issues)):
        errors.append(_error("RECONCILIATION_ISSUE_COUNT_MISMATCH", "reconciliation_report issue_count must be an integer (not boolean) equal to issues length.", "reconciliation_report"))
    if isinstance(issues, list):
        seen_issue_ids: set[str] = set()
        for index, issue in enumerate(issues):
            issue_id = issue.get("issue_id") if isinstance(issue, dict) else None
            if not _nonempty(issue_id):
                errors.append(_error("RECONCILIATION_ISSUE_ID_INVALID", f"issues[{index}] requires a non-empty string issue_id.", "reconciliation_report"))
            elif issue_id in seen_issue_ids:
                errors.append(_error("RECONCILIATION_ISSUE_ID_DUPLICATE", f"Duplicate reconciliation issue_id: {issue_id}.", "reconciliation_report"))
            else:
                seen_issue_ids.add(issue_id)
    return errors


def _validate_modeling_task(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "outcome_type",
                "outcome_value_field", "outcome_unit", "feature_bindings", "split")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("MODELING_TASK_INVALID", "modeling_task must contain exact task/endpoint, outcome, feature, unit, and split definitions.", "modeling_task")]
    errors: list[dict[str, str]] = []
    if not all(_nonempty(payload.get(key)) for key in ("task_id", "target_id", "endpoint_definition")):
        errors.append(_error("MODELING_TASK_IDENTITY_INVALID", "task_id, target_id, and endpoint_definition must be non-empty strings.", "modeling_task"))
    if payload.get("outcome_type") not in {"NUMERIC", "CATEGORICAL"} or payload.get("outcome_value_field") not in {"raw_value", "normalized_value"}:
        errors.append(_error("MODELING_TASK_OUTCOME_INVALID", "outcome_type or outcome_value_field is unsupported.", "modeling_task"))
    if payload.get("outcome_unit") is not None and not isinstance(payload.get("outcome_unit"), str):
        errors.append(_error("MODELING_TASK_UNIT_INVALID", "outcome_unit must be an exact string or null.", "modeling_task"))
    bindings = payload.get("feature_bindings")
    if not isinstance(bindings, list) or not bindings:
        errors.append(_error("MODELING_TASK_FEATURES_MISSING", "At least one explicit feature binding is required.", "modeling_task"))
    else:
        feature_ids: set[str] = set()
        for index, binding in enumerate(bindings):
            fields = ("feature_id", "condition_type", "value_field", "value_type")
            if not isinstance(binding, dict) or any(not _nonempty(binding.get(key)) for key in fields) or "expected_unit" not in binding:
                errors.append(_error("MODELING_TASK_FEATURE_INVALID", f"feature_bindings[{index}] requires exact feature/condition/field/type/unit fields.", "modeling_task"))
                continue
            if binding["value_field"] not in {"raw_value", "normalized_value"} or binding["value_type"] not in {"NUMERIC", "CATEGORICAL"}:
                errors.append(_error("MODELING_TASK_FEATURE_TYPE_INVALID", f"feature_bindings[{index}] has unsupported field/type.", "modeling_task"))
            if binding["feature_id"] in feature_ids:
                errors.append(_error("MODELING_TASK_FEATURE_ID_DUPLICATE", f"Duplicate feature_id: {binding['feature_id']}.", "modeling_task"))
            feature_ids.add(binding["feature_id"])
            if binding["expected_unit"] is not None and not isinstance(binding["expected_unit"], str):
                errors.append(_error("MODELING_TASK_FEATURE_UNIT_INVALID", f"feature_bindings[{index}].expected_unit must be a string or null.", "modeling_task"))
    split = payload.get("split")
    if not isinstance(split, dict) or split.get("strategy") not in {"GROUPED_HOLDOUT", "EXPLICIT_STUDIES"}:
        errors.append(_error("MODELING_TASK_SPLIT_INVALID", "split.strategy must be GROUPED_HOLDOUT or EXPLICIT_STUDIES.", "modeling_task"))
    elif split["strategy"] == "EXPLICIT_STUDIES":
        explicit_groups: dict[str, set[str]] = {}
        for key in ("validation_study_ids", "test_study_ids"):
            values = split.get(key)
            if not isinstance(values, list) or not values or any(not _nonempty(value) for value in values) or len(values) != len(set(values)):
                errors.append(_error("MODELING_TASK_EXPLICIT_SPLIT_INVALID", f"split.{key} must contain unique explicit Study IDs.", "modeling_task"))
            else:
                explicit_groups[key] = set(values)
        if len(explicit_groups) == 2 and explicit_groups["validation_study_ids"].intersection(explicit_groups["test_study_ids"]):
            errors.append(_error("MODELING_TASK_EXPLICIT_SPLIT_OVERLAP", "Validation and test Study IDs must be disjoint in modeling_task.", "modeling_task"))
    elif split["strategy"] == "GROUPED_HOLDOUT":
        fractions = split.get("fractions")
        if not isinstance(fractions, dict) or any(not isinstance(fractions.get(key), (int, float)) or isinstance(fractions.get(key), bool) for key in ("train", "validation", "test")):
            errors.append(_error("MODELING_TASK_SPLIT_FRACTIONS_INVALID", "GROUPED_HOLDOUT requires numeric train/validation/test fractions.", "modeling_task"))
        elif any(fractions[key] <= 0 for key in ("train", "validation", "test")) or abs(sum(fractions[key] for key in ("train", "validation", "test")) - 1.0) > 1e-9:
            errors.append(_error("MODELING_TASK_SPLIT_FRACTIONS_INVALID", "Study split fractions must be positive and sum to 1.", "modeling_task"))
    return errors


def _validate_cohort_manifest(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "bundle_sha256", "task_sha256", "artifact_sha256",
                "eligible_observation_count", "eligible_study_count")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("COHORT_MANIFEST_INVALID", "modeling_cohort_manifest lacks task/bundle hashes, counts, or artifact hashes.", "modeling_cohort_manifest")]
    errors: list[dict[str, str]] = []
    if not _sha256(payload.get("bundle_sha256")) or not _sha256(payload.get("task_sha256")):
        errors.append(_error("COHORT_MANIFEST_INPUT_HASH_INVALID", "Cohort manifest bundle/task hashes must be SHA-256.", "modeling_cohort_manifest"))
    hashes = payload.get("artifact_sha256")
    if not isinstance(hashes, dict) or not all(_sha256(hashes.get(key)) for key in ("modeling_cohort.csv", "cohort_report.json", "split_manifest.json")):
        errors.append(_error("COHORT_MANIFEST_OUTPUT_HASH_INVALID", "Cohort manifest must hash-bind cohort CSV, report, and split manifest.", "modeling_cohort_manifest"))
    for key in ("eligible_observation_count", "eligible_study_count"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(_error("COHORT_MANIFEST_COUNT_INVALID", f"{key} must be a positive integer.", "modeling_cohort_manifest"))
    return errors


def _validate_cohort_report(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "eligible_observation_count",
                "eligible_study_count", "eligible_study_ids", "split_counts",
                "bundle_sha256", "task_sha256")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or payload.get("valid") is not True or any(key not in payload for key in required):
        return [_error("COHORT_REPORT_INVALID", "cohort_report must expose a valid schema, exact task identity, Study IDs, counts, and input hashes.", "cohort_report")]
    errors: list[dict[str, str]] = []
    study_ids = payload.get("eligible_study_ids")
    if not isinstance(study_ids, list) or not study_ids or any(not _nonempty(value) for value in study_ids) or len(study_ids) != len(set(study_ids)):
        return [_error("COHORT_ELIGIBLE_STUDY_IDS_INVALID", "eligible_study_ids must be a non-empty unique list of Study IDs.", "cohort_report")]
    if payload.get("eligible_study_count") != len(study_ids):
        errors.append(_error("COHORT_STUDY_COUNT_MISMATCH", "eligible_study_count must equal eligible_study_ids length.", "cohort_report"))
    for key in ("eligible_study_count", "eligible_observation_count"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(_error("COHORT_COUNT_INVALID", f"{key} must be a positive integer.", "cohort_report"))
    if not _sha256(payload.get("bundle_sha256")) or not _sha256(payload.get("task_sha256")):
        errors.append(_error("COHORT_INPUT_HASH_INVALID", "cohort_report must bind the exact bundle and modeling task SHA-256 values.", "cohort_report"))
    return errors


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
    required = ("task_id", "target_id", "endpoint_definition", "outcome_type",
                "outcome_value_field", "outcome_unit", "primary_selection_metric",
                "selected_model", "selected_candidate_id", "validation_comparison",
                "test_evaluation")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("MODEL_REPORT_INVALID", "model_report lacks task/endpoint outcome definitions, selection metric, or validation/test fields.", "model_report")]
    errors: list[dict[str, str]] = []
    if payload.get("outcome_type") not in {"NUMERIC", "CATEGORICAL"}:
        errors.append(_error("MODEL_REPORT_OUTCOME_TYPE_INVALID", "model_report.outcome_type must be NUMERIC or CATEGORICAL.", "model_report"))
    if payload.get("outcome_value_field") not in {"raw_value", "normalized_value"}:
        errors.append(_error("MODEL_REPORT_OUTCOME_FIELD_INVALID", "model_report.outcome_value_field must be an explicit canonical value field.", "model_report"))
    if payload.get("outcome_unit") is not None and not isinstance(payload.get("outcome_unit"), str):
        errors.append(_error("MODEL_REPORT_OUTCOME_UNIT_INVALID", "model_report.outcome_unit must be an exact string or null.", "model_report"))
    if not all(_nonempty(payload.get(key)) for key in ("task_id", "target_id", "endpoint_definition", "primary_selection_metric", "selected_model", "selected_candidate_id")):
        errors.append(_error("MODEL_REPORT_IDENTITY_INVALID", "model_report identity and model-selection fields must be non-empty strings.", "model_report"))
    if not isinstance(payload.get("validation_comparison"), list) or not payload["validation_comparison"]:
        errors.append(_error("MODEL_VALIDATION_COMPARISON_MISSING", "model_report.validation_comparison must be non-empty.", "model_report"))
    if not isinstance(payload.get("test_evaluation"), dict) or not payload["test_evaluation"]:
        errors.append(_error("MODEL_TEST_EVALUATION_MISSING", "model_report.test_evaluation must be non-empty.", "model_report"))
    return errors


def _validate_model_artifact(payload: Any) -> list[dict[str, str]]:
    required = ("schema_version", "engine_version", "task_id", "model_type", "target_id",
                "endpoint_definition", "outcome_value_field", "outcome_unit", "feature_bindings",
                "selected_candidate_id", "selection_metric", "training_observation_ids",
                "training_study_ids", "test_observation_ids", "model_parameters")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("MODEL_ARTIFACT_INVALID", "model_artifact lacks serialized model identity, feature binding, or training/test IDs.", "model_artifact")]
    errors: list[dict[str, str]] = []
    if payload.get("model_type") not in {"mean_baseline", "ridge_regression", "majority_class_baseline", "mixed_naive_bayes"}:
        errors.append(_error("MODEL_ARTIFACT_TYPE_INVALID", "model_artifact.model_type is unsupported.", "model_artifact"))
    feature_bindings = payload.get("feature_bindings")
    if (not isinstance(feature_bindings, list) or not feature_bindings
            or any(not isinstance(value, dict) or any(not _nonempty(value.get(key)) for key in (
                "feature_id", "condition_type", "value_field", "value_type"
            )) or "expected_unit" not in value for value in feature_bindings)):
        errors.append(_error("MODEL_ARTIFACT_FEATURE_BINDINGS_INVALID", "model_artifact.feature_bindings must contain explicit feature, condition, field, type, and unit bindings.", "model_artifact"))
    for key in ("training_observation_ids", "training_study_ids", "test_observation_ids"):
        values = payload.get(key)
        if (not isinstance(values, list) or any(not _nonempty(value) for value in values)
                or len(values) != len(set(values))):
            errors.append(_error("MODEL_ARTIFACT_LIST_INVALID", f"model_artifact.{key} must be an array of unique non-empty IDs.", "model_artifact"))
    if not isinstance(payload.get("model_parameters"), dict):
        errors.append(_error("MODEL_ARTIFACT_PARAMETERS_INVALID", "model_parameters must be an object.", "model_artifact"))
    training, test = payload.get("training_study_ids"), payload.get("test_study_ids")
    if isinstance(training, list) and isinstance(test, list) and set(training).intersection(test):
        errors.append(_error("MODEL_ARTIFACT_STUDY_LEAKAGE", "Training and test Study IDs overlap in serialized model artifact.", "model_artifact"))
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


def _validate_reproducibility_evaluation(payload: Any) -> list[dict[str, str]]:
    required = ("task_id", "target_id", "endpoint_definition", "fold_count", "study_count",
                "observation_count", "folds", "per_study_performance", "validation_scope", "uncertainty")
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or any(key not in payload for key in required):
        return [_error("REPRODUCIBILITY_EVALUATION_INVALID", "Nested evaluation lacks task, fold, Study, or performance fields.", "reproducibility_evaluation")]
    errors: list[dict[str, str]] = []
    expected_scope = "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION"
    if payload.get("validation_scope") != expected_scope:
        errors.append(_error("REPRODUCIBILITY_SCOPE_INVALID", "Nested evaluation scope must explicitly state Study-grouped validation and its limits.", "reproducibility_evaluation"))
    studies, folds = payload.get("study_count"), payload.get("folds")
    if not isinstance(studies, int) or isinstance(studies, bool) or studies < 4:
        errors.append(_error("REPRODUCIBILITY_STUDY_COUNT_INVALID", "Nested Study-grouped validation requires at least four Studies.", "reproducibility_evaluation"))
    if not isinstance(folds, list) or not isinstance(payload.get("fold_count"), int) or len(folds) != payload.get("fold_count") or len(folds) < 4:
        return errors + [_error("REPRODUCIBILITY_FOLD_COUNT_INVALID", "fold_count must equal at least four fold records.", "reproducibility_evaluation")]
    held_out: dict[str, int] = {}
    for index, fold in enumerate(folds):
        if not isinstance(fold, dict):
            errors.append(_error("REPRODUCIBILITY_FOLD_INVALID", f"folds[{index}] must be an object.", "reproducibility_evaluation"))
            continue
        test_ids, outer_train = fold.get("test_study_ids"), fold.get("outer_training_study_ids")
        inner_train, inner_valid = fold.get("inner_training_study_ids"), fold.get("inner_validation_study_ids")
        groups = (test_ids, outer_train, inner_train, inner_valid)
        if any(not isinstance(group, list) or not group or any(not _nonempty(value) for value in group) for group in groups):
            errors.append(_error("REPRODUCIBILITY_FOLD_GROUPS_INVALID", f"folds[{index}] requires non-empty explicit Study ID groups.", "reproducibility_evaluation"))
            continue
        if any(len(group) != len(set(group)) for group in groups):
            errors.append(_error("REPRODUCIBILITY_FOLD_GROUPS_DUPLICATE", f"folds[{index}] contains duplicate Study IDs within a group.", "reproducibility_evaluation"))
            continue
        if set(test_ids).intersection(outer_train) or set(inner_train).intersection(inner_valid):
            errors.append(_error("REPRODUCIBILITY_FOLD_LEAKAGE", f"folds[{index}] contains test/outer-training or inner-training/validation overlap.", "reproducibility_evaluation"))
        if not set(inner_train).issubset(set(outer_train)) or not set(inner_valid).issubset(set(outer_train)):
            errors.append(_error("REPRODUCIBILITY_INNER_GROUP_OUTSIDE_OUTER_TRAIN", f"folds[{index}] inner groups must be subsets of outer-training Studies.", "reproducibility_evaluation"))
        if set(inner_train) | set(inner_valid) != set(outer_train):
            errors.append(_error("REPRODUCIBILITY_INNER_GROUP_COVERAGE", f"folds[{index}] inner training/validation groups must cover all outer-training Studies.", "reproducibility_evaluation"))
        for study_id in test_ids:
            held_out[study_id] = held_out.get(study_id, 0) + 1
    performance = payload.get("per_study_performance")
    performance_values = [
        item.get("study_id") for item in performance
        if isinstance(item, dict) and _nonempty(item.get("study_id"))
    ] if isinstance(performance, list) else []
    performance_ids = set(performance_values)
    performance_rows_valid = (
        isinstance(performance, list) and len(performance) == len(performance_ids)
        and all(isinstance(item, dict) and _nonempty(item.get("study_id")) for item in performance)
    )
    if not performance_rows_valid or not performance_ids or performance_ids != set(held_out):
        errors.append(_error("REPRODUCIBILITY_PER_STUDY_COVERAGE_MISMATCH", "per_study_performance must contain one record for every outer held-out Study ID.", "reproducibility_evaluation"))
    if any(count != 1 for count in held_out.values()):
        errors.append(_error("REPRODUCIBILITY_STUDY_NOT_HELD_OUT_ONCE", "Each Study must appear in exactly one outer test fold.", "reproducibility_evaluation"))
    universe = set(held_out)
    for index, fold in enumerate(folds):
        if isinstance(fold, dict) and isinstance(fold.get("test_study_ids"), list) and isinstance(fold.get("outer_training_study_ids"), list):
            test_group, outer_group = set(fold["test_study_ids"]), set(fold["outer_training_study_ids"])
            if test_group | outer_group != universe:
                errors.append(_error("REPRODUCIBILITY_OUTER_GROUP_COVERAGE", f"folds[{index}] outer test/training Studies must cover the complete evaluation Study set.", "reproducibility_evaluation"))

    if isinstance(studies, int) and len(held_out) != studies:
        errors.append(_error("REPRODUCIBILITY_STUDY_COUNT_MISMATCH", "study_count must equal the unique outer held-out Study count.", "reproducibility_evaluation"))
    if not isinstance(payload.get("uncertainty"), dict) or payload["uncertainty"].get("status") != "NOT_CALIBRATED":
        errors.append(_error("REPRODUCIBILITY_UNCERTAINTY_STATUS_INVALID", "Nested evaluation uncertainty must remain NOT_CALIBRATED.", "reproducibility_evaluation"))
    return errors


def _validate_reproducibility_manifest(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("REPRODUCIBILITY_MANIFEST_INVALID", "reproducibility_evaluation_manifest requires schema_version 1.0.", "reproducibility_evaluation_manifest")]
    errors: list[dict[str, str]] = []
    inputs, outputs, ids = payload.get("input_hashes"), payload.get("output_hashes"), payload.get("study_ids")
    required_inputs = ("cohort_sha256", "cohort_report_sha256", "split_manifest_sha256", "cohort_manifest_sha256", "task_sha256")
    if not isinstance(inputs, dict) or not all(_sha256(inputs.get(key)) for key in required_inputs):
        errors.append(_error("REPRODUCIBILITY_INPUT_HASHES_INVALID", "Nested evaluation manifest must bind cohort/report/split/manifest/task hashes.", "reproducibility_evaluation_manifest"))
    if not isinstance(outputs, dict) or not outputs or any(not _sha256(value) for value in outputs.values()):
        errors.append(_error("REPRODUCIBILITY_OUTPUT_HASHES_INVALID", "Nested evaluation output_hashes must contain SHA-256 values.", "reproducibility_evaluation_manifest"))
    if not isinstance(ids, list) or len(ids) < 4 or any(not _nonempty(value) for value in ids) or len(ids) != len(set(ids)):
        errors.append(_error("REPRODUCIBILITY_MANIFEST_STUDY_IDS_INVALID", "Nested evaluation manifest requires at least four unique Study IDs.", "reproducibility_evaluation_manifest"))
    if payload.get("selection_protocol") != "NESTED_INNER_STUDY_HOLDOUT" or payload.get("test_protocol") != "OUTER_GROUPED_K_FOLD_EACH_STUDY_HELD_OUT_ONCE":
        errors.append(_error("REPRODUCIBILITY_PROTOCOL_INVALID", "Nested evaluation manifest protocols do not match the fixed supported protocols.", "reproducibility_evaluation_manifest"))
    if payload.get("uncertainty_status") != "DESCRIPTIVE_CROSS_STUDY_ERROR_ONLY_NOT_CALIBRATED":
        errors.append(_error("REPRODUCIBILITY_MANIFEST_UNCERTAINTY_INVALID", "Nested evaluation manifest must state that uncertainty is not calibrated.", "reproducibility_evaluation_manifest"))
    return errors


def _validate_publication_manifest(payload: Any, run_id: str, project_id: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        return [_error("PUBLICATION_MANIFEST_INVALID", "publication_package_manifest requires schema_version 1.0.", "publication_package_manifest")]
    if payload.get("run_id") != run_id or payload.get("project_id") != project_id:
        errors.append(_error("PUBLICATION_PACKAGE_IDENTITY_MISMATCH", "Publication package run_id/project_id does not match this acceptance.", "publication_package_manifest"))
    if not _nonempty(payload.get("package_version")):
        errors.append(_error("PUBLICATION_PACKAGE_VERSION_INVALID", "package_version must be a non-empty string.", "publication_package_manifest"))
    if payload.get("writing_guide") != "README_FOR_WRITING_SKILL.md" or not _sha256(payload.get("writing_guide_sha256")):
        errors.append(_error("PUBLICATION_WRITING_GUIDE_INVALID", "Publication package must hash-bind README_FOR_WRITING_SKILL.md.", "publication_package_manifest"))
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, dict) or any(not _nonempty(key) or not _sha256(value) for key, value in source_hashes.items()):
        errors.append(_error("PUBLICATION_SOURCE_HASHES_INVALID", "source_hashes must be an object of explicit source IDs/labels to SHA-256 values.", "publication_package_manifest"))
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not isinstance(payload.get("completeness"), dict):
        errors.append(_error("PUBLICATION_PACKAGE_CONTENT_INVALID", "Publication package requires a non-empty artifact index and completeness object.", "publication_package_manifest"))
    else:
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict) or any(not _nonempty(artifact.get(key)) for key in ("artifact_id", "path", "type", "description", "status")):
                errors.append(_error("PUBLICATION_ARTIFACT_ENTRY_INVALID", f"artifacts[{index}] requires artifact_id/path/type/description/status.", "publication_package_manifest"))
                continue
            if artifact["artifact_id"] in seen_ids or artifact["path"] in seen_paths:
                errors.append(_error("PUBLICATION_ARTIFACT_ID_OR_PATH_DUPLICATE", f"artifacts[{index}] duplicates an artifact ID or package path.", "publication_package_manifest"))
            seen_ids.add(artifact["artifact_id"])
            seen_paths.add(artifact["path"])
            if artifact["status"] not in {"complete", "partial", "not_generated", "not_applicable", "requires_review"}:
                errors.append(_error("PUBLICATION_ARTIFACT_STATUS_INVALID", f"artifacts[{index}] has an unsupported status.", "publication_package_manifest"))
            if artifact["status"] in {"complete", "partial"} and not _sha256(artifact.get("sha256")):
                errors.append(_error("PUBLICATION_ARTIFACT_HASH_MISSING", f"artifacts[{index}] requires an exact SHA-256 for complete/partial status.", "publication_package_manifest"))
    completeness = payload.get("completeness")
    if isinstance(completeness, dict):
        if (completeness.get("status") not in {"complete", "partial", "requires_review"}
                or not isinstance(completeness.get("unresolved_items"), list)):
            errors.append(_error("PUBLICATION_COMPLETENESS_INVALID", "Publication completeness requires a supported status and unresolved_items array.", "publication_package_manifest"))
        elif isinstance(artifacts, list):
            has_review = any(isinstance(item, dict) and item.get("status") == "requires_review" for item in artifacts)
            has_partial = any(isinstance(item, dict) and item.get("status") in {"partial", "not_generated"} for item in artifacts)
            derived_status = "requires_review" if has_review else ("partial" if has_partial else "complete")
            derived_unresolved = [
                f"{item['artifact_id']} [{item['status']}]: {item['description']}"
                for item in artifacts if isinstance(item, dict)
                and item.get("status") not in {"complete", "not_applicable"}
                and all(_nonempty(item.get(key)) for key in ("artifact_id", "status", "description"))
            ]
            if completeness.get("status") != derived_status or completeness.get("unresolved_items") != derived_unresolved:
                errors.append(_error("PUBLICATION_COMPLETENESS_DERIVATION_MISMATCH", "Completeness status and unresolved_items must be deterministically derived from artifact statuses/descriptions.", "publication_package_manifest"))
    return errors


def _validate_publication_integrity_report(payload: Any) -> list[dict[str, str]]:
    required = ("valid", "package_dir", "artifact_count", "checked_file_count",
                "errors", "artifact_checks", "completeness")
    if not isinstance(payload, dict) or any(key not in payload for key in required):
        return [_error("PUBLICATION_INTEGRITY_REPORT_INVALID", "Integrity report must contain the complete package audit result.", "publication_integrity_report")]
    errors: list[dict[str, str]] = []
    if payload.get("valid") is not True or not isinstance(payload.get("errors"), list) or payload["errors"]:
        errors.append(_error("PUBLICATION_INTEGRITY_AUDIT_FAILED", "Integrity report must report valid=true with an empty errors array.", "publication_integrity_report"))
    for key in ("artifact_count", "checked_file_count"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < (1 if key == "artifact_count" else 2):
            errors.append(_error("PUBLICATION_INTEGRITY_COUNT_INVALID", f"{key} must be a positive artifact count or at least two checked root/package files.", "publication_integrity_report"))
    if not isinstance(payload.get("artifact_checks"), list):
        errors.append(_error("PUBLICATION_INTEGRITY_CHECKS_INVALID", "artifact_checks must be an array.", "publication_integrity_report"))
    if not isinstance(payload.get("completeness"), dict):
        errors.append(_error("PUBLICATION_INTEGRITY_COMPLETENESS_MISSING", "Audit report must include manifest completeness.", "publication_integrity_report"))
    return errors


def validate_stage_payload(artifact_type: str, payload: Any, *, run_id: str, project_id: str,
                           study_ids: set[str], source_snapshot: list[dict[str, Any]] | None = None,
                           canonical_sha256: str | None = None,
                           eligible_study_ids: set[str] | None = None,
                           selected_source_ids: set[str] | None = None) -> list[dict[str, str]]:
    """Validate one typed evidence payload using fixed V1.0 implementation rules."""
    sources = source_snapshot or []
    if artifact_type == "source_selection_manifest":
        return _validate_source_selection(payload, sources, study_ids)
    if artifact_type == "source_inventory":
        return _validate_source_inventory(payload, sources, selected_source_ids)
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
    if artifact_type == "reconciliation_decisions":
        return []
    if artifact_type == "modeling_task":
        return _validate_modeling_task(payload)
    if artifact_type == "cohort_report":
        return _validate_cohort_report(payload)
    if artifact_type == "modeling_cohort_manifest":
        return _validate_cohort_manifest(payload)
    if artifact_type == "modeling_cohort_csv":
        return []
    if artifact_type == "split_manifest":
        return _validate_split_manifest(payload, eligible_study_ids)
    if artifact_type == "model_report":
        return _validate_model_report(payload)
    if artifact_type == "model_artifact":
        return _validate_model_artifact(payload)
    if artifact_type == "modeling_run_manifest":
        return _validate_model_manifest(payload)
    if artifact_type == "reproducibility_evaluation":
        return _validate_reproducibility_evaluation(payload)
    if artifact_type == "reproducibility_evaluation_manifest":
        return _validate_reproducibility_manifest(payload)
    if artifact_type == "publication_package_manifest":
        return _validate_publication_manifest(payload, run_id, project_id)
    if artifact_type == "publication_integrity_report":
        return _validate_publication_integrity_report(payload)
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
    if not isinstance(evidence, list):
        return [_error("STAGE_EVIDENCE_LIST_INVALID", f"Evidence for {stage_id} must be an array.")]
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(_error("STAGE_EVIDENCE_ITEM_INVALID", f"Evidence item {index} in {stage_id} must be an object."))
            continue
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

    selection_item = by_type.get("source_selection_manifest")
    selected_source_ids = None
    if isinstance(selection_item, dict) and isinstance(selection_item.get("payload"), dict):
        rows = selection_item["payload"].get("selected_sources", [])
        if isinstance(rows, list):
            selected_source_ids = {
                row.get("source_id") for row in rows
                if isinstance(row, dict) and _nonempty(row.get("source_id"))
            }
    for artifact_type, item in by_type.items():
        if artifact_type in {"mapping_plan", "reconciliation_decisions"}:
            continue
        artifact_source_snapshot = source_snapshot
        if artifact_type == "extraction_review_record":
            selection_item = all_payloads.get("source_selection_manifest")
            selection_payload = selection_item.get("payload") if isinstance(selection_item, dict) else None
            selected_rows = selection_payload.get("selected_sources") if isinstance(selection_payload, dict) else None
            if not isinstance(selected_rows, list):
                errors.append(_error("EXTRACTION_SELECTION_MANIFEST_MISSING", "Extraction review PASS requires the preceding accepted source_selection_manifest.", artifact_type))
                artifact_source_snapshot = []
            else:
                selected_ids = {
                    row.get("source_id") for row in selected_rows
                    if isinstance(row, dict) and _nonempty(row.get("source_id"))
                }
                artifact_source_snapshot = [
                    row for row in source_snapshot
                    if isinstance(row, dict) and row.get("source_id") in selected_ids
                ]
                if len(artifact_source_snapshot) != len(selected_ids):
                    errors.append(_error("EXTRACTION_SELECTED_SOURCE_SET_INVALID", "The accepted source selection does not resolve exactly to the Run source snapshot.", artifact_type))
        errors.extend(validate_stage_payload(
            artifact_type, item["payload"], run_id=run_id, project_id=project_id,
            study_ids=study_ids, source_snapshot=artifact_source_snapshot,
            canonical_sha256=canonical_sha, eligible_study_ids=eligible_ids,
            selected_source_ids=selected_source_ids,
        ))

    if stage_id == "semantic_mapping" and "mapping_plan" in by_type:
        inventory = all_payloads.get("source_inventory")
        errors.extend(_validate_mapping_plan(by_type["mapping_plan"]["payload"], inventory))
    if stage_id == "canonical_reconciliation" and "canonical_bundle" in by_type:
        bundle_item = by_type["canonical_bundle"]
        bundle = bundle_item["payload"]
        canonical_studies = {
            row.get("study_id") for row in bundle.get("studies", [])
            if isinstance(row, dict) and _nonempty(row.get("study_id"))
        } if isinstance(bundle, dict) else set()
        if canonical_studies != study_ids:
            errors.append(_error("CANONICAL_STUDY_SET_MISMATCH", "Canonical Study IDs must exactly match source_snapshot.study_ids.", "canonical_bundle"))
        if isinstance(bundle, dict):
            if bundle.get("project_id") != project_id:
                errors.append(_error("CANONICAL_PROJECT_ID_MISMATCH", "canonical_bundle.project_id must match the Run project_id.", "canonical_bundle"))
            mapping = all_payloads.get("mapping_plan")
            inventory = all_payloads.get("source_inventory")
            provenance_value = bundle.get("build_provenance")
            provenance = provenance_value if isinstance(provenance_value, dict) else {}
            if mapping and bundle.get("mapping_version") != mapping["payload"].get("mapping_version"):
                errors.append(_error("CANONICAL_MAPPING_VERSION_MISMATCH", "canonical_bundle.mapping_version must match the approved mapping_plan.", "canonical_bundle"))
            if mapping and provenance.get("mapping_plan_sha256") != mapping.get("sha256"):
                errors.append(_error("CANONICAL_MAPPING_PLAN_HASH_MISMATCH", "canonical_bundle.build_provenance.mapping_plan_sha256 must bind the accepted mapping_plan.", "canonical_bundle"))
            if inventory and provenance.get("source_inventory_sha256") != inventory.get("sha256"):
                errors.append(_error("CANONICAL_SOURCE_INVENTORY_HASH_MISMATCH", "canonical_bundle.build_provenance.source_inventory_sha256 must bind the accepted source_inventory.", "canonical_bundle"))
            selected_hashes = {item.get("sha256") for item in source_snapshot if isinstance(item, dict)}
            for index, item in enumerate(bundle.get("evidence", [])):
                locator = item.get("source_locator") if isinstance(item, dict) else None
                if isinstance(locator, dict) and locator.get("source_sha256") not in selected_hashes:
                    errors.append(_error("CANONICAL_EVIDENCE_SOURCE_HASH_UNKNOWN", f"Evidence item {index} does not cite a selected source snapshot hash.", "canonical_bundle"))

    if stage_id == "canonical_reconciliation" and all(
        kind in by_type for kind in ("canonical_bundle", "reconciliation_report", "reconciliation_decisions")
    ):
        from dor.reconciliation import validate_reconciliation_decisions
        bundle_item = by_type["canonical_bundle"]
        report_item = by_type["reconciliation_report"]
        decision_item = by_type["reconciliation_decisions"]
        try:
            decision_report = validate_reconciliation_decisions(
                decision_item["payload"], report_item["payload"], bundle_item["payload"],
                report_item["sha256"], bundle_item["sha256"],
            )
            for error in decision_report.get("errors", []):
                errors.append(_error("RECONCILIATION_DECISIONS_INVALID", error.get("message", error.get("code", "Invalid reconciliation decision.")), "reconciliation_decisions"))
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            errors.append(_error("RECONCILIATION_DECISIONS_INPUT_INVALID", f"Malformed reconciliation issue/decision structure was rejected without acceptance: {exc}", "reconciliation_decisions"))
        report_payload, decision_payload = report_item["payload"], decision_item["payload"]
        issue_by_id = {}
        if isinstance(report_payload, dict) and isinstance(report_payload.get("issues"), list):
            for issue in report_payload["issues"]:
                issue_id = issue.get("issue_id") if isinstance(issue, dict) else None
                if _nonempty(issue_id):
                    issue_by_id[issue_id] = issue
        decision_by_id = {}
        if isinstance(decision_payload, dict) and isinstance(decision_payload.get("decisions"), list):
            for decision in decision_payload["decisions"]:
                issue_id = decision.get("issue_id") if isinstance(decision, dict) else None
                if _nonempty(issue_id):
                    decision_by_id[issue_id] = decision
        for issue_id, issue in issue_by_id.items():
            if issue.get("severity") not in {"CRITICAL", "REVIEW_REQUIRED"}:
                continue
            decision = decision_by_id.get(issue_id)
            if decision is None or decision.get("decision") == "REMAINS_UNRESOLVED":
                errors.append(_error("RECONCILIATION_BLOCKING_ISSUE_UNRESOLVED", f"Blocking reconciliation issue {issue_id} requires an explicit human decision before PASS.", "reconciliation_decisions"))

    if stage_id == "cohort_feasibility" and all(
        kind in by_type for kind in ("modeling_task", "cohort_report", "split_manifest",
                                     "modeling_cohort_manifest", "modeling_cohort_csv")
    ):
        task_item = by_type["modeling_task"]
        report_item = by_type["cohort_report"]
        split_item = by_type["split_manifest"]
        manifest_item = by_type["modeling_cohort_manifest"]
        csv_item = by_type["modeling_cohort_csv"]
        task, report = task_item["payload"], report_item["payload"]
        split, cohort_manifest = split_item["payload"], manifest_item["payload"]
        canonical = all_payloads.get("canonical_bundle")
        if isinstance(task, dict) and isinstance(report, dict):
            for field in ("task_id", "target_id", "endpoint_definition"):
                if report.get(field) != task.get(field):
                    errors.append(_error("COHORT_TASK_IDENTITY_MISMATCH", f"cohort_report.{field} must match the exact approved modeling_task.", "cohort_report"))
            if report.get("task_sha256") != task_item.get("sha256"):
                errors.append(_error("COHORT_TASK_HASH_NOT_BOUND", "cohort_report must bind the exact modeling_task evidence hash.", "cohort_report"))
            if canonical and report.get("bundle_sha256") != canonical.get("sha256"):
                errors.append(_error("COHORT_CANONICAL_BUNDLE_HASH_NOT_BOUND", "cohort_report must bind the exact canonical_bundle evidence hash.", "cohort_report"))
            if canonical and not set(report.get("eligible_study_ids", [])).issubset(set(
                row.get("study_id") for row in canonical["payload"].get("studies", [])
                if isinstance(row, dict) and _nonempty(row.get("study_id"))
            )):
                errors.append(_error("COHORT_STUDY_NOT_IN_CANONICAL_BUNDLE", "Cohort eligible_study_ids must be a subset of canonical Study IDs.", "cohort_report"))
        if isinstance(task, dict) and isinstance(split, dict):
            if split.get("task_id") != task.get("task_id"):
                errors.append(_error("COHORT_SPLIT_TASK_MISMATCH", "split_manifest.task_id must match modeling_task.task_id.", "split_manifest"))
            task_split = task.get("split") if isinstance(task.get("split"), dict) else {}
            if task_split.get("strategy") != split.get("strategy"):
                errors.append(_error("COHORT_SPLIT_STRATEGY_MISMATCH", "split_manifest strategy must match the approved modeling_task strategy.", "split_manifest"))
            if task_split.get("strategy") == "EXPLICIT_STUDIES":
                explicit_ids = set(task_split.get("validation_study_ids", [])) | set(task_split.get("test_study_ids", []))
                eligible_ids = set(report.get("eligible_study_ids", [])) if isinstance(report, dict) else set()
                if not explicit_ids.issubset(eligible_ids):
                    errors.append(_error("COHORT_TASK_STUDY_NOT_ELIGIBLE", "Explicit validation/test Study IDs must be contained in the eligible Cohort Study set.", "modeling_task"))
                expected_map = {
                    sid: ("test" if sid in task_split.get("test_study_ids", []) else
                          "validation" if sid in task_split.get("validation_study_ids", []) else "train")
                    for sid in report.get("eligible_study_ids", [])
                } if isinstance(report, dict) else {}
                if expected_map != split.get("study_to_split"):
                    errors.append(_error("COHORT_EXPLICIT_SPLIT_TASK_MISMATCH", "split_manifest Study assignments must be derived exactly from modeling_task explicit validation/test Study IDs.", "split_manifest"))
            elif task_split.get("strategy") == "GROUPED_HOLDOUT":
                if split.get("seed", 42) != task_split.get("seed", 42):
                    errors.append(_error("COHORT_SPLIT_SEED_MISMATCH", "split_manifest seed must match the approved modeling_task seed.", "split_manifest"))
        if isinstance(cohort_manifest, dict) and isinstance(report, dict) and isinstance(split, dict):
            if (cohort_manifest.get("task_id") != task.get("task_id")
                    or cohort_manifest.get("task_sha256") != task_item.get("sha256")
                    or cohort_manifest.get("bundle_sha256") != (canonical.get("sha256") if canonical else None)):
                errors.append(_error("COHORT_MANIFEST_INPUT_BINDING_MISMATCH", "modeling_cohort_manifest must bind the exact task and canonical bundle hashes.", "modeling_cohort_manifest"))
            hashes = cohort_manifest.get("artifact_sha256", {})
            if not isinstance(hashes, dict):
                hashes = {}
            if hashes.get("cohort_report.json") != report_item.get("sha256"):
                errors.append(_error("COHORT_MANIFEST_REPORT_HASH_MISMATCH", "modeling_cohort_manifest must bind the exact cohort_report hash.", "modeling_cohort_manifest"))
            if hashes.get("split_manifest.json") != split_item.get("sha256"):
                errors.append(_error("COHORT_MANIFEST_SPLIT_HASH_MISMATCH", "modeling_cohort_manifest must bind the exact split_manifest hash.", "modeling_cohort_manifest"))
            if hashes.get("modeling_cohort.csv") != csv_item.get("sha256"):
                errors.append(_error("COHORT_MANIFEST_CSV_HASH_MISMATCH", "modeling_cohort_manifest must bind the exact modeling_cohort.csv hash.", "modeling_cohort_manifest"))
            if (cohort_manifest.get("eligible_study_count") != report.get("eligible_study_count")
                    or cohort_manifest.get("eligible_observation_count") != report.get("eligible_observation_count")):
                errors.append(_error("COHORT_MANIFEST_COUNTS_MISMATCH", "Cohort manifest counts must equal cohort_report counts.", "modeling_cohort_manifest"))
        if isinstance(report, dict) and isinstance(split, dict):
            ids = report.get("eligible_study_ids", [])
            if isinstance(ids, list) and set(split.get("study_to_split", {})) != set(ids):
                errors.append(_error("COHORT_SPLIT_STUDY_SET_MISMATCH", "split_manifest Study IDs must exactly match cohort_report.eligible_study_ids.", "split_manifest"))
    if stage_id == "publication_handoff" and all(
        kind in by_type for kind in ("publication_package_manifest", "publication_integrity_report")
    ):
        from pathlib import Path
        from dor.publication import audit_publication_package_files
        manifest_item = by_type["publication_package_manifest"]
        integrity_item = by_type["publication_integrity_report"]
        manifest_payload = manifest_item.get("payload")
        selection_item = all_payloads.get("source_selection_manifest")
        selection_payload = selection_item.get("payload") if isinstance(selection_item, dict) else None
        selected_rows = selection_payload.get("selected_sources") if isinstance(selection_payload, dict) else None
        expected_source_hashes: dict[str, str] = {}
        if not isinstance(selected_rows, list):
            errors.append(_error("PUBLICATION_SOURCE_SELECTION_MISSING", "Publication handoff requires the preceding accepted source-selection manifest.", "publication_package_manifest"))
        else:
            for row in selected_rows:
                if not isinstance(row, dict) or not _nonempty(row.get("source_id")) or not _sha256(row.get("sha256")):
                    errors.append(_error("PUBLICATION_SELECTED_SOURCE_BINDING_INVALID", "Selected source rows must expose exact source IDs and SHA-256 values.", "publication_package_manifest"))
                    continue
                source_id = row["source_id"]
                if source_id in expected_source_hashes:
                    errors.append(_error("PUBLICATION_SELECTED_SOURCE_DUPLICATE", f"Duplicate selected source ID in publication provenance: {source_id}.", "publication_package_manifest"))
                expected_source_hashes[source_id] = row["sha256"]
            if isinstance(manifest_payload, dict) and manifest_payload.get("source_hashes") != expected_source_hashes:
                errors.append(_error("PUBLICATION_SOURCE_HASHES_NOT_BOUND", "Publication package source_hashes must exactly equal the IDs and hashes of the accepted selected sources; labels or stale/unselected hashes are not accepted.", "publication_package_manifest"))
        manifest_path = Path(str(manifest_item.get("path", ""))).expanduser().resolve(strict=False)
        stored_audit = integrity_item.get("payload")
        if manifest_path.name != "package_manifest.json":
            errors.append(_error("PUBLICATION_MANIFEST_PATH_INVALID", "publication_package_manifest evidence path must name package_manifest.json.", "publication_package_manifest"))
        else:
            try:
                actual_audit = audit_publication_package_files(manifest_path.parent)
                if actual_audit.get("valid") is not True:
                    errors.append(_error("PUBLICATION_PACKAGE_ACTUAL_AUDIT_FAILED", "Recomputed audit of the exact publication package found missing, extra, unsafe, or hash-mismatched files.", "publication_package_manifest"))
                for field in ("valid", "package_dir", "artifact_count", "checked_file_count",
                              "errors", "artifact_checks", "completeness"):
                    if not isinstance(stored_audit, dict) or stored_audit.get(field) != actual_audit.get(field):
                        errors.append(_error("PUBLICATION_AUDIT_REPORT_STALE_OR_INCONSISTENT", f"Stored publication_integrity_report.{field} does not match a fresh audit of the Run-bound package.", "publication_integrity_report"))
            except (OSError, ValueError, TypeError) as exc:
                errors.append(_error("PUBLICATION_PACKAGE_AUDIT_UNREADABLE", f"Could not independently audit publication package: {exc}", "publication_package_manifest"))

    if stage_id == "modeling_validation" and all(kind in by_type for kind in (
        "model_report", "model_artifact", "modeling_run_manifest",
        "reproducibility_evaluation", "reproducibility_evaluation_manifest"
    )):
        report_item = by_type["model_report"]
        artifact_item = by_type["model_artifact"]
        model_item = by_type["modeling_run_manifest"]
        evaluation_item = by_type["reproducibility_evaluation"]
        evaluation_manifest_item = by_type["reproducibility_evaluation_manifest"]
        report = report_item["payload"]
        artifact = artifact_item["payload"]
        model_manifest = model_item["payload"]
        evaluation = evaluation_item["payload"]
        evaluation_manifest = evaluation_manifest_item["payload"]
        if isinstance(report, dict) and isinstance(artifact, dict) and isinstance(model_manifest, dict):
            if (report.get("task_id") != model_manifest.get("task_id")
                    or report.get("selected_model") != model_manifest.get("selected_model")
                    or report.get("task_id") != artifact.get("task_id")
                    or report.get("selected_candidate_id") != artifact.get("selected_candidate_id")
                    or report.get("target_id") != artifact.get("target_id")
                    or report.get("endpoint_definition") != artifact.get("endpoint_definition")):
                errors.append(_error("MODEL_REPORT_ARTIFACT_IDENTITY_MISMATCH", "model_report, model_artifact, and modeling_run_manifest task/model selections must match.", "model_report"))
            if report.get("selected_model") != artifact.get("model_type"):
                errors.append(_error("MODEL_TYPE_SELECTION_MISMATCH", "model_report.selected_model must equal the serialized model_artifact.model_type.", "model_artifact"))
            if report.get("primary_selection_metric") != artifact.get("selection_metric"):
                errors.append(_error("MODEL_SELECTION_METRIC_MISMATCH", "model_report.primary_selection_metric must equal model_artifact.selection_metric.", "model_artifact"))
            task_item = all_payloads.get("modeling_task")
            task_payload = task_item.get("payload") if isinstance(task_item, dict) else None
            if not isinstance(task_payload, dict):
                errors.append(_error("MODEL_TASK_EVIDENCE_MISSING", "Model validation must bind to the exact preceding modeling_task evidence.", "modeling_task"))
            else:
                artifact_task_fields = ("task_id", "target_id", "endpoint_definition", "outcome_value_field", "outcome_unit")
                if any(artifact.get(field) != task_payload.get(field) for field in artifact_task_fields):
                    errors.append(_error("MODEL_ARTIFACT_TASK_BINDING_MISMATCH", "Serialized model task/target/endpoint/outcome field/unit must exactly match the accepted modeling_task.", "model_artifact"))
                if artifact.get("feature_bindings") != task_payload.get("feature_bindings"):
                    errors.append(_error("MODEL_ARTIFACT_FEATURE_BINDING_MISMATCH", "Serialized model feature_bindings must exactly match the accepted modeling_task.", "model_artifact"))
                report_task_fields = ("task_id", "target_id", "endpoint_definition", "outcome_type", "outcome_value_field", "outcome_unit")
                if any(report.get(field) != task_payload.get(field) for field in report_task_fields):
                    errors.append(_error("MODEL_REPORT_TASK_BINDING_MISMATCH", "Model report target/endpoint/outcome definition must exactly match the accepted modeling_task.", "model_report"))
            outputs = model_manifest.get("output_hashes", {})
            if outputs.get("model_report.json") != report_item.get("sha256"):
                errors.append(_error("MODEL_REPORT_HASH_NOT_BOUND", "modeling_run_manifest.output_hashes.model_report.json must equal the cited model_report hash.", "modeling_run_manifest"))
            if outputs.get("model_artifact.json") != artifact_item.get("sha256"):
                errors.append(_error("MODEL_ARTIFACT_HASH_NOT_BOUND", "modeling_run_manifest.output_hashes.model_artifact.json must equal the cited model_artifact hash.", "modeling_run_manifest"))
            split_item = all_payloads.get("split_manifest")
            cohort_item = all_payloads.get("cohort_report")
            if split_item and isinstance(split_item.get("payload"), dict):
                split_payload = split_item["payload"]
                split_map = split_payload.get("study_to_split", {})
                expected_groups = {
                    key: sorted(sid for sid, partition in split_map.items() if partition == key)
                    for key in ("train", "validation", "test")
                }
                actual_groups = model_manifest.get("study_ids_by_split", {})
                actual_groups = {key: sorted(values) for key, values in actual_groups.items()} if isinstance(actual_groups, dict) else {}
                if actual_groups != expected_groups:
                    errors.append(_error("MODEL_SPLIT_MANIFEST_MISMATCH", "Model Study assignments must exactly match the accepted cohort split_manifest.", "modeling_run_manifest"))
                inputs = model_manifest.get("input_hashes", {})
                if inputs.get("split_manifest_sha256") != split_item.get("sha256"):
                    errors.append(_error("MODEL_SPLIT_HASH_NOT_BOUND", "modeling_run_manifest must bind the exact accepted split_manifest hash.", "modeling_run_manifest"))
                if cohort_item and inputs.get("cohort_report_sha256") != cohort_item.get("sha256"):
                    errors.append(_error("MODEL_COHORT_REPORT_HASH_NOT_BOUND", "modeling_run_manifest must bind the exact accepted cohort_report hash.", "modeling_run_manifest"))
                cohort_manifest_item = all_payloads.get("modeling_cohort_manifest")
                task_item = all_payloads.get("modeling_task")
                csv_item = all_payloads.get("modeling_cohort_csv")
                if cohort_manifest_item and inputs.get("cohort_manifest_sha256") != cohort_manifest_item.get("sha256"):
                    errors.append(_error("MODEL_COHORT_MANIFEST_HASH_NOT_BOUND", "modeling_run_manifest must bind the exact modeling_cohort_manifest hash.", "modeling_run_manifest"))
                if task_item and inputs.get("task_sha256") != task_item.get("sha256"):
                    errors.append(_error("MODEL_TASK_HASH_NOT_BOUND", "modeling_run_manifest must bind the exact approved modeling_task hash.", "modeling_run_manifest"))
                if csv_item and inputs.get("cohort_sha256") != csv_item.get("sha256"):
                    errors.append(_error("MODEL_COHORT_CSV_HASH_NOT_BOUND", "modeling_run_manifest must bind the exact modeling_cohort.csv hash.", "modeling_run_manifest"))
                if isinstance(artifact, dict):
                    expected_training_studies = sorted(expected_groups["train"] + expected_groups["validation"])
                    if sorted(artifact.get("training_study_ids", [])) != expected_training_studies:
                        errors.append(_error("MODEL_ARTIFACT_TRAINING_STUDIES_MISMATCH", "Serialized model training_study_ids must equal train plus validation Studies in the accepted split.", "model_artifact"))
                    observations = split_payload.get("observation_ids_by_split", {})
                    expected_training_observations = set(observations.get("train", [])) | set(observations.get("validation", []))
                    expected_test_observations = set(observations.get("test", []))
                    if set(artifact.get("training_observation_ids", [])) != expected_training_observations:
                        errors.append(_error("MODEL_ARTIFACT_TRAINING_OBSERVATIONS_MISMATCH", "Serialized model training observation IDs must equal train plus validation observations.", "model_artifact"))
                    if set(artifact.get("test_observation_ids", [])) != expected_test_observations:
                        errors.append(_error("MODEL_ARTIFACT_TEST_OBSERVATIONS_MISMATCH", "Serialized model test observation IDs must equal held-out test observations.", "model_artifact"))
            if isinstance(evaluation, dict) and isinstance(evaluation_manifest, dict):
                if (evaluation.get("task_id") != evaluation_manifest.get("task_id")
                        or evaluation.get("task_id") != report.get("task_id")
                        or evaluation.get("target_id") != report.get("target_id")
                        or evaluation.get("endpoint_definition") != report.get("endpoint_definition")
                        or evaluation.get("fold_count") != evaluation_manifest.get("fold_count")
                        or evaluation.get("study_count") != len(evaluation_manifest.get("study_ids", []))):
                    errors.append(_error("REPRODUCIBILITY_REPORT_MANIFEST_MISMATCH", "Nested evaluation report task/endpoint/fold/Study counts must match model_report and its manifest.", "reproducibility_evaluation"))
                if evaluation_manifest.get("output_hashes", {}).get("reproducibility_evaluation.json") != evaluation_item.get("sha256"):
                    errors.append(_error("REPRODUCIBILITY_REPORT_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact evaluation report hash.", "reproducibility_evaluation_manifest"))
                if cohort_item and isinstance(cohort_item.get("payload"), dict):
                    eligible_ids = set(cohort_item["payload"].get("eligible_study_ids", []))
                    manifest_ids = set(evaluation_manifest.get("study_ids", []))
                    held_out_ids = {
                        sid for fold in evaluation.get("folds", []) if isinstance(fold, dict)
                        for sid in fold.get("test_study_ids", []) if isinstance(sid, str)
                    }
                    if manifest_ids != eligible_ids or held_out_ids != eligible_ids:
                        errors.append(_error("REPRODUCIBILITY_STUDY_SET_MISMATCH", "Nested evaluation manifest and outer held-out folds must cover exactly cohort_report.eligible_study_ids.", "reproducibility_evaluation_manifest"))
                    eval_inputs = evaluation_manifest.get("input_hashes", {})
                    if split_item and eval_inputs.get("split_manifest_sha256") != split_item.get("sha256"):
                        errors.append(_error("REPRODUCIBILITY_SPLIT_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact accepted split_manifest hash.", "reproducibility_evaluation_manifest"))
                    if eval_inputs.get("cohort_report_sha256") != cohort_item.get("sha256"):
                        errors.append(_error("REPRODUCIBILITY_COHORT_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact accepted cohort_report hash.", "reproducibility_evaluation_manifest"))
                    cohort_manifest_item = all_payloads.get("modeling_cohort_manifest")
                    task_item = all_payloads.get("modeling_task")
                    csv_item = all_payloads.get("modeling_cohort_csv")
                    if cohort_manifest_item and eval_inputs.get("cohort_manifest_sha256") != cohort_manifest_item.get("sha256"):
                        errors.append(_error("REPRODUCIBILITY_COHORT_MANIFEST_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact modeling_cohort_manifest hash.", "reproducibility_evaluation_manifest"))
                    if task_item and eval_inputs.get("task_sha256") != task_item.get("sha256"):
                        errors.append(_error("REPRODUCIBILITY_TASK_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact approved modeling_task hash.", "reproducibility_evaluation_manifest"))
                    if csv_item and eval_inputs.get("cohort_sha256") != csv_item.get("sha256"):
                        errors.append(_error("REPRODUCIBILITY_COHORT_CSV_HASH_NOT_BOUND", "Nested evaluation manifest must bind the exact modeling_cohort.csv hash.", "reproducibility_evaluation_manifest"))
    return errors
