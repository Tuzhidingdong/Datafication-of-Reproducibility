"""Deterministic, Study-aware screening of canonical condition/outcome opportunities.

This module never infers scientific meanings from canonical identifiers. It screens
only reported numeric observations linked through the declared Experiment/System/
Study relationships and keeps the independent Study as the inferential unit.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from typing import Any

ENGINE_VERSION = "1.3.0"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _reported_value(record: dict[str, Any]) -> tuple[Any, str]:
    """Use normalized value/unit only as a complete pair; otherwise use raw pair."""
    if record.get("normalized_value") not in (None, "") and record.get("normalized_unit") not in (None, ""):
        return record.get("normalized_value"), str(record.get("normalized_unit")).strip()
    value = record.get("raw_value")
    unit = record.get("raw_unit")
    return value, str(unit).strip() if unit not in (None, "") else "UNSPECIFIED_UNIT"


def _label(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _identifier_key(value: Any) -> str:
    """Keep canonical identifiers exact; never case-fold or strip punctuation."""
    return str(value) if value is not None else ""


def _semantic_metadata_index(records: list[dict[str, Any]], key_field: str) -> dict[str, dict[str, Any]]:
    """Summarize optional, explicitly reviewed semantic metadata without guessing."""
    grouped: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        key = str(record.get(key_field) or "")
        if key:
            grouped[key].append(record.get("semantic_metadata"))
    result: dict[str, dict[str, Any]] = {}
    for key, entries in grouped.items():
        supplied = [item for item in entries if isinstance(item, dict)]
        if not supplied:
            result[key] = {"status": "MISSING", "metadata": None}
            continue
        if len(supplied) != len(entries):
            result[key] = {"status": "PARTIAL", "metadata": None}
            continue
        if len({_label(item) for item in supplied}) != 1:
            result[key] = {"status": "CONFLICTING", "metadata": None}
            continue
        metadata = supplied[0]
        approved = str(metadata.get("review_status") or "").strip().upper() == "APPROVED"
        approved = approved and bool(str(metadata.get("canonical_concept_id") or "").strip())
        result[key] = {"status": "APPROVED" if approved else "UNAPPROVED", "metadata": metadata}
    return result


def _metadata_dependencies(metadata: dict[str, Any] | None) -> set[str]:
    if not metadata:
        return set()
    raw = metadata.get("derived_from", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {_identifier_key(item) for item in raw if _identifier_key(item)}


def _semantic_metadata_summary(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {"status": "MISSING", "canonical_concept_id": None}
    metadata = entry.get("metadata") or {}
    return {
        "status": entry.get("status", "MISSING"),
        "canonical_concept_id": metadata.get("canonical_concept_id"),
        "display_name": metadata.get("display_name"),
        "definition": metadata.get("definition"),
        "measurement_basis": metadata.get("measurement_basis"),
        "measurement_context": metadata.get("measurement_context"),
        "derivation_type": metadata.get("derivation_type"),
        "derived_from": metadata.get("derived_from", []),
        "reviewer": metadata.get("reviewer"),
        "reviewed_at": metadata.get("reviewed_at"),
        "review_rationale": metadata.get("review_rationale"),
        "source_refs": metadata.get("source_refs", []),
    }


def _semantic_review(target_id: str, condition_type: str,
                     target_entry: dict[str, Any] | None,
                     condition_entry: dict[str, Any] | None) -> dict[str, Any]:
    target = _semantic_metadata_summary(target_entry)
    condition = _semantic_metadata_summary(condition_entry)
    if target["status"] == "APPROVED" and condition["status"] == "APPROVED":
        if target.get("canonical_concept_id") != condition.get("canonical_concept_id"):
            relationship = "DISTINCT_APPROVED_CONCEPTS"
        elif (
            target.get("measurement_context")
            and target.get("measurement_context") == condition.get("measurement_context")
        ):
            relationship = "SAME_APPROVED_CONCEPT_SAME_MEASUREMENT_CONTEXT"
        else:
            relationship = "SAME_APPROVED_CONCEPT_CONTEXT_UNRESOLVED"
        status = "APPROVED_METADATA_AVAILABLE_FOR_DOMAIN_REVIEW"
    else:
        relationship = "UNRESOLVED_FROM_AVAILABLE_METADATA"
        status = "DOMAIN_SEMANTIC_REVIEW_REQUIRED"
    return {
        "status": status,
        "relationship_status": relationship,
        "target": {"identifier": target_id, **target},
        "condition": {"identifier": condition_type, **condition},
        "interpretation": (
            "Only consistently supplied, explicitly reviewed metadata is reported. "
            "Physical meaning is not inferred from identifiers, labels, or correlations."
        ),
    }


def _self_association_reason(
    target_id: str, condition_type: str, outcome_unit: str, condition_unit: str,
    levels_by_label: dict[str, dict[str, dict[str, dict[str, Any]]]],
    target_metadata: dict[str, Any] | None = None,
    condition_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Return a reason only for explicit identity/dependency, never high correlation."""
    if _identifier_key(target_id) and _identifier_key(target_id) == _identifier_key(condition_type):
        return "SAME_CANONICAL_ATTRIBUTE"
    target_meta = (target_metadata or {}).get("metadata") or {}
    condition_meta = (condition_metadata or {}).get("metadata") or {}
    if (target_metadata or {}).get("status") == "APPROVED" and (condition_metadata or {}).get("status") == "APPROVED":
        target_concept = str(target_meta.get("canonical_concept_id") or "").strip()
        condition_concept = str(condition_meta.get("canonical_concept_id") or "").strip()
        if (
            target_concept
            and target_concept == condition_concept
            and target_meta.get("measurement_context")
            and target_meta.get("measurement_context") == condition_meta.get("measurement_context")
        ):
            return "SAME_APPROVED_SEMANTIC_CONCEPT"
        target_dependencies = (
            _metadata_dependencies(target_meta)
            if str(target_meta.get("derivation_type") or "").upper() == "CALCULATED" else set()
        )
        condition_dependencies = (
            _metadata_dependencies(condition_meta)
            if str(condition_meta.get("derivation_type") or "").upper() == "CALCULATED" else set()
        )
        if (_identifier_key(condition_type) in target_dependencies
                or _identifier_key(condition_concept) in target_dependencies
                or _identifier_key(target_id) in condition_dependencies
                or _identifier_key(target_concept) in condition_dependencies):
            return "DECLARED_DIRECT_DERIVATION"
    if outcome_unit != condition_unit:
        return None
    compared = []
    study_ids = set()
    for study_levels in levels_by_label.values():
        for study_id, systems_by_study in study_levels.items():
            for cell in systems_by_study.values():
                condition_value = cell.get("condition_number")
                outcome_value = _median(cell.get("values", []))
                if condition_value is None or outcome_value is None:
                    return None
                compared.append((condition_value, outcome_value))
                study_ids.add(study_id)
    if len(study_ids) >= 3 and len(compared) >= 4 and all(
        math.isclose(condition, outcome, rel_tol=0.0, abs_tol=0.0)
        for condition, outcome in compared
    ):
        return "IDENTICAL_VALUES"
    return None

def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = ((index + 1) + end) / 2.0
        for cursor in range(index, end):
            ranks[ordered[cursor][0]] = average
        index = end
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 4 or len(set(xs)) < 3 or len(set(ys)) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    dx = [value - mx for value in rx]
    dy = [value - my for value in ry]
    denominator = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(dx, dy)) / denominator))


def _sign_test_p(values: list[float]) -> float | None:
    """Exact two-sided sign test across independent Study-level effects."""
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    n = positive + negative
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(positive, negative) + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    fraction = position - lower
    return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)


def _bootstrap_median_ci(values: list[float], iterations: int, seed: int) -> list[float] | None:
    if len(values) < 2 or iterations < 100:
        return None
    rng = random.Random(seed)
    sampled_medians = []
    for _ in range(iterations):
        sampled = [values[rng.randrange(len(values))] for _ in values]
        sampled_medians.append(float(statistics.median(sampled)))
    lower = _percentile(sampled_medians, 0.025)
    upper = _percentile(sampled_medians, 0.975)
    return [lower, upper] if lower is not None and upper is not None else None


def _stable_seed(seed: int, identity: Any) -> int:
    digest = hashlib.sha256(_label(identity).encode("utf-8")).digest()
    return (seed + int.from_bytes(digest[:4], "big")) % (2 ** 32)


def _apply_bh(rows: list[dict[str, Any]], family: str) -> None:
    eligible = [(index, row["p_value"]) for index, row in enumerate(rows)
                if row.get("analysis_family") == family
                and row.get("p_value") is not None
                and not row.get("mirror_duplicate_of_opportunity_id")]
    eligible.sort(key=lambda item: (item[1], item[0]))
    total = len(eligible)
    running = 1.0
    for rank in range(total, 0, -1):
        index, p_value = eligible[rank - 1]
        running = min(running, p_value * total / rank)
        rows[index]["q_value"] = min(1.0, running)


def _json_safe_key(key: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "target_id": key[0],
        "endpoint_definition": key[1],
        "timepoint": key[2],
        "outcome_unit": key[3],
    }


def _opportunity_id(identity: Any) -> str:
    digest = hashlib.sha256(_label(identity).encode("utf-8")).hexdigest()[:12].upper()
    return "OPP-" + digest


def _correlation_opportunity_id(row: dict[str, Any]) -> str:
    outcome_key = (row["target_id"], row["endpoint_definition"], row["timepoint"], row["outcome_unit"])
    condition_base = (row["condition_type"], row["condition_unit"])
    return _opportunity_id(["BETWEEN_SYSTEM_SPEARMAN", outcome_key, condition_base])


def _reciprocal_pattern_proof(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """Prove reciprocal values and exact support while retaining endpoint/timepoint context."""
    if (left.get("analysis_family") != "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
            or right.get("analysis_family") != "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"):
        return None
    if not (
        left.get("target_id") == right.get("condition_type")
        and left.get("condition_type") == right.get("target_id")
        and left.get("outcome_unit") == right.get("condition_unit")
        and left.get("condition_unit") == right.get("outcome_unit")
    ):
        return None
    left_studies = {item["study_id"]: item for item in left.get("study_effects", [])}
    right_studies = {item["study_id"]: item for item in right.get("study_effects", [])}
    if (not left_studies or set(left_studies) != set(right_studies)
            or left.get("p_value") is None or right.get("p_value") is None):
        return None
    matched_systems, matched_experiments, matched_observations = 0, set(), set()
    for study_id in sorted(left_studies):
        a_points = {item["system_id"]: item for item in left_studies[study_id].get("system_points", [])}
        b_points = {item["system_id"]: item for item in right_studies[study_id].get("system_points", [])}
        if not a_points or set(a_points) != set(b_points):
            return None
        for system_id in sorted(a_points):
            a, b = a_points[system_id], b_points[system_id]
            if not (
                math.isclose(float(a["condition_value"]), float(b["outcome_median"]), rel_tol=0.0, abs_tol=0.0)
                and math.isclose(float(a["outcome_median"]), float(b["condition_value"]), rel_tol=0.0, abs_tol=0.0)
                and set(a.get("supporting_experiment_ids", [])) == set(b.get("supporting_experiment_ids", []))
            ):
                return None
            matched_systems += 1
            matched_experiments.update(a.get("supporting_experiment_ids", []))
            matched_observations.update(a.get("supporting_observation_ids", []))
            matched_observations.update(b.get("supporting_observation_ids", []))
    same_endpoint = left.get("endpoint_definition") == right.get("endpoint_definition")
    same_timepoint = left.get("timepoint") == right.get("timepoint")
    return {
        "exact_reciprocal_values": True,
        "identical_study_support": True,
        "identical_system_support_within_each_study": True,
        "identical_experiment_support_within_each_system": True,
        "unit_strings_cross_match_exactly": True,
        "same_endpoint_definition": same_endpoint,
        "same_timepoint": same_timepoint,
        "context_dimensions_differ": [
            key for key, same in (
                ("endpoint_definition", same_endpoint),
                ("timepoint", same_timepoint),
            ) if not same
        ],
        "supporting_study_ids": sorted(left_studies),
        "matched_system_count": matched_systems,
        "matched_experiment_count": len(matched_experiments),
        "matched_observation_count": len(matched_observations),
    }


def _exact_mirror_proof(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """Deduplication proof additionally requires identical endpoint and timepoint."""
    proof = _reciprocal_pattern_proof(left, right)
    if proof is None or not proof["same_endpoint_definition"] or not proof["same_timepoint"]:
        return None
    return {
        key: value for key, value in proof.items()
        if key not in {"same_endpoint_definition", "same_timepoint", "context_dimensions_differ"}
    }


def _related_opportunity_groups(
    opportunities: list[dict[str, Any]],
    correlation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group exact reciprocal data patterns with differing context, without statistical merging."""
    opportunity_by_id = {item["opportunity_id"]: item for item in opportunities}
    groups = []
    for left_index, left in enumerate(correlation_rows):
        left_id = _correlation_opportunity_id(left)
        if left_id not in opportunity_by_id:
            continue
        for right in correlation_rows[left_index + 1:]:
            right_id = _correlation_opportunity_id(right)
            if right_id not in opportunity_by_id:
                continue
            proof = _reciprocal_pattern_proof(left, right)
            if proof is None or not proof["context_dimensions_differ"]:
                continue
            member_ids = sorted([left_id, right_id])
            group_id = "REL-" + hashlib.sha256(_label(member_ids).encode("utf-8")).hexdigest()[:12].upper()
            members = []
            for opportunity_id in member_ids:
                item = opportunity_by_id[opportunity_id]
                item.setdefault("related_group_ids", []).append(group_id)
                members.append({
                    "opportunity_id": opportunity_id,
                    "target_id": item["target_id"],
                    "condition_type": item["condition_type"],
                    "endpoint_definition": item["endpoint_definition"],
                    "timepoint": item["timepoint"],
                    "outcome_unit": item["outcome_unit"],
                    "condition_unit": item["condition_unit"],
                    "p_value": item.get("p_value"),
                    "q_value": item.get("q_value"),
                })
            groups.append({
                "related_group_id": group_id,
                "relationship_type": "RECIPROCAL_DATA_PATTERN_CONTEXT_VARIANT",
                "member_opportunity_ids": member_ids,
                "members": members,
                "proof": proof,
                "review_status": "REQUIRES_DOMAIN_REVIEW",
                "decision": "KEEP_ALL_MEMBERS_AS_DISTINCT_HYPOTHESES",
                "statistical_action": "NO_DEDUPLICATION_NO_FDR_CHANGE",
            })
    return sorted(groups, key=lambda item: item["related_group_id"])


def _mark_exact_mirror_duplicates(correlation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = list(range(len(correlation_rows)))
    proofs: dict[tuple[int, int], dict[str, Any]] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(correlation_rows)):
        for right in range(left + 1, len(correlation_rows)):
            proof = _exact_mirror_proof(correlation_rows[left], correlation_rows[right])
            if proof is not None:
                proofs[(left, right)] = proof
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(correlation_rows)):
        groups[find(index)].append(index)
    diagnostics = []
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        representative_index = min(
            indexes,
            key=lambda index: (
                str(correlation_rows[index].get("target_id", "")),
                str(correlation_rows[index].get("condition_type", "")),
                _label(correlation_rows[index].get("endpoint_definition")),
                _label(correlation_rows[index].get("timepoint")),
            ),
        )
        representative = correlation_rows[representative_index]
        representative_id = _correlation_opportunity_id(representative)
        member_ids = sorted(_correlation_opportunity_id(correlation_rows[index]) for index in indexes)
        group_id = "MIRROR-" + hashlib.sha256(_label(member_ids).encode("utf-8")).hexdigest()[:12].upper()
        for index in indexes:
            row = correlation_rows[index]
            row["mirror_group_id"] = group_id
            if index == representative_index:
                row["deduplication_status"] = "UNIQUE_MIRROR_GROUP_REPRESENTATIVE"
            else:
                row["deduplication_status"] = "EXACT_MIRROR_DUPLICATE_EXCLUDED_FROM_FDR"
                row["mirror_duplicate_of_opportunity_id"] = representative_id
        proof_candidates = [proof for (left, right), proof in proofs.items()
                            if left in indexes and right in indexes]
        if not proof_candidates:
            raise RuntimeError("Mirror group has no exact reciprocal proof.")
        diagnostics.append({
            "mirror_group_id": group_id,
            "representative_opportunity_id": representative_id,
            "duplicate_opportunity_ids": sorted(
                _correlation_opportunity_id(correlation_rows[index])
                for index in indexes if index != representative_index
            ),
            "member_opportunity_ids": member_ids,
            "attribute_pair": sorted({str(correlation_rows[index].get("target_id")) for index in indexes}),
            "proof": proof_candidates[0],
            "decision": "ONE_STATISTICAL_HYPOTHESIS_RETAINED_BEFORE_BH_FDR",
        })
    return sorted(diagnostics, key=lambda item: item["mirror_group_id"])


def _screen_recorded_condition_covariates(
    study_effects: list[dict[str, Any]],
    primary_condition_base: tuple[str, str],
    target_id: str,
    system_condition_values: dict[tuple[str, str], dict[tuple[str, str], dict[str, dict[str, Any]]]],
) -> dict[str, Any]:
    """Flag exact monotonic co-exposures recorded on the same System cohort."""
    covariate_bases = sorted(
        {base for condition_map in system_condition_values.values() for base in condition_map},
        key=_label,
    )
    findings: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    coverage_rows = []
    examined = set()
    for covariate_base in covariate_bases:
        if (
            covariate_base == primary_condition_base
            or _identifier_key(covariate_base[0]) == _identifier_key(target_id)
        ):
            continue
        examined.add(covariate_base)
        complete_studies, incomplete_studies, rank_eligible_studies = [], [], []
        for study_effect in study_effects:
            study_id = study_effect["study_id"]
            points = study_effect.get("system_points", [])
            covariate_values, complete = [], True
            for point in points:
                levels = system_condition_values.get((study_id, point["system_id"]), {}).get(covariate_base, {})
                if len(levels) != 1:
                    complete = False
                    break
                level = next(iter(levels.values()))
                if level.get("condition_number") is None:
                    complete = False
                    break
                covariate_values.append(float(level["condition_number"]))
            if not complete or len(covariate_values) != len(points):
                incomplete_studies.append(study_id)
                continue
            complete_studies.append(study_id)
            exposure_values = [float(point["condition_value"]) for point in points]
            outcome_values = [float(point["outcome_median"]) for point in points]
            rho_exposure = _spearman(exposure_values, covariate_values)
            if rho_exposure is None:
                continue
            rank_eligible_studies.append(study_id)
            rho_outcome = _spearman(covariate_values, outcome_values)
            if abs(rho_exposure) == 1.0:
                findings[covariate_base].append({
                    "study_id": study_id,
                    "system_count": len(points),
                    "spearman_rho_with_primary_condition": rho_exposure,
                    "spearman_rho_with_outcome": rho_outcome,
                    "supporting_system_ids": sorted(point["system_id"] for point in points),
                })
        coverage_rows.append({
            "condition_type": covariate_base[0],
            "condition_unit": covariate_base[1],
            "complete_numeric_coverage_study_ids": sorted(complete_studies),
            "complete_numeric_coverage_study_count": len(complete_studies),
            "incomplete_or_ambiguous_study_ids": sorted(incomplete_studies),
            "rank_screen_eligible_study_ids": sorted(rank_eligible_studies),
            "status": (
                "EXACT_MONOTONIC_CO_VARIATION_DETECTED"
                if findings.get(covariate_base)
                else "NO_EXACT_MONOTONIC_CO_VARIATION_IN_EVALUABLE_STUDIES"
                if rank_eligible_studies
                else "INSUFFICIENT_OR_INCOMPLETE_COVARIATE_COVERAGE"
            ),
        })
    serialized = []
    for (condition_type, condition_unit), rows in sorted(findings.items(), key=lambda item: _label(item[0])):
        serialized.append({
            "condition_type": condition_type,
            "condition_unit": condition_unit,
            "status": "PERFECT_MONOTONIC_CO_VARIATION_WITH_PRIMARY_EXPOSURE",
            "supporting_studies": sorted(item["study_id"] for item in rows),
            "study_count": len(rows),
            "study_details": rows,
            "interpretation": "Potential co-exposure/non-identifiability; this is a review flag, not proof of confounding.",
        })
    if serialized:
        overall_status = "POTENTIAL_CO_EXPOSURE_REQUIRES_DOMAIN_REVIEW"
    elif not coverage_rows:
        overall_status = "NO_OTHER_RECORDED_CONDITION_COVARIATE_AVAILABLE"
    elif not any(row["rank_screen_eligible_study_ids"] for row in coverage_rows):
        overall_status = "NO_EVALUABLE_RECORDED_COVARIATE_COVERAGE"
    else:
        overall_status = "NO_PERFECT_MONOTONIC_RECORDED_COVARIATE_DETECTED"
    return {
        "status": overall_status,
        "screen_method": "EXACT_WITHIN_STUDY_SPEARMAN_ABS_RHO_EQ_1_ON_COMPLETE_SYSTEM_COHORT",
        "recorded_condition_covariate_types_examined": len(examined),
        "covariate_coverage": coverage_rows,
        "findings": serialized,
        "unassessed_confounder_domains": [
            "System/material/composition descriptors not represented as structured reported Conditions",
            "Protocol, laboratory, synthesis, measurement and batch effects not represented as structured numeric/categorical covariates",
            "Unmeasured or incompletely reported variables",
        ],
        "limitation": "This is an unadjusted screening diagnostic. No covariate adjustment or causal identification is performed.",
    }



def build_scientific_opportunities(
    bundle: dict[str, Any],
    minimum_paired_studies: int = 3,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    maximum_opportunities: int = 500,
    maximum_levels_per_condition: int = 20,
    seed: int = 42,
    semantic_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Screen within-Study/System condition contrasts and numeric condition trends.

    Observations are first reduced to an Experiment-level median. Conditions are
    compared within the same Study and System; multiple systems then contribute
    one median effect per Study. All p-values therefore use independent Studies,
    never flattened Observation rows, as their sampling unit.
    """
    if minimum_paired_studies < 3:
        raise ValueError("minimum_paired_studies must be >= 3 for the Study-level sign test.")
    if not 0 < fdr_alpha < 1:
        raise ValueError("fdr_alpha must be between 0 and 1.")
    if bootstrap_iterations < 0 or maximum_opportunities < 1 or maximum_levels_per_condition < 2:
        raise ValueError("bootstrap_iterations must be non-negative, maximum_opportunities positive, and maximum_levels_per_condition >= 2.")

    semantic_registry_summary = {
        "status": "NOT_SUPPLIED",
        "registry_id": None,
        "record_count": 0,
        "approved_record_count": 0,
        "applied_record_count": 0,
        "target_record_count": 0,
        "condition_record_count": 0,
        "bundle_modified": False,
        "source_locators_dereferenced": False,
    }
    if semantic_registry is not None:
        from dor.semantic_registry import overlay_semantic_registry
        bundle, semantic_registry_summary = overlay_semantic_registry(bundle, semantic_registry)

    experiments = {row["experiment_id"]: row for row in bundle.get("experiments", [])}
    systems = {row["system_id"]: row for row in bundle.get("systems", [])}
    conditions = {row["condition_id"]: row for row in bundle.get("conditions", [])}
    target_semantic_index = _semantic_metadata_index(bundle.get("observations", []), "target_id")
    condition_semantic_index = _semantic_metadata_index(bundle.get("conditions", []), "condition_type")

    # Experiment-level outcomes: several Observations in one Experiment are
    # summarized first, so repeated rows cannot inflate independent sample size.
    observations_by_experiment: dict[str, dict[tuple[str, str, str, str], list[tuple[float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    all_observation_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    reported_numeric_count = 0
    for observation in bundle.get("observations", []):
        if observation.get("value_state") != "REPORTED":
            continue
        value, unit = _reported_value(observation)
        numeric = _finite_number(value)
        if numeric is None or unit == "UNSPECIFIED_UNIT":
            continue
        target_id = str(observation.get("target_id") or "UNSPECIFIED_TARGET")
        endpoint = str(observation.get("endpoint_definition") or "UNSPECIFIED_ENDPOINT_DEFINITION")
        timepoint = str(observation.get("timepoint")) if observation.get("timepoint") not in (None, "") else "UNSPECIFIED_TIMEPOINT"
        outcome_key = (target_id, endpoint, timepoint, unit)
        experiment_id = observation.get("experiment_id")
        if experiment_id not in experiments:
            continue
        observations_by_experiment[experiment_id][outcome_key].append(
            (numeric, str(observation.get("observation_id") or ""))
        )
        all_observation_counts[outcome_key] += 1
        reported_numeric_count += 1

    # Experiment-level condition assignments. Multiple distinct values of one
    # condition type/unit on the same Experiment are not silently resolved.
    ambiguous_assignments = 0
    experiment_conditions: dict[str, dict[tuple[str, str], tuple[str, Any, float | None]]] = {}
    for experiment_id, experiment in experiments.items():
        grouped: dict[tuple[str, str], dict[str, tuple[Any, float | None]]] = defaultdict(dict)
        for condition_id in experiment.get("condition_ids", []):
            condition = conditions.get(condition_id)
            if not condition or condition.get("value_state") != "REPORTED":
                continue
            value, unit = _reported_value(condition)
            if value in (None, ""):
                continue
            condition_type = str(condition.get("condition_type") or "UNSPECIFIED_CONDITION")
            level_key = (condition_type, unit)
            label = _label(value)
            grouped[level_key][label] = (value, _finite_number(value))
        assigned: dict[tuple[str, str], tuple[str, Any, float | None]] = {}
        for base, levels in grouped.items():
            if len(levels) != 1:
                ambiguous_assignments += 1
                continue
            label, (value, number) = next(iter(levels.items()))
            assigned[base] = (label, value, number)
        experiment_conditions[experiment_id] = assigned

    system_condition_values: dict[tuple[str, str], dict[tuple[str, str], dict[str, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for experiment_id, assigned in experiment_conditions.items():
        experiment = experiments[experiment_id]
        system_key = (str(experiment["study_id"]), str(experiment["system_id"]))
        for condition_base, (level_label, raw_level, level_number) in assigned.items():
            item = system_condition_values[system_key][condition_base].setdefault(
                level_label,
                {"condition_value": raw_level, "condition_number": level_number, "experiment_ids": set()},
            )
            item["experiment_ids"].add(experiment_id)

    # Cell keys retain Study and System. A Study with many systems still enters
    # the inferential test once, after a within-Study aggregation.
    cells: dict[tuple[Any, ...], dict[str, Any]] = {}
    numeric_points: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for experiment_id, outcome_groups in observations_by_experiment.items():
        experiment = experiments[experiment_id]
        study_id = str(experiment["study_id"])
        system_id = str(experiment["system_id"])
        for outcome_key, entries in outcome_groups.items():
            experiment_median = _median([item[0] for item in entries])
            if experiment_median is None:
                continue
            observation_ids = sorted({item[1] for item in entries if item[1]})
            for condition_base, (level_label, raw_level, level_number) in experiment_conditions.get(experiment_id, {}).items():
                key = (outcome_key, condition_base, level_label, study_id, system_id)
                cell = cells.setdefault(key, {
                    "values": [], "experiment_ids": set(), "observation_ids": set(),
                    "condition_value": raw_level, "condition_number": level_number,
                })
                cell["values"].append(experiment_median)
                cell["experiment_ids"].add(experiment_id)
                cell["observation_ids"].update(observation_ids)
                if level_number is not None:
                    numeric_points[(outcome_key, condition_base, study_id, system_id)].append({
                        "x": level_number,
                        "y": experiment_median,
                        "experiment_id": experiment_id,
                        "observation_ids": observation_ids,
                    })

    by_base: dict[tuple[Any, ...], dict[str, dict[str, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    for (outcome_key, condition_base, level_label, study_id, system_id), cell in cells.items():
        by_base[(outcome_key, condition_base)][level_label][study_id][system_id] = cell

    contrast_rows: list[dict[str, Any]] = []
    correlation_rows: list[dict[str, Any]] = []
    condition_level_support_rows: list[dict[str, Any]] = []
    categorical_level_count_excluded = 0
    raw_opportunities: list[dict[str, Any]] = []

    # Exclude structural self-relations before tests and BH family construction.
    self_association_exclusions: list[dict[str, Any]] = []
    for base_key, levels_by_label in list(by_base.items()):
        outcome_key, condition_base = base_key
        target_id, endpoint, timepoint, outcome_unit = outcome_key
        condition_type, condition_unit = condition_base
        reason = _self_association_reason(
            target_id, condition_type, outcome_unit, condition_unit, levels_by_label,
            target_metadata=target_semantic_index.get(target_id),
            condition_metadata=condition_semantic_index.get(condition_type),
        )
        if reason is None:
            continue
        experiment_ids = {
            exp for study_levels in levels_by_label.values()
            for systems_by_study in study_levels.values()
            for cell in systems_by_study.values() for exp in cell["experiment_ids"]
        }
        observation_ids = {
            obs for study_levels in levels_by_label.values()
            for systems_by_study in study_levels.values()
            for cell in systems_by_study.values() for obs in cell["observation_ids"]
        }
        system_ids = {
            system for study_levels in levels_by_label.values()
            for systems_by_study in study_levels.values() for system in systems_by_study
        }
        study_ids = {
            study for study_levels in levels_by_label.values() for study in study_levels
        }
        self_association_exclusions.append({
            "exclusion_id": "SELF-" + hashlib.sha256(_label(base_key).encode("utf-8")).hexdigest()[:12].upper(),
            "exclusion_reason": reason,
            "target_id": target_id,
            "endpoint_definition": endpoint,
            "timepoint": timepoint,
            "outcome_unit": outcome_unit,
            "condition_type": condition_type,
            "condition_unit": condition_unit,
            "semantic_review": _semantic_review(
                target_id, condition_type,
                target_semantic_index.get(target_id),
                condition_semantic_index.get(condition_type),
            ),
            "independent_study_count": len(study_ids),
            "system_count": len(system_ids),
            "experiment_count": len(experiment_ids),
            "observation_count": len(observation_ids),
            "analysis_families_excluded": [
                "CONDITION_OUTCOME_PAIRED_STUDY_SYSTEM_CONTRAST",
                "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST",
                "CONDITION_OUTCOME_WITHIN_SYSTEM_SPEARMAN",
                "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN",
            ],
            "admission_status": "EXCLUDED_FROM_SCIENTIFIC_OPPORTUNITIES_AND_FDR",
        })
        del by_base[base_key]

    for base_key, levels_by_label in sorted(by_base.items(), key=lambda item: _label(item[0])):
        outcome_key, condition_base = base_key
        target_id, endpoint, timepoint, outcome_unit = outcome_key
        condition_type, condition_unit = condition_base
        labels = sorted(levels_by_label)
        for label in labels:
            study_levels = levels_by_label[label]
            condition_level_support_rows.append({
                "target_id": target_id,
                "endpoint_definition": endpoint,
                "timepoint": timepoint,
                "outcome_unit": outcome_unit,
                "condition_type": condition_type,
                "condition_unit": condition_unit,
                "condition_level": label,
                "study_count": len(study_levels),
                "system_count": len({system for systems_by_study in study_levels.values() for system in systems_by_study}),
                "experiment_count": len({experiment for systems_by_study in study_levels.values() for cell in systems_by_study.values() for experiment in cell["experiment_ids"]}),
            })
        level_study_counts = {
            label: len(levels_by_label[label]) for label in labels
        }
        numeric_levels = {
            levels_by_label[label][study_id][system_id]["condition_number"]
            for label in labels
            for study_id in levels_by_label[label]
            for system_id in levels_by_label[label][study_id]
            if levels_by_label[label][study_id][system_id]["condition_number"] is not None
        }
        all_levels_numeric = all(
            levels_by_label[label][study_id][system_id]["condition_number"] is not None
            for label in labels
            for study_id in levels_by_label[label]
            for system_id in levels_by_label[label][study_id]
        )
        if all_levels_numeric:
            numeric_level_by_label = {
                label: next(
                    levels_by_label[label][study_id][system_id]["condition_number"]
                    for study_id in sorted(levels_by_label[label])
                    for system_id in sorted(levels_by_label[label][study_id])
                )
                for label in labels
            }
            labels = sorted(labels, key=lambda label: (numeric_level_by_label[label], label))
        else:
            # Nominal labels have no inferred scientific order. Their stable
            # serialized order only defines the signed b-minus-a contrast.
            labels = sorted(labels)
        use_numeric_trend = all_levels_numeric and len(numeric_levels) >= 3

        if use_numeric_trend:
            study_effects = []
            for study_id in sorted({key[2] for key in numeric_points if key[0] == outcome_key and key[1] == condition_base}):
                system_rhos = []
                supporting_experiments: set[str] = set()
                supporting_observations: set[str] = set()
                supporting_systems: set[str] = set()
                for (point_outcome, point_condition, point_study, system_id), points in numeric_points.items():
                    if point_outcome != outcome_key or point_condition != condition_base or point_study != study_id:
                        continue
                    rho = _spearman([item["x"] for item in points], [item["y"] for item in points])
                    if rho is None:
                        continue
                    system_rhos.append(rho)
                    supporting_systems.add(system_id)
                    for item in points:
                        supporting_experiments.add(item["experiment_id"])
                        supporting_observations.update(item["observation_ids"])
                study_rho = _median(system_rhos)
                if study_rho is not None:
                    study_effects.append({
                        "study_id": study_id,
                        "study_spearman_rho": study_rho,
                        "eligible_system_count": len(system_rhos),
                        "supporting_system_ids": sorted(supporting_systems),
                        "supporting_experiment_ids": sorted(supporting_experiments),
                        "supporting_observation_ids": sorted(supporting_observations),
                    })
            rhos = [item["study_spearman_rho"] for item in study_effects]
            p_value = _sign_test_p(rhos) if len(rhos) >= minimum_paired_studies else None
            identity = ["SPEARMAN", outcome_key, condition_base]
            effect = _median(rhos)
            ci = _bootstrap_median_ci(rhos, bootstrap_iterations, _stable_seed(seed, identity))
            correlation_rows.append({
                "analysis_family": "CONDITION_OUTCOME_WITHIN_SYSTEM_SPEARMAN",
                "target_id": target_id,
                "endpoint_definition": endpoint,
                "timepoint": timepoint,
                "outcome_unit": outcome_unit,
                "condition_type": condition_type,
                "condition_unit": condition_unit,
                "independent_study_count": len(rhos),
                "system_correlation_count": sum(item["eligible_system_count"] for item in study_effects),
                "experiment_count": len({exp for item in study_effects for exp in item["supporting_experiment_ids"]}),
                "observation_count": len({obs for item in study_effects for obs in item["supporting_observation_ids"]}),
                "median_study_spearman_rho": effect,
                "study_spearman_ci95": ci,
                "positive_study_count": sum(value > 0 for value in rhos),
                "negative_study_count": sum(value < 0 for value in rhos),
                "zero_study_count": sum(value == 0 for value in rhos),
                "p_value": p_value,
                "q_value": None,
                "study_effects": study_effects,
                "interpretation_status": "WITHIN_STUDY_SYSTEM_RANK_ASSOCIATION_CANDIDATE_NOT_CAUSAL",
            })
            row = correlation_rows[-1]
            if len(rhos) >= minimum_paired_studies:
                opp_id = _opportunity_id(identity)
                raw_opportunities.append({
                    "schema_version": "1.0",
                    "opportunity_id": opp_id,
                    "analysis_family": row["analysis_family"],
                    "signal_type": "WITHIN_STUDY_SYSTEM_NUMERIC_CONDITION_TREND",
                    "target_id": target_id,
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "outcome_unit": outcome_unit,
                    "condition_type": condition_type,
                    "condition_unit": condition_unit,
                    "condition_levels": sorted(numeric_levels),
                    "independent_study_count": len(rhos),
                    "effect_size": effect,
                    "confidence_interval_95": ci,
                    "p_value": p_value,
                    "q_value": None,
                    "study_effects": study_effects,
                    "supporting_studies": sorted(item["study_id"] for item in study_effects),
                    "supporting_signals": [opp_id],
                    "scientific_question": (
                        f"Within independent Studies and comparable Systems, is canonical target "
                        f"'{target_id}' ({endpoint}; timepoint {timepoint}; {outcome_unit}) associated "
                        f"with the reported numeric condition '{condition_type}' ({condition_unit})?"
                    ),
                    "hypothesis": (
                        "The condition/outcome rank association has a consistent direction across independent Studies; "
                        "this is a screening hypothesis, not a causal claim."
                    ),
                    "semantic_status": "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
                    "identifiability": "WITHIN_STUDY_AND_WITHIN_SYSTEM_EXPERIMENT_LEVEL_RANK_ASSOCIATION",
                    "limitations": [
                        "Target and condition identifiers are not interpreted or renamed by this engine.",
                        "Each Study contributes at most one median correlation, regardless of its Observation count.",
                        "Only Systems with at least four eligible Experiments and at least three distinct condition values contribute.",
                        "The sign test evaluates cross-Study direction consistency; it does not establish causality or remove unmeasured confounding.",
                        "No implicit unit conversion, timepoint merging, or extrapolation is performed."
                    ],
                    "evidence_refs": study_effects,
                })

        # Categorical and two-level numeric conditions are screened as within-
        # Study/System paired contrasts. More than one system in a Study is first
        # summarized to a single Study-level effect.
        else:
            if len(labels) < 2:
                continue
            screened_labels = labels
            if len(labels) > maximum_levels_per_condition:
                screened_labels = sorted(
                    labels,
                    key=lambda label: (-level_study_counts[label], label),
                )[:maximum_levels_per_condition]
                categorical_level_count_excluded += len(labels) - len(screened_labels)
            for label_a, label_b in itertools.combinations(screened_labels, 2):
                studies_a = levels_by_label[label_a]
                studies_b = levels_by_label[label_b]
                eligible_level_a = len(studies_a)
                eligible_level_b = len(studies_b)
                if min(eligible_level_a, eligible_level_b) < 2:
                    continue
                study_effects = []
                for study_id in sorted(set(studies_a) & set(studies_b)):
                    systems_a = studies_a[study_id]
                    systems_b = studies_b[study_id]
                    paired_systems = sorted(set(systems_a) & set(systems_b))
                    system_differences = []
                    paired_experiments: set[str] = set()
                    paired_observations: set[str] = set()
                    for system_id in paired_systems:
                        cell_a = systems_a[system_id]
                        cell_b = systems_b[system_id]
                        median_a = _median(cell_a["values"])
                        median_b = _median(cell_b["values"])
                        if median_a is None or median_b is None:
                            continue
                        system_differences.append(median_b - median_a)
                        paired_experiments.update(cell_a["experiment_ids"])
                        paired_experiments.update(cell_b["experiment_ids"])
                        paired_observations.update(cell_a["observation_ids"])
                        paired_observations.update(cell_b["observation_ids"])
                    if not system_differences:
                        continue
                    study_effects.append({
                        "study_id": study_id,
                        "level_a_median": _median([
                            _median(systems_a[system]["values"]) for system in paired_systems
                            if system in systems_a and systems_a[system]["values"]
                        ]),
                        "level_b_median": _median([
                            _median(systems_b[system]["values"]) for system in paired_systems
                            if system in systems_b and systems_b[system]["values"]
                        ]),
                        "median_paired_system_difference_b_minus_a": _median(system_differences),
                        "paired_system_count": len(system_differences),
                        "supporting_system_ids": paired_systems,
                        "supporting_experiment_ids": sorted(paired_experiments),
                        "supporting_observation_ids": sorted(paired_observations),
                    })
                differences = [item["median_paired_system_difference_b_minus_a"] for item in study_effects]
                p_value = _sign_test_p(differences) if len(differences) >= minimum_paired_studies else None
                identity = ["PAIRED_CONTRAST", outcome_key, condition_base, label_a, label_b]
                effect = _median(differences)
                ci = _bootstrap_median_ci(differences, bootstrap_iterations, _stable_seed(seed, identity))
                contrast_rows.append({
                    "analysis_family": "CONDITION_OUTCOME_PAIRED_STUDY_SYSTEM_CONTRAST",
                    "target_id": target_id,
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "outcome_unit": outcome_unit,
                    "condition_type": condition_type,
                    "condition_unit": condition_unit,
                    "level_a": label_a,
                    "level_b": label_b,
                    "contrast_orientation": "NUMERIC_ASCENDING" if all_levels_numeric else "SERIALIZED_LABEL_ORDER",
                    "level_a_study_count": eligible_level_a,
                    "level_b_study_count": eligible_level_b,
                    "paired_study_count": len(differences),
                    "paired_system_count": sum(item["paired_system_count"] for item in study_effects),
                    "experiment_count": len({exp for item in study_effects for exp in item["supporting_experiment_ids"]}),
                    "observation_count": len({obs for item in study_effects for obs in item["supporting_observation_ids"]}),
                    "median_study_difference_b_minus_a": effect,
                    "study_difference_ci95": ci,
                    "positive_study_count": sum(value > 0 for value in differences),
                    "negative_study_count": sum(value < 0 for value in differences),
                    "zero_study_count": sum(value == 0 for value in differences),
                    "p_value": p_value,
                    "q_value": None,
                    "study_effects": study_effects,
                    "interpretation_status": "WITHIN_STUDY_SYSTEM_DESCRIPTIVE_CONTRAST",
                })
                row = contrast_rows[-1]
                opp_id = _opportunity_id(identity)
                raw_opportunities.append({
                    "schema_version": "1.0",
                    "opportunity_id": opp_id,
                    "analysis_family": row["analysis_family"],
                    "signal_type": "WITHIN_STUDY_SYSTEM_CONDITION_OUTCOME_CONTRAST",
                    "target_id": target_id,
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "outcome_unit": outcome_unit,
                    "condition_type": condition_type,
                    "condition_unit": condition_unit,
                    "level_a": label_a,
                    "level_b": label_b,
                    "contrast_orientation": "NUMERIC_ASCENDING" if all_levels_numeric else "SERIALIZED_LABEL_ORDER",
                    "independent_study_count": len(differences),
                    "effect_size": effect,
                    "confidence_interval_95": ci,
                    "p_value": p_value,
                    "q_value": None,
                    "study_effects": study_effects,
                    "supporting_studies": sorted(item["study_id"] for item in study_effects),
                    "supporting_signals": [opp_id],
                    "scientific_question": (
                        f"Within independent Studies and comparable Systems, does condition "
                        f"'{condition_type}' ({condition_unit}) at level {label_b} versus {label_a} "
                        f"correspond to a difference in canonical target '{target_id}' "
                        f"({endpoint}; timepoint {timepoint}; {outcome_unit})?"
                    ),
                    "hypothesis": (
                        "The within-Study/System contrast has a consistent direction across independent Studies; "
                        "it is a candidate association and not a causal effect."
                    ),
                    "semantic_status": "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
                    "identifiability": "WITHIN_STUDY_AND_WITHIN_SYSTEM_PAIRED_CONTRAST",
                    "limitations": [
                        "Target and condition identifiers are not interpreted or renamed by this engine.",
                        "Each Study contributes at most one median paired effect, regardless of its Observation count.",
                        "A System contributes only when both condition levels are present in that same System.",
                        "The exact sign test evaluates cross-Study direction consistency; effect magnitude uncertainty uses Study bootstrap.",
                        "Confounding, protocol differences, and measurement comparability still require scientific review.",
                        "No implicit unit conversion, timepoint merging, or causal inference is performed."
                    ],
                    "evidence_refs": study_effects,
                })

    # Between-System, within-Study screens are distinct from paired within-
    # System screens. They are enabled when the Canonical grain contains one
    # Experiment per System, but are explicitly labelled cross-sectional and
    # retain system-composition confounding as a limitation.
    between_system_numeric_group_count = 0
    between_system_numeric_eligible_study_count = 0
    between_system_categorical_pair_count = 0
    between_system_categorical_eligible_study_count = 0
    for base_key, levels_by_label in sorted(by_base.items(), key=lambda item: _label(item[0])):
        outcome_key, condition_base = base_key
        target_id, endpoint, timepoint, outcome_unit = outcome_key
        condition_type, condition_unit = condition_base
        labels = sorted(levels_by_label)
        level_numbers: dict[str, float | None] = {}
        level_study_counts = {label: len(levels_by_label[label]) for label in labels}
        for label in labels:
            first_cell = next(
                levels_by_label[label][study_id][system_id]
                for study_id in sorted(levels_by_label[label])
                for system_id in sorted(levels_by_label[label][study_id])
            )
            level_numbers[label] = first_cell["condition_number"]
        all_numeric = all(value is not None for value in level_numbers.values())
        numeric_levels = {value for value in level_numbers.values() if value is not None}
        if all_numeric:
            labels = sorted(labels, key=lambda label: (level_numbers[label], label))

        # A System is eligible for the between-System screen only when it
        # contributes exactly one condition level for this outcome/condition
        # within this Study. Systems with repeated levels remain available to
        # the separate within-System analysis above.
        labels_by_study_system: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for label in labels:
            for study_id, systems_by_study in levels_by_label[label].items():
                for system_id in systems_by_study:
                    labels_by_study_system[study_id][system_id].append(label)
        eligible_cells: dict[str, dict[str, tuple[str, dict[str, Any]]]] = defaultdict(dict)
        for study_id, systems_by_study in labels_by_study_system.items():
            for system_id, system_labels in systems_by_study.items():
                if len(system_labels) != 1:
                    continue
                label = system_labels[0]
                eligible_cells[study_id][system_id] = (
                    label, levels_by_label[label][study_id][system_id]
                )

        use_between_system_numeric = all_numeric and len(numeric_levels) >= 3
        if use_between_system_numeric:
            between_system_numeric_group_count += 1
            study_effects = []
            for study_id in sorted(eligible_cells):
                points = []
                for system_id, (label, cell) in sorted(eligible_cells[study_id].items()):
                    x_value = level_numbers[label]
                    y_value = _median(cell["values"])
                    if x_value is None or y_value is None:
                        continue
                    points.append({
                        "x": x_value, "y": y_value,
                        "condition_value": float(x_value),
                        "outcome_median": float(y_value),
                        "system_id": system_id,
                        "experiment_ids": sorted(cell["experiment_ids"]),
                        "observation_ids": sorted(cell["observation_ids"]),
                    })
                rho = _spearman(
                    [item["x"] for item in points],
                    [item["y"] for item in points],
                )
                if rho is None:
                    continue
                study_effects.append({
                    "study_id": study_id,
                    "study_spearman_rho": rho,
                    "eligible_system_count": len(points),
                    "system_points": [
                        {
                            "system_id": item["system_id"],
                            "condition_value": item["condition_value"],
                            "outcome_median": item["outcome_median"],
                            "supporting_experiment_ids": item["experiment_ids"],
                            "supporting_observation_ids": item["observation_ids"],
                        }
                        for item in points
                    ],
                    "supporting_system_ids": sorted(item["system_id"] for item in points),
                    "supporting_experiment_ids": sorted({
                        experiment for item in points for experiment in item["experiment_ids"]
                    }),
                    "supporting_observation_ids": sorted({
                        observation for item in points for observation in item["observation_ids"]
                    }),
                })
            if study_effects:
                between_system_numeric_eligible_study_count += len(study_effects)
                confounding_review = _screen_recorded_condition_covariates(
                    study_effects, condition_base, target_id, system_condition_values
                )
                rhos = [item["study_spearman_rho"] for item in study_effects]
                p_value = _sign_test_p(rhos) if len(rhos) >= minimum_paired_studies else None
                identity = ["BETWEEN_SYSTEM_SPEARMAN", outcome_key, condition_base]
                effect = _median(rhos)
                ci = _bootstrap_median_ci(rhos, bootstrap_iterations, _stable_seed(seed, identity))
                correlation_rows.append({
                    "analysis_family": "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN",
                    "target_id": target_id,
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "outcome_unit": outcome_unit,
                    "condition_type": condition_type,
                    "condition_unit": condition_unit,
                    "independent_study_count": len(rhos),
                    "system_correlation_count": sum(item["eligible_system_count"] for item in study_effects),
                    "experiment_count": len({exp for item in study_effects for exp in item["supporting_experiment_ids"]}),
                    "observation_count": len({obs for item in study_effects for obs in item["supporting_observation_ids"]}),
                    "median_study_spearman_rho": effect,
                    "study_spearman_ci95": ci,
                    "positive_study_count": sum(value > 0 for value in rhos),
                    "negative_study_count": sum(value < 0 for value in rhos),
                    "zero_study_count": sum(value == 0 for value in rhos),
                    "p_value": p_value,
                    "q_value": None,
                    "study_effects": study_effects,
                    "confounding_review": confounding_review,
                    "interpretation_status": "BETWEEN_SYSTEM_WITHIN_STUDY_RANK_ASSOCIATION_CANDIDATE_NOT_CAUSAL",
                })
                if len(rhos) >= minimum_paired_studies:
                    opp_id = _opportunity_id(identity)
                    raw_opportunities.append({
                        "schema_version": "1.0",
                        "opportunity_id": opp_id,
                        "analysis_family": "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN",
                        "signal_type": "WITHIN_STUDY_BETWEEN_SYSTEM_NUMERIC_CONDITION_TREND",
                        "target_id": target_id,
                        "endpoint_definition": endpoint,
                        "timepoint": timepoint,
                        "outcome_unit": outcome_unit,
                        "condition_type": condition_type,
                        "condition_unit": condition_unit,
                        "condition_levels": sorted(numeric_levels),
                        "independent_study_count": len(rhos),
                        "effect_size": effect,
                        "confidence_interval_95": ci,
                        "p_value": p_value,
                        "q_value": None,
                        "study_effects": study_effects,
                        "confounding_review": confounding_review,
                        "supporting_studies": sorted(item["study_id"] for item in study_effects),
                        "supporting_signals": [opp_id],
                        "scientific_question": (
                            f"Within independent Studies, across distinct canonical Systems, is "
                            f"canonical target '{target_id}' ({endpoint}; timepoint {timepoint}; {outcome_unit}) "
                            f"associated with the reported numeric condition '{condition_type}' ({condition_unit})?"
                        ),
                        "hypothesis": (
                            "The between-System condition/outcome rank association has a consistent direction "
                            "across independent Studies; this is cross-sectional screening, not a causal claim."
                        ),
                        "semantic_status": "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
                        "identifiability": "WITHIN_STUDY_BETWEEN_SYSTEM_CROSS_SECTIONAL_RANK_ASSOCIATION",
                        "limitations": [
                            "Each Study contributes at most one Spearman correlation across eligible Systems.",
                            "Systems with more than one condition level are excluded from this between-System screen and remain eligible for within-System analysis.",
                            "Differences in chemistry, composition, protocol, and laboratory between Systems may confound the association.",
                            "The cross-Study sign test screens direction consistency; it does not establish causality or remove system-level confounding.",
                            "Target and condition identifiers are not interpreted, and no unit conversion or timepoint merging is performed.",
                        ],
                        "evidence_refs": study_effects,
                    })

        elif len(labels) >= 2:
            screened_labels = labels
            if len(labels) > maximum_levels_per_condition:
                screened_labels = sorted(
                    labels, key=lambda label: (-level_study_counts[label], label)
                )[:maximum_levels_per_condition]
            for label_a, label_b in itertools.combinations(screened_labels, 2):
                between_system_categorical_pair_count += 1
                study_effects = []
                for study_id in sorted(eligible_cells):
                    group_a = []
                    group_b = []
                    for system_id, (label, cell) in sorted(eligible_cells[study_id].items()):
                        system_value = _median(cell["values"])
                        if system_value is None:
                            continue
                        point = {
                            "system_id": system_id,
                            "outcome_median": system_value,
                            "experiment_ids": sorted(cell["experiment_ids"]),
                            "observation_ids": sorted(cell["observation_ids"]),
                        }
                        if label == label_a:
                            group_a.append(point)
                        elif label == label_b:
                            group_b.append(point)
                    # Require replicated Systems in both groups within a Study.
                    if len(group_a) < 2 or len(group_b) < 2:
                        continue
                    median_a = _median([item["outcome_median"] for item in group_a])
                    median_b = _median([item["outcome_median"] for item in group_b])
                    if median_a is None or median_b is None:
                        continue
                    study_effects.append({
                        "study_id": study_id,
                        "level_a_median": median_a,
                        "level_b_median": median_b,
                        "median_between_system_difference_b_minus_a": median_b - median_a,
                        "level_a_system_ids": sorted(item["system_id"] for item in group_a),
                        "level_b_system_ids": sorted(item["system_id"] for item in group_b),
                        "level_a_system_count": len(group_a),
                        "level_b_system_count": len(group_b),
                        "supporting_system_ids": sorted(
                            {item["system_id"] for item in group_a + group_b}
                        ),
                        "supporting_experiment_ids": sorted({
                            experiment for item in group_a + group_b for experiment in item["experiment_ids"]
                        }),
                        "supporting_observation_ids": sorted({
                            observation for item in group_a + group_b for observation in item["observation_ids"]
                        }),
                    })
                if not study_effects:
                    continue
                between_system_categorical_eligible_study_count += len(study_effects)
                differences = [
                    item["median_between_system_difference_b_minus_a"]
                    for item in study_effects
                ]
                p_value = _sign_test_p(differences) if len(differences) >= minimum_paired_studies else None
                identity = ["BETWEEN_SYSTEM_CONTRAST", outcome_key, condition_base, label_a, label_b]
                effect = _median(differences)
                ci = _bootstrap_median_ci(differences, bootstrap_iterations, _stable_seed(seed, identity))
                contrast_rows.append({
                    "analysis_family": "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST",
                    "target_id": target_id,
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "outcome_unit": outcome_unit,
                    "condition_type": condition_type,
                    "condition_unit": condition_unit,
                    "level_a": label_a,
                    "level_b": label_b,
                    "contrast_orientation": "NUMERIC_ASCENDING" if all_numeric else "SERIALIZED_LABEL_ORDER",
                    "independent_study_count": len(differences),
                    "level_a_system_count": sum(item["level_a_system_count"] for item in study_effects),
                    "level_b_system_count": sum(item["level_b_system_count"] for item in study_effects),
                    "paired_study_count": 0,
                    "paired_system_count": 0,
                    "experiment_count": len({exp for item in study_effects for exp in item["supporting_experiment_ids"]}),
                    "observation_count": len({obs for item in study_effects for obs in item["supporting_observation_ids"]}),
                    "median_study_difference_b_minus_a": effect,
                    "study_difference_ci95": ci,
                    "positive_study_count": sum(value > 0 for value in differences),
                    "negative_study_count": sum(value < 0 for value in differences),
                    "zero_study_count": sum(value == 0 for value in differences),
                    "p_value": p_value,
                    "q_value": None,
                    "study_effects": study_effects,
                    "interpretation_status": "BETWEEN_SYSTEM_WITHIN_STUDY_CROSS_SECTIONAL_CONTRAST_CANDIDATE_NOT_CAUSAL",
                })
                if len(differences) >= minimum_paired_studies:
                    opp_id = _opportunity_id(identity)
                    raw_opportunities.append({
                        "schema_version": "1.0",
                        "opportunity_id": opp_id,
                        "analysis_family": "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST",
                        "signal_type": "WITHIN_STUDY_BETWEEN_SYSTEM_CONDITION_OUTCOME_CONTRAST",
                        "target_id": target_id,
                        "endpoint_definition": endpoint,
                        "timepoint": timepoint,
                        "outcome_unit": outcome_unit,
                        "condition_type": condition_type,
                        "condition_unit": condition_unit,
                        "level_a": label_a,
                        "level_b": label_b,
                        "contrast_orientation": "NUMERIC_ASCENDING" if all_numeric else "SERIALIZED_LABEL_ORDER",
                        "independent_study_count": len(differences),
                        "effect_size": effect,
                        "confidence_interval_95": ci,
                        "p_value": p_value,
                        "q_value": None,
                        "study_effects": study_effects,
                        "supporting_studies": sorted(item["study_id"] for item in study_effects),
                        "supporting_signals": [opp_id],
                        "scientific_question": (
                            f"Within independent Studies, do distinct canonical Systems assigned to "
                            f"condition '{condition_type}' ({condition_unit}) level {label_b} versus {label_a} "
                            f"differ in canonical target '{target_id}' ({endpoint}; timepoint {timepoint}; {outcome_unit})?"
                        ),
                        "hypothesis": (
                            "The between-System group contrast is directionally consistent across independent Studies; "
                            "this is cross-sectional association screening, not a causal effect."
                        ),
                        "semantic_status": "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
                        "identifiability": "WITHIN_STUDY_BETWEEN_SYSTEM_CROSS_SECTIONAL_CONTRAST",
                        "limitations": [
                            "Each Study contributes one difference between System-level group medians.",
                            "Both condition levels require at least two distinct Systems within a Study.",
                            "Differences in chemistry, composition, protocol, and laboratory between Systems may confound the contrast.",
                            "The exact sign test evaluates cross-Study direction consistency; it does not establish causality.",
                            "Target and condition identifiers are not interpreted, and no unit conversion or timepoint merging is performed.",
                        ],
                        "evidence_refs": study_effects,
                    })

    mirror_duplicates = _mark_exact_mirror_duplicates(correlation_rows)
    mirror_duplicate_ids = {
        opportunity_id
        for group in mirror_duplicates
        for opportunity_id in group["duplicate_opportunity_ids"]
    }
    opportunity_count_before_mirror_deduplication = len(raw_opportunities)
    raw_opportunities = [item for item in raw_opportunities if item["opportunity_id"] not in mirror_duplicate_ids]

    _apply_bh(contrast_rows, "CONDITION_OUTCOME_PAIRED_STUDY_SYSTEM_CONTRAST")
    _apply_bh(contrast_rows, "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST")
    _apply_bh(correlation_rows, "CONDITION_OUTCOME_WITHIN_SYSTEM_SPEARMAN")
    _apply_bh(correlation_rows, "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN")

    contrast_index = {
        (row["analysis_family"], row["target_id"], row["endpoint_definition"], row["timepoint"], row["outcome_unit"],
         row["condition_type"], row["condition_unit"], row["level_a"], row["level_b"]): row
        for row in contrast_rows
    }
    correlation_index = {
        (row["analysis_family"], row["target_id"], row["endpoint_definition"], row["timepoint"], row["outcome_unit"],
         row["condition_type"], row["condition_unit"]): row
        for row in correlation_rows
    }
    for opportunity in raw_opportunities:
        if "CONTRAST" in opportunity["analysis_family"]:
            key = (opportunity["analysis_family"], opportunity["target_id"], opportunity["endpoint_definition"],
                   opportunity["timepoint"], opportunity["outcome_unit"], opportunity["condition_type"],
                   opportunity["condition_unit"], opportunity["level_a"], opportunity["level_b"])
            tested = contrast_index[key]
        else:
            key = (opportunity["analysis_family"], opportunity["target_id"], opportunity["endpoint_definition"],
                   opportunity["timepoint"], opportunity["outcome_unit"], opportunity["condition_type"],
                   opportunity["condition_unit"])
            tested = correlation_index[key]
        opportunity["p_value"] = tested["p_value"]
        opportunity["q_value"] = tested["q_value"]
        q_value = tested["q_value"]
        if q_value is None:
            opportunity["screen_status"] = "DESCRIPTIVE_CANDIDATE_INSUFFICIENT_INDEPENDENT_STUDY_SUPPORT"
            opportunity["recommendation"] = "reserve"
        elif q_value <= fdr_alpha:
            opportunity["screen_status"] = "FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW"
            opportunity["recommendation"] = (
                "priority_1" if opportunity["independent_study_count"] >= 5 and q_value <= 0.05
                else "priority_2"
            )
        else:
            opportunity["screen_status"] = "NOT_FDR_SCREEN_POSITIVE_REQUIRES_REVIEW"
            opportunity["recommendation"] = "priority_3"
        opportunity["semantic_review"] = _semantic_review(
            opportunity["target_id"], opportunity["condition_type"],
            target_semantic_index.get(opportunity["target_id"]),
            condition_semantic_index.get(opportunity["condition_type"]),
        )
        opportunity["semantic_status"] = (
            "APPROVED_SEMANTIC_METADATA_AVAILABLE_FOR_DOMAIN_REVIEW"
            if opportunity["semantic_review"]["status"] == "APPROVED_METADATA_AVAILABLE_FOR_DOMAIN_REVIEW"
            else "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW"
        )
        if opportunity["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN":
            opportunity["confounding_review"] = correlation_index[(
                opportunity["analysis_family"], opportunity["target_id"], opportunity["endpoint_definition"],
                opportunity["timepoint"], opportunity["outcome_unit"], opportunity["condition_type"],
                opportunity["condition_unit"]
            )].get("confounding_review")
        elif "BETWEEN_SYSTEM" in opportunity["analysis_family"]:
            opportunity["confounding_review"] = {
                "status": "STRUCTURED_COVARIATE_SCREEN_NOT_AVAILABLE_FOR_THIS_ANALYSIS_FAMILY",
                "unassessed_confounder_domains": [
                    "System/material/composition descriptors",
                    "Protocol, laboratory, synthesis, measurement and batch effects",
                    "Unmeasured or incompletely reported variables",
                ],
            }
        else:
            opportunity["confounding_review"] = {
                "status": "WITHIN_SYSTEM_DESIGN_STILL_REQUIRES_DOMAIN_REVIEW",
                "unassessed_confounder_domains": [
                    "Time-varying protocol and batch effects",
                    "Unmeasured or incompletely reported variables",
                ],
            }
        opportunity["novelty_status"] = "targeted_literature_review_pending"
        opportunity["scientific_significance"] = (
            "A reproducible cross-Study pattern may help prioritize a focused research question; "
            "scientific meaning depends on approved target/condition semantics and domain review."
        )
        opportunity["data_feasibility"] = (
            f"{opportunity['independent_study_count']} independent Studies contribute; "
            "Study-level support, not flattened Observation count, determines this number."
        )
        opportunity["confounding_risks"] = [
            "Unmeasured protocol, composition, laboratory, and system-level differences may remain.",
            "Canonical linkage quality and endpoint comparability depend on the approved upstream mapping.",
        ]
        opportunity["robustness_requirements"] = [
            "Review target and condition semantics and exact unit compatibility.",
            "Inspect each Study/System evidence row and counterexamples.",
            "Repeat after excluding individual Studies and compare direction consistency.",
            "Check endpoint definition and timepoint comparability before formal modelling.",
        ]
        opportunity["proposed_methods"] = [
            "Study-aware descriptive replication",
            "Within-System paired contrasts where repeated condition levels exist",
            "Within-Study between-System cross-sectional contrasts/trends, with explicit system-composition confounding review",
            "Study-grouped validation after the user approves a research scope",
        ]
        opportunity["expected_scientific_contribution"] = (
            "Prioritize a data-supported association question and identify the independent Studies "
            "and Systems needed for focused validation."
        )
        opportunity["experimental_validation_requirements"] = [
            "Independent experiments designed to isolate the selected condition while controlling other variables.",
            "Predefine the outcome endpoint, timepoint, and measurement protocol.",
        ]
        opportunity["supporting_signals"] = opportunity["supporting_signals"]
        study_effect_values = [
            item.get(
                "median_paired_system_difference_b_minus_a",
                item.get("median_between_system_difference_b_minus_a", item.get("study_spearman_rho")),
            )
            for item in opportunity["study_effects"]
        ]
        opportunity_effect = opportunity.get("effect_size")
        pooled_direction = 1 if (opportunity_effect or 0) > 0 else (-1 if (opportunity_effect or 0) < 0 else 0)
        opportunity["counterexamples"] = [
            item["study_id"]
            for item, study_value in zip(opportunity["study_effects"], study_effect_values)
            if study_value == 0 or (pooled_direction != 0 and study_value * pooled_direction < 0)
        ]
        opportunity["evidence_feasibility"] = {
            "study_count": opportunity["independent_study_count"],
            "system_count": len({
                system for item in opportunity["study_effects"]
                for system in (
                    item.get("supporting_system_ids", [])
                    or item.get("level_a_system_ids", []) + item.get("level_b_system_ids", [])
                )
            }),
            "experiment_count": sum(len(item.get("supporting_experiment_ids", [])) for item in opportunity["study_effects"]),
            "observation_count": sum(len(item.get("supporting_observation_ids", [])) for item in opportunity["study_effects"]),
        }

    raw_opportunities.sort(key=lambda item: (
        0 if item["q_value"] is not None and item["q_value"] <= fdr_alpha else 1,
        item["q_value"] if item["q_value"] is not None else 1.0,
        -item["independent_study_count"],
        item["opportunity_id"],
    ))
    opportunities = raw_opportunities[:maximum_opportunities]
    for opportunity in opportunities:
        opportunity["related_group_ids"] = []
    related_opportunity_groups = _related_opportunity_groups(opportunities, correlation_rows)

    signals = []
    evidence_ledger = []
    for opportunity in opportunities:
        signals.append({
            "signal_id": opportunity["opportunity_id"],
            "signal_type": opportunity["signal_type"],
            "target_id": opportunity["target_id"],
            "condition_type": opportunity["condition_type"],
            "supporting_study_count": opportunity["independent_study_count"],
            "effect_size": opportunity["effect_size"],
            "p_value": opportunity["p_value"],
            "q_value": opportunity["q_value"],
            "screen_status": opportunity["screen_status"],
            "interpretation_status": "CANDIDATE_ONLY_REQUIRES_DOMAIN_REVIEW_NOT_CAUSAL",
        })
        for study_effect in opportunity["evidence_refs"]:
            evidence_ledger.append({
                "opportunity_id": opportunity["opportunity_id"],
                "analysis_family": opportunity["analysis_family"],
                **study_effect,
            })

    profile = {
        "engine_version": ENGINE_VERSION,
        "analysis_unit": "INDEPENDENT_STUDY",
        "minimum_paired_studies": minimum_paired_studies,
        "fdr_method": "BENJAMINI_HOCHBERG_WITHIN_ANALYSIS_FAMILY",
        "fdr_alpha": fdr_alpha,
        "bootstrap_iterations": bootstrap_iterations,
        "seed": seed,
        "numeric_observation_count_used": reported_numeric_count,
        "ambiguous_condition_experiment_assignments_excluded": ambiguous_assignments,
        "paired_contrast_test_count": sum(row["analysis_family"] == "CONDITION_OUTCOME_PAIRED_STUDY_SYSTEM_CONTRAST" for row in contrast_rows),
        "between_system_contrast_test_count": sum(row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST" for row in contrast_rows),
        "numeric_trend_test_count": len(correlation_rows),
        "numeric_trend_fdr_test_count": sum(
            row.get("p_value") is not None and not row.get("mirror_duplicate_of_opportunity_id")
            for row in correlation_rows
        ),
        "within_system_numeric_trend_test_count": sum(row["analysis_family"] == "CONDITION_OUTCOME_WITHIN_SYSTEM_SPEARMAN" for row in correlation_rows),
        "between_system_numeric_trend_test_count": sum(row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN" for row in correlation_rows),
        "between_system_numeric_group_count": between_system_numeric_group_count,
        "between_system_numeric_eligible_study_count": between_system_numeric_eligible_study_count,
        "between_system_categorical_pair_count": between_system_categorical_pair_count,
        "between_system_categorical_eligible_study_count": between_system_categorical_eligible_study_count,
        "maximum_levels_per_condition": maximum_levels_per_condition,
        "condition_level_count_total": len(condition_level_support_rows),
        "categorical_level_count_excluded_from_pairwise_screen": categorical_level_count_excluded,
        "self_association_exclusion_count": len(self_association_exclusions),
        "self_association_exclusion_reason_counts": {
            reason: sum(item["exclusion_reason"] == reason for item in self_association_exclusions)
            for reason in sorted({item["exclusion_reason"] for item in self_association_exclusions})
        },
        "opportunity_count_before_mirror_deduplication": opportunity_count_before_mirror_deduplication,
        "mirror_duplicate_opportunity_count": len(mirror_duplicate_ids),
        "mirror_duplicate_group_count": len(mirror_duplicates),
        "related_opportunity_group_count": len(related_opportunity_groups),
        "opportunity_count_before_limit": len(raw_opportunities),
        "opportunity_count_written": len(opportunities),
        "fdr_screen_positive_count": sum(
            item["q_value"] is not None and item["q_value"] <= fdr_alpha for item in opportunities
        ),
        "semantic_policy": "IDENTIFIERS_RETAINED; NO_AUTOMATIC_TARGET_OR_CONDITION_INTERPRETATION",
        "semantic_registry": semantic_registry_summary,
    }
    limitations = [
        "The independent inferential unit is Study; Observation rows are aggregated within Experiment, System, and Study before cross-Study tests.",
        "Condition contrasts require the same canonical System to contain both levels within a Study.",
        "Numeric-condition trends use a separate Spearman correlation within each Study/System and combine one median rho per Study.",
        "Two-sided exact sign tests assess consistency across independent Studies; Benjamini-Hochberg q-values are calculated separately by analysis family.",
        "Bootstrap intervals resample independent Study effects; they do not account for all upstream measurement or mapping uncertainty.",
        "The screen is observational and exploratory. It cannot establish causality, mechanisms, novelty, or experimental validity.",
        "Target IDs, endpoint definitions, and condition labels are not assigned scientific meanings by this engine.",
        "No implicit unit conversion, endpoint merging, timepoint merging, missing-value imputation, or condition conflict resolution is performed.",
    ]
    return {
        "profile": profile,
        "contrasts": contrast_rows,
        "correlations": correlation_rows,
        "condition_level_support": condition_level_support_rows,
        "opportunities": opportunities,
        "signals": signals,
        "evidence_ledger": evidence_ledger,
        "self_association_exclusions": self_association_exclusions,
        "mirror_duplicates": mirror_duplicates,
        "related_opportunity_groups": related_opportunity_groups,
        "limitations": limitations + [
            "Exact reciprocal between-System rank relations are deduplicated only when canonical identifiers, endpoint/timepoint, cross-matched exact unit strings, Study/System support, Experiment support, and every per-System value pair prove an exact mirror. When the same reciprocal data pattern differs in endpoint or timepoint, it is grouped for domain review while all hypotheses and BH-FDR entries remain distinct.",
            "Canonical identifiers are compared exactly; case-folding, punctuation removal, and other identifier normalization are prohibited for identity or dependency decisions.",
            "Optional semantic_metadata is used only when consistently supplied and explicitly marked APPROVED; identifier-only or incomplete semantics remain unresolved and require domain review.",
            "Recorded numeric Condition covariates with exact monotonic co-variation are flagged as potential co-exposures; this is not an adjusted model and unstructured/unmeasured confounders remain unassessed.",
            "Canonical target/condition identity and exact same-unit value identity are excluded before inferential testing and FDR correction.",
            "Perfect correlation alone is not treated as proof of self-association; broader deterministic derivation requires explicit provenance metadata and human review.",
        ],
    }
