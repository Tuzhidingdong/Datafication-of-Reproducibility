"""Cross-Study screening of pairwise predictive interaction terms for numeric endpoints.

This module estimates incremental held-out predictive value. It does not estimate causal
synergy, physical mechanisms, or inferential p-values.
"""
from __future__ import annotations
import csv, hashlib, itertools, json, math
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file
from dor.modeling import (
    _fit_encoder, _fit_ridge, _finite_number, _partition, _predict_ridge,
    _regression_metrics, _settings, _transform_rows, _typed_rows, _load_cohort,
)
from dor.reproducibility import _grouped_folds, _validation_studies

ENGINE_VERSION = "dor-runtime/0.1.0"
DEFAULT_MIN_OBSERVATIONS = 10
DEFAULT_MIN_STUDIES = 3
DEFAULT_MIN_POSITIVE_FOLD_FRACTION = 0.6
DEFAULT_MAX_PAIRS = 100
DEFAULT_MAX_INTERACTION_COLUMNS = 500


def _interaction_settings(task: dict[str, Any], feature_ids: set[str]) -> dict[str, Any]:
    spec = task.get("interaction_discovery", {})
    if not isinstance(spec, dict):
        raise ValueError("interaction_discovery must be an object.")
    allowed = {"feature_pairs", "minimum_joint_observations", "minimum_joint_studies",
               "minimum_positive_fold_fraction", "maximum_feature_pairs",
               "maximum_interaction_columns"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError("Unsupported interaction_discovery settings: " + ", ".join(unknown))
    pairs = spec.get("feature_pairs")
    if pairs is None:
        pair_ids = list(itertools.combinations(sorted(feature_ids), 2))
    else:
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("interaction_discovery.feature_pairs must be a non-empty list when supplied.")
        pair_ids = []
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(pairs):
            if not isinstance(item, dict) or set(item) != {"feature_a", "feature_b"}:
                raise ValueError("Each feature_pairs item must contain exactly feature_a and feature_b.")
            a, b = item["feature_a"], item["feature_b"]
            if not isinstance(a, str) or not isinstance(b, str) or a not in feature_ids or b not in feature_ids or a == b:
                raise ValueError("Each interaction pair must reference two distinct feature_id values in feature_bindings.")
            key = tuple(sorted((a, b)))
            if key in seen:
                raise ValueError("Duplicate interaction pair at feature_pairs index " + str(index) + ".")
            seen.add(key)
            pair_ids.append(key)
    minimum_observations = spec.get("minimum_joint_observations", DEFAULT_MIN_OBSERVATIONS)
    minimum_studies = spec.get("minimum_joint_studies", DEFAULT_MIN_STUDIES)
    positive_fraction = spec.get("minimum_positive_fold_fraction", DEFAULT_MIN_POSITIVE_FOLD_FRACTION)
    maximum_pairs = spec.get("maximum_feature_pairs", DEFAULT_MAX_PAIRS)
    maximum_columns = spec.get("maximum_interaction_columns", DEFAULT_MAX_INTERACTION_COLUMNS)
    if not isinstance(minimum_observations, int) or isinstance(minimum_observations, bool) or minimum_observations < 2:
        raise ValueError("minimum_joint_observations must be an integer >= 2.")
    if not isinstance(minimum_studies, int) or isinstance(minimum_studies, bool) or minimum_studies < 2:
        raise ValueError("minimum_joint_studies must be an integer >= 2.")
    if not _finite_number(positive_fraction) or not 0 < float(positive_fraction) <= 1:
        raise ValueError("minimum_positive_fold_fraction must be in (0, 1].")
    if not isinstance(maximum_pairs, int) or isinstance(maximum_pairs, bool) or maximum_pairs < 1:
        raise ValueError("maximum_feature_pairs must be a positive integer.")
    if not isinstance(maximum_columns, int) or isinstance(maximum_columns, bool) or maximum_columns < 1:
        raise ValueError("maximum_interaction_columns must be a positive integer.")
    if len(pair_ids) > maximum_pairs:
        raise ValueError("Candidate pair count exceeds maximum_feature_pairs; explicitly restrict the scientifically justified candidate list.")
    if not pair_ids:
        raise ValueError("At least two distinct feature bindings or one explicit feature pair are required.")
    return {"feature_pairs": pair_ids, "minimum_joint_observations": minimum_observations,
            "minimum_joint_studies": minimum_studies,
            "minimum_positive_fold_fraction": float(positive_fraction),
            "maximum_feature_pairs": maximum_pairs, "maximum_interaction_columns": maximum_columns}


def _encode_pair_columns(encoder: dict[str, Any], feature_a: str, feature_b: str,
                         maximum_columns: int) -> list[tuple[int, int]]:
    columns = encoder["columns"]
    idx_a = [i for i, item in enumerate(columns) if item["feature_id"] == feature_a]
    idx_b = [i for i, item in enumerate(columns) if item["feature_id"] == feature_b]
    products = [(a, b) for a in idx_a for b in idx_b]
    if not products:
        raise ValueError("No encoded columns found for candidate pair.")
    if len(products) > maximum_columns:
        raise OverflowError("PAIR_INTERACTION_ENCODING_EXCEEDS_LIMIT")
    return products


def _append_pair_products(matrix: list[list[float]], pair_columns: list[tuple[int, int]]) -> list[list[float]]:
    return [row + [row[a] * row[b] for a, b in pair_columns] for row in matrix]


def _fit_pair_candidate(train: list[dict[str, Any]], validation: list[dict[str, Any]],
                        bindings: list[dict[str, Any]], pair: tuple[str, str],
                        settings: dict[str, Any], maximum_columns: int) -> tuple[float, list[dict[str, Any]]]:
    y_train = [row["outcome"] for row in train]
    y_validation = [row["outcome"] for row in validation]
    encoder, x_train_base = _fit_encoder(train, bindings)
    x_validation_base = _transform_rows(validation, encoder)
    pair_columns = _encode_pair_columns(encoder, pair[0], pair[1], maximum_columns)
    x_train = _append_pair_products(x_train_base, pair_columns)
    x_validation = _append_pair_products(x_validation_base, pair_columns)
    comparisons = []
    for alpha in settings["ridge_alphas"]:
        fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
        predictions = _predict_ridge(x_validation, fitted)
        comparisons.append({"alpha": alpha, "validation_metrics": _regression_metrics(y_validation, predictions),
                            "converged": fitted["converged"], "iterations": fitted["iterations"],
                            "eligible_for_selection": bool(fitted["converged"])})
    eligible = [item for item in comparisons if item["eligible_for_selection"]]
    if not eligible:
        raise RuntimeError("NO_CONVERGED_RIDGE_CANDIDATE_FOR_PAIR_INTERACTION")
    chosen = min(eligible, key=lambda item: (item["validation_metrics"]["rmse"], item["alpha"]))
    return float(chosen["alpha"]), comparisons


def _fit_additive_candidate(train: list[dict[str, Any]], validation: list[dict[str, Any]],
                            bindings: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    y_train = [row["outcome"] for row in train]
    y_validation = [row["outcome"] for row in validation]
    encoder, x_train = _fit_encoder(train, bindings)
    x_validation = _transform_rows(validation, encoder)
    comparisons = []
    for alpha in settings["ridge_alphas"]:
        fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
        predictions = _predict_ridge(x_validation, fitted)
        comparisons.append({"alpha": alpha, "validation_metrics": _regression_metrics(y_validation, predictions),
                            "converged": fitted["converged"], "iterations": fitted["iterations"],
                            "eligible_for_selection": bool(fitted["converged"])})
    eligible = [item for item in comparisons if item["eligible_for_selection"]]
    if not eligible:
        raise RuntimeError("NO_CONVERGED_RIDGE_CANDIDATE_FOR_ADDITIVE_MODEL")
    chosen = min(eligible, key=lambda item: (item["validation_metrics"]["rmse"], item["alpha"]))
    return float(chosen["alpha"]), comparisons


def _fit_predict_outer(train: list[dict[str, Any]], test: list[dict[str, Any]],
                       bindings: list[dict[str, Any]], alpha: float,
                       pair: tuple[str, str] | None, settings: dict[str, Any],
                       maximum_columns: int) -> tuple[list[float], bool]:
    y_train = [row["outcome"] for row in train]
    encoder, x_train_base = _fit_encoder(train, bindings)
    x_test_base = _transform_rows(test, encoder)
    if pair is not None:
        pair_columns = _encode_pair_columns(encoder, pair[0], pair[1], maximum_columns)
        x_train = _append_pair_products(x_train_base, pair_columns)
        x_test = _append_pair_products(x_test_base, pair_columns)
    else:
        x_train, x_test = x_train_base, x_test_base
    fitted = _fit_ridge(x_train, y_train, alpha, settings["max_iter"], settings["tolerance"])
    if not fitted["converged"]:
        raise RuntimeError("RIDGE_OUTER_REFIT_NOT_CONVERGED")
    return _predict_ridge(x_test, fitted), True


def _joint_coverage(rows: list[dict[str, Any]], feature_a: str, feature_b: str) -> dict[str, Any]:
    combinations = {(str(row[feature_a]), str(row[feature_b])) for row in rows}
    studies = sorted({row["study_id"] for row in rows})
    return {
        "observation_count": len(rows),
        "study_count": len(studies),
        "study_ids": studies,
        "distinct_observed_value_pairs": len(combinations),
        "feature_a_observed_values": len({str(row[feature_a]) for row in rows}),
        "feature_b_observed_values": len({str(row[feature_b]) for row in rows})
    }


def _per_study_uplift(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["study_id"], []).append(row)
    result = []
    for study_id in sorted(groups):
        values = groups[study_id]
        additive_errors = [abs(item["additive_prediction"] - item["actual"]) for item in values]
        interaction_errors = [abs(item["interaction_prediction"] - item["actual"]) for item in values]
        additive_mae = sum(additive_errors) / len(values)
        interaction_mae = sum(interaction_errors) / len(values)
        result.append({
            "study_id": study_id, "fold": values[0]["fold"], "n": len(values),
            "additive_mae": additive_mae, "interaction_mae": interaction_mae,
            "mae_improvement": additive_mae - interaction_mae,
            "interaction_better": interaction_mae < additive_mae
        })
    return result


def _summarize_candidate(pair: tuple[str, str], coverage: dict[str, Any],
                         fold_results: list[dict[str, Any]], study_results: list[dict[str, Any]],
                         minimum_positive_fraction: float, minimum_studies: int) -> dict[str, Any]:
    improvements = [row["rmse_improvement"] for row in fold_results]
    positive_folds = sum(value > 0 for value in improvements)
    positive_fold_fraction = positive_folds / len(improvements) if improvements else 0.0
    mean_improvement = sum(improvements) / len(improvements) if improvements else None
    study_improvements = [row["mae_improvement"] for row in study_results]
    positive_studies = sum(value > 0 for value in study_improvements)
    positive_study_fraction = positive_studies / len(study_improvements) if study_improvements else 0.0
    if coverage["observation_count"] < 2 or coverage["study_count"] < minimum_studies:
        status = "INSUFFICIENT_JOINT_SUPPORT"
    elif positive_fold_fraction >= minimum_positive_fraction and mean_improvement is not None and mean_improvement > 0:
        status = "CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE"
    else:
        status = "NOT_STABLE_OR_NO_INCREMENTAL_GAIN"
    return {
        "feature_a": pair[0], "feature_b": pair[1],
        "interaction_id": "INT_" + hashlib.sha256((pair[0] + "|" + pair[1]).encode("utf-8")).hexdigest()[:20].upper(),
        "joint_coverage": coverage,
        "fold_count": len(fold_results),
        "positive_improvement_folds": positive_folds,
        "positive_improvement_fold_fraction": positive_fold_fraction,
        "mean_fold_rmse_improvement": mean_improvement,
        "study_count_evaluated": len(study_results),
        "positive_improvement_studies": positive_studies,
        "positive_improvement_study_fraction": positive_study_fraction,
        "per_fold": fold_results,
        "per_study": study_results,
        "interpretation_status": status,
        "claim_scope": "PREDICTIVE_STATISTICAL_INTERACTION_CANDIDATE_NOT_CAUSAL_OR_MECHANISTIC_EVIDENCE"
    }


def discover_interactions_files(cohort_dir: Path, task_path: Path, output_dir: Path,
                                folds: int | None = None, seed: int = 42) -> dict[str, Any]:
    cohort_dir = cohort_dir.expanduser().resolve()
    task_path = task_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty interaction output directory: " + str(output_dir))
    rows_raw, task, split_manifest, cohort_manifest = _load_cohort(cohort_dir, task_path)
    if task.get("outcome_type") != "NUMERIC":
        raise ValueError("The initial pairwise interaction engine supports NUMERIC endpoints only; categorical interaction methods require a separate validated contract.")
    settings = _settings(task)
    rows = _typed_rows(rows_raw, task)
    bindings = task["feature_bindings"]
    feature_ids = {binding["feature_id"] for binding in bindings}
    interaction_settings = _interaction_settings(task, feature_ids)
    study_ids = sorted({row["study_id"] for row in rows})
    if folds is None:
        folds = min(5, len(study_ids))
    if not isinstance(folds, int) or isinstance(folds, bool) or folds < 4:
        raise ValueError("Pairwise interaction cross-validation requires folds >= 4 and at least four eligible Studies.")
    if folds > len(study_ids):
        raise ValueError("Requested folds exceed eligible Study count.")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer.")
    pairs = interaction_settings["feature_pairs"]
    coverage_by_pair = {pair: _joint_coverage(rows, pair[0], pair[1]) for pair in pairs}
    candidates = []
    exclusions = []
    for pair in pairs:
        coverage = coverage_by_pair[pair]
        if coverage["observation_count"] < interaction_settings["minimum_joint_observations"]:
            exclusions.append({"feature_a":pair[0],"feature_b":pair[1],"reason":"INSUFFICIENT_JOINT_OBSERVATIONS","joint_coverage":coverage})
        elif coverage["study_count"] < interaction_settings["minimum_joint_studies"]:
            exclusions.append({"feature_a":pair[0],"feature_b":pair[1],"reason":"INSUFFICIENT_JOINT_STUDIES","joint_coverage":coverage})
        else:
            candidates.append(pair)
    if not candidates:
        raise ValueError("No candidate feature pairs meet the declared joint-support thresholds.")
    fold_groups = _grouped_folds(study_ids, folds, seed)
    all_results: dict[tuple[str,str], list[dict[str,Any]]] = {pair:[] for pair in candidates}
    all_predictions: dict[tuple[str,str], list[dict[str,Any]]] = {pair:[] for pair in candidates}
    failed_pairs: dict[tuple[str,str], list[int]] = {}
    failed_pair_reasons: dict[tuple[str,str], str] = {}
    fold_protocol = []
    max_columns = interaction_settings["maximum_interaction_columns"]
    for fold_index, held_studies in enumerate(fold_groups, start=1):
        outer_train_studies = sorted(set(study_ids) - set(held_studies))
        inner_train_studies, inner_validation_studies = _validation_studies(outer_train_studies, seed, fold_index)
        inner_train = [row for row in rows if row["study_id"] in inner_train_studies]
        inner_validation = [row for row in rows if row["study_id"] in inner_validation_studies]
        outer_train = [row for row in rows if row["study_id"] in outer_train_studies]
        outer_test = [row for row in rows if row["study_id"] in held_studies]
        if len(inner_train_studies) < 2 or not inner_validation or not outer_test:
            raise ValueError("A nested interaction fold has insufficient Study-level train/validation/test support.")
        additive_alpha, additive_validation = _fit_additive_candidate(inner_train,inner_validation,bindings,settings)
        additive_predictions, additive_converged = _fit_predict_outer(outer_train,outer_test,bindings,additive_alpha,None,settings,max_columns)
        y_test = [row["outcome"] for row in outer_test]
        additive_metrics = _regression_metrics(y_test,additive_predictions)
        fold_protocol.append({
            "fold":fold_index,"held_out_study_ids":sorted(held_studies),
            "outer_training_study_ids":outer_train_studies,
            "inner_training_study_ids":sorted(inner_train_studies),
            "inner_validation_study_ids":sorted(inner_validation_studies),
            "additive_alpha":additive_alpha,"additive_validation_comparison":additive_validation,
            "additive_outer_test_metrics":additive_metrics,"additive_converged":additive_converged
        })
        for pair in candidates:
            try:
                pair_alpha,pair_validation = _fit_pair_candidate(inner_train,inner_validation,bindings,pair,settings,max_columns)
                pair_predictions,pair_converged = _fit_predict_outer(outer_train,outer_test,bindings,pair_alpha,pair,settings,max_columns)
            except OverflowError:
                failed_pairs.setdefault(pair, []).append(fold_index)
                failed_pair_reasons[pair] = "PAIR_INTERACTION_ENCODING_EXCEEDS_LIMIT"
                continue
            except RuntimeError as exc:
                failed_pairs.setdefault(pair, []).append(fold_index)
                failed_pair_reasons[pair] = str(exc)
                continue
            pair_metrics = _regression_metrics(y_test,pair_predictions)
            improvement = additive_metrics["rmse"] - pair_metrics["rmse"]
            all_results[pair].append({
                "fold":fold_index,"held_out_study_ids":sorted(held_studies),
                "additive_alpha":additive_alpha,"interaction_alpha":pair_alpha,
                "additive_rmse":additive_metrics["rmse"],"interaction_rmse":pair_metrics["rmse"],
                "rmse_improvement":improvement,"interaction_validation_comparison":pair_validation,
                "interaction_converged":pair_converged
            })
            for index,row in enumerate(outer_test):
                all_predictions[pair].append({
                    "observation_id":row["observation_id"],"study_id":row["study_id"],"fold":fold_index,
                    "actual":row["outcome"],"additive_prediction":additive_predictions[index],
                    "interaction_prediction":pair_predictions[index],
                    "additive_absolute_error":abs(additive_predictions[index]-row["outcome"]),
                    "interaction_absolute_error":abs(pair_predictions[index]-row["outcome"])
                })
    for pair, failed_folds in sorted(failed_pairs.items()):
        reason = failed_pair_reasons.get(pair, "PAIR_INTERACTION_ENCODING_EXCEEDS_LIMIT")
        exclusions.append({"feature_a":pair[0],"feature_b":pair[1],
            "reason":reason,"folds":failed_folds})
    catalogue = []
    prediction_rows = []
    for pair in candidates:
        fold_results = all_results[pair]
        if not fold_results or pair in failed_pairs:
            continue
        study_results = _per_study_uplift(all_predictions[pair])
        summary = _summarize_candidate(pair,coverage_by_pair[pair],fold_results,study_results,
            interaction_settings["minimum_positive_fold_fraction"],interaction_settings["minimum_joint_studies"])
        catalogue.append(summary)
        for row in all_predictions[pair]:
            prediction_rows.append({"interaction_id":summary["interaction_id"],"feature_a":pair[0],
                "feature_b":pair[1],**row})
    catalogue.sort(key=lambda item:(item["interpretation_status"]!="CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE",
                                    -(item["mean_fold_rmse_improvement"] or 0),item["feature_a"],item["feature_b"]))
    report = {
        "schema_version":"1.0","task_id":task["task_id"],"target_id":task["target_id"],
        "endpoint_definition":task["endpoint_definition"],"outcome_type":"NUMERIC",
        "method":"NESTED_STUDY_GROUPED_PAIRWISE_BILINEAR_RIDGE_ABLATION",
        "statistic_definition":"Fold RMSE improvement = additive Ridge outer-test RMSE minus Ridge outer-test RMSE with the single candidate feature-pair's encoded cross-products added. Positive means lower error for the interaction-augmented model.",
        "fold_count":len(fold_groups),"study_count":len(study_ids),"observation_count":len(rows),
        "candidate_pair_count":len(pairs),"support_eligible_pair_count":len(candidates),
        "eligible_pair_count":len(catalogue),"excluded_pair_count":len(exclusions),"exclusions":exclusions,
        "minimum_joint_observations":interaction_settings["minimum_joint_observations"],
        "minimum_joint_studies":interaction_settings["minimum_joint_studies"],
        "minimum_positive_fold_fraction":interaction_settings["minimum_positive_fold_fraction"],
        "fold_protocol":fold_protocol,"interaction_catalogue":catalogue,
        "interpretation_limits":[
            "Only numeric endpoints are supported by this initial interaction engine.",
            "The interaction basis is a bilinear product of train-standardized numeric and one-hot categorical encoded columns.",
            "Predictive error improvement is not an inferential p-value, causal interaction estimate, synergistic effect, or physical mechanism.",
            "Candidate pairs are evaluated separately; results do not estimate the joint contribution of all interactions simultaneously.",
            "Study-grouped outer folds reduce leakage by canonical Study ID but do not resolve hidden dependencies between distinct Study records."
        ],
        "validation_scope":"NESTED_STUDY_HELD_OUT_PREDICTIVE_PAIR_SCREEN_NOT_CAUSAL_INFERENCE_OR_PROSPECTIVE_VALIDATION"
    }
    output_dir.mkdir(parents=True,exist_ok=True)
    report_path=output_dir/"interaction_discovery_report.json"
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    catalogue_path=output_dir/"interaction_catalogue.csv"
    fields=["interaction_id","feature_a","feature_b","interpretation_status","observation_count","study_count",
            "distinct_observed_value_pairs","fold_count","positive_improvement_folds",
            "positive_improvement_fold_fraction","mean_fold_rmse_improvement",
            "positive_improvement_studies","positive_improvement_study_fraction","claim_scope"]
    with catalogue_path.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader()
        for item in catalogue:
            coverage=item["joint_coverage"]
            writer.writerow({"interaction_id":item["interaction_id"],"feature_a":item["feature_a"],
                "feature_b":item["feature_b"],"interpretation_status":item["interpretation_status"],
                "observation_count":coverage["observation_count"],"study_count":coverage["study_count"],
                "distinct_observed_value_pairs":coverage["distinct_observed_value_pairs"],
                "fold_count":item["fold_count"],"positive_improvement_folds":item["positive_improvement_folds"],
                "positive_improvement_fold_fraction":item["positive_improvement_fold_fraction"],
                "mean_fold_rmse_improvement":item["mean_fold_rmse_improvement"],
                "positive_improvement_studies":item["positive_improvement_studies"],
                "positive_improvement_study_fraction":item["positive_improvement_study_fraction"],
                "claim_scope":item["claim_scope"]})
    prediction_fields=["interaction_id","feature_a","feature_b","observation_id","study_id","fold","actual",
                       "additive_prediction","interaction_prediction","additive_absolute_error","interaction_absolute_error"]
    with (output_dir/"interaction_oof_predictions.csv").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=prediction_fields); writer.writeheader(); writer.writerows(prediction_rows)
    input_hashes={"cohort_sha256":sha256_file(cohort_dir/"modeling_cohort.csv"),
        "cohort_report_sha256":sha256_file(cohort_dir/"cohort_report.json"),
        "split_manifest_sha256":sha256_file(cohort_dir/"split_manifest.json"),
        "cohort_manifest_sha256":sha256_file(cohort_dir/"modeling_cohort_manifest.json"),
        "task_sha256":sha256_file(task_path)}
    output_hashes={name:sha256_file(output_dir/name) for name in
        ("interaction_discovery_report.json","interaction_catalogue.csv","interaction_oof_predictions.csv")}
    manifest={"schema_version":"1.0","task_id":task["task_id"],"engine_version":ENGINE_VERSION,
        "input_hashes":input_hashes,"output_hashes":output_hashes,"fold_count":len(fold_groups),
        "seed":seed,"candidate_pair_count":len(pairs),"support_eligible_pair_count":len(candidates),
        "eligible_pair_count":len(catalogue),"method":"NESTED_STUDY_GROUPED_PAIRWISE_BILINEAR_RIDGE_ABLATION",
        "claim_scope":"PREDICTIVE_STATISTICAL_INTERACTION_CANDIDATE_NOT_CAUSAL_OR_MECHANISTIC_EVIDENCE",
        "source_policy":"TASK_AND_COHORT_READ_ONLY; OUTER_HELD_OUT_STUDIES_EXCLUDED_FROM_FITTING_AND_SELECTION"}
    (output_dir/"interaction_discovery_manifest.json").write_text(
        json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    return {"valid":True,"report":report,"manifest":manifest,"output_dir":str(output_dir)}
