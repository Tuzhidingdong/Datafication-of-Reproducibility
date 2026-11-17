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

ENGINE_VERSION = "1.0.0"


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
    """Normalize an identifier only for conservative same-attribute detection."""
    return "".join(character for character in str(value or "") if character.isalnum()).casefold()


def _self_association_reason(
    target_id: str,
    condition_type: str,
    outcome_unit: str,
    condition_unit: str,
    levels_by_label: dict[str, dict[str, dict[str, dict[str, Any]]]],
) -> str | None:
    """Return a reason only for explicit identity, never for mere high correlation."""
    if _identifier_key(target_id) and _identifier_key(target_id) == _identifier_key(condition_type):
        return "SAME_CANONICAL_ATTRIBUTE"
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
                if row.get("analysis_family") == family and row.get("p_value") is not None]
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


def build_scientific_opportunities(
    bundle: dict[str, Any],
    minimum_paired_studies: int = 3,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    maximum_opportunities: int = 500,
    maximum_levels_per_condition: int = 20,
    seed: int = 42,
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

    experiments = {row["experiment_id"]: row for row in bundle.get("experiments", [])}
    systems = {row["system_id"]: row for row in bundle.get("systems", [])}
    conditions = {row["condition_id"]: row for row in bundle.get("conditions", [])}

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
            target_id, condition_type, outcome_unit, condition_unit, levels_by_label
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
                        "x": x_value, "y": y_value, "system_id": system_id,
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
        "opportunity_count_before_limit": len(raw_opportunities),
        "opportunity_count_written": len(opportunities),
        "fdr_screen_positive_count": sum(
            item["q_value"] is not None and item["q_value"] <= fdr_alpha for item in opportunities
        ),
        "semantic_policy": "IDENTIFIERS_RETAINED; NO_AUTOMATIC_TARGET_OR_CONDITION_INTERPRETATION",
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
        "limitations": limitations + [
            "Canonical target/condition identity and exact same-unit value identity are excluded before inferential testing and FDR correction.",
            "Perfect correlation alone is not treated as proof of self-association; broader deterministic derivation requires explicit provenance metadata and human review.",
        ],
    }
