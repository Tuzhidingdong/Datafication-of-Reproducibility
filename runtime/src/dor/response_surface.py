"""Descriptive pairwise response surfaces for selected numeric interaction candidates.

The surface is an all-cohort refit for visualization, not an independent validation result.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from dor.interactions import _append_pair_products, _encode_pair_columns
from dor.mapping import sha256_file
from dor.modeling import (
    _fit_encoder, _fit_ridge, _load_cohort, _predict_ridge, _settings,
    _transform_rows, _typed_rows,
)
from dor.reproducibility import _quantile

ENGINE_VERSION = "dor-runtime/0.1.0"
DEFAULT_GRID_SIZE = 21
DEFAULT_BACKGROUND_MAX = 500
DEFAULT_SUPPORT_QUANTILE = 0.95


def _surface_settings(task: dict[str, Any], grid_size: int | None,
                     background_max: int | None) -> dict[str, Any]:
    spec = task.get("interaction_surface", {})
    if not isinstance(spec, dict):
        raise ValueError("interaction_surface must be an object.")
    allowed = {"grid_size", "background_max_observations", "range_quantiles", "support_distance_quantile"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError("Unsupported interaction_surface settings: " + ", ".join(unknown))
    size = grid_size if grid_size is not None else spec.get("grid_size", DEFAULT_GRID_SIZE)
    maximum = background_max if background_max is not None else spec.get(
        "background_max_observations", DEFAULT_BACKGROUND_MAX)
    quantiles = spec.get("range_quantiles", [0.0, 1.0])
    support_quantile = spec.get("support_distance_quantile", DEFAULT_SUPPORT_QUANTILE)
    if not isinstance(size, int) or isinstance(size, bool) or not 5 <= size <= 61:
        raise ValueError("grid_size must be an integer between 5 and 61.")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 10 or maximum > 5000:
        raise ValueError("background_max_observations must be an integer between 10 and 5000.")
    if (not isinstance(quantiles, list) or len(quantiles) != 2 or
        any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1
            for value in quantiles) or quantiles[0] >= quantiles[1]):
        raise ValueError("range_quantiles must contain two increasing values in [0, 1].")
    if (not isinstance(support_quantile, (int, float)) or isinstance(support_quantile, bool)
        or not 0.5 <= support_quantile < 1):
        raise ValueError("support_distance_quantile must be in [0.5, 1).")
    return {"grid_size": size, "background_max_observations": maximum,
            "range_quantiles": [float(value) for value in quantiles],
            "support_distance_quantile": float(support_quantile)}


def _load_interaction_selection(interaction_dir: Path, interaction_id: str,
                                cohort_dir: Path, task_path: Path,
                                task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = interaction_dir / "interaction_discovery_report.json"
    manifest_path = interaction_dir / "interaction_discovery_manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("interaction_dir must contain interaction_discovery_report.json and interaction_discovery_manifest.json.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_inputs = {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "task_sha256": sha256_file(task_path),
    }
    for key, value in current_inputs.items():
        if manifest.get("input_hashes", {}).get(key) != value:
            raise ValueError("Interaction discovery manifest does not match current input: " + key)
    expected_report_hash = manifest.get("output_hashes", {}).get("interaction_discovery_report.json")
    if expected_report_hash != sha256_file(report_path):
        raise ValueError("Interaction discovery report hash does not match its manifest.")
    if report.get("task_id") != task.get("task_id") or report.get("target_id") != task.get("target_id") or report.get("endpoint_definition") != task.get("endpoint_definition"):
        raise ValueError("Interaction discovery report target/endpoint does not match the current modeling task.")
    matches = [item for item in report.get("interaction_catalogue", [])
               if item.get("interaction_id") == interaction_id]
    if len(matches) != 1:
        raise ValueError("interaction_id must identify exactly one pair in the hash-verified interaction catalogue.")
    selected = matches[0]
    feature_ids = {binding["feature_id"]: binding for binding in task["feature_bindings"]}
    feature_a, feature_b = selected["feature_a"], selected["feature_b"]
    if feature_a not in feature_ids or feature_b not in feature_ids:
        raise ValueError("Selected interaction pair is not fully represented in the current task feature_bindings.")
    if feature_ids[feature_a]["value_type"] != "NUMERIC" or feature_ids[feature_b]["value_type"] != "NUMERIC":
        raise ValueError("The initial response-surface engine supports numeric × numeric feature pairs only.")
    alphas = [item.get("interaction_alpha") for item in selected.get("per_fold", [])]
    alphas = [float(value) for value in alphas if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(float(value)) and float(value) > 0]
    if not alphas:
        raise ValueError("Selected interaction catalogue entry has no valid per-fold interaction alpha values.")
    return selected, {"report": report, "manifest": manifest, "report_sha256": expected_report_hash,
                      "selected_alpha_values": alphas, "selected_alpha_median": _quantile(alphas, 0.5)}


def _load_robustness_selection(robustness_dir: Path | None, interaction_id: str,
                               cohort_dir: Path, task_path: Path) -> dict[str, Any] | None:
    if robustness_dir is None:
        return None
    report_path = robustness_dir / "interaction_robustness_report.json"
    manifest_path = robustness_dir / "interaction_robustness_manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("robustness_dir must contain interaction_robustness_report.json and interaction_robustness_manifest.json.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_inputs = {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "task_sha256": sha256_file(task_path),
    }
    for key, value in expected_inputs.items():
        if manifest.get("input_hashes", {}).get(key) != value:
            raise ValueError("Interaction robustness manifest does not match current input: " + key)
    if manifest.get("output_hashes", {}).get("interaction_robustness_report.json") != sha256_file(report_path):
        raise ValueError("Interaction robustness report hash does not match its manifest.")
    matches = [item for item in report.get("interaction_catalogue", [])
               if item.get("interaction_id") == interaction_id]
    return matches[0] if len(matches) == 1 else None


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inside_convex_hull(point: tuple[float, float], hull: list[tuple[float, float]]) -> bool:
    if len(hull) < 3:
        return False
    signs = []
    for index, start in enumerate(hull):
        end = hull[(index + 1) % len(hull)]
        cross = ((end[0] - start[0]) * (point[1] - start[1]) -
                 (end[1] - start[1]) * (point[0] - start[0]))
        if abs(cross) > 1e-10:
            signs.append(cross > 0)
    return not signs or all(value == signs[0] for value in signs)


def _nearest_distances(points: list[tuple[float, float]], query: tuple[float, float],
                       scales: tuple[float, float]) -> list[float]:
    return [math.sqrt(((query[0] - point[0]) / scales[0]) ** 2 +
                      ((query[1] - point[1]) / scales[1]) ** 2) for point in points]


def _percentile(values: list[float], quantile: float) -> float:
    value = _quantile(values, quantile)
    if value is None:
        raise ValueError("Cannot calculate percentile from an empty sequence.")
    return float(value)


def _grid(low: float, high: float, size: int) -> list[float]:
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        raise ValueError("Each selected numeric feature must have a non-zero finite observed range.")
    return [low + (high - low) * index / (size - 1) for index in range(size)]


def _background_rows(rows: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    if len(rows) <= maximum:
        return rows
    indices = sorted({round(index * (len(rows) - 1) / (maximum - 1)) for index in range(maximum)})
    return [rows[index] for index in indices]


def _partial_dependence_predictions(
    grid_x: list[float], grid_y: list[float], background: list[dict[str, Any]],
    feature_a: str, feature_b: str, encoder: dict[str, Any],
    model: dict[str, Any], pair_columns: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    surface: list[dict[str, Any]] = []
    for y_value in grid_y:
        for x_value in grid_x:
            varied = []
            for row in background:
                item = dict(row)
                item[feature_a] = x_value
                item[feature_b] = y_value
                varied.append(item)
            base_matrix = _transform_rows(varied, encoder)
            matrix = _append_pair_products(base_matrix, pair_columns)
            predictions = _predict_ridge(matrix, model)
            surface.append({"feature_a_value": x_value, "feature_b_value": y_value,
                            "predicted_mean": sum(predictions) / len(predictions)})
    return surface


def _finite_difference(values: list[float], coordinates: list[float], index: int) -> float:
    if index == 0:
        return (values[1] - values[0]) / (coordinates[1] - coordinates[0])
    if index == len(values) - 1:
        return (values[-1] - values[-2]) / (coordinates[-1] - coordinates[-2])
    return (values[index + 1] - values[index - 1]) / (coordinates[index + 1] - coordinates[index - 1])


def generate_interaction_surface_files(
    cohort_dir: Path,
    task_path: Path,
    interaction_dir: Path,
    interaction_id: str,
    output_dir: Path,
    robustness_dir: Path | None = None,
    grid_size: int | None = None,
    background_max: int | None = None,
) -> dict[str, Any]:
    cohort_dir = cohort_dir.expanduser().resolve()
    task_path = task_path.expanduser().resolve()
    interaction_dir = interaction_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    robustness_dir = robustness_dir.expanduser().resolve() if robustness_dir else None
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty response-surface output directory: " + str(output_dir))

    rows_raw, task, split_manifest, cohort_manifest = _load_cohort(cohort_dir, task_path)
    if task.get("outcome_type") != "NUMERIC":
        raise ValueError("Response surfaces currently require a NUMERIC endpoint.")
    selected, selection_meta = _load_interaction_selection(interaction_dir, interaction_id, cohort_dir, task_path, task)
    robustness = _load_robustness_selection(robustness_dir, interaction_id, cohort_dir, task_path)
    settings = _surface_settings(task, grid_size, background_max)
    rows = _typed_rows(rows_raw, task)
    bindings = task["feature_bindings"]
    feature_a, feature_b = selected["feature_a"], selected["feature_b"]
    values_a = [float(row[feature_a]) for row in rows]
    values_b = [float(row[feature_b]) for row in rows]
    if any(not math.isfinite(value) for value in values_a + values_b):
        raise ValueError("Selected pair contains non-finite numeric values.")
    range_q = settings["range_quantiles"]
    range_a = (_percentile(values_a, range_q[0]), _percentile(values_a, range_q[1]))
    range_b = (_percentile(values_b, range_q[0]), _percentile(values_b, range_q[1]))
    axis_a = _grid(range_a[0], range_a[1], settings["grid_size"])
    axis_b = _grid(range_b[0], range_b[1], settings["grid_size"])

    encoder, _ = _fit_encoder(rows, bindings)
    pair_columns = _encode_pair_columns(encoder, feature_a, feature_b, 10)
    if len(pair_columns) != 1:
        raise ValueError("Numeric × numeric response surfaces require exactly one encoded product term.")
    alpha = float(selection_meta["selected_alpha_median"])
    model_settings = _settings(task)
    base_matrix = _transform_rows(rows, encoder)
    interaction_matrix = _append_pair_products(base_matrix, pair_columns)
    model = _fit_ridge(interaction_matrix, [row["outcome"] for row in rows],
                       alpha, model_settings["max_iter"], model_settings["tolerance"])
    if not model["converged"]:
        raise RuntimeError("Full-cohort descriptive interaction refit did not converge; response surface was not generated.")

    background = _background_rows(rows, settings["background_max_observations"])
    surface = _partial_dependence_predictions(axis_a, axis_b, background, feature_a, feature_b,
                                               encoder, model, pair_columns)
    matrix = {(item["feature_a_value"], item["feature_b_value"]): item["predicted_mean"] for item in surface}

    points = list(zip(values_a, values_b))
    mean_a = sum(values_a) / len(values_a)
    mean_b = sum(values_b) / len(values_b)
    scale_a = math.sqrt(sum((value - mean_a) ** 2 for value in values_a) / len(values_a))
    scale_b = math.sqrt(sum((value - mean_b) ** 2 for value in values_b) / len(values_b))
    scale_a = scale_a if scale_a > 1e-12 else 1.0
    scale_b = scale_b if scale_b > 1e-12 else 1.0
    # Repeated observations at identical setpoints must not collapse the density threshold to zero.
    unique_points = sorted(set(points))
    if len(unique_points) < 3:
        raise ValueError("At least three distinct observed feature-pair coordinates are required to estimate a 2D response-surface support region.")
    nearest_distances = []
    for index, point in enumerate(unique_points):
        distances = _nearest_distances(unique_points[:index] + unique_points[index+1:], point, (scale_a, scale_b))
        if distances:
            nearest_distances.append(min(distances))
    support_threshold = _percentile(nearest_distances, settings["support_distance_quantile"])
    hull = _convex_hull(unique_points)

    # The derivative is in outcome units per raw feature unit. Ridge uses standardized features.
    feature_a_column = next(i for i, item in enumerate(encoder["columns"]) if item["feature_id"] == feature_a)
    feature_b_column = next(i for i, item in enumerate(encoder["columns"]) if item["feature_id"] == feature_b)
    interaction_coefficient = model["coefficients"][len(encoder["columns"])]
    cross_partial = (model["target_scale"] * interaction_coefficient /
                     (encoder["standardizer"]["scales"][feature_a_column] *
                      encoder["standardizer"]["scales"][feature_b_column]))

    grid_lookup = {(x, y): value for (x, y), value in matrix.items()}
    rows_out = []
    for j, y_value in enumerate(axis_b):
        row_predictions = [grid_lookup[(x_value, y_value)] for x_value in axis_a]
        derivative_b_column = []
        for i, x_value in enumerate(axis_a):
            d_a = _finite_difference(row_predictions, axis_a, i)
            column_values = [grid_lookup[(x_value, y)] for y in axis_b]
            d_b = _finite_difference(column_values, axis_b, j)
            nearest = min(_nearest_distances(points, (x_value, y_value), (scale_a, scale_b)))
            inside = _inside_convex_hull((x_value, y_value), hull)
            if len(hull) < 3:
                support_status = "SUPPORT_NOT_ESTIMABLE"
            elif not inside:
                support_status = "OUTSIDE_OBSERVED_CONVEX_HULL"
            elif nearest > support_threshold:
                support_status = "LOW_LOCAL_DENSITY"
            else:
                support_status = "SUPPORTED_EMPIRICAL_2D_REGION"
            rows_out.append({
                "feature_a_value": x_value, "feature_b_value": y_value,
                "predicted_mean": grid_lookup[(x_value, y_value)],
                "support_status": support_status, "inside_observed_convex_hull": inside,
                "nearest_reference_distance": nearest, "reference_distance_threshold": support_threshold,
                "marginal_effect_feature_a": d_a, "marginal_effect_feature_b": d_b,
                "cross_partial_derivative": cross_partial
            })
    supported_count = sum(1 for item in rows_out if item["support_status"] == "SUPPORTED_EMPIRICAL_2D_REGION")
    support_counts = {status: sum(1 for item in rows_out if item["support_status"] == status)
                      for status in ("SUPPORTED_EMPIRICAL_2D_REGION", "LOW_LOCAL_DENSITY",
                                     "OUTSIDE_OBSERVED_CONVEX_HULL", "SUPPORT_NOT_ESTIMABLE")}
    observed = [{
        "observation_id": row["observation_id"], "study_id": row["study_id"],
        "feature_a_value": float(row[feature_a]), "feature_b_value": float(row[feature_b]),
        "actual_outcome": float(row["outcome"])
    } for row in rows]
    report = {
        "schema_version": "1.0", "task_id": task["task_id"], "target_id": task["target_id"],
        "endpoint_definition": task["endpoint_definition"], "interaction_id": interaction_id,
        "feature_a": feature_a, "feature_b": feature_b, "outcome_unit": task.get("outcome_unit"),
        "source_interaction_status": selected.get("interpretation_status"),
        "robustness_status": robustness.get("robustness_status") if robustness else "NOT_SUPPLIED",
        "method": "ALL_COHORT_DESCRIPTIVE_REFIT_FROM_MEDIAN_NESTED_ALPHA",
        "prediction_mode": "PARTIAL_DEPENDENCE_AVERAGED_OVER_EMPIRICAL_BACKGROUND",
        "model": {"type": "PAIRWISE_BILINEAR_RIDGE", "alpha": alpha,
                  "alpha_values_from_nested_folds": selection_meta["selected_alpha_values"],
                  "converged": model["converged"], "iterations": model["iterations"]},
        "cohort": {"observation_count": len(rows), "study_count": len({row["study_id"] for row in rows}),
                   "distinct_observed_feature_pairs": len(unique_points),
                   "background_observation_count": len(background),
                   "background_sampling": "DETERMINISTIC_EVENLY_SPACED_ROWS" if len(background) < len(rows) else "ALL_ELIGIBLE_ROWS"},
        "grid": {"grid_size_per_axis": settings["grid_size"], "grid_point_count": len(rows_out),
                 "feature_a_range": list(range_a), "feature_b_range": list(range_b),
                 "range_quantiles": range_q},
        "empirical_support": {"method": "2D_CONVEX_HULL_AND_Q_NEAREST_NEIGHBOUR_DISTANCE",
                              "distance_quantile": settings["support_distance_quantile"],
                              "distance_threshold": support_threshold,
                              "feature_a_scale": scale_a, "feature_b_scale": scale_b,
                              "convex_hull_vertices": [{"feature_a": x, "feature_b": y} for x, y in hull],
                              "grid_status_counts": support_counts,
                              "supported_grid_fraction": supported_count / len(rows_out)},
        "marginal_effects": {"definition": "Finite differences of the partial-dependence surface in raw feature units.",
                             "feature_a_unit": next(item["expected_unit"] for item in bindings if item["feature_id"] == feature_a),
                             "feature_b_unit": next(item["expected_unit"] for item in bindings if item["feature_id"] == feature_b),
                             "cross_partial_derivative": cross_partial,
                             "cross_partial_derivative_unit": "outcome_unit / feature_a_unit / feature_b_unit"},
        "interpretation_limits": [
            "The response surface is a descriptive full-cohort refit using the median Ridge alpha selected in the nested interaction folds; it is not an independent validation result.",
            "Partial dependence averages over observed values of all other features. When covariates are correlated, some constructed combinations may be unrealistic.",
            "The 2D support mask describes only the selected feature pair; it does not establish support in the full multivariable condition space.",
            "Convex-hull and nearest-neighbour support labels are empirical heuristics, not physical boundaries or calibrated probabilities.",
            "Predictions in LOW_LOCAL_DENSITY, OUTSIDE_OBSERVED_CONVEX_HULL, or SUPPORT_NOT_ESTIMABLE regions must not be presented as empirically supported response.",
            "Marginal effects are model-derived slopes, not causal effects. The cross-partial derivative is a property of this bilinear model basis, not proof of a physical mechanism."
        ],
        "validation_scope": "DESCRIPTIVE_RESPONSE_SURFACE_NOT_INDEPENDENT_VALIDATION_OR_CAUSAL_INFERENCE"
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "interaction_response_surface_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    grid_path = output_dir / "interaction_response_surface.csv"
    grid_fields = ["feature_a_value", "feature_b_value", "predicted_mean", "support_status",
                   "inside_observed_convex_hull", "nearest_reference_distance", "reference_distance_threshold",
                   "marginal_effect_feature_a", "marginal_effect_feature_b", "cross_partial_derivative"]
    with grid_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=grid_fields)
        writer.writeheader()
        writer.writerows(rows_out)
    observed_path = output_dir / "interaction_observed_support.csv"
    with observed_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["observation_id", "study_id", "feature_a_value", "feature_b_value", "actual_outcome"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(observed)
    marginal_path = output_dir / "interaction_marginal_effects.csv"
    with marginal_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["feature_a_value", "feature_b_value", "marginal_effect_feature_a",
                  "marginal_effect_feature_b", "cross_partial_derivative", "support_status"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{key: item[key] for key in fields} for item in rows_out])

    input_hashes = {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "task_sha256": sha256_file(task_path),
        "interaction_discovery_report_sha256": selection_meta["report_sha256"],
        "interaction_discovery_manifest_sha256": sha256_file(interaction_dir / "interaction_discovery_manifest.json"),
    }
    if robustness_dir:
        input_hashes["interaction_robustness_report_sha256"] = sha256_file(robustness_dir / "interaction_robustness_report.json")
        input_hashes["interaction_robustness_manifest_sha256"] = sha256_file(robustness_dir / "interaction_robustness_manifest.json")
    artifact_names = ["interaction_response_surface_report.json", "interaction_response_surface.csv",
                      "interaction_observed_support.csv", "interaction_marginal_effects.csv"]
    output_hashes = {name: sha256_file(output_dir / name) for name in artifact_names}
    manifest = {
        "schema_version": "1.0", "engine_version": ENGINE_VERSION,
        "task_id": task["task_id"], "interaction_id": interaction_id,
        "input_hashes": input_hashes, "output_hashes": output_hashes,
        "grid_point_count": len(rows_out), "observation_count": len(rows),
        "study_count": len({row["study_id"] for row in rows}),
        "method": report["method"], "prediction_mode": report["prediction_mode"],
        "claim_scope": "DESCRIPTIVE_MODEL_RESPONSE_NOT_INDEPENDENT_VALIDATION_CAUSALITY_OR_MECHANISM",
        "source_policy": "COHORT_TASK_AND_INTERACTION_EVIDENCE_READ_ONLY"
    }
    manifest_path = output_dir / "interaction_response_surface_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"valid": True, "report": report, "manifest": manifest, "output_dir": str(output_dir)}
