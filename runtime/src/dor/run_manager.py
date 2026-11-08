"""Project run management, artifact lineage, and conservative resume planning.

A run event ledger records execution metadata. It is separate from the scientific
G0-G4 approval ledger and never creates or changes scientific approvals.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import uuid
from typing import Any, Mapping

from dor.gates import inspect_gate_ledger
from dor.mapping import sha256_file

RUN_SCHEMA_VERSION = "1.0"
EVENT_GENESIS_HASH = "0" * 64
_STAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GATE_IDS = {"G0", "G1", "G2", "G3", "G4"}
_PRODUCER_KINDS = {"local", "worker", "manual"}
_STAGE_STATUSES = {"RUNNING", "SUCCEEDED", "FAILED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _safe_relative_path(root: Path, raw: str, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty relative path.")
    windows = PureWindowsPath(raw)
    normalized_raw = raw.replace("\\", "/")
    raw_parts = normalized_raw.split("/")
    posix = PurePosixPath(normalized_raw)
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"{label} contains an unsafe path component: {raw!r}.")
    if Path(raw).is_absolute() or windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ValueError(f"{label} must be relative to the run workspace: {raw!r}.")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"{label} contains an unsafe path component: {raw!r}.")
    candidate = (root / Path(*posix.parts)).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if not candidate.is_relative_to(root_resolved):
        raise ValueError(f"{label} escapes the run workspace: {raw!r}.")
    return candidate


def _absolute_existing_directory(raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be an absolute directory path.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute: {raw!r}.")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} is not a directory: {resolved}.")
    return resolved


def _validate_plan(plan: dict[str, Any], run_root: Path | None = None) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, str]]:
    if plan.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Run plan schema_version must be {RUN_SCHEMA_VERSION}.")
    project_id = plan.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("Run plan requires a non-empty project_id.")

    roots_value = plan.get("source_roots")
    if not isinstance(roots_value, list) or not roots_value:
        raise ValueError("Run plan requires one or more explicit source_roots.")
    roots = [_absolute_existing_directory(item, "source_roots entry") for item in roots_value]
    if len({str(item) for item in roots}) != len(roots):
        raise ValueError("Run plan source_roots contains duplicate directories.")
    if run_root is not None:
        root = run_root.resolve(strict=False)
        for source_root in roots:
            if root == source_root or root.is_relative_to(source_root) or source_root.is_relative_to(root):
                raise ValueError("Run workspace and protected source_roots must be separate, non-nested directories.")

    source_defs = plan.get("source_artifacts")
    if not isinstance(source_defs, list) or not source_defs:
        raise ValueError("Run plan requires explicit source_artifacts; do not infer source inputs.")
    artifacts: dict[str, dict[str, Any]] = {}
    for item in source_defs:
        if not isinstance(item, dict):
            raise ValueError("Every source_artifacts item must be an object.")
        artifact_id, raw_path = item.get("artifact_id"), item.get("path")
        if not isinstance(artifact_id, str) or not _STAGE_ID.fullmatch(artifact_id):
            raise ValueError(f"Invalid source artifact_id: {artifact_id!r}.")
        if artifact_id in artifacts:
            raise ValueError(f"Duplicate artifact_id: {artifact_id}.")
        if not isinstance(raw_path, str) or not Path(raw_path).expanduser().is_absolute():
            raise ValueError(f"Source artifact {artifact_id} path must be absolute.")
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Source artifact {artifact_id} is not a file: {path}.")
        if not any(path.is_relative_to(source_root) for source_root in roots):
            raise ValueError(f"Source artifact {artifact_id} is outside all declared source_roots: {path}.")
        artifacts[artifact_id] = {"artifact_id": artifact_id, "path": str(path), "kind": "source"}

    stages_value = plan.get("stages")
    if not isinstance(stages_value, list) or not stages_value:
        raise ValueError("Run plan requires a non-empty explicit stages array.")
    stages: dict[str, dict[str, Any]] = {}
    producer_by_artifact: dict[str, str] = {}
    output_paths: set[str] = set()
    for stage in stages_value:
        if not isinstance(stage, dict):
            raise ValueError("Every stage must be an object.")
        stage_id = stage.get("stage_id")
        if not isinstance(stage_id, str) or not _STAGE_ID.fullmatch(stage_id):
            raise ValueError(f"Invalid stage_id: {stage_id!r}.")
        if stage_id in stages:
            raise ValueError(f"Duplicate stage_id: {stage_id}.")
        executor = stage.get("executor", "local")
        if executor not in _PRODUCER_KINDS:
            raise ValueError(f"Stage {stage_id} executor must be local, worker, or manual.")
        worker_task = stage.get("worker_task")
        if executor == "worker":
            if not isinstance(worker_task, dict):
                raise ValueError(f"Worker stage {stage_id} requires an explicit worker_task object.")
            objective = worker_task.get("objective")
            actions = worker_task.get("permitted_actions")
            forbidden = worker_task.get("forbidden_actions", [])
            if not isinstance(objective, str) or not objective.strip():
                raise ValueError(f"Worker stage {stage_id} requires a non-empty worker_task.objective.")
            if not isinstance(actions, list) or not actions or any(not isinstance(x, str) or not x.strip() for x in actions):
                raise ValueError(f"Worker stage {stage_id} requires non-empty worker_task.permitted_actions.")
            if not isinstance(forbidden, list) or any(not isinstance(x, str) or not x.strip() for x in forbidden):
                raise ValueError(f"Worker stage {stage_id} worker_task.forbidden_actions must be an array of non-empty strings.")
            for limit_name in ("max_context_tokens", "max_output_tokens"):
                limit = worker_task.get(limit_name)
                if limit is not None and (not isinstance(limit, int) or limit < 1):
                    raise ValueError(f"Worker stage {stage_id} {limit_name} must be a positive integer.")
        elif worker_task is not None:
            raise ValueError(f"Only Worker stages may declare worker_task: {stage_id}.")
        dependencies = stage.get("depends_on", [])
        inputs = stage.get("inputs", [])
        outputs = stage.get("outputs", [])
        if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise ValueError(f"Stage {stage_id} depends_on must be an array of stage IDs.")
        if len(dependencies) != len(set(dependencies)) or stage_id in dependencies:
            raise ValueError(f"Stage {stage_id} has duplicate or self dependencies.")
        if not isinstance(inputs, list) or not inputs or any(not isinstance(x, str) for x in inputs):
            raise ValueError(f"Stage {stage_id} must declare a non-empty inputs array of artifact IDs.")
        if len(inputs) != len(set(inputs)):
            raise ValueError(f"Stage {stage_id} inputs contains duplicate artifact IDs.")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError(f"Stage {stage_id} must declare a non-empty outputs array.")
        gate = stage.get("required_gate")
        if gate is not None and gate not in _GATE_IDS:
            raise ValueError(f"Stage {stage_id} required_gate must be G0-G4 or null.")
        normalized_outputs = []
        for output in outputs:
            if not isinstance(output, dict):
                raise ValueError(f"Stage {stage_id} output declarations must be objects.")
            artifact_id, raw_path = output.get("artifact_id"), output.get("path")
            kind = output.get("kind", "derived")
            if not isinstance(artifact_id, str) or not _STAGE_ID.fullmatch(artifact_id):
                raise ValueError(f"Stage {stage_id} has invalid output artifact_id {artifact_id!r}.")
            if artifact_id in artifacts or artifact_id in producer_by_artifact:
                raise ValueError(f"Duplicate output artifact_id: {artifact_id}.")
            if kind not in {"derived", "worker_staging"}:
                raise ValueError(f"Output {artifact_id} kind must be derived or worker_staging.")
            if kind == "worker_staging":
                if executor != "worker":
                    raise ValueError(f"Only Worker-executed stages may declare worker_staging output {artifact_id}.")
                expected_prefix = ("worker_staging", stage_id)
                normalized = str(raw_path).replace("\\", "/") if isinstance(raw_path, str) else ""
                if tuple(PurePosixPath(normalized).parts[:2]) != expected_prefix:
                    raise ValueError(f"Worker output {artifact_id} must be under worker_staging/{stage_id}/.")
            elif executor == "worker":
                raise ValueError(f"Worker stage {stage_id} may write only to worker_staging/{stage_id}/, never approved derived paths.")
            if run_root is not None:
                path = _safe_relative_path(run_root, raw_path, f"Stage {stage_id} output {artifact_id}")
                normalized_path = str(path)
            else:
                if not isinstance(raw_path, str) or not raw_path.strip() or Path(raw_path).is_absolute() or PureWindowsPath(raw_path).drive:
                    raise ValueError(f"Stage {stage_id} output {artifact_id} path must be relative.")
                normalized_path = str(PurePosixPath(raw_path.replace("\\", "/")))
                if any(part in {"", ".", ".."} for part in PurePosixPath(normalized_path).parts):
                    raise ValueError(f"Stage {stage_id} output {artifact_id} has an unsafe path.")
            if normalized_path in output_paths:
                raise ValueError(f"Multiple output artifacts target the same path: {raw_path}.")
            output_paths.add(normalized_path)
            producer_by_artifact[artifact_id] = stage_id
            normalized_outputs.append({"artifact_id": artifact_id, "path": raw_path, "kind": kind})
        stages[stage_id] = {
            "stage_id": stage_id, "depends_on": list(dependencies), "required_gate": gate,
            "inputs": list(inputs), "outputs": normalized_outputs, "executor": executor,
            "worker_task": worker_task,
        }

    for stage_id, stage in stages.items():
        unknown = set(stage["depends_on"]) - set(stages)
        if unknown:
            raise ValueError(f"Stage {stage_id} depends on unknown stages: {', '.join(sorted(unknown))}.")
        for artifact_id in stage["inputs"]:
            if artifact_id not in artifacts and artifact_id not in producer_by_artifact:
                raise ValueError(f"Stage {stage_id} uses undeclared input artifact: {artifact_id}.")
            producer = producer_by_artifact.get(artifact_id)
            if producer is not None and producer not in stage["depends_on"]:
                raise ValueError(
                    f"Stage {stage_id} consumes {artifact_id} from {producer} but does not declare that direct dependency."
                )
    workflow_ledger = plan.get("workflow_ledger_path")
    if workflow_ledger is not None:
        if not isinstance(workflow_ledger, str) or not Path(workflow_ledger).expanduser().is_absolute():
            raise ValueError("workflow_ledger_path must be absolute when supplied.")
    # Topological order is explicit and deterministic; cycles fail closed.
    remaining = {key: set(value["depends_on"]) for key, value in stages.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError("Run plan stage dependency graph contains a cycle.")
        for key in ready:
            order.append(key)
            remaining.pop(key)
        for deps in remaining.values():
            deps.difference_update(ready)
    return order, artifacts, producer_by_artifact


def _initialization_snapshot(manifest: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "project_id", "created_at", "engine_version", "workspace_root",
        "plan_path", "plan_sha256", "event_ledger_path", "workflow_ledger_path",
        "source_roots", "source_artifacts", "stage_order", "integrity_scope",
    )
    return {key: manifest.get(key) for key in keys}


def _manifest_context(manifest_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = _read_json(manifest_path, "Run manifest")
    if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("Unsupported run manifest schema_version.")
    root = manifest_path.parent.resolve(strict=True)
    if manifest.get("workspace_root") != str(root):
        raise ValueError("Run manifest workspace_root does not match its containing directory.")
    plan_path = _safe_relative_path(root, manifest.get("plan_path"), "Run plan path")
    if not plan_path.is_file():
        raise ValueError(f"Bound run plan is missing: {plan_path}.")
    plan_hash = sha256_file(plan_path)
    if plan_hash != manifest.get("plan_sha256"):
        raise ValueError("Run plan SHA-256 differs from the immutable run-init snapshot.")
    plan = _read_json(plan_path, "Bound run plan")
    order, source_defs, producer_by_artifact = _validate_plan(plan, root)
    if plan.get("project_id") != manifest.get("project_id"):
        raise ValueError("Run manifest project_id differs from its bound run plan.")
    if manifest.get("plan_path") != "run_plan.json" or manifest.get("event_ledger_path") != "run_events.jsonl":
        raise ValueError("Run manifest plan/event-ledger paths must use the initialized in-workspace locations.")
    expected_roots = [str(Path(item).expanduser().resolve(strict=True)) for item in plan["source_roots"]]
    if manifest.get("source_roots") != expected_roots:
        raise ValueError("Run manifest source_roots differ from the bound run plan.")
    expected_workflow_ledger = plan.get("workflow_ledger_path")
    if expected_workflow_ledger:
        expected_workflow_ledger = str(Path(expected_workflow_ledger).expanduser().resolve(strict=False))
    if manifest.get("workflow_ledger_path") != expected_workflow_ledger:
        raise ValueError("Run manifest workflow_ledger_path differs from the bound run plan.")
    if manifest.get("stage_order") != order:
        raise ValueError("Run manifest stage_order differs from the bound dependency graph.")
    for item in manifest.get("source_artifacts", []):
        source_defs_item = source_defs.get(item.get("artifact_id"))
        if source_defs_item is None or source_defs_item["path"] != item.get("path"):
            raise ValueError("Run manifest source artifact definitions differ from the bound plan.")
    if len(manifest.get("source_artifacts", [])) != len(source_defs):
        raise ValueError("Run manifest source artifact set differs from the bound plan.")
    event_path = _safe_relative_path(root, manifest.get("event_ledger_path"), "Run event ledger path")
    events = _load_events(event_path, manifest["run_id"])
    if not events or events[0].get("initialization") != _initialization_snapshot(manifest):
        raise ValueError("Run manifest differs from its immutable RUN_INITIALIZED event snapshot.")
    _validate_event_semantics(events, _stage_map(plan), root, plan)
    return root, manifest, plan, events


def _load_events(event_path: Path, run_id: str) -> list[dict[str, Any]]:
    if not event_path.exists():
        return []
    events: list[dict[str, Any]] = []
    previous = EVENT_GENESIS_HASH
    with event_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank line in run event ledger at line {line_number}.")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid run event JSON at line {line_number}: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Run event at line {line_number} must be a JSON object.")
            supplied = event.get("event_hash")
            payload = {key: value for key, value in event.items() if key != "event_hash"}
            if supplied != _hash_payload(payload):
                raise ValueError(f"Run event hash mismatch at line {line_number}.")
            if event.get("sequence") != line_number or event.get("previous_event_hash") != previous:
                raise ValueError(f"Run event sequence/hash-chain mismatch at line {line_number}.")
            if event.get("run_id") != run_id:
                raise ValueError(f"Run event at line {line_number} belongs to another run.")
            event_type = event.get("event_type")
            if event_type not in {"RUN_INITIALIZED", "WORKER_AUTHORIZED", "STAGE_STATUS"}:
                raise ValueError(f"Unsupported run event type at line {line_number}.")
            if event_type == "RUN_INITIALIZED":
                if line_number != 1 or "stage_id" in event:
                    raise ValueError("RUN_INITIALIZED must be the first event and cannot name a stage.")
            else:
                stage_id = event.get("stage_id")
                if not isinstance(stage_id, str) or not _STAGE_ID.fullmatch(stage_id):
                    raise ValueError(f"Invalid run event stage_id at line {line_number}.")
            if event_type == "STAGE_STATUS" and event.get("status") not in _STAGE_STATUSES:
                raise ValueError(f"Invalid stage status at line {line_number}.")
            if line_number == 1 and event_type != "RUN_INITIALIZED":
                raise ValueError("Run event ledger must begin with RUN_INITIALIZED.")
            if line_number > 1 and event_type == "RUN_INITIALIZED":
                raise ValueError("Run event ledger cannot contain more than one RUN_INITIALIZED event.")
            events.append(event)
            previous = supplied
    return events



def _validate_event_semantics(
    events: list[dict[str, Any]], stages: Mapping[str, Mapping[str, Any]],
    root: Path, plan: Mapping[str, Any],
) -> None:
    latest_status: dict[str, dict[str, Any]] = {}
    definitions, _ = _artifact_definitions(plan)

    def validate_snapshots(items: Any, artifact_ids: list[str], label: str, line_number: int) -> None:
        if not isinstance(items, list) or len(items) != len(artifact_ids):
            raise ValueError(f"{label} artifact list is incomplete at line {line_number}.")
        for item, artifact_id in zip(items, artifact_ids):
            if not isinstance(item, dict) or item.get("artifact_id") != artifact_id:
                raise ValueError(f"{label} artifact IDs/order differ from the run plan at line {line_number}.")
            expected_path = str(_artifact_path(root, definitions[artifact_id]))
            if item.get("path") != expected_path:
                raise ValueError(f"{label} path differs from the run plan for {artifact_id} at line {line_number}.")
            digest = item.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError(f"{label} SHA-256 is malformed for {artifact_id} at line {line_number}.")

    def validate_gate_snapshot(event: Mapping[str, Any], stage: Mapping[str, Any], line_number: int) -> None:
        required = stage.get("required_gate")
        snapshot = event.get("gate_approval")
        if required is None:
            if snapshot is not None:
                raise ValueError(f"Unexpected gate approval snapshot for ungated stage at line {line_number}.")
            return
        if (not isinstance(snapshot, dict) or snapshot.get("gate_id") != required
                or snapshot.get("status") != "APPROVED"
                or not isinstance(snapshot.get("event_hash"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", snapshot["event_hash"])):
            raise ValueError(f"Stage lacks an exact current {required} approval snapshot at line {line_number}.")
    authorization_by_stage_attempt: dict[tuple[str, int], dict[str, Any]] = {}
    if not events or events[0].get("event_type") != "RUN_INITIALIZED":
        raise ValueError("Run event ledger must begin with RUN_INITIALIZED.")
    for line_number, event in enumerate(events, start=1):
        if event["event_type"] == "RUN_INITIALIZED":
            if line_number != 1:
                raise ValueError("RUN_INITIALIZED may appear only as the first event.")
            continue
        stage_id = event["stage_id"]
        stage = stages.get(stage_id)
        if stage is None:
            raise ValueError(f"Run event at line {line_number} references unknown stage {stage_id}.")
        latest = latest_status.get(stage_id)
        expected_attempt = (latest.get("attempt", 0) if latest else 0) + 1
        if event["event_type"] == "WORKER_AUTHORIZED":
            if stage["executor"] != "worker":
                raise ValueError(f"Run event at line {line_number} authorizes a non-Worker stage.")
            if event.get("attempt") != expected_attempt:
                raise ValueError(f"Worker authorization attempt mismatch at line {line_number}.")
            worker = event.get("worker")
            if not isinstance(worker, dict) or not all(
                isinstance(worker.get(key), str) and worker[key].strip()
                for key in ("role", "provider", "model", "project_root")
            ):
                raise ValueError(f"Worker authorization metadata is incomplete at line {line_number}.")
            if not isinstance(event.get("authorized_by"), str) or not event["authorized_by"].strip():
                raise ValueError(f"Worker authorization lacks authorized_by at line {line_number}.")
            if not isinstance(event.get("rationale"), str) or not event["rationale"].strip():
                raise ValueError(f"Worker authorization lacks rationale at line {line_number}.")
            if event.get("task_spec") != stage.get("worker_task"):
                raise ValueError(f"Worker authorization task specification differs from the run plan at line {line_number}.")
            validate_snapshots(event.get("input_artifacts"), stage["inputs"], "Worker authorization inputs", line_number)
            expected_outputs = [
                {"artifact_id": item["artifact_id"], "path": str(_artifact_path(root, item)), "kind": item["kind"]}
                for item in stage["outputs"]
            ]
            if event.get("permitted_outputs") != expected_outputs:
                raise ValueError(f"Worker permitted outputs differ from the run plan at line {line_number}.")
            validate_gate_snapshot(event, stage, line_number)
            key = (stage_id, event["attempt"])
            if key in authorization_by_stage_attempt:
                raise ValueError(f"Duplicate Worker authorization for the same attempt at line {line_number}.")
            authorization_by_stage_attempt[key] = event
            continue
        status = event["status"]
        if status == "RUNNING":
            if event.get("attempt") != expected_attempt:
                raise ValueError(f"Stage attempt number mismatch at line {line_number}.")
            producer = event.get("producer")
            if not isinstance(producer, dict) or producer.get("kind") != stage["executor"]:
                raise ValueError(f"Stage producer does not match its plan at line {line_number}.")
            validate_snapshots(event.get("input_artifacts"), stage["inputs"], "Stage inputs", line_number)
            if event.get("output_artifacts") != []:
                raise ValueError(f"RUNNING event must not claim completed outputs at line {line_number}.")
            validate_gate_snapshot(event, stage, line_number)
            if latest is not None and latest.get("status") == "RUNNING" and event.get("confirmed_abandoned") is not True:
                raise ValueError(f"Replacement RUNNING event lacks abandoned-process confirmation at line {line_number}.")
            if stage["executor"] == "worker":
                authorization = authorization_by_stage_attempt.get((stage_id, event["attempt"]))
                if authorization is None:
                    raise ValueError(f"Worker stage RUNNING event has no preceding authorization at line {line_number}.")
                if authorization.get("input_artifacts") != event.get("input_artifacts"):
                    raise ValueError(f"Worker stage input snapshot differs from its authorization at line {line_number}.")
                for key in ("role", "provider", "model", "project_root"):
                    if producer.get(key) != authorization["worker"].get(key):
                        raise ValueError(f"Worker stage identity differs from its authorization at line {line_number}.")
                if event.get("gate_approval") != authorization.get("gate_approval"):
                    raise ValueError(f"Worker stage gate snapshot differs from its authorization at line {line_number}.")
        else:
            if status == "FAILED" and (not isinstance(event.get("reason"), str) or not event["reason"].strip()):
                raise ValueError(f"FAILED stage event lacks a non-empty reason at line {line_number}.")
            if latest is None or latest.get("status") != "RUNNING" or latest.get("attempt") != event.get("attempt"):
                raise ValueError(f"Stage {status} event has no matching RUNNING attempt at line {line_number}.")
            if event.get("input_artifacts") != latest.get("input_artifacts"):
                raise ValueError(f"Stage completion input snapshot differs from its RUNNING event at line {line_number}.")
            if event.get("gate_approval") != latest.get("gate_approval"):
                raise ValueError(f"Stage completion gate snapshot differs from its RUNNING event at line {line_number}.")
            if status == "SUCCEEDED":
                validate_snapshots(
                    event.get("output_artifacts"),
                    [item["artifact_id"] for item in stage["outputs"]],
                    "Stage outputs", line_number,
                )
            else:
                allowed_outputs = {item["artifact_id"] for item in stage["outputs"]}
                output_items = event.get("output_artifacts")
                if not isinstance(output_items, list) or any(
                    not isinstance(item, dict) or item.get("artifact_id") not in allowed_outputs
                    for item in output_items
                ) or len({item["artifact_id"] for item in output_items}) != len(output_items):
                    raise ValueError(f"FAILED event output list is invalid at line {line_number}.")
                for item in output_items:
                    validate_snapshots([item], [item["artifact_id"]], "Failed-stage outputs", line_number)
            started_producer = latest.get("producer", {})
            completed_producer = event.get("producer", {})
            for key, value in started_producer.items():
                if completed_producer.get(key) != value:
                    raise ValueError(f"Stage completion changed producer field {key} at line {line_number}.")
            late_fields = {
                "job_id", "session_id", "task_id", "input_tokens", "output_tokens",
                "reasoning_tokens", "cache_read_tokens", "cache_write_tokens",
            }
            if set(completed_producer) - set(started_producer) - late_fields:
                raise ValueError(f"Stage completion added an unsupported producer field at line {line_number}.")
        latest_status[stage_id] = event


def _append_event(
    event_path: Path, run_id: str, event_payload: dict[str, Any],
    expected_previous_event_hash: str,
) -> dict[str, Any]:
    lock_path = event_path.with_name(event_path.name + ".lock")
    with _exclusive_lock(lock_path):
        events = _load_events(event_path, run_id)
        actual_previous_event_hash = events[-1]["event_hash"] if events else EVENT_GENESIS_HASH
        if actual_previous_event_hash != expected_previous_event_hash:
            raise ValueError("Run event ledger changed concurrently; reload run status and retry from the current state.")
        payload = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "sequence": len(events) + 1,
            "recorded_at": _now(),
            "previous_event_hash": events[-1]["event_hash"] if events else EVENT_GENESIS_HASH,
            **event_payload,
        }
        event = {**payload, "event_hash": _hash_payload(payload)}
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("ab") as handle:
            handle.write((_canonical_json(event) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    return event


def _stage_map(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {stage["stage_id"]: stage for stage in plan["stages"]}


def _latest_stage_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["event_type"] == "STAGE_STATUS":
            latest[event["stage_id"]] = event
    return latest


def _latest_worker_authorization(events: list[dict[str, Any]], stage_id: str, attempt: int) -> dict[str, Any] | None:
    for event in reversed(events):
        if event["event_type"] == "WORKER_AUTHORIZED" and event["stage_id"] == stage_id and event.get("attempt") == attempt:
            return event
    return None


def _artifact_definitions(plan: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    definitions: dict[str, dict[str, Any]] = {}
    producers: dict[str, str] = {}
    for item in plan["source_artifacts"]:
        definitions[item["artifact_id"]] = {"artifact_id": item["artifact_id"], "path": item["path"], "kind": "source"}
    for stage in plan["stages"]:
        for output in stage["outputs"]:
            definitions[output["artifact_id"]] = output
            producers[output["artifact_id"]] = stage["stage_id"]
    return definitions, producers


def _artifact_path(root: Path, definition: Mapping[str, Any]) -> Path:
    if definition.get("kind") == "source":
        return Path(definition["path"]).expanduser().resolve(strict=False)
    return _safe_relative_path(root, definition["path"], f"Artifact {definition['artifact_id']} path")


def _snapshot_artifacts(root: Path, manifest: Mapping[str, Any], plan: Mapping[str, Any],
                        artifact_ids: list[str]) -> list[dict[str, str]]:
    definitions, _ = _artifact_definitions(plan)
    source_hashes = {item["artifact_id"]: item["sha256"] for item in manifest["source_artifacts"]}
    snapshots = []
    for artifact_id in artifact_ids:
        definition = definitions[artifact_id]
        path = _artifact_path(root, definition)
        if not path.is_file():
            raise ValueError(f"Required artifact {artifact_id} is missing: {path}.")
        digest = sha256_file(path)
        if definition.get("kind", "derived") == "source" and digest != source_hashes[artifact_id]:
            raise ValueError(f"Protected source artifact {artifact_id} changed after run initialization; create a new run.")
        snapshots.append({"artifact_id": artifact_id, "path": str(path), "sha256": digest})
    return snapshots


def _gate_status(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    ledger = manifest.get("workflow_ledger_path")
    if not ledger:
        return None
    path = Path(ledger)
    if not path.exists():
        return None
    return inspect_gate_ledger(path)


def _gate_approval(stage: Mapping[str, Any], gate_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    required = stage.get("required_gate")
    if required is None:
        return None
    gate = gate_snapshot.get("gates", {}).get(required, {}) if gate_snapshot else {}
    return {
        "gate_id": required,
        "status": gate.get("status", "NOT_AVAILABLE"),
        "event_hash": gate.get("event_hash"),
    }


def _required_gate_is_current(stage: Mapping[str, Any], gate_snapshot: dict[str, Any] | None) -> bool:
    if stage.get("required_gate") is None:
        return True
    return bool(gate_snapshot and gate_snapshot.get("valid_ledger")
                and _gate_approval(stage, gate_snapshot).get("status") == "APPROVED")


def _resume_plan(root: Path, manifest: dict[str, Any], plan: dict[str, Any],
                 events: list[dict[str, Any]]) -> dict[str, Any]:
    order, _, _ = _validate_plan(plan, root)
    stages = _stage_map(plan)
    latest = _latest_stage_events(events)
    gate_snapshot = _gate_status(manifest)
    actions: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    for stage_id in order:
        stage = stages[stage_id]
        dependencies = stage["depends_on"]
        dependency_actions = [actions[item] for item in dependencies]
        current_event = latest.get(stage_id)
        reasons: list[str] = []
        source_hashes = {item["artifact_id"]: item["sha256"] for item in manifest["source_artifacts"]}
        changed_source_inputs = []
        for artifact_id in stage["inputs"]:
            definition = next((item for item in manifest["source_artifacts"] if item["artifact_id"] == artifact_id), None)
            if definition is None:
                continue
            path = Path(definition["path"])
            try:
                actual = sha256_file(path) if path.is_file() else None
            except OSError:
                actual = None
            if actual != source_hashes[artifact_id]:
                changed_source_inputs.append(artifact_id)
        if current_event is not None and current_event["status"] == "RUNNING":
            action = "RUNNING_NEEDS_RECONCILIATION"
            reasons.append("A prior attempt was recorded as RUNNING; inspect the external process before recording another attempt.")
        elif changed_source_inputs:
            action = "SOURCE_CHANGED_NEW_RUN_REQUIRED"
            reasons.append("Protected source inputs changed: " + ", ".join(changed_source_inputs) + ". Initialize a new run.")
        elif any(item != "REUSE" for item in dependency_actions):
            action = "INVALIDATED_BY_UPSTREAM" if current_event and current_event.get("status") == "SUCCEEDED" else "WAITING_FOR_DEPENDENCIES"
            reasons.append("One or more declared dependencies are not currently reusable.")
        elif not _required_gate_is_current(stage, gate_snapshot):
            action = "BLOCKED_GATE"
            reasons.append(f"Required gate {stage.get('required_gate')} is not currently approved.")
        elif current_event is None:
            action = "READY_TO_RUN"
        elif current_event["status"] == "FAILED":
            action = "RETRY_REQUIRED"
            reasons.append(current_event.get("reason") or "The prior attempt failed.")
        else:
            current_gate_approval = _gate_approval(stage, gate_snapshot)
            if current_event.get("gate_approval") != current_gate_approval:
                reasons.append("Required approval gate decision changed since this stage attempt.")
            definitions, _ = _artifact_definitions(plan)
            source_hashes = {item["artifact_id"]: item["sha256"] for item in manifest["source_artifacts"]}
            recorded_inputs = {item["artifact_id"]: item for item in current_event.get("input_artifacts", [])}
            recorded_outputs = {item["artifact_id"]: item for item in current_event.get("output_artifacts", [])}
            for artifact_id in stage["inputs"]:
                definition = definitions[artifact_id]
                path = _artifact_path(root, definition)
                expected = recorded_inputs.get(artifact_id, {}).get("sha256")
                try:
                    actual = sha256_file(path) if path.is_file() else None
                except OSError:
                    actual = None
                if definition.get("kind", "derived") == "source" and actual != source_hashes.get(artifact_id):
                    reasons.append(f"Protected source changed: {artifact_id}.")
                if actual is None or actual != expected:
                    reasons.append(f"Input artifact changed or missing: {artifact_id}.")
            for output in stage["outputs"]:
                path = _artifact_path(root, output)
                expected = recorded_outputs.get(output["artifact_id"], {}).get("sha256")
                try:
                    actual = sha256_file(path) if path.is_file() else None
                except OSError:
                    actual = None
                if actual is None or actual != expected:
                    reasons.append(f"Output artifact changed or missing: {output['artifact_id']}.")
            action = "REBUILD_REQUIRED" if reasons else "REUSE"
        actions[stage_id] = action
        details[stage_id] = {
            "stage_id": stage_id,
            "status": current_event.get("status") if current_event else "NOT_STARTED",
            "attempt": current_event.get("attempt", 0) if current_event else 0,
            "action": action,
            "dependencies": dependencies,
            "required_gate": stage.get("required_gate"),
            "reasons": reasons,
            "last_event_hash": current_event.get("event_hash") if current_event else None,
        }
    reusable = sum(1 for value in actions.values() if value == "REUSE")
    ready = sum(1 for value in actions.values() if value == "READY_TO_RUN")
    rebuild = sum(1 for value in actions.values() if value in {"REBUILD_REQUIRED", "RETRY_REQUIRED", "INVALIDATED_BY_UPSTREAM"})
    blocked_source = sum(1 for value in actions.values() if value == "SOURCE_CHANGED_NEW_RUN_REQUIRED")
    return {
        "run_id": manifest["run_id"],
        "project_id": manifest["project_id"],
        "workspace_root": str(root),
        "stage_count": len(order),
        "reuse_count": reusable,
        "ready_to_run_count": ready,
        "rebuild_or_retry_count": rebuild,
        "source_changed_block_count": blocked_source,
        "stages": [details[stage_id] for stage_id in order],
        "execution_policy": "PLAN_ONLY_NO_COMMANDS_OR_WORKERS_ARE_STARTED_AND_NO_GATE_DECISIONS_ARE_CREATED",
    }


def initialize_run(plan_path: Path, run_root: Path, run_id: str | None = None) -> dict[str, Any]:
    source_plan_path = plan_path.expanduser().resolve(strict=True)
    plan = _read_json(source_plan_path, "Run plan")
    run_root = run_root.expanduser().resolve(strict=False)
    _validate_plan(plan, run_root)
    if run_id is None:
        run_id = "RUN_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    if not _STAGE_ID.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, numbers, dot, underscore, or hyphen.")
    if run_root.exists():
        if not run_root.is_dir() or any(run_root.iterdir()):
            raise FileExistsError(f"Run workspace must be new or empty; refusing to overwrite: {run_root}.")
    else:
        run_root.mkdir(parents=True, exist_ok=False)
    plan_bytes = source_plan_path.read_bytes()
    plan_copy = run_root / "run_plan.json"
    plan_copy.write_bytes(plan_bytes)
    source_artifacts = []
    for item in plan["source_artifacts"]:
        path = Path(item["path"]).expanduser().resolve(strict=True)
        source_artifacts.append({
            "artifact_id": item["artifact_id"], "path": str(path), "sha256": sha256_file(path),
        })
    workflow_ledger = plan.get("workflow_ledger_path")
    if workflow_ledger:
        workflow_ledger = str(Path(workflow_ledger).expanduser().resolve(strict=False))
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": plan["project_id"],
        "created_at": _now(),
        "engine_version": "0.1.0",
        "workspace_root": str(run_root),
        "plan_path": "run_plan.json",
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "event_ledger_path": "run_events.jsonl",
        "workflow_ledger_path": workflow_ledger,
        "source_roots": [str(Path(item).expanduser().resolve(strict=True)) for item in plan["source_roots"]],
        "source_artifacts": source_artifacts,
        "stage_order": _validate_plan(plan, run_root)[0],
        "integrity_scope": "INITIALIZATION_EVENT_BINDS_PLAN_AND_SOURCE_SNAPSHOTS_PLUS_APPEND_ONLY_EVENT_CHAIN_NOT_USER_AUTHENTICATION",
    }
    _write_json_atomic(run_root / "run_manifest.json", manifest)
    initialization_payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "sequence": 1,
        "recorded_at": manifest["created_at"],
        "previous_event_hash": EVENT_GENESIS_HASH,
        "event_type": "RUN_INITIALIZED",
        "initialization": _initialization_snapshot(manifest),
    }
    initialization_event = {
        **initialization_payload,
        "event_hash": _hash_payload(initialization_payload),
    }
    (run_root / "run_events.jsonl").write_text(
        _canonical_json(initialization_event) + "\n", encoding="utf-8",
    )
    return {
        "status": "initialized",
        "run_id": run_id,
        "project_id": plan["project_id"],
        "workspace_root": str(run_root),
        "manifest_path": str(run_root / "run_manifest.json"),
        "event_ledger_path": str(run_root / "run_events.jsonl"),
        "stage_order": manifest["stage_order"],
        "plan_sha256": manifest["plan_sha256"],
    }


def verify_run(manifest_path: Path) -> dict[str, Any]:
    root, manifest, plan, events = _manifest_context(manifest_path)
    source_status = []
    for item in manifest["source_artifacts"]:
        path = Path(item["path"])
        try:
            actual = sha256_file(path) if path.is_file() else None
        except OSError:
            actual = None
        source_status.append({
            "artifact_id": item["artifact_id"], "path": item["path"],
            "expected_sha256": item["sha256"], "actual_sha256": actual,
            "status": "CURRENT" if actual == item["sha256"] else "STALE_OR_MISSING",
        })
    resume = _resume_plan(root, manifest, plan, events)
    artifact_manifest = _artifact_manifest(root, manifest, plan, events)
    return {
        "valid_manifest_and_event_chain": True,
        "run_id": manifest["run_id"],
        "project_id": manifest["project_id"],
        "workspace_root": str(root),
        "plan_sha256": manifest["plan_sha256"],
        "event_count": len(events),
        "last_event_hash": events[-1]["event_hash"] if events else EVENT_GENESIS_HASH,
        "source_artifacts": source_status,
        "source_integrity": "CURRENT" if all(item["status"] == "CURRENT" for item in source_status) else "SOURCE_CHANGED_NEW_RUN_REQUIRED",
        "artifact_manifest": artifact_manifest,
        "resume_plan": resume,
    }


def build_resume_plan(manifest_path: Path) -> dict[str, Any]:
    root, manifest, plan, events = _manifest_context(manifest_path)
    return _resume_plan(root, manifest, plan, events)



def _artifact_manifest(root: Path, manifest: dict[str, Any], plan: dict[str, Any],
                       events: list[dict[str, Any]]) -> dict[str, Any]:
    latest_success: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["event_type"] == "STAGE_STATUS" and event["status"] == "SUCCEEDED":
            latest_success[event["stage_id"]] = event
    definitions, producers = _artifact_definitions(plan)
    successful_outputs: dict[str, dict[str, Any]] = {}
    latest_status = _latest_stage_events(events)
    resume_actions = {
        item["stage_id"]: item["action"]
        for item in _resume_plan(root, manifest, plan, events)["stages"]
    }
    for stage_id, event in latest_success.items():
        for output in event.get("output_artifacts", []):
            successful_outputs[output["artifact_id"]] = {
                **output, "producer_stage_id": stage_id,
                "attempt": event["attempt"], "event_hash": event["event_hash"],
            }

    artifacts: list[dict[str, Any]] = []
    for source in manifest["source_artifacts"]:
        path = Path(source["path"])
        try:
            actual = sha256_file(path) if path.is_file() else None
        except OSError:
            actual = None
        state = "CURRENT" if actual == source["sha256"] else "SOURCE_CHANGED_OR_MISSING"
        artifacts.append({
            "artifact_id": source["artifact_id"], "kind": "source",
            "producer_stage_id": None, "path": source["path"],
            "expected_sha256": source["sha256"], "actual_sha256": actual,
            "last_successful_attempt": None, "producer_event_hash": None,
            "status": state,
        })

    for stage_id in manifest["stage_order"]:
        stage = _stage_map(plan)[stage_id]
        for output in stage["outputs"]:
            path = _artifact_path(root, output)
            try:
                actual = sha256_file(path) if path.is_file() else None
            except OSError:
                actual = None
            recorded = successful_outputs.get(output["artifact_id"])
            expected = recorded.get("sha256") if recorded else None
            if recorded is None:
                state = "PRESENT_UNRECORDED" if actual is not None else "NOT_CREATED"
            elif latest_status.get(stage_id, {}).get("status") != "SUCCEEDED" or resume_actions.get(stage_id) != "REUSE":
                state = "STALE_OR_MISSING"
            else:
                state = "CURRENT" if actual == expected else "STALE_OR_MISSING"
            artifacts.append({
                "artifact_id": output["artifact_id"], "kind": output.get("kind", "derived"),
                "producer_stage_id": producers[output["artifact_id"]],
                "path": str(path), "expected_sha256": expected,
                "actual_sha256": actual,
                "last_successful_attempt": recorded.get("attempt") if recorded else None,
                "producer_event_hash": recorded.get("event_hash") if recorded else None,
                "status": state,
            })

    counts: dict[str, int] = {}
    for item in artifacts:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    source_states = [item["status"] for item in artifacts if item["kind"] == "source"]
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "project_id": manifest["project_id"],
        "workspace_root": str(root),
        "source_roots": list(manifest["source_roots"]),
        "generated_at": _now(),
        "event_count": len(events),
        "last_event_hash": events[-1]["event_hash"] if events else EVENT_GENESIS_HASH,
        "artifact_count": len(artifacts),
        "status_counts": counts,
        "source_integrity": "CURRENT" if all(item == "CURRENT" for item in source_states) else "SOURCE_CHANGED_NEW_RUN_REQUIRED",
        "artifacts": artifacts,
        "source_of_truth": "RUN_PLAN_SOURCE_SNAPSHOTS_AND_HASH_CHAINED_RUN_EVENTS; THIS_MANIFEST_IS_A_REGENERABLE_VIEW",
    }


def build_artifact_manifest(manifest_path: Path) -> dict[str, Any]:
    root, manifest, plan, events = _manifest_context(manifest_path)
    return _artifact_manifest(root, manifest, plan, events)


def _stage_input_snapshots(root: Path, manifest: dict[str, Any], plan: dict[str, Any],
                           stage: dict[str, Any]) -> list[dict[str, str]]:
    definitions, _ = _artifact_definitions(plan)
    return _snapshot_artifacts(root, manifest, plan, stage["inputs"])


def _check_gate(stage: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    required = stage.get("required_gate")
    if required is None:
        return None
    snapshot = _gate_status(manifest)
    approval = _gate_approval(stage, snapshot)
    if not snapshot or not snapshot.get("valid_ledger") or approval.get("status") != "APPROVED":
        raise ValueError(f"Stage requires a currently approved {required} gate; no approval was created.")
    return approval


def authorize_worker(
    manifest_path: Path, stage_id: str, role: str, provider: str, model: str,
    project_root: Path, authorized_by: str, rationale: str,
    confirm_abandoned: bool = False,
) -> dict[str, Any]:
    root, manifest, plan, events = _manifest_context(manifest_path)
    stages = _stage_map(plan)
    stage = stages.get(stage_id)
    if stage is None:
        raise ValueError(f"Unknown stage_id: {stage_id}.")
    if stage["executor"] != "worker":
        raise ValueError(f"Stage {stage_id} is not declared as Worker-executed.")
    if not all(isinstance(item, str) and item.strip() for item in (role, provider, model, authorized_by, rationale)):
        raise ValueError("Worker role, provider, model, authorizer, and rationale must be non-empty.")
    project = project_root.expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Worker project_root must be an existing directory.")
    resume = _resume_plan(root, manifest, plan, events)
    state = next(item for item in resume["stages"] if item["stage_id"] == stage_id)
    allowed_actions = {"READY_TO_RUN", "RETRY_REQUIRED", "REBUILD_REQUIRED"}
    if confirm_abandoned:
        allowed_actions.add("RUNNING_NEEDS_RECONCILIATION")
    if state["action"] not in allowed_actions:
        raise ValueError(f"Worker stage is not ready for authorization (action={state['action']}).")
    gate_approval = _check_gate(stage, manifest)
    input_artifacts = _stage_input_snapshots(root, manifest, plan, stage)
    permitted_outputs = []
    for output in stage["outputs"]:
        path = _artifact_path(root, output)
        if path.exists():
            raise FileExistsError(f"Worker staging output already exists; refusing overwrite: {path}.")
        permitted_outputs.append({"artifact_id": output["artifact_id"], "path": str(path), "kind": output["kind"]})
    latest = _latest_stage_events(events).get(stage_id)
    attempt = (latest.get("attempt", 0) if latest else 0) + 1
    if _latest_worker_authorization(events, stage_id, attempt) is not None:
        raise ValueError("A Worker authorization packet already exists for this attempt; do not silently re-authorize or duplicate dispatch.")
    payload = {
        "event_type": "WORKER_AUTHORIZED",
        "stage_id": stage_id,
        "attempt": attempt,
        "authorized_by": authorized_by.strip(),
        "rationale": rationale.strip(),
        "worker": {
            "role": role.strip(), "provider": provider.strip(), "model": model.strip(),
            "project_root": str(project),
        },
        "input_artifacts": input_artifacts,
        "permitted_outputs": permitted_outputs,
        "task_spec": stage["worker_task"],
        "gate_approval": gate_approval,
    }
    expected_previous_event_hash = events[-1]["event_hash"] if events else EVENT_GENESIS_HASH
    event = _append_event(
        root / manifest["event_ledger_path"], manifest["run_id"], payload,
        expected_previous_event_hash,
    )
    return {
        "status": "worker_dispatch_authorized",
        "run_id": manifest["run_id"],
        "stage_id": stage_id,
        "attempt": attempt,
        "authorization_event_hash": event["event_hash"],
        "authorized_by": authorized_by.strip(),
        "worker": payload["worker"],
        "task_packet": {
            "project_id": manifest["project_id"],
            "run_id": manifest["run_id"],
            "stage_id": stage_id,
            "role": role.strip(),
            "provider": provider.strip(),
            "model": model.strip(),
            "project_root": str(project),
            "inputs": input_artifacts,
            "permitted_outputs": permitted_outputs,
            "objective": stage["worker_task"]["objective"],
            "permitted_actions": stage["worker_task"]["permitted_actions"],
            "forbidden_actions": stage["worker_task"].get("forbidden_actions", []),
            "max_context_tokens": stage["worker_task"].get("max_context_tokens"),
            "max_output_tokens": stage["worker_task"].get("max_output_tokens"),
            "constraints": [
                "Read declared inputs only; do not crawl the workspace.",
                "Do not modify source files, run manifests, event ledgers, workflow approval ledgers, or approved scientific artifacts.",
                "Write new outputs only to the listed worker_staging paths; never overwrite an existing file.",
                "Return job/session identifiers and token usage only when actually reported by the Worker Manager.",
                "Worker completion is not a scientific approval; a human must review and promote any accepted result separately.",
            ],
        },
    }


def record_stage_status(
    manifest_path: Path, stage_id: str, status: str, producer_kind: str,
    command: str | None = None, role: str | None = None, provider: str | None = None,
    model: str | None = None, project_root: str | None = None, job_id: str | None = None,
    session_id: str | None = None, task_id: str | None = None,
    input_tokens: int | None = None, output_tokens: int | None = None,
    reasoning_tokens: int | None = None, cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None, reason: str | None = None,
    confirm_abandoned: bool = False,
) -> dict[str, Any]:
    if status not in _STAGE_STATUSES:
        raise ValueError("Stage status must be RUNNING, SUCCEEDED, or FAILED.")
    if producer_kind not in _PRODUCER_KINDS:
        raise ValueError("producer_kind must be local, worker, or manual.")
    for value, label in ((input_tokens, "input_tokens"), (output_tokens, "output_tokens"),
                         (reasoning_tokens, "reasoning_tokens"), (cache_read_tokens, "cache_read_tokens"),
                         (cache_write_tokens, "cache_write_tokens")):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError(f"{label} must be a non-negative integer when supplied.")
    root, manifest, plan, events = _manifest_context(manifest_path)
    stage = _stage_map(plan).get(stage_id)
    if stage is None:
        raise ValueError(f"Unknown stage_id: {stage_id}.")
    if stage["executor"] != producer_kind:
        raise ValueError(f"Stage {stage_id} executor is {stage['executor']}, not {producer_kind}.")
    latest = _latest_stage_events(events).get(stage_id)
    producer = {
        key: value for key, value in {
            "kind": producer_kind, "command": command, "role": role, "provider": provider,
            "model": model, "project_root": project_root, "job_id": job_id,
            "session_id": session_id, "task_id": task_id, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "reasoning_tokens": reasoning_tokens,
            "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens,
        }.items() if value is not None
    }
    if status == "RUNNING":
        resume = _resume_plan(root, manifest, plan, events)
        state = next(item for item in resume["stages"] if item["stage_id"] == stage_id)
        allowed = {"READY_TO_RUN", "RETRY_REQUIRED", "REBUILD_REQUIRED"}
        if state["action"] == "RUNNING_NEEDS_RECONCILIATION" and confirm_abandoned:
            allowed.add("RUNNING_NEEDS_RECONCILIATION")
        if state["action"] not in allowed:
            raise ValueError(f"Stage cannot start a new attempt (action={state['action']}).")
        gate_approval = _check_gate(stage, manifest)
        input_snapshots = _stage_input_snapshots(root, manifest, plan, stage)
        attempt = (latest.get("attempt", 0) if latest else 0) + 1
        for output in stage["outputs"]:
            output_path = _artifact_path(root, output)
            if output_path.exists():
                raise FileExistsError(
                    f"Refusing to overwrite an existing stage output: {output_path}. "
                    "Archive/remove the old attempt output explicitly or initialize a revised run plan."
                )
        if producer_kind == "worker":
            auth = _latest_worker_authorization(events, stage_id, attempt)
            if auth is None:
                raise ValueError("Worker stage requires a matching run-worker-authorize event before dispatch.")
            worker = auth["worker"]
            for key, value in (("role", role), ("provider", provider), ("model", model), ("project_root", project_root)):
                if not isinstance(value, str) or value != worker[key]:
                    raise ValueError(f"Worker {key} must exactly match the preceding authorization packet.")
            if auth["input_artifacts"] != input_snapshots:
                raise ValueError("Worker authorization inputs changed; request a new authorization packet.")
            for output in stage["outputs"]:
                path = _artifact_path(root, output)
                if path.exists():
                    raise FileExistsError(f"Worker staging output already exists; refusing overwrite: {path}.")
        event_payload = {
            "event_type": "STAGE_STATUS", "stage_id": stage_id, "status": "RUNNING",
            "attempt": attempt, "producer": producer, "input_artifacts": input_snapshots,
            "output_artifacts": [], "reason": None,
            "gate_approval": gate_approval,
            "confirmed_abandoned": bool(confirm_abandoned and latest is not None and latest.get("status") == "RUNNING"),
        }
    else:
        if latest is None or latest.get("status") != "RUNNING":
            raise ValueError(f"Stage {stage_id} can be completed only after a recorded RUNNING event.")
        if latest.get("producer", {}).get("kind") != producer_kind:
            raise ValueError("Stage completion producer_kind differs from the RUNNING event.")
        completed_producer = dict(latest["producer"])
        for key, value in producer.items():
            if value is None:
                continue
            if key in {"kind", "role", "provider", "model", "project_root"} and key in completed_producer and value != completed_producer[key]:
                raise ValueError(f"Stage completion cannot change producer identity field {key}.")
            completed_producer[key] = value
        if status == "FAILED":
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("FAILED stage status requires a non-empty reason.")
            outputs = []
            for output in stage["outputs"]:
                path = _artifact_path(root, output)
                if path.is_file():
                    outputs.append({"artifact_id": output["artifact_id"], "path": str(path), "sha256": sha256_file(path)})
            event_payload = {
                "event_type": "STAGE_STATUS", "stage_id": stage_id, "status": "FAILED",
                "attempt": latest["attempt"], "producer": completed_producer,
                "input_artifacts": latest["input_artifacts"], "output_artifacts": outputs,
                "gate_approval": latest.get("gate_approval"),
                "reason": reason.strip(),
            }
        else:
            current_inputs = _stage_input_snapshots(root, manifest, plan, stage)
            if current_inputs != latest.get("input_artifacts"):
                raise ValueError("Stage inputs changed while the stage was running; completion is rejected.")
            output_snapshots = _snapshot_artifacts(root, manifest, plan, [item["artifact_id"] for item in stage["outputs"]])
            for output in stage["outputs"]:
                if output.get("kind", "derived") == "worker_staging" and latest["producer"]["kind"] != "worker":
                    raise ValueError("Only the Worker may create worker_staging outputs.")
            event_payload = {
                "event_type": "STAGE_STATUS", "stage_id": stage_id, "status": "SUCCEEDED",
                "attempt": latest["attempt"], "producer": completed_producer,
                "input_artifacts": latest["input_artifacts"], "output_artifacts": output_snapshots,
                "gate_approval": latest.get("gate_approval"),
                "reason": None,
            }
    expected_previous_event_hash = events[-1]["event_hash"] if events else EVENT_GENESIS_HASH
    event = _append_event(
        root / manifest["event_ledger_path"], manifest["run_id"], event_payload,
        expected_previous_event_hash,
    )
    return {
        "recorded": True, "run_id": manifest["run_id"], "stage_id": stage_id,
        "status": status, "attempt": event["attempt"], "event_hash": event["event_hash"],
        "event_count": event["sequence"],
    }
