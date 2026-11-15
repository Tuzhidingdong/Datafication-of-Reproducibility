"""Nested study-group cross-validation and feature-space support diagnostics."""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file
from dor.modeling import (
    _classification_metrics, _fit_encoder, _fit_naive_bayes, _fit_ridge,
    _finite_number, _fit_standardizer, _apply_standardizer, _majority_model,
    _partition, _predict_majority, _predict_naive_bayes, _predict_ridge,
    _regression_metrics, _settings, _transform_rows, _typed_rows, _load_cohort,
)

ENGINE_VERSION = "dor-runtime/0.1.0"
DEFAULT_FOLDS = 5
DEFAULT_VALIDATION_STUDY_FRACTION = 0.2
DOMAIN_DISTANCE_QUANTILE = 0.95


def _stable_order(ids: list[str], seed: int, scope: str) -> list[str]:
    return sorted(ids, key=lambda sid: hashlib.sha256((str(seed) + ":" + scope + ":" + sid).encode("utf-8")).hexdigest())


def _grouped_folds(study_ids: list[str], folds: int, seed: int) -> list[list[str]]:
    ordered = _stable_order(sorted(set(study_ids)), seed, "outer")
    groups = [[] for _ in range(folds)]
    for index, study_id in enumerate(ordered):
        groups[index % folds].append(study_id)
    return [group for group in groups if group]


def _validation_studies(outer_train_ids: list[str], seed: int, fold_index: int,
                        fraction: float = DEFAULT_VALIDATION_STUDY_FRACTION) -> tuple[set[str], set[str]]:
    ordered = _stable_order(outer_train_ids, seed, "inner-" + str(fold_index))
    count = max(1, int(math.ceil(len(ordered) * fraction)))
    count = min(count, len(ordered) - 2)
    validation = set(ordered[:count])
    training = set(ordered[count:])
    return training, validation


def _select_numeric_candidate(train: list[dict[str, Any]], validation: list[dict[str, Any]],
                              bindings: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, float | None, list[dict[str, Any]]]:
    y_train = [row["outcome"] for row in train]
    y_validation = [row["outcome"] for row in validation]
    comparisons: list[dict[str, Any]] = []
    mean_prediction = sum(y_train) / len(y_train)
    mean_metrics = _regression_metrics(y_validation, [mean_prediction] * len(validation))
    comparisons.append({"candidate_id": "mean_baseline", "model_type": "mean_baseline",
                        "alpha": None, "validation_metrics": mean_metrics, "converged": True,
                        "eligible_for_selection": True})
    encoder, x_train = _fit_encoder(train, bindings)
    x_validation = _transform_rows(validation, encoder)
    for alpha in settings["ridge_alphas"]:
        fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
        validation_metrics = _regression_metrics(y_validation, _predict_ridge(x_validation, fitted)) if fitted["converged"] else None
        comparisons.append({"candidate_id": "ridge_alpha_" + format(alpha, ".12g"),
            "model_type": "ridge_regression", "alpha": alpha,
            "validation_metrics": validation_metrics,
            "converged": fitted["converged"], "iterations": fitted["iterations"],
            "eligible_for_selection": bool(fitted["converged"]),
            "exclusion_reason": None if fitted["converged"] else "RIDGE_FIT_NOT_CONVERGED"})
    eligible_comparisons = [item for item in comparisons if item.get("eligible_for_selection") is True]
    chosen = min(eligible_comparisons, key=lambda item: (item["validation_metrics"]["rmse"],
        0 if item["model_type"] == "mean_baseline" else 1, item.get("alpha") or 0))
    return chosen["candidate_id"], chosen.get("alpha"), comparisons


def _predict_numeric_candidate(train: list[dict[str, Any]], test: list[dict[str, Any]],
                               bindings: list[dict[str, Any]], candidate_id: str,
                               alpha: float | None, settings: dict[str, Any]) -> tuple[list[float], str, bool | None]:
    y_train = [row["outcome"] for row in train]
    if candidate_id == "mean_baseline":
        return [sum(y_train) / len(y_train)] * len(test), "mean_baseline", True
    if alpha is None:
        raise ValueError("Selected Ridge candidate is missing alpha.")
    encoder, x_train = _fit_encoder(train, bindings)
    fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
    if not fitted["converged"]:
        baseline = sum(y_train) / len(y_train)
        return [baseline] * len(test), "mean_baseline_fallback_nonconverged", False
    predictions = _predict_ridge(_transform_rows(test, encoder), fitted)
    return predictions, "ridge_regression", True


def _select_categorical_candidate(train: list[dict[str, Any]], validation: list[dict[str, Any]],
                                  bindings: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, float | None, list[dict[str, Any]]]:
    y_train = [row["outcome"] for row in train]
    y_validation = [row["outcome"] for row in validation]
    majority = _majority_model(y_train)
    baseline_predictions = _predict_majority(majority, len(validation))
    comparisons: list[dict[str, Any]] = [{
        "candidate_id": "majority_class_baseline", "model_type": "majority_class_baseline",
        "smoothing": None, "validation_metrics": _classification_metrics(y_validation, baseline_predictions)
    }]
    for smoothing in settings["naive_bayes_smoothing"]:
        fitted = _fit_naive_bayes(train, bindings, y_train, smoothing, settings["naive_bayes_variance_floor"])
        predictions = _predict_naive_bayes(validation, fitted)
        comparisons.append({
            "candidate_id": "naive_bayes_alpha_" + format(smoothing, ".12g"),
            "model_type": "mixed_naive_bayes", "smoothing": smoothing,
            "validation_metrics": _classification_metrics(y_validation, predictions)
        })
    chosen = max(comparisons, key=lambda item: (item["validation_metrics"]["macro_f1"],
        1 if item["model_type"] == "majority_class_baseline" else 0,
        -(item.get("smoothing") or 0)))
    return chosen["candidate_id"], chosen.get("smoothing"), comparisons


def _predict_categorical_candidate(train: list[dict[str, Any]], test: list[dict[str, Any]],
                                   bindings: list[dict[str, Any]], candidate_id: str,
                                   smoothing: float | None, settings: dict[str, Any]) -> tuple[list[str], str]:
    y_train = [row["outcome"] for row in train]
    if candidate_id == "majority_class_baseline":
        return _predict_majority(_majority_model(y_train), len(test)), "majority_class_baseline"
    if smoothing is None:
        raise ValueError("Selected Naive Bayes candidate is missing smoothing.")
    fitted = _fit_naive_bayes(train, bindings, y_train, smoothing, settings["naive_bayes_variance_floor"])
    return _predict_naive_bayes(test, fitted), "mixed_naive_bayes"


def _feature_distance(a: dict[str, Any], b: dict[str, Any], bindings: list[dict[str, Any]],
                      scales: dict[str, float]) -> float:
    contributions = []
    for binding in bindings:
        fid = binding["feature_id"]
        if binding["value_type"] == "NUMERIC":
            contributions.append((float(a[fid]) - float(b[fid])) / scales[fid])
        else:
            contributions.append(0.0 if str(a[fid]) == str(b[fid]) else 1.0)
    return math.sqrt(sum(value * value for value in contributions) / len(contributions)) if contributions else 0.0


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _domain_diagnostics(reference: list[dict[str, Any]], queries: list[dict[str, Any]],
                        bindings: list[dict[str, Any]], fold_index: int) -> list[dict[str, Any]]:
    if len(reference) < 2:
        return [{"observation_id": row["observation_id"], "study_id": row["study_id"],
                 "fold": fold_index, "status": "REVIEW_REQUIRED",
                 "nearest_reference_distance": None, "reference_distance_q95": None,
                 "outside_numeric_training_range": None, "unseen_categorical_level": None,
                 "warning_reasons": ["INSUFFICIENT_REFERENCE_ROWS"]} for row in queries]
    scales: dict[str, float] = {}
    numeric_ranges: dict[str, tuple[float, float]] = {}
    category_levels: dict[str, set[str]] = {}
    for binding in bindings:
        fid = binding["feature_id"]
        values = [row[fid] for row in reference]
        if binding["value_type"] == "NUMERIC":
            numbers = [float(value) for value in values]
            mean = sum(numbers) / len(numbers)
            variance = sum((value - mean) ** 2 for value in numbers) / len(numbers)
            scale = math.sqrt(variance)
            scales[fid] = scale if scale > 1e-12 else 1.0
            numeric_ranges[fid] = (min(numbers), max(numbers))
        else:
            category_levels[fid] = {str(value) for value in values}
    training_nearest = []
    for index, row in enumerate(reference):
        distances = [_feature_distance(row, other, bindings, scales)
                     for j, other in enumerate(reference) if j != index]
        if distances:
            training_nearest.append(min(distances))
    threshold = _quantile(training_nearest, DOMAIN_DISTANCE_QUANTILE)
    results = []
    for row in queries:
        distances = [_feature_distance(row, other, bindings, scales) for other in reference]
        nearest = min(distances) if distances else None
        outside = any(float(row[fid]) < limits[0] or float(row[fid]) > limits[1]
                      for fid, limits in numeric_ranges.items())
        unseen = any(str(row[fid]) not in levels for fid, levels in category_levels.items())
        reasons = []
        if outside:
            reasons.append("NUMERIC_FEATURE_OUTSIDE_REFERENCE_RANGE")
        if unseen:
            reasons.append("UNSEEN_CATEGORICAL_LEVEL")
        if threshold is not None and nearest is not None and nearest > threshold:
            reasons.append("NEAREST_REFERENCE_DISTANCE_ABOVE_EMPIRICAL_Q95")
        status = "OUT_OF_DOMAIN" if reasons else ("IN_DOMAIN" if threshold is not None else "REVIEW_REQUIRED")
        results.append({
            "observation_id": row["observation_id"], "study_id": row["study_id"],
            "fold": fold_index, "status": status,
            "nearest_reference_distance": nearest, "reference_distance_q95": threshold,
            "outside_numeric_training_range": outside, "unseen_categorical_level": unseen,
            "warning_reasons": reasons
        })
    return results


def _study_metrics(rows: list[dict[str, Any]], outcome_type: str) -> list[dict[str, Any]]:
    by_study: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_study.setdefault(row["study_id"], []).append(row)
    results = []
    for study_id in sorted(by_study):
        values = by_study[study_id]
        actual = [row["actual"] for row in values]
        predicted = [row["prediction"] for row in values]
        item: dict[str, Any] = {"study_id": study_id, "fold": values[0]["fold"], "n": len(values)}
        if outcome_type == "NUMERIC":
            metrics = _regression_metrics(actual, predicted)
            item.update(metrics)
            item["mean_signed_error"] = sum(predicted[i] - actual[i] for i in range(len(actual))) / len(actual)
        else:
            metrics = _classification_metrics(actual, predicted)
            item.update({"accuracy": metrics["accuracy"], "balanced_accuracy": metrics["balanced_accuracy"],
                         "macro_f1": metrics["macro_f1"], "confusion_matrix": metrics["confusion_matrix"]})
        item["selected_model"] = values[0]["selected_model"]
        results.append(item)
    return results


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "sd": None, "q95": None}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {"n": len(values), "mean": mean, "median": _quantile(values, 0.5),
            "sd": math.sqrt(variance), "q95": _quantile(values, 0.95)}


def evaluate_reproducibility_files(cohort_dir: Path, task_path: Path, output_dir: Path,
                                   folds: int | None = None, seed: int = 42) -> dict[str, Any]:
    cohort_dir = cohort_dir.expanduser().resolve()
    task_path = task_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty evaluation output directory: " + str(output_dir))
    rows_raw, task, split_manifest, cohort_manifest = _load_cohort(cohort_dir, task_path)
    settings = _settings(task)
    rows = _typed_rows(rows_raw, task)
    study_ids = sorted({row["study_id"] for row in rows})
    if folds is None:
        folds = min(DEFAULT_FOLDS, len(study_ids))
    if not isinstance(folds, int) or isinstance(folds, bool) or folds < 4:
        raise ValueError("Grouped nested evaluation requires folds >= 4 and at least four eligible Studies.")
    if folds > len(study_ids):
        raise ValueError("Requested folds exceed the number of eligible Studies.")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer.")
    bindings = task["feature_bindings"]
    fold_groups = _grouped_folds(study_ids, folds, seed)
    predictions: list[dict[str, Any]] = []
    domain_rows: list[dict[str, Any]] = []
    fold_reports: list[dict[str, Any]] = []

    for fold_index, test_studies in enumerate(fold_groups, start=1):
        outer_train_studies = sorted(set(study_ids) - set(test_studies))
        inner_train_studies, inner_validation_studies = _validation_studies(outer_train_studies, seed, fold_index)
        inner_train = [row for row in rows if row["study_id"] in inner_train_studies]
        inner_validation = [row for row in rows if row["study_id"] in inner_validation_studies]
        outer_train = [row for row in rows if row["study_id"] in outer_train_studies]
        outer_test = [row for row in rows if row["study_id"] in test_studies]
        if len({row["study_id"] for row in inner_train}) < 2 or not inner_validation or not outer_test:
            raise ValueError("A nested fold does not have sufficient Study-level training, validation, and test data.")

        if task["outcome_type"] == "NUMERIC":
            candidate_id, alpha, comparisons = _select_numeric_candidate(inner_train, inner_validation, bindings, settings)
            fold_predictions, selected_model, converged = _predict_numeric_candidate(
                outer_train, outer_test, bindings, candidate_id, alpha, settings)
            actual = [row["outcome"] for row in outer_test]
            fold_metrics = _regression_metrics(actual, fold_predictions)
            baseline_predictions = [sum(row["outcome"] for row in outer_train) / len(outer_train)] * len(outer_test)
            baseline_metrics = _regression_metrics(actual, baseline_predictions)
            model_meta = {"selected_candidate_id": candidate_id, "alpha": alpha, "converged": converged,
                          "outer_refit_fallback": selected_model == "mean_baseline_fallback_nonconverged",
                          "fallback_reason": "RIDGE_OUTER_REFIT_NOT_CONVERGED" if selected_model == "mean_baseline_fallback_nonconverged" else None}
        else:
            candidate_id, smoothing, comparisons = _select_categorical_candidate(inner_train, inner_validation, bindings, settings)
            fold_predictions, selected_model = _predict_categorical_candidate(
                outer_train, outer_test, bindings, candidate_id, smoothing, settings)
            actual = [row["outcome"] for row in outer_test]
            fold_metrics = _classification_metrics(actual, fold_predictions)
            baseline_predictions = _predict_majority(_majority_model([row["outcome"] for row in outer_train]), len(outer_test))
            baseline_metrics = _classification_metrics(actual, baseline_predictions)
            model_meta = {"selected_candidate_id": candidate_id, "smoothing": smoothing}
        for index, row in enumerate(outer_test):
            predictions.append({
                "observation_id": row["observation_id"], "study_id": row["study_id"],
                "fold": fold_index, "selected_model": selected_model,
                "actual": row["outcome"], "prediction": fold_predictions[index],
                "baseline_prediction": baseline_predictions[index]
            })
        domain_rows.extend(_domain_diagnostics(outer_train, outer_test, bindings, fold_index))
        fold_reports.append({
            "fold": fold_index, "test_study_ids": sorted(test_studies),
            "outer_training_study_ids": outer_train_studies,
            "inner_training_study_ids": sorted(inner_train_studies),
            "inner_validation_study_ids": sorted(inner_validation_studies),
            "selected_model": selected_model, **model_meta,
            "inner_validation_comparison": comparisons,
            "outer_test_metrics": fold_metrics,
            "outer_test_baseline_metrics": baseline_metrics,
            "train_observation_count": len(outer_train),
            "test_observation_count": len(outer_test)
        })

    predictions.sort(key=lambda row: (row["study_id"], row["observation_id"]))
    study_performance = _study_metrics(predictions, task["outcome_type"])
    actual_all = [row["actual"] for row in predictions]
    predicted_all = [row["prediction"] for row in predictions]
    baseline_all = [row["baseline_prediction"] for row in predictions]
    if task["outcome_type"] == "NUMERIC":
        pooled_metrics = _regression_metrics(actual_all, predicted_all)
        pooled_baseline = _regression_metrics(actual_all, baseline_all)
        study_bias = [row["mean_signed_error"] for row in study_performance]
        error_distribution = _distribution([abs(predicted_all[i] - actual_all[i]) for i in range(len(actual_all))])
        bias_distribution = _distribution(study_bias)
    else:
        pooled_metrics = _classification_metrics(actual_all, predicted_all)
        pooled_baseline = _classification_metrics(actual_all, baseline_all)
        error_distribution = _distribution([0.0 if predicted_all[i] == actual_all[i] else 1.0 for i in range(len(actual_all))])
        bias_distribution = None

    selection_counts: dict[str, int] = {}
    for fold in fold_reports:
        key = fold["selected_model"]
        selection_counts[key] = selection_counts.get(key, 0) + 1
    domain_counts = {status: sum(1 for row in domain_rows if row["status"] == status)
                     for status in ("IN_DOMAIN", "OUT_OF_DOMAIN", "REVIEW_REQUIRED")}
    report = {
        "schema_version": "1.0", "task_id": task["task_id"], "target_id": task["target_id"],
        "endpoint_definition": task["endpoint_definition"], "outcome_type": task["outcome_type"],
        "fold_count": len(fold_reports), "study_count": len(study_ids),
        "observation_count": len(predictions), "seed": seed,
        "outer_split_strategy": "DETERMINISTIC_GROUPED_K_FOLD_BY_STUDY",
        "inner_selection_strategy": "NESTED_STUDY_HOLDOUT_WITHIN_OUTER_TRAINING_STUDIES",
        "pooled_out_of_fold_metrics": pooled_metrics,
        "pooled_baseline_metrics": pooled_baseline,
        "per_study_performance": study_performance,
        "between_study_error_or_bias_distribution": {
            "absolute_error_distribution": error_distribution,
            "study_mean_signed_error_distribution": bias_distribution
        },
        "folds": fold_reports,
        "model_selection_frequency": selection_counts,
        "applicability_domain": {
            "method": "MIXED_FEATURE_NEAREST_NEIGHBOUR_DISTANCE",
            "distance_definition": "Root mean square of per-feature distances; numeric differences scaled by outer-training SD (constant feature scale set to 1); categorical mismatch contributes 1.",
            "reference_threshold": "95th percentile of leave-one-out nearest-neighbour distances among outer-training observations.",
            "quantile": DOMAIN_DISTANCE_QUANTILE, "counts": domain_counts,
            "warning": "Heuristic support diagnostic only; it is not a calibrated probability, confidence interval, or proof of physical extrapolation."
        },
        "uncertainty": {
            "status": "NOT_CALIBRATED",
            "reason": "This evaluation reports nested held-out-study error distributions. It does not convert them into prediction intervals or calibrated probabilities.",
            "descriptive_absolute_error_distribution": error_distribution
        },
        "validation_scope": "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION"
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reproducibility_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    prediction_fields = ["observation_id", "study_id", "fold", "selected_model", "actual", "prediction", "baseline_prediction"]
    with (output_dir / "cross_study_predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prediction_fields)
        writer.writeheader()
        writer.writerows(predictions)
    study_fields = sorted({key for row in study_performance for key in row})
    with (output_dir / "study_performance.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=study_fields)
        writer.writeheader()
        for row in study_performance:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})
    domain_fields = ["observation_id", "study_id", "fold", "status", "nearest_reference_distance",
                     "reference_distance_q95", "outside_numeric_training_range",
                     "unseen_categorical_level", "warning_reasons"]
    with (output_dir / "applicability_domain.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=domain_fields)
        writer.writeheader()
        for row in domain_rows:
            writer.writerow({**row, "warning_reasons": json.dumps(row["warning_reasons"], ensure_ascii=False)})
    input_hashes = {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "cohort_report_sha256": sha256_file(cohort_dir / "cohort_report.json"),
        "split_manifest_sha256": sha256_file(cohort_dir / "split_manifest.json"),
        "cohort_manifest_sha256": sha256_file(cohort_dir / "modeling_cohort_manifest.json"),
        "task_sha256": sha256_file(task_path)
    }
    output_names = ["reproducibility_evaluation.json", "cross_study_predictions.csv",
                    "study_performance.csv", "applicability_domain.csv"]
    output_hashes = {name: sha256_file(output_dir / name) for name in output_names}
    manifest = {
        "schema_version": "1.0", "task_id": task["task_id"], "engine_version": ENGINE_VERSION,
        "input_hashes": input_hashes, "output_hashes": output_hashes,
        "fold_count": len(fold_reports), "seed": seed,
        "study_ids": study_ids, "selection_protocol": "NESTED_INNER_STUDY_HOLDOUT",
        "test_protocol": "OUTER_GROUPED_K_FOLD_EACH_STUDY_HELD_OUT_ONCE",
        "applicability_domain_method": "MIXED_FEATURE_NEAREST_NEIGHBOUR_EMPIRICAL_REFERENCE_Q95",
        "uncertainty_status": "DESCRIPTIVE_CROSS_STUDY_ERROR_ONLY_NOT_CALIBRATED",
        "source_policy": "COHORT_AND_TASK_READ_ONLY; EACH_OUTER_TEST_STUDY_EXCLUDED_FROM_ALL_FITTING_AND_INNER_SELECTION"
    }
    (output_dir / "reproducibility_evaluation_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"valid": True, "report": report, "manifest": manifest, "output_dir": str(output_dir)}
