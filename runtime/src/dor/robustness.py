"""Seed-sensitivity assessment for pairwise predictive interaction candidates.

This is a split-randomness sensitivity analysis, not an independent inferential test.
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
import tempfile
from pathlib import Path
from typing import Any

from dor.interactions import discover_interactions_files
from dor.mapping import sha256_file

ENGINE_VERSION = "dor-runtime/0.1.0"
DEFAULT_SEEDS = (11, 23, 42)
DEFAULT_STABLE_RUN_FRACTION = 0.8


def _validate_seeds(seeds: list[int] | tuple[int, ...]) -> list[int]:
    if not isinstance(seeds, (list, tuple)) or len(seeds) < 3:
        raise ValueError("At least three distinct integer seeds are required for sensitivity assessment.")
    if any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds):
        raise ValueError("Every robustness seed must be an integer.")
    if len(set(seeds)) != len(seeds):
        raise ValueError("Robustness seeds must be unique.")
    return list(seeds)


def _summarize_pair(pair_id: str, pair_runs: list[dict[str, Any]],
                    stable_run_fraction: float) -> dict[str, Any]:
    candidate_runs = [item for item in pair_runs
                      if item["interpretation_status"] == "CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE"]
    improvements = [item["mean_fold_rmse_improvement"] for item in pair_runs
                    if isinstance(item.get("mean_fold_rmse_improvement"), (int, float))]
    candidate_fraction = len(candidate_runs) / len(pair_runs)
    median_improvement = statistics.median(improvements) if improvements else None
    if candidate_fraction >= stable_run_fraction and median_improvement is not None and median_improvement > 0:
        status = "SEED_STABLE_PREDICTIVE_INTERACTION_CANDIDATE"
    elif candidate_fraction > 0:
        status = "SEED_SENSITIVE_PREDICTIVE_INTERACTION"
    else:
        status = "NOT_REPRODUCED_ACROSS_SEEDS"
    first = pair_runs[0]
    return {
        "interaction_id": first["interaction_id"],
        "feature_a": first["feature_a"],
        "feature_b": first["feature_b"],
        "run_count": len(pair_runs),
        "candidate_run_count": len(candidate_runs),
        "candidate_run_fraction": candidate_fraction,
        "median_mean_fold_rmse_improvement": median_improvement,
        "minimum_mean_fold_rmse_improvement": min(improvements) if improvements else None,
        "maximum_mean_fold_rmse_improvement": max(improvements) if improvements else None,
        "seed_results": pair_runs,
        "robustness_status": status,
        "claim_scope": "SEED_SENSITIVITY_OF_PREDICTIVE_SCREEN_NOT_INFERENTIAL_SIGNIFICANCE_CAUSALITY_OR_MECHANISM"
    }


def assess_interaction_robustness_files(
    cohort_dir: Path,
    task_path: Path,
    output_dir: Path,
    seeds: list[int] | tuple[int, ...] = DEFAULT_SEEDS,
    folds: int | None = None,
    minimum_candidate_run_fraction: float = DEFAULT_STABLE_RUN_FRACTION,
) -> dict[str, Any]:
    cohort_dir = cohort_dir.expanduser().resolve()
    task_path = task_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    seeds = _validate_seeds(seeds)
    if not isinstance(minimum_candidate_run_fraction, (int, float)) or isinstance(minimum_candidate_run_fraction, bool) or not 0 < minimum_candidate_run_fraction <= 1:
        raise ValueError("minimum_candidate_run_fraction must be in (0, 1].")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty robustness output directory: " + str(output_dir))

    run_catalogues: list[dict[str, Any]] = []
    run_protocol: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="dor-interaction-robustness-") as temporary:
        temporary_root = Path(temporary)
        for seed in seeds:
            run_dir = temporary_root / ("seed_" + str(seed))
            result = discover_interactions_files(cohort_dir, task_path, run_dir, folds=folds, seed=seed)
            report = result["report"]
            run_protocol.append({
                "seed": seed,
                "fold_count": report["fold_count"],
                "study_count": report["study_count"],
                "observation_count": report["observation_count"],
                "candidate_pair_count": report["candidate_pair_count"],
                "eligible_pair_count": report["eligible_pair_count"],
                "exclusions": report["exclusions"],
                "fold_protocol": report["fold_protocol"]
            })
            for item in report["interaction_catalogue"]:
                run_catalogues.append({
                    "seed": seed,
                    "interaction_id": item["interaction_id"],
                    "feature_a": item["feature_a"],
                    "feature_b": item["feature_b"],
                    "interpretation_status": item["interpretation_status"],
                    "mean_fold_rmse_improvement": item["mean_fold_rmse_improvement"],
                    "positive_improvement_fold_fraction": item["positive_improvement_fold_fraction"],
                    "positive_improvement_study_fraction": item["positive_improvement_study_fraction"]
                })

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in run_catalogues:
        grouped.setdefault(item["interaction_id"], []).append(item)
    # Include pairs that were support-eligible in one run but absent from another as explicit missing runs.
    pair_templates = {key: values[0] for key, values in grouped.items()}
    robustness_catalogue = []
    for interaction_id, template in sorted(pair_templates.items()):
        by_seed = {item["seed"]: item for item in grouped[interaction_id]}
        pair_runs = []
        for seed in seeds:
            item = by_seed.get(seed)
            if item is None:
                pair_runs.append({
                    "seed": seed,
                    "interaction_id": interaction_id,
                    "feature_a": template["feature_a"],
                    "feature_b": template["feature_b"],
                    "interpretation_status": "NOT_EVALUABLE_IN_THIS_SPLIT",
                    "mean_fold_rmse_improvement": None,
                    "positive_improvement_fold_fraction": None,
                    "positive_improvement_study_fraction": None
                })
            else:
                pair_runs.append(item)
        robustness_catalogue.append(_summarize_pair(interaction_id, pair_runs, float(minimum_candidate_run_fraction)))

    report = {
        "schema_version": "1.0",
        "method": "REPEATED_NESTED_STUDY_GROUPED_CV_SEED_SENSITIVITY",
        "seed_count": len(seeds),
        "seeds": seeds,
        "fold_count": run_protocol[0]["fold_count"],
        "minimum_candidate_run_fraction": float(minimum_candidate_run_fraction),
        "run_protocol": run_protocol,
        "interaction_catalogue": robustness_catalogue,
        "interpretation_limits": [
            "This analysis changes deterministic Study-grouped fold assignments through the random seed and repeats the complete nested interaction screen.",
            "It assesses sensitivity to split randomness only; it does not test alternative feature encodings, endpoint definitions, model families, hidden confounding, or external populations.",
            "Candidate-run fraction is a descriptive stability frequency, not a probability, p-value, confidence level, or FDR-adjusted statistic.",
            "A pair not present in a run's catalogue is marked NOT_EVALUABLE_IN_THIS_SPLIT rather than assigned zero improvement.",
            "A seed-stable predictive candidate is not a causal interaction, synergy claim, or physical mechanism."
        ],
        "validation_scope": "REPEATED_NESTED_STUDY_HELD_OUT_SEED_SENSITIVITY_NOT_INDEPENDENT_VALIDATION"
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "interaction_robustness_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    catalogue_path = output_dir / "interaction_robustness_catalogue.csv"
    fields = [
        "interaction_id", "feature_a", "feature_b", "robustness_status",
        "run_count", "candidate_run_count", "candidate_run_fraction",
        "median_mean_fold_rmse_improvement", "minimum_mean_fold_rmse_improvement",
        "maximum_mean_fold_rmse_improvement", "claim_scope"
    ]
    with catalogue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in robustness_catalogue:
            writer.writerow({key: item.get(key) for key in fields if key != "claim_scope"} |
                            {"claim_scope": item["claim_scope"]})

    input_hashes = {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "cohort_report_sha256": sha256_file(cohort_dir / "cohort_report.json"),
        "split_manifest_sha256": sha256_file(cohort_dir / "split_manifest.json"),
        "cohort_manifest_sha256": sha256_file(cohort_dir / "modeling_cohort_manifest.json"),
        "task_sha256": sha256_file(task_path)
    }
    output_hashes = {
        "interaction_robustness_report.json": sha256_file(report_path),
        "interaction_robustness_catalogue.csv": sha256_file(catalogue_path)
    }
    manifest = {
        "schema_version": "1.0",
        "engine_version": ENGINE_VERSION,
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "seeds": seeds,
        "fold_count": report["fold_count"],
        "minimum_candidate_run_fraction": float(minimum_candidate_run_fraction),
        "method": report["method"],
        "claim_scope": "SEED_SENSITIVITY_NOT_INFERENTIAL_SIGNIFICANCE_CAUSALITY_OR_MECHANISM",
        "source_policy": "TASK_AND_COHORT_READ_ONLY; EACH_RUN_USES_NESTED_STUDY_GROUPED_VALIDATION"
    }
    manifest_path = output_dir / "interaction_robustness_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    manifest["output_hashes"]["interaction_robustness_manifest.json"] = sha256_file(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"valid": True, "report": report, "manifest": manifest, "output_dir": str(output_dir)}
