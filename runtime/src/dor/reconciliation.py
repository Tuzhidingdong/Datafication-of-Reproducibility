"""Evidence-linked, non-destructive reconciliation for canonical research bundles."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.diagnostics import diagnose_canonical_bundle
from dor.mapping import sha256_file


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _issue_id(category: str, entity_refs: list[str], evidence_refs: list[str], context: dict[str, Any]) -> str:
    payload = _stable([category, sorted(entity_refs), sorted(evidence_refs), context])
    return "REC_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()


def _make_issue(category: str, severity: str, entity_type: str, entity_refs: list[str],
                evidence_refs: list[str], summary: str, review_question: str,
                context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    return {
        "issue_id": _issue_id(category, entity_refs, evidence_refs, context),
        "category": category,
        "severity": severity,
        "status": "OPEN",
        "entity_type": entity_type,
        "entity_refs": sorted(set(entity_refs)),
        "evidence_refs": sorted(set(evidence_refs)),
        "summary": summary,
        "review_question": review_question,
        "context": context,
    }


def _records(bundle: dict[str, Any], name: str, id_field: str) -> dict[str, dict[str, Any]]:
    rows = bundle.get(name, [])
    if not isinstance(rows, list):
        return {}
    return {row[id_field]: row for row in rows
            if isinstance(row, dict) and isinstance(row.get(id_field), str)}


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def reconcile_canonical_bundle(bundle: Any, bundle_sha256: str | None = None) -> dict[str, Any]:
    """Create a review queue. It never changes, merges, selects, or removes canonical records."""
    if not isinstance(bundle, dict):
        return {
            "schema_version": "1.0",
            "bundle_sha256": bundle_sha256,
            "valid_bundle": False,
            "validation_errors": [{"code": "BUNDLE_NOT_OBJECT", "path": "$", "message": "Bundle must be an object."}],
            "issue_count": 0,
            "issues": [],
            "decision_policy": "HUMAN_REVIEW_ONLY_NO_CANONICAL_DATA_MUTATION",
        }

    validation = validate_canonical_bundle(bundle)
    diagnostics = diagnose_canonical_bundle(bundle)
    studies = _records(bundle, "studies", "study_id")
    systems = _records(bundle, "systems", "system_id")
    conditions = _records(bundle, "conditions", "condition_id")
    experiments = _records(bundle, "experiments", "experiment_id")
    observations = _records(bundle, "observations", "observation_id")
    evidence = _records(bundle, "evidence", "evidence_id")
    issues: list[dict[str, Any]] = []

    # Carry structural/reference problems into the queue rather than silently repairing them.
    for error in validation.get("errors", []):
        issues.append(_make_issue(
            "CANONICAL_INTEGRITY_ERROR", "CRITICAL", "bundle", [],
            [], error.get("message", "Canonical integrity error."),
            "Repair the source mapping or explicit relationship declaration; do not patch the canonical bundle by guessing.",
            {"validation_error": error},
        ))

    # Candidate duplicates use exact canonical payloads after excluding generated IDs and provenance.
    for candidate in diagnostics.get("duplicate_candidates", []):
        issues.append(_make_issue(
            "POTENTIAL_DUPLICATE_ENTITY", "REVIEW_REQUIRED", candidate.get("entity_type", "unknown"),
            candidate.get("candidate_ids", []), [],
            "Records have identical non-provenance payloads; this is only a duplicate candidate.",
            "Are these the same source fact, separate replicates/specimens, or independently reported records?",
            {"payload_sha256": candidate.get("payload_sha256"), "action": "DO_NOT_MERGE_AUTOMATICALLY"},
        ))

    # Unreferenced entities are surfaced individually and remain valid entities until reviewed.
    unreferenced = diagnostics.get("unreferenced", {})
    unreferenced_entities = {
        "studies_without_system_experiment_or_evidence_link": ("studies", studies),
        "systems_without_condition_or_experiment_use": ("systems", systems),
        "conditions_not_used_by_experiments": ("conditions", conditions),
        "experiments_without_observations": ("experiments", experiments),
        "evidence_not_cited_by_observations": ("evidence", evidence),
    }
    for category, (entity_type, entity_records) in unreferenced_entities.items():
        for entity_id in unreferenced.get(category, []):
            evidence_refs = [entity_id] if entity_type == "evidence" else []
            issues.append(_make_issue(
                "UNREFERENCED_" + entity_type.upper(), "WARNING", entity_type, [entity_id],
                evidence_refs, f"{entity_type[:-1].capitalize() if entity_type.endswith('s') else entity_type.capitalize()} {entity_id} has no link in the audited relationship category.",
                "Is this entity intentionally standalone, is a relationship missing from the source, or is the explicit build specification incomplete?",
                {"diagnostic_category": category},
            ))

    # Missing endpoint definitions must be visible before outcomes can enter endpoint-specific cohorts.
    target_endpoints: dict[tuple[str, str], dict[str, list[str]]] = {}
    observation_context: dict[str, dict[str, Any]] = {}
    for observation_id, observation in observations.items():
        experiment_id = observation.get("experiment_id")
        target_id = observation.get("target_id")
        endpoint = observation.get("endpoint_definition")
        timepoint = observation.get("timepoint")
        endpoint_text = endpoint.strip() if isinstance(endpoint, str) else ""
        if not endpoint_text:
            issues.append(_make_issue(
                "ENDPOINT_DEFINITION_MISSING", "REVIEW_REQUIRED", "observations", [observation_id],
                _as_string_list(observation.get("evidence_ids")),
                "Observation has no explicit endpoint_definition.",
                "What precise endpoint, protocol, and operational definition produced this value? Do not infer endpoint equivalence from target_id or units.",
                {"experiment_id": experiment_id, "target_id": target_id, "timepoint": timepoint},
            ))
        if isinstance(experiment_id, str) and isinstance(target_id, str) and endpoint_text:
            target_endpoints.setdefault((experiment_id, target_id), {}).setdefault(endpoint_text, []).append(observation_id)
        observation_context[observation_id] = {
            "experiment_id": experiment_id,
            "target_id": target_id,
            "endpoint_definition": endpoint_text or None,
            "timepoint": timepoint,
            "replicate_id": observation.get("replicate_id"),
            "sample_id": observation.get("sample_id"),
        }

    # Same target label with multiple explicit endpoint definitions: keep endpoints distinct.
    for (experiment_id, target_id), endpoint_map in target_endpoints.items():
        if len(endpoint_map) > 1:
            refs = [item for ids in endpoint_map.values() for item in ids]
            evidence_refs = [ev for oid in refs for ev in _as_string_list(observations[oid].get("evidence_ids"))]
            issues.append(_make_issue(
                "ENDPOINT_DEFINITION_VARIANTS", "WARNING", "observations", refs, evidence_refs,
                "The same target_id occurs with multiple explicit endpoint definitions in one experiment.",
                "Confirm that these are intentionally distinct endpoints and preserve separate target/cohort definitions; do not combine by label or unit.",
                {"experiment_id": experiment_id, "target_id": target_id,
                 "endpoint_definitions": sorted(endpoint_map)},
            ))

    # Compare observation values only within an explicit endpoint/timepoint identity.
    observation_groups: dict[tuple[Any, ...], list[str]] = {}
    for observation_id, observation in observations.items():
        endpoint = observation.get("endpoint_definition")
        if not isinstance(endpoint, str) or not endpoint.strip():
            continue
        if observation.get("value_state") != "REPORTED":
            continue
        key = (
            observation.get("experiment_id"),
            observation.get("target_id"),
            endpoint.strip(),
            _stable(observation.get("timepoint")),
            _stable(observation.get("replicate_id")) if observation.get("replicate_id") is not None else None,
            _stable(observation.get("sample_id")) if observation.get("sample_id") is not None else None,
        )
        observation_groups.setdefault(key, []).append(observation_id)

    for key, ids in observation_groups.items():
        if len(ids) < 2:
            continue
        value_signatures = {
            _stable({
                "raw_value": observations[oid].get("raw_value"),
                "raw_unit": observations[oid].get("raw_unit"),
                "normalized_value": observations[oid].get("normalized_value"),
                "normalized_unit": observations[oid].get("normalized_unit"),
                "value_state": observations[oid].get("value_state"),
            })
            for oid in ids
        }
        if len(value_signatures) < 2:
            continue
        explicit_replicate = key[4] is not None or key[5] is not None
        category = "VALUE_CONFLICT_SAME_REPLICATE_OR_SAMPLE" if explicit_replicate else "OBSERVATION_VARIATION_GRAIN_UNRESOLVED"
        severity = "REVIEW_REQUIRED" if explicit_replicate else "WARNING"
        evidence_refs = [ev for oid in ids for ev in _as_string_list(observations[oid].get("evidence_ids"))]
        issues.append(_make_issue(
            category, severity, "observations", ids, evidence_refs,
            "Reported values differ for observations sharing the same experiment, target, endpoint, and timepoint.",
            "Do these records represent conflicting extraction, repeated measurements, distinct replicates, or a source-level correction? Resolve only with explicit sample/replicate and evidence review.",
            {"experiment_id": key[0], "target_id": key[1], "endpoint_definition": key[2],
             "timepoint": observations[ids[0]].get("timepoint"),
             "replicate_id": observations[ids[0]].get("replicate_id"),
             "sample_id": observations[ids[0]].get("sample_id"),
             "value_signatures": sorted(value_signatures)},
        ))

    # Two evidence entries at one exact source locator can disagree in extraction.
    evidence_by_locator: dict[tuple[str, str, str, str, str], list[str]] = {}
    for evidence_id, item in evidence.items():
        locator = item.get("source_locator")
        if not isinstance(locator, dict):
            continue
        key = (
            str(item.get("study_id", "")),
            str(locator.get("source_file", "")),
            str(locator.get("source_sha256", "")),
            str(locator.get("locator_type", "")),
            str(locator.get("locator", "")),
        )
        evidence_by_locator.setdefault(key, []).append(evidence_id)
        extraction_status = item.get("extraction_status")
        if isinstance(extraction_status, str) and extraction_status in {"REVIEW_REQUIRED", "CONFLICTING", "UNVERIFIED"}:
            linked_observations = [
                oid for oid, observation in observations.items()
                if evidence_id in _as_string_list(observation.get("evidence_ids"))
            ]
            issues.append(_make_issue(
                "EVIDENCE_VERIFICATION_REQUIRED", "REVIEW_REQUIRED", "evidence", [evidence_id],
                [evidence_id], "Evidence extraction status is " + str(item.get("extraction_status")) + ".",
                "Verify this source passage/table/figure locator and reconcile the extracted statement against the original source.",
                {"extraction_status": item.get("extraction_status"),
                 "linked_observation_ids": sorted(linked_observations)},
            ))

    for locator_key, evidence_ids in evidence_by_locator.items():
        if len(evidence_ids) < 2:
            continue
        signatures = {
            _stable({
                "evidence_type": evidence[item].get("evidence_type"),
                "quoted_text": evidence[item].get("quoted_text"),
                "extraction_status": evidence[item].get("extraction_status"),
            })
            for item in evidence_ids
        }
        category = "EVIDENCE_EXTRACTION_DISAGREEMENT" if len(signatures) > 1 else "DUPLICATE_EVIDENCE_LOCATOR"
        issues.append(_make_issue(
            category, "REVIEW_REQUIRED", "evidence", evidence_ids, evidence_ids,
            "Multiple evidence records point to the same exact source locator.",
            "Compare the original source locator and retain both extraction records until their provenance and interpretation are reviewed.",
            {"source_locator": {
                "study_id": locator_key[0], "source_file": locator_key[1],
                "source_sha256": locator_key[2], "locator_type": locator_key[3],
                "locator": locator_key[4]},
             "extraction_signatures": sorted(signatures)},
        ))

    # Explicitly ambiguous/conflicting value states are not silently promoted.
    for entity_type, records, id_field in (
        ("conditions", conditions, "condition_id"),
        ("observations", observations, "observation_id"),
    ):
        for entity_id, record in records.items():
            state = record.get("value_state")
            if isinstance(state, str) and state in {"AMBIGUOUS", "CONFLICTING"}:
                evidence_refs = _as_string_list(record.get("evidence_ids"))
                issues.append(_make_issue(
                    "SOURCE_VALUE_STATE_" + str(state), "REVIEW_REQUIRED", entity_type,
                    [entity_id], evidence_refs,
                    f"{entity_type[:-1].capitalize()} is explicitly marked {state}.",
                    "Review the underlying evidence and preserve the unresolved state until a documented decision is made.",
                    {"value_state": state},
                ))

    # Deterministic ordering and de-duplication by stable issue ID.
    unique = {item["issue_id"]: item for item in issues}
    ordered = sorted(unique.values(), key=lambda item: (item["severity"], item["category"], item["issue_id"]))
    severity_counts = {name: sum(item["severity"] == name for item in ordered)
                       for name in ("CRITICAL", "REVIEW_REQUIRED", "WARNING", "INFO")}
    return {
        "schema_version": "1.0",
        "bundle_sha256": bundle_sha256,
        "valid_bundle": bool(validation.get("valid")),
        "validation_error_count": validation.get("error_count", 0),
        "validation_warning_count": validation.get("warning_count", 0),
        "issue_count": len(ordered),
        "severity_counts": severity_counts,
        "issues": ordered,
        "decision_policy": "HUMAN_REVIEW_ONLY_NO_CANONICAL_DATA_MUTATION",
        "validation_scope": "DETERMINISTIC_CANDIDATE_DETECTION_NOT_SCIENTIFIC_RECONCILIATION",
    }


def reconcile_bundle_file(bundle_path: Path, output_dir: Path) -> dict[str, Any]:
    bundle_hash = sha256_file(bundle_path)
    with bundle_path.open("r", encoding="utf-8-sig") as handle:
        bundle = json.load(handle)
    if sha256_file(bundle_path) != bundle_hash:
        raise ValueError("Canonical bundle changed while being reconciled.")
    report = reconcile_canonical_bundle(bundle, bundle_hash)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Output path exists and is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise FileExistsError(f"Refusing to overwrite non-empty reconciliation output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "reconciliation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    queue_path = output_dir / "reconciliation_review_queue.csv"
    fields = ["issue_id", "category", "severity", "status", "entity_type", "entity_refs",
              "evidence_refs", "summary", "review_question", "context"]
    with queue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for issue in report["issues"]:
            writer.writerow({**issue,
                "entity_refs": json.dumps(issue["entity_refs"], ensure_ascii=False),
                "evidence_refs": json.dumps(issue["evidence_refs"], ensure_ascii=False),
                "context": json.dumps(issue["context"], ensure_ascii=False, sort_keys=True)})
    return {"report": report, "report_path": str(report_path), "queue_path": str(queue_path)}


def validate_reconciliation_decisions(decisions: Any, report: Any, bundle: Any,
                                       report_sha256: str, bundle_sha256: str | None = None) -> dict[str, Any]:
    """Validate human decision records without applying them to the canonical bundle."""
    errors: list[dict[str, str]] = []
    if not isinstance(decisions, dict):
        return {"valid": False, "errors": [{"code":"DECISIONS_NOT_OBJECT","path":"$","message":"Decision file must be an object."}],
                "validated_decision_ids": [], "decision_policy":"DECISIONS_ARE_REVIEW_METADATA_ONLY"}
    if decisions.get("schema_version") != "1.0":
        errors.append({
            "code": "UNSUPPORTED_DECISIONS_SCHEMA_VERSION",
            "path": "schema_version",
            "message": "Decision file schema_version must be 1.0.",
        })
    report_is_object = isinstance(report, dict)
    if not report_is_object or decisions.get("reconciliation_report_sha256") != report_sha256:
        errors.append({"code":"STALE_RECONCILIATION_REPORT","path":"reconciliation_report_sha256","message":"Decisions must bind to the exact reconciliation report file hash."})
    if not report_is_object:
        errors.append({
            "code": "RECONCILIATION_REPORT_NOT_OBJECT",
            "path": "$",
            "message": "The reconciliation report must be a JSON object.",
        })
    else:
        required_report_fields = {
            "schema_version", "bundle_sha256", "valid_bundle", "issue_count",
            "issues", "decision_policy", "validation_scope",
        }
        missing_report_fields = sorted(required_report_fields - set(report))
        for field in missing_report_fields:
            errors.append({
                "code": "RECONCILIATION_REPORT_FIELD_MISSING",
                "path": field,
                "message": f"The reconciliation report is missing required field {field}.",
            })
        if report.get("schema_version") != "1.0":
            errors.append({
                "code": "UNSUPPORTED_RECONCILIATION_REPORT_SCHEMA",
                "path": "schema_version",
                "message": "The reconciliation report schema_version must be 1.0.",
            })
        if report.get("valid_bundle") is not True:
            errors.append({
                "code": "RECONCILIATION_BUNDLE_INVALID",
                "path": "valid_bundle",
                "message": "A reconciliation decision record can only be accepted for a valid Canonical Bundle.",
            })
        if report.get("decision_policy") != "HUMAN_REVIEW_ONLY_NO_CANONICAL_DATA_MUTATION":
            errors.append({
                "code": "UNSUPPORTED_RECONCILIATION_DECISION_POLICY",
                "path": "decision_policy",
                "message": "The reconciliation report must preserve the non-destructive human-review policy.",
            })
        if report.get("validation_scope") != "DETERMINISTIC_CANDIDATE_DETECTION_NOT_SCIENTIFIC_RECONCILIATION":
            errors.append({
                "code": "UNSUPPORTED_RECONCILIATION_VALIDATION_SCOPE",
                "path": "validation_scope",
                "message": "The reconciliation report must declare its deterministic candidate-detection scope.",
            })
    if not isinstance(bundle, dict) or not report_is_object or report.get("bundle_sha256") is None:
        errors.append({"code":"MISSING_BUNDLE_PROVENANCE","path":"bundle_sha256","message":"The reconciliation report must reference a bundle hash."})
    elif bundle_sha256 is None or report.get("bundle_sha256") != bundle_sha256:
        errors.append({"code":"STALE_CANONICAL_BUNDLE","path":"bundle_sha256","message":"The canonical bundle must match the exact bundle hash used by the reconciliation report."})
    issues = report.get("issues") if isinstance(report, dict) else None
    if not isinstance(issues, list):
        errors.append({
            "code": "REPORT_ISSUES_NOT_ARRAY",
            "path": "issues",
            "message": "The reconciliation report issues field must be an array.",
        })
        issues = []
    issue_count = report.get("issue_count") if isinstance(report, dict) else None
    if (not isinstance(issue_count, int) or isinstance(issue_count, bool)
            or issue_count != len(issues)):
        errors.append({
            "code": "RECONCILIATION_ISSUE_COUNT_MISMATCH",
            "path": "issue_count",
            "message": "issue_count must equal the number of entries in the issues array.",
        })
    issue_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(issues):
        issue_id = item.get("issue_id") if isinstance(item, dict) else None
        if not isinstance(issue_id, str) or not issue_id.strip():
            errors.append({
                "code": "INVALID_RECONCILIATION_ISSUE_ID",
                "path": f"issues[{index}].issue_id",
                "message": "Every reconciliation report issue requires a non-empty issue_id.",
            })
        elif issue_id in issue_by_id:
            errors.append({
                "code": "DUPLICATE_RECONCILIATION_ISSUE_ID",
                "path": f"issues[{index}].issue_id",
                "message": "The reconciliation report contains a duplicate issue_id.",
            })
        else:
            issue_by_id[issue_id] = item
    evidence_ids = set(_records(bundle, "evidence", "evidence_id")) if isinstance(bundle, dict) else set()
    decision_rows = decisions.get("decisions")
    if not isinstance(decision_rows, list):
        errors.append({"code":"DECISIONS_NOT_ARRAY","path":"decisions","message":"decisions must be an array."})
        decision_rows = []
    seen: set[str] = set()
    valid_ids = []
    allowed = {"CONFIRMED_DISTINCT", "CONFIRMED_CONFLICT", "RESOLVED_WITH_EVIDENCE",
               "EXCLUDE_FROM_ANALYSIS", "REMAINS_UNRESOLVED"}
    for index, decision in enumerate(decision_rows):
        path = f"decisions[{index}]"
        if not isinstance(decision, dict):
            errors.append({"code":"DECISION_NOT_OBJECT","path":path,"message":"Decision must be an object."})
            continue
        issue_id = decision.get("issue_id")
        if not isinstance(issue_id, str) or issue_id not in issue_by_id:
            errors.append({"code":"UNKNOWN_RECONCILIATION_ISSUE","path":f"{path}.issue_id","message":"issue_id is not present in the referenced reconciliation report."})
            continue
        if issue_id in seen:
            errors.append({"code":"DUPLICATE_ISSUE_DECISION","path":f"{path}.issue_id","message":"An issue may have at most one decision in this decision file."})
        seen.add(issue_id)
        if not isinstance(decision.get("decision"), str) or decision.get("decision") not in allowed:
            errors.append({"code":"INVALID_RECONCILIATION_DECISION","path":f"{path}.decision","message":"Unsupported decision value."})
        for field in ("reviewer", "reviewed_at", "rationale"):
            if not isinstance(decision.get(field), str) or not decision[field].strip():
                errors.append({"code":"DECISION_METADATA_REQUIRED","path":f"{path}.{field}","message":f"{field} must be a non-empty string."})
        reviewed_at = decision.get("reviewed_at")
        if isinstance(reviewed_at, str) and reviewed_at.strip():
            try:
                timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError("timezone offset is required")
            except ValueError:
                errors.append({
                    "code": "INVALID_DECISION_TIMESTAMP",
                    "path": f"{path}.reviewed_at",
                    "message": "reviewed_at must be an ISO-8601 timestamp with an explicit timezone.",
                })
        refs = decision.get("evidence_refs", [])
        if (not isinstance(refs, list)
                or any(not isinstance(ref, str) or ref not in evidence_ids for ref in refs)
                or len(refs) != len(set(refs))):
            errors.append({"code":"INVALID_DECISION_EVIDENCE","path":f"{path}.evidence_refs","message":"evidence_refs must contain unique evidence IDs present in the canonical bundle."})
        if decision.get("decision") == "RESOLVED_WITH_EVIDENCE" and not refs:
            errors.append({"code":"RESOLUTION_EVIDENCE_REQUIRED","path":f"{path}.evidence_refs","message":"RESOLVED_WITH_EVIDENCE requires at least one canonical evidence ID."})
        issue = issue_by_id[issue_id]
        if (issue.get("severity") in {"CRITICAL", "REVIEW_REQUIRED"}
                and decision.get("decision") == "REMAINS_UNRESOLVED"):
            errors.append({
                "code": "BLOCKING_RECONCILIATION_ISSUE_UNRESOLVED",
                "path": f"{path}.decision",
                "message": (
                    f"Issue {issue_id} has severity {issue.get('severity')} and cannot remain unresolved "
                    "when the reconciliation decision packet is submitted for G2."
                ),
            })
        valid_ids.append(issue_id)
    missing_issue_ids = sorted(set(issue_by_id) - seen)
    for issue_id in missing_issue_ids:
        errors.append({
            "code": "RECONCILIATION_ISSUE_NOT_REVIEWED",
            "path": "decisions",
            "message": f"Reconciliation issue {issue_id} has no explicit human decision.",
        })
    return {
        "valid": not errors,
        "error_count": len(errors),
        "errors": errors,
        "validated_decision_ids": sorted(set(valid_ids)) if not errors else [],
        "decision_count": len(decision_rows),
        "decision_policy": "VALIDATED_REVIEW_METADATA_ONLY_DO_NOT_MUTATE_CANONICAL_DATA",
        "validation_scope": "DECISION_SCHEMA_REFERENCE_AND_PROVENANCE_CHECKS_NOT_SCIENTIFIC_ADJUDICATION",
    }


def validate_reconciliation_decisions_files(decisions_path: Path, report_path: Path,
                                             bundle_path: Path) -> dict[str, Any]:
    with decisions_path.open("r", encoding="utf-8-sig") as handle:
        decisions = json.load(handle)
    with report_path.open("r", encoding="utf-8-sig") as handle:
        report = json.load(handle)
    with bundle_path.open("r", encoding="utf-8-sig") as handle:
        bundle = json.load(handle)
    return validate_reconciliation_decisions(decisions, report, bundle, sha256_file(report_path), sha256_file(bundle_path))
