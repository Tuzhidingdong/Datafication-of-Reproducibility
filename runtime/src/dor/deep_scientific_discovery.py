"""Full-bundle deep scientific screens over pairwise-available canonical data.

The engine is deterministic and dependency-free. It screens within-System response
shape, pairwise/three-way predictive interactions, and multi-objective co-variation.
Study is the inferential unit; no Observation, Experiment, System, or candidate row is
promoted to an independent Study. Missing features are handled pairwise, not by a
global complete-case cohort. All labels remain canonical identifiers.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import statistics
from collections import defaultdict
from typing import Any

ENGINE_VERSION = "1.0.0"
_UNSPECIFIED = "UNSPECIFIED_UNIT"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _value_unit(record: dict[str, Any]) -> tuple[Any, str]:
    if record.get("normalized_value") not in (None, "") and record.get("normalized_unit") not in (None, ""):
        return record.get("normalized_value"), str(record.get("normalized_unit")).strip()
    unit = record.get("raw_unit")
    return record.get("raw_value"), str(unit).strip() if unit not in (None, "") else _UNSPECIFIED


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
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
    dx = [item - mx for item in rx]
    dy = [item - my for item in ry]
    denominator = math.sqrt(sum(item * item for item in dx) * sum(item * item for item in dy))
    if denominator <= 0:
        return None
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(dx, dy)) / denominator))


def _sign_test_p(values: list[float]) -> float | None:
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    n = positive + negative
    if n == 0:
        return None
    tail = sum(math.comb(n, index) for index in range(min(positive, negative) + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    low, high = int(math.floor(position)), int(math.ceil(position))
    fraction = position - low
    return float(ordered[low] * (1.0 - fraction) + ordered[high] * fraction)


def _bootstrap_ci(values: list[float], iterations: int, seed: int) -> list[float] | None:
    if len(values) < 2 or iterations < 100:
        return None
    import random
    rng = random.Random(seed)
    sampled = [
        float(statistics.median(values[rng.randrange(len(values))] for _ in values))
        for _ in range(iterations)
    ]
    return [_percentile(sampled, 0.025), _percentile(sampled, 0.975)]


def _stable_seed(seed: int, identity: Any) -> int:
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).digest()
    return (seed + int.from_bytes(digest[:4], "big")) % (2 ** 32)


def _identifier(identity: Any, prefix: str = "DEEP") -> str:
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:14].upper()
    return f"{prefix}-{digest}"


def _solve(design: list[list[float]], y: list[float]) -> list[float] | None:
    """Solve least squares through pivoted normal equations; reject singular designs."""
    if not design or len(design) != len(y):
        return None
    width = len(design[0])
    if width == 0 or any(len(row) != width for row in design) or len(y) < width:
        return None
    matrix = [[sum(row[i] * row[j] for row in design) for j in range(width)] for i in range(width)]
    vector = [sum(row[i] * target for row, target in zip(design, y)) for i in range(width)]
    scale = max((abs(value) for row in matrix for value in row), default=1.0)
    tolerance = max(1e-12, scale * 1e-12)
    for column in range(width):
        pivot = max(range(column, width), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) <= tolerance:
            return None
        if pivot != column:
            matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
            vector[column], vector[pivot] = vector[pivot], vector[column]
        divisor = matrix[column][column]
        for j in range(column, width):
            matrix[column][j] /= divisor
        vector[column] /= divisor
        for row in range(width):
            if row == column:
                continue
            factor = matrix[row][column]
            if factor == 0:
                continue
            for j in range(column, width):
                matrix[row][j] -= factor * matrix[column][j]
            vector[row] -= factor * vector[column]
    return vector if all(math.isfinite(value) for value in vector) else None


def _standardize(values: list[float]) -> tuple[list[float], float, float]:
    mean = statistics.mean(values)
    deviation = statistics.pstdev(values)
    if deviation <= 1e-12:
        deviation = 1.0
    return [(value - mean) / deviation for value in values], mean, deviation


def _univariate_design(xs: list[float], kind: str, knot: float | None = None) -> list[list[float]]:
    rows = []
    for value in xs:
        if kind == "linear":
            rows.append([1.0, value])
        elif kind == "quadratic":
            rows.append([1.0, value, value * value])
        elif kind == "threshold":
            if knot is None:
                raise ValueError("A threshold model requires a knot.")
            rows.append([1.0, value, max(0.0, value - knot)])
        else:
            raise ValueError(f"Unsupported univariate model: {kind}")
    return rows


def _best_threshold(xs: list[float], ys: list[float]) -> tuple[float, list[float]] | None:
    unique = sorted(set(xs))
    candidates = [
        (left + right) / 2.0
        for left, right in zip(unique[1:-2], unique[2:-1])
    ]
    best: tuple[float, list[float]] | None = None
    best_sse = math.inf
    for knot in candidates:
        left_levels = {x for x in xs if x <= knot}
        right_levels = {x for x in xs if x > knot}
        if len(left_levels) < 2 or len(right_levels) < 2:
            continue
        coefficients = _solve(_univariate_design(xs, "threshold", knot), ys)
        if coefficients is None:
            continue
        predictions = [
            sum(a * b for a, b in zip(row, coefficients))
            for row in _univariate_design(xs, "threshold", knot)
        ]
        sse = sum((actual - predicted) ** 2 for actual, predicted in zip(ys, predictions))
        if sse < best_sse - 1e-12 or (
            math.isclose(sse, best_sse, rel_tol=0.0, abs_tol=1e-12)
            and (best is None or knot < best[0])
        ):
            best_sse, best = sse, (knot, coefficients)
    return best


def _predict_univariate(
    train_x: list[float], train_y: list[float], test_x: float, kind: str
) -> tuple[float, float | None] | None:
    scaled, mean, deviation = _standardize(train_x)
    test_scaled = (test_x - mean) / deviation
    knot = None
    if kind == "threshold":
        selected = _best_threshold(scaled, train_y)
        if selected is None:
            return None
        knot, coefficients = selected
    else:
        coefficients = _solve(_univariate_design(scaled, kind), train_y)
        if coefficients is None:
            return None
    row = _univariate_design([test_scaled], kind, knot)[0]
    prediction = sum(a * b for a, b in zip(row, coefficients))
    return prediction, (knot * deviation + mean) if knot is not None else None


def _loo_rmse_univariate(xs: list[float], ys: list[float], kind: str) -> float | None:
    errors = []
    for held_out in range(len(xs)):
        train_x = xs[:held_out] + xs[held_out + 1:]
        train_y = ys[:held_out] + ys[held_out + 1:]
        if len(set(train_x)) < (4 if kind == "threshold" else 3):
            return None
        fitted = _predict_univariate(train_x, train_y, xs[held_out], kind)
        if fitted is None:
            return None
        errors.append((ys[held_out] - fitted[0]) ** 2)
    return math.sqrt(statistics.mean(errors)) if errors else None


def _multi_design(rows: list[list[float]], order: int, include_high_order: bool) -> list[list[float]]:
    design = []
    for values in rows:
        if order == 2:
            x, z = values
            features = [1.0, x, z]
            if include_high_order:
                features.append(x * z)
        elif order == 3:
            x, z, w = values
            features = [1.0, x, z, w, x * z, x * w, z * w]
            if include_high_order:
                features.append(x * z * w)
        else:
            raise ValueError("Interaction order must be two or three.")
        design.append(features)
    return design


def _loo_rmse_multi(xs: list[list[float]], ys: list[float], order: int, include_high_order: bool) -> float | None:
    errors = []
    for held_out in range(len(ys)):
        train_rows = [row for index, row in enumerate(xs) if index != held_out]
        train_y = ys[:held_out] + ys[held_out + 1:]
        width = order
        means = [statistics.mean(row[column] for row in train_rows) for column in range(width)]
        deviations = [
            statistics.pstdev(row[column] for row in train_rows) or 1.0
            for column in range(width)
        ]
        if any(deviation <= 1e-12 for deviation in deviations):
            deviations = [1.0 if item <= 1e-12 else item for item in deviations]
        scaled_train = [
            [(row[column] - means[column]) / deviations[column] for column in range(width)]
            for row in train_rows
        ]
        scaled_test = [
            (xs[held_out][column] - means[column]) / deviations[column]
            for column in range(width)
        ]
        design = _multi_design(scaled_train, order, include_high_order)
        coefficients = _solve(design, train_y)
        if coefficients is None:
            return None
        prediction = sum(
            a * b for a, b in zip(
                _multi_design([scaled_test], order, include_high_order)[0], coefficients
            )
        )
        errors.append((ys[held_out] - prediction) ** 2)
    return math.sqrt(statistics.mean(errors)) if errors else None


def _model_improvement(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline <= 1e-12:
        return None
    return (baseline - candidate) / baseline


def _study_effect_rows(
    system_rows: list[dict[str, Any]],
    *,
    minimum_studies: int,
    bootstrap_iterations: int,
    seed: int,
    fdr_alpha: float,
) -> dict[str, Any]:
    study_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in system_rows:
        study_groups[row["study_id"]].append(row)
    effects = []
    for study_id, rows in sorted(study_groups.items()):
        values = [item["effect"] for item in rows if item.get("effect") is not None]
        if not values:
            continue
        supporting_system_ids = sorted({
            system_id
            for item in rows
            for system_id in item.get("supporting_system_ids", [item.get("system_id")])
            if system_id
        })
        effects.append({
            "study_id": study_id,
            "effect": float(statistics.median(values)),
            "system_count": sum(
                int(item.get("supporting_system_count", 1)) for item in rows
            ),
            "system_ids": supporting_system_ids,
            "experiment_ids": sorted({value for item in rows for value in item["experiment_ids"]}),
            "observation_ids": sorted({value for item in rows for value in item["observation_ids"]}),
            "system_effects": rows,
        })
    values = [item["effect"] for item in effects]
    reference_direction = (
        "POSITIVE" if values and statistics.median(values) > 0
        else "NEGATIVE" if values and statistics.median(values) < 0
        else "ZERO_OR_UNRESOLVED"
    )
    counterexample_effects = (
        [item["study_id"] for item in effects if item["effect"] <= 0]
        if reference_direction == "POSITIVE"
        else [item["study_id"] for item in effects if item["effect"] >= 0]
        if reference_direction == "NEGATIVE"
        else []
    )
    return {
        "study_effects": effects,
        "effect_direction": reference_direction,
        "counterexample_direction": "OPPOSITE_TO_MEDIAN_STUDY_EFFECT_DIRECTION",
        "independent_study_count": len(effects),
        "effect_estimate": _median(values),
        "confidence_interval_95": _bootstrap_ci(
            values, bootstrap_iterations, _stable_seed(seed, [item["study_id"] for item in effects])
        ),
        "p_value": _sign_test_p(values) if len(effects) >= minimum_studies else None,
        "q_value": None,
        "fdr_alpha": fdr_alpha,
        "counterexample_study_ids": counterexample_effects,
    }


def _apply_bh(opportunities: list[dict[str, Any]], family: str) -> None:
    eligible = [
        (index, row["p_value"])
        for index, row in enumerate(opportunities)
        if row.get("analysis_family") == family and row.get("p_value") is not None
    ]
    eligible.sort(key=lambda item: (item[1], item[0]))
    running = 1.0
    total = len(eligible)
    for rank in range(total, 0, -1):
        index, p_value = eligible[rank - 1]
        running = min(running, p_value * total / rank)
        opportunities[index]["q_value"] = min(1.0, running)


def _finalize(opportunities: list[dict[str, Any]], fdr_alpha: float) -> None:
    for family in sorted({row["analysis_family"] for row in opportunities}):
        _apply_bh(opportunities, family)
    for row in opportunities:
        if row.get("model_improvement_threshold_met") is False:
            row["screen_status"] = "BELOW_MINIMUM_PREDICTIVE_GAIN_RETAINED_FOR_COUNTEREVIDENCE"
        elif row.get("q_value") is not None and row["q_value"] <= fdr_alpha:
            row["screen_status"] = "FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW"
        elif row.get("p_value") is None:
            row["screen_status"] = "DESCRIPTIVE_CANDIDATE_INSUFFICIENT_INDEPENDENT_STUDY_SUPPORT"
        else:
            row["screen_status"] = "CANDIDATE_NOT_FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW"


def _outcome_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("target_id") or "UNSPECIFIED_TARGET"),
        str(record.get("endpoint_definition") or "UNSPECIFIED_ENDPOINT_DEFINITION"),
        str(record.get("timepoint") or "UNSPECIFIED_TIMEPOINT"),
        _value_unit(record)[1],
    )


def _feature_key(record: dict[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("condition_type") or "UNSPECIFIED_CONDITION"),
        _value_unit(record)[1],
    )


def _collect_experiment_values(bundle: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    experiments = {item["experiment_id"]: item for item in bundle.get("experiments", [])}
    outcome_values: dict[tuple[str, tuple[str, str, str, str]], list[tuple[float, str]]] = defaultdict(list)
    for observation in bundle.get("observations", []):
        if observation.get("value_state") != "REPORTED":
            continue
        raw, unit = _value_unit(observation)
        number = _number(raw)
        if number is None or unit == _UNSPECIFIED:
            continue
        experiment_id = observation.get("experiment_id")
        if experiment_id not in experiments:
            continue
        outcome_values[(experiment_id, _outcome_key(observation))].append(
            (number, str(observation.get("observation_id") or ""))
        )
    outcomes_by_experiment: dict[str, dict] = defaultdict(dict)
    for (experiment_id, key), values in outcome_values.items():
        outcomes_by_experiment[experiment_id][key] = {
            "value": float(statistics.median(item[0] for item in values)),
            "observation_ids": sorted({item[1] for item in values if item[1]}),
        }

    conditions = {item["condition_id"]: item for item in bundle.get("conditions", [])}
    conditions_by_experiment: dict[str, dict] = defaultdict(dict)
    ambiguous_assignments = 0
    for experiment_id, experiment in experiments.items():
        by_feature: dict[tuple[str, str], list[float]] = defaultdict(list)
        for condition_id in experiment.get("condition_ids", []):
            condition = conditions.get(condition_id)
            if not condition or condition.get("value_state") != "REPORTED":
                continue
            raw, unit = _value_unit(condition)
            number = _number(raw)
            if number is None or unit == _UNSPECIFIED:
                continue
            by_feature[_feature_key(condition)].append(number)
        for feature, values in by_feature.items():
            unique = sorted(set(values))
            if len(unique) == 1:
                conditions_by_experiment[experiment_id][feature] = unique[0]
            else:
                ambiguous_assignments += 1

    context = {
        "experiments": experiments,
        "ambiguous_condition_assignments_excluded": ambiguous_assignments,
        "outcomes_by_experiment": outcomes_by_experiment,
        "conditions_by_experiment": conditions_by_experiment,
    }
    return outcomes_by_experiment, conditions_by_experiment, context


def _records_for_outcome_feature(
    outcome_key: tuple[str, str, str, str],
    feature_key: tuple[str, str],
    outcomes: dict[str, dict],
    conditions: dict[str, dict],
    experiments: dict[str, dict],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for experiment_id in sorted(outcomes):
        outcome = outcomes[experiment_id].get(outcome_key)
        condition = conditions.get(experiment_id, {}).get(feature_key)
        if outcome is None or condition is None:
            continue
        experiment = experiments[experiment_id]
        grouped[(experiment["study_id"], experiment["system_id"])].append({
            "study_id": experiment["study_id"],
            "system_id": experiment["system_id"],
            "experiment_id": experiment_id,
            "x": condition,
            "y": outcome["value"],
            "observation_ids": outcome["observation_ids"],
        })
    return grouped


def _response_screen(
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    kind: str,
    *,
    minimum_experiments: int,
    minimum_improvement: float,
) -> list[dict[str, Any]]:
    system_rows = []
    for (study_id, system_id), rows in sorted(grouped.items()):
        xs, ys = [item["x"] for item in rows], [item["y"] for item in rows]
        if len(rows) < minimum_experiments or len(set(xs)) < 5:
            continue
        linear = _loo_rmse_univariate(xs, ys, "linear")
        candidate = _loo_rmse_univariate(xs, ys, kind)
        improvement = _model_improvement(linear, candidate)
        if improvement is None:
            continue
        metadata = None
        if kind == "quadratic":
            scaled, mean, deviation = _standardize(xs)
            coefficients = _solve(_univariate_design(scaled, "quadratic"), ys)
            if coefficients is not None:
                metadata = {"quadratic_coefficient_standardized": coefficients[2]}
        elif kind == "threshold":
            scaled, mean, deviation = _standardize(xs)
            best = _best_threshold(scaled, ys)
            if best is not None:
                metadata = {"threshold_value": best[0] * deviation + mean}
        system_rows.append({
            "study_id": study_id,
            "system_id": system_id,
            "effect": improvement,
            "linear_loo_rmse": linear,
            "candidate_loo_rmse": candidate,
            "experiment_count": len(rows),
            "experiment_ids": sorted(item["experiment_id"] for item in rows),
            "observation_ids": sorted({value for item in rows for value in item["observation_ids"]}),
            "metadata": metadata,
        })
    return system_rows



def _between_system_points(
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    order: int,
) -> dict[str, list[dict[str, Any]]]:
    """Collapse only constant-within-System exposures to one cross-sectional point."""
    by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (study_id, system_id), rows in sorted(grouped.items()):
        values_by_feature = []
        eligible = True
        for index in range(order):
            values = {float(item[f"x{index}"]) for item in rows} if order > 1 else {
                float(item["x"]) for item in rows
            }
            if len(values) != 1:
                eligible = False
                break
            values_by_feature.append(next(iter(values)))
        if not eligible:
            continue
        by_study[study_id].append({
            "study_id": study_id,
            "system_id": system_id,
            "x": values_by_feature,
            "y": float(statistics.median(item["y"] for item in rows)),
            "experiment_ids": sorted({item["experiment_id"] for item in rows}),
            "observation_ids": sorted({
                value for item in rows for value in item["observation_ids"]
            }),
        })
    for study_id in by_study:
        by_study[study_id].sort(key=lambda item: item["system_id"])
    return by_study


def _response_screen_between_systems(
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    kind: str,
    *,
    minimum_systems: int,
) -> list[dict[str, Any]]:
    """Cross-sectional nonlinear response screen across Systems within each Study."""
    output = []
    for study_id, points in sorted(_between_system_points(grouped, 1).items()):
        xs = [item["x"][0] for item in points]
        ys = [item["y"] for item in points]
        if len(points) < minimum_systems or len(set(xs)) < 5:
            continue
        linear = _loo_rmse_univariate(xs, ys, "linear")
        candidate = _loo_rmse_univariate(xs, ys, kind)
        improvement = _model_improvement(linear, candidate)
        if improvement is None:
            continue
        metadata = None
        if kind == "quadratic":
            scaled, _, _ = _standardize(xs)
            coefficients = _solve(_univariate_design(scaled, "quadratic"), ys)
            if coefficients is not None:
                metadata = {"quadratic_coefficient_standardized": coefficients[2]}
        else:
            scaled, mean, deviation = _standardize(xs)
            best = _best_threshold(scaled, ys)
            if best is not None:
                metadata = {"threshold_value": best[0] * deviation + mean}
        output.append({
            "study_id": study_id,
            "system_id": "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
            "supporting_system_ids": sorted(item["system_id"] for item in points),
            "supporting_system_count": len(points),
            "effect": improvement,
            "linear_loo_rmse": linear,
            "candidate_loo_rmse": candidate,
            "experiment_count": sum(len(item["experiment_ids"]) for item in points),
            "experiment_ids": sorted({
                experiment_id for item in points for experiment_id in item["experiment_ids"]
            }),
            "observation_ids": sorted({
                observation_id for item in points for observation_id in item["observation_ids"]
            }),
            "metadata": metadata,
            "analysis_design": "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
        })
    return output


def _interaction_screen_between_systems(
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    order: int,
    *,
    minimum_systems: int,
) -> list[dict[str, Any]]:
    """Cross-sectional two-/three-way predictive screen across Systems within Study."""
    output = []
    for study_id, points in sorted(_between_system_points(grouped, order).items()):
        xs = [item["x"] for item in points]
        ys = [item["y"] for item in points]
        if len(points) < minimum_systems or any(
            len({row[index] for row in xs}) < 3 for index in range(order)
        ):
            continue
        baseline = _loo_rmse_multi(xs, ys, order, False)
        candidate = _loo_rmse_multi(xs, ys, order, True)
        improvement = _model_improvement(baseline, candidate)
        if improvement is None:
            continue
        output.append({
            "study_id": study_id,
            "system_id": "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
            "supporting_system_ids": sorted(item["system_id"] for item in points),
            "supporting_system_count": len(points),
            "effect": improvement,
            "additive_or_lower_order_loo_rmse": baseline,
            "higher_order_loo_rmse": candidate,
            "experiment_count": sum(len(item["experiment_ids"]) for item in points),
            "experiment_ids": sorted({
                experiment_id for item in points for experiment_id in item["experiment_ids"]
            }),
            "observation_ids": sorted({
                observation_id for item in points for observation_id in item["observation_ids"]
            }),
            "analysis_design": "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
        })
    return output


def _interaction_screen(
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    order: int,
    *,
    minimum_experiments: int,
    minimum_improvement: float,
) -> list[dict[str, Any]]:
    system_rows = []
    for (study_id, system_id), rows in sorted(grouped.items()):
        if len(rows) < minimum_experiments:
            continue
        xs = [[item[f"x{index}"] for index in range(order)] for item in rows]
        if any(len({row[index] for row in xs}) < 3 for index in range(order)):
            continue
        baseline = _loo_rmse_multi(xs, [item["y"] for item in rows], order, False)
        candidate = _loo_rmse_multi(xs, [item["y"] for item in rows], order, True)
        improvement = _model_improvement(baseline, candidate)
        if improvement is None:
            continue
        system_rows.append({
            "study_id": study_id,
            "system_id": system_id,
            "effect": improvement,
            "additive_or_lower_order_loo_rmse": baseline,
            "higher_order_loo_rmse": candidate,
            "experiment_count": len(rows),
            "experiment_ids": sorted(item["experiment_id"] for item in rows),
            "observation_ids": sorted({value for item in rows for value in item["observation_ids"]}),
        })
    return system_rows


def _make_opportunity(
    signal_type: str,
    analysis_family: str,
    identity: Any,
    variable_context: dict[str, Any],
    study_summary: dict[str, Any],
    effect_label: str,
) -> dict[str, Any]:
    return {
        "opportunity_id": _identifier([signal_type, identity]),
        "signal_type": signal_type,
        "analysis_family": analysis_family,
        **variable_context,
        "effect_label": effect_label,
        "effect_estimate": study_summary["effect_estimate"],
        "effect_direction": study_summary["effect_direction"],
        "counterexample_direction": study_summary["counterexample_direction"],
        "analysis_unit": "INDEPENDENT_STUDY",
        "confidence_interval_95": study_summary["confidence_interval_95"],
        "p_value": study_summary["p_value"],
        "q_value": None,
        "independent_study_count": study_summary["independent_study_count"],
        "study_effects": study_summary["study_effects"],
        "counterexample_study_ids": study_summary["counterexample_study_ids"],
        "semantic_status": "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
        "interpretation_status": "OBSERVATIONAL_SCREEN_NOT_CAUSAL_OR_MECHANISTIC",
        "screen_status": None,
        "proposed_validation": (
            "Review endpoint/condition semantics and measurement context, then test the "
            "candidate pattern in an independently designed or independently reported Study."
        ),
    }


def _pareto_front(
    points: list[dict[str, Any]], maximize_a: bool, maximize_b: bool
) -> set[str]:
    frontier = set()
    key_field = "experiment_id" if points and "experiment_id" in points[0] else "system_id"
    for candidate in points:
        a = candidate["a"] if maximize_a else -candidate["a"]
        b = candidate["b"] if maximize_b else -candidate["b"]
        dominated = False
        for other in points:
            if other is candidate:
                continue
            oa = other["a"] if maximize_a else -other["a"]
            ob = other["b"] if maximize_b else -other["b"]
            if oa >= a and ob >= b and (oa > a or ob > b):
                dominated = True
                break
        if not dominated:
            frontier.add(candidate[key_field])
    return frontier


def build_deep_scientific_discovery(
    bundle: dict[str, Any],
    *,
    minimum_studies: int = 3,
    minimum_experiments_per_system: int = 8,
    minimum_triplet_experiments_per_system: int = 12,
    minimum_between_systems_per_study: int = 8,
    maximum_condition_pairs: int = 100,
    maximum_condition_triplets: int = 40,
    maximum_multiobjective_pairs: int = 100,
    maximum_condition_features_for_triplets: int = 18,
    minimum_model_improvement: float = 0.10,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Screen nonlinear responses, condition interactions and multi-objective structure."""
    if minimum_studies < 2:
        raise ValueError("minimum_studies must be >= 2.")
    if minimum_experiments_per_system < 6 or minimum_triplet_experiments_per_system < 10:
        raise ValueError("Deep discovery minimum repeated-Experiment thresholds are too small.")
    if minimum_between_systems_per_study < 5:
        raise ValueError("minimum_between_systems_per_study must be >= 5.")
    if min(maximum_condition_pairs, maximum_condition_triplets, maximum_multiobjective_pairs) < 1:
        raise ValueError("Deep discovery candidate limits must be positive.")
    if not 0 < minimum_model_improvement < 1:
        raise ValueError("minimum_model_improvement must be between 0 and 1.")
    if not 0 < fdr_alpha <= 1:
        raise ValueError("fdr_alpha must be in (0, 1].")

    outcomes, conditions, context = _collect_experiment_values(bundle)
    experiments = context["experiments"]
    outcome_keys = sorted({key for values in outcomes.values() for key in values})
    feature_support: dict[tuple[str, str], set[str]] = defaultdict(set)
    for experiment_id, features in conditions.items():
        for feature in features:
            feature_support[feature].add(experiment_id)

    # Features are ranked only to bound combinatorics. Every retained hypothesis uses
    # its own pairwise-available rows; no common complete-case cohort is constructed.
    features_by_outcome: dict[tuple[str, str, str, str], list[tuple[str, str]]] = {}
    omitted_feature_count = 0
    outcome_feature_support: dict[tuple[tuple[str, str, str, str], tuple[str, str]], set[str]] = defaultdict(set)
    for experiment_id, outcome_map in outcomes.items():
        for outcome_key in outcome_map:
            for feature in conditions.get(experiment_id, {}):
                outcome_feature_support[(outcome_key, feature)].add(experiment_id)
    for outcome_key in outcome_keys:
        features = [
            feature for (candidate_outcome, feature), experiments_set in outcome_feature_support.items()
            if candidate_outcome == outcome_key
        ]
        features.sort(key=lambda feature: (
            -len(outcome_feature_support[(outcome_key, feature)]),
            feature[0], feature[1],
        ))
        features_by_outcome[outcome_key] = features
        omitted_feature_count += max(0, len(features) - maximum_condition_features_for_triplets)

    nonlinear_rows: list[dict[str, Any]] = []
    interaction_rows: list[dict[str, Any]] = []
    multiobjective_rows: list[dict[str, Any]] = []
    frontier_rows: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    nonlinear_hypothesis_count = 0
    nonlinear_hypotheses_omitted = 0
    pair_hypothesis_count = 0
    pair_hypotheses_omitted = 0
    triplet_hypothesis_count = 0
    triplet_hypotheses_omitted = 0
    multiobjective_hypothesis_count = 0
    multiobjective_hypotheses_omitted = 0
    screened_model_evaluation_count = 0

    for outcome_key in outcome_keys:
        features = features_by_outcome[outcome_key]
        # Nonlinear main effects: each feature/outcome pair has its own available subset.
        response_candidates = []
        for feature in features:
            support = outcome_feature_support[(outcome_key, feature)]
            study_support = {
                experiments[item]["study_id"] for item in support if item in experiments
            }
            if len(study_support) >= minimum_studies:
                response_candidates.append((feature, len(support), len(study_support)))
        nonlinear_hypothesis_count += min(len(response_candidates), maximum_condition_pairs)
        nonlinear_hypotheses_omitted += max(0, len(response_candidates) - maximum_condition_pairs)
        for feature, _, _ in response_candidates[:maximum_condition_pairs]:
            grouped = _records_for_outcome_feature(
                outcome_key, feature, outcomes, conditions, experiments
            )
            for kind, suffix, signal_type in (
                ("quadratic", "NONLINEAR_QUADRATIC", "NONLINEAR_QUADRATIC_RESPONSE"),
                ("threshold", "NONLINEAR_THRESHOLD", "NONLINEAR_THRESHOLD_RESPONSE"),
            ):
                screen_designs = (
                    (
                        "WITHIN_SYSTEM_REPEATED_EXPERIMENTS",
                        _response_screen(
                            grouped, kind,
                            minimum_experiments=minimum_experiments_per_system,
                            minimum_improvement=minimum_model_improvement,
                        ),
                    ),
                    (
                        "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
                        _response_screen_between_systems(
                            grouped, kind, minimum_systems=minimum_between_systems_per_study
                        ),
                    ),
                )
                for design, system_rows in screen_designs:
                    screened_model_evaluation_count += len(system_rows)
                    if not system_rows:
                        continue
                    summary = _study_effect_rows(
                        system_rows, minimum_studies=minimum_studies,
                        bootstrap_iterations=bootstrap_iterations, seed=seed,
                        fdr_alpha=fdr_alpha,
                    )
                    if summary["independent_study_count"] < minimum_studies:
                        continue
                    if kind == "quadratic":
                        coefficient_values_by_study: dict[str, list[float]] = defaultdict(list)
                        for item in system_rows:
                            if item.get("metadata") and item["metadata"].get("quadratic_coefficient_standardized") is not None:
                                coefficient_values_by_study[item["study_id"]].append(
                                    item["metadata"]["quadratic_coefficient_standardized"]
                                )
                        quadratic_coefficients = [
                            float(statistics.median(values))
                            for values in coefficient_values_by_study.values()
                        ]
                        shape = (
                            "CONCAVE" if quadratic_coefficients and statistics.median(quadratic_coefficients) < 0
                            else "CONVEX_OR_MIXED" if quadratic_coefficients else "UNRESOLVED_FROM_AVAILABLE_FITS"
                        )
                        variable_context = {"outcome": dict(zip(
                            ("target_id", "endpoint_definition", "timepoint", "unit"), outcome_key
                        )), "condition": {"condition_type": feature[0], "unit": feature[1]},
                            "response_shape": shape}
                    else:
                        threshold_values_by_study: dict[str, list[float]] = defaultdict(list)
                        for item in system_rows:
                            if item.get("metadata") and item["metadata"].get("threshold_value") is not None:
                                threshold_values_by_study[item["study_id"]].append(
                                    item["metadata"]["threshold_value"]
                                )
                        thresholds = [
                            float(statistics.median(values))
                            for values in threshold_values_by_study.values()
                        ]
                        variable_context = {"outcome": dict(zip(
                            ("target_id", "endpoint_definition", "timepoint", "unit"), outcome_key
                        )), "condition": {"condition_type": feature[0], "unit": feature[1]},
                            "threshold_value_median_across_eligible_studies": _median(thresholds),
                            "threshold_values_are_descriptive_not_universal_cutoffs": True}
                    identity = [outcome_key, feature, kind, design]
                    opportunity = _make_opportunity(
                        signal_type, f"{design}_{suffix}", identity, variable_context, summary,
                        "median Study-level relative LOO-RMSE improvement over linear response",
                    )
                    opportunity["analysis_design"] = design
                    opportunity["model_comparison"] = (
                        f"LEAVE_ONE_{'EXPERIMENT' if design.startswith('WITHIN') else 'SYSTEM'}_OUT_LINEAR_VS_QUADRATIC"
                        if kind == "quadratic"
                        else f"LEAVE_ONE_{'EXPERIMENT' if design.startswith('WITHIN') else 'SYSTEM'}_OUT_LINEAR_VS_CONTINUOUS_PIECEWISE_LINEAR"
                    )
                    opportunity["eligible_system_count"] = sum(
                        item["system_count"] for item in summary["study_effects"]
                    )
                    opportunity["confounding_review"] = (
                        "Within-System comparison reduces stable System-identity differences but does not remove protocol/time confounding."
                        if design.startswith("WITHIN")
                        else "Cross-sectional between-System response may be confounded by System composition, protocol, source, and other Study-level differences."
                    )
                    opportunity["minimum_model_improvement_threshold"] = minimum_model_improvement
                    opportunity["model_improvement_threshold_met"] = (
                        summary["effect_estimate"] is not None
                        and summary["effect_estimate"] >= minimum_model_improvement
                    )
                    nonlinear_rows.append(opportunity)
                    opportunities.append(opportunity)

        # Two- and three-condition combinations use only experiments where that
        # particular pair/triplet and this outcome are all present.
        pair_support: dict[tuple[tuple[str, str], tuple[str, str]], set[str]] = defaultdict(set)
        triplet_support: dict[tuple[tuple[str, str], tuple[str, str], tuple[str, str]], set[str]] = defaultdict(set)
        combination_features = features[:maximum_condition_features_for_triplets]
        for experiment_id, outcome_map in outcomes.items():
            if outcome_key not in outcome_map:
                continue
            present = sorted(set(conditions.get(experiment_id, {})) & set(combination_features))
            for pair in itertools.combinations(present, 2):
                pair_support[pair].add(experiment_id)
            triplet_present = present
            for triplet in itertools.combinations(triplet_present, 3):
                triplet_support[triplet].add(experiment_id)

        eligible_pairs = []
        for pair, ids in pair_support.items():
            study_count = len({experiments[item]["study_id"] for item in ids})
            if study_count >= minimum_studies:
                eligible_pairs.append((pair, len(ids), study_count))
        eligible_pairs.sort(key=lambda item: (-item[1], -item[2], item[0]))
        pair_hypothesis_count += min(len(eligible_pairs), maximum_condition_pairs)
        pair_hypotheses_omitted += max(0, len(eligible_pairs) - maximum_condition_pairs)
        for pair, _, _ in eligible_pairs[:maximum_condition_pairs]:
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for experiment_id in sorted(pair_support[pair]):
                experiment = experiments[experiment_id]
                outcome = outcomes[experiment_id][outcome_key]
                values = conditions[experiment_id]
                grouped[(experiment["study_id"], experiment["system_id"])].append({
                    "study_id": experiment["study_id"], "system_id": experiment["system_id"],
                    "experiment_id": experiment_id, "x0": values[pair[0]], "x1": values[pair[1]],
                    "y": outcome["value"], "observation_ids": outcome["observation_ids"],
                })
            screen_designs = (
                (
                    "WITHIN_SYSTEM_REPEATED_EXPERIMENTS",
                    _interaction_screen(
                        grouped, 2, minimum_experiments=minimum_experiments_per_system,
                        minimum_improvement=minimum_model_improvement,
                    ),
                    "LEAVE_ONE_EXPERIMENT_OUT",
                ),
                (
                    "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
                    _interaction_screen_between_systems(
                        grouped, 2, minimum_systems=minimum_between_systems_per_study
                    ),
                    "LEAVE_ONE_SYSTEM_OUT",
                ),
            )
            for design, system_rows, validation_unit in screen_designs:
                screened_model_evaluation_count += len(system_rows)
                if not system_rows:
                    continue
                summary = _study_effect_rows(
                    system_rows, minimum_studies=minimum_studies,
                    bootstrap_iterations=bootstrap_iterations, seed=seed, fdr_alpha=fdr_alpha,
                )
                if summary["independent_study_count"] < minimum_studies:
                    continue
                family = f"{design}_INTERACTION_2WAY"
                variable_context = {
                    "outcome": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), outcome_key)),
                    "condition_features": [
                        {"condition_type": item[0], "unit": item[1]} for item in pair
                    ],
                    "interaction_order": 2,
                }
                opportunity = _make_opportunity(
                    "TWO_WAY_CONDITION_INTERACTION", family, [outcome_key, pair, design],
                    variable_context, summary,
                    "median Study-level relative LOO-RMSE improvement over additive model",
                )
                opportunity["analysis_design"] = design
                opportunity["model_comparison"] = f"{validation_unit}_ADDITIVE_VS_ADDITIVE_PLUS_PRODUCT_TERM"
                opportunity["eligible_system_count"] = sum(
                    item["system_count"] for item in summary["study_effects"]
                )
                opportunity["confounding_review"] = (
                    "Within-System comparison reduces stable System-identity differences but does not remove protocol/time confounding."
                    if design.startswith("WITHIN")
                    else "Cross-sectional between-System interaction may be confounded by System composition, protocol, source, and other Study-level differences."
                )
                opportunity["minimum_model_improvement_threshold"] = minimum_model_improvement
                opportunity["model_improvement_threshold_met"] = (
                    summary["effect_estimate"] is not None
                    and summary["effect_estimate"] >= minimum_model_improvement
                )
                interaction_rows.append(opportunity)
                opportunities.append(opportunity)

        eligible_triplets = []
        for triplet, ids in triplet_support.items():
            study_count = len({experiments[item]["study_id"] for item in ids})
            if study_count >= minimum_studies:
                eligible_triplets.append((triplet, len(ids), study_count))
        eligible_triplets.sort(key=lambda item: (-item[1], -item[2], item[0]))
        triplet_hypothesis_count += min(len(eligible_triplets), maximum_condition_triplets)
        triplet_hypotheses_omitted += max(0, len(eligible_triplets) - maximum_condition_triplets)
        for triplet, _, _ in eligible_triplets[:maximum_condition_triplets]:
            grouped = defaultdict(list)
            for experiment_id in sorted(triplet_support[triplet]):
                experiment = experiments[experiment_id]
                outcome = outcomes[experiment_id][outcome_key]
                values = conditions[experiment_id]
                grouped[(experiment["study_id"], experiment["system_id"])].append({
                    "study_id": experiment["study_id"], "system_id": experiment["system_id"],
                    "experiment_id": experiment_id,
                    "x0": values[triplet[0]], "x1": values[triplet[1]], "x2": values[triplet[2]],
                    "y": outcome["value"], "observation_ids": outcome["observation_ids"],
                })
            screen_designs = (
                (
                    "WITHIN_SYSTEM_REPEATED_EXPERIMENTS",
                    _interaction_screen(
                        grouped, 3, minimum_experiments=minimum_triplet_experiments_per_system,
                        minimum_improvement=minimum_model_improvement,
                    ),
                    "LEAVE_ONE_EXPERIMENT_OUT",
                ),
                (
                    "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
                    _interaction_screen_between_systems(
                        grouped, 3, minimum_systems=max(
                        minimum_between_systems_per_study,
                        minimum_triplet_experiments_per_system,
                    )
                    ),
                    "LEAVE_ONE_SYSTEM_OUT",
                ),
            )
            for design, system_rows, validation_unit in screen_designs:
                screened_model_evaluation_count += len(system_rows)
                if not system_rows:
                    continue
                summary = _study_effect_rows(
                    system_rows, minimum_studies=minimum_studies,
                    bootstrap_iterations=bootstrap_iterations, seed=seed, fdr_alpha=fdr_alpha,
                )
                if summary["independent_study_count"] < minimum_studies:
                    continue
                family = f"{design}_INTERACTION_3WAY"
                variable_context = {
                    "outcome": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), outcome_key)),
                    "condition_features": [
                        {"condition_type": item[0], "unit": item[1]} for item in triplet
                    ],
                    "interaction_order": 3,
                }
                opportunity = _make_opportunity(
                    "THREE_WAY_CONDITION_INTERACTION", family, [outcome_key, triplet, design],
                    variable_context, summary,
                    "median Study-level relative LOO-RMSE improvement over all lower-order terms",
                )
                opportunity["analysis_design"] = design
                opportunity["model_comparison"] = f"{validation_unit}_ALL_MAIN_AND_PAIRWISE_TERMS_VS_PLUS_THREE_WAY_PRODUCT"
                opportunity["eligible_system_count"] = sum(
                    item["system_count"] for item in summary["study_effects"]
                )
                opportunity["confounding_review"] = (
                    "Within-System comparison reduces stable System-identity differences but does not remove protocol/time confounding."
                    if design.startswith("WITHIN")
                    else "Cross-sectional between-System interaction may be confounded by System composition, protocol, source, and other Study-level differences."
                )
                opportunity["minimum_model_improvement_threshold"] = minimum_model_improvement
                opportunity["model_improvement_threshold_met"] = (
                    summary["effect_estimate"] is not None
                    and summary["effect_estimate"] >= minimum_model_improvement
                )
                interaction_rows.append(opportunity)
                opportunities.append(opportunity)

    # Pairwise outcome co-variation and direction-explicit Pareto frontiers.
    outcome_pair_support: dict[tuple[tuple[str, str, str, str], tuple[str, str, str, str]], set[str]] = defaultdict(set)
    for experiment_id, values in outcomes.items():
        present = sorted(values)
        for pair in itertools.combinations(present, 2):
            outcome_pair_support[pair].add(experiment_id)
    multi_candidates = []
    for pair, ids in outcome_pair_support.items():
        study_count = len({experiments[item]["study_id"] for item in ids})
        if study_count >= minimum_studies:
            multi_candidates.append((pair, len(ids), study_count))
    multi_candidates.sort(key=lambda item: (-item[1], -item[2], item[0]))
    multiobjective_hypothesis_count = min(len(multi_candidates), maximum_multiobjective_pairs)
    multiobjective_hypotheses_omitted = max(0, len(multi_candidates) - maximum_multiobjective_pairs)

    for pair, _, _ in multi_candidates[:maximum_multiobjective_pairs]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for experiment_id in sorted(outcome_pair_support[pair]):
            experiment = experiments[experiment_id]
            grouped[(experiment["study_id"], experiment["system_id"])].append({
                "study_id": experiment["study_id"], "system_id": experiment["system_id"],
                "experiment_id": experiment_id,
                "a": outcomes[experiment_id][pair[0]]["value"],
                "b": outcomes[experiment_id][pair[1]]["value"],
                "observation_ids": sorted(
                    set(outcomes[experiment_id][pair[0]]["observation_ids"])
                    | set(outcomes[experiment_id][pair[1]]["observation_ids"])
                ),
            })
        within_system_rows = []
        for (study_id, system_id), points in sorted(grouped.items()):
            if len(points) < 2:
                continue
            rho = _spearman([item["a"] for item in points], [item["b"] for item in points])
            if rho is not None:
                within_system_rows.append({
                    "study_id": study_id, "system_id": system_id, "effect": rho,
                    "experiment_ids": sorted(item["experiment_id"] for item in points),
                    "observation_ids": sorted({v for item in points for v in item["observation_ids"]}),
                })
            for direction, maximize_a, maximize_b in (
                ("MAX_MAX", True, True), ("MAX_MIN", True, False),
                ("MIN_MAX", False, True), ("MIN_MIN", False, False),
            ):
                front = _pareto_front(points, maximize_a, maximize_b)
                for item in points:
                    frontier_rows.append({
                        "population_type": "WITHIN_SYSTEM_REPEATED_EXPERIMENTS",
                        "outcome_a": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[0])),
                        "outcome_b": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[1])),
                        "study_id": study_id, "system_id": system_id,
                        "direction_scenario": direction,
                        "objective_direction_declared_by_user": False,
                        "experiment_id": item["experiment_id"],
                        "supporting_experiment_ids": [item["experiment_id"]],
                        "value_a": item["a"], "value_b": item["b"],
                        "is_non_dominated": item["experiment_id"] in front,
                        "frontier_point_count": len(front),
                        "point_count_in_population": len(points),
                    })

        between_system_rows = []
        between_points_by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (study_id, system_id), points in sorted(grouped.items()):
            between_points_by_study[study_id].append({
                "study_id": study_id, "system_id": system_id,
                "a": float(statistics.median(item["a"] for item in points)),
                "b": float(statistics.median(item["b"] for item in points)),
                "experiment_ids": sorted(item["experiment_id"] for item in points),
                "observation_ids": sorted({v for item in points for v in item["observation_ids"]}),
            })
        for study_id, points in sorted(between_points_by_study.items()):
            if len(points) < 4:
                continue
            rho = _spearman([item["a"] for item in points], [item["b"] for item in points])
            if rho is not None:
                between_system_rows.append({
                    "study_id": study_id,
                    "system_id": "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY",
                    "supporting_system_ids": sorted(item["system_id"] for item in points),
                    "supporting_system_count": len(points),
                    "effect": rho,
                    "experiment_ids": sorted({
                        experiment_id for item in points for experiment_id in item["experiment_ids"]
                    }),
                    "observation_ids": sorted({
                        observation_id for item in points for observation_id in item["observation_ids"]
                    }),
                })
            for direction, maximize_a, maximize_b in (
                ("MAX_MAX", True, True), ("MAX_MIN", True, False),
                ("MIN_MAX", False, True), ("MIN_MIN", False, False),
            ):
                front = _pareto_front(points, maximize_a, maximize_b)
                for item in points:
                    frontier_rows.append({
                        "population_type": "BETWEEN_SYSTEMS_CROSS_SECTIONAL_WITHIN_STUDY",
                        "outcome_a": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[0])),
                        "outcome_b": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[1])),
                        "study_id": study_id, "system_id": item["system_id"],
                        "direction_scenario": direction,
                        "objective_direction_declared_by_user": False,
                        "experiment_id": None,
                        "supporting_experiment_ids": item["experiment_ids"],
                        "value_a": item["a"], "value_b": item["b"],
                        "is_non_dominated": item["system_id"] in front,
                        "frontier_point_count": len(front),
                        "point_count_in_population": len(points),
                    })

        for analysis_design, system_rows in (
            ("WITHIN_SYSTEM_REPEATED_EXPERIMENTS", within_system_rows),
            ("BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY", between_system_rows),
        ):
            if not system_rows:
                continue
            summary = _study_effect_rows(
                system_rows, minimum_studies=minimum_studies,
                bootstrap_iterations=bootstrap_iterations, seed=seed, fdr_alpha=fdr_alpha,
            )
            if summary["independent_study_count"] < minimum_studies:
                continue
            family = f"{analysis_design}_MULTIOBJECTIVE_COVARIATION"
            variable_context = {
                "objective_a": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[0])),
                "objective_b": dict(zip(("target_id", "endpoint_definition", "timepoint", "unit"), pair[1])),
                "pareto_direction_scenarios": ["MAX_MAX", "MAX_MIN", "MIN_MAX", "MIN_MIN"],
                "objective_directions": "NOT_INFERRED; all four direction scenarios are reported",
            }
            opportunity = _make_opportunity(
                "MULTIOBJECTIVE_COVARIATION_AND_PARETO_FRONTIER", family,
                [pair, analysis_design], variable_context, summary,
                (
                    "median Study-level within-System Spearman correlation"
                    if analysis_design.startswith("WITHIN")
                    else "median Study-level between-System Spearman correlation within Study"
                ),
            )
            opportunity["analysis_design"] = analysis_design
            opportunity["covariation_class"] = (
                "CROSS_STUDY_NEGATIVE_COVARIATION_REQUIRES_OBJECTIVE_DIRECTION_REVIEW"
                if summary["effect_estimate"] is not None and summary["effect_estimate"] < 0
                else "CROSS_STUDY_NONNEGATIVE_OR_MIXED_COVARIATION"
            )
            opportunity["pareto_frontier_is_descriptive"] = True
            opportunity["confounding_review"] = (
                "Within-System co-variation reduces stable System-identity differences but does not remove protocol/time confounding."
                if analysis_design.startswith("WITHIN")
                else "Between-System co-variation and Pareto membership may be confounded by System composition, protocol, source, and other Study-level differences."
            )
            multiobjective_rows.append(opportunity)
            opportunities.append(opportunity)

    _finalize(opportunities, fdr_alpha)
    opportunities.sort(key=lambda item: (
        item.get("q_value") if item.get("q_value") is not None else 1.0,
        item.get("p_value") if item.get("p_value") is not None else 1.0,
        -item["independent_study_count"], item["opportunity_id"],
    ))
    return {
        "schema_version": "1.0",
        "engine_version": ENGINE_VERSION,
        "status": "completed",
        "profile": {
            "outcome_group_count": len(outcome_keys),
            "experiment_count_with_numeric_outcomes": len(outcomes),
            "condition_feature_count_with_numeric_reported_values": len(feature_support),
            "ambiguous_condition_assignments_excluded": context["ambiguous_condition_assignments_excluded"],
            "outcome_condition_hypothesis_count": sum(len(items) for items in features_by_outcome.values()),
            "nonlinear_hypotheses_screened": nonlinear_hypothesis_count,
            "nonlinear_hypotheses_omitted_by_limit": nonlinear_hypotheses_omitted,
            "two_way_hypotheses_screened": pair_hypothesis_count,
            "two_way_hypotheses_omitted_by_limit": pair_hypotheses_omitted,
            "three_way_hypotheses_screened": triplet_hypothesis_count,
            "three_way_hypotheses_omitted_by_limit": triplet_hypotheses_omitted,
            "multiobjective_pairs_screened": multiobjective_hypothesis_count,
            "multiobjective_pairs_omitted_by_limit": multiobjective_hypotheses_omitted,
            "condition_features_omitted_from_pair_and_triplet_combinatorics": omitted_feature_count,
            "eligible_model_evaluations": screened_model_evaluation_count,
            "opportunity_count": len(opportunities),
            "within_system_opportunity_count": sum(
                item.get("analysis_design") == "WITHIN_SYSTEM_REPEATED_EXPERIMENTS"
                for item in opportunities
            ),
            "between_system_cross_sectional_opportunity_count": sum(
                item.get("analysis_design") == "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY"
                for item in opportunities
            ),
            "fdr_screen_positive_count": sum(
                item["screen_status"] == "FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW"
                for item in opportunities
            ),
            "analysis_unit": "INDEPENDENT_STUDY",
            "data_subset_policy": "PAIRWISE_AVAILABLE_SUBSETS_NO_GLOBAL_COMPLETE_CASE_REQUIREMENT",
            "primary_value_policy": "REPORTED_VALUE_ONLY_CANDIDATE_SOURCES_ANALYSED_IN_SEPARATE_SENSITIVITY_SCENARIOS",
            "minimum_studies": minimum_studies,
            "minimum_experiments_per_system": minimum_experiments_per_system,
            "minimum_triplet_experiments_per_system": minimum_triplet_experiments_per_system,
            "minimum_between_systems_per_study": minimum_between_systems_per_study,
            "minimum_model_improvement": minimum_model_improvement,
            "fdr_alpha": fdr_alpha,
            "bootstrap_iterations": bootstrap_iterations,
            "seed": seed,
        },
        "nonlinear_opportunities": nonlinear_rows,
        "interaction_opportunities": interaction_rows,
        "multiobjective_opportunities": multiobjective_rows,
        "pareto_frontier_rows": frontier_rows,
        "opportunities": opportunities,
        "limitations": [
            "These are observational predictive screens, not causal effects or established mechanisms.",
            "Nonlinear and interaction model comparisons use leave-one-Experiment-out prediction within each canonical Study/System; cross-Study inference uses one median effect per independent Study.",
            "The two-way and three-way screens are bounded by explicit candidate caps; omitted hypothesis counts remain in the profile.",
            "Three-way screening uses the best-covered numeric condition features per outcome solely to bound combinatorics; it still uses each triplet's own available subset.",
            "Pareto frontiers are emitted under all four maximize/minimize direction scenarios because objective direction is not inferred from data.",
            "Units and canonical identifiers are matched exactly; no implicit unit conversion, semantic mapping, imputation, or conflicting-condition resolution is applied.",
            "Candidate-source alternatives are not part of primary results and must be interpreted only in their separate sensitivity reports.",
            "Study-level bootstrap intervals do not account for every upstream mapping, extraction, or measurement uncertainty.",
        ],
    }
