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

from dor.gates import _exclusive_lock

GENESIS_HASH = "0" * 64
STAGE_ORDER = (
    "source_selection", "source_integrity", "extraction_review",
    "semantic_mapping", "canonical_reconciliation", "cohort_feasibility",
    "modeling_validation", "publication_handoff",
)
TERMINAL_STAGE_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
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
            if event.get("event_type") not in {"RECORD_CREATED", "STAGE_REVIEW_RECORDED", "FINAL_DECISION_RECORDED"}:
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
                                   "rationale", "recorded_at", "record_sha256")):
                raise ValueError(f"Acceptance event at line {line_number} lacks required metadata.")
            _parse_timestamp(event["recorded_at"], f"event {line_number} recorded_at")
            digest = event["record_sha256"]
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"Invalid record SHA-256 at line {line_number}.")
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
                if event.get("changed_stage_ids") != [] or event.get("invalidated_stage_ids") != []:
                    raise ValueError("Initial acceptance event cannot claim revised stages.")
                if previous_record is not None:
                    raise ValueError("Invalid initial acceptance history.")
            else:
                if previous_record is None:
                    raise ValueError("Acceptance history has no preceding snapshot.")
                for field in IMMUTABLE_RECORD_FIELDS:
                    if snapshot.get(field) != previous_record.get(field):
                        raise ValueError(f"Acceptance identity/source field {field} changed; create a new Acceptance Record.")
                raw_changed = _changed_stage_ids(previous_record, snapshot)
                previous_assessment = previous_record.get("final_assessment")
                current_assessment = snapshot.get("final_assessment")
                assessment_changed = previous_assessment != current_assessment
                if raw_changed:
                    if event.get("event_type") != "STAGE_REVIEW_RECORDED":
                        raise ValueError(f"Stage changes must be recorded as STAGE_REVIEW_RECORDED at line {line_number}.")
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
                    if not assessment_changed or event.get("event_type") != "FINAL_DECISION_RECORDED":
                        raise ValueError(f"Acceptance revision {line_number} contains no valid stage or final-decision change.")
                    if event.get("changed_stage_ids") != [] or event.get("invalidated_stage_ids") != []:
                        raise ValueError(f"Final-decision event must not list revised stages at line {line_number}.")
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
    return events, snapshots


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
                  previous_event_hash: str, previous_record_sha256: str | None,
                  sequence: int) -> dict[str, Any]:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_path.parent.is_symlink() or snapshot_path.exists():
        raise ValueError("Acceptance revision snapshot path already exists or is unsafe.")
    with snapshot_path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
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
        "snapshot_file": snapshot_path.name,
        "previous_record_sha256": previous_record_sha256,
        "changed_stage_ids": changed_stage_ids,
        "invalidated_stage_ids": invalidated_stage_ids,
        "stage_statuses": {
            item.get("stage_id"): item.get("status")
            for item in record.get("stages", []) if isinstance(item, dict)
        },
        "final_decision": record.get("final_assessment", {}).get("decision"),
        "previous_event_hash": previous_event_hash,
    }
    event = {**payload, "event_hash": _event_hash(payload)}
    mode = "x" if sequence == 1 else "a"
    with ledger_path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
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
            actor, rationale, "RECORD_CREATED", [], [], GENESIS_HASH, None, 1,
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
        old_assessment = previous_record.get("final_assessment")
        new_assessment = record.get("final_assessment")
        if changed:
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
            _validate_final_decision_review(new_assessment)
            old_meta = tuple(old_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(old_assessment, dict) else ()
            new_meta = tuple(new_assessment.get(key) for key in ("assessed_by", "assessed_at", "rationale")) if isinstance(new_assessment, dict) else ()
            if new_meta == old_meta:
                raise ValueError("A final decision revision requires fresh assessed_by, assessed_at, or rationale metadata.")
            event_type = "FINAL_DECISION_RECORDED"
        else:
            raise ValueError("Acceptance record changed outside the stage/final-assessment review fields.")

        normalized = (json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        _atomic_write(record_path, normalized)
        sequence = len(events) + 1
        snapshot_path = snapshots_dir / f"revision-{sequence:06d}.json"
        event = _append_event(
            ledger_path, snapshot_path, record, normalized, actor, rationale,
            event_type, changed, invalidated, previous_event["event_hash"],
            previous_event["record_sha256"], sequence,
        )
    return {
        "valid": True,
        "acceptance_id": record.get("acceptance_id"),
        "revision": sequence,
        "event_type": event_type,
        "changed_stage_ids": changed,
        "invalidated_stage_ids": invalidated,
        "final_decision": record.get("final_assessment", {}).get("decision"),
        "event_hash": event["event_hash"],
        "ledger_path": str(ledger_path),
        "snapshot_path": str(snapshot_path),
    }


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
