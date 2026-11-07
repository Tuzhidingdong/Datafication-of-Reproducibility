"""Non-destructive diagnostics for canonical entity relationships and duplicates."""
from __future__ import annotations

import hashlib
import json
from typing import Any

ID_FIELDS = {
    "studies":"study_id", "systems":"system_id", "conditions":"condition_id",
    "experiments":"experiment_id", "observations":"observation_id",
    "comparisons":"comparison_id", "evidence":"evidence_id",
}
NON_SEMANTIC_FIELDS = {"field_provenance", "_provenance", "source_locators", "source_locator"}


def _fingerprint(record: dict[str, Any], id_field: str) -> str:
    payload = {key: value for key, value in record.items()
               if key != id_field and key not in NON_SEMANTIC_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def diagnose_canonical_bundle(bundle: Any) -> dict[str, Any]:
    """Report exact-payload duplicate candidates and unreferenced records; never merges or edits."""
    if not isinstance(bundle, dict):
        return {"valid_input": False, "errors": [{"code":"BUNDLE_NOT_OBJECT","message":"Bundle must be an object."}],
                "duplicate_candidates": [], "unreferenced": {}}
    duplicates = []
    for entity, id_field in ID_FIELDS.items():
        rows = bundle.get(entity, [])
        if not isinstance(rows, list):
            continue
        by_hash: dict[str, list[str]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get(id_field), str):
                continue
            fingerprint = _fingerprint(row, id_field)
            by_hash.setdefault(fingerprint, []).append(row[id_field])
        for fingerprint, identifiers in by_hash.items():
            if len(identifiers) > 1:
                duplicates.append({"entity_type":entity, "candidate_ids":sorted(identifiers),
                                   "payload_sha256":fingerprint,
                                   "status":"REVIEW_ONLY_NOT_MERGED"})

    def string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def ids(entity: str) -> dict[str, dict[str, Any]]:
        rows = bundle.get(entity, [])
        if not isinstance(rows, list):
            return {}
        id_field = ID_FIELDS[entity]
        return {row[id_field]: row for row in rows
                if isinstance(row, dict) and isinstance(row.get(id_field), str)}

    studies, systems, conditions = ids("studies"), ids("systems"), ids("conditions")
    experiments, observations, evidence = ids("experiments"), ids("observations"), ids("evidence")
    linked_studies = set()
    linked_systems = set()
    used_conditions = set()
    observed_experiments = set()
    cited_evidence = set()
    for row in systems.values():
        linked_studies.update(string_list(row.get("study_ids")))
    for row in evidence.values():
        value = row.get("study_id")
        if isinstance(value, str):
            linked_studies.add(value)
    for row in experiments.values():
        study_id, system_id = row.get("study_id"), row.get("system_id")
        if isinstance(study_id, str):
            linked_studies.add(study_id)
        if isinstance(system_id, str):
            linked_systems.add(system_id)
        used_conditions.update(string_list(row.get("condition_ids")))
    for row in conditions.values():
        linked_systems.update(string_list(row.get("system_ids")))
    for row in observations.values():
        experiment_id = row.get("experiment_id")
        if isinstance(experiment_id, str):
            observed_experiments.add(experiment_id)
        cited_evidence.update(string_list(row.get("evidence_ids")))

    unreferenced = {
        "studies_without_system_experiment_or_evidence_link": sorted(set(studies) - linked_studies),
        "systems_without_condition_or_experiment_use": sorted(set(systems) - linked_systems),
        "conditions_not_used_by_experiments": sorted(set(conditions) - used_conditions),
        "experiments_without_observations": sorted(set(experiments) - observed_experiments),
        "evidence_not_cited_by_observations": sorted(set(evidence) - cited_evidence),
    }
    counts = {key: len(value) for key, value in unreferenced.items()}
    return {
        "valid_input": True,
        "duplicate_candidate_count": len(duplicates),
        "duplicate_candidates": duplicates,
        "unreferenced": unreferenced,
        "unreferenced_counts": counts,
        "interpretation": "DIAGNOSTIC_ONLY_REVIEW_REQUIRED_NO_RECORDS_MERGED_OR_DELETED",
    }
