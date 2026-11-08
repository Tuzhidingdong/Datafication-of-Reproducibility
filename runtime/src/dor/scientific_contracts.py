"""Non-destructive diagnostics for scientific record grain and explicit identities."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

EXPLICIT_OBSERVATION_ID_FIELDS = (
    "replicate_id", "replicate_group_id", "sample_id", "specimen_id",
    "measurement_id", "technical_replicate_id",
)


def _has_explicit_identity(observation: dict[str, Any]) -> bool:
    for field in EXPLICIT_OBSERVATION_ID_FIELDS:
        value = observation.get(field)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def inspect_scientific_data_grain(bundle: dict[str, Any]) -> dict[str, Any]:
    """Report ambiguous record grain without assigning replicate or independence semantics."""
    warnings: list[dict[str, Any]] = []
    conditions = {
        item.get("condition_id"): item
        for item in bundle.get("conditions", [])
        if isinstance(item, dict) and isinstance(item.get("condition_id"), str)
    }
    multiple_condition_groups = 0
    for experiment in bundle.get("experiments", []):
        if not isinstance(experiment, dict):
            continue
        by_type: dict[str, list[str]] = defaultdict(list)
        for condition_id in experiment.get("condition_ids", []):
            condition = conditions.get(condition_id)
            if condition is not None and isinstance(condition.get("condition_type"), str):
                by_type[condition["condition_type"]].append(condition_id)
        for condition_type, condition_ids in sorted(by_type.items()):
            if len(condition_ids) > 1:
                multiple_condition_groups += 1
                warnings.append({
                    "code": "MULTIPLE_CONDITIONS_SAME_TYPE_IN_EXPERIMENT",
                    "experiment_id": experiment.get("experiment_id"),
                    "condition_type": condition_type,
                    "condition_ids": sorted(condition_ids),
                    "interpretation": "AMBIGUOUS_FEATURE_BINDING_REQUIRES_EXPLICIT_REVIEW",
                    "action": "NO_SELECTION_NO_AVERAGING_NO_COLLAPSING",
                })

    observation_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in bundle.get("observations", []):
        if not isinstance(observation, dict):
            continue
        experiment_id = observation.get("experiment_id")
        target_id = observation.get("target_id")
        endpoint = observation.get("endpoint_definition")
        if all(isinstance(value, str) and value.strip()
               for value in (experiment_id, target_id, endpoint)):
            observation_groups[(experiment_id, target_id, endpoint)].append(observation)

    repeated_groups = 0
    groups_without_identity = 0
    groups_with_partial_identity = 0
    groups_with_explicit_identity = 0
    for (experiment_id, target_id, endpoint), records in sorted(observation_groups.items()):
        if len(records) < 2:
            continue
        repeated_groups += 1
        identity_flags = [_has_explicit_identity(record) for record in records]
        if not any(identity_flags):
            groups_without_identity += 1
            status = "REPEATED_OBSERVATIONS_WITHOUT_EXPLICIT_IDENTITY"
        elif not all(identity_flags):
            groups_with_partial_identity += 1
            status = "PARTIAL_EXPLICIT_IDENTITY_COVERAGE"
        else:
            groups_with_explicit_identity += 1
            status = "EXPLICIT_IDENTIFIERS_PRESENT_SEMANTICS_UNVERIFIED"
        warnings.append({
            "code": status,
            "experiment_id": experiment_id,
            "target_id": target_id,
            "endpoint_definition": endpoint,
            "observation_ids": sorted(record.get("observation_id", "") for record in records),
            "identity_fields_supplied": sorted({
                field for record in records for field in EXPLICIT_OBSERVATION_ID_FIELDS
                if _has_explicit_identity({field: record.get(field)})
            }),
            "interpretation": (
                "Observation grouping and statistical independence are unresolved; "
                "an explicit identifier is not proof of independent replication."
            ),
            "action": "PRESERVE_EACH_OBSERVATION_NO_AUTOMATIC_AGGREGATION_OR_REPLICATE_ASSIGNMENT",
        })

    return {
        "status": "PASS_WITH_REVIEW_WARNINGS" if warnings else "PASS",
        "warning_count": len(warnings),
        "warnings": warnings,
        "condition_grain": {
            "multiple_same_type_groups": multiple_condition_groups,
            "automatic_condition_selection": False,
            "automatic_condition_aggregation": False,
        },
        "observation_grain": {
            "repeated_experiment_target_endpoint_groups": repeated_groups,
            "groups_without_explicit_identity": groups_without_identity,
            "groups_with_partial_identity": groups_with_partial_identity,
            "groups_with_explicit_identity_but_unverified_semantics": groups_with_explicit_identity,
            "automatic_replicate_assignment": False,
            "automatic_observation_aggregation": False,
            "assumed_independence": False,
            "outer_validation_group": "Study",
        },
        "scope": "NON_DESTRUCTIVE_GRAIN_DIAGNOSTICS_NOT_EXPERIMENT_OR_REPLICATE_RECONSTRUCTION",
    }
