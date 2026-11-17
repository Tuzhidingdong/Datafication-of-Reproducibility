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


def _binding_map(source: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    bindings = source.get("feature_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError(label + " has no explicit feature bindings.")
    result: dict[str, dict[str, Any]] = {}
    for item in bindings:
        if not isinstance(item, dict):
            raise ValueError(label + " feature bindings are malformed.")
        fid = item.get("feature_id")
        if not isinstance(fid, str) or not fid:
            raise ValueError(label + " feature bindings contain an invalid feature_id.")
        if fid in result:
            raise ValueError(label + " feature bindings are duplicated: " + fid)
        result[fid] = item
    return result


def _validate_query(query: Any, source: dict[str, Any], label: str = "selected model artifact") -> dict[str, Any]:
    if not isinstance(query, dict) or query.get("schema_version") != "1.0":
        raise ValueError("Virtual reproduction query must be an object with schema_version 1.0.")
    for key in ("task_id", "target_id", "endpoint_definition"):
        if query.get(key) != source.get(key):
            raise ValueError("Query " + key + " does not exactly match the " + label + ".")
    features = query.get("features")
    if not isinstance(features, dict):
        raise ValueError("Query features must be an object keyed by exact feature_id.")
    expected = _binding_map(source, label.capitalize() if label else "Source")
    missing = sorted(set(expected) - set(features))
    extra = sorted(set(features) - set(expected))
    if missing or extra:
        raise ValueError("Query feature IDs must match exactly; missing=" + repr(missing) + "; extra=" + repr(extra))
    row: dict[str, Any] = {}
    for fid, binding in expected.items():
        item = features[fid]
        if not isinstance(item, dict) or set(item) != {"value", "unit"}:
            raise ValueError("Feature " + fid + " must contain exactly value and unit.")
        if item.get("unit") != binding.get("expected_unit"):
            raise ValueError("Feature " + fid + " unit must exactly match expected_unit; no implicit conversion is performed.")
        expected_type = binding.get("value_type")
        value = item.get("value")
        if expected_type == "NUMERIC":
            if not _finite_number(value):
                raise ValueError("Numeric feature " + fid + " must be a finite JSON number, not a numeric string.")
            row[fid] = float(value)
        elif expected_type == "CATEGORICAL":
            if not isinstance(value, str) or not value:
                raise ValueError("Categorical feature " + fid + " must be a non-empty string.")
            row[fid] = value
        else:
            raise ValueError("Unsupported feature value_type for " + fid)
    return row


def _load_decision(decision_path: Path) -> dict[str, Any]:
    decision_path = decision_path.expanduser().resolve(strict=True)
    decision = _read_json(decision_path)
    if not isinstance(decision, dict):
        raise ValueError("Virtual query decision must be a JSON object.")
    if decision.get("schema_version") != "1.0":
        raise ValueError("Virtual query decision schema_version must be 1.0.")
    status = decision.get("decision")
    if status not in {"RUN_PREDICTION", "NOT_APPLICABLE"}:
        raise ValueError("Virtual query decision must be RUN_PREDICTION or NOT_APPLICABLE.")
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Virtual query decision requires a non-empty reason.")
    for key in ("task_id", "target_id", "endpoint_definition", "modeling_task_sha256", "reviewer", "decided_at"):
        value = decision.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Virtual query decision missing required field: {key}")
    if status == "RUN_PREDICTION":
        source = decision.get("source_query_path")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("RUN_PREDICTION decision must provide source_query_path.")
    else:
        if "source_query_path" in decision and decision.get("source_query_path") is not None:
            raise ValueError("NOT_APPLICABLE decision must not provide source_query_path.")
    return decision


def prepare_virtual_query_files(
    task_path: Path,
    decision_path: Path,
    output_path: Path,
    report_path: Path,
    query_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a RUN_PREDICTION virtual query decision and materialize formal artifacts.

    The query file is treated as the human-supplied prediction condition input.
    A schema/task-consistent copy is written to ``output_path`` as the formal
    Run Artifact ``virtual_query_input`` and a validation report is written to
    ``report_path``. No target selection, condition value, or unit is inferred or
    transformed.
    """
    task_path = task_path.expanduser().resolve(strict=True)
    decision_path = decision_path.expanduser().resolve(strict=True)
    output_path = output_path.expanduser().resolve()
    report_path = report_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite existing virtual query output: " + str(output_path))
    if report_path.exists():
        raise FileExistsError("Refusing to overwrite existing virtual query validation: " + str(report_path))

    task = _read_json(task_path)
    if not isinstance(task, dict):
        raise ValueError("Modeling task must be a JSON object.")
    decision = _load_decision(decision_path)
    if decision.get("decision") != "RUN_PREDICTION":
        raise ValueError("Only RUN_PREDICTION decisions can produce virtual_query_input and virtual_query_validation artifacts.")

    task_sha256 = sha256_file(task_path)
    if decision.get("modeling_task_sha256") != task_sha256:
        raise ValueError("Virtual query decision modeling_task_sha256 does not match the confirmed modeling task.")
    for key in ("task_id", "target_id", "endpoint_definition"):
        if decision.get(key) != task.get(key):
            raise ValueError(f"Virtual query decision {key} does not exactly match the confirmed modeling task.")

    required_task_fields = ("task_id", "target_id", "endpoint_definition", "feature_bindings")
    for field in required_task_fields:
        if field not in task:
            raise ValueError("Confirmed modeling task is missing required field: " + field)

    source_query_raw = query_path if query_path is not None else Path(str(decision["source_query_path"]))
    source_query_path = source_query_raw.expanduser().resolve(strict=True)
    query = _read_json(source_query_path)
    if not isinstance(query, dict):
        raise ValueError("Virtual reproduction query must be a JSON object.")

    row = _validate_query(query, task, label="confirmed modeling task")
    expected_features = _binding_map(task, "Confirmed modeling task")
    if query.get("schema_version") != "1.0":
        raise ValueError("Virtual reproduction query schema_version must be 1.0.")
    if set(query.keys()) != {"schema_version", "task_id", "target_id", "endpoint_definition", "features"}:
        raise ValueError("Virtual reproduction query must contain only schema_version, task_id, target_id, endpoint_definition, and features.")
    if set(query["features"].keys()) != set(expected_features.keys()):
        raise ValueError("Query feature IDs must match the confirmed modeling task exactly.")

    _write_json(output_path, query)
    report = {
        "schema_version": "1.0",
        "contract": "VIRTUAL_QUERY_PREPARATION",
        "valid": True,
        "task_path": str(task_path),
        "task_sha256": task_sha256,
        "decision_path": str(decision_path),
        "decision_sha256": sha256_file(decision_path),
        "source_query_path": str(source_query_path),
        "source_query_sha256": sha256_file(source_query_path),
        "prepared_query_path": str(output_path),
        "prepared_query_sha256": sha256_file(output_path),
        "task_id": task.get("task_id"),
        "target_id": task.get("target_id"),
        "endpoint_definition": task.get("endpoint_definition"),
        "feature_count": len(expected_features),
        "validated_feature_ids": sorted(expected_features.keys()),
        "decision": "RUN_PREDICTION",
        "interpretation": (
            "A validated, task-consistent virtual query prepared from human-provided conditions under a "
            "RUN_PREDICTION decision. It does not predict an outcome, approve a gate, or imply physical reproducibility."
        ),
    }
    _write_json(report_path, report)
    return {
        "valid": True,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "report": report,
        "validated_features": row,
    }


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




def read_virtual_query_decision(decision_path: Path) -> dict[str, Any]:
    """Load and structurally validate a virtual_query_decision artifact."""
    decision_path = decision_path.expanduser().resolve(strict=True)
    _ = _load_decision(decision_path)
    return _read_json(decision_path)


def validate_virtual_query_preparation_artifacts(
    *,
    task_path: Path,
    decision_path: Path,
    query_path: Path | None = None,
    validation_path: Path | None = None,
) -> dict[str, Any]:
    """Validate decision and, for RUN_PREDICTION, the prepared query/validation artifacts.

    Returns a summary including decision state and checked artifact hashes.
    """
    task_path = task_path.expanduser().resolve(strict=True)
    decision_path = decision_path.expanduser().resolve(strict=True)
    task = _read_json(task_path)
    if not isinstance(task, dict):
        raise ValueError("Modeling task must be a JSON object.")
    for field in ("task_id", "target_id", "endpoint_definition"):
        if field not in task:
            raise ValueError("Confirmed modeling task is missing required field: " + field)
    task_sha256 = sha256_file(task_path)
    decision = read_virtual_query_decision(decision_path)
    decision_sha = sha256_file(decision_path)

    if decision.get("modeling_task_sha256") != task_sha256:
        raise ValueError("Virtual query decision modeling_task_sha256 does not match the confirmed modeling task.")
    for key in ("task_id", "target_id", "endpoint_definition"):
        if decision.get(key) != task.get(key):
            raise ValueError(f"Virtual query decision {key} does not exactly match the confirmed modeling task.")

    status = decision.get("decision")
    summary: dict[str, Any] = {
        "valid": True,
        "decision": status,
        "reason": decision.get("reason"),
        "decision_path": str(decision_path),
        "decision_sha256": decision_sha,
        "task_path": str(task_path),
        "task_sha256": task_sha256,
        "task_id": task.get("task_id"),
        "target_id": task.get("target_id"),
        "endpoint_definition": task.get("endpoint_definition"),
    }
    if status == "NOT_APPLICABLE":
        if query_path is not None and Path(query_path).expanduser().exists():
            raise ValueError("NOT_APPLICABLE virtual query decision must not have a virtual_query_input artifact.")
        if validation_path is not None and Path(validation_path).expanduser().exists():
            raise ValueError("NOT_APPLICABLE virtual query decision must not have a virtual_query_validation artifact.")
        summary["artifacts"] = {"virtual_query_input": None, "virtual_query_validation": None}
        return summary

    # RUN_PREDICTION
    if query_path is None or validation_path is None:
        raise ValueError("RUN_PREDICTION decision requires both virtual_query_input and virtual_query_validation artifacts.")
    query_path = query_path.expanduser().resolve(strict=True)
    validation_path = validation_path.expanduser().resolve(strict=True)
    query = _read_json(query_path)
    if not isinstance(query, dict):
        raise ValueError("Virtual query input must be a JSON object.")
    _validate_query(query, task, label="confirmed modeling task")
    if set(query.keys()) != {"schema_version", "task_id", "target_id", "endpoint_definition", "features"}:
        raise ValueError("Virtual reproduction query must contain only schema_version, task_id, target_id, endpoint_definition, and features.")
    if set(query.get("features", {}).keys()) != set(_binding_map(task, "Confirmed modeling task").keys()):
        raise ValueError("Query feature IDs must match the confirmed modeling task exactly.")

    validation = _read_json(validation_path)
    if not isinstance(validation, dict):
        raise ValueError("Virtual query validation must be a JSON object.")
    if validation.get("schema_version") != "1.0" or validation.get("contract") != "VIRTUAL_QUERY_PREPARATION":
        raise ValueError("Virtual query validation has an unsupported contract.")
    if validation.get("valid") is not True:
        raise ValueError("Virtual query validation must declare valid=true.")
    if validation.get("decision") != "RUN_PREDICTION":
        raise ValueError("Virtual query validation must correspond to a RUN_PREDICTION decision.")
    if validation.get("task_sha256") != task_sha256:
        raise ValueError("Virtual query validation does not bind the exact confirmed modeling task.")
    if validation.get("decision_sha256") != decision_sha:
        raise ValueError("Virtual query validation does not bind the exact virtual query decision.")
    if validation.get("prepared_query_sha256") != sha256_file(query_path):
        raise ValueError("Virtual query validation does not bind the exact prepared virtual query input.")
    source_q = validation.get("source_query_path")
    source_q_sha = validation.get("source_query_sha256")
    if not isinstance(source_q, str) or not source_q.strip() or not isinstance(source_q_sha, str):
        raise ValueError("Virtual query validation must record source query provenance.")
    try:
        sp = Path(source_q).expanduser()
        if sp.exists() and sha256_file(sp.resolve(strict=True)) != source_q_sha:
            raise ValueError("Virtual query validation source query hash does not match the recorded source file.")
    except OSError:
        pass
    for key in ("task_id", "target_id", "endpoint_definition"):
        if validation.get(key) != task.get(key):
            raise ValueError(f"Virtual query validation {key} does not match the confirmed modeling task.")

    summary["artifacts"] = {
        "virtual_query_input": {"path": str(query_path), "sha256": sha256_file(query_path)},
        "virtual_query_validation": {"path": str(validation_path), "sha256": sha256_file(validation_path)},
    }
    return summary
