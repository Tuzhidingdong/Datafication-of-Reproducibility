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


def _value(record: dict[str, Any]) -> Any:
    value = record.get("normalized_value")
    return record.get("raw_value") if value is None or value == "" else value


def _unit(record: dict[str, Any]) -> str:
    value = record.get("normalized_unit")
    if value is None or value == "":
        value = record.get("raw_unit")
    return str(value).strip() if value not in (None, "") else "UNSPECIFIED_UNIT"


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
        targets_by_experiment[experiment_id].add(target_id)

        numeric = _number(_value(observation))
        if observation.get("value_state") == "REPORTED" and numeric is not None and unit != "UNSPECIFIED_UNIT":
            reported_numeric += 1
            by_study_target_unit[(target_id, unit, study_id)].append(numeric)

        for condition_id in experiment.get("condition_ids", []):
            condition = conditions[condition_id]
            if condition.get("value_state") != "REPORTED":
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
            if item.get("value_state") == "REPORTED"
            and (value := _number(_value(item))) is not None
            and unit != "UNSPECIFIED_UNIT"
        ]
        study_count = len({
            study_by_experiment[item["experiment_id"]] for item in items
        })
        target_rows.append({
            "target_id": target_id,
            "unit": unit,
            "observation_count": len(items),
            "study_count": study_count,
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

    profile = {
        "study_count": len(studies),
        "system_count": len(bundle["systems"]),
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
        "interpretation_boundary": [
            "Summaries use the canonical entity links supplied by the adapter or approved mapping.",
            "Units are kept as exact strings; no implicit conversion is performed.",
            "Study-level summaries are descriptive and are not inferential heterogeneity tests.",
            "Co-observation within one canonical experiment does not establish causality or interaction.",
            "No causal, mechanistic, novelty, or statistical-significance claims are generated.",
        ],
    }


def run_canonical_discovery_scan(
    bundle_path: Path,
    output_dir: Path,
    minimum_studies: int = 3,
    maximum_pairs: int = 250,
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
    result = summarize_canonical_bundle(bundle, minimum_studies, maximum_pairs)
    if _sha256(bundle_path) != input_hash:
        raise RuntimeError("Canonical bundle changed during discovery scan.")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "target_support.csv",
        ["target_id", "unit", "observation_count", "study_count", "reported_numeric_count",
         "numeric_min", "numeric_median", "numeric_max"], result["target_rows"])
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
         "interpretation_status"], result["signals"])

    report = {
        "schema_version": "1.0",
        "input_type": "CANONICAL_BUNDLE",
        "input_bundle_sha256": input_hash,
        "profile": result["profile"],
        "signal_count": len(result["signals"]),
        "signals": result["signals"],
        "interpretation_boundary": result["interpretation_boundary"],
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
        "manifest_path": str(output_dir / "discovery_manifest.json"),
        "report_path": str(output_dir / "discovery_report.json"),
        "brief_path": str(brief_path),
    }
