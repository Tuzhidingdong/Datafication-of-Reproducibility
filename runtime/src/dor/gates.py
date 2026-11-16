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
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

GENESIS_HASH = "0" * 64
GATE_ORDER = ("G0", "G1", "G2", "G3", "G4")
PREVIOUS_GATE = {GATE_ORDER[i]: GATE_ORDER[i - 1] for i in range(1, len(GATE_ORDER))}
G4_REQUIRED_REVIEWED_ARTIFACTS = {
    "model_report",
    "reproducibility_evaluation",
    "interaction_report",
    "robustness_report",
    "interaction_selection",
    "virtual_prediction",
}
G4_FULL_ANALYSIS_REVIEWABLE_ARTIFACTS = {
    *G4_REQUIRED_REVIEWED_ARTIFACTS,
    "cohort_review_record",
    "cohort_review_validation",
}
G4_SINGLE_STUDY_REVIEWABLE_ARTIFACTS = {
    "single_study_applicability_record",
    "single_study_applicability_validation",
    "canonical_bundle",
    "canonical_validation_report",
    "reconciliation_report",
    "reconciliation_decisions",
    "research_scope_record",
    "modeling_task",
    *G4_REQUIRED_REVIEWED_ARTIFACTS,
    "interaction_manifest",
    "robustness_manifest",
}
G3_SINGLE_STUDY_REQUIRED_ARTIFACTS = {
    "single_study_applicability_record",
    "single_study_applicability_validation",
    "canonical_bundle",
    "modeling_task",
    "model_report",
    "reproducibility_evaluation",
    "interaction_report",
    "interaction_manifest",
    "robustness_report",
    "robustness_manifest",
    "interaction_selection",
    "virtual_prediction",
}
G4_SINGLE_STUDY_REQUIRED_ARTIFACTS = {
    "publication_plan", "publication_plan_validation",
    "worker_review_output", "reviewed_findings",
    *G4_SINGLE_STUDY_REVIEWABLE_ARTIFACTS,
}
REQUIRED_ARTIFACTS = {
    "G0": {"dataset_manifest", "source_inventory", "g0_review_packet", "g0_review_packet_validation"},
    "G1": {"mapping_plan", "mapping_validation", "source_inventory", "build_spec", "build_spec_validation", "g1_review_packet", "g1_review_packet_validation"},
    "G2": {"canonical_bundle", "canonical_validation_report", "reconciliation_report", "reconciliation_decisions", "discovery_report", "research_scope_record", "modeling_task", "g2_review_packet", "g2_review_packet_validation"},
    "G3": {
        "interaction_report", "interaction_manifest",
        "robustness_report", "robustness_manifest", "interaction_selection",
    },
    "G4": {
        "publication_plan", "publication_plan_validation",
        "worker_review_output", "reviewed_findings",
        *G4_FULL_ANALYSIS_REVIEWABLE_ARTIFACTS,
    },
}
G4_REVIEWABLE_ARTIFACTS = G4_FULL_ANALYSIS_REVIEWABLE_ARTIFACTS


# These sets mirror the two supported generic Run Plan entry routes. They are
# workflow contracts (artifact IDs only), not discipline-specific assumptions.
_GATE_REVIEW_INPUT_SETS = {
    "G0": (
        frozenset({
            "dataset_manifest", "source_inventory", "data_audit_report",
            "mapping_review_queue", "adapter_handoff",
        }),
        frozenset({
            "dataset_manifest", "source_inventory", "adapter_handoff",
            "materialization_manifest",
        }),
    ),
    "G1": (
        frozenset({
            "mapping_plan", "mapping_validation", "source_inventory",
            "build_spec", "build_spec_validation",
        }),
    ),
    "G2": (
        frozenset({
            "canonical_bundle", "canonical_validation_report",
            "reconciliation_report", "reconciliation_review_queue",
            "reconciliation_decisions", "reconciliation_decision_validation",
            "discovery_report", "research_scope_record", "modeling_task",
        }),
    ),
}
_GATE_REVIEW_OUTPUT_PATHS = {
    "G0": {
        "STRUCTURED_DATASET": (
            "01_audit/g0_review_packet.json",
            "01_audit/g0_review_packet_validation.json",
        ),
        "CANONICAL_BUNDLE": (
            "01_review/g0_review_packet.json",
            "01_review/g0_review_packet_validation.json",
        ),
    },
    "G1": {
        "DEFAULT": (
            "02_mapping/g1_review_packet.json",
            "02_mapping/g1_review_packet_validation.json",
        ),
    },
    "G2": {
        "DEFAULT": (
            "04_reconciliation/g2_review_packet.json",
            "04_reconciliation/g2_review_packet_validation.json",
        ),
    },
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
                single_study_profile = "single_study_applicability_record" in artifact_ids
                if gate == "G3" and single_study_profile:
                    required = G3_SINGLE_STUDY_REQUIRED_ARTIFACTS
                elif gate == "G4" and single_study_profile:
                    required = G4_SINGLE_STUDY_REQUIRED_ARTIFACTS
                else:
                    required = REQUIRED_ARTIFACTS[gate]
                missing = required - artifact_ids
                if missing:
                    raise ValueError(f"Gate {gate} event at line {line_number} lacks required artifacts: {', '.join(sorted(missing))}.")
                if gate == "G4":
                    reviewable = (G4_SINGLE_STUDY_REVIEWABLE_ARTIFACTS
                                  if single_study_profile else G4_REVIEWABLE_ARTIFACTS)
                    if not reviewable.issubset(artifact_ids):
                        raise ValueError("G4 does not bind the complete declared Worker review input set.")
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


def _require_gate_binding(
    by_id: Mapping[str, dict[str, str]], artifact_id: str, gate_id: str,
) -> dict[str, str]:
    """Return one required Gate artifact with a user-actionable failure message."""
    binding = by_id.get(artifact_id)
    if binding is None:
        raise ValueError(
            f"{gate_id} approval is missing required artifact {artifact_id!r}. "
            "Regenerate the review packet from the active Run and retry the Gate only after the missing stage output exists."
        )
    return binding


def _validate_gate_review_packet(bindings: list[dict[str, str]], gate_id: str) -> None:
    stage_id = gate_id.lower() + "_review_packet"
    report_id = stage_id + "_validation"
    by_id = _binding_map(bindings)
    packet_binding = _require_gate_binding(by_id, stage_id, gate_id)
    report_binding = _require_gate_binding(by_id, report_id, gate_id)
    packet = _read_json_binding(packet_binding, gate_id + " review packet")
    report = _read_json_binding(report_binding, gate_id + " review packet validation")

    if set(packet) - {
        "schema_version", "run_id", "project_id", "stage_id", "prepared_at",
        "packet_status", "artifact_bindings", "review_items",
        "unresolved_questions", "preparation_notes",
    }:
        raise ValueError(f"{gate_id} review packet contains unknown top-level properties.")
    required = {
        "schema_version", "run_id", "project_id", "stage_id", "prepared_at",
        "packet_status", "artifact_bindings", "review_items", "unresolved_questions",
    }
    if required - set(packet):
        raise ValueError(f"{gate_id} review packet is missing required properties.")
    if packet.get("schema_version") != "1.0" or packet.get("stage_id") != stage_id:
        raise ValueError(f"{gate_id} review packet schema_version or stage_id is invalid.")
    if packet.get("packet_status") != "AWAITING_HUMAN_REVIEW":
        raise ValueError(f"{gate_id} review packet must remain AWAITING_HUMAN_REVIEW.")
    for key in ("run_id", "project_id"):
        if not isinstance(packet.get(key), str) or not packet[key].strip():
            raise ValueError(f"{gate_id} review packet {key} must be a non-empty string.")
    prepared_at = packet.get("prepared_at")
    if not isinstance(prepared_at, str):
        raise ValueError(f"{gate_id} review packet prepared_at must be timezone-aware ISO-8601.")
    try:
        parsed = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone offset is required")
    except ValueError as exc:
        raise ValueError(f"{gate_id} review packet prepared_at must be timezone-aware ISO-8601.") from exc

    run_root_value = report.get("run_root")
    if not isinstance(run_root_value, str) or not run_root_value.strip():
        raise ValueError(f"{gate_id} validation report must identify run_root.")
    run_root = Path(run_root_value).expanduser().resolve(strict=True)
    if not run_root.is_dir():
        raise ValueError(f"{gate_id} validation report run_root must be a directory.")
    packet_path = Path(packet_binding["path"]).expanduser().resolve(strict=True)
    report_path = Path(report_binding["path"]).expanduser().resolve(strict=True)
    if not packet_path.is_relative_to(run_root) or not report_path.is_relative_to(run_root):
        raise ValueError(f"{gate_id} review packet and validation report must be inside the same Run workspace.")
    actual_input_ids = frozenset(set(by_id) - {stage_id, report_id})
    allowed_input_sets = _GATE_REVIEW_INPUT_SETS[gate_id]
    if actual_input_ids not in allowed_input_sets:
        raise ValueError(
            f"{gate_id} Gate-bound input artifacts must match one exact supported Run Plan input set."
        )
    if gate_id == "G0":
        route = "CANONICAL_BUNDLE" if "materialization_manifest" in actual_input_ids else "STRUCTURED_DATASET"
    else:
        route = "DEFAULT"
    expected_packet_rel, expected_report_rel = _GATE_REVIEW_OUTPUT_PATHS[gate_id][route]
    if packet_path.relative_to(run_root).as_posix() != expected_packet_rel:
        raise ValueError(f"{gate_id} review packet path must be {expected_packet_rel}.")
    if report_path.relative_to(run_root).as_posix() != expected_report_rel:
        raise ValueError(f"{gate_id} review validation report path must be {expected_report_rel}.")
    if report.get("contract") != "RUN_REVIEW_PACKET" or report.get("valid") is not True:
        raise ValueError(f"{gate_id} review packet validation report must have contract RUN_REVIEW_PACKET and valid=true.")
    if report.get("run_id") != packet["run_id"] or report.get("project_id") != packet["project_id"]:
        raise ValueError(f"{gate_id} validation report Run/project identity differs from the packet.")
    if report.get("stage_id") != stage_id:
        raise ValueError(f"{gate_id} validation report stage_id differs from the packet.")
    if report.get("validation_report_path") != str(report_path):
        raise ValueError(f"{gate_id} validation report path does not match the Gate-bound report.")
    record = report.get("record")
    if not isinstance(record, dict) or (
        record.get("path") != str(packet_path)
        or record.get("sha256") != packet_binding["sha256"]
        or sha256_file(packet_path) != packet_binding["sha256"]
    ):
        raise ValueError(f"{gate_id} validation report is not bound to the exact Gate-bound review packet.")
    if not isinstance(report.get("errors"), list) or report["errors"]:
        raise ValueError(f"{gate_id} validation report contains errors.")
    
    expected_input_ids = set(by_id) - {stage_id, report_id}
    packet_bindings = packet.get("artifact_bindings")
    if not isinstance(packet_bindings, list) or not packet_bindings:
        raise ValueError(f"{gate_id} review packet artifact_bindings must be a non-empty array.")
    supplied_ids: set[str] = set()
    for index, item in enumerate(packet_bindings):
        if not isinstance(item, dict) or set(item) != {"artifact_id", "path", "sha256"}:
            raise ValueError(f"{gate_id} review packet artifact_bindings[{index}] has an invalid property set.")
        artifact_id = item.get("artifact_id")
        raw_path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in supplied_ids:
            raise ValueError(f"{gate_id} review packet artifact IDs must be non-empty and unique.")
        supplied_ids.add(artifact_id)
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"{gate_id} review packet artifact path must be non-empty.")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"{gate_id} review packet artifact SHA-256 is invalid.")
        binding = by_id.get(artifact_id)
        if binding is None:
            raise ValueError(f"{gate_id} Gate event does not bind packet artifact {artifact_id}.")
        raw = Path(raw_path).expanduser()
        candidate = raw if raw.is_absolute() else run_root / raw
        try:
            candidate = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"{gate_id} review packet artifact is missing: {artifact_id}.") from exc
        if not candidate.is_relative_to(run_root):
            raise ValueError(f"{gate_id} review packet artifact escapes the Run workspace: {artifact_id}.")
        gate_path = Path(binding["path"]).expanduser().resolve(strict=True)
        if candidate != gate_path or digest != binding["sha256"]:
            raise ValueError(f"{gate_id} review packet artifact {artifact_id} differs from the exact Gate-bound path/hash.")
        if not candidate.is_file() or sha256_file(candidate) != digest:
            raise ValueError(f"{gate_id} review packet artifact {artifact_id} changed after review.")
    if supplied_ids != expected_input_ids:
        missing = sorted(expected_input_ids - supplied_ids)
        extra = sorted(supplied_ids - expected_input_ids)
        raise ValueError(
            f"{gate_id} review packet must cover exactly the Gate-bound input artifacts; "
            f"missing={missing}, extra={extra}."
        )
    if report.get("checked_artifact_count") != len(supplied_ids):
        raise ValueError(f"{gate_id} validation report checked_artifact_count is inconsistent.")

    questions = packet.get("review_items")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"{gate_id} review packet requires at least one review item.")
    question_ids: set[str] = set()
    covered_ids: set[str] = set()
    for index, question in enumerate(questions):
        if not isinstance(question, dict) or set(question) != {"item_id", "question", "artifact_ids", "mandatory"}:
            raise ValueError(f"{gate_id} review_items[{index}] has an invalid property set.")
        item_id = question.get("item_id")
        refs = question.get("artifact_ids")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in question_ids:
            raise ValueError(f"{gate_id} review item IDs must be non-empty and unique.")
        question_ids.add(item_id)
        if not isinstance(question.get("question"), str) or not question["question"].strip():
            raise ValueError(f"{gate_id} review item question must be non-empty.")
        if type(question.get("mandatory")) is not bool:
            raise ValueError(f"{gate_id} review item mandatory must be boolean.")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
                or len(refs) != len(set(refs))):
            raise ValueError(f"{gate_id} review item artifact_ids must be a non-empty unique string array.")
        if not set(refs).issubset(supplied_ids):
            raise ValueError(f"{gate_id} review item references an artifact outside the packet.")
        covered_ids.update(refs)
    if covered_ids != supplied_ids:
        raise ValueError(f"{gate_id} review items must collectively cover every Gate-bound input artifact.")
    if not isinstance(packet.get("unresolved_questions"), list) or any(
        not isinstance(item, str) for item in packet["unresolved_questions"]
    ):
        raise ValueError(f"{gate_id} review packet unresolved_questions must be an array of strings.")
    if "preparation_notes" in packet and (
        not isinstance(packet["preparation_notes"], list)
        or any(not isinstance(item, str) for item in packet["preparation_notes"])
    ):
        raise ValueError(f"{gate_id} review packet preparation_notes must be an array of strings.")


def _validate_g1_artifacts(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> None:
    by_id = _binding_map(bindings)
    mapping_binding = _require_gate_binding(by_id, "mapping_plan", "G1")
    validation_binding = _require_gate_binding(by_id, "mapping_validation", "G1")
    inventory_binding = _require_gate_binding(by_id, "source_inventory", "G1")
    spec_binding = _require_gate_binding(by_id, "build_spec", "G1")
    build_spec_validation_binding = _require_gate_binding(by_id, "build_spec_validation", "G1")
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
    bundle_binding = _require_gate_binding(by_id, "canonical_bundle", "G2")
    validation_binding = _require_gate_binding(by_id, "canonical_validation_report", "G2")
    reconciliation_binding = _require_gate_binding(by_id, "reconciliation_report", "G2")
    decisions_binding = _require_gate_binding(by_id, "reconciliation_decisions", "G2")
    discovery_binding = _require_gate_binding(by_id, "discovery_report", "G2")
    scope_binding = _require_gate_binding(by_id, "research_scope_record", "G2")
    task_binding = _require_gate_binding(by_id, "modeling_task", "G2")
    prior = _binding_map(previous_gate_event["artifacts"])
    bundle = _read_json_binding(bundle_binding, "G2 canonical_bundle")
    validation = _read_json_binding(validation_binding, "G2 canonical_validation_report")
    reconciliation = _read_json_binding(reconciliation_binding, "G2 reconciliation_report")
    task = _read_json_binding(task_binding, "G2 modeling_task")
    discovery = _read_json_binding(discovery_binding, "G2 discovery_report")
    scope = _read_json_binding(scope_binding, "G2 research_scope_record")

    if validation.get("valid") is not True:
        raise ValueError("G2 canonical_validation_report must have valid=true.")
    if reconciliation.get("bundle_sha256") != bundle_binding["sha256"]:
        raise ValueError("G2 reconciliation_report does not reference the exact approved canonical_bundle hash.")
    from dor.reconciliation import validate_reconciliation_decisions_files
    recomputed_decisions = validate_reconciliation_decisions_files(
        Path(decisions_binding["path"]),
        Path(reconciliation_binding["path"]),
        Path(bundle_binding["path"]),
    )
    if recomputed_decisions.get("valid") is not True:
        raise ValueError(
            "G2 reconciliation decisions do not pass exact report/Canonical Bundle provenance validation."
        )
    from dor.research_scope import validate_research_scope_files
    scope_validation = validate_research_scope_files(
        Path(scope_binding["path"]),
        Path(discovery_binding["path"]),
        Path(task_binding["path"]),
    )
    if scope_validation.get("valid") is not True:
        raise ValueError(
            "G2 research_scope_record does not validate against the exact Discovery report and modeling task: "
            + "; ".join(item.get("message", item.get("code", "invalid")) for item in scope_validation.get("errors", []))
        )
    if scope.get("discovery_report_sha256") != discovery_binding["sha256"]:
        raise ValueError("G2 research_scope_record does not bind the exact approved Discovery report hash.")
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


def _validate_single_study_na_bundle(
    by_id: Mapping[str, dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify NOT_APPLICABLE records against the exact G2-approved task and Bundle."""
    previous = _binding_map(previous_gate_event.get("artifacts", []))
    bundle_binding = _require_gate_binding(previous, "canonical_bundle", "G3")
    task_binding = _require_gate_binding(previous, "modeling_task", "G3")
    record_binding = _require_gate_binding(by_id, "single_study_applicability_record", "G3")
    validation_binding = _require_gate_binding(by_id, "single_study_applicability_validation", "G3")
    record = _read_json_binding(record_binding, "single-study applicability record")
    validation = _read_json_binding(validation_binding, "single-study applicability validation")
    task = _read_json_binding(task_binding, "G2 modeling task")
    bundle = _read_json_binding(bundle_binding, "G2 canonical_bundle")
    bundle_studies = bundle.get("studies")
    bundle_study_ids = [
        item.get("study_id") for item in bundle_studies
        if isinstance(item, dict) and isinstance(item.get("study_id"), str) and item.get("study_id")
    ] if isinstance(bundle_studies, list) else []
    if len(bundle_study_ids) != 1 or bundle_study_ids != record.get("study_ids"):
        raise ValueError("G3 single-study applicability record must match exactly one explicit Study in the G2-approved Canonical Bundle.")

    if record.get("schema_version") != "1.0" or record.get("scope") != "CONTROLLED_SINGLE_STUDY":
        raise ValueError("G3 single-study applicability record has an unsupported schema or scope.")
    if (record.get("applicability_status") != "NOT_APPLICABLE"
            or type(record.get("study_count")) is not int or record.get("study_count") != 1):
        raise ValueError("G3 single-study applicability record must declare one Study and NOT_APPLICABLE.")
    if (record.get("canonical_bundle_sha256") != bundle_binding["sha256"]
            or record.get("modeling_task_sha256") != task_binding["sha256"]):
        raise ValueError("G3 single-study applicability record differs from the exact G2-approved Bundle/task.")
    if (validation.get("valid") is not True
            or validation.get("applicability_status") != "NOT_APPLICABLE"
            or validation.get("run_id") != record.get("run_id")
            or validation.get("project_id") != record.get("project_id")
            or validation.get("study_count") != 1
            or validation.get("eligible_study_count") != 1):
        raise ValueError("G3 requires a valid deterministic single-study applicability report for the same Run/Project and one eligible Study.")
    if (validation.get("applicability_record_sha256") != record_binding["sha256"]
            or validation.get("canonical_bundle_sha256") != bundle_binding["sha256"]
            or validation.get("modeling_task_sha256") != task_binding["sha256"]):
        raise ValueError("G3 applicability validation does not bind the exact record, Bundle, and task.")
    study_ids = record.get("study_ids")
    if not isinstance(study_ids, list) or len(study_ids) != 1 or not isinstance(study_ids[0], str) or not study_ids[0]:
        raise ValueError("G3 single-study applicability record requires exactly one explicit Study ID.")
    for status_field, reason_field in (
        ("cohort_feasibility_status", "cohort_feasibility_reason"),
        ("modeling_validation_status", "modeling_validation_reason"),
    ):
        if record.get(status_field) != "NOT_APPLICABLE":
            raise ValueError(f"G3 applicability record {status_field} must be NOT_APPLICABLE.")
        if not isinstance(record.get(reason_field), str) or not record[reason_field].strip():
            raise ValueError(f"G3 applicability record lacks {reason_field}.")
    if not all(isinstance(record.get(field), str) and record[field].strip()
               for field in ("reviewer", "rationale")):
        raise ValueError("G3 applicability record requires reviewer and rationale.")
    try:
        reviewed_at = datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            raise ValueError("timezone required")
    except (KeyError, ValueError) as exc:
        raise ValueError("G3 applicability record reviewed_at must be timezone-aware.") from exc

    run_id = record.get("run_id")
    project_id = record.get("project_id")
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("G3 single-study applicability record requires non-empty Run and Project identity.")
    base_fields = {
        "run_id": run_id,
        "project_id": project_id,
        "applicability_status": "NOT_APPLICABLE",
        "scope": "CONTROLLED_SINGLE_STUDY",
        "study_ids": study_ids,
        "study_count": 1,
        "eligible_study_count": 1,
        "canonical_bundle_sha256": bundle_binding["sha256"],
        "modeling_task_sha256": task_binding["sha256"],
        "applicability_record_sha256": record_binding["sha256"],
    }
    report_ids = {
        "model_report": "model_report",
        "reproducibility_evaluation": "reproducibility_evaluation",
        "interaction_report": "interaction_report",
        "robustness_report": "robustness_report",
        "virtual_prediction": "virtual_prediction",
    }
    for artifact_id, label in report_ids.items():
        binding = _require_gate_binding(by_id, artifact_id, "G3")
        report = _read_json_binding(binding, "G3 " + label)
        if report.get("schema_version") != "1.0" or any(report.get(key) != value for key, value in base_fields.items()):
            raise ValueError(f"G3 {label} is not a matching NOT_APPLICABLE record.")
        if report.get("task_id") != task.get("task_id"):
            raise ValueError(f"G3 {label} task_id differs from the approved task.")
        if not isinstance(report.get("reason"), str) or not report["reason"].strip():
            raise ValueError(f"G3 {label} lacks its explicit non-applicability reason.")
        if artifact_id in {"interaction_report", "robustness_report"} and report.get("interaction_catalogue") != []:
            raise ValueError(f"G3 {label} must contain an explicitly empty interaction catalogue.")
        for forbidden in ("model_artifact", "validation_metrics", "test_evaluation",
                          "folds", "per_study_performance", "prediction", "predicted_value"):
            if forbidden in report:
                raise ValueError(f"G3 {label} must not contain fabricated scientific result field {forbidden}.")

    for manifest_id, report_id, filename in (
        ("interaction_manifest", "interaction_report", "interaction_discovery_report.json"),
        ("robustness_manifest", "robustness_report", "interaction_robustness_report.json"),
    ):
        binding = _require_gate_binding(by_id, manifest_id, "G3")
        payload = _read_json_binding(binding, "G3 " + manifest_id)
        if any(payload.get(key) != value for key, value in base_fields.items()):
            raise ValueError(f"G3 {manifest_id} is not a matching NOT_APPLICABLE manifest.")
        inputs = payload.get("input_hashes")
        outputs = payload.get("output_hashes")
        report_binding = _require_gate_binding(by_id, report_id, "G3")
        if (not isinstance(inputs, dict)
                or inputs.get("task_sha256") != task_binding["sha256"]
                or inputs.get("canonical_bundle_sha256") != bundle_binding["sha256"]
                or inputs.get("applicability_record_sha256") != record_binding["sha256"]):
            raise ValueError(f"G3 {manifest_id} does not bind the exact Bundle/task/applicability record.")
        if not isinstance(outputs, dict) or outputs.get(filename) != report_binding["sha256"]:
            raise ValueError(f"G3 {manifest_id} does not bind the exact NOT_APPLICABLE report.")

    selection_binding = _require_gate_binding(by_id, "interaction_selection", "G3")
    selection = _read_json_binding(selection_binding, "G3 interaction_selection")
    if selection.get("schema_version") != "1.1":
        raise ValueError("G3 single-study interaction_selection schema_version must be 1.1.")
    if selection.get("task_id") != task.get("task_id"):
        raise ValueError("G3 interaction_selection task_id differs from the approved task.")
    if (selection.get("interaction_report_sha256") != by_id["interaction_report"]["sha256"]
            or selection.get("robustness_report_sha256") != by_id["robustness_report"]["sha256"]):
        raise ValueError("G3 interaction_selection must bind the exact NOT_APPLICABLE reports.")
    if selection.get("selected_interaction_ids") != [] or selection.get("not_selected_interaction_ids") != []:
        raise ValueError("A NOT_APPLICABLE single-Study Run cannot select nonexistent interactions.")
    if selection.get("applicability_status") != "NOT_APPLICABLE":
        raise ValueError("G3 interaction_selection must explicitly declare NOT_APPLICABLE.")
    if selection.get("not_applicable_reason") != record["modeling_validation_reason"]:
        raise ValueError("G3 interaction_selection reason differs from the reviewed applicability record.")
    if not all(isinstance(selection.get(key), str) and selection[key].strip()
               for key in ("reviewer", "reviewed_at", "rationale")):
        raise ValueError("G3 single-study interaction_selection requires reviewer, timestamp, and rationale.")
    try:
        parsed = datetime.fromisoformat(selection["reviewed_at"].replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ValueError("G3 single-study interaction_selection reviewed_at must be timezone-aware.") from exc
    return record


def _validate_g3_selection(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any],
) -> None:
    by_id = _binding_map(bindings)
    if "single_study_applicability_record" in by_id:
        _validate_single_study_na_bundle(by_id, previous_gate_event)
        return
    report_binding = _require_gate_binding(by_id, "interaction_report", "G3")
    interaction_manifest_binding = _require_gate_binding(by_id, "interaction_manifest", "G3")
    robustness_binding = _require_gate_binding(by_id, "robustness_report", "G3")
    robustness_manifest_binding = _require_gate_binding(by_id, "robustness_manifest", "G3")
    selection_binding = _require_gate_binding(by_id, "interaction_selection", "G3")
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



def _validate_g4_publication_plan(by_id: Mapping[str, dict[str, str]]) -> None:
    """Recheck the exact late-bound Publication Plan and every source it packages."""
    plan_binding = _require_gate_binding(by_id, "publication_plan", "G4")
    validation_binding = _require_gate_binding(by_id, "publication_plan_validation", "G4")
    plan = _read_json_binding(plan_binding, "G4 publication_plan")
    report = _read_json_binding(validation_binding, "G4 publication_plan_validation")

    if report.get("schema_version") != "1.0" or report.get("contract") != "RUN_BOUND_PUBLICATION_PLAN":
        raise ValueError("G4 publication_plan_validation has an unsupported contract.")
    if report.get("valid") is not True:
        raise ValueError("G4 publication_plan_validation must declare valid=true.")
    if report.get("plan") != {
        "path": plan_binding["path"],
        "sha256": plan_binding["sha256"],
    }:
        raise ValueError("G4 publication_plan_validation does not bind the exact Gate-bound plan path and SHA-256.")
    if report.get("validation_report_path") != validation_binding["path"]:
        raise ValueError("G4 publication_plan_validation report path differs from the Gate-bound report.")
    if (plan.get("run_id") != report.get("run_id")
            or plan.get("project_id") != report.get("project_id")):
        raise ValueError("G4 Publication Plan identity differs from its validation report.")

    run_root_value = report.get("run_root")
    if not isinstance(run_root_value, str) or not run_root_value.strip():
        raise ValueError("G4 publication_plan_validation must identify run_root.")
    run_root = Path(run_root_value).expanduser().resolve(strict=True)
    if not run_root.is_dir():
        raise ValueError("G4 Publication Plan run_root must be a directory.")
    for label, binding in (
        ("publication_plan", plan_binding),
        ("publication_plan_validation", validation_binding),
    ):
        path = Path(binding["path"]).expanduser().resolve(strict=True)
        if not path.is_relative_to(run_root) or sha256_file(path) != binding["sha256"]:
            raise ValueError(f"G4 {label} is outside the active Run or changed after validation.")

    if not isinstance(plan, dict):
        raise ValueError("G4 Publication Plan must be a JSON object.")
    if not all(isinstance(plan.get(key), str) and plan[key].strip()
               for key in ("project_id", "run_id", "package_version")):
        raise ValueError("G4 Publication Plan requires project_id, run_id, and package_version.")
    if report.get("run_id") != plan.get("run_id") or report.get("project_id") != plan.get("project_id"):
        raise ValueError("G4 Publication Plan identity differs from the active validation report.")
    if not isinstance(report.get("errors"), list) or report["errors"]:
        raise ValueError("G4 Publication Plan validation report must contain an empty errors array.")

    entries = plan.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("G4 Publication Plan artifacts must be a non-empty array.")
    package_ids: list[str] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("G4 Publication Plan contains a malformed artifact entry.")
        package_id = item.get("artifact_id")
        if not isinstance(package_id, str) or not package_id.strip():
            raise ValueError("G4 Publication Plan contains an empty package artifact ID.")
        package_ids.append(package_id)
    if len(package_ids) != len(set(package_ids)):
        raise ValueError("G4 Publication Plan contains duplicate package artifact IDs.")

    required_common = {
        "WORKER_REVIEW_RECORD", "HUMAN_DISPOSITION_RECORD",
        "HUMAN_DISPOSITION_VALIDATION",
    }
    if "single_study_applicability_record" in by_id:
        required_package_ids = required_common | {
            "SINGLE_STUDY_APPLICABILITY_RECORD",
            "SINGLE_STUDY_APPLICABILITY_VALIDATION",
            "MODEL_NOT_APPLICABLE_RECORD",
            "REPRODUCIBILITY_NOT_APPLICABLE_RECORD",
            "INTERACTION_NOT_APPLICABLE_RECORD",
            "INTERACTION_NOT_APPLICABLE_MANIFEST",
            "ROBUSTNESS_NOT_APPLICABLE_RECORD",
            "ROBUSTNESS_NOT_APPLICABLE_MANIFEST",
            "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD",
            "INTERACTION_SELECTION",
        }
        expected_package_sources = {
            "ADAPTER_HANDOFF": "adapter_handoff",
            "DATASET_MANIFEST": "dataset_manifest",
            "SOURCE_INVENTORY": "source_inventory",
            "MAPPING_PLAN": "mapping_plan",
            "MAPPING_VALIDATION": "mapping_validation",
            "BUILD_SPEC": "build_spec",
            "BUILD_SPEC_VALIDATION": "build_spec_validation",
            "CANONICAL_BUNDLE": "canonical_bundle",
            "CANONICAL_VALIDATION": "canonical_validation_report",
            "RECONCILIATION_REPORT": "reconciliation_report",
            "RECONCILIATION_DECISIONS": "reconciliation_decisions",
            "RECONCILIATION_VALIDATION": "reconciliation_decision_validation",
            "DISCOVERY_REPORT": "discovery_report",
            "RESEARCH_SCOPE_RECORD": "research_scope_record",
            "MODELING_TASK": "modeling_task",
            "G2_REVIEW_PACKET": "g2_review_packet",
            "SINGLE_STUDY_APPLICABILITY_RECORD": "single_study_applicability_record",
            "SINGLE_STUDY_APPLICABILITY_VALIDATION": "single_study_applicability_validation",
            "MODEL_NOT_APPLICABLE_RECORD": "model_report",
            "REPRODUCIBILITY_NOT_APPLICABLE_RECORD": "reproducibility_evaluation",
            "INTERACTION_NOT_APPLICABLE_RECORD": "interaction_report",
            "INTERACTION_NOT_APPLICABLE_MANIFEST": "interaction_manifest",
            "ROBUSTNESS_NOT_APPLICABLE_RECORD": "robustness_report",
            "ROBUSTNESS_NOT_APPLICABLE_MANIFEST": "robustness_manifest",
            "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD": "virtual_prediction",
            "INTERACTION_SELECTION": "interaction_selection",
            "WORKER_REVIEW_RECORD": "worker_review_output",
            "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
            "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
        }
    else:
        required_package_ids = required_common | {
            "COHORT_REVIEW_RECORD", "COHORT_REVIEW_VALIDATION",
            "MODEL_ARTIFACT_001", "MODEL_REPORT_001",
            "REPRODUCIBILITY_EVALUATION_001", "INTERACTION_REPORT_001",
            "INTERACTION_ROBUSTNESS_001", "INTERACTION_SELECTION_001",
            "VIRTUAL_PREDICTION_001",
        }
        expected_package_sources = {
            "MODEL_ARTIFACT_001": "model_artifact",
            "MODEL_REPORT_001": "model_report",
            "REPRODUCIBILITY_EVALUATION_001": "reproducibility_evaluation",
            "INTERACTION_REPORT_001": "interaction_report",
            "INTERACTION_ROBUSTNESS_001": "robustness_report",
            "INTERACTION_SELECTION_001": "interaction_selection",
            "VIRTUAL_PREDICTION_001": "virtual_prediction",
            "COHORT_REVIEW_RECORD": "cohort_review_record",
            "COHORT_REVIEW_VALIDATION": "cohort_review_validation",
            "WORKER_REVIEW_RECORD": "worker_review_output",
            "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
            "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
            "MECHANISM_PLAN_001": "mechanism_plan",
            "MECHANISM_BRIDGE_001": "mechanism_evidence_bridge_report",
            "MECHANISM_FINDINGS_001": "mechanism_findings",
            "MECHANISM_LEDGER_001": "mechanism_evidence_ledger",
            "MECHANISM_REVIEW_QUEUE_001": "mechanism_review_queue",
            "MECHANISM_MANIFEST_001": "mechanism_evidence_bridge_manifest",
            "RESPONSE_SURFACE_REPORT_001": "interaction_response_surface_report",
            "RESPONSE_SURFACE_DATA_001": "interaction_response_surface",
            "RESPONSE_SURFACE_MANIFEST_001": "interaction_response_surface_manifest",
            "RESPONSE_SURFACE_SUPPORT_001": "interaction_observed_support",
            "RESPONSE_SURFACE_MARGINALS_001": "interaction_marginal_effects",
        }
    missing_package_ids = sorted(required_package_ids - set(package_ids))
    if missing_package_ids:
        raise ValueError(
            "G4 Publication Plan is missing required delivery entries: "
            + ", ".join(missing_package_ids)
        )
    report_sources = report.get("source_artifacts")
    if not isinstance(report_sources, list):
        raise ValueError("G4 publication_plan_validation must contain source_artifacts.")
    reported_by_package: dict[str, dict[str, Any]] = {}
    for item in report_sources:
        if not isinstance(item, dict):
            raise ValueError("G4 Publication Plan source binding is malformed.")
        package_id = item.get("package_artifact_id")
        if not isinstance(package_id, str) or not package_id.strip() or package_id in reported_by_package:
            raise ValueError("G4 Publication Plan source bindings require unique package_artifact_id values.")
        reported_by_package[package_id] = item

    expected_package_ids: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("G4 Publication Plan contains a malformed artifact entry.")
        package_id = item.get("artifact_id")
        source_path = item.get("source_path")
        source_id = item.get("source_artifact_id")
        status = item.get("status")
        if status not in {"complete", "partial", "requires_review", "not_generated", "not_applicable"}:
            raise ValueError(f"G4 Publication Plan {package_id} has an unsupported status.")
        if status in {"complete", "partial"} and not isinstance(source_path, str):
            raise ValueError(f"G4 Publication Plan {package_id} requires a source_path for status={status}.")
        if status in {"not_generated", "not_applicable"} and (source_path is not None or source_id is not None):
            raise ValueError(f"G4 Publication Plan {package_id} cannot bind a source for status={status}.")
        if source_path is None:
            if source_id is not None:
                raise ValueError(f"G4 Publication Plan {package_id} has source_artifact_id without source_path.")
            continue
        if not isinstance(package_id, str) or not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("Every sourced G4 Publication Plan entry requires package artifact_id and source_artifact_id.")
        expected_source_id = expected_package_sources.get(package_id)
        if expected_source_id is not None and source_id != expected_source_id:
            raise ValueError(
                f"G4 Publication Plan {package_id} must bind Run Artifact {expected_source_id}, not {source_id}."
            )
        expected_package_ids.add(package_id)
        relative = Path(source_path)
        if (relative.is_absolute() or re.match(r"^[A-Za-z]:", source_path)
                or "\\" in source_path or any(part in {"", ".", ".."} for part in relative.parts)
                or relative.as_posix() != source_path):
            raise ValueError(f"G4 Publication Plan source_path is not a safe Run-relative path: {source_path!r}.")
        unresolved_source = run_root / relative
        if unresolved_source.is_symlink():
            raise ValueError(f"G4 Publication Plan source must not be a symbolic link: {unresolved_source}.")
        source_file = unresolved_source.resolve(strict=True)
        if not source_file.is_file() or not source_file.is_relative_to(run_root):
            raise ValueError(f"G4 Publication Plan source is not a regular file inside the Run: {source_file}.")
        digest = sha256_file(source_file)
        report_source = reported_by_package.get(package_id)
        if report_source is None:
            raise ValueError(f"G4 publication_plan_validation omits package source {package_id}.")
        if (report_source.get("artifact_id") != source_id
                or report_source.get("path") != str(source_file)
                or report_source.get("sha256") != digest):
            raise ValueError(f"G4 Publication Plan source {package_id} differs from its validation binding.")
        gate_source = by_id.get(source_id)
        if gate_source is None:
            raise ValueError(f"G4 Gate event must bind Publication Plan source Run Artifact {source_id}.")
        if gate_source["path"] != str(source_file) or gate_source["sha256"] != digest:
            raise ValueError(f"G4 Gate binding for {source_id} differs from the exact Publication Plan source.")

    if set(reported_by_package) != expected_package_ids:
        raise ValueError("G4 publication_plan_validation source set differs from the final Publication Plan.")
    if report.get("checked_source_count") != len(expected_package_ids):
        raise ValueError("G4 publication_plan_validation checked_source_count is inconsistent.")


def _validate_g4_reviewed_findings(
    bindings: list[dict[str, str]],
    previous_gate_event: Mapping[str, Any] | None = None,
) -> None:
    by_id = _binding_map(bindings)
    single_study_profile = "single_study_applicability_record" in by_id
    if single_study_profile:
        if previous_gate_event is None:
            raise ValueError("G4 single-study review requires the approved G3 event.")
        _validate_single_study_na_bundle(by_id, previous_gate_event)
        expected_reviewed_artifacts = G4_SINGLE_STUDY_REVIEWABLE_ARTIFACTS
    else:
        expected_reviewed_artifacts = G4_FULL_ANALYSIS_REVIEWABLE_ARTIFACTS
    worker_binding = _require_gate_binding(by_id, "worker_review_output", "G4")
    reviewed_binding = _require_gate_binding(by_id, "reviewed_findings", "G4")
    worker_result = _read_json_binding(worker_binding, "G4 worker_review_output")
    reviewed = _read_json_binding(reviewed_binding, "G4 reviewed_findings")
    for label, binding in (
        ("worker_review_output", worker_binding),
        ("reviewed_findings", reviewed_binding),
    ):
        bound_path = Path(binding["path"])
        if not bound_path.is_file() or sha256_file(bound_path) != binding["sha256"]:
            raise ValueError(f"G4 {label} changed after the Gate artifact hash was recorded.")

    worker_required = {
        "schema_version", "task_id", "status", "summary", "findings",
        "artifacts", "warnings", "unresolved_questions",
    }
    worker_allowed = worker_required | {"recommended_next_action"}
    if worker_required - set(worker_result) or set(worker_result) - worker_allowed:
        raise ValueError("G4 worker_review_output has missing or unknown top-level properties.")
    if worker_result.get("schema_version") != "1.0":
        raise ValueError("G4 worker_review_output schema_version must be 1.0.")
    if not isinstance(worker_result.get("task_id"), str) or not worker_result["task_id"].strip():
        raise ValueError("G4 worker_review_output requires a non-empty task_id.")
    if not isinstance(worker_result.get("status"), str) or worker_result["status"] not in {"completed", "partial", "blocked", "failed"}:
        raise ValueError("G4 worker_review_output status is invalid.")
    if not isinstance(worker_result.get("summary"), str) or not worker_result["summary"].strip():
        raise ValueError("G4 worker_review_output summary must be non-empty.")
    if "recommended_next_action" in worker_result and not isinstance(worker_result["recommended_next_action"], str):
        raise ValueError("G4 worker_review_output recommended_next_action must be a string.")
    for field in ("artifacts", "warnings", "unresolved_questions"):
        if not isinstance(worker_result.get(field), list):
            raise ValueError(f"G4 worker_review_output {field} must be an array.")
    for field in ("warnings", "unresolved_questions"):
        if any(not isinstance(item, str) for item in worker_result[field]):
            raise ValueError(f"G4 worker_review_output {field} must contain strings.")

    raw_findings = worker_result["findings"]
    if not isinstance(raw_findings, list):
        raise ValueError("G4 worker_review_output findings must be an array.")
    worker_findings: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_findings):
        required = {"finding_id", "summary", "supporting_artifact_ids", "evidence"}
        allowed = required | {"limitations"}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - allowed:
            raise ValueError(
                f"G4 Worker finding at index {index} requires finding_id, summary, "
                "supporting_artifact_ids, and evidence, with no unknown properties."
            )
        finding_id = item.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id.strip() or finding_id in worker_findings:
            raise ValueError("G4 Worker finding IDs must be non-empty and unique.")
        if not isinstance(item.get("summary"), str) or not item["summary"].strip():
            raise ValueError(f"G4 Worker finding {finding_id} requires a non-empty summary.")
        supporting = item.get("supporting_artifact_ids")
        if (not isinstance(supporting, list) or not supporting
                or any(not isinstance(ref, str) or not ref.strip() for ref in supporting)
                or len(supporting) != len(set(supporting))):
            raise ValueError(f"G4 Worker finding {finding_id} requires unique non-empty supporting_artifact_ids.")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"G4 Worker finding {finding_id} requires exact evidence locators.")
        evidence_ids: set[str] = set()
        for locator in evidence:
            if (not isinstance(locator, dict)
                    or not {"artifact_id", "locator"}.issubset(locator)
                    or set(locator) - {"artifact_id", "locator", "description"}):
                raise ValueError(f"G4 Worker finding {finding_id} contains an invalid evidence locator.")
            artifact_id = locator.get("artifact_id")
            if not isinstance(artifact_id, str) or artifact_id not in set(supporting):
                raise ValueError(f"G4 Worker finding {finding_id} evidence must point to one of its supporting artifacts.")
            if not isinstance(locator.get("locator"), str) or not locator["locator"].strip():
                raise ValueError(f"G4 Worker finding {finding_id} evidence locator must be non-empty.")
            if "description" in locator and not isinstance(locator["description"], str):
                raise ValueError(f"G4 Worker finding {finding_id} evidence description must be a string.")
            evidence_ids.add(artifact_id)
        if evidence_ids != set(supporting):
            raise ValueError(f"G4 Worker finding {finding_id} must provide a locator for every supporting artifact.")
        limitations = item.get("limitations", [])
        if not isinstance(limitations, list) or any(not isinstance(value, str) for value in limitations):
            raise ValueError(f"G4 Worker finding {finding_id} limitations must be an array of strings.")
        worker_findings[finding_id] = dict(item)

    reviewed_required = {
        "schema_version", "run_id", "project_id", "reviewer", "reviewed_at",
        "worker_output", "reviewed_artifacts", "findings", "promotion_decision",
        "overall_rationale",
    }
    if reviewed_required - set(reviewed) or set(reviewed) - reviewed_required:
        raise ValueError("G4 reviewed_findings has missing or unknown top-level properties.")
    if reviewed.get("schema_version") != "1.0":
        raise ValueError("G4 reviewed_findings schema_version must be 1.0.")
    for key in ("run_id", "project_id", "reviewer"):
        if not isinstance(reviewed.get(key), str) or not reviewed[key].strip():
            raise ValueError(f"G4 reviewed_findings requires a non-empty {key}.")
    reviewed_at = reviewed.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise ValueError("G4 reviewed_findings requires reviewed_at.")
    try:
        parsed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("timezone offset is required")
    except ValueError as exc:
        raise ValueError("G4 reviewed_findings reviewed_at must be an ISO-8601 timestamp with timezone.") from exc
    rationale = reviewed.get("overall_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("G4 reviewed_findings requires an overall_rationale.")

    worker_ref = reviewed.get("worker_output")
    if not isinstance(worker_ref, dict):
        raise ValueError("G4 reviewed_findings must bind worker_output.")
    if (worker_ref.get("artifact_id") != "worker_review_output"
            or worker_ref.get("path") != worker_binding["path"]
            or worker_ref.get("sha256") != worker_binding["sha256"]):
        raise ValueError("G4 reviewed_findings worker_output does not bind the exact G4 worker_review_output artifact.")

    reviewed_artifacts = reviewed.get("reviewed_artifacts")
    if not isinstance(reviewed_artifacts, list) or not reviewed_artifacts:
        raise ValueError("G4 reviewed_findings requires at least one reviewed_artifact.")
    reviewed_ids: set[str] = set()
    for index, item in enumerate(reviewed_artifacts):
        if not isinstance(item, dict) or set(item) != {"artifact_id", "path", "sha256"}:
            raise ValueError(f"G4 reviewed_artifacts[{index}] must contain exactly artifact_id, path, and sha256.")
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in reviewed_ids:
            raise ValueError("G4 reviewed_findings reviewed_artifacts must have unique non-empty artifact IDs.")
        reviewed_ids.add(artifact_id)
        binding = by_id.get(artifact_id)
        if binding is None:
            raise ValueError(f"G4 Gate event must bind reviewed artifact {artifact_id}.")
        if item.get("path") != binding["path"] or item.get("sha256") != binding["sha256"]:
            raise ValueError(f"G4 reviewed_findings artifact {artifact_id} does not match the exact Gate-bound path and SHA-256.")
        path = Path(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ValueError(f"G4 reviewed artifact {artifact_id} changed after human review.")
    if reviewed_ids != expected_reviewed_artifacts:
        missing = sorted(expected_reviewed_artifacts - reviewed_ids)
        unexpected = sorted(reviewed_ids - expected_reviewed_artifacts)
        raise ValueError(
            "G4 reviewed_findings must bind exactly the artifacts supplied to the active Worker review stage; "
            + "missing=" + ", ".join(missing) + "; unexpected=" + ", ".join(unexpected) + "."
        )
    for finding_id, finding in worker_findings.items():
        if not set(finding["supporting_artifact_ids"]).issubset(reviewed_ids):
            raise ValueError(f"G4 Worker finding {finding_id} cites an artifact outside the human-reviewed artifact set.")

    records = reviewed.get("findings")
    if not isinstance(records, list):
        raise ValueError("G4 reviewed_findings findings must be an array.")
    human_ids: list[str] = []
    dispositions: list[str] = []
    allowed_dispositions = {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES", "REJECT", "DEFER"}
    for index, item in enumerate(records):
        required = {"worker_finding_id", "disposition", "reviewer_rationale", "supporting_artifact_ids"}
        allowed = required | {"revised_finding_summary"}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - allowed:
            raise ValueError(f"G4 reviewed_findings item {index} has missing or unknown properties.")
        finding_id = item.get("worker_finding_id")
        disposition = item.get("disposition")
        rationale = item.get("reviewer_rationale")
        if not isinstance(finding_id, str) or not finding_id.strip():
            raise ValueError(f"G4 reviewed_findings item {index} requires worker_finding_id.")
        if not isinstance(disposition, str) or disposition not in allowed_dispositions:
            raise ValueError(f"G4 reviewed_findings item {finding_id} has an unsupported disposition.")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"G4 reviewed_findings item {finding_id} requires reviewer_rationale.")
        if disposition == "ACCEPT_WITH_CHANGES":
            revised = item.get("revised_finding_summary")
            if not isinstance(revised, str) or not revised.strip():
                raise ValueError(f"G4 finding {finding_id} requires revised_finding_summary for ACCEPT_WITH_CHANGES.")
        elif "revised_finding_summary" in item:
            raise ValueError(f"G4 finding {finding_id} may include revised_finding_summary only for ACCEPT_WITH_CHANGES.")
        supporting = item.get("supporting_artifact_ids")
        if (not isinstance(supporting, list)
                or any(not isinstance(ref, str) or not ref.strip() for ref in supporting)
                or len(supporting) != len(set(supporting))
                or any(ref not in reviewed_ids for ref in supporting)):
            raise ValueError(f"G4 finding {finding_id} references artifacts outside the reviewed artifact set.")
        if disposition in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"} and not supporting:
            raise ValueError(f"G4 accepted finding {finding_id} must cite at least one reviewed artifact.")
        if disposition == "ACCEPT_AS_IS":
            original = worker_findings.get(finding_id)
            if original and set(supporting) != set(original["supporting_artifact_ids"]):
                raise ValueError(f"G4 ACCEPT_AS_IS finding {finding_id} must preserve the Worker supporting artifact IDs.")
        human_ids.append(finding_id)
        dispositions.append(disposition)

    if len(human_ids) != len(set(human_ids)):
        raise ValueError("G4 reviewed_findings contains duplicate worker_finding_id values.")
    if set(human_ids) != set(worker_findings) or len(human_ids) != len(worker_findings):
        raise ValueError("G4 human dispositions must cover every Worker finding exactly once, with no unknown finding IDs.")

    if worker_result.get("status") in {"blocked", "failed"} and any(
        value in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"} for value in dispositions
    ):
        raise ValueError("G4 cannot promote findings from a blocked or failed Worker result.")

    accepted = sum(value in {"ACCEPT_AS_IS", "ACCEPT_WITH_CHANGES"} for value in dispositions)
    changed = dispositions.count("ACCEPT_WITH_CHANGES")
    deferred = dispositions.count("DEFER")
    decision = reviewed.get("promotion_decision")
    consistent = (
        (decision == "PROMOTE_ACCEPTED_ONLY" and accepted > 0 and changed == 0)
        or (decision == "PROMOTE_WITH_CHANGES" and accepted > 0 and changed > 0)
        or (decision == "DO_NOT_PROMOTE" and accepted == 0 and deferred == 0)
        or (decision == "DEFER" and accepted == 0 and deferred > 0)
    )
    if not consistent:
        raise ValueError("G4 promotion_decision is inconsistent with the individual human finding dispositions.")
    _validate_g4_publication_plan(by_id)

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
    if gate_id in {"G0", "G1", "G2"}:
        _validate_gate_review_packet(bindings, gate_id)
    if gate_id == "G1":
        _validate_g1_artifacts(bindings, latest_by_gate["G0"])
    elif gate_id == "G2":
        _validate_g2_artifacts(bindings, latest_by_gate["G1"])
    elif gate_id == "G3":
        _validate_g3_selection(bindings, latest_by_gate["G2"])
    elif gate_id == "G4":
        _validate_g4_reviewed_findings(bindings, latest_by_gate.get("G3"))


def require_selected_interaction_id(ledger_path: Path, interaction_id: str) -> dict[str, Any]:
    """Require a response-surface interaction to be the exact G3-selected candidate."""
    if not isinstance(interaction_id, str) or not interaction_id.strip():
        raise ValueError("A non-empty interaction_id is required.")
    require_gate(ledger_path, "G3")
    events = _load_events(Path(ledger_path).expanduser().resolve())
    event = next(item for item in reversed(events) if item["gate_id"] == "G3")
    by_id = {item["artifact_id"]: item for item in event["artifacts"]}
    selection_binding = _require_gate_binding(by_id, "interaction_selection", "G3")
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
    selection_binding = _require_gate_binding(by_id, "interaction_selection", "G3")
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
        if gate_id == "G4" and not G4_REVIEWABLE_ARTIFACTS.issubset(ids):
            raise ValueError(
                "G4 requires the complete six-artifact input set supplied to independent_result_review."
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
