"""Guarded scenario prediction using a hash-verified selected baseline model."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file
from dor.modeling import _predict_majority, _predict_naive_bayes, _predict_ridge, _transform_rows


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_query(query: Any, artifact: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(query, dict) or query.get("schema_version") != "1.0":
        raise ValueError("Virtual reproduction query must be an object with schema_version 1.0.")
    for key in ("task_id", "target_id", "endpoint_definition"):
        if query.get(key) != artifact.get(key):
            raise ValueError("Query " + key + " does not exactly match the selected model artifact.")
    features = query.get("features")
    if not isinstance(features, dict):
        raise ValueError("Query features must be an object keyed by exact feature_id.")
    bindings = artifact.get("feature_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("Model artifact has no explicit feature bindings.")
    expected_ids = [item.get("feature_id") for item in bindings if isinstance(item, dict)]
    if len(expected_ids) != len(bindings) or len(set(expected_ids)) != len(expected_ids):
        raise ValueError("Model artifact feature bindings are malformed or duplicated.")
    missing = sorted(set(expected_ids) - set(features))
    extra = sorted(set(features) - set(expected_ids))
    if missing or extra:
        raise ValueError("Query feature IDs must match exactly; missing=" + repr(missing) + "; extra=" + repr(extra))
    row: dict[str, Any] = {}
    for binding in bindings:
        fid = binding["feature_id"]
        item = features[fid]
        if not isinstance(item, dict) or set(item) != {"value", "unit"}:
            raise ValueError("Feature " + fid + " must contain exactly value and unit.")
        if item["unit"] != binding.get("expected_unit"):
            raise ValueError("Feature " + fid + " unit must exactly match expected_unit; no implicit conversion is performed.")
        value = item["value"]
        if binding["value_type"] == "NUMERIC":
            if not _finite_number(value):
                raise ValueError("Numeric feature " + fid + " must be a finite JSON number, not a numeric string.")
            row[fid] = float(value)
        elif binding["value_type"] == "CATEGORICAL":
            if not isinstance(value, str) or not value:
                raise ValueError("Categorical feature " + fid + " must be a non-empty string.")
            row[fid] = value
        else:
            raise ValueError("Unsupported feature value_type for " + fid)
    return row


def _assess_domain(row: dict[str, Any], artifact: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    domain = artifact.get("training_feature_domain")
    reports: list[dict[str, Any]] = []
    warnings: list[str] = []
    bindings = artifact["feature_bindings"]
    if not isinstance(domain, dict):
        domain = {}
    for binding in bindings:
        fid = binding["feature_id"]
        spec = domain.get(fid)
        value = row[fid]
        if not isinstance(spec, dict):
            reports.append({"feature_id": fid, "status": "SUPPORT_NOT_ASSESSABLE"})
            warnings.append("TRAINING_DOMAIN_NOT_RECORDED:" + fid)
            continue
        if binding["value_type"] == "NUMERIC":
            lower, upper = spec.get("minimum"), spec.get("maximum")
            if not _finite_number(lower) or not _finite_number(upper):
                reports.append({"feature_id": fid, "status": "SUPPORT_NOT_ASSESSABLE"})
                warnings.append("TRAINING_NUMERIC_RANGE_NOT_RECORDED:" + fid)
            elif float(value) < float(lower) or float(value) > float(upper):
                reports.append({"feature_id": fid, "status": "OUTSIDE_TRAINING_RANGE",
                                "query_value": value, "training_range": [lower, upper],
                                "unit": binding.get("expected_unit")})
                warnings.append("OUTSIDE_TRAINING_RANGE:" + fid)
            else:
                reports.append({"feature_id": fid, "status": "WITHIN_TRAINING_RANGE",
                                "query_value": value, "training_range": [lower, upper],
                                "unit": binding.get("expected_unit")})
        else:
            categories = spec.get("categories")
            if not isinstance(categories, list):
                reports.append({"feature_id": fid, "status": "SUPPORT_NOT_ASSESSABLE"})
                warnings.append("TRAINING_CATEGORY_SET_NOT_RECORDED:" + fid)
            elif value not in categories:
                reports.append({"feature_id": fid, "status": "UNKNOWN_CATEGORY",
                                "query_value": value, "known_categories": categories})
                warnings.append("UNKNOWN_CATEGORY:" + fid)
            else:
                reports.append({"feature_id": fid, "status": "KNOWN_CATEGORY",
                                "query_value": value, "known_category_count": len(categories)})
    return reports, warnings


def predict_virtual_condition_files(model_run_dir: Path, query_path: Path, output_path: Path) -> dict[str, Any]:
    model_run_dir = model_run_dir.expanduser().resolve()
    query_path = query_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.is_relative_to(model_run_dir):
        raise ValueError("Virtual reproduction output must be outside the immutable model-run directory.")
    artifact_path = model_run_dir / "model_artifact.json"
    report_path = model_run_dir / "model_report.json"
    manifest_path = model_run_dir / "modeling_run_manifest.json"
    for path in (artifact_path, report_path, manifest_path, query_path):
        if not path.is_file():
            raise FileNotFoundError("Required virtual reproduction input is missing: " + str(path))
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite an existing virtual reproduction output: " + str(output_path))

    manifest = _read_json(manifest_path)
    artifact = _read_json(artifact_path)
    model_report = _read_json(report_path)
    query = _read_json(query_path)
    if not all(isinstance(item, dict) for item in (manifest, artifact, model_report)):
        raise ValueError("Model run manifest, artifact, and report must be JSON objects.")
    if manifest.get("task_id") != artifact.get("task_id") or model_report.get("task_id") != artifact.get("task_id"):
        raise ValueError("Model run manifest, report, and artifact task IDs do not agree.")
    output_hashes = manifest.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise ValueError("Model run manifest has no output hash table.")
    for name, path in (("model_artifact.json", artifact_path), ("model_report.json", report_path)):
        expected = output_hashes.get(name)
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ValueError("Model run artifact hash is missing or stale: " + name)
    if manifest.get("selected_model") != artifact.get("model_type") or model_report.get("selected_model") != artifact.get("model_type"):
        raise ValueError("Selected model identity differs across the model run files.")
    training_ids = artifact.get("training_observation_ids")
    test_ids = artifact.get("test_observation_ids")
    if not isinstance(training_ids, list) or not training_ids or not isinstance(test_ids, list):
        raise ValueError("Model artifact must record non-empty training IDs and test IDs.")
    if set(training_ids).intersection(test_ids):
        raise ValueError("Model artifact incorrectly overlaps training and held-out test Observation IDs.")
    row = _validate_query(query, artifact)
    domain_report, warnings = _assess_domain(row, artifact)

    model_type = artifact.get("model_type")
    params = artifact.get("model_parameters")
    if not isinstance(params, dict) or params.get("model_type") != model_type:
        raise ValueError("Serialized selected model parameters are missing or inconsistent.")
    if model_type == "mean_baseline":
        prediction: Any = params.get("prediction")
        if not _finite_number(prediction):
            raise ValueError("Mean baseline prediction is invalid.")
        prediction = float(prediction)
    elif model_type == "ridge_regression":
        encoder = params.get("encoder")
        fitted = params.get("fit")
        if not isinstance(encoder, dict) or not isinstance(fitted, dict):
            raise ValueError("Ridge model artifact is missing its encoder or fitted coefficients.")
        prediction = _predict_ridge(_transform_rows([row], encoder), fitted)[0]
    elif model_type == "majority_class_baseline":
        fitted = params.get("parameters")
        if not isinstance(fitted, dict):
            raise ValueError("Majority baseline parameters are missing.")
        prediction = _predict_majority(fitted, 1)[0]
    elif model_type == "mixed_naive_bayes":
        fitted = params.get("parameters")
        if not isinstance(fitted, dict):
            raise ValueError("Mixed Naive Bayes parameters are missing.")
        prediction = _predict_naive_bayes([row], fitted)[0]
    else:
        raise ValueError("Unsupported model type for virtual reproduction: " + str(model_type))

    out_of_domain = any(item["status"] in {"OUTSIDE_TRAINING_RANGE", "UNKNOWN_CATEGORY"} for item in domain_report)
    unassessable = any(item["status"] == "SUPPORT_NOT_ASSESSABLE" for item in domain_report)
    if out_of_domain:
        prediction_status = "EXTRAPOLATIVE_OR_UNKNOWN_CATEGORY_SCENARIO"
    elif unassessable:
        prediction_status = "PREDICTION_SUPPORT_NOT_ASSESSABLE"
    else:
        prediction_status = "WITHIN_RECORDED_MARGINAL_TRAINING_DOMAIN"
    warnings.extend([
        "NOT_CALIBRATED: no calibrated prediction interval or probability is produced.",
        "MARGINAL_DOMAIN_ONLY: per-feature ranges/categories do not establish joint multivariable support.",
        "NOT_A_PHYSICAL_REPRODUCTION: this is a model-based scenario estimate, not a reproduced experiment or a physical-state simulation."
    ])
    result = {
        "schema_version": "1.0",
        "prediction_id": "VIRTUAL_" + sha256_file(query_path)[:16].upper(),
        "task_id": artifact["task_id"],
        "target_id": artifact["target_id"],
        "endpoint_definition": artifact["endpoint_definition"],
        "outcome_unit": artifact.get("outcome_unit"),
        "model_type": model_type,
        "selected_candidate_id": artifact.get("selected_candidate_id"),
        "prediction": prediction,
        "prediction_status": prediction_status,
        "uncertainty_status": "NOT_CALIBRATED",
        "support_assessment": {
            "scope": "MARGINAL_TRAINING_RANGE_AND_CATEGORY_CHECK_ONLY",
            "per_feature": domain_report,
            "nearest_training_observation": "NOT_COMPUTED; raw training rows are not embedded in the model artifact"
        },
        "warnings": warnings,
        "query_features": row,
        "provenance": {
            "model_artifact_sha256": sha256_file(artifact_path),
            "model_report_sha256": sha256_file(report_path),
            "model_run_manifest_sha256": sha256_file(manifest_path),
            "query_sha256": sha256_file(query_path),
            "training_observation_ids": training_ids,
            "training_study_ids": artifact.get("training_study_ids", []),
            "test_observation_ids": test_ids,
            "test_set_used_for_fit_or_selection": False,
            "model_run_selection_rule": manifest.get("selection_rule")
        },
        "interpretation_boundary": "Predictive association under the serialized baseline model only; not causal inference, mechanistic validation, calibrated uncertainty, or a guarantee of experimental reproducibility."
    }
    _write_json(output_path, result)
    return {"valid": True, "report": result, "output_path": str(output_path)}
