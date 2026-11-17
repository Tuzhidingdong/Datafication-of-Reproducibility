from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file


def validate_research_scope_record(
    record: Any,
    discovery_report: Any,
    modeling_task: Any,
    discovery_report_sha256: str,
) -> dict[str, Any]:
    """Validate a human-selected scope against exact exploratory signals and task identity."""
    errors: list[dict[str, str]] = []

    def issue(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    if not isinstance(record, dict):
        return {
            "valid": False,
            "errors": [{"code": "SCOPE_RECORD_NOT_OBJECT", "path": "$", "message": "Research scope record must be a JSON object."}],
            "selected_signal_ids": [],
            "discovery_report_sha256": discovery_report_sha256,
        }
    if record.get("schema_version") != "1.0":
        issue("UNSUPPORTED_SCOPE_SCHEMA_VERSION", "schema_version", "Research scope record schema_version must be 1.0.")
    if not isinstance(record.get("scope_id"), str) or not record["scope_id"].strip():
        issue("SCOPE_ID_REQUIRED", "scope_id", "scope_id must be a non-empty string.")
    if record.get("discovery_report_sha256") != discovery_report_sha256:
        issue("SCOPE_DISCOVERY_HASH_MISMATCH", "discovery_report_sha256", "Scope record must bind to the exact Discovery report SHA-256.")

    report_signals_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(discovery_report, dict):
        issue("DISCOVERY_REPORT_NOT_OBJECT", "$discovery_report", "Discovery report must be a JSON object.")
        report_signal_ids: list[str] = []
    else:
        signals = discovery_report.get("signals")
        if not isinstance(signals, list):
            issue("DISCOVERY_SIGNALS_NOT_ARRAY", "signals", "Discovery report signals must be an array.")
            signals = []
        report_signal_ids = []
        seen_report: set[str] = set()
        for index, signal in enumerate(signals):
            signal_id = signal.get("signal_id") if isinstance(signal, dict) else None
            if not isinstance(signal_id, str) or not signal_id.strip():
                issue("DISCOVERY_SIGNAL_ID_INVALID", f"signals[{index}].signal_id", "Every Discovery signal requires a non-empty signal_id.")
            elif signal_id in seen_report:
                issue("DISCOVERY_SIGNAL_ID_DUPLICATE", f"signals[{index}].signal_id", "Discovery report contains a duplicate signal_id.")
            else:
                seen_report.add(signal_id)
                report_signal_ids.append(signal_id)
                report_signals_by_id[signal_id] = signal

    def read_id_list(key: str) -> list[str]:
        value = record.get(key)
        if not isinstance(value, list):
            issue("SCOPE_SIGNAL_LIST_INVALID", key, f"{key} must be an array of signal IDs.")
            return []
        if any(not isinstance(item, str) or not item.strip() for item in value):
            issue("SCOPE_SIGNAL_ID_INVALID", key, f"{key} may contain only non-empty signal IDs.")
            return []
        if len(value) != len(set(value)):
            issue("SCOPE_SIGNAL_ID_DUPLICATE", key, f"{key} contains duplicate signal IDs.")
        return value

    selected = read_id_list("selected_signal_ids")
    excluded = read_id_list("not_selected_signal_ids")
    overlap = sorted(set(selected) & set(excluded))
    if overlap:
        issue("SCOPE_SIGNAL_PARTITION_OVERLAP", "selected_signal_ids", "Selected and not-selected signal IDs must be disjoint.")
    classified = set(selected) | set(excluded)
    expected = set(report_signal_ids)
    if classified != expected:
        missing = sorted(expected - classified)
        unknown = sorted(classified - expected)
        if missing:
            issue("SCOPE_SIGNAL_UNCLASSIFIED", "selected_signal_ids", "Every Discovery signal must be selected or explicitly not selected: " + ", ".join(missing))
        if unknown:
            issue("SCOPE_SIGNAL_UNKNOWN", "selected_signal_ids", "Scope record contains signal IDs absent from the bound Discovery report: " + ", ".join(unknown))
    if not selected:
        issue("SCOPE_HAS_NO_SELECTED_SIGNAL", "selected_signal_ids", "At least one Discovery signal must be selected before a formal analysis task can proceed.")

    if not isinstance(modeling_task, dict):
        issue("MODELING_TASK_NOT_OBJECT", "$modeling_task", "Modeling task must be a JSON object.")
    else:
        for field in ("task_id", "target_id"):
            task_value = modeling_task.get(field)
            if not isinstance(task_value, str) or not task_value.strip():
                issue("MODELING_TASK_IDENTITY_MISSING", field, f"Modeling task requires a non-empty {field}.")
            elif record.get(field) != task_value:
                issue("SCOPE_TASK_IDENTITY_MISMATCH", field, f"Scope record {field} must match the exact modeling task.")
        task_target = modeling_task.get("target_id")
        if isinstance(task_target, str) and task_target.strip():
            for selected_id in selected:
                selected_signal = report_signals_by_id.get(selected_id, {})
                signal_target = selected_signal.get("target_id")
                if isinstance(signal_target, str) and signal_target.strip() and signal_target != task_target:
                    issue(
                        "SCOPE_SELECTED_SIGNAL_TARGET_MISMATCH",
                        "selected_signal_ids",
                        f"Selected Discovery signal {selected_id} targets {signal_target}, but the modeling task targets {task_target}.",
                    )

    for field in ("scope_statement", "selection_rationale", "reviewed_by"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            issue("SCOPE_METADATA_REQUIRED", field, f"{field} must be a non-empty string.")
    reviewed_at = record.get("reviewed_at")
    if isinstance(reviewed_at, str) and reviewed_at.strip():
        try:
            parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone offset is required")
        except ValueError:
            issue("SCOPE_TIMESTAMP_INVALID", "reviewed_at", "reviewed_at must be an ISO-8601 timestamp with an explicit timezone.")
    else:
        issue("SCOPE_METADATA_REQUIRED", "reviewed_at", "reviewed_at must be a timezone-aware ISO-8601 timestamp.")
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item.strip() for item in limitations):
        issue("SCOPE_LIMITATIONS_INVALID", "limitations", "limitations must be an array of non-empty strings.")

    return {
        "valid": not errors,
        "error_count": len(errors),
        "errors": errors,
        "scope_id": record.get("scope_id"),
        "task_id": record.get("task_id"),
        "target_id": record.get("target_id"),
        "discovered_signal_count": len(report_signal_ids),
        "selected_signal_ids": sorted(set(selected)) if not errors else [],
        "selected_opportunity_ids": sorted(
            signal_id for signal_id in selected
            if str(report_signals_by_id.get(signal_id, {}).get("signal_type", "")).startswith("WITHIN_STUDY_SYSTEM_")
        ) if not errors else [],
        "selected_signal_count": len(selected),
        "not_selected_signal_count": len(excluded),
        "discovery_report_sha256": discovery_report_sha256,
        "validation_scope": "SCOPE_SIGNAL_PARTITION_AND_TASK_IDENTITY_PROVENANCE_ONLY_NOT_SCIENTIFIC_JUDGEMENT",
    }


def validate_research_scope_files(
    scope_path: Path,
    discovery_report_path: Path,
    modeling_task_path: Path,
) -> dict[str, Any]:
    with scope_path.open("r", encoding="utf-8-sig") as handle:
        record = json.load(handle)
    with discovery_report_path.open("r", encoding="utf-8-sig") as handle:
        report = json.load(handle)
    with modeling_task_path.open("r", encoding="utf-8-sig") as handle:
        task = json.load(handle)
    return validate_research_scope_record(record, report, task, sha256_file(discovery_report_path))
