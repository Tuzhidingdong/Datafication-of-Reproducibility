"""Append-only revision history for V1.0 scientific acceptance records.

The ledger is a tamper-evident review history, not an identity/authentication
system. Immutable JSON snapshots are chained by SHA-256 and each ledger event
binds one exact snapshot. A changed stage invalidates every later stage and the
final assessment; a new decision must be explicitly recorded afterwards.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from dor.gates import _exclusive_lock, _load_events, sha256_file

GENESIS_HASH = "0" * 64
STAGE_ORDER = (
    "source_selection", "source_integrity", "extraction_review",
    "semantic_mapping", "canonical_reconciliation", "cohort_feasibility",
    "modeling_validation", "publication_handoff",
)
TERMINAL_STAGE_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
GATE_ORDER = ("G0", "G1", "G2", "G3", "G4")
EXTERNAL_LEDGER_FIELDS = ("workflow_gate_ledger", "run_event_ledger")
REVIEW_FIELDS = ("reviewed_by", "reviewed_at", "review_rationale")
IMMUTABLE_RECORD_FIELDS = (
    "schema_version", "acceptance_id", "project_id", "scope", "run_id",
    "run_manifest_sha256", "source_snapshot",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event_hash(payload: Mapping[str, Any]) -> str:
    return _hash_bytes(_canonical_json(dict(payload)).encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone.")


def _record_bytes(record_path: Path) -> bytes:
    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError("Acceptance record must be a regular, non-symlink file.")
    raw = record_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Acceptance record must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Acceptance record must be a JSON object.")
    return raw


def _record_object(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Acceptance record must be a JSON object.")
    return value


def _snapshot_dir(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".revisions")


def _safe_paths(ledger_path: Path) -> tuple[Path, Path]:
    supplied = ledger_path.expanduser()
    if supplied.is_symlink():
        raise ValueError("Acceptance ledger must not be a symlink.")
    ledger_path = supplied.resolve(strict=False)
    snapshots = _snapshot_dir(ledger_path)
    if snapshots.is_symlink():
        raise ValueError("Acceptance revision directory must not be a symlink.")
    return ledger_path, snapshots


def _load_history(ledger_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ledger_path, snapshots_dir = _safe_paths(ledger_path)
    if not ledger_path.is_file():
        raise ValueError("Acceptance revision ledger is missing.")
    if not snapshots_dir.is_dir():
        raise ValueError("Acceptance revision snapshot directory is missing.")
    events: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    previous_event_hash = GENESIS_HASH
    previous_record_hash: str | None = None
    previous_record: dict[str, Any] | None = None

    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank line in acceptance ledger at line {line_number}.")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid acceptance ledger JSON at line {line_number}: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Acceptance event at line {line_number} must be a JSON object.")
            if event.get("schema_version") != "1.0":
                raise ValueError(f"Unsupported acceptance event schema at line {line_number}.")
            if event.get("event_type") not in {"RECORD_CREATED", "STAGE_REVIEW_RECORDED", "FINAL_DECISION_RECORDED", "UPSTREAM_LEDGER_RECORDED"}:
                raise ValueError(f"Unknown acceptance event type at line {line_number}.")
            supplied_hash = event.get("event_hash")
            payload = {key: value for key, value in event.items() if key != "event_hash"}
            if not isinstance(supplied_hash, str) or supplied_hash != _event_hash(payload):
                raise ValueError(f"Acceptance event hash mismatch at line {line_number}.")
            if type(event.get("sequence")) is not int or event["sequence"] != line_number:
                raise ValueError(f"Acceptance ledger sequence mismatch at line {line_number}.")
            if event.get("previous_event_hash") != previous_event_hash:
                raise ValueError(f"Acceptance ledger hash-chain mismatch at line {line_number}.")
            if event.get("snapshot_file") != f"revision-{line_number:06d}.json":
                raise ValueError(f"Acceptance snapshot name mismatch at line {line_number}.")
            if event.get("previous_record_sha256") != previous_record_hash:
                raise ValueError(f"Acceptance record revision chain mismatch at line {line_number}.")
            if not all(isinstance(event.get(key), str) and event[key].strip()
                       for key in ("acceptance_id", "project_id", "run_id", "actor",
                                   "rationale", "recorded_at", "record_sha256",
                                   "precommit_record_sha256")):
                raise ValueError(f"Acceptance event at line {line_number} lacks required metadata.")
            if not isinstance(event.get("changed_gate_ids"), list):
                raise ValueError(f"Acceptance event changed_gate_ids must be an array at line {line_number}.")
            if (not isinstance(event.get("changed_ledger_ids"), list)
                    or any(key not in EXTERNAL_LEDGER_FIELDS for key in event["changed_ledger_ids"])
                    or len(set(event["changed_ledger_ids"])) != len(event["changed_ledger_ids"])):
                raise ValueError(f"Acceptance event changed_ledger_ids is invalid at line {line_number}.")

            if any(gate not in GATE_ORDER for gate in event["changed_gate_ids"]) or len(set(event["changed_gate_ids"])) != len(event["changed_gate_ids"]):
                raise ValueError(f"Acceptance event changed_gate_ids contains an unknown or duplicate gate at line {line_number}.")
            _parse_timestamp(event["recorded_at"], f"event {line_number} recorded_at")
            digest = event["record_sha256"]
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"Invalid record SHA-256 at line {line_number}.")
            precommit_digest = event["precommit_record_sha256"]
            if len(precommit_digest) != 64 or any(char not in "0123456789abcdef" for char in precommit_digest):
                raise ValueError(f"Invalid precommit record SHA-256 at line {line_number}.")
            snapshot_path = snapshots_dir / event["snapshot_file"]
            if snapshot_path.is_symlink() or not snapshot_path.is_file():
                raise ValueError(f"Acceptance revision snapshot is missing or unsafe at line {line_number}.")
            if _hash_file(snapshot_path) != digest:
                raise ValueError(f"Acceptance revision snapshot hash mismatch at line {line_number}.")
            snapshot = _record_object(snapshot_path.read_bytes())
            if any(snapshot.get(key) != event.get(event_key) for key, event_key in (
                ("acceptance_id", "acceptance_id"), ("project_id", "project_id"),
                ("run_id", "run_id"),
            )):
                raise ValueError(f"Acceptance snapshot identity mismatch at line {line_number}.")
            statuses = {
                item.get("stage_id"): item.get("status")
                for item in snapshot.get("stages", []) if isinstance(item, dict)
            }
            if event.get("stage_statuses") != statuses:
                raise ValueError(f"Acceptance stage status summary mismatch at line {line_number}.")
            snapshot_assessment = snapshot.get("final_assessment")
            snapshot_decision = snapshot_assessment.get("decision") if isinstance(snapshot_assessment, dict) else None
            if event.get("final_decision") != snapshot_decision:
                raise ValueError(f"Acceptance final decision summary mismatch at line {line_number}.")

            if line_number == 1:
                if event.get("event_type") != "RECORD_CREATED":
                    raise ValueError("First acceptance event must be RECORD_CREATED.")
                if (event.get("changed_stage_ids") != [] or event.get("invalidated_stage_ids") != []
                        or event.get("changed_gate_ids") != [] or event.get("changed_ledger_ids") != []):
                    raise ValueError("Initial acceptance event cannot claim revised stages or gates.")
                if previous_record is not None:
                    raise ValueError("Invalid initial acceptance history.")
            else:
                if previous_record is None:
                    raise ValueError("Acceptance history has no preceding snapshot.")
                for field in IMMUTABLE_RECORD_FIELDS:
                    if snapshot.get(field) != previous_record.get(field):
                        raise ValueError(f"Acceptance identity/source field {field} changed; create a new Acceptance Record.")
                raw_changed = _changed_stage_ids(previous_record, snapshot)
                changed_ledger_ids = _changed_external_ledger_ids(previous_record, snapshot)
                previous_gate_binding = previous_record.get("workflow_gate_ledger")
                current_gate_binding = snapshot.get("workflow_gate_ledger")
                expected_changed_gates = _changed_gate_ids(previous_gate_binding, current_gate_binding)
                previous_assessment = previous_record.get("final_assessment")
                current_assessment = snapshot.get("final_assessment")
                assessment_changed = previous_assessment != current_assessment
                if changed_ledger_ids and any(previous_record.get(key) is not None for key in EXTERNAL_LEDGER_FIELDS):
                    _ensure_only_fields_changed(
                        previous_record, snapshot, {*EXTERNAL_LEDGER_FIELDS, "stages", "final_assessment"},
                        f"Acceptance gate-binding revision {line_number}",
                    )
                    if event.get("event_type") != "UPSTREAM_LEDGER_RECORDED":
                        raise ValueError(f"Upstream ledger changes must be UPSTREAM_LEDGER_RECORDED at line {line_number}.")
                    if event.get("changed_ledger_ids") != changed_ledger_ids:
                        raise ValueError(f"Acceptance changed_ledger_ids mismatch at line {line_number}.")
                    if event.get("changed_gate_ids") != expected_changed_gates:
                        raise ValueError(f"Acceptance changed_gate_ids mismatch at line {line_number}.")
                    if event.get("changed_stage_ids") != [] or event.get("invalidated_stage_ids") != list(STAGE_ORDER):
                        raise ValueError(f"Gate binding revision must invalidate every Acceptance stage at line {line_number}.")
                    for binding_key in EXTERNAL_LEDGER_FIELDS:
                        if previous_record.get(binding_key) is not None and not isinstance(snapshot.get(binding_key), dict):
                            raise ValueError(f"Upstream ledger revision removed {binding_key} at line {line_number}.")
                    _validate_downstream_reset(snapshot, list(STAGE_ORDER))
                    if current_assessment != _invalidated_assessment(line_number, "upstream ledger"):
                        raise ValueError(f"Final assessment was not invalidated after gate binding revision at line {line_number}.")
                elif raw_changed:
                    _ensure_only_fields_changed(
                        previous_record, snapshot, {"stages", "final_assessment"},
                        f"Acceptance revision {line_number}",
                    )
                    if event.get("event_type") != "STAGE_REVIEW_RECORDED":
                        raise ValueError(f"Stage changes must be recorded as STAGE_REVIEW_RECORDED at line {line_number}.")
                    if event.get("changed_gate_ids") != [] or event.get("changed_ledger_ids") != []:
                        raise ValueError(f"Stage review must not change upstream ledgers at line {line_number}.")
                    revised_stage_ids = [raw_changed[0]]
                    if event.get("changed_stage_ids") != revised_stage_ids:
                        raise ValueError(f"Acceptance changed_stage_ids mismatch at line {line_number}.")
                    earliest = STAGE_ORDER.index(raw_changed[0])
                    expected_invalidated = list(STAGE_ORDER[earliest + 1:])
                    if event.get("invalidated_stage_ids") != expected_invalidated:
                        raise ValueError(f"Acceptance downstream invalidation list mismatch at line {line_number}.")
                    _validate_changed_stage_reviews(previous_record, snapshot, revised_stage_ids)
                    _validate_downstream_reset(snapshot, expected_invalidated)
                    if current_assessment != _invalidated_assessment(line_number, raw_changed[0]):
                        raise ValueError(f"Final assessment was not invalidated after stage revision at line {line_number}.")
                else:
                    _ensure_only_fields_changed(
                        previous_record, snapshot,
                        {"final_assessment", *EXTERNAL_LEDGER_FIELDS} if changed_ledger_ids else {"final_assessment"},
                        f"Acceptance revision {line_number}",
                    )
                    if not assessment_changed or event.get("event_type") != "FINAL_DECISION_RECORDED":
                        raise ValueError(f"Acceptance revision {line_number} contains no valid stage or final-decision change.")
                    if event.get("changed_stage_ids") != [] or event.get("invalidated_stage_ids") != []:
                        raise ValueError(f"Final-decision event must not list revised stages at line {line_number}.")
                    expected_initial_bindings = (
                        changed_ledger_ids if changed_ledger_ids
                        and all(previous_record.get(key) is None for key in EXTERNAL_LEDGER_FIELDS)
                        else []
                    )
                    if event.get("changed_gate_ids") != [] or event.get("changed_ledger_ids") != expected_initial_bindings:
                        raise ValueError(f"Final-decision event has an invalid initial upstream-ledger capture at line {line_number}.")
                    _validate_final_decision_review(current_assessment)
                    previous_meta = tuple(previous_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(previous_assessment, dict) else ()
                    current_meta = tuple(current_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(current_assessment, dict) else ()
                    if current_meta == previous_meta:
                        raise ValueError(f"Final decision revision lacks fresh reviewer metadata at line {line_number}.")
            events.append(event)
            snapshots.append(snapshot)
            previous_event_hash = supplied_hash
            previous_record_hash = digest
            previous_record = snapshot

    if not events:
        raise ValueError("Acceptance ledger is empty.")
    expected_snapshot_names = {f"revision-{index:06d}.json" for index in range(1, len(events) + 1)}
    actual_snapshot_names = {item.name for item in snapshots_dir.iterdir()}
    if actual_snapshot_names != expected_snapshot_names:
        unexpected = sorted(actual_snapshot_names - expected_snapshot_names)
        missing = sorted(expected_snapshot_names - actual_snapshot_names)
        raise ValueError(
            f"Acceptance revision directory does not exactly match ledger references "
            f"(unreferenced={unexpected}, missing={missing})."
        )
    return events, snapshots



def _changed_external_ledger_ids(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    return [key for key in EXTERNAL_LEDGER_FIELDS if previous.get(key) != current.get(key)]


def _validate_run_event_ledger_binding(binding: Mapping[str, Any], record_parent: Path,
                                       run_id: str, previous: Mapping[str, Any] | None = None) -> None:
    from dor.run_manager import _load_events as _load_run_events
    path_value = binding.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("Run event ledger path is missing from its Acceptance binding.")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = record_parent / path
    if path.is_symlink():
        raise ValueError("Run event ledger path must not be a symlink.")
    path = path.resolve(strict=True)
    if not path.is_file() or sha256_file(path) != binding.get("sha256"):
        raise ValueError("Run event ledger file does not match its Acceptance SHA-256 binding.")
    events = _load_run_events(path, run_id)
    actual_tip = events[-1]["event_hash"] if events else None
    if (type(binding.get("event_count")) is not int or binding["event_count"] != len(events)
            or binding.get("last_event_hash") != actual_tip):
        raise ValueError("Run event ledger binding does not match its current append-only tip.")
    if previous is not None:
        previous_tip = previous.get("last_event_hash")
        previous_count = previous.get("event_count")
        previous_path = Path(previous.get("path", "")).expanduser()
        if not previous_path.is_absolute():
            previous_path = record_parent / previous_path
        if previous_path.resolve(strict=False) != path:
            raise ValueError("Run event ledger path cannot be replaced during an Acceptance revision.")
        if type(previous_count) is not int or previous_count < 0 or previous_count > len(events):
            raise ValueError("Run event ledger event count moved backwards or is malformed.")
        expected_prior_tip = events[previous_count - 1]["event_hash"] if previous_count else None
        if previous_tip != expected_prior_tip:
            raise ValueError("Run event ledger history rolled back or replaced the prior event tip.")

def _changed_gate_ids(previous: Any, current: Any) -> list[str]:
    if previous is None and current is None:
        return []
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return list(GATE_ORDER)
    old_hashes = previous.get("gate_event_hashes")
    new_hashes = current.get("gate_event_hashes")
    old_artifacts = previous.get("gate_artifacts")
    new_artifacts = current.get("gate_artifacts")
    changed = [
        gate for gate in GATE_ORDER
        if not isinstance(old_hashes, dict) or not isinstance(new_hashes, dict)
        or old_hashes.get(gate) != new_hashes.get(gate)
        or not isinstance(old_artifacts, dict) or not isinstance(new_artifacts, dict)
        or old_artifacts.get(gate) != new_artifacts.get(gate)
    ]
    if not changed and (previous.get("sha256") != current.get("sha256")
                        or previous.get("path") != current.get("path")):
        return list(GATE_ORDER)
    return changed


def _validate_gate_ledger_extension(previous: Mapping[str, Any], current: Mapping[str, Any],
                                    record_parent: Path) -> None:
    old_path_value, new_path_value = previous.get("path"), current.get("path")
    if not isinstance(old_path_value, str) or not isinstance(new_path_value, str):
        raise ValueError("Gate ledger path is missing from a prior or current binding.")
    old_path = Path(old_path_value).expanduser()
    new_path = Path(new_path_value).expanduser()
    if not old_path.is_absolute():
        old_path = record_parent / old_path
    if not new_path.is_absolute():
        new_path = record_parent / new_path
    if old_path.is_symlink() or new_path.is_symlink():
        raise ValueError("Gate ledger path must not be a symlink.")
    old_path = old_path.resolve(strict=False)
    new_path = new_path.resolve(strict=True)
    if old_path != new_path:
        raise ValueError("Gate ledger path cannot be replaced during an Acceptance revision.")
    if not new_path.is_file() or sha256_file(new_path) != current.get("sha256"):
        raise ValueError("Current Gate ledger file does not match the proposed Acceptance binding.")
    events = _load_events(new_path)
    event_hashes = {event["event_hash"] for event in events}
    old_hashes = previous.get("gate_event_hashes")
    if not isinstance(old_hashes, dict):
        raise ValueError("Previous Acceptance revision has no valid Gate event hash map.")
    for gate in GATE_ORDER:
        prior_hash = old_hashes.get(gate)
        if prior_hash is not None and prior_hash not in event_hashes:
            raise ValueError(f"Gate ledger history rolled back or replaced the prior {gate} approval event.")
    latest = {event["gate_id"]: event["event_hash"] for event in events}
    if current.get("gate_event_hashes") != {gate: latest.get(gate) for gate in GATE_ORDER}:
        raise ValueError("Current Acceptance Gate event hashes do not match the append-only Gate ledger tip.")
    if not isinstance(current.get("gate_artifacts"), dict):
        raise ValueError("Current Acceptance Gate artifact bindings are missing.")


def _ensure_only_fields_changed(previous: Mapping[str, Any], current: Mapping[str, Any],
                                allowed: set[str], label: str) -> None:
    keys = set(previous) | set(current)
    changed = {
        key for key in keys
        if previous.get(key) != current.get(key) or (key in previous) != (key in current)
    }
    unexpected = sorted(changed - allowed)
    if unexpected:
        raise ValueError(
            f"{label} changed fields outside the permitted review state: {', '.join(unexpected)}."
        )


def _changed_stage_ids(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    old_stages = previous.get("stages")
    new_stages = current.get("stages")
    if not isinstance(old_stages, list) or not isinstance(new_stages, list):
        return list(STAGE_ORDER)
    old_by_id = {item.get("stage_id"): item for item in old_stages if isinstance(item, dict)}
    new_by_id = {item.get("stage_id"): item for item in new_stages if isinstance(item, dict)}
    changed = {
        stage_id for stage_id in STAGE_ORDER
        if old_by_id.get(stage_id) != new_by_id.get(stage_id)
    }
    if [item.get("stage_id") for item in old_stages if isinstance(item, dict)] != [
        item.get("stage_id") for item in new_stages if isinstance(item, dict)
    ]:
        changed.update(STAGE_ORDER)
    if set(old_by_id) != set(STAGE_ORDER) or set(new_by_id) != set(STAGE_ORDER):
        changed.update(STAGE_ORDER)
    return [stage_id for stage_id in STAGE_ORDER if stage_id in changed]


def _validate_changed_stage_reviews(previous: Mapping[str, Any], current: Mapping[str, Any],
                                    changed: list[str]) -> None:
    old_by_id = {item.get("stage_id"): item for item in previous.get("stages", []) if isinstance(item, dict)}
    new_by_id = {item.get("stage_id"): item for item in current.get("stages", []) if isinstance(item, dict)}
    for stage_id in changed:
        stage = new_by_id.get(stage_id)
        if not isinstance(stage, dict):
            raise ValueError(f"Revised stage {stage_id} is missing.")
        if stage.get("status") in TERMINAL_STAGE_STATUSES:
            _validate_stage_review(stage)
            old_review = old_by_id.get(stage_id, {})
            new_review = tuple(stage.get(key) for key in REVIEW_FIELDS)
            old_review_tuple = tuple(old_review.get(key) for key in REVIEW_FIELDS)
            if new_review == old_review_tuple:
                raise ValueError(f"Revised terminal stage {stage_id} must carry fresh reviewer metadata.")


def _validate_stage_review(stage: Mapping[str, Any]) -> None:
    if not all(isinstance(stage.get(key), str) and stage[key].strip() for key in REVIEW_FIELDS):
        raise ValueError(f"Reviewed stage {stage.get('stage_id')} requires reviewed_by, reviewed_at, and review_rationale.")
    _parse_timestamp(stage.get("reviewed_at"), f"{stage.get('stage_id')} reviewed_at")


def _validate_final_decision_review(assessment: Any) -> None:
    if not isinstance(assessment, dict):
        raise ValueError("Final assessment must be an object.")
    if assessment.get("decision") not in {"PASS", "CONDITIONAL_PASS", "FAIL"}:
        raise ValueError("A recorded final decision must be PASS, CONDITIONAL_PASS, or FAIL.")
    if not all(isinstance(assessment.get(key), str) and assessment[key].strip()
               for key in ("assessed_by", "rationale", "assessed_at")):
        raise ValueError("A recorded final decision requires assessed_by, assessed_at, and rationale.")
    _parse_timestamp(assessment.get("assessed_at"), "final_assessment.assessed_at")


def _invalidated_assessment(revision: int, first_changed_stage: str) -> dict[str, Any]:
    return {
        "decision": "NOT_ASSESSED",
        "assessed_by": "UNASSESSED",
        "rationale": (
            f"Automatically invalidated by acceptance revision {revision} after "
            f"re-review of {first_changed_stage}; a new final decision is required."
        ),
        "blocking_issue_ids": [],
    }


def _invalidate_downstream(record: dict[str, Any], stage_ids: list[str]) -> None:
    targets = set(stage_ids)
    for stage in record.get("stages", []):
        if not isinstance(stage, dict) or stage.get("stage_id") not in targets:
            continue
        stage["status"] = "NOT_STARTED"
        stage["evidence"] = []
        stage["checks"] = []
        stage["limitations"] = []
        for key in ("not_applicable_reason", "blocker_reason", "decision_note", *REVIEW_FIELDS):
            stage.pop(key, None)


def _validate_downstream_reset(record: Mapping[str, Any], stage_ids: list[str]) -> None:
    by_id = {item.get("stage_id"): item for item in record.get("stages", []) if isinstance(item, dict)}
    for stage_id in stage_ids:
        stage = by_id.get(stage_id)
        if not isinstance(stage, dict):
            raise ValueError(f"Invalidated downstream stage {stage_id} is missing.")
        if (stage.get("status") != "NOT_STARTED" or stage.get("evidence") != []
                or stage.get("checks") != [] or stage.get("limitations") != []
                or any(key in stage for key in ("not_applicable_reason", "blocker_reason", "decision_note", *REVIEW_FIELDS))):
            raise ValueError(f"Downstream stage {stage_id} retained stale review state after an upstream revision.")


def _append_event(ledger_path: Path, snapshot_path: Path, record: dict[str, Any],
                  raw: bytes, actor: str, rationale: str, event_type: str,
                  changed_stage_ids: list[str], invalidated_stage_ids: list[str],
                  changed_gate_ids: list[str], changed_ledger_ids: list[str],
                  previous_event_hash: str, previous_record_sha256: str | None,
                  sequence: int, precommit_record_sha256: str) -> dict[str, Any]:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_path.parent.is_symlink() or snapshot_path.exists():
        raise ValueError("Acceptance revision snapshot path already exists or is unsafe.")
    _atomic_write(snapshot_path, raw)
    payload = {
        "schema_version": "1.0",
        "sequence": sequence,
        "event_type": event_type,
        "acceptance_id": record.get("acceptance_id"),
        "project_id": record.get("project_id"),
        "run_id": record.get("run_id"),
        "actor": actor.strip(),
        "rationale": rationale.strip(),
        "recorded_at": _now(),
        "record_sha256": _hash_bytes(raw),
        "precommit_record_sha256": precommit_record_sha256,
        "snapshot_file": snapshot_path.name,
        "previous_record_sha256": previous_record_sha256,
        "changed_stage_ids": changed_stage_ids,
        "invalidated_stage_ids": invalidated_stage_ids,
        "changed_gate_ids": changed_gate_ids,
        "changed_ledger_ids": changed_ledger_ids,
        "stage_statuses": {
            item.get("stage_id"): item.get("status")
            for item in record.get("stages", []) if isinstance(item, dict)
        },
        "final_decision": record.get("final_assessment", {}).get("decision"),
        "previous_event_hash": previous_event_hash,
    }
    event = {**payload, "event_hash": _event_hash(payload)}
    prior_size = ledger_path.stat().st_size if ledger_path.exists() else 0
    mode = "x" if sequence == 1 else "a"
    try:
        with ledger_path.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if ledger_path.exists():
            if sequence == 1:
                ledger_path.unlink()
            else:
                with ledger_path.open("r+b") as handle:
                    handle.truncate(prior_size)
                    handle.flush()
                    os.fsync(handle.fileno())
        snapshot_path.unlink(missing_ok=True)
        raise
    return event


def initialize_acceptance_ledger(record_path: Path, ledger_path: Path,
                                  actor: str, rationale: str) -> dict[str, Any]:
    if not isinstance(actor, str) or not actor.strip() or not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Acceptance ledger initialization requires a non-empty actor and rationale.")
    record_path = record_path.expanduser()
    raw = _record_bytes(record_path)
    record_path = record_path.resolve(strict=False)
    record = _record_object(raw)
    ledger_path, snapshots_dir = _safe_paths(ledger_path)
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    with _exclusive_lock(lock_path):
        if ledger_path.exists() or snapshots_dir.exists():
            raise ValueError("Acceptance ledger already exists; refusing to overwrite its history.")
        snapshots_dir.mkdir(parents=True, exist_ok=False)
        event = _append_event(
            ledger_path, snapshots_dir / "revision-000001.json", record, raw,
            actor, rationale, "RECORD_CREATED", [], [], [], [], GENESIS_HASH, None, 1,
            _hash_bytes(raw),
        )
    return {
        "valid": True, "acceptance_id": record.get("acceptance_id"),
        "revision": 1, "event_hash": event["event_hash"],
        "ledger_path": str(ledger_path),
        "snapshot_path": str(snapshots_dir / "revision-000001.json"),
    }


def _atomic_write(path: Path, raw: bytes) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    if temp_path.exists() or temp_path.is_symlink():
        raise ValueError("Acceptance record temporary path already exists.")
    try:
        with temp_path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def record_acceptance_revision(record_path: Path, ledger_path: Path,
                               actor: str, rationale: str) -> dict[str, Any]:
    if not isinstance(actor, str) or not actor.strip() or not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Acceptance revision requires a non-empty actor and rationale.")
    record_path = record_path.expanduser()
    if record_path.is_symlink():
        raise ValueError("Acceptance record must not be a symlink.")
    record_path = record_path.resolve(strict=False)
    ledger_path, snapshots_dir = _safe_paths(ledger_path)
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    with _exclusive_lock(lock_path):
        events, snapshots = _load_history(ledger_path)
        previous_event = events[-1]
        previous_record = snapshots[-1]
        raw = _record_bytes(record_path)
        record = _record_object(raw)
        previous_snapshot_path = snapshots_dir / previous_event["snapshot_file"]
        if _hash_bytes(raw) == previous_event["record_sha256"]:
            raise ValueError("Acceptance record is unchanged; no revision event is needed.")
        for field in IMMUTABLE_RECORD_FIELDS:
            if record.get(field) != previous_record.get(field):
                raise ValueError(f"Acceptance identity/source field {field} changed; create a new Acceptance Record.")

        changed = _changed_stage_ids(previous_record, record)
        invalidated: list[str] = []
        changed_gates: list[str] = []
        old_assessment = previous_record.get("final_assessment")
        new_assessment = record.get("final_assessment")
        changed_ledger_ids = _changed_external_ledger_ids(previous_record, record)
        previous_gate_binding = previous_record.get("workflow_gate_ledger")
        current_gate_binding = record.get("workflow_gate_ledger")
        previous_run_binding = previous_record.get("run_event_ledger")
        current_run_binding = record.get("run_event_ledger")
        if changed_ledger_ids and any(previous_record.get(key) is not None for key in EXTERNAL_LEDGER_FIELDS):
            _ensure_only_fields_changed(previous_record, record, {*EXTERNAL_LEDGER_FIELDS}, "Acceptance upstream-ledger revision")
            if "workflow_gate_ledger" in changed_ledger_ids:
                if not isinstance(current_gate_binding, dict):
                    raise ValueError("An upstream ledger revision cannot remove workflow_gate_ledger.")
                if previous_gate_binding is not None:
                    _validate_gate_ledger_extension(previous_gate_binding, current_gate_binding, record_path.parent)
            if "run_event_ledger" in changed_ledger_ids:
                if not isinstance(current_run_binding, dict):
                    raise ValueError("An upstream ledger revision cannot remove run_event_ledger.")
                _validate_run_event_ledger_binding(current_run_binding, record_path.parent, record.get("run_id"), previous_run_binding)
            changed_gates = _changed_gate_ids(previous_gate_binding, current_gate_binding)
            invalidated = list(STAGE_ORDER)
            _invalidate_downstream(record, invalidated)
            next_revision = len(events) + 1
            record["final_assessment"] = _invalidated_assessment(next_revision, "upstream ledger")
            changed = []
            event_type = "UPSTREAM_LEDGER_RECORDED"
        elif changed:
            if changed_ledger_ids:
                raise ValueError("Initial upstream ledger bindings must be captured with an explicit final-decision review, not a stage revision.")
            _ensure_only_fields_changed(
                previous_record, record, {"stages", "final_assessment"},
                "Acceptance revision",
            )
            revised_stage_ids = [changed[0]]
            _validate_changed_stage_reviews(previous_record, record, revised_stage_ids)
            earliest = STAGE_ORDER.index(changed[0])
            invalidated = list(STAGE_ORDER[earliest + 1:])
            _invalidate_downstream(record, invalidated)
            next_revision = len(events) + 1
            record["final_assessment"] = _invalidated_assessment(next_revision, changed[0])
            changed = revised_stage_ids
            event_type = "STAGE_REVIEW_RECORDED"
        elif old_assessment != new_assessment:
            allowed = {"final_assessment", *EXTERNAL_LEDGER_FIELDS} if changed_ledger_ids else {"final_assessment"}
            _ensure_only_fields_changed(
                previous_record, record, allowed,
                "Acceptance revision",
            )
            if changed_ledger_ids and any(previous_record.get(key) is not None for key in EXTERNAL_LEDGER_FIELDS):
                raise ValueError("Existing upstream ledger changes require a full upstream-ledger revision.")
            if "workflow_gate_ledger" in changed_ledger_ids and not isinstance(current_gate_binding, dict):
                raise ValueError("Initial Gate binding must be a complete object.")
            if "run_event_ledger" in changed_ledger_ids:
                if not isinstance(current_run_binding, dict):
                    raise ValueError("Initial Run Event Ledger binding must be a complete object.")
                _validate_run_event_ledger_binding(current_run_binding, record_path.parent, record.get("run_id"))
            _validate_final_decision_review(new_assessment)
            old_meta = tuple(old_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(old_assessment, dict) else ()
            new_meta = tuple(new_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(new_assessment, dict) else ()
            if new_meta == old_meta:
                raise ValueError("A final decision revision requires fresh assessed_by, assessed_at, or rationale metadata.")
            event_type = "FINAL_DECISION_RECORDED"
        else:
            raise ValueError("Acceptance record changed outside the stage/final-assessment review fields.")

        normalized = (json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        sequence = len(events) + 1
        snapshot_path = snapshots_dir / f"revision-{sequence:06d}.json"
        event = _append_event(
            ledger_path, snapshot_path, record, normalized, actor, rationale,
            event_type, changed, invalidated, changed_gates, changed_ledger_ids, previous_event["event_hash"],
            previous_event["record_sha256"], sequence, _hash_bytes(raw),
        )
        _atomic_write(record_path, normalized)
    return {
        "valid": True,
        "acceptance_id": record.get("acceptance_id"),
        "revision": sequence,
        "event_type": event_type,
        "changed_stage_ids": changed,
        "invalidated_stage_ids": invalidated,
        "changed_gate_ids": changed_gates,
        "changed_ledger_ids": changed_ledger_ids,
        "final_decision": record.get("final_assessment", {}).get("decision"),
        "event_hash": event["event_hash"],
        "ledger_path": str(ledger_path),
        "snapshot_path": str(snapshot_path),
    }


def recover_acceptance_record(record_path: Path, ledger_path: Path) -> dict[str, Any]:
    """Recover only a committed update whose current file is still the precommit draft."""
    record_path = record_path.expanduser()
    if record_path.is_symlink():
        raise ValueError("Acceptance record must not be a symlink.")
    record_path = record_path.resolve(strict=False)
    ledger_path, snapshots_dir = _safe_paths(ledger_path)
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    with _exclusive_lock(lock_path):
        # A process may stop mid-append. A final unterminated JSONL line is
        # uncommitted by definition; truncate it before examining snapshots.
        if ledger_path.exists():
            ledger_bytes = ledger_path.read_bytes()
            if ledger_bytes and not ledger_bytes.endswith(b"\n"):
                last_newline = ledger_bytes.rfind(b"\n")
                if last_newline < 0:
                    raise ValueError("Recovery refused: no complete ledger event remains; reinitialize only after manual review.")
                with ledger_path.open("r+b") as handle:
                    handle.truncate(last_newline + 1)
                    handle.flush()
                    os.fsync(handle.fileno())
        complete_lines = ledger_path.read_bytes().splitlines() if ledger_path.exists() else []
        committed_names = {f"revision-{index:06d}.json" for index in range(1, len(complete_lines) + 1)}
        allowed_orphans = {
            f"revision-{len(complete_lines) + 1:06d}.json",
            f"revision-{len(complete_lines) + 1:06d}.json.tmp",
        }
        present_names = {item.name for item in snapshots_dir.iterdir()}
        orphans = present_names - committed_names
        if orphans:
            if not orphans.issubset(allowed_orphans):
                raise ValueError("Recovery refused: unexpected or multiple unreferenced snapshot files exist.")
            for name in orphans:
                orphan = snapshots_dir / name
                if orphan.is_symlink() or not orphan.is_file():
                    raise ValueError("Recovery refused: unsafe unreferenced snapshot entry.")
                orphan.unlink()
        events, _ = _load_history(ledger_path)
        if not events:
            raise ValueError("No committed acceptance event remains; reinitialize only after manual review.")
        current = _record_bytes(record_path)
        latest_event = events[-1]
        latest = (snapshots_dir / latest_event["snapshot_file"]).read_bytes()
        if _hash_bytes(current) == latest_event["record_sha256"]:
            return {"valid": True, "recovered": False, "revision": len(events),
                    "record_sha256": latest_event["record_sha256"]}
        allowed = {latest_event.get("precommit_record_sha256"),
                   latest_event.get("previous_record_sha256")}
        if _hash_bytes(current) not in allowed:
            raise ValueError("Recovery refused: current record is not the exact precommit state; preserve it for manual review.")
        _atomic_write(record_path, latest)
        return {"valid": True, "recovered": True, "revision": len(events),
                "record_sha256": latest_event["record_sha256"]}


def validate_acceptance_ledger(record_path: Path, ledger_path: Path) -> dict[str, Any]:
    try:
        record_path = record_path.expanduser()
        if record_path.is_symlink():
            raise ValueError("Acceptance record must not be a symlink.")
        record_path = record_path.resolve(strict=False)
        ledger_path, snapshots_dir = _safe_paths(ledger_path)
        events, snapshots = _load_history(ledger_path)
        raw = _record_bytes(record_path)
        current_hash = _hash_bytes(raw)
        latest_hash = events[-1]["record_sha256"]
        if current_hash != latest_hash:
            raise ValueError(
                "Current Acceptance Record does not match the latest immutable revision snapshot; "
                "record a revision or restore the recorded snapshot."
            )
        current = _record_object(raw)
        if current != snapshots[-1]:
            raise ValueError("Current Acceptance Record content differs from the latest revision snapshot.")
        return {
            "valid": True,
            "revision": len(events),
            "event_count": len(events),
            "latest_event_hash": events[-1]["event_hash"],
            "latest_record_sha256": latest_hash,
            "latest_event_type": events[-1]["event_type"],
            "changed_gate_ids": events[-1]["changed_gate_ids"],
            "changed_ledger_ids": events[-1]["changed_ledger_ids"],
            "ledger_path": str(ledger_path),
            "snapshot_directory": str(snapshots_dir),
            "issues": [],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        return {
            "valid": False, "revision": None, "event_count": None,
            "latest_event_hash": None, "latest_record_sha256": None,
            "ledger_path": str(ledger_path), "issues": [{"code": "ACCEPTANCE_LEDGER_INVALID", "message": str(exc)}],
        }


def inspect_acceptance_history(ledger_path: Path) -> dict[str, Any]:
    """Return the verified revision timeline without modifying any files."""
    try:
        ledger_path, snapshots_dir = _safe_paths(ledger_path)
        events, snapshots = _load_history(ledger_path)
        timeline = []
        for event, snapshot in zip(events, snapshots):
            timeline.append({
                "revision": event["sequence"],
                "event_type": event["event_type"],
                "recorded_at": event["recorded_at"],
                "actor": event["actor"],
                "rationale": event["rationale"],
                "changed_stage_ids": event["changed_stage_ids"],
                "invalidated_stage_ids": event["invalidated_stage_ids"],
                "changed_gate_ids": event["changed_gate_ids"],
                "changed_ledger_ids": event["changed_ledger_ids"],
                "stage_statuses": event["stage_statuses"],
                "final_decision": event["final_decision"],
                "record_sha256": event["record_sha256"],
                "previous_record_sha256": event["previous_record_sha256"],
                "event_hash": event["event_hash"],
                "snapshot_path": str(snapshots_dir / event["snapshot_file"]),
            })
        return {
            "valid": True,
            "acceptance_id": events[-1]["acceptance_id"],
            "project_id": events[-1]["project_id"],
            "run_id": events[-1]["run_id"],
            "event_count": len(events),
            "latest_event_hash": events[-1]["event_hash"],
            "events": timeline,
            "issues": [],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        return {
            "valid": False, "acceptance_id": None, "project_id": None,
            "run_id": None, "event_count": None, "latest_event_hash": None,
            "events": [], "issues": [{"code": "ACCEPTANCE_LEDGER_INVALID", "message": str(exc)}],
        }


def _checkpoint_binding_path(binding: Mapping[str, Any], record_parent: Path,
                             label: str) -> Path:
    value = binding.get("path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} checkpoint binding requires a non-empty path.")
    supplied = Path(value).expanduser()
    if not supplied.is_absolute():
        supplied = record_parent / supplied
    if supplied.is_symlink():
        raise ValueError(f"{label} checkpoint path must not be a symlink.")
    resolved = supplied.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} checkpoint path must resolve to a regular file.")
    return resolved


def _build_acceptance_checkpoint_payload(record_path: Path,
                                         ledger_path: Path) -> dict[str, Any]:
    record_path = record_path.expanduser()
    if record_path.is_symlink():
        raise ValueError("Acceptance record must not be a symlink.")
    record_path = record_path.resolve(strict=True)
    if not record_path.is_file():
        raise ValueError("Acceptance record must be a regular file.")
    ledger_path, snapshots_dir = _safe_paths(ledger_path)
    events, snapshots = _load_history(ledger_path)
    record_raw = _record_bytes(record_path)
    record_sha = _hash_bytes(record_raw)
    if record_sha != events[-1]["record_sha256"]:
        raise ValueError("Current Acceptance Record does not match the latest committed revision.")
    record = _record_object(record_raw)
    if record != snapshots[-1]:
        raise ValueError("Current Acceptance Record content differs from the latest committed snapshot.")

    upstream_ledgers: dict[str, Any] = {}
    for key in EXTERNAL_LEDGER_FIELDS:
        binding = record.get(key)
        if binding is None:
            continue
        if not isinstance(binding, dict):
            raise ValueError(f"{key} must be an object before creating an external checkpoint.")
        if key == "workflow_gate_ledger":
            _validate_gate_ledger_extension(binding, binding, record_path.parent)
            path = _checkpoint_binding_path(binding, record_path.parent, "Workflow Gate Ledger")
            gate_events = _load_events(path)
            latest: dict[str, dict[str, Any]] = {}
            for event in gate_events:
                latest[event["gate_id"]] = event
            actual_hashes = {
                gate_id: latest.get(gate_id, {}).get("event_hash")
                for gate_id in GATE_ORDER
            }
            actual_artifacts: dict[str, list[dict[str, Any]]] = {}
            for gate_id in GATE_ORDER:
                gate_event = latest.get(gate_id)
                event_artifacts = gate_event.get("artifacts") if isinstance(gate_event, dict) else []
                if not isinstance(event_artifacts, list):
                    raise ValueError(f"Workflow Gate {gate_id} artifact references are malformed.")
                normalized: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for item in event_artifacts:
                    if not isinstance(item, dict):
                        raise ValueError(f"Workflow Gate {gate_id} contains a malformed artifact reference.")
                    artifact_id, artifact_path, artifact_sha = (
                        item.get("artifact_id"), item.get("path"), item.get("sha256")
                    )
                    if (not isinstance(artifact_id, str) or not artifact_id.strip()
                            or artifact_id in seen_ids or not isinstance(artifact_path, str)
                            or not artifact_path.strip() or Path(artifact_path).is_symlink()
                            or not isinstance(artifact_sha, str) or len(artifact_sha) != 64
                            or any(char not in "0123456789abcdef" for char in artifact_sha)):
                        raise ValueError(f"Workflow Gate {gate_id} contains an invalid artifact identity.")
                    seen_ids.add(artifact_id)
                    normalized.append({
                        "artifact_id": artifact_id,
                        "path": str(Path(artifact_path).resolve(strict=False)),
                        "sha256": artifact_sha,
                    })
                actual_artifacts[gate_id] = normalized
            if binding.get("gate_event_hashes") != actual_hashes:
                raise ValueError("Workflow Gate Ledger event hashes differ from the current Acceptance binding.")
            if binding.get("gate_artifacts") != actual_artifacts:
                raise ValueError("Workflow Gate Ledger artifact references differ from the current Acceptance binding.")
        else:
            _validate_run_event_ledger_binding(binding, record_path.parent, str(record.get("run_id", "")))
            path = _checkpoint_binding_path(binding, record_path.parent, "Run Event Ledger")
        upstream_ledgers[key] = {
            "path": str(path),
            "sha256": _hash_file(path),
            "binding": binding,
        }

    snapshot_manifest = []
    for event in events:
        snapshot_path = snapshots_dir / event["snapshot_file"]
        if snapshot_path.is_symlink() or not snapshot_path.is_file():
            raise ValueError(f"Unsafe or missing Acceptance snapshot: {event['snapshot_file']}.")
        snapshot_manifest.append({
            "name": event["snapshot_file"],
            "sha256": _hash_file(snapshot_path),
        })

    return {
        "schema_version": "1.0",
        "checkpoint_type": "DOR_ACCEPTANCE_LEDGER_CHECKPOINT",
        "acceptance": {
            "acceptance_id": record.get("acceptance_id"),
            "project_id": record.get("project_id"),
            "run_id": record.get("run_id"),
        },
        "record": {
            "path": str(record_path),
            "sha256": record_sha,
        },
        "revision_ledger": {
            "path": str(ledger_path),
            "sha256": _hash_file(ledger_path),
            "event_count": len(events),
            "latest_event_hash": events[-1]["event_hash"],
            "latest_record_sha256": events[-1]["record_sha256"],
        },
        "revision_snapshots": {
            "directory": str(snapshots_dir),
            "items": snapshot_manifest,
        },
        "upstream_ledgers": upstream_ledgers,
    }


def create_acceptance_checkpoint(record_path: Path, ledger_path: Path,
                                  checkpoint_path: Path) -> dict[str, Any]:
    """Create a detached state checkpoint; its digest must be retained out of band."""
    payload = _build_acceptance_checkpoint_payload(record_path, ledger_path)
    target = checkpoint_path.expanduser()
    if target.is_symlink() or target.exists():
        raise ValueError("Acceptance checkpoint output already exists or is a symlink; refusing to overwrite.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = target.parent.resolve(strict=True) / target.name
    protected = {
        Path(payload["record"]["path"]),
        Path(payload["revision_ledger"]["path"]),
        *(Path(item["path"]) for item in payload["upstream_ledgers"].values()),
    }
    if target in protected:
        raise ValueError("Acceptance checkpoint output cannot overwrite a bound source or ledger.")
    snapshots_dir = Path(payload["revision_snapshots"]["directory"])
    try:
        target.relative_to(snapshots_dir)
    except ValueError:
        pass
    else:
        raise ValueError("Acceptance checkpoint must not be stored inside the revision snapshot directory.")
    raw = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    _atomic_write(target, raw)
    return {
        "valid": True,
        "checkpoint_path": str(target),
        "checkpoint_sha256": _hash_bytes(raw),
        "acceptance_id": payload["acceptance"]["acceptance_id"],
        "revision_count": payload["revision_ledger"]["event_count"],
        "external_anchor_required": True,
        "instruction": "Store this checkpoint file and its SHA-256 outside the writable project/ledger trust boundary.",
    }


def verify_acceptance_checkpoint(record_path: Path, ledger_path: Path,
                                  checkpoint_path: Path,
                                  expected_sha256: str) -> dict[str, Any]:
    """Compare live acceptance state with a checkpoint whose digest is independently trusted."""
    try:
        if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
                or any(char not in "0123456789abcdef" for char in expected_sha256)):
            raise ValueError("--expected-sha256 must be a lowercase SHA-256 digest.")
        supplied = checkpoint_path.expanduser()
        if supplied.is_symlink() or not supplied.is_file():
            raise ValueError("Acceptance checkpoint must be a regular, non-symlink file.")
        raw = supplied.read_bytes()
        actual_checkpoint_sha = _hash_bytes(raw)
        if actual_checkpoint_sha != expected_sha256:
            return {
                "valid": False,
                "checkpoint_sha256": actual_checkpoint_sha,
                "issues": [{
                    "code": "ACCEPTANCE_CHECKPOINT_ANCHOR_MISMATCH",
                    "message": "Checkpoint file SHA-256 differs from the independently retained expected digest.",
                }],
            }
        try:
            checkpoint = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Acceptance checkpoint must be readable JSON: {exc}") from exc
        if not isinstance(checkpoint, dict):
            raise ValueError("Acceptance checkpoint must be a JSON object.")
        live = _build_acceptance_checkpoint_payload(record_path, ledger_path)
        if not isinstance(checkpoint.get("revision_ledger"), dict):
            raise ValueError("Checkpoint revision_ledger section is missing or malformed.")
        anchor_ledger = checkpoint["revision_ledger"]
        anchor_count = anchor_ledger.get("event_count")
        if type(anchor_count) is not int or anchor_count < 1:
            raise ValueError("Checkpoint event_count must be a positive integer.")
        current_events, _ = _load_history(Path(live["revision_ledger"]["path"]))
        if anchor_count > len(current_events):
            return {
                "valid": False,
                "checkpoint_sha256": actual_checkpoint_sha,
                "issues": [{
                    "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                    "message": "Current Acceptance history is shorter than the independently anchored revision; rollback detected.",
                }],
            }
        anchor_items = checkpoint.get("revision_snapshots", {}).get("items")
        live_items = live["revision_snapshots"]["items"]
        if (checkpoint.get("acceptance") != live["acceptance"]
                or checkpoint.get("record", {}).get("path") != live["record"]["path"]
                or anchor_ledger.get("path") != live["revision_ledger"]["path"]
                or checkpoint.get("revision_snapshots", {}).get("directory") != live["revision_snapshots"]["directory"]
                or not isinstance(anchor_items, list) or len(anchor_items) != anchor_count
                or live_items[:anchor_count] != anchor_items):
            return {
                "valid": False,
                "checkpoint_sha256": actual_checkpoint_sha,
                "issues": [{
                    "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                    "message": "Anchored Acceptance identity, paths, or revision snapshots were changed.",
                }],
            }
        anchor_event = current_events[anchor_count - 1]
        if (anchor_event.get("event_hash") != anchor_ledger.get("latest_event_hash")
                or anchor_event.get("record_sha256") != anchor_ledger.get("latest_record_sha256")
                or checkpoint.get("record", {}).get("sha256") != anchor_event.get("record_sha256")):
            return {
                "valid": False,
                "checkpoint_sha256": actual_checkpoint_sha,
                "issues": [{
                    "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                    "message": "The anchored event tip or record snapshot is no longer present at its original revision.",
                }],
            }

        # Upstream ledgers that existed at the checkpoint must remain at the same
        # path and preserve their old event history. New bindings must be captured
        # by a later, valid Acceptance event.
        anchor_upstream = checkpoint.get("upstream_ledgers", {})
        live_upstream = live.get("upstream_ledgers", {})
        if not isinstance(anchor_upstream, dict) or not isinstance(live_upstream, dict):
            raise ValueError("Checkpoint upstream_ledgers section must be an object.")
        record_parent = Path(live["record"]["path"]).parent
        run_id = str(live["acceptance"]["run_id"])
        for key in EXTERNAL_LEDGER_FIELDS:
            old_item = anchor_upstream.get(key)
            new_item = live_upstream.get(key)
            if old_item is not None:
                if not isinstance(old_item, dict) or not isinstance(new_item, dict):
                    return {
                        "valid": False,
                        "checkpoint_sha256": actual_checkpoint_sha,
                        "issues": [{
                            "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                            "message": f"Previously bound upstream ledger {key} was removed or malformed.",
                        }],
                    }
                old_binding, new_binding = old_item.get("binding"), new_item.get("binding")
                if key == "workflow_gate_ledger":
                    _validate_gate_ledger_extension(old_binding, new_binding, record_parent)
                else:
                    _validate_run_event_ledger_binding(new_binding, record_parent, run_id, old_binding)
            elif new_item is not None:
                was_recorded = any(
                    key in event.get("changed_ledger_ids", [])
                    for event in current_events[anchor_count:]
                )
                if not was_recorded:
                    return {
                        "valid": False,
                        "checkpoint_sha256": actual_checkpoint_sha,
                        "issues": [{
                            "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                            "message": f"New upstream ledger {key} has no post-checkpoint Acceptance binding event.",
                        }],
                    }

        if anchor_count == len(current_events):
            if checkpoint != live:
                changed = sorted(
                    key for key in set(checkpoint) | set(live)
                    if checkpoint.get(key) != live.get(key)
                )
                return {
                    "valid": False,
                    "checkpoint_sha256": actual_checkpoint_sha,
                    "changed_sections": changed,
                    "issues": [{
                        "code": "ACCEPTANCE_CHECKPOINT_STATE_CHANGED",
                        "message": "Live Acceptance state differs from the checkpoint at the same revision tip.",
                    }],
                }
            status = "CURRENT_MATCH"
        else:
            status = "APPEND_ONLY_EXTENDED"
        return {
            "valid": True,
            "status": status,
            "current_state_is_checkpointed": status == "CURRENT_MATCH",
            "checkpoint_sha256": actual_checkpoint_sha,
            "acceptance_id": live["acceptance"]["acceptance_id"],
            "checkpoint_revision_count": anchor_count,
            "current_revision_count": len(current_events),
            "latest_event_hash": live["revision_ledger"]["latest_event_hash"],
            "issues": [],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "checkpoint_sha256": None,
            "issues": [{
                "code": "ACCEPTANCE_CHECKPOINT_INVALID",
                "message": str(exc),
            }],
        }
