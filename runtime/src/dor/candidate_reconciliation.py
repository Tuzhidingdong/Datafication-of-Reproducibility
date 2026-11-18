"""Pairwise diagnostic reconciliation for provenance-bearing candidate values.

This layer explains candidate disagreements without choosing, averaging, or promoting
candidate values. It is deliberately separate from primary analysis and source-specific
sensitivity scenarios.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from itertools import combinations
from typing import Any

from dor.candidate_mining import _candidate_pair, _nonblank, _record_candidates
from dor.semantic_registry import approved_unit_symbol_lookup, overlay_semantic_registry


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _affine_exact(value: Decimal, scale: Decimal, offset: Decimal) -> Decimal:
    product_exponent = value.as_tuple().exponent + scale.as_tuple().exponent
    product_adjusted = value.adjusted() + scale.adjusted()
    minimum_exponent = min(product_exponent, offset.as_tuple().exponent)
    maximum_adjusted = max(product_adjusted, offset.adjusted())
    precision = max(28, maximum_adjusted - minimum_exponent + 4)
    with localcontext() as context:
        context.prec = precision
        return value * scale + offset


def _parent_semantic_status(record: dict[str, Any]) -> str:
    metadata = record.get("semantic_metadata")
    if not isinstance(metadata, dict):
        return "PARENT_ATTRIBUTE_SEMANTICS_UNREVIEWED_OR_INCOMPLETE_CANDIDATE_QUOTE_SCOPE_UNVERIFIED"
    required = (
        "canonical_concept_id",
        "definition",
        "measurement_basis",
        "measurement_context",
        "derivation_type",
    )
    if metadata.get("review_status") == "APPROVED" and all(
        isinstance(metadata.get(field), str) and metadata[field].strip()
        for field in required
    ):
        return "APPROVED_PARENT_ATTRIBUTE_SEMANTICS_CANDIDATE_QUOTE_SCOPE_UNVERIFIED"
    return "PARENT_ATTRIBUTE_SEMANTICS_UNREVIEWED_OR_INCOMPLETE_CANDIDATE_QUOTE_SCOPE_UNVERIFIED"


def _unit_comparison(
    unit_a: str,
    unit_b: str,
    value_a: Any,
    value_b: Any,
    unit_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parsed_a = _decimal(value_a)
    parsed_b = _decimal(value_b)
    missing_a = not _nonblank(unit_a) or unit_a == "UNSPECIFIED_UNIT"
    missing_b = not _nonblank(unit_b) or unit_b == "UNSPECIFIED_UNIT"
    if missing_a or missing_b:
        return {
            "unit_comparison_status": "UNIT_MISSING_OR_UNSPECIFIED",
            "comparable_unit": None,
            "comparable_value_a": None,
            "comparable_value_b": None,
            "unit_adjusted_comparison_status": "NOT_COMPARABLE_MISSING_UNIT",
        }
    if unit_a == unit_b:
        comparable_status = "NOT_COMPARABLE_NON_NUMERIC_VALUE"
        if parsed_a is not None and parsed_b is not None:
            comparable_status = "NUMERICALLY_EQUAL" if parsed_a == parsed_b else "NUMERICALLY_DIFFERENT"
        return {
            "unit_comparison_status": "EXACT_UNIT_LABEL_MATCH",
            "comparable_unit": unit_a,
            "comparable_value_a": _decimal_text(parsed_a),
            "comparable_value_b": _decimal_text(parsed_b),
            "unit_adjusted_comparison_status": comparable_status,
        }

    definition_a = unit_lookup.get(unit_a)
    definition_b = unit_lookup.get(unit_b)
    if definition_a is None or definition_b is None:
        return {
            "unit_comparison_status": "UNIT_LABELS_DIFFER_UNRESOLVED",
            "comparable_unit": None,
            "comparable_value_a": None,
            "comparable_value_b": None,
            "unit_adjusted_comparison_status": "NOT_COMPARABLE_UNRESOLVED_UNIT_LABELS",
        }
    if definition_a["dimension_id"] != definition_b["dimension_id"]:
        return {
            "unit_comparison_status": "APPROVED_INCOMPATIBLE_DIMENSIONS",
            "comparable_unit": None,
            "comparable_value_a": None,
            "comparable_value_b": None,
            "unit_adjusted_comparison_status": "NOT_COMPARABLE_INCOMPATIBLE_DIMENSIONS",
        }

    canonical_a = None
    canonical_b = None
    if parsed_a is not None:
        canonical_a = _affine_exact(
            parsed_a,
            Decimal(definition_a["scale_to_canonical"]),
            Decimal(definition_a["offset_to_canonical"]),
        )
    if parsed_b is not None:
        canonical_b = _affine_exact(
            parsed_b,
            Decimal(definition_b["scale_to_canonical"]),
            Decimal(definition_b["offset_to_canonical"]),
        )
    comparable_status = "NOT_COMPARABLE_NON_NUMERIC_VALUE"
    if canonical_a is not None and canonical_b is not None:
        comparable_status = "NUMERICALLY_EQUAL" if canonical_a == canonical_b else "NUMERICALLY_DIFFERENT"
    return {
        "unit_comparison_status": "APPROVED_SAME_DIMENSION_CONVERSION",
        "comparable_unit": definition_a["canonical_unit"],
        "comparable_value_a": _decimal_text(canonical_a),
        "comparable_value_b": _decimal_text(canonical_b),
        "unit_adjusted_comparison_status": comparable_status,
    }


def _value_comparison(value_a: Any, value_b: Any) -> str:
    present_a = _nonblank(value_a)
    present_b = _nonblank(value_b)
    if not present_a and not present_b:
        return "BOTH_VALUES_MISSING"
    if not present_a or not present_b:
        return "ONE_VALUE_MISSING"
    number_a = _decimal(value_a)
    number_b = _decimal(value_b)
    if number_a is not None and number_b is not None:
        return "NUMERICALLY_EQUAL" if number_a == number_b else "NUMERICALLY_DIFFERENT"
    return "NON_NUMERIC_EXACT_MATCH" if _json_key(value_a) == _json_key(value_b) else "NON_NUMERIC_VALUES_DIFFER"


def _overall_status(value_status: str, unit_status: str, adjusted_status: str) -> str:
    if unit_status == "APPROVED_INCOMPATIBLE_DIMENSIONS":
        return "INCOMPATIBLE_UNIT_DIMENSIONS_REVIEW"
    if unit_status == "UNIT_LABELS_DIFFER_UNRESOLVED":
        return "UNIT_EQUIVALENCE_UNRESOLVED"
    if unit_status == "UNIT_MISSING_OR_UNSPECIFIED":
        return "UNIT_MISSING_REVIEW"
    if value_status in {"BOTH_VALUES_MISSING", "ONE_VALUE_MISSING"}:
        return "VALUE_EVIDENCE_INSUFFICIENT"
    if value_status.startswith("NON_NUMERIC"):
        return (
            "NON_NUMERIC_EXACT_MATCH_REQUIRES_SEMANTIC_REVIEW"
            if value_status == "NON_NUMERIC_EXACT_MATCH"
            else "NON_NUMERIC_VALUE_DIFFERENCE_REQUIRES_SEMANTIC_REVIEW"
        )
    if adjusted_status == "NUMERICALLY_EQUAL":
        return "NUMERICALLY_EQUIVALENT_WITHIN_DECLARED_UNIT_BASIS"
    if adjusted_status == "NUMERICALLY_DIFFERENT":
        return "NUMERICALLY_DIFFERENT_WITHIN_DECLARED_UNIT_BASIS"
    return "VALUE_COMPARISON_INSUFFICIENT"


def build_candidate_pairwise_reconciliation(
    bundle: dict[str, Any],
    *,
    semantic_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare candidate pairs only when attached to the same canonical parent record."""
    semantic_bundle = bundle
    if semantic_registry is not None:
        semantic_bundle, _ = overlay_semantic_registry(bundle, semantic_registry)
    semantic_records = {
        ("OBSERVATION", row.get("observation_id")): row
        for row in semantic_bundle.get("observations", [])
    }
    semantic_records.update({
        ("CONDITION", row.get("condition_id")): row
        for row in semantic_bundle.get("conditions", [])
    })

    unit_lookup = approved_unit_symbol_lookup(semantic_registry)
    experiments = {row["experiment_id"]: row for row in bundle.get("experiments", [])}
    systems = {row["system_id"]: row for row in bundle.get("systems", [])}
    condition_experiments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for experiment in experiments.values():
        for condition_id in experiment.get("condition_ids", []):
            condition_experiments[condition_id].append(experiment)

    pairwise_rows: list[dict[str, Any]] = []
    entity_sets = (
        ("OBSERVATION", bundle.get("observations", []), "observation_id"),
        ("CONDITION", bundle.get("conditions", []), "condition_id"),
    )
    for entity_type, records, id_field in entity_sets:
        for record in records:
            record_id = record.get(id_field)
            candidates = _record_candidates(record)
            if len(candidates) < 2:
                continue
            if entity_type == "OBSERVATION":
                experiment = experiments.get(record.get("experiment_id"), {})
                related_experiments = [experiment] if experiment else []
                feature_id = str(record.get("target_id") or "UNSPECIFIED_TARGET")
                endpoint = record.get("endpoint_definition")
                timepoint = record.get("timepoint")
            else:
                related_experiments = condition_experiments.get(record_id, [])
                feature_id = str(record.get("condition_type") or "UNSPECIFIED_CONDITION")
                endpoint = None
                timepoint = None

            study_ids = sorted({
                str(item.get("study_id"))
                for item in related_experiments if item.get("study_id")
            })
            system_ids = sorted({
                str(item.get("system_id"))
                for item in related_experiments if item.get("system_id")
            } | {
                str(value) for value in record.get("system_ids", [])
                if entity_type == "CONDITION"
            })
            if entity_type == "CONDITION" and not study_ids:
                for system_id in system_ids:
                    system = systems.get(system_id, {})
                    study_ids.extend(str(value) for value in system.get("study_ids", []) if value)
                study_ids = sorted(set(study_ids))
            experiment_ids = sorted({
                str(item.get("experiment_id"))
                for item in related_experiments if item.get("experiment_id")
            })
            semantic_record = semantic_records.get((entity_type, record_id), record)
            semantic_status = _parent_semantic_status(semantic_record)

            for candidate_a, candidate_b in combinations(candidates, 2):
                value_a, unit_a = _candidate_pair(candidate_a)
                value_b, unit_b = _candidate_pair(candidate_b)
                source_a = str(candidate_a.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE")
                source_b = str(candidate_b.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE")
                value_status = _value_comparison(value_a, value_b)
                unit_result = _unit_comparison(unit_a, unit_b, value_a, value_b, unit_lookup)
                pairwise_rows.append({
                    "entity_type": entity_type,
                    "record_id": record_id,
                    "feature_id": feature_id,
                    "study_ids_json": json.dumps(study_ids, ensure_ascii=False),
                    "system_ids_json": json.dumps(system_ids, ensure_ascii=False),
                    "experiment_ids_json": json.dumps(experiment_ids, ensure_ascii=False),
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "candidate_source_relation": "SAME_SOURCE" if source_a == source_b else "CROSS_SOURCE",
                    "candidate_a_id": candidate_a.get("candidate_id"),
                    "candidate_a_source": source_a,
                    "candidate_a_value": value_a,
                    "candidate_a_unit": unit_a,
                    "candidate_a_quoted_text": candidate_a.get("quoted_text"),
                    "candidate_a_source_metadata_json": json.dumps(
                        candidate_a.get("source_metadata", {}), ensure_ascii=False, sort_keys=True
                    ),
                    "candidate_a_source_locators_json": json.dumps(
                        candidate_a.get("source_locators", []), ensure_ascii=False, sort_keys=True
                    ),
                    "candidate_b_id": candidate_b.get("candidate_id"),
                    "candidate_b_source": source_b,
                    "candidate_b_value": value_b,
                    "candidate_b_unit": unit_b,
                    "candidate_b_quoted_text": candidate_b.get("quoted_text"),
                    "candidate_b_source_metadata_json": json.dumps(
                        candidate_b.get("source_metadata", {}), ensure_ascii=False, sort_keys=True
                    ),
                    "candidate_b_source_locators_json": json.dumps(
                        candidate_b.get("source_locators", []), ensure_ascii=False, sort_keys=True
                    ),
                    "value_comparison_status": value_status,
                    "unit_comparison_status": unit_result["unit_comparison_status"],
                    "comparable_unit": unit_result["comparable_unit"],
                    "comparable_value_a": unit_result["comparable_value_a"],
                    "comparable_value_b": unit_result["comparable_value_b"],
                    "unit_adjusted_comparison_status": unit_result["unit_adjusted_comparison_status"],
                    "parent_semantic_status": semantic_status,
                    "overall_comparison_status": _overall_status(
                        value_status,
                        unit_result["unit_comparison_status"],
                        unit_result["unit_adjusted_comparison_status"],
                    ),
                })

    status_counts = {
        field: dict(sorted(Counter(row[field] for row in pairwise_rows).items()))
        for field in (
            "candidate_source_relation",
            "value_comparison_status",
            "unit_comparison_status",
            "unit_adjusted_comparison_status",
            "parent_semantic_status",
            "overall_comparison_status",
        )
    }
    profile = {
        "pairwise_comparison_count": len(pairwise_rows),
        "same_source_comparison_count": sum(
            row["candidate_source_relation"] == "SAME_SOURCE" for row in pairwise_rows
        ),
        "cross_source_comparison_count": sum(
            row["candidate_source_relation"] == "CROSS_SOURCE" for row in pairwise_rows
        ),
        "unit_conversion_applied_comparison_count": sum(
            row["unit_comparison_status"] == "APPROVED_SAME_DIMENSION_CONVERSION"
            for row in pairwise_rows
        ),
        "status_counts": status_counts,
        "unit_registry": {
            "schema_version": semantic_registry.get("schema_version") if semantic_registry else None,
            "registry_id": semantic_registry.get("registry_id") if semantic_registry else None,
            "approved_unit_definition_count": sum(
                1 for row in (semantic_registry or {}).get("unit_definitions", [])
                if row.get("review_status") == "APPROVED"
            ),
            "approved_unit_symbol_count": len(unit_lookup),
        },
        "interpretation_boundary": [
            "Only candidates attached to the same Canonical Observation or Condition are compared pairwise.",
            "Numeric equality uses exact Decimal comparison; no rounding, tolerance, locale parsing, or imputation is applied.",
            "Different unit labels are converted only when both exact symbols occur in an approved Semantic Registry v1.1 definition for the same declared dimension.",
            "Approved unit conversions are diagnostic only; they do not alter primary values or candidate-source sensitivity scenarios.",
            "Parent attribute semantics do not establish that two candidate quotations refer to the same measurement definition or context; candidate quote scope remains unverified.",
            "No candidate is selected, averaged, rejected, or promoted by this diagnostic layer.",
        ],
    }
    return {"profile": profile, "pairwise_rows": pairwise_rows}
