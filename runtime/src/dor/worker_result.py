"""Strict structural validation for bounded Worker result packets.

This module is shared by the Run Manager (before a Worker stage can be
recorded SUCCEEDED) and the human-promotion validator (before dispositions).
It validates packet shape and evidence references, not scientific truth.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def validate_worker_result_payload(
    result: Mapping[str, Any], allowed_input_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Validate the Worker Result contract and return findings indexed by ID."""
    required = {
        "schema_version", "task_id", "status", "summary", "findings",
        "artifacts", "warnings", "unresolved_questions",
    }
    allowed = required | {"recommended_next_action"}
    if not isinstance(result, Mapping) or set(result) - allowed or required - set(result):
        raise ValueError("Worker result has missing or unknown top-level properties.")
    if result.get("schema_version") != "1.0":
        raise ValueError("Worker result schema_version must be 1.0.")
    if not isinstance(result.get("task_id"), str) or not result["task_id"].strip():
        raise ValueError("Worker result task_id must be non-empty.")
    if not isinstance(result.get("status"), str) or result["status"] not in {"completed", "partial", "blocked", "failed"}:
        raise ValueError("Worker result status is invalid.")
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        raise ValueError("Worker result summary must be a non-empty string.")
    if "recommended_next_action" in result and not isinstance(result["recommended_next_action"], str):
        raise ValueError("Worker result recommended_next_action must be a string.")
    for name in ("warnings", "unresolved_questions"):
        if not isinstance(result.get(name), list) or any(not isinstance(x, str) for x in result[name]):
            raise ValueError("Worker result " + name + " must be an array of strings.")
    if not isinstance(result.get("artifacts"), list):
        raise ValueError("Worker result artifacts must be an array.")
    for artifact in result["artifacts"]:
        required_fields = {"path", "artifact_type"}
        allowed_fields = required_fields | {"sha256", "description", "source_record_ids"}
        if (not isinstance(artifact, dict) or not required_fields.issubset(artifact)
                or set(artifact) - allowed_fields):
            raise ValueError("Worker result artifact has an invalid property set.")
        if any(not isinstance(artifact.get(key), str) or not artifact[key].strip()
               for key in required_fields):
            raise ValueError("Worker result artifact path and artifact_type must be non-empty.")
        if "sha256" in artifact and (
            not isinstance(artifact["sha256"], str) or not _SHA256.fullmatch(artifact["sha256"])
        ):
            raise ValueError("Worker result artifact sha256 is invalid.")
        if "description" in artifact and not isinstance(artifact["description"], str):
            raise ValueError("Worker result artifact description must be a string.")
        if "source_record_ids" in artifact and (
            not isinstance(artifact["source_record_ids"], list)
            or any(not isinstance(x, str) for x in artifact["source_record_ids"])
        ):
            raise ValueError("Worker result source_record_ids must be an array of strings.")

    findings = result.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Worker result findings must be an array.")
    indexed: dict[str, dict[str, Any]] = {}
    for finding in findings:
        required_fields = {"finding_id", "summary", "supporting_artifact_ids", "evidence"}
        allowed_fields = required_fields | {"limitations"}
        if (not isinstance(finding, dict) or not required_fields.issubset(finding)
                or set(finding) - allowed_fields):
            raise ValueError("Every Worker finding requires finding_id, summary, supporting_artifact_ids, and evidence.")
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id.strip() or finding_id in indexed:
            raise ValueError("Worker finding IDs must be non-empty and unique.")
        if not isinstance(finding.get("summary"), str) or not finding["summary"].strip():
            raise ValueError("Worker finding summary must be non-empty.")
        supporting = finding.get("supporting_artifact_ids")
        if (not isinstance(supporting, list) or not supporting
                or any(not isinstance(x, str) or not x.strip() for x in supporting)
                or len(supporting) != len(set(supporting))):
            raise ValueError("Worker finding supporting_artifact_ids must be a non-empty unique string array.")
        if not set(supporting).issubset(allowed_input_ids):
            raise ValueError("Worker finding cites an artifact not supplied to the Worker.")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Worker finding evidence must contain exact locators.")
        evidence_ids: set[str] = set()
        for locator in evidence:
            if (not isinstance(locator, dict)
                    or not {"artifact_id", "locator"}.issubset(locator)
                    or set(locator) - {"artifact_id", "locator", "description"}):
                raise ValueError("Worker evidence locator has an invalid property set.")
            artifact_id = locator.get("artifact_id")
            if not isinstance(artifact_id, str) or artifact_id not in set(supporting):
                raise ValueError("Worker evidence locator must identify a supporting input artifact.")
            if not isinstance(locator.get("locator"), str) or not locator["locator"].strip():
                raise ValueError("Worker evidence locator must be a non-empty path or location.")
            if "description" in locator and not isinstance(locator["description"], str):
                raise ValueError("Worker evidence description must be a string.")
            evidence_ids.add(artifact_id)
        if evidence_ids != set(supporting):
            raise ValueError("Every supporting artifact must have at least one exact evidence locator.")
        limitations = finding.get("limitations", [])
        if not isinstance(limitations, list) or any(not isinstance(x, str) for x in limitations):
            raise ValueError("Worker finding limitations must be an array of strings.")
        indexed[finding_id] = dict(finding)
    return indexed
