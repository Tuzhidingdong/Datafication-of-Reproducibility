"""Deterministic baseline model fitting, validation-based selection, and held-out evaluation."""
from __future__ import annotations
import csv, json, math
from pathlib import Path
from typing import Any
from dor.mapping import sha256_file

ENGINE_VERSION = "dor-runtime/0.1.0"
DEFAULT_RIDGE_ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0]
DEFAULT_NB_SMOOTHING = [0.1, 1.0, 10.0]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _settings(task: dict[str, Any]) -> dict[str, Any]:
    settings = task.get("modeling", {})
    if not isinstance(settings, dict):
        raise ValueError("The optional modeling settings must be an object.")
    if task["outcome_type"] == "NUMERIC":
        alphas = settings.get("ridge_alphas", DEFAULT_RIDGE_ALPHAS)
        if not isinstance(alphas, list) or not alphas or any(not _finite_number(x) or float(x) <= 0 for x in alphas):
            raise ValueError("modeling.ridge_alphas must be a non-empty list of positive finite numbers.")
        if len(set(float(x) for x in alphas)) != len(alphas):
            raise ValueError("modeling.ridge_alphas must not contain duplicates.")
        max_iter = settings.get("max_iter", 2000)
        tolerance = settings.get("tolerance", 1e-8)
        if not isinstance(max_iter, int) or isinstance(max_iter, bool) or max_iter < 1:
            raise ValueError("modeling.max_iter must be a positive integer.")
        if not _finite_number(tolerance) or float(tolerance) <= 0:
            raise ValueError("modeling.tolerance must be a positive finite number.")
        return {"ridge_alphas": [float(x) for x in alphas], "max_iter": max_iter, "tolerance": float(tolerance)}
    smoothing = settings.get("naive_bayes_smoothing", DEFAULT_NB_SMOOTHING)
    if not isinstance(smoothing, list) or not smoothing or any(not _finite_number(x) or float(x) <= 0 for x in smoothing):
        raise ValueError("modeling.naive_bayes_smoothing must be a non-empty list of positive finite numbers.")
    if len(set(float(x) for x in smoothing)) != len(smoothing):
        raise ValueError("modeling.naive_bayes_smoothing must not contain duplicates.")
    variance_floor = settings.get("naive_bayes_variance_floor", 1e-6)
    if not _finite_number(variance_floor) or float(variance_floor) <= 0:
        raise ValueError("modeling.naive_bayes_variance_floor must be a positive finite number.")
    return {"naive_bayes_smoothing": [float(x) for x in smoothing], "naive_bayes_variance_floor": float(variance_floor)}


def _load_cohort(cohort_dir: Path, task_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = cohort_dir / "modeling_cohort_manifest.json"
    report_path = cohort_dir / "cohort_report.json"
    split_path = cohort_dir / "split_manifest.json"
    csv_path = cohort_dir / "modeling_cohort.csv"
    for path in (manifest_path, report_path, split_path, csv_path, task_path):
        if not path.is_file():
            raise FileNotFoundError("Required modeling input is missing: " + str(path))
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    split = _read_json(split_path)
    task = _read_json(task_path)
    if not isinstance(manifest, dict) or not isinstance(report, dict) or not isinstance(split, dict) or not isinstance(task, dict):
        raise ValueError("Modeling inputs must be JSON objects.")
    if manifest.get("task_id") != task.get("task_id") or report.get("task_id") != task.get("task_id"):
        raise ValueError("Cohort manifest/report and task IDs do not match.")
    checks = manifest.get("artifact_sha256", {})
    for name, path in (("modeling_cohort.csv", csv_path), ("cohort_report.json", report_path), ("split_manifest.json", split_path)):
        expected = checks.get(name) if isinstance(checks, dict) else None
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ValueError("Cohort artifact hash is missing or stale: " + name)
    task_hash = sha256_file(task_path)
    if manifest.get("task_sha256") != task_hash:
        raise ValueError("Modeling task hash does not match the task used to build this cohort.")
    if report.get("valid") is not True or report.get("validation_scope") is None:
        raise ValueError("Cohort report is not a successful validated report.")
    if split.get("task_id") != task.get("task_id") or split.get("study_group_field") != "study_id":
        raise ValueError("Split manifest does not match the modelling task or required Study grouping.")
    if split.get("leakage_check", {}).get("valid") is not True:
        raise ValueError("Split manifest does not assert a successful study-overlap check.")
    feature_bindings = task.get("feature_bindings")
    if not isinstance(feature_bindings, list) or not feature_bindings:
        raise ValueError("Task has no explicit feature bindings.")
    required = {"cohort_row_id", "study_id", "system_id", "experiment_id", "observation_id",
                "target_id", "endpoint_definition", "outcome_value", "outcome_unit", "split"}
    required.update(binding["feature_id"] for binding in feature_bindings)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Cohort CSV is missing required fields: " + ", ".join(sorted(required - set(reader.fieldnames or []))))
        rows = list(reader)
    if not rows:
        raise ValueError("Cohort CSV contains no rows.")
    seen_rows: set[str] = set()
    seen_observations: set[str] = set()
    study_assignments = split.get("study_to_split", {})
    observation_ids = set()
    for row in rows:
        if not row["cohort_row_id"] or row["cohort_row_id"] in seen_rows:
            raise ValueError("Cohort row IDs must be non-empty and unique.")
        if not row["observation_id"] or row["observation_id"] in seen_observations:
            raise ValueError("Observation IDs must be non-empty and unique; duplicate rows are not silently removed.")
        seen_rows.add(row["cohort_row_id"])
        seen_observations.add(row["observation_id"])
        observation_ids.add(row["observation_id"])
        if row["target_id"] != task.get("target_id") or row["endpoint_definition"] != task.get("endpoint_definition"):
            raise ValueError("Cohort contains an observation outside the exact task endpoint.")
        if row["outcome_unit"] != (task.get("outcome_unit") if task.get("outcome_unit") is not None else ""):
            raise ValueError("Cohort outcome unit differs from the task's exact unit.")
        if row["split"] not in {"train", "validation", "test"}:
            raise ValueError("Cohort row has an invalid split label.")
        if study_assignments.get(row["study_id"]) != row["split"]:
            raise ValueError("A row's Study split differs from split_manifest.")
    expected_observations = {
        oid for split_name in ("train", "validation", "test")
        for oid in split.get("observation_ids_by_split", {}).get(split_name, [])
    }
    if observation_ids != expected_observations:
        raise ValueError("Cohort Observation IDs do not match split_manifest.")
    groups: dict[str, set[str]] = {}
    for row in rows:
        groups.setdefault(row["study_id"], set()).add(row["split"])
    if any(len(value) != 1 for value in groups.values()):
        raise ValueError("Study leakage detected: a Study appears in multiple data partitions.")
    for partition in ("train", "validation", "test"):
        if not any(row["split"] == partition for row in rows):
            raise ValueError("The " + partition + " partition is empty.")
    if manifest.get("eligible_observation_count") != len(rows):
        raise ValueError("Cohort manifest observation count is stale.")
    return rows, task, split, manifest


def _typed_rows(rows: list[dict[str, Any]], task: dict[str, Any]) -> list[dict[str, Any]]:
    typed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = dict(row)
        value = row["outcome_value"]
        if task["outcome_type"] == "NUMERIC":
            try:
                outcome = float(value)
            except (TypeError, ValueError):
                raise ValueError("Non-numeric outcome at cohort row " + str(index) + ".")
            if not math.isfinite(outcome):
                raise ValueError("Non-finite outcome at cohort row " + str(index) + ".")
            item["outcome"] = outcome
        else:
            if value is None or str(value) == "":
                raise ValueError("Empty categorical outcome at cohort row " + str(index) + ".")
            item["outcome"] = str(value)
        for binding in task["feature_bindings"]:
            fid = binding["feature_id"]
            raw = row[fid]
            if binding["value_type"] == "NUMERIC":
                try:
                    feature_value = float(raw)
                except (TypeError, ValueError):
                    raise ValueError("Non-numeric feature " + fid + " at cohort row " + str(index) + ".")
                if not math.isfinite(feature_value):
                    raise ValueError("Non-finite feature " + fid + " at cohort row " + str(index) + ".")
                item[fid] = feature_value
            else:
                if raw == "":
                    raise ValueError("Empty categorical feature " + fid + " at cohort row " + str(index) + ".")
                item[fid] = str(raw)
        typed.append(item)
    return typed


def _raw_matrix(rows: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> list[list[float]]:
    columns: list[dict[str, Any]] = []
    categories: dict[str, list[str]] = {}
    for binding in bindings:
        fid = binding["feature_id"]
        if binding["value_type"] == "NUMERIC":
            columns.append({"column": fid, "feature_id": fid, "kind": "NUMERIC"})
        else:
            cats = sorted({str(row[fid]) for row in rows})
            categories[fid] = cats
            for category in cats:
                columns.append({"column": fid + "==" + json.dumps(category, ensure_ascii=False), "feature_id": fid,
                                "kind": "CATEGORICAL_ONE_HOT", "category": category})
    if len(columns) > 500:
        raise ValueError("Encoded feature count exceeds the safe baseline-engine limit of 500; reduce or explicitly regroup high-cardinality categorical features.")
    raw_matrix: list[list[float]] = []
    for row in rows:
        vector: list[float] = []
        for column in columns:
            value = row[column["feature_id"]]
            if column["kind"] == "NUMERIC":
                vector.append(float(value))
            else:
                vector.append(1.0 if str(value) == column["category"] else 0.0)
        raw_matrix.append(vector)
    state = {"columns": columns, "categories": categories}
    return raw_matrix, state


def _fit_standardizer(matrix: list[list[float]]) -> dict[str, Any]:
    width = len(matrix[0]) if matrix else 0
    means: list[float] = []
    scales: list[float] = []
    for j in range(width):
        values = [row[j] for row in matrix]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        scale = math.sqrt(variance)
        if not math.isfinite(scale) or scale < 1e-12:
            scale = 1.0
        means.append(mean)
        scales.append(scale)
    return {"means": means, "scales": scales}


def _apply_standardizer(matrix: list[list[float]], state: dict[str, Any]) -> list[list[float]]:
    means, scales = state["means"], state["scales"]
    return [[(value - means[j]) / scales[j] for j, value in enumerate(row)] for row in matrix]


def _fit_encoder(rows: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> tuple[dict[str, Any], list[list[float]]]:
    raw, base = _raw_matrix(rows, bindings)
    standardizer = _fit_standardizer(raw)
    encoder = {**base, "standardizer": standardizer}
    return encoder, _apply_standardizer(raw, standardizer)


def _transform_rows(rows: list[dict[str, Any]], encoder: dict[str, Any]) -> list[list[float]]:
    columns = encoder["columns"]
    categories = encoder["categories"]
    raw: list[list[float]] = []
    for row in rows:
        vector: list[float] = []
        for column in columns:
            value = row[column["feature_id"]]
            if column["kind"] == "NUMERIC":
                vector.append(float(value))
            else:
                vector.append(1.0 if str(value) == column["category"] else 0.0)
        raw.append(vector)
    return _apply_standardizer(raw, encoder["standardizer"])


def _fit_ridge(matrix: list[list[float]], y: list[float], alpha: float, max_iter: int, tolerance: float) -> dict[str, Any]:
    n = len(y)
    width = len(matrix[0]) if matrix else 0
    target_mean = sum(y) / n
    target_variance = sum((value - target_mean) ** 2 for value in y) / n
    target_scale = math.sqrt(target_variance)
    if target_scale < 1e-12:
        target_scale = 1.0
    y_scaled = [(value - target_mean) / target_scale for value in y]
    coefficients = [0.0] * width
    residual = y_scaled[:]
    denominators = [sum(row[j] * row[j] for row in matrix) + n * alpha for j in range(width)]
    converged = width == 0
    iterations = 0
    for iteration in range(max_iter):
        max_delta = 0.0
        for j in range(width):
            numerator = 0.0
            old = coefficients[j]
            for i in range(n):
                numerator += matrix[i][j] * (residual[i] + matrix[i][j] * old)
            new = numerator / denominators[j]
            delta = new - old
            if delta:
                for i in range(n):
                    residual[i] -= matrix[i][j] * delta
                coefficients[j] = new
                max_delta = max(max_delta, abs(delta))
        iterations = iteration + 1
        if max_delta < tolerance:
            converged = True
            break
    return {"alpha": alpha, "target_mean": target_mean, "target_scale": target_scale,
            "intercept_standardized": 0.0, "coefficients": coefficients,
            "converged": converged, "iterations": iterations}


def _predict_ridge(matrix: list[list[float]], model: dict[str, Any]) -> list[float]:
    values = []
    for row in matrix:
        standardized = model["intercept_standardized"] + sum(value * coefficient for value, coefficient in zip(row, model["coefficients"]))
        values.append(model["target_mean"] + model["target_scale"] * standardized)
    return values


def _predict_mean(y_train: list[float], count: int) -> list[float]:
    mean = sum(y_train) / len(y_train)
    return [mean] * count


def _regression_metrics(actual: list[float], predicted: list[float]) -> dict[str, Any]:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("Regression metric inputs must have equal non-zero length.")
    errors = [predicted[i] - actual[i] for i in range(len(actual))]
    mae = sum(abs(value) for value in errors) / len(errors)
    rmse = math.sqrt(sum(value * value for value in errors) / len(errors))
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    residual = sum(value * value for value in errors)
    r2 = None if len(actual) < 2 or total <= 0 else 1.0 - residual / total
    return {"n": len(actual), "mae": mae, "rmse": rmse, "r2": r2}


def _majority_model(y: list[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for value in y:
        counts[value] = counts.get(value, 0) + 1
    majority = sorted(counts, key=lambda value: (-counts[value], value))[0]
    return {"classes": sorted(counts), "class_counts": counts, "majority_class": majority}


def _predict_majority(model: dict[str, Any], count: int) -> list[str]:
    return [model["majority_class"]] * count


def _fit_naive_bayes(rows: list[dict[str, Any]], bindings: list[dict[str, Any]], y: list[str],
                     smoothing: float, variance_floor: float) -> dict[str, Any]:
    classes = sorted(set(y))
    class_counts = {label: sum(1 for value in y if value == label) for label in classes}
    numeric: dict[str, Any] = {}
    categorical: dict[str, Any] = {}
    for binding in bindings:
        fid = binding["feature_id"]
        if binding["value_type"] == "NUMERIC":
            global_values = [float(row[fid]) for row in rows]
            global_mean = sum(global_values) / len(global_values)
            global_variance = sum((value - global_mean) ** 2 for value in global_values) / len(global_values)
            global_scale = math.sqrt(global_variance) if global_variance > 1e-12 else 1.0
            stats = {}
            for label in classes:
                values = [(float(row[fid]) - global_mean) / global_scale for row, target in zip(rows, y) if target == label]
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / len(values)
                stats[label] = {"mean": mean, "variance": max(variance, variance_floor)}
            numeric[fid] = {"global_mean": global_mean, "global_scale": global_scale, "by_class": stats}
        else:
            vocab = sorted({str(row[fid]) for row in rows})
            by_class = {}
            for label in classes:
                counts: dict[str, int] = {}
                for row, target in zip(rows, y):
                    if target == label:
                        key = str(row[fid])
                        counts[key] = counts.get(key, 0) + 1
                by_class[label] = counts
            categorical[fid] = {"vocabulary": vocab, "by_class": by_class}
    return {"classes": classes, "class_counts": class_counts, "numeric_features": numeric,
            "categorical_features": categorical, "smoothing": smoothing, "variance_floor": variance_floor}


def _predict_naive_bayes(rows: list[dict[str, Any]], model: dict[str, Any]) -> list[str]:
    classes = model["classes"]
    total = sum(model["class_counts"].values())
    predictions: list[str] = []
    for row in rows:
        scores: dict[str, float] = {}
        for label in classes:
            score = math.log(model["class_counts"][label] / total)
            for fid, spec in model["numeric_features"].items():
                value = (float(row[fid]) - spec["global_mean"]) / spec["global_scale"]
                stat = spec["by_class"][label]
                variance = stat["variance"]
                score += -0.5 * math.log(2.0 * math.pi * variance) - ((value - stat["mean"]) ** 2) / (2.0 * variance)
            for fid, spec in model["categorical_features"].items():
                observed = str(row[fid])
                counts = spec["by_class"][label]
                vocab_size = len(spec["vocabulary"]) + 1
                score += math.log((counts.get(observed, 0) + model["smoothing"]) /
                                  (model["class_counts"][label] + model["smoothing"] * vocab_size))
            scores[label] = score
        predictions.append(sorted(classes, key=lambda label: (-scores[label], label))[0])
    return predictions


def _classification_metrics(actual: list[str], predicted: list[str]) -> dict[str, Any]:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("Classification metric inputs must have equal non-zero length.")
    labels = sorted(set(actual) | set(predicted))
    matrix = {truth: {prediction: 0 for prediction in labels} for truth in labels}
    for truth, prediction in zip(actual, predicted):
        matrix[truth][prediction] += 1
    recalls, f1s = [], []
    for label in labels:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted_count = sum(matrix[truth][label] for truth in labels)
        if support:
            recalls.append(tp / support)
        precision = tp / predicted_count if predicted_count else 0.0
        recall = tp / support if support else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    true_labels = sorted(set(actual))
    balanced = sum(matrix[label][label] / sum(matrix[label].values()) for label in true_labels) / len(true_labels)
    accuracy = sum(1 for truth, prediction in zip(actual, predicted) if truth == prediction) / len(actual)
    return {"n": len(actual), "accuracy": accuracy, "balanced_accuracy": balanced,
            "macro_f1": sum(f1s) / len(f1s), "labels": labels, "confusion_matrix": matrix}


def _partition(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["split"] == name]


def _run_regression(rows: list[dict[str, Any]], task: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    train, validation, test = (_partition(rows, name) for name in ("train", "validation", "test"))
    if len(train) < 2:
        raise ValueError("At least two training observations are required for regression baselines.")
    y_train = [row["outcome"] for row in train]
    y_validation = [row["outcome"] for row in validation]
    comparisons: list[dict[str, Any]] = []
    mean_predictions = _predict_mean(y_train, len(validation))
    mean_metrics = _regression_metrics(y_validation, mean_predictions)
    comparisons.append({"candidate_model":"mean_baseline","alpha":None,"validation_metrics":mean_metrics,"converged":True,"iterations":0})
    candidate_models: dict[str, dict[str, Any]] = {}
    bindings = task["feature_bindings"]
    encoder, x_train = _fit_encoder(train, bindings)
    x_validation = _transform_rows(validation, encoder)
    for alpha in settings["ridge_alphas"]:
        fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
        predictions = _predict_ridge(x_validation, fitted)
        name = "ridge_alpha_" + format(alpha, ".12g")
        candidate_models[name] = {"fit":fitted,"encoder":encoder}
        comparisons.append({"candidate_model":"ridge_regression","candidate_id":name,"alpha":alpha,
                            "validation_metrics":_regression_metrics(y_validation,predictions),
                            "converged":fitted["converged"],"iterations":fitted["iterations"]})
    chosen = min(comparisons, key=lambda item:(item["validation_metrics"]["rmse"],
                                                0 if item["candidate_model"]=="mean_baseline" else 1,
                                                item.get("alpha") or 0))
    selected_name = chosen.get("candidate_id","mean_baseline")
    train_validation = train + validation
    y_train_validation = [row["outcome"] for row in train_validation]
    baseline_model = {"model_type":"mean_baseline","prediction":sum(y_train_validation)/len(y_train_validation)}
    test_actual = [row["outcome"] for row in test]
    baseline_predictions = [baseline_model["prediction"]] * len(test)
    if selected_name == "mean_baseline":
        selected_model = baseline_model
        selected_predictions = baseline_predictions
    else:
        selected_encoder, x_train_validation = _fit_encoder(train_validation, bindings)
        final_fit = _fit_ridge(x_train_validation,y_train_validation,chosen["alpha"],
                               settings["max_iter"],settings["tolerance"])
        selected_model = {"model_type":"ridge_regression","alpha":chosen["alpha"],
                          "fit":final_fit,"encoder":selected_encoder}
        selected_predictions = _predict_ridge(_transform_rows(test,selected_encoder),final_fit)
    report = {
        "task_id":task["task_id"],"outcome_type":"NUMERIC","primary_selection_metric":"validation_rmse_minimized",
        "selected_model":selected_model["model_type"],"selected_candidate_id":selected_name,
        "validation_comparison":comparisons,
        "test_evaluation":{"selected_model":_regression_metrics(test_actual,selected_predictions),
                           "mean_baseline":_regression_metrics(test_actual,baseline_predictions)},
        "training_observation_count":len(train),"validation_observation_count":len(validation),
        "refit_observation_count":len(train_validation),"test_observation_count":len(test)
    }
    artifact = {
        "schema_version":"1.0","engine_version":ENGINE_VERSION,"task_id":task["task_id"],
        "model_type":selected_model["model_type"],"target_id":task["target_id"],
        "endpoint_definition":task["endpoint_definition"],"outcome_value_field":task["outcome_value_field"],
        "outcome_unit":task["outcome_unit"],"feature_bindings":bindings,
        "selected_candidate_id":selected_name,"selection_metric":"validation_rmse_minimized",
        "training_observation_ids":[row["observation_id"] for row in train_validation],
        "training_study_ids":sorted({row["study_id"] for row in train_validation}),
        "test_observation_ids":[row["observation_id"] for row in test],
        "model_parameters":selected_model
    }
    predictions = [{"observation_id":row["observation_id"],"study_id":row["study_id"],
                    "actual":row["outcome"],"prediction":selected_predictions[i],
                    "mean_baseline_prediction":baseline_predictions[i],
                    "residual":selected_predictions[i]-row["outcome"]}
                   for i,row in enumerate(test)]
    return report,artifact,predictions


def _run_classification(rows: list[dict[str, Any]], task: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any],dict[str, Any],list[dict[str, Any]]]:
    train, validation, test = (_partition(rows,name) for name in ("train","validation","test"))
    if len(train)<2:
        raise ValueError("At least two training observations are required for classification baselines.")
    y_train=[row["outcome"] for row in train]
    y_validation=[row["outcome"] for row in validation]
    majority=_majority_model(y_train)
    baseline_predictions=_predict_majority(majority,len(validation))
    comparisons=[{"candidate_model":"majority_class_baseline","smoothing":None,
                  "validation_metrics":_classification_metrics(y_validation,baseline_predictions)}]
    candidate_fits={}
    for smoothing in settings["naive_bayes_smoothing"]:
        fitted=_fit_naive_bayes(train,task["feature_bindings"],y_train,smoothing,settings["naive_bayes_variance_floor"])
        predictions=_predict_naive_bayes(validation,fitted)
        name="naive_bayes_alpha_"+format(smoothing,".12g")
        candidate_fits[name]=fitted
        comparisons.append({"candidate_model":"mixed_naive_bayes","candidate_id":name,"smoothing":smoothing,
                            "validation_metrics":_classification_metrics(y_validation,predictions)})
    chosen=max(comparisons,key=lambda item:(item["validation_metrics"]["macro_f1"],
                                             1 if item["candidate_model"]=="majority_class_baseline" else 0,
                                             -(item.get("smoothing") or 0)))
    selected_name=chosen.get("candidate_id","majority_class_baseline")
    train_validation=train+validation
    y_train_validation=[row["outcome"] for row in train_validation]
    final_majority=_majority_model(y_train_validation)
    final_baseline=_predict_majority(final_majority,len(test))
    if selected_name=="majority_class_baseline":
        selected_model={"model_type":"majority_class_baseline","parameters":final_majority}
        selected_predictions=final_baseline
    else:
        smoothing=chosen["smoothing"]
        fitted=_fit_naive_bayes(train_validation,task["feature_bindings"],y_train_validation,
                                smoothing,settings["naive_bayes_variance_floor"])
        selected_model={"model_type":"mixed_naive_bayes","parameters":fitted}
        selected_predictions=_predict_naive_bayes(test,fitted)
    test_actual=[row["outcome"] for row in test]
    report={
        "task_id":task["task_id"],"outcome_type":"CATEGORICAL","primary_selection_metric":"validation_macro_f1_maximized",
        "selected_model":selected_model["model_type"],"selected_candidate_id":selected_name,
        "validation_comparison":comparisons,
        "test_evaluation":{"selected_model":_classification_metrics(test_actual,selected_predictions),
                           "majority_class_baseline":_classification_metrics(test_actual,final_baseline)},
        "training_observation_count":len(train),"validation_observation_count":len(validation),
        "refit_observation_count":len(train_validation),"test_observation_count":len(test)
    }
    artifact={
        "schema_version":"1.0","engine_version":ENGINE_VERSION,"task_id":task["task_id"],
        "model_type":selected_model["model_type"],"target_id":task["target_id"],
        "endpoint_definition":task["endpoint_definition"],"outcome_value_field":task["outcome_value_field"],
        "outcome_unit":task["outcome_unit"],"feature_bindings":task["feature_bindings"],
        "selected_candidate_id":selected_name,"selection_metric":"validation_macro_f1_maximized",
        "training_observation_ids":[row["observation_id"] for row in train_validation],
        "training_study_ids":sorted({row["study_id"] for row in train_validation}),
        "test_observation_ids":[row["observation_id"] for row in test],
        "model_parameters":selected_model
    }
    predictions=[{"observation_id":row["observation_id"],"study_id":row["study_id"],
                  "actual":row["outcome"],"prediction":selected_predictions[i],
                  "majority_baseline_prediction":final_baseline[i],
                  "correct":selected_predictions[i]==row["outcome"]}
                 for i,row in enumerate(test)]
    return report,artifact,predictions


def run_baseline_models_files(cohort_dir: Path,task_path: Path,output_dir: Path) -> dict[str,Any]:
    cohort_dir=cohort_dir.expanduser().resolve()
    task_path=task_path.expanduser().resolve()
    output_dir=output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: "+str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty model output directory: "+str(output_dir))
    rows_raw,task,split,cohort_manifest=_load_cohort(cohort_dir,task_path)
    settings=_settings(task)
    rows=_typed_rows(rows_raw,task)
    train,validation,test=(_partition(rows,name) for name in ("train","validation","test"))
    if not train or not validation or not test:
        raise ValueError("Train, validation, and test partitions must each contain at least one observation.")
    if task["outcome_type"]=="NUMERIC":
        report,artifact,predictions=_run_regression(rows,task,settings)
    elif task["outcome_type"]=="CATEGORICAL":
        report,artifact,predictions=_run_classification(rows,task,settings)
    else:
        raise ValueError("Unsupported outcome_type; expected NUMERIC or CATEGORICAL.")
    output_dir.mkdir(parents=True,exist_ok=True)
    _write_json(output_dir/"model_report.json",report)
    _write_json(output_dir/"model_artifact.json",artifact)
    pred_path=output_dir/"test_predictions.csv"
    fields=list(predictions[0].keys())
    with pred_path.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        writer.writerows(predictions)
    comparison_path=output_dir/"validation_model_comparison.csv"
    comparisons=report["validation_comparison"]
    comparison_fields=["candidate_model","candidate_id","alpha","smoothing","converged","iterations",
                       "validation_n","validation_mae","validation_rmse","validation_r2",
                       "validation_accuracy","validation_balanced_accuracy","validation_macro_f1","selected"]
    with comparison_path.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=comparison_fields)
        writer.writeheader()
        for item in comparisons:
            metrics=item["validation_metrics"]
            writer.writerow({
                "candidate_model":item["candidate_model"],"candidate_id":item.get("candidate_id"),
                "alpha":item.get("alpha"),"smoothing":item.get("smoothing"),
                "converged":item.get("converged"),"iterations":item.get("iterations"),
                "validation_n":metrics.get("n"),"validation_mae":metrics.get("mae"),
                "validation_rmse":metrics.get("rmse"),"validation_r2":metrics.get("r2"),
                "validation_accuracy":metrics.get("accuracy"),
                "validation_balanced_accuracy":metrics.get("balanced_accuracy"),
                "validation_macro_f1":metrics.get("macro_f1"),
                "selected":item.get("candidate_id", "majority_class_baseline" if task["outcome_type"]=="CATEGORICAL" else "mean_baseline")==report["selected_candidate_id"]
            })
    input_hashes={
        "cohort_sha256":sha256_file(cohort_dir/"modeling_cohort.csv"),
        "cohort_report_sha256":sha256_file(cohort_dir/"cohort_report.json"),
        "split_manifest_sha256":sha256_file(cohort_dir/"split_manifest.json"),
        "cohort_manifest_sha256":sha256_file(cohort_dir/"modeling_cohort_manifest.json"),
        "task_sha256":sha256_file(task_path)
    }
    output_hashes={name:sha256_file(output_dir/name) for name in
                   ("model_report.json","model_artifact.json","test_predictions.csv","validation_model_comparison.csv")}
    run_manifest={
        "schema_version":"1.0","task_id":task["task_id"],"engine_version":ENGINE_VERSION,
        "input_hashes":input_hashes,"output_hashes":output_hashes,
        "split_strategy":split["strategy"],"split_seed":split.get("seed",42),
        "study_ids_by_split":split["leakage_check"]["study_ids_by_split"],
        "selected_model":report["selected_model"],
        "selection_rule":"Validation metric only; test set evaluated after selection.",
        "source_policy":"COHORT_AND_TASK_READ_ONLY; TRANSFORMS_FIT_ON_TRAIN_ONLY_FOR_VALIDATION; FINAL_REFIT_ON_TRAIN_PLUS_VALIDATION; TEST_USED_FOR_FINAL_EVALUATION_ONLY"
    }
    _write_json(output_dir/"modeling_run_manifest.json",run_manifest)
    return {"valid":True,"report":report,"artifact":artifact,"manifest":run_manifest,"output_dir":str(output_dir)}
