"""Domain-neutral exploratory profiling over a validated canonical bundle."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.scientific_opportunities import build_scientific_opportunities


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _has_normalized_pair(record: dict[str, Any]) -> bool:
    return (
        record.get("normalized_value") not in (None, "")
        and record.get("normalized_unit") not in (None, "")
    )


def _value(record: dict[str, Any]) -> Any:
    if _has_normalized_pair(record):
        return record["normalized_value"]
    return record.get("raw_value")


def _unit(record: dict[str, Any]) -> str:
    value = record.get("normalized_unit") if _has_normalized_pair(record) else record.get("raw_unit")
    return str(value).strip() if value not in (None, "") else "UNSPECIFIED_UNIT"


def _has_reported_value(record: dict[str, Any]) -> bool:
    return record.get("value_state") == "REPORTED" and any(
        record.get(field) not in (None, "") for field in ("raw_value", "normalized_value")
    )


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize_canonical_bundle(
    bundle: dict[str, Any],
    minimum_studies: int = 3,
    maximum_pairs: int = 250,
    minimum_paired_studies: int = 3,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    maximum_opportunities: int = 500,
    maximum_levels_per_condition: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """Summarize canonical entities without interpreting target or condition semantics."""
    if minimum_studies < 2 or maximum_pairs < 1:
        raise ValueError("minimum_studies must be >= 2 and maximum_pairs must be positive.")
    validation = validate_canonical_bundle(bundle)
    if not validation["valid"]:
        raise ValueError("Canonical bundle failed structural/reference validation: " +
                         json.dumps(validation["errors"][:10], ensure_ascii=False))

    studies = {item["study_id"]: item for item in bundle["studies"]}
    experiments = {item["experiment_id"]: item for item in bundle["experiments"]}
    conditions = {item["condition_id"]: item for item in bundle["conditions"]}
    observations = bundle["observations"]

    by_target_unit: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_study_target_unit: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    condition_links: dict[tuple[str, str], set[str]] = defaultdict(set)
    condition_observations: dict[tuple[str, str], set[str]] = defaultdict(set)
    targets_by_experiment: dict[str, set[str]] = defaultdict(set)
    study_by_experiment = {item["experiment_id"]: item["study_id"] for item in bundle["experiments"]}
    reported_numeric = 0

    for observation in observations:
        target_id = str(observation.get("target_id") or "UNSPECIFIED_TARGET")
        experiment_id = observation["experiment_id"]
        experiment = experiments[experiment_id]
        study_id = experiment["study_id"]
        unit = _unit(observation)
        by_target_unit[(target_id, unit)].append(observation)
        if _has_reported_value(observation):
            targets_by_experiment[experiment_id].add(target_id)

        numeric = _number(_value(observation))
        if _has_reported_value(observation) and numeric is not None and unit != "UNSPECIFIED_UNIT":
            reported_numeric += 1
            by_study_target_unit[(target_id, unit, study_id)].append(numeric)

        if not _has_reported_value(observation):
            continue
        for condition_id in experiment.get("condition_ids", []):
            condition = conditions[condition_id]
            if not _has_reported_value(condition):
                continue
            condition_type = str(condition.get("condition_type") or "UNSPECIFIED_CONDITION")
            condition_links[(target_id, condition_type)].add(study_id)
            condition_observations[(target_id, condition_type)].add(observation["observation_id"])

    target_rows: list[dict[str, Any]] = []
    study_rows: list[dict[str, Any]] = []
    condition_rows: list[dict[str, Any]] = []
    joint_rows: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for (target_id, unit), items in sorted(by_target_unit.items()):
        numeric = [
            value for item in items
            if _has_reported_value(item)
            and (value := _number(_value(item))) is not None
            and unit != "UNSPECIFIED_UNIT"
        ]
        study_count = len({
            study_by_experiment[item["experiment_id"]] for item in items
        })
        reported_items = [item for item in items if _has_reported_value(item)]
        reported_study_count = len({
            study_by_experiment[item["experiment_id"]] for item in reported_items
        })
        target_rows.append({
            "target_id": target_id,
            "unit": unit,
            "observation_count": len(items),
            "study_count": study_count,
            "reported_observation_count": len(reported_items),
            "reported_study_count": reported_study_count,
            "reported_numeric_count": len(numeric),
            "numeric_min": min(numeric) if numeric else None,
            "numeric_median": _median(numeric),
            "numeric_max": max(numeric) if numeric else None,
        })

    study_medians: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (target_id, unit, study_id), values in sorted(by_study_target_unit.items()):
        median = _median(values)
        study_rows.append({
            "target_id": target_id,
            "unit": unit,
            "study_id": study_id,
            "observation_count": len(values),
            "study_median": median,
        })
        if median is not None:
            study_medians[(target_id, unit)].append(median)

    for (target_id, unit), values in sorted(study_medians.items()):
        if len(values) >= minimum_studies:
            signals.append({
                "signal_id": f"VAR-{len(signals) + 1:04d}",
                "signal_type": "CROSS_STUDY_DESCRIPTIVE_VARIATION",
                "target_id": target_id,
                "unit": unit,
                "supporting_study_count": len(values),
                "study_median_min": min(values),
                "study_median_median": _median(values),
                "study_median_max": max(values),
                "interpretation_status": "DESCRIPTIVE_ONLY_NOT_AN_INFERENTIAL_TEST",
            })

    for (target_id, condition_type), study_ids in sorted(condition_links.items()):
        observation_count = len(condition_observations[(target_id, condition_type)])
        condition_rows.append({
            "target_id": target_id,
            "condition_type": condition_type,
            "observation_count_with_condition": observation_count,
            "study_count": len(study_ids),
        })
        if len(study_ids) >= minimum_studies:
            signals.append({
                "signal_id": f"COND-{len(signals) + 1:04d}",
                "signal_type": "CONDITION_COVERAGE",
                "target_id": target_id,
                "condition_type": condition_type,
                "supporting_observation_count": observation_count,
                "supporting_study_count": len(study_ids),
                "interpretation_status": "COVERAGE_ONLY_NO_CONDITION_EFFECT_ESTIMATED",
            })

    pair_support: dict[tuple[str, str], set[str]] = defaultdict(set)
    for experiment_id, target_ids in targets_by_experiment.items():
        study_id = study_by_experiment[experiment_id]
        ordered = sorted(target_ids)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                pair_support[(left, right)].add(study_id)

    sorted_pairs = sorted(
        pair_support.items(),
        key=lambda item: (-len(item[1]), item[0])
    )[:maximum_pairs]
    for left_right, study_ids in sorted_pairs:
        left, right = left_right
        joint_rows.append({
            "target_a": left,
            "target_b": right,
            "supporting_study_count": len(study_ids),
            "linkage_basis": "SHARED_CANONICAL_EXPERIMENT",
        })
        if len(study_ids) >= minimum_studies:
            signals.append({
                "signal_id": f"PAIR-{len(signals) + 1:04d}",
                "signal_type": "CO_OBSERVED_TARGET_PAIR",
                "target_a": left,
                "target_b": right,
                "supporting_study_count": len(study_ids),
                "interpretation_status": "CO_OBSERVATION_ONLY_NOT_AN_INTERACTION",
            })

    scientific = build_scientific_opportunities(
        bundle,
        minimum_paired_studies=minimum_paired_studies,
        fdr_alpha=fdr_alpha,
        bootstrap_iterations=bootstrap_iterations,
        maximum_opportunities=maximum_opportunities,
        maximum_levels_per_condition=maximum_levels_per_condition,
        seed=seed,
    )
    signals.extend(scientific["signals"])

    studies_with_observations = {
        study_by_experiment[item["experiment_id"]]
        for item in observations
        if item.get("experiment_id") in study_by_experiment
    }
    systems_with_experiments = {item["system_id"] for item in bundle["experiments"]}
    profile = {
        "study_count": len(studies),
        "study_count_with_observations": len(studies_with_observations),
        "study_count_without_observations": len(set(studies) - studies_with_observations),
        "system_count": len(bundle["systems"]),
        "system_count_with_experiments": len(systems_with_experiments),
        "system_count_without_experiments": len(set(item["system_id"] for item in bundle["systems"]) - systems_with_experiments),
        "condition_count": len(conditions),
        "experiment_count": len(experiments),
        "observation_count": len(observations),
        "target_count": len({str(item.get("target_id") or "UNSPECIFIED_TARGET") for item in observations}),
        "reported_numeric_observation_count": reported_numeric,
        "minimum_studies_for_cross_study_signal": minimum_studies,
    }
    return {
        "profile": profile,
        "target_rows": target_rows,
        "study_rows": study_rows,
        "condition_rows": condition_rows,
        "joint_rows": joint_rows,
        "signals": signals,
        "scientific": scientific,
        "interpretation_boundary": [
            "Summaries use the canonical entity links supplied by the adapter or approved mapping.",
            "Units are kept as exact strings; no implicit conversion is performed.",
            "Study-level summaries are descriptive and are not inferential heterogeneity tests.",
            "Co-observation within one canonical experiment does not establish causality or interaction.",
            "Statistical screens and q-values are prioritization evidence only; they do not establish scientific significance, causality, mechanism, novelty, or publication-worthiness.",
        ],
    }


def run_canonical_discovery_scan(
    bundle_path: Path,
    output_dir: Path,
    minimum_studies: int = 3,
    maximum_pairs: int = 250,
    minimum_paired_studies: int = 3,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    maximum_opportunities: int = 500,
    maximum_levels_per_condition: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """Create a read-only exploratory report from a canonical bundle."""
    bundle_path = bundle_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Canonical bundle does not exist: {bundle_path}")
    if output_dir == bundle_path or output_dir.is_relative_to(bundle_path):
        raise ValueError("Discovery output must be separate from the canonical bundle.")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Output path is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise FileExistsError(f"Refusing to overwrite a non-empty output directory: {output_dir}")

    input_hash = _sha256(bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
    result = summarize_canonical_bundle(
        bundle, minimum_studies, maximum_pairs, minimum_paired_studies,
        fdr_alpha, bootstrap_iterations, maximum_opportunities,
        maximum_levels_per_condition, seed,
    )
    if _sha256(bundle_path) != input_hash:
        raise RuntimeError("Canonical bundle changed during discovery scan.")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "target_support.csv",
        ["target_id", "unit", "observation_count", "study_count", "reported_observation_count",
         "reported_study_count", "reported_numeric_count", "numeric_min", "numeric_median", "numeric_max"],
        result["target_rows"])
    _write_csv(output_dir / "study_coverage.csv",
        ["target_id", "unit", "study_id", "observation_count", "study_median"], result["study_rows"])
    _write_csv(output_dir / "condition_support.csv",
        ["target_id", "condition_type", "observation_count_with_condition", "study_count"], result["condition_rows"])
    _write_csv(output_dir / "joint_support.csv",
        ["target_a", "target_b", "supporting_study_count", "linkage_basis"], result["joint_rows"])
    _write_csv(output_dir / "signal_catalogue.csv",
        ["signal_id", "signal_type", "target_id", "target_a", "target_b", "unit",
         "condition_type", "supporting_observation_count", "supporting_study_count",
         "study_median_min", "study_median_median", "study_median_max",
         "effect_size", "p_value", "q_value", "screen_status", "interpretation_status"], result["signals"])

    scientific = result["scientific"]
    _write_csv(output_dir / "condition_outcome_contrasts.csv",
        ["analysis_family", "target_id", "endpoint_definition", "timepoint", "outcome_unit",
         "condition_type", "condition_unit", "level_a", "level_b", "contrast_orientation",
         "level_a_study_count", "level_b_study_count", "level_a_system_count", "level_b_system_count",
         "independent_study_count", "paired_study_count", "paired_system_count", "experiment_count",
         "observation_count", "median_study_difference_b_minus_a", "study_difference_ci95",
         "positive_study_count", "negative_study_count", "zero_study_count", "p_value", "q_value",
         "interpretation_status", "study_effects_json"],
        [{**{key: value for key, value in row.items() if key != "study_effects"},
          "study_difference_ci95": json.dumps(row.get("study_difference_ci95"), ensure_ascii=False),
          "study_effects_json": json.dumps(row.get("study_effects", []), ensure_ascii=False, sort_keys=True)}
         for row in scientific["contrasts"]])
    _write_csv(output_dir / "condition_level_support.csv",
        ["target_id", "endpoint_definition", "timepoint", "outcome_unit",
         "condition_type", "condition_unit", "condition_level", "study_count",
         "system_count", "experiment_count"], scientific["condition_level_support"])
    _write_csv(output_dir / "condition_outcome_correlations.csv",
        ["analysis_family", "target_id", "endpoint_definition", "timepoint", "outcome_unit",
         "condition_type", "condition_unit", "independent_study_count", "system_correlation_count",
         "experiment_count", "observation_count", "median_study_spearman_rho", "study_spearman_ci95",
         "positive_study_count", "negative_study_count", "zero_study_count", "p_value", "q_value",
         "deduplication_status", "mirror_group_id", "mirror_duplicate_of_opportunity_id",
         "confounding_review_json", "interpretation_status", "study_effects_json"],
        [{**{key: value for key, value in row.items() if key != "study_effects"},
          "study_spearman_ci95": json.dumps(row.get("study_spearman_ci95"), ensure_ascii=False),
          "confounding_review_json": json.dumps(row.get("confounding_review"), ensure_ascii=False, sort_keys=True),
          "study_effects_json": json.dumps(row.get("study_effects", []), ensure_ascii=False, sort_keys=True)}
         for row in scientific["correlations"]])

    opportunity_payload = {
        "schema_version": "1.0",
        "engine_version": scientific["profile"]["engine_version"],
        "input_bundle_sha256": input_hash,
        "candidate_count_before_limit": scientific["profile"]["opportunity_count_before_limit"],
        "candidate_count_written": len(scientific["opportunities"]),
        "opportunities": scientific["opportunities"],
        "excluded_self_associations": scientific["self_association_exclusions"],
        "mirror_duplicates": scientific["mirror_duplicates"],
        "limitations": scientific["limitations"],
    }
    (output_dir / "research_opportunities.json").write_text(
        json.dumps(opportunity_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "evidence_ledger.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in scientific["evidence_ledger"]),
        encoding="utf-8",
    )
    scientific_profile = {
        "profile": scientific["profile"],
        "limitations": scientific["limitations"],
        "analysis_families": {
            "paired_contrast": "Study-level exact two-sided sign test; within-System paired contrasts; BH correction",
            "numeric_trend": "Within-System and between-System within-Study Spearman screens; one effect per Study; exact sign test and BH correction",
            "between_system_contrast": "Cross-sectional System-level group medians within each Study; independent Study sign test; BH correction",
        },
    }
    (output_dir / "scientific_analysis_profile.json").write_text(
        json.dumps(scientific_profile, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "schema_version": "1.2",
        "input_type": "CANONICAL_BUNDLE",
        "input_bundle_sha256": input_hash,
        "profile": result["profile"],
        "signal_count": len(result["signals"]),
        "signals": result["signals"],
        "scientific_analysis": scientific_profile,
        "research_opportunities_file": "research_opportunities.json",
        "research_opportunity_count": len(scientific["opportunities"]),
        "excluded_self_association_count": len(scientific["self_association_exclusions"]),
        "mirror_duplicate_opportunity_count": scientific["profile"]["mirror_duplicate_opportunity_count"],
        "mirror_duplicate_group_count": scientific["profile"]["mirror_duplicate_group_count"],
        "evidence_ledger_file": "evidence_ledger.jsonl",
        "evidence_ledger_row_count": len(scientific["evidence_ledger"]),
        "interpretation_boundary": result["interpretation_boundary"] + scientific["limitations"],
    }
    (output_dir / "discovery_data_profile.json").write_text(
        json.dumps(result["profile"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "discovery_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    brief_lines = [
        "# Exploratory research brief",
        "",
        "This brief contains aggregate summaries only. It does not contain raw observations, source quotations, or full source records.",
        "",
        "## Dataset profile",
        "",
    ]
    for key, value in result["profile"].items():
        brief_lines.append(f"- {key}: {value}")
    brief_lines.extend(["", "## DOR-generated research opportunities", ""])
    for opportunity in scientific["opportunities"][:25]:
        brief_lines.append(
            f"- {opportunity['opportunity_id']}: {opportunity['scientific_question']} "
            f"| studies={opportunity['independent_study_count']} "
            f"| effect={opportunity['effect_size']} "
            f"| p={opportunity['p_value']} | q={opportunity['q_value']} "
            f"| status={opportunity['screen_status']}"
        )
    brief_lines.extend(["", "These candidates are generated by deterministic Runtime analysis. Agent review may challenge interpretation but must not replace, fabricate, or silently promote these evidence records.", ""])
    brief_lines.extend(["", "## Excluded structural self-associations", ""])
    for exclusion in scientific["self_association_exclusions"]:
        brief_lines.append("- " + json.dumps(exclusion, ensure_ascii=False, sort_keys=True))
    if not scientific["self_association_exclusions"]:
        brief_lines.append("- None detected by the conservative identity checks.")
    brief_lines.extend(["", "## Exact mirror-duplicate relationships", ""])
    for duplicate in scientific["mirror_duplicates"]:
        brief_lines.append("- " + json.dumps(duplicate, ensure_ascii=False, sort_keys=True))
    if not scientific["mirror_duplicates"]:
        brief_lines.append("- None proven by the exact reciprocal-value and support checks.")
    brief_lines.extend(["", "## Candidate semantic and confounding review", ""])
    for opportunity in scientific["opportunities"]:
        brief_lines.append(
            f"- {opportunity['opportunity_id']}: semantic={opportunity['semantic_review']['status']}; "
            f"confounding={opportunity['confounding_review']['status']}"
        )
    brief_lines.extend(["", "## Candidate signals", ""])
    for signal in result["signals"][:40]:
        brief_lines.append("- " + json.dumps(signal, ensure_ascii=False, sort_keys=True))
    brief_lines.extend(["", "## Interpretation limits", ""])
    brief_lines.extend("- " + item for item in result["interpretation_boundary"])
    brief_lines.append("")
    brief_path = output_dir / "agent_research_brief.md"
    brief_path.write_text("\n".join(brief_lines), encoding="utf-8")

    output_files = sorted(
        item for item in output_dir.iterdir()
        if item.is_file() and item.name != "discovery_manifest.json"
    )
    manifest = {
        "schema_version": "1.0",
        "input_bundle_path": str(bundle_path),
        "input_bundle_sha256": input_hash,
        "source_files_modified": False,
        "raw_observations_in_agent_brief": False,
        "scientific_discovery_engine": scientific["profile"],
        "output_files": [
            {"path": item.name, "sha256": _sha256(item)} for item in output_files
        ],
        "scope": "READ_ONLY_CANONICAL_BUNDLE_EXPLORATORY_PROFILE",
    }
    (output_dir / "discovery_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "completed",
        "output_dir": str(output_dir),
        "input_bundle_sha256": input_hash,
        "profile": result["profile"],
        "signal_count": len(result["signals"]),
        "research_opportunity_count": len(scientific["opportunities"]),
        "mirror_duplicate_opportunity_count": scientific["profile"]["mirror_duplicate_opportunity_count"],
        "mirror_duplicate_group_count": scientific["profile"]["mirror_duplicate_group_count"],
        "fdr_screen_positive_count": scientific["profile"]["fdr_screen_positive_count"],
        "manifest_path": str(output_dir / "discovery_manifest.json"),
        "report_path": str(output_dir / "discovery_report.json"),
        "brief_path": str(brief_path),
    }
