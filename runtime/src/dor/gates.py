"""Hash-bound, append-only scientific workflow approval gates.

The ledger records declared human decisions. It is an integrity/provenance control,
not an authentication system: reviewer identity is recorded, not independently
verified. The CLI requires an explicit compatibility override to run gated stages
without a ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

GENESIS_HASH = "0" * 64
GATE_ORDER = ("G0", "G1", "G2", "G3", "G4")
PREVIOUS_GATE = {GATE_ORDER[i]: GATE_ORDER[i - 1] for i in range(1, len(GATE_ORDER))}
REQUIRED_ARTIFACTS = {
    "G0": {"dataset_manifest", "source_inventory"},
    "G1": {"mapping_plan", "mapping_validation", "source_inventory", "build_spec", "build_spec_validation"},
    "G2": {"canonical_bundle", "canonical_validation_report", "reconciliation_report", "reconciliation_decisions", "reconciliation_decision_validation", "modeling_task"},
    "G3": {
        "interaction_report", "interaction_manifest",
        "robustness_report", "robustness_manifest", "interaction_selection",
    },
    "G4": {"publication_plan"},
}
G4_REVIEWABLE_ARTIFACTS = {
    "model_report", "reproducibility_report", "interaction_report",
    "mechanism_findings", "virtual_prediction",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _event_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _exclusive_lock(lock_path: Path):
    """Small cross-platform advisory lock for serialized ledger appends."""
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


def _load_events(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    events: list[dict[str, Any]] = []
    latest_by_gate: dict[str, dict[str, Any]] = {}
    previous_hash = GENESIS_HASH
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank line in workflow gate ledger at line {line_number}.")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in workflow gate ledger at line {line_number}: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Workflow gate event at line {line_number} must be a JSON object.")
            supplied_hash = event.get("event_hash")
            payload = {key: value for key, value in event.items() if key != "event_hash"}
            if not isinstance(supplied_hash, str) or supplied_hash != _event_hash(payload):
                raise ValueError(f"Workflow gate event hash mismatch at line {line_number}.")
            if event.get("sequence") != line_number:
                raise ValueError(f"Workflow gate sequence mismatch at line {line_number}.")
            if event.get("previous_event_hash") != previous_hash:
                raise ValueError(f"Workflow gate hash-chain mismatch at line {line_number}.")
            gate = event.get("gate_id")
            if gate not in GATE_ORDER:
                raise ValueError(f"Unknown gate_id at line {line_number}: {gate!r}.")
            if event.get("decision") not in {"APPROVE", "REVISE", "STOP"}:
                raise ValueError(f"Invalid gate decision at line {line_number}.")
            if not all(isinstance(event.get(key), str) and event[key].strip()
                       for key in ("reviewer", "reviewed_at", "rationale")):
                raise ValueError(f"Gate event at line {line_number} lacks reviewer, timestamp, or rationale.")
            try:
                datetime.fromisoformat(event["reviewed_at"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Invalid reviewed_at timestamp at line {line_number}.") from exc
            artifacts = event.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError(f"Gate event artifacts must be an array at line {line_number}.")
            artifact_ids: set[str] = set()
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ValueError(f"Invalid artifact binding at line {line_number}.")
                artifact_id = artifact.get("artifact_id")
                if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in artifact_ids:
                    raise ValueError(f"Missing or duplicate artifact_id at line {line_number}.")
                artifact_ids.add(artifact_id)
                if not isinstance(artifact.get("path"), str) or not Path(artifact["path"]).is_absolute():
                    raise ValueError(f"Artifact path must be absolute at line {line_number}.")
                digest = artifact.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError(f"Invalid artifact SHA-256 at line {line_number}.")
            if event["decision"] == "APPROVE":
                missing = REQUIRED_ARTIFACTS[gate] - artifact_ids
                if missing:
                    raise ValueError(f"Gate {gate} event at line {line_number} lacks required artifacts: {', '.join(sorted(missing))}.")
                if gate == "G4" and not (G4_REVIEWABLE_ARTIFACTS & artifact_ids):
                    raise ValueError("G4 requires at least one reviewed scientific result artifact.")
            prior_gate = PREVIOUS_GATE.get(gate)
            expected_dependency = latest_by_gate.get(prior_gate, {}).get("event_hash") if prior_gate else None
            if event.get("depends_on_event_hash") != expected_dependency:
                raise ValueError(f"Gate {gate} dependency does not match the preceding gate event at line {line_number}.")
            if prior_gate:
                prior_event = latest_by_gate.get(prior_gate)
                if prior_event is None or prior_event.get("decision") != "APPROVE":
                    raise ValueError(f"Gate {gate} was recorded without an approved {prior_gate} event.")
            if event["decision"] == "APPROVE":
                _validate_approval_artifacts(gate, artifacts, latest_by_gate)
            events.append(event)
            latest_by_gate[gate] = event
            previous_hash = supplied_hash
    return events


def _read_json_binding(binding: Mapping[str, Any], label: str) -> dict[str, Any]:
    path = Path(binding["path"])
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _binding_map(bindings: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {item["artifact_id"]: item for item in bindings}


def _validate_g1_artifacts(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> None:
    by_id = _binding_map(bindings)
    mapping_binding = by_id["mapping_plan"]
    validation_binding = by_id["mapping_validation"]
    inventory_binding = by_id["source_inventory"]
    spec_binding = by_id["build_spec"]
    build_spec_validation_binding = by_id["build_spec_validation"]
    prior_inventory = _binding_map(previous_gate_event["artifacts"]).get("source_inventory")
    if prior_inventory is None or (
        prior_inventory["path"] != inventory_binding["path"]
        or prior_inventory["sha256"] != inventory_binding["sha256"]
    ):
        raise ValueError("G1 source_inventory must be the exact source inventory approved at G0.")

    inventory = _read_json_binding(inventory_binding, "G1 source_inventory")
    mapping_plan = _read_json_binding(mapping_binding, "G1 mapping_plan")
    build_spec = _read_json_binding(spec_binding, "G1 build_spec")
    mapping_validation = _read_json_binding(validation_binding, "G1 mapping_validation")
    build_spec_validation = _read_json_binding(build_spec_validation_binding, "G1 build_spec_validation")
    inventory_hash = inventory_binding["sha256"]
    mapping_hash = mapping_binding["sha256"]

    if mapping_plan.get("source_inventory_sha256") != inventory_hash:
        raise ValueError("G1 mapping_plan does not reference the exact approved source_inventory hash.")
    if build_spec.get("source_inventory_sha256") != inventory_hash:
        raise ValueError("G1 build_spec does not reference the exact approved source_inventory hash.")
    if build_spec.get("mapping_plan_sha256") != mapping_hash:
        raise ValueError("G1 build_spec does not reference the exact approved mapping_plan hash.")
    if build_spec.get("mapping_version") != mapping_plan.get("mapping_version"):
        raise ValueError("G1 build_spec mapping_version does not match the approved mapping_plan.")
    if mapping_validation.get("valid") is not True:
        raise ValueError("G1 mapping_validation must have valid=true.")
    if mapping_validation.get("source_inventory_sha256") != inventory_hash:
        raise ValueError("G1 mapping_validation does not reference the exact approved source_inventory hash.")
    if mapping_validation.get("mapping_version") != mapping_plan.get("mapping_version"):
        raise ValueError("G1 mapping_validation mapping_version does not match the approved mapping_plan.")

    from dor.mapping import validate_mapping_plan
    recomputed = validate_mapping_plan(mapping_plan, inventory, inventory_hash)
    if recomputed != mapping_validation:
        raise ValueError("G1 mapping_validation is not the deterministic validation result for the bound mapping_plan and source_inventory.")

    if build_spec_validation.get("valid") is not True:
        raise ValueError("G1 build_spec_validation must have valid=true.")
    expected_build_hashes = {
        "mapping_plan_sha256": mapping_hash,
        "source_inventory_sha256": inventory_hash,
        "build_spec_sha256": spec_binding["sha256"],
    }
    if any(build_spec_validation.get(key) != value for key, value in expected_build_hashes.items()):
        raise ValueError("G1 build_spec_validation does not bind the exact mapping plan, source inventory, and build spec.")
    from dor.builder import validate_build_spec_files
    recomputed_build_spec = validate_build_spec_files(
        Path(mapping_binding["path"]),
        Path(inventory_binding["path"]),
        Path(spec_binding["path"]),
    )
    if recomputed_build_spec != build_spec_validation:
        raise ValueError("G1 build_spec_validation is not the deterministic validation result for the bound mapping plan, source inventory, and build spec.")


def _validate_g2_artifacts(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> None:
    by_id = _binding_map(bindings)
    bundle_binding = by_id["canonical_bundle"]
    validation_binding = by_id["canonical_validation_report"]
    reconciliation_binding = by_id["reconciliation_report"]
    decisions_binding = by_id["reconciliation_decisions"]
    decisions_validation_binding = by_id["reconciliation_decision_validation"]
    task_binding = by_id["modeling_task"]
    prior = _binding_map(previous_gate_event["artifacts"])
    bundle = _read_json_binding(bundle_binding, "G2 canonical_bundle")
    validation = _read_json_binding(validation_binding, "G2 canonical_validation_report")
    reconciliation = _read_json_binding(reconciliation_binding, "G2 reconciliation_report")
    decisions_validation = _read_json_binding(
        decisions_validation_binding, "G2 reconciliation_decision_validation"
    )
    task = _read_json_binding(task_binding, "G2 modeling_task")

    if validation.get("valid") is not True:
        raise ValueError("G2 canonical_validation_report must have valid=true.")
    if reconciliation.get("bundle_sha256") != bundle_binding["sha256"]:
        raise ValueError("G2 reconciliation_report does not reference the exact approved canonical_bundle hash.")
    if decisions_validation.get("valid") is not True:
        raise ValueError("G2 reconciliation_decision_validation must have valid=true.")
    from dor.reconciliation import validate_reconciliation_decisions_files
    recomputed_decisions = validate_reconciliation_decisions_files(
        Path(decisions_binding["path"]),
        Path(reconciliation_binding["path"]),
        Path(bundle_binding["path"]),
    )
    if recomputed_decisions != decisions_validation:
        raise ValueError(
            "G2 reconciliation_decision_validation is not the deterministic result "
            "for the exact bound decisions, reconciliation report, and Canonical Bundle."
        )
    provenance = bundle.get("build_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("G2 canonical_bundle has no build_provenance object.")
    expected_links = (
        ("mapping_plan_sha256", "mapping_plan"),
        ("source_inventory_sha256", "source_inventory"),
        ("build_spec_sha256", "build_spec"),
    )
    for provenance_key, prior_artifact_id in expected_links:
        approved = prior.get(prior_artifact_id)
        if approved is None or provenance.get(provenance_key) != approved["sha256"]:
            raise ValueError(
                f"G2 canonical_bundle build_provenance.{provenance_key} does not match the current G1-approved {prior_artifact_id}."
            )
    if not isinstance(task.get("task_id"), str) or not task["task_id"].strip():
        raise ValueError("G2 modeling_task requires a non-empty task_id.")
    if not isinstance(task.get("target_id"), str) or not task["target_id"].strip():
        raise ValueError("G2 modeling_task requires a non-empty target_id.")
    if not isinstance(task.get("endpoint_definition"), str) or not task["endpoint_definition"].strip():
        raise ValueError("G2 modeling_task requires an exact non-empty endpoint_definition.")


def _validate_g3_selection(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> None:
    by_id = _binding_map(bindings)
    report_binding = by_id["interaction_report"]
    interaction_manifest_binding = by_id["interaction_manifest"]
    robustness_binding = by_id["robustness_report"]
    robustness_manifest_binding = by_id["robustness_manifest"]
    selection_binding = by_id["interaction_selection"]
    report = _read_json_binding(report_binding, "G3 interaction_report")
    interaction_manifest = _read_json_binding(interaction_manifest_binding, "G3 interaction_manifest")
    robustness_report = _read_json_binding(robustness_binding, "G3 robustness_report")
    robustness_manifest = _read_json_binding(robustness_manifest_binding, "G3 robustness_manifest")
    selection = _read_json_binding(selection_binding, "G3 interaction_selection")

    if selection.get("schema_version") != "1.1":
        raise ValueError("G3 interaction_selection schema_version must be 1.1.")
    if selection.get("task_id") != report.get("task_id") or interaction_manifest.get("task_id") != report.get("task_id"):
        raise ValueError("G3 selection, interaction report, and interaction manifest task IDs must match.")
    if selection.get("interaction_report_sha256") != report_binding["sha256"]:
        raise ValueError("G3 selection must bind the exact interaction report SHA-256.")
    if selection.get("robustness_report_sha256") != robustness_binding["sha256"]:
        raise ValueError("G3 selection must bind the exact robustness report SHA-256.")

    approved_task = _binding_map(previous_gate_event["artifacts"]).get("modeling_task")
    if approved_task is None:
        raise ValueError("G3 requires the G2-approved modeling_task artifact.")
    interaction_inputs = interaction_manifest.get("input_hashes")
    robustness_inputs = robustness_manifest.get("input_hashes")
    if not isinstance(interaction_inputs, dict) or not isinstance(robustness_inputs, dict):
        raise ValueError("G3 interaction and robustness manifests require input_hashes objects.")
    if interaction_inputs.get("task_sha256") != approved_task["sha256"]:
        raise ValueError("G3 interaction manifest was not generated from the exact G2-approved modeling_task.")
    if robustness_inputs.get("task_sha256") != approved_task["sha256"]:
        raise ValueError("G3 robustness manifest was not generated from the exact G2-approved modeling_task.")
    interaction_outputs = interaction_manifest.get("output_hashes")
    robustness_outputs = robustness_manifest.get("output_hashes")
    if not isinstance(interaction_outputs, dict) or interaction_outputs.get("interaction_discovery_report.json") != report_binding["sha256"]:
        raise ValueError("G3 interaction manifest does not bind the exact interaction_report.")
    if not isinstance(robustness_outputs, dict) or robustness_outputs.get("interaction_robustness_report.json") != robustness_binding["sha256"]:
        raise ValueError("G3 robustness manifest does not bind the exact robustness_report.")

    shared_inputs = (
        "cohort_sha256", "cohort_report_sha256",
        "split_manifest_sha256", "cohort_manifest_sha256",
    )
    for input_name in shared_inputs:
        interaction_value = interaction_inputs.get(input_name)
        robustness_value = robustness_inputs.get(input_name)
        if not isinstance(interaction_value, str) or not interaction_value:
            raise ValueError(f"G3 interaction manifest is missing {input_name}.")
        if interaction_value != robustness_value:
            raise ValueError(f"G3 interaction and robustness runs do not share the same {input_name}.")

    for field in ("selected_interaction_ids", "not_selected_interaction_ids"):
        values = selection.get(field)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError(f"G3 selection {field} must be an array of non-empty interaction IDs.")
        if len(values) != len(set(values)):
            raise ValueError(f"G3 selection {field} contains duplicate interaction IDs.")
    selected = set(selection["selected_interaction_ids"])
    not_selected = set(selection["not_selected_interaction_ids"])
    if selected.intersection(not_selected):
        raise ValueError("G3 selected and not-selected interaction IDs overlap.")
    if len(selected) > 1:
        raise ValueError("One G3 decision packet may select at most one interaction for its single reviewed mechanism_plan.")

    def catalogue_ids(source: Mapping[str, Any], label: str) -> set[str]:
        catalogue = source.get("interaction_catalogue")
        if not isinstance(catalogue, list):
            raise ValueError(f"{label} does not contain an interaction_catalogue array.")
        identifiers = {
            item.get("interaction_id") for item in catalogue
            if isinstance(item, dict) and isinstance(item.get("interaction_id"), str)
        }
        if len(identifiers) != len(catalogue):
            raise ValueError(f"{label} contains missing or duplicate interaction IDs.")
        return identifiers

    reported_ids = catalogue_ids(report, "G3 interaction_report")
    robust_ids = catalogue_ids(robustness_report, "G3 robustness_report")
    if reported_ids != robust_ids:
        raise ValueError("G3 interaction and robustness reports do not contain the same candidate ID set.")
    if selected.union(not_selected) != reported_ids:
        raise ValueError("G3 selection must classify every reported interaction ID exactly once.")
    if not all(isinstance(selection.get(key), str) and selection[key].strip()
               for key in ("reviewer", "reviewed_at", "rationale")):
        raise ValueError("G3 selection requires reviewer, reviewed_at, and rationale.")
    try:
        datetime.fromisoformat(selection["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("G3 selection reviewed_at must be an ISO-8601 timestamp.") from exc

    mechanism_binding = by_id.get("mechanism_plan")
    if selected and mechanism_binding is None:
        raise ValueError("A non-empty G3 selection requires a reviewed mechanism_plan artifact.")
    if mechanism_binding is not None:
        mechanism_plan = _read_json_binding(mechanism_binding, "G3 mechanism_plan")
        if mechanism_plan.get("task_id") != selection["task_id"]:
            raise ValueError("G3 mechanism_plan task_id does not match the selected interaction task.")
        if mechanism_plan.get("interaction_id") not in selected:
            raise ValueError("G3 mechanism_plan interaction_id is not in selected_interaction_ids.")


def _validate_approval_artifacts(
    gate_id: str,
    bindings: list[dict[str, str]],
    latest_by_gate: Mapping[str, Mapping[str, Any]],
) -> None:
    # If an earlier event's files have become stale, inspect_gate_ledger must still
    # report STALE_ARTIFACT rather than failing to parse the historical ledger.
    for binding in bindings:
        path = Path(binding["path"])
        try:
            current_hash = sha256_file(path) if path.is_file() else None
        except OSError:
            current_hash = None
        if current_hash != binding["sha256"]:
            return
    if gate_id == "G1":
        _validate_g1_artifacts(bindings, latest_by_gate["G0"])
    elif gate_id == "G2":
        _validate_g2_artifacts(bindings, latest_by_gate["G1"])
    elif gate_id == "G3":
        _validate_g3_selection(bindings, latest_by_gate["G2"])


def require_selected_interaction_id(ledger_path: Path, interaction_id: str) -> dict[str, Any]:
    """Require a response-surface interaction to be the exact G3-selected candidate."""
    if not isinstance(interaction_id, str) or not interaction_id.strip():
        raise ValueError("A non-empty interaction_id is required.")
    require_gate(ledger_path, "G3")
    events = _load_events(Path(ledger_path).expanduser().resolve())
    event = next(item for item in reversed(events) if item["gate_id"] == "G3")
    by_id = {item["artifact_id"]: item for item in event["artifacts"]}
    selection_binding = by_id["interaction_selection"]
    with Path(selection_binding["path"]).open("r", encoding="utf-8-sig") as handle:
        selection = json.load(handle)
    if interaction_id not in selection.get("selected_interaction_ids", []):
        raise ValueError(f"Interaction {interaction_id} was not selected in the current G3 approval.")
    return {"gate_id": "G3", "interaction_id": interaction_id,
            "interaction_selection_sha256": selection_binding["sha256"]}


def require_selected_interaction(ledger_path: Path, mechanism_plan_path: Path) -> dict[str, Any]:
    """Ensure a mechanism run uses the exact user-selected candidate and approved draft plan."""
    require_gate(ledger_path, "G3")
    events = _load_events(Path(ledger_path).expanduser().resolve())
    event = next(item for item in reversed(events) if item["gate_id"] == "G3")
    by_id = {item["artifact_id"]: item for item in event["artifacts"]}
    selection_binding = by_id["interaction_selection"]
    plan_binding = by_id.get("mechanism_plan")
    if plan_binding is None:
        raise ValueError("G3 contains no mechanism plan; no mechanism investigation was approved.")
    actual_path = Path(mechanism_plan_path).expanduser().resolve(strict=True)
    if plan_binding["path"] != str(actual_path) or plan_binding["sha256"] != sha256_file(actual_path):
        raise ValueError("Mechanism plan differs from the exact plan reviewed at G3.")
    with actual_path.open("r", encoding="utf-8-sig") as handle:
        plan = json.load(handle)
    with Path(selection_binding["path"]).open("r", encoding="utf-8-sig") as handle:
        selection = json.load(handle)
    if plan.get("interaction_id") not in selection.get("selected_interaction_ids", []):
        raise ValueError("Mechanism plan interaction_id was not explicitly selected at G3.")
    return {"gate_id": "G3", "interaction_id": plan.get("interaction_id"),
            "mechanism_plan_sha256": plan_binding["sha256"]}


def _artifact_state(event: Mapping[str, Any]) -> tuple[str, list[dict[str, str]]]:
    stale: list[dict[str, str]] = []
    for artifact in event.get("artifacts", []):
        path = Path(artifact["path"])
        try:
            current = sha256_file(path) if path.is_file() else None
        except OSError:
            current = None
        if current != artifact["sha256"]:
            stale.append({
                "artifact_id": artifact["artifact_id"],
                "path": str(path),
                "expected_sha256": artifact["sha256"],
                "actual_sha256": current or "MISSING_OR_UNREADABLE",
            })
    return ("STALE_ARTIFACT" if stale else "CURRENT"), stale


def inspect_gate_ledger(ledger_path: Path) -> dict[str, Any]:
    """Validate the event chain and report the current state of every gate."""
    ledger_path = ledger_path.expanduser().resolve()
    events = _load_events(ledger_path)
    latest = {event["gate_id"]: event for event in events}
    statuses: dict[str, dict[str, Any]] = {}
    latest_events: dict[str, dict[str, Any]] = {}
    for gate in GATE_ORDER:
        event = latest.get(gate)
        if event is None:
            statuses[gate] = {"status": "NOT_RECORDED", "decision": None, "event_hash": None}
            continue
        latest_events[gate] = event
        artifact_status, stale = _artifact_state(event)
        if artifact_status == "STALE_ARTIFACT":
            status = artifact_status
        elif event["decision"] != "APPROVE":
            status = event["decision"]
        else:
            predecessor = PREVIOUS_GATE.get(gate)
            dependency_current = (
                predecessor is None
                or (
                    statuses[predecessor]["status"] == "APPROVED"
                    and event.get("depends_on_event_hash") == statuses[predecessor].get("event_hash")
                )
            )
            status = "APPROVED" if dependency_current else "BLOCKED_UPSTREAM"
        statuses[gate] = {
            "status": status,
            "decision": event["decision"],
            "event_hash": event["event_hash"],
            "reviewer": event["reviewer"],
            "reviewed_at": event["reviewed_at"],
            "depends_on_event_hash": event.get("depends_on_event_hash"),
            "stale_artifacts": stale,
            "artifact_ids": [item["artifact_id"] for item in event["artifacts"]],
        }
    return {
        "valid_ledger": True,
        "ledger_path": str(ledger_path),
        "event_count": len(events),
        "last_event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
        "gates": statuses,
        "events": latest_events,
        "event_history": events,
        "workflow_status": (
            "READY_FOR_FINALIZATION" if statuses["G4"]["status"] == "APPROVED"
            else "IN_PROGRESS"
        ),
        "integrity_scope": "APPEND_ONLY_HASH_CHAIN_AND_FILE_HASH_VERIFICATION_NOT_USER_AUTHENTICATION",
    }


def _artifact_bindings(artifact_specs: Iterable[tuple[str, Path]]) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    seen: set[str] = set()
    for artifact_id, raw_path in artifact_specs:
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ValueError("Artifact IDs must be non-empty strings.")
        if artifact_id in seen:
            raise ValueError(f"Duplicate artifact ID: {artifact_id}.")
        seen.add(artifact_id)
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Gate artifact is not a file: {path}.")
        bindings.append({
            "artifact_id": artifact_id,
            "path": str(path),
            "sha256": sha256_file(path),
        })
    bindings.sort(key=lambda item: item["artifact_id"])
    return bindings


def record_gate_decision(
    ledger_path: Path,
    gate_id: str,
    decision: str,
    reviewer: str,
    rationale: str,
    artifact_specs: Iterable[tuple[str, Path]],
) -> dict[str, Any]:
    """Append one immutable, hash-bound human decision event to a JSONL ledger."""
    if gate_id not in GATE_ORDER:
        raise ValueError(f"Unsupported gate: {gate_id}.")
    if decision not in {"APPROVE", "REVISE", "STOP"}:
        raise ValueError("Decision must be APPROVE, REVISE, or STOP.")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A non-empty reviewer identifier is required.")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("A non-empty decision rationale is required.")
    bindings = _artifact_bindings(artifact_specs)
    ids = {item["artifact_id"] for item in bindings}
    if decision == "APPROVE":
        missing = REQUIRED_ARTIFACTS[gate_id] - ids
        if missing:
            raise ValueError(f"Gate {gate_id} requires artifact IDs: {', '.join(sorted(missing))}.")
        if gate_id == "G4" and not (G4_REVIEWABLE_ARTIFACTS & ids):
            raise ValueError(
                "G4 requires at least one reviewed result: model_report, reproducibility_report, "
                "interaction_report, mechanism_findings, or virtual_prediction."
            )
    ledger_path = ledger_path.expanduser().resolve()
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    with _exclusive_lock(lock_path):
        events = _load_events(ledger_path)
        latest = {event["gate_id"]: event for event in events}
        predecessor = PREVIOUS_GATE.get(gate_id)
        dependency_hash = latest.get(predecessor, {}).get("event_hash") if predecessor else None
        if predecessor:
            snapshot = inspect_gate_ledger(ledger_path)
            if snapshot["gates"][predecessor]["status"] != "APPROVED":
                raise ValueError(
                    f"Cannot record {gate_id}: {predecessor} must be currently approved; "
                    f"its status is {snapshot['gates'][predecessor]['status']}."
                )
        if decision == "APPROVE":
            for binding in bindings:
                path = Path(binding["path"])
                if not path.is_file() or sha256_file(path) != binding["sha256"]:
                    raise ValueError(f"Approval artifact changed while recording the decision: {path}")
            _validate_approval_artifacts(gate_id, bindings, latest)
        payload = {
            "schema_version": "1.0",
            "sequence": len(events) + 1,
            "gate_id": gate_id,
            "decision": decision,
            "reviewer": reviewer.strip(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "rationale": rationale.strip(),
            "artifacts": bindings,
            "depends_on_event_hash": dependency_hash,
            "previous_event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
        }
        event = {**payload, "event_hash": _event_hash(payload)}
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("ab") as handle:
            handle.write((_canonical_json(event) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    return {
        "recorded": True,
        "ledger_path": str(ledger_path),
        "event": event,
        "gate_status": inspect_gate_ledger(ledger_path)["gates"][gate_id],
    }


def require_gate(
    ledger_path: Path,
    gate_id: str,
    expected_artifacts: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Fail closed unless this and every preceding gate remain current and approved."""
    if gate_id not in GATE_ORDER:
        raise ValueError(f"Unsupported gate: {gate_id}.")
    snapshot = inspect_gate_ledger(ledger_path)
    for gate in GATE_ORDER[: GATE_ORDER.index(gate_id) + 1]:
        state = snapshot["gates"][gate]["status"]
        if state != "APPROVED":
            raise ValueError(f"Required workflow gate {gate} is not currently approved (status={state}).")
    selected = next(event for event in reversed(_load_events(Path(ledger_path).expanduser().resolve()))
                    if event["gate_id"] == gate_id)
    by_id = {item["artifact_id"]: item for item in selected["artifacts"]}
    for artifact_id, expected_path in (expected_artifacts or {}).items():
        binding = by_id.get(artifact_id)
        if binding is None:
            raise ValueError(f"Gate {gate_id} does not bind required artifact {artifact_id}.")
        actual_path = str(Path(expected_path).expanduser().resolve(strict=True))
        if binding["path"] != actual_path:
            raise ValueError(f"Gate {gate_id} artifact {artifact_id} path differs from the approved path.")
        if binding["sha256"] != sha256_file(Path(actual_path)):
            raise ValueError(f"Gate {gate_id} artifact {artifact_id} hash differs from the approved hash.")
    return {
        "gate_id": gate_id,
        "status": "APPROVED",
        "event_hash": selected["event_hash"],
        "reviewer": selected["reviewer"],
        "reviewed_at": selected["reviewed_at"],
    }
