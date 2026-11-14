"""Study-level condition/outcome association screening.

This module links deterministic condition candidates to numeric observation outcomes.
It deliberately performs descriptive, not inferential, comparisons: Study (DOI) is
the aggregation unit, exact feature IDs and unit strings define endpoint strata,
and unmapped feature semantics remain explicitly unresolved.
"""
from __future__ import annotations

import csv
import itertools
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

_EXCLUDED_ORIGINS = {"RECONCILIATION_CSV_ONLY", "RECONCILIATION_CSV_AMBIGUOUS"}
_EXCLUDED_CONDITION_TYPES = {
    "system_domain", "chemical_formula_component", "electrolyte_component",
}
_MIN_CONFIDENCE = {"HIGH", "MEDIUM"}
_REDUNDANT_COMBINATION_TYPE_PAIRS = {
    frozenset({"cell_configuration", "cell_configuration_class"}),
}
_MAX_CONTRAST_LEVELS = 25


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _mad(values: list[float]) -> float | None:
    centre = _median(values)
    return _median([abs(value - centre) for value in values]) if centre is not None else None


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _study(record: dict[str, Any]) -> str | None:
    doi = _text(record.get("doi")).casefold()
    return "DOI:" + doi if doi else None


def _condition_dimension(candidate: dict[str, Any]) -> tuple[str, str]:
    """Return a comparison dimension and level without inferring hidden chemistry."""
    condition_type = _text(candidate.get("condition_type"))
    normalized = _text(candidate.get("normalized_value")) or _text(candidate.get("raw_value"))
    numeric_unit = _text(candidate.get("numeric_unit"))
    unit_suffix = f"[{numeric_unit}]" if numeric_unit else ""
    if condition_type == "salt_concentration" and "|" in normalized:
        salt, level = normalized.split("|", 1)
        salt = salt.strip()
        return f"salt_concentration[{salt}]{unit_suffix}", level.strip()
    if condition_type == "percentage_modifier":
        match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?\s*%)\s*(.*?)\s*$", normalized)
        if match and match.group(2):
            return f"percentage_modifier[{match.group(2).casefold()}]{unit_suffix}", normalized
    return f"{condition_type}{unit_suffix}", normalized


def _source_priority(source_field: str) -> int:
    if source_field == "measurement_conditions":
        return 0
    if ".quote" in source_field or ".cell_value" in source_field:
        return 1
    if source_field == "target_system":
        return 2
    return 3


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple, set)) else value
                for key, value in row.items()
            })


def build_condition_performance_analysis(
    observations: list[dict[str, Any]],
    condition_records: list[dict[str, Any]],
    output_dir: Path,
    minimum_studies: int = 3,
) -> dict[str, Any]:
    """Link candidate conditions to agreed numeric outcomes and compare by DOI Study."""
    if minimum_studies < 2:
        raise ValueError("minimum_studies must be >= 2 for condition-performance screening.")

    observation_by_id = {
        _text(item.get("observation_id")): item
        for item in observations if _text(item.get("observation_id"))
    }
    outcome_by_id: dict[str, dict[str, Any]] = {}
    for observation_id, item in observation_by_id.items():
        study_id = _study(item)
        feature_id = _text(item.get("feature_id"))
        unit = _text(item.get("resolved_unit"))
        value = _number(item.get("resolved_value"))
        if (
            study_id
            and feature_id
            and unit
            and value is not None
            and _text(item.get("status")).upper() == "AGREED_MATCH"
            and not bool(item.get("requires_human_review"))
            and _text(item.get("source_origin")).upper() not in _EXCLUDED_ORIGINS
            and _text(item.get("batch_id")) not in {
                "BATCH_20261106_LIMITS_PROBE",
                "BATCH_20261106_SMOKE_NR_94908118",
            }
        ):
            outcome_by_id[observation_id] = {
                "observation_id": observation_id,
                "study_group_id": study_id,
                "paper_id": _text(item.get("paper_id")),
                "doi": _text(item.get("doi")),
                "feature_id": feature_id,
                "outcome_unit": unit,
                "outcome_value": value,
                "target_system": _text(item.get("target_system")) or "NOT_REPORTED",
            }

    # Consolidate repeated extractions of the same condition level on an observation.
    candidates_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    excluded_candidate_count = 0
    unsupported_candidate_count = 0
    for candidate in condition_records:
        observation_id = _text(candidate.get("observation_id"))
        if observation_id not in outcome_by_id:
            continue
        condition_type = _text(candidate.get("condition_type"))
        confidence = _text(candidate.get("confidence")).upper()
        review_status = _text(candidate.get("review_status"))
        if (
            _text(candidate.get("data_eligibility")) == "EXCLUDED_TEST_DATA"
            or condition_type in _EXCLUDED_CONDITION_TYPES
            or confidence not in _MIN_CONFIDENCE
            or review_status == "CANDIDATE_REQUIRES_CONTEXT_REVIEW"
        ):
            excluded_candidate_count += 1
            continue
        dimension, level = _condition_dimension(candidate)
        if not dimension or not level:
            unsupported_candidate_count += 1
            continue
        key = (observation_id, condition_type, dimension, level)
        candidates_by_key[key].append(candidate)

    # More than one value for the same dimension in one observation is ambiguous;
    # preserve it in the records but do not choose one for outcome comparisons.
    levels_by_observation_dimension: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for observation_id, condition_type, dimension, level in candidates_by_key:
        levels_by_observation_dimension[(observation_id, condition_type, dimension)].add(level)
    ambiguous_keys = {
        key for key, levels in levels_by_observation_dimension.items() if len(levels) > 1
    }

    # One link row per observation x dimension x level; source duplicates are collapsed.
    link_rows: list[dict[str, Any]] = []
    links_by_observation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_study_values: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for (observation_id, condition_type, dimension, level), source_candidates in sorted(candidates_by_key.items()):
        if (observation_id, condition_type, dimension) in ambiguous_keys:
            continue
        outcome = outcome_by_id[observation_id]
        preferred = sorted(
            source_candidates,
            key=lambda item: (
                _source_priority(_text(item.get("source_field"))),
                0 if _text(item.get("confidence")).upper() == "HIGH" else 1,
            ),
        )[0]
        source_fields = sorted({_text(item.get("source_field")) for item in source_candidates if _text(item.get("source_field"))})
        methods = sorted({_text(item.get("extraction_method")) for item in source_candidates if _text(item.get("extraction_method"))})
        link = {
            **outcome,
            "condition_type": condition_type,
            "condition_dimension": dimension,
            "condition_level": level,
            "condition_normalized_value": _text(preferred.get("normalized_value")) or _text(preferred.get("raw_value")),
            "condition_numeric_value": preferred.get("numeric_value"),
            "condition_numeric_unit": _text(preferred.get("numeric_unit")),
            "condition_unit_basis": _text(preferred.get("unit_basis")),
            "condition_source_fields": source_fields,
            "condition_extraction_methods": methods,
            "condition_confidence": _text(preferred.get("confidence")),
            "condition_record_match_count": len(source_candidates),
            "condition_record_ids": sorted({
                _text(item.get("condition_record_id"))
                for item in source_candidates if _text(item.get("condition_record_id"))
            }),
        }
        link_rows.append(link)
        links_by_observation[observation_id].append(link)
        key = (
            outcome["feature_id"], outcome["outcome_unit"], condition_type,
            dimension, level, outcome["study_group_id"],
        )
        grouped_study_values[key].append({
            "outcome_value": outcome["outcome_value"],
            "observation_id": observation_id,
            "target_system": outcome["target_system"],
            "condition_numeric_value": _number(preferred.get("numeric_value")),
            "condition_numeric_unit": _text(preferred.get("numeric_unit")),
            "source_fields": source_fields,
        })

    # Feature-level denominators show where condition extraction can support a
    # comparison; a high linkage rate is coverage, not evidence of an effect.
    feature_outcome_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    feature_linked_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    feature_studies: dict[tuple[str, str], set[str]] = defaultdict(set)
    feature_linked_studies: dict[tuple[str, str], set[str]] = defaultdict(set)
    for observation_id, outcome in outcome_by_id.items():
        key = (outcome["feature_id"], outcome["outcome_unit"])
        feature_outcome_ids[key].add(observation_id)
        feature_studies[key].add(outcome["study_group_id"])
    for link in link_rows:
        key = (link["feature_id"], link["outcome_unit"])
        feature_linked_ids[key].add(link["observation_id"])
        feature_linked_studies[key].add(link["study_group_id"])
    feature_coverage_rows: list[dict[str, Any]] = []
    for key in sorted(feature_outcome_ids):
        feature, unit = key
        outcome_count = len(feature_outcome_ids[key])
        linked_count = len(feature_linked_ids[key])
        feature_coverage_rows.append({
            "feature_id": feature,
            "outcome_unit": unit,
            "eligible_numeric_outcome_observation_count": outcome_count,
            "condition_linked_observation_count": linked_count,
            "condition_linkage_coverage_fraction": linked_count / outcome_count if outcome_count else 0.0,
            "doi_study_count": len(feature_studies[key]),
            "condition_linked_doi_study_count": len(feature_linked_studies[key]),
            "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
        })

    # Aggregate technical observations within each DOI first; DOI is the independent
    # support unit used for the across-Study descriptive summaries.
    study_strata_rows: list[dict[str, Any]] = []
    study_lookup: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for key, values in sorted(grouped_study_values.items()):
        feature, unit, condition_type, dimension, level, study_id = key
        outcomes = [item["outcome_value"] for item in values]
        systems = sorted({item["target_system"] for item in values})
        numeric_conditions = sorted({
            item["condition_numeric_value"] for item in values
            if item["condition_numeric_value"] is not None
        })
        numeric_units = sorted({
            item["condition_numeric_unit"] for item in values
            if item["condition_numeric_unit"]
        })
        row = {
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_type": condition_type,
            "condition_dimension": dimension,
            "condition_level": level,
            "study_group_id": study_id,
            "study_observation_count": len(values),
            "study_outcome_median": _median(outcomes),
            "study_outcome_min": min(outcomes),
            "study_outcome_max": max(outcomes),
            "target_system_count": len(systems),
            "target_system_examples": systems[:5],
            "condition_numeric_values": numeric_conditions,
            "condition_numeric_units": numeric_units,
            "observation_ids_sample": sorted({item["observation_id"] for item in values})[:5],
        }
        study_strata_rows.append(row)
        study_lookup[key] = {
            "median": float(_median(outcomes)),
            "systems": set(systems),
            "observation_count": len(values),
        }

    # Build joint condition-combination strata from condition pairs recorded on the
    # same observation. This is joint support and descriptive outcome context, not
    # an interaction effect or evidence of synergy.
    combination_study_values: dict[tuple[str, str, str, str, str, str, str], list[float]] = defaultdict(list)
    combination_study_systems: dict[tuple[str, str, str, str, str, str, str], set[str]] = defaultdict(set)
    combination_study_observation_counts: dict[tuple[str, str, str, str, str, str, str], int] = defaultdict(int)
    redundant_combination_pair_count = 0
    for observation_id, links in links_by_observation.items():
        if len(links) < 2:
            continue
        outcome = outcome_by_id[observation_id]
        unique_dimensions = {
            link["condition_dimension"]: link for link in links
        }
        ordered_links = sorted(unique_dimensions.values(), key=lambda item: item["condition_dimension"])
        for left, right in itertools.combinations(ordered_links, 2):
            if frozenset({left["condition_type"], right["condition_type"]}) in _REDUNDANT_COMBINATION_TYPE_PAIRS:
                redundant_combination_pair_count += 1
                continue
            key = (
                outcome["feature_id"], outcome["outcome_unit"],
                left["condition_dimension"], left["condition_level"],
                right["condition_dimension"], right["condition_level"],
                outcome["study_group_id"],
            )
            combination_study_values[key].append(outcome["outcome_value"])
            combination_study_systems[key].add(outcome["target_system"])
            combination_study_observation_counts[key] += 1

    combination_by_study_rows: list[dict[str, Any]] = []
    combination_by_stratum: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, values in sorted(combination_study_values.items()):
        feature, unit, dimension_a, level_a, dimension_b, level_b, study_id = key
        row = {
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_dimension_a": dimension_a,
            "condition_level_a": level_a,
            "condition_dimension_b": dimension_b,
            "condition_level_b": level_b,
            "study_group_id": study_id,
            "study_observation_count": combination_study_observation_counts[key],
            "study_outcome_median": _median(values),
            "target_system_count": len(combination_study_systems[key]),
        }
        combination_by_study_rows.append(row)
        combination_by_stratum[key[:6]].append(row)

    combination_rows: list[dict[str, Any]] = []
    combination_lookup: dict[tuple[str, str, str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for key, rows in sorted(combination_by_stratum.items()):
        feature, unit, dimension_a, level_a, dimension_b, level_b = key
        medians = [float(row["study_outcome_median"]) for row in rows]
        systems_count = sum(int(row["target_system_count"]) for row in rows)
        supported = len(rows) >= minimum_studies
        row = {
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_dimension_a": dimension_a,
            "condition_level_a": level_a,
            "condition_dimension_b": dimension_b,
            "condition_level_b": level_b,
            "doi_study_count": len(rows),
            "observation_count": sum(int(item["study_observation_count"]) for item in rows),
            "median_of_study_medians": _median(medians),
            "study_median_mad": _mad(medians),
            "study_median_q1": _quantile(medians, 0.25),
            "study_median_q3": _quantile(medians, 0.75),
            "target_system_count_sum_within_studies": systems_count,
            "screening_status": "SUPPORTED_JOINT_CONDITION_STRATUM" if supported else "INSUFFICIENT_DOI_STUDIES",
            "interpretation_status": "JOINT_CONDITION_SUPPORT_NOT_A_STATISTICAL_INTERACTION",
            "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
        }
        combination_rows.append(row)
        for study_row in rows:
            combination_lookup[key][study_row["study_group_id"]] = {
                "median": float(study_row["study_outcome_median"])
            }

    combo_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in combination_rows:
        combo_groups[(
            row["feature_id"], row["outcome_unit"],
            row["condition_dimension_a"], row["condition_dimension_b"],
        )].append(row)

    combination_contrast_rows: list[dict[str, Any]] = []
    combination_hypothesis_rows: list[dict[str, Any]] = []
    for group_key, rows in sorted(combo_groups.items()):
        feature, unit, dimension_a, dimension_b = group_key
        supported_rows = [row for row in rows if row["doi_study_count"] >= minimum_studies]
        if len(supported_rows) < 2:
            continue
        supported_rows.sort(key=lambda row: (
            row["condition_level_a"], row["condition_level_b"]
        ))
        omitted = max(0, len(supported_rows) - _MAX_CONTRAST_LEVELS)
        selected_rows = supported_rows[:_MAX_CONTRAST_LEVELS]
        for left, right in itertools.combinations(selected_rows, 2):
            left_key = (
                feature, unit, dimension_a, left["condition_level_a"],
                dimension_b, left["condition_level_b"],
            )
            right_key = (
                feature, unit, dimension_a, right["condition_level_a"],
                dimension_b, right["condition_level_b"],
            )
            left_studies = combination_lookup[left_key]
            right_studies = combination_lookup[right_key]
            shared = sorted(set(left_studies) & set(right_studies))
            differences = [
                right_studies[study_id]["median"] - left_studies[study_id]["median"]
                for study_id in shared
            ]
            median_a = float(left["median_of_study_medians"])
            median_b = float(right["median_of_study_medians"])
            aggregate_difference = median_b - median_a
            if aggregate_difference > 0:
                opposite_count = sum(value < 0 for value in differences)
            elif aggregate_difference < 0:
                opposite_count = sum(value > 0 for value in differences)
            else:
                opposite_count = 0
            paired_higher_count = sum(value > 0 for value in differences)
            paired_lower_count = sum(value < 0 for value in differences)
            paired_equal_count = sum(value == 0 for value in differences)
            combination_contrast_rows.append({
                "combination_contrast_id": f"CCPA-{len(combination_contrast_rows) + 1:05d}",
                "feature_id": feature,
                "outcome_unit": unit,
                "condition_dimension_a": dimension_a,
                "condition_level_a_left": left["condition_level_a"],
                "condition_dimension_b": dimension_b,
                "condition_level_b_left": left["condition_level_b"],
                "condition_level_a_right": right["condition_level_a"],
                "condition_level_b_right": right["condition_level_b"],
                "doi_study_count_left": left["doi_study_count"],
                "doi_study_count_right": right["doi_study_count"],
                "median_outcome_left": median_a,
                "median_outcome_right": median_b,
                "median_difference_right_minus_left": aggregate_difference,
                "shared_doi_study_count": len(shared),
                "shared_doi_median_difference": _median(differences),
                "shared_doi_higher_outcome_count": paired_higher_count,
                "shared_doi_lower_outcome_count": paired_lower_count,
                "shared_doi_equal_outcome_count": paired_equal_count,
                "shared_doi_opposite_direction_count": opposite_count,
                "omitted_supported_combinations_from_pairwise_cap": omitted,
                "interpretation_status": "DESCRIPTIVE_JOINT_CONDITION_ASSOCIATION_NOT_INTERACTION_EFFECT",
                "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
            })
        lowest = min(supported_rows, key=lambda row: float(row["median_of_study_medians"]))
        highest = max(supported_rows, key=lambda row: float(row["median_of_study_medians"]))
        combination_hypothesis_rows.append({
            "combination_hypothesis_id": f"HCCPA-{len(combination_hypothesis_rows) + 1:05d}",
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_dimension_a": dimension_a,
            "condition_dimension_b": dimension_b,
            "supported_combination_count": len(supported_rows),
            "total_doi_study_support_across_combinations": sum(int(row["doi_study_count"]) for row in supported_rows),
            "lowest_outcome_combination": f"{lowest['condition_level_a']} × {lowest['condition_level_b']}",
            "lowest_combination_median_outcome": lowest["median_of_study_medians"],
            "highest_outcome_combination": f"{highest['condition_level_a']} × {highest['condition_level_b']}",
            "highest_combination_median_outcome": highest["median_of_study_medians"],
            "observed_combination_median_spread": float(highest["median_of_study_medians"]) - float(lowest["median_of_study_medians"]),
            "candidate_question": (
                f"Within {feature} ({unit}), do observed {dimension_a} × {dimension_b} "
                "combinations show different Study-level outcomes after semantic, system, "
                "protocol, and study-level confounder review?"
            ),
            "candidate_status": "REQUIRES_FEATURE_MAPPING_AND_JOINT_CONDITION_REVIEW",
            "claim_boundary": "JOINT_SUPPORT_AND_DESCRIPTIVE_ASSOCIATION_ONLY_NOT_STATISTICAL_INTERACTION_OR_SYNERGY",
        })

    # Collapse Study-level medians to condition strata. Do not treat observations
    # within a paper as independent replicates for between-group support.
    by_stratum: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, row in zip(sorted(grouped_study_values), study_strata_rows):
        by_stratum[key[:5]].append(row)

    exact_target_systems_by_stratum: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for study_key, study_values in study_lookup.items():
        exact_target_systems_by_stratum[study_key[:5]].update(study_values["systems"])

    stratum_rows: list[dict[str, Any]] = []
    summaries: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for key, rows in sorted(by_stratum.items()):
        feature, unit, condition_type, dimension, level = key
        medians = [float(row["study_outcome_median"]) for row in rows]
        all_numeric_conditions = sorted({
            value for row in rows for value in row["condition_numeric_values"]
        })
        numeric_units = sorted({value for row in rows for value in row["condition_numeric_units"]})
        target_system_count = len(exact_target_systems_by_stratum[key])
        supported = len(rows) >= minimum_studies
        row = {
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_type": condition_type,
            "condition_dimension": dimension,
            "condition_level": level,
            "study_count": len(rows),
            "observation_count": sum(int(item["study_observation_count"]) for item in rows),
            "median_of_study_medians": _median(medians),
            "study_median_mad": _mad(medians),
            "study_median_q1": _quantile(medians, 0.25),
            "study_median_q3": _quantile(medians, 0.75),
            "study_median_min": min(medians),
            "study_median_max": max(medians),
            "condition_numeric_values": all_numeric_conditions,
            "condition_numeric_units": numeric_units,
            "target_system_count": target_system_count,
            "screening_status": "SUPPORTED_DESCRIPTIVE_STRATUM" if supported else "INSUFFICIENT_DOI_STUDIES",
            "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
        }
        stratum_rows.append(row)
        summaries[key] = row

    study_lookup_by_stratum: dict[tuple[str, str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for key, value in study_lookup.items():
        study_lookup_by_stratum[key[:5]][key[5]] = value

    # Pairwise contrasts are descriptive differences in Study-level medians, not
    # inferential effects. Bound high-cardinality dimensions to avoid combinatorial
    # output while retaining every stratum in condition_performance_strata.csv.
    by_dimension: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, row in summaries.items():
        by_dimension[key[:4]].append(row)

    contrast_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    for dimension_key, rows in sorted(by_dimension.items()):
        feature, unit, condition_type, dimension = dimension_key
        supported_rows = [row for row in rows if int(row["study_count"]) >= minimum_studies]
        if len(supported_rows) < 2:
            continue
        # Numeric condition levels are ordered by value where consistently available.
        numeric_available = all(
            len(row["condition_numeric_values"]) == 1 for row in supported_rows
        )
        if numeric_available:
            supported_rows.sort(key=lambda row: (row["condition_numeric_values"][0], row["condition_level"]))
        else:
            supported_rows.sort(key=lambda row: row["condition_level"])
        omitted_level_count = max(0, len(supported_rows) - _MAX_CONTRAST_LEVELS)
        contrast_levels = supported_rows[:_MAX_CONTRAST_LEVELS]
        for left, right in itertools.combinations(contrast_levels, 2):
            left_key = (feature, unit, condition_type, dimension, left["condition_level"])
            right_key = (feature, unit, condition_type, dimension, right["condition_level"])
            left_studies = study_lookup_by_stratum.get(left_key, {})
            right_studies = study_lookup_by_stratum.get(right_key, {})
            shared = sorted(set(left_studies) & set(right_studies))
            paired_differences = [
                right_studies[study_id]["median"] - left_studies[study_id]["median"]
                for study_id in shared
            ]
            matched_system_studies = sum(
                bool(left_studies[study_id]["systems"] & right_studies[study_id]["systems"])
                for study_id in shared
            )
            left_median = float(left["median_of_study_medians"])
            right_median = float(right["median_of_study_medians"])
            paired_higher_count = sum(value > 0 for value in paired_differences)
            paired_lower_count = sum(value < 0 for value in paired_differences)
            paired_equal_count = sum(value == 0 for value in paired_differences)
            aggregate_direction = right_median - left_median
            paired_opposite_direction_count = (
                paired_lower_count if aggregate_direction > 0
                else paired_higher_count if aggregate_direction < 0
                else min(paired_higher_count, paired_lower_count)
            )
            contrast_rows.append({
                "contrast_id": f"CPA-{len(contrast_rows) + 1:05d}",
                "feature_id": feature,
                "outcome_unit": unit,
                "condition_type": condition_type,
                "condition_dimension": dimension,
                "level_a": left["condition_level"],
                "level_b": right["condition_level"],
                "study_count_a": left["study_count"],
                "study_count_b": right["study_count"],
                "median_outcome_a": left_median,
                "median_outcome_b": right_median,
                "median_difference_b_minus_a": right_median - left_median,
                "paired_study_count": len(shared),
                "paired_study_median_difference": _median(paired_differences),
                "paired_higher_outcome_in_level_b_count": paired_higher_count,
                "paired_lower_outcome_in_level_b_count": paired_lower_count,
                "paired_equal_outcome_count": paired_equal_count,
                "paired_opposite_to_aggregate_direction_count": paired_opposite_direction_count,
                "same_target_system_paired_study_count": matched_system_studies,
                "omitted_supported_levels_from_pairwise_cap": omitted_level_count,
                "interpretation_status": "DESCRIPTIVE_CROSS_STUDY_ASSOCIATION_NOT_CAUSAL_OR_INFERENTIAL",
                "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
            })
        lowest = min(supported_rows, key=lambda row: float(row["median_of_study_medians"]))
        highest = max(supported_rows, key=lambda row: float(row["median_of_study_medians"]))
        spread = float(highest["median_of_study_medians"]) - float(lowest["median_of_study_medians"])
        hypothesis_rows.append({
            "hypothesis_candidate_id": f"HCPA-{len(hypothesis_rows) + 1:05d}",
            "feature_id": feature,
            "outcome_unit": unit,
            "condition_type": condition_type,
            "condition_dimension": dimension,
            "supported_condition_level_count": len(supported_rows),
            "total_doi_study_support_across_levels": sum(int(row["study_count"]) for row in supported_rows),
            "lowest_median_level": lowest["condition_level"],
            "lowest_level_median_outcome": lowest["median_of_study_medians"],
            "highest_median_level": highest["condition_level"],
            "highest_level_median_outcome": highest["median_of_study_medians"],
            "observed_between_level_median_spread": spread,
            "pairwise_contrast_count_written": min(len(list(itertools.combinations(supported_rows, 2))),
                                                   len(list(itertools.combinations(contrast_levels, 2)))),
            "candidate_question": (
                f"Within {feature} ({unit}), do Study-level outcomes differ across "
                f"{dimension} levels after endpoint semantics, system/protocol comparability, "
                "and study-level confounding are reviewed?"
            ),
            "candidate_status": "REQUIRES_FEATURE_MAPPING_AND_DOMAIN_REVIEW",
            "claim_boundary": "EXPLORATORY_ASSOCIATION_ONLY_NO_CAUSAL_OR_SIGNIFICANCE_CLAIM",
        })

    _write_csv(output_dir / "condition_combination_performance_study_strata.csv", [
        "feature_id", "outcome_unit", "condition_dimension_a", "condition_level_a",
        "condition_dimension_b", "condition_level_b", "study_group_id",
        "study_observation_count", "study_outcome_median", "target_system_count",
    ], combination_by_study_rows)
    _write_csv(output_dir / "condition_combination_performance.csv", [
        "feature_id", "outcome_unit", "condition_dimension_a", "condition_level_a",
        "condition_dimension_b", "condition_level_b", "doi_study_count", "observation_count",
        "median_of_study_medians", "study_median_mad", "study_median_q1", "study_median_q3",
        "target_system_count_sum_within_studies", "screening_status", "interpretation_status",
        "endpoint_semantics_status",
    ], combination_rows)
    _write_csv(output_dir / "condition_combination_contrasts.csv", [
        "combination_contrast_id", "feature_id", "outcome_unit",
        "condition_dimension_a", "condition_level_a_left", "condition_dimension_b",
        "condition_level_b_left", "condition_level_a_right", "condition_level_b_right",
        "doi_study_count_left", "doi_study_count_right", "median_outcome_left",
        "median_outcome_right", "median_difference_right_minus_left",
        "shared_doi_study_count", "shared_doi_median_difference",
        "shared_doi_higher_outcome_count", "shared_doi_lower_outcome_count",
        "shared_doi_equal_outcome_count", "shared_doi_opposite_direction_count",
        "omitted_supported_combinations_from_pairwise_cap",
        "interpretation_status", "endpoint_semantics_status",
    ], combination_contrast_rows)
    _write_csv(output_dir / "condition_combination_hypothesis_candidates.csv", [
        "combination_hypothesis_id", "feature_id", "outcome_unit",
        "condition_dimension_a", "condition_dimension_b", "supported_combination_count",
        "total_doi_study_support_across_combinations", "lowest_outcome_combination",
        "lowest_combination_median_outcome", "highest_outcome_combination",
        "highest_combination_median_outcome", "observed_combination_median_spread",
        "candidate_question", "candidate_status", "claim_boundary",
    ], combination_hypothesis_rows)

    _write_csv(output_dir / "condition_performance_feature_coverage.csv", [
        "feature_id", "outcome_unit", "eligible_numeric_outcome_observation_count",
        "condition_linked_observation_count", "condition_linkage_coverage_fraction",
        "doi_study_count", "condition_linked_doi_study_count", "endpoint_semantics_status",
    ], feature_coverage_rows)
    _write_csv(output_dir / "condition_outcome_links.csv", [
        "observation_id", "paper_id", "doi", "study_group_id", "feature_id",
        "outcome_value", "outcome_unit", "target_system", "condition_type",
        "condition_dimension", "condition_level", "condition_normalized_value", "condition_numeric_value",
        "condition_numeric_unit", "condition_unit_basis", "condition_source_fields",
        "condition_extraction_methods", "condition_confidence", "condition_record_match_count",
        "condition_record_ids",
    ], link_rows)
    _write_csv(output_dir / "condition_performance_study_strata.csv", [
        "feature_id", "outcome_unit", "condition_type", "condition_dimension",
        "condition_level", "study_group_id", "study_observation_count",
        "study_outcome_median", "study_outcome_min", "study_outcome_max",
        "target_system_count", "target_system_examples", "condition_numeric_values",
        "condition_numeric_units", "observation_ids_sample",
    ], study_strata_rows)
    _write_csv(output_dir / "condition_performance_strata.csv", [
        "feature_id", "outcome_unit", "condition_type", "condition_dimension",
        "condition_level", "study_count", "observation_count",
        "median_of_study_medians", "study_median_mad", "study_median_q1",
        "study_median_q3", "study_median_min", "study_median_max",
        "condition_numeric_values", "condition_numeric_units", "target_system_count",
        "screening_status", "endpoint_semantics_status",
    ], stratum_rows)
    _write_csv(output_dir / "condition_performance_contrasts.csv", [
        "contrast_id", "feature_id", "outcome_unit", "condition_type",
        "condition_dimension", "level_a", "level_b", "study_count_a", "study_count_b",
        "median_outcome_a", "median_outcome_b", "median_difference_b_minus_a",
        "paired_study_count", "paired_study_median_difference",
        "paired_higher_outcome_in_level_b_count", "paired_lower_outcome_in_level_b_count",
        "paired_equal_outcome_count", "paired_opposite_to_aggregate_direction_count",
        "same_target_system_paired_study_count",
        "omitted_supported_levels_from_pairwise_cap", "interpretation_status",
        "endpoint_semantics_status",
    ], contrast_rows)
    _write_csv(output_dir / "condition_hypothesis_candidates.csv", [
        "hypothesis_candidate_id", "feature_id", "outcome_unit", "condition_type",
        "condition_dimension", "supported_condition_level_count",
        "total_doi_study_support_across_levels", "lowest_median_level",
        "lowest_level_median_outcome", "highest_median_level",
        "highest_level_median_outcome", "observed_between_level_median_spread",
        "pairwise_contrast_count_written", "candidate_question", "candidate_status",
        "claim_boundary",
    ], hypothesis_rows)

    matched_observation_ids = {row["observation_id"] for row in link_rows}
    summary = {
        "schema_version": "1.0",
        "analysis": "CONDITION_STRATIFIED_STUDY_LEVEL_DESCRIPTIVE_ASSOCIATION_SCREEN",
        "mapping_status": "PENDING_INSPECTION_OF_ACTUAL_CSV_AND_JSON",
        "endpoint_semantics_status": "UNMAPPED_FEATURE_SEMANTICS",
        "minimum_doi_studies_per_condition_level": minimum_studies,
        "numeric_outcome_observation_count": len(outcome_by_id),
        "numeric_outcome_observations_linked_to_conditions": len(matched_observation_ids),
        "condition_outcome_link_row_count": len(link_rows),
        "study_level_stratum_row_count": len(study_strata_rows),
        "condition_stratum_row_count": len(stratum_rows),
        "feature_coverage_row_count": len(feature_coverage_rows),
        "feature_coverage_preview": feature_coverage_rows[:25],
        "supported_condition_stratum_count": sum(
            row["screening_status"] == "SUPPORTED_DESCRIPTIVE_STRATUM" for row in stratum_rows
        ),
        "condition_dimension_count": len(by_dimension),
        "screenable_condition_dimension_count": len(hypothesis_rows),
        "descriptive_contrast_count": len(contrast_rows),
        "hypothesis_candidate_count": len(hypothesis_rows),
        "joint_condition_observation_count": len(links_by_observation),
        "redundant_joint_condition_pairs_skipped": redundant_combination_pair_count,
        "joint_condition_combination_study_strata_count": len(combination_by_study_rows),
        "joint_condition_combination_strata_count": len(combination_rows),
        "supported_joint_condition_combination_count": sum(
            row["screening_status"] == "SUPPORTED_JOINT_CONDITION_STRATUM"
            for row in combination_rows
        ),
        "joint_condition_combination_contrast_count": len(combination_contrast_rows),
        "joint_condition_hypothesis_candidate_count": len(combination_hypothesis_rows),
        "joint_condition_hypothesis_preview": combination_hypothesis_rows[:25],
        "ambiguous_observation_dimension_count": len(ambiguous_keys),
        "excluded_condition_candidate_count": excluded_candidate_count,
        "unsupported_condition_candidate_count": unsupported_candidate_count,
        "pairwise_level_cap": _MAX_CONTRAST_LEVELS,
        "pairwise_truncation_dimension_count": sum(
            1 for rows in by_dimension.values()
            if sum(1 for row in rows if int(row["study_count"]) >= minimum_studies) > _MAX_CONTRAST_LEVELS
        ),
        "hypothesis_candidates_preview": [
            {
                "hypothesis_candidate_id": row["hypothesis_candidate_id"],
                "feature_id": row["feature_id"],
                "outcome_unit": row["outcome_unit"],
                "condition_dimension": row["condition_dimension"],
                "supported_condition_level_count": row["supported_condition_level_count"],
                "total_doi_study_support_across_levels": row["total_doi_study_support_across_levels"],
                "observed_between_level_median_spread": row["observed_between_level_median_spread"],
            }
            for row in hypothesis_rows[:25]
        ],
        "files": [
            "condition_combination_performance_study_strata.csv",
            "condition_combination_performance.csv",
            "condition_combination_contrasts.csv",
            "condition_combination_hypothesis_candidates.csv",
            "condition_performance_feature_coverage.csv",
            "condition_outcome_links.csv",
            "condition_performance_study_strata.csv",
            "condition_performance_strata.csv",
            "condition_performance_contrasts.csv",
            "condition_hypothesis_candidates.csv",
        ],
        "interpretation_limits": [
            "Only AGREED_MATCH numeric outcomes with explicit DOI, exact feature ID, and exact non-empty unit are included.",
            "Each DOI contributes one median per feature/unit/condition-level stratum; observations within a DOI are not counted as independent Studies.",
            "Condition values are deterministic candidates, not human-accepted facts; low-confidence and context-review table candidates are excluded.",
            "Multiple candidate levels for the same condition dimension within one observation are marked ambiguous and excluded from that dimension's comparison.",
            "Electrolyte-component presence is not treated as a mutually exclusive condition level because mixtures may contain multiple salts; salt-specific concentration candidates are screened separately.",
            "Different condition levels may be confounded by target system, cell design, protocol, laboratory, or other unrecorded variables.",
            "Feature identifiers remain semantically unmapped; do not label an endpoint or interpret the direction as better/worse until domain mapping is reviewed.",
            "Contrasts are descriptive differences of Study-level medians, not p-values, confidence intervals, causal effects, or mechanisms.",
            "No dose-response trend is fitted and percentage bases are never inferred.",
            "Cell configuration and its derived cell-configuration class are not paired as independent conditions because that would create a deterministic duplicate combination.",
            "Joint condition combination files describe co-recorded condition support and outcomes; they do not estimate statistical interaction terms, synergistic effects, or causal modification.",
        ],
    }
    (output_dir / "condition_performance_analysis_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
