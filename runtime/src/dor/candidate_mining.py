"""Candidate-value inventory and source-specific sensitivity mining.

Candidate alternatives remain attached to their source Observation/Condition. They
are never counted as additional experimental observations. Each candidate-source
scenario is run independently of the primary reported-value analysis.
"""
from __future__ import annotations

import copy
import json
import math
from collections import defaultdict
from typing import Any

from dor.scientific_opportunities import build_scientific_opportunities


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _nonblank(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidate_pair(candidate: dict[str, Any]) -> tuple[Any, str]:
    normalized_value = candidate.get("normalized_value")
    normalized_unit = candidate.get("normalized_unit")
    if _nonblank(normalized_value) and _nonblank(normalized_unit):
        return normalized_value, str(normalized_unit).strip()
    raw_value = candidate.get("raw_value")
    raw_unit = candidate.get("raw_unit")
    return raw_value, str(raw_unit).strip() if _nonblank(raw_unit) else "UNSPECIFIED_UNIT"


def _record_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = record.get("value_candidates", [])
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _has_primary_value(record: dict[str, Any]) -> bool:
    if record.get("value_state") != "REPORTED":
        return False
    return _nonblank(record.get("normalized_value")) or _nonblank(record.get("raw_value"))


def _candidate_status(candidates: list[dict[str, Any]]) -> str:
    usable = [_candidate_pair(item) for item in candidates if _nonblank(_candidate_pair(item)[0])]
    if not usable:
        return "NO_USABLE_VALUE"
    value_keys = {_json_key(value) for value, _ in usable}
    unit_keys = {unit for _, unit in usable}
    if len(value_keys) == 1 and len(unit_keys) == 1:
        return "EXACT_VALUE_UNIT_CONSENSUS"
    if len(value_keys) == 1:
        return "UNIT_CONFLICT"
    if len(unit_keys) == 1:
        return "VALUE_CONFLICT"
    return "VALUE_AND_UNIT_CONFLICT"


def _context(bundle: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    experiments = {row["experiment_id"]: row for row in bundle.get("experiments", [])}
    systems = {row["system_id"]: row for row in bundle.get("systems", [])}
    condition_experiments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for experiment in experiments.values():
        for condition_id in experiment.get("condition_ids", []):
            condition_experiments[condition_id].append(experiment)
    return experiments, systems, condition_experiments


def inventory_candidate_values(bundle: dict[str, Any]) -> dict[str, Any]:
    """Inventory candidate alternatives, record-level reconciliation and missingness."""
    experiments, systems, condition_experiments = _context(bundle)
    inventory: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    missingness: dict[tuple[str, str, str], dict[str, Any]] = {}

    entity_sets = (
        ("OBSERVATION", bundle.get("observations", [])),
        ("CONDITION", bundle.get("conditions", [])),
    )
    for entity_type, records in entity_sets:
        for record in records:
            record_id = record.get("observation_id") if entity_type == "OBSERVATION" else record.get("condition_id")
            if entity_type == "OBSERVATION":
                experiment = experiments.get(record.get("experiment_id"), {})
                related_experiments = [experiment] if experiment else []
                feature_id = str(record.get("target_id") or "UNSPECIFIED_TARGET")
                endpoint = record.get("endpoint_definition")
                timepoint = record.get("timepoint")
            else:
                related_experiments = condition_experiments.get(record_id, [])
                feature_id = str(record.get("condition_type") or "UNSPECIFIED_CONDITION")
                endpoint = None
                timepoint = None

            study_ids = sorted({str(item.get("study_id")) for item in related_experiments if item.get("study_id")})
            system_ids = sorted({
                str(item.get("system_id")) for item in related_experiments if item.get("system_id")
            } | {
                str(system_id) for system_id in record.get("system_ids", []) if entity_type == "CONDITION"
            })
            experiment_ids = sorted({str(item.get("experiment_id")) for item in related_experiments if item.get("experiment_id")})
            if entity_type == "CONDITION" and not study_ids:
                for system_id in system_ids:
                    system = systems.get(system_id, {})
                    study_ids.extend(str(value) for value in system.get("study_ids", []) if value)
                study_ids = sorted(set(study_ids))

            state = str(record.get("value_state") or "UNSPECIFIED_STATE")
            key = (entity_type, feature_id, state)
            aggregate = missingness.setdefault(key, {
                "entity_type": entity_type,
                "feature_id": feature_id,
                "value_state": state,
                "_record_ids": set(),
                "_study_ids": set(),
                "_system_ids": set(),
                "_experiment_ids": set(),
                "_candidate_record_ids": set(),
                "candidate_count": 0,
                "candidate_values_with_locators": 0,
                "candidate_quote_count": 0,
                "candidate_metadata_count": 0,
                "records_with_value": 0,
                "records_with_unit": 0,
            })
            aggregate["_record_ids"].add(str(record_id))
            aggregate["_study_ids"].update(study_ids)
            aggregate["_system_ids"].update(system_ids)
            aggregate["_experiment_ids"].update(experiment_ids)
            primary_value = record.get("normalized_value")
            primary_unit = record.get("normalized_unit")
            if not (_nonblank(primary_value) and _nonblank(primary_unit)):
                primary_value, primary_unit = record.get("raw_value"), record.get("raw_unit")
            if _nonblank(primary_value):
                aggregate["records_with_value"] += 1
            if _nonblank(primary_unit):
                aggregate["records_with_unit"] += 1

            candidates = _record_candidates(record)
            if candidates:
                aggregate["_candidate_record_ids"].add(str(record_id))
                aggregate["candidate_count"] += len(candidates)
            for candidate in candidates:
                candidate_value, candidate_unit = _candidate_pair(candidate)
                candidate_source = str(candidate.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE")
                locators = candidate.get("source_locators", [])
                if isinstance(locators, list) and locators:
                    aggregate["candidate_values_with_locators"] += 1
                quote = candidate.get("quoted_text")
                if isinstance(quote, str) and quote.strip():
                    aggregate["candidate_quote_count"] += 1
                source_metadata = candidate.get("source_metadata", {})
                if isinstance(source_metadata, dict) and source_metadata:
                    aggregate["candidate_metadata_count"] += 1
                inventory.append({
                    "entity_type": entity_type,
                    "record_id": record_id,
                    "feature_id": feature_id,
                    "study_ids_json": json.dumps(study_ids, ensure_ascii=False),
                    "system_ids_json": json.dumps(system_ids, ensure_ascii=False),
                    "experiment_ids_json": json.dumps(experiment_ids, ensure_ascii=False),
                    "endpoint_definition": endpoint,
                    "timepoint": timepoint,
                    "primary_value_state": state,
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_source": candidate_source,
                    "candidate_value": candidate_value,
                    "candidate_unit": candidate_unit,
                    "candidate_numeric_value": _finite_number(candidate_value),
                    "quoted_text": quote,
                    "source_metadata_json": json.dumps(source_metadata if isinstance(source_metadata, dict) else {}, ensure_ascii=False, sort_keys=True),
                    "source_locators_json": json.dumps(locators if isinstance(locators, list) else [], ensure_ascii=False, sort_keys=True),
                    "source_metadata_json": json.dumps(source_metadata if isinstance(source_metadata, dict) else {}, ensure_ascii=False, sort_keys=True),
                })

            if candidates:
                pairs = [_candidate_pair(item) for item in candidates if _nonblank(_candidate_pair(item)[0])]
                unique_values = sorted({_json_key(value) for value, _ in pairs})
                unique_units = sorted({unit for _, unit in pairs})
                reconciliation.append({
                    "entity_type": entity_type,
                    "record_id": record_id,
                    "feature_id": feature_id,
                    "primary_value_state": state,
                    "candidate_count": len(candidates),
                    "candidate_source_count": len({str(item.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE") for item in candidates}),
                    "usable_candidate_count": len(pairs),
                    "distinct_candidate_value_count": len(unique_values),
                    "distinct_candidate_unit_count": len(unique_units),
                    "reconciliation_status": _candidate_status(candidates),
                    "candidate_sources_json": json.dumps(sorted({str(item.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE") for item in candidates}), ensure_ascii=False),
                    "candidate_value_unit_pairs_json": json.dumps([
                        {"value": value, "unit": unit} for value, unit in pairs
                    ], ensure_ascii=False, sort_keys=True),
                    "candidate_metadata_keys_json": json.dumps(sorted({
                        key for candidate in candidates
                        for key in (candidate.get("source_metadata", {}) if isinstance(candidate.get("source_metadata"), dict) else {})
                    }), ensure_ascii=False),
                    "candidate_source_metadata_json": json.dumps([
                        {
                            "candidate_id": candidate.get("candidate_id"),
                            "candidate_source": candidate.get("candidate_source"),
                            "source_metadata": candidate.get("source_metadata", {}),
                        }
                        for candidate in candidates
                    ], ensure_ascii=False, sort_keys=True),
                })

    missingness_rows = []
    for row in missingness.values():
        missingness_rows.append({
            "entity_type": row["entity_type"],
            "feature_id": row["feature_id"],
            "value_state": row["value_state"],
            "record_count": len(row["_record_ids"]),
            "study_count": len(row["_study_ids"]),
            "system_count": len(row["_system_ids"]),
            "experiment_count": len(row["_experiment_ids"]),
            "records_with_candidates": len(row["_candidate_record_ids"]),
            "candidate_count": row["candidate_count"],
            "candidate_values_with_locators": row["candidate_values_with_locators"],
            "candidate_quote_count": row["candidate_quote_count"],
            "candidate_metadata_count": row["candidate_metadata_count"],
            "records_with_value": row["records_with_value"],
            "records_with_unit": row["records_with_unit"],
        })

    reconciliation_counts: dict[str, int] = defaultdict(int)
    for row in reconciliation:
        reconciliation_counts[row["reconciliation_status"]] += 1
    candidate_sources = sorted({
        str(row["candidate_source"]) for row in inventory
        if row.get("candidate_source") != "UNSPECIFIED_CANDIDATE_SOURCE"
    })
    profile = {
        "candidate_record_count": len(reconciliation),
        "candidate_entry_count": len(inventory),
        "candidate_value_count": sum(1 for row in inventory if _nonblank(row["candidate_value"])),
        "candidate_source_count": len(candidate_sources),
        "candidate_entries_without_value_count": sum(1 for row in inventory if not _nonblank(row["candidate_value"])),
        "candidate_sources": candidate_sources,
        "reconciliation_status_counts": dict(sorted(reconciliation_counts.items())),
        "candidate_observation_count": sum(1 for row in reconciliation if row["entity_type"] == "OBSERVATION"),
        "candidate_condition_count": sum(1 for row in reconciliation if row["entity_type"] == "CONDITION"),
        "candidate_entries_with_numeric_value_count": sum(1 for row in inventory if row["candidate_numeric_value"] is not None),
        "candidate_entries_with_unit_count": sum(1 for row in inventory if row["candidate_unit"] != "UNSPECIFIED_UNIT"),
        "candidate_entries_with_quote_count": sum(1 for row in inventory if isinstance(row["quoted_text"], str) and row["quoted_text"].strip()),
        "candidate_entries_with_metadata_fields_count": sum(1 for row in inventory if row["source_metadata_json"] != "{}"),
        "candidate_entries_with_metadata_count": sum(
            1 for row in inventory
            if any(value not in (None, "") for value in json.loads(row["source_metadata_json"]).values())
        ),
        "candidate_evidence_only_entry_count": sum(
            1 for row in inventory
            if not _nonblank(row["candidate_value"])
            and (
                bool(row["quoted_text"])
                or any(value not in (None, "") for value in json.loads(row["source_metadata_json"]).values())
                or row["source_locators_json"] != "[]"
            )
        ),
        "candidate_metadata_key_counts": dict(sorted({
            key: sum(1 for row in inventory if key in json.loads(row["source_metadata_json"]))
            for key in {
                metadata_key
                for row in inventory
                for metadata_key in json.loads(row["source_metadata_json"])
            }
        }.items())),
        "candidate_entries_with_locator_count": sum(1 for row in inventory if row["source_locators_json"] != "[]"),
        "candidate_metadata_keys": sorted({
            key for row in inventory
            for key in json.loads(row["source_metadata_json"])
        }),
        "missingness_group_count": len(missingness_rows),
    }
    return {
        "profile": profile,
        "inventory_rows": inventory,
        "reconciliation_rows": reconciliation,
        "missingness_rows": sorted(missingness_rows, key=lambda row: (row["entity_type"], row["feature_id"], row["value_state"])),
    }


def build_candidate_source_sensitivities(
    bundle: dict[str, Any],
    *,
    minimum_paired_studies: int = 3,
    fdr_alpha: float = 0.10,
    bootstrap_iterations: int = 1000,
    maximum_opportunities: int = 500,
    maximum_levels_per_condition: int = 20,
    seed: int = 42,
    semantic_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one isolated sensitivity scenario per candidate source, never per candidate row."""
    inventory = inventory_candidate_values(bundle)
    candidate_sources = inventory["profile"]["candidate_sources"]
    scenarios = []

    for candidate_source in candidate_sources:
        scenario_bundle = copy.deepcopy(bundle)
        overlay_counts = {"observations": 0, "conditions": 0}
        conflicts_skipped = {"observations": 0, "conditions": 0}
        unusable_candidates_skipped = {"observations": 0, "conditions": 0}
        primary_fallback_counts = {"observations": 0, "conditions": 0}

        for collection, entity_type, id_field in (
            ("observations", "observations", "observation_id"),
            ("conditions", "conditions", "condition_id"),
        ):
            for record in scenario_bundle.get(collection, []):
                matching = [
                    candidate for candidate in _record_candidates(record)
                    if str(candidate.get("candidate_source") or "UNSPECIFIED_CANDIDATE_SOURCE") == candidate_source
                ]
                if not matching:
                    if _has_primary_value(record):
                        primary_fallback_counts[entity_type] += 1
                    continue
                usable = [
                    _candidate_pair(candidate)
                    for candidate in matching
                    if _nonblank(_candidate_pair(candidate)[0])
                ]
                unique_pairs = {_json_key([value, unit]): (value, unit) for value, unit in usable}
                if len(unique_pairs) != 1:
                    if len(unique_pairs) > 1:
                        conflicts_skipped[entity_type] += 1
                    else:
                        unusable_candidates_skipped[entity_type] += 1
                    if _has_primary_value(record):
                        primary_fallback_counts[entity_type] += 1
                    continue
                selected_value, selected_unit = next(iter(unique_pairs.values()))
                matching_with_normalized_pair = [
                    item for item in matching
                    if _nonblank(item.get("normalized_value")) and _nonblank(item.get("normalized_unit"))
                ]
                if matching_with_normalized_pair:
                    chosen = matching_with_normalized_pair[0]
                    record["normalized_value"] = chosen.get("normalized_value")
                    record["normalized_unit"] = chosen.get("normalized_unit")
                    record["raw_value"] = chosen.get("raw_value")
                    record["raw_unit"] = chosen.get("raw_unit")
                else:
                    record["normalized_value"] = None
                    record["normalized_unit"] = None
                    record["raw_value"] = selected_value
                    record["raw_unit"] = None if selected_unit == "UNSPECIFIED_UNIT" else selected_unit
                record["value_state"] = "REPORTED"
                overlay_counts[entity_type] += 1

        if not any(overlay_counts.values()):
            continue

        analysis = build_scientific_opportunities(
            scenario_bundle,
            minimum_paired_studies=minimum_paired_studies,
            fdr_alpha=fdr_alpha,
            bootstrap_iterations=bootstrap_iterations,
            maximum_opportunities=maximum_opportunities,
            maximum_levels_per_condition=maximum_levels_per_condition,
            seed=seed,
            semantic_registry=semantic_registry,
        )
        scenarios.append({
            "candidate_source": candidate_source,
            "scenario_status": "CANDIDATE_SOURCE_SENSITIVITY_ONLY_NOT_PRIMARY",
            "scenario_data_composition": "CANDIDATE_SOURCE_WHERE_UNIQUE_WITH_PRIMARY_VALUE_FALLBACK_ELSEWHERE",
            "overlay_counts": overlay_counts,
            "primary_value_fallback_record_counts": primary_fallback_counts,
            "conflicting_candidate_records_skipped": conflicts_skipped,
            "unusable_candidate_records_skipped": unusable_candidates_skipped,
            "candidate_opportunity_count": len(analysis["opportunities"]),
            "fdr_screen_positive_count": analysis["profile"]["fdr_screen_positive_count"],
            "analysis_profile": analysis["profile"],
            "opportunities": analysis["opportunities"],
            "limitations": [
                "This scenario substitutes only the selected candidate source's values into a copy of the bundle.",
                "Candidate alternatives are not additional observations, replicates, Systems, or independent Studies.",
                "Results are sensitivity evidence and are not mixed with the primary reported-value results or their FDR family.",
                "Candidate extraction agreement does not establish source accuracy or scientific validity.",
            ],
        })

    return {
        "schema_version": "1.0",
        "status": "completed",
        "scenario_count": len(scenarios),
        "candidate_inventory_profile": inventory["profile"],
        "scenarios": scenarios,
    }
