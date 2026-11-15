"""Validate supported Run Plan stage graphs against executable action bindings."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONTRACT_PATH = Path(__file__).with_name("stage_execution_contract.json")


def _load_contract() -> dict[str, Any]:
    try:
        payload = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Bundled Stage execution contract is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise RuntimeError("Bundled Stage execution contract has an unsupported schema_version.")
    return payload


def _output_signature(outputs: Any) -> list[dict[str, str]]:
    if not isinstance(outputs, list):
        return []
    result = []
    for output in outputs:
        if not isinstance(output, dict):
            return []
        result.append({
            "artifact_id": output.get("artifact_id"),
            "path": output.get("path"),
            "kind": output.get("kind", "derived"),
        })
    return result


def validate_supported_run_plan_execution_contract(plan: dict[str, Any]) -> None:
    """Fail closed when a supported adapter Run Plan drifts from its action contract.

    Custom Run Plans outside the two published adapter routes remain extensible.
    """
    stages = plan.get("stages")
    if not isinstance(stages, list):
        return
    stage_ids = [item.get("stage_id") for item in stages if isinstance(item, dict)]
    if "source_audit" in stage_ids:
        route = "STRUCTURED_DATASET"
    elif "adapter_artifact_materialization" in stage_ids:
        route = "CANONICAL_BUNDLE"
    else:
        return

    contract = _load_contract()
    routes = contract.get("routes", {})
    expected_ids = routes.get(route)
    if not isinstance(expected_ids, list):
        raise ValueError(f"Stage execution contract does not declare route {route}.")
    actual_ids = set(stage_ids)
    expected_set = set(expected_ids)
    if actual_ids != expected_set:
        missing = sorted(expected_set - actual_ids)
        extra = sorted(actual_ids - expected_set)
        raise ValueError(
            f"Run Plan stage set differs from the {route} execution contract; "
            f"missing={missing}, extra={extra}."
        )

    bindings = contract.get("stages")
    if not isinstance(bindings, list):
        raise RuntimeError("Bundled Stage execution contract has no stages array.")
    by_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get("stage_id"), str):
            raise RuntimeError("Bundled Stage execution contract contains a malformed stage binding.")
        if binding["stage_id"] in by_id:
            raise RuntimeError(f"Duplicate Stage execution binding: {binding['stage_id']}.")
        by_id[binding["stage_id"]] = binding

    for stage in stages:
        stage_id = stage["stage_id"]
        binding = by_id.get(stage_id)
        if binding is None:
            raise ValueError(f"Stage {stage_id} has no execution action binding.")
        variant = next(
            (item for item in binding.get("route_variants", [])
             if isinstance(item, dict) and item.get("route") == route),
            None,
        )
        if variant is None:
            raise ValueError(f"Stage {stage_id} has no {route} execution variant.")
        executor = stage.get("executor", "local")
        if executor != variant.get("executor"):
            raise ValueError(
                f"Stage {stage_id} executor drift: Run Plan declares {executor}, "
                f"execution contract declares {variant.get('executor')}."
            )
        if binding.get("action_type") != {"local": "CLI", "manual": "MANUAL", "worker": "WORKER"}[executor]:
            raise ValueError(f"Stage {stage_id} action_type does not match executor {executor}.")
        if list(stage.get("depends_on", [])) != list(variant.get("depends_on", [])):
            raise ValueError(f"Stage {stage_id} dependencies differ from its execution contract.")
        if list(stage.get("inputs", [])) != list(variant.get("inputs", [])):
            raise ValueError(f"Stage {stage_id} input Artifact IDs differ from its execution contract.")
        if _output_signature(stage.get("outputs")) != variant.get("outputs"):
            raise ValueError(f"Stage {stage_id} output Artifact IDs/paths/kinds differ from its execution contract.")
        if stage.get("required_gate") != variant.get("required_gate"):
            raise ValueError(f"Stage {stage_id} required_gate differs from its execution contract.")
        if stage.get("activation") != variant.get("activation"):
            raise ValueError(f"Stage {stage_id} activation condition differs from its execution contract.")

        if executor == "local" and not isinstance(binding.get("cli_command"), str):
            raise ValueError(f"Local Stage {stage_id} has no Runtime CLI command.")
        if executor == "worker" and not all(
            isinstance(binding.get(key), str) and binding[key]
            for key in ("authorization_command", "host_action")
        ):
            raise ValueError(f"Worker Stage {stage_id} has no authorization/dispatch action.")


def stage_action_bindings_for_plan(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the machine-declared action binding for each stage in a supported route.

    Custom Run Plans intentionally return an empty mapping. The caller remains
    responsible for validating supported plans before relying on these bindings.
    """
    stages = plan.get("stages")
    if not isinstance(stages, list):
        return {}
    stage_ids = {
        item.get("stage_id") for item in stages if isinstance(item, dict)
    }
    if "source_audit" in stage_ids:
        route = "STRUCTURED_DATASET"
    elif "adapter_artifact_materialization" in stage_ids:
        route = "CANONICAL_BUNDLE"
    else:
        return {}

    contract = _load_contract()
    bindings = contract.get("stages")
    if not isinstance(bindings, list):
        raise RuntimeError("Bundled Stage execution contract has no stages array.")
    by_id = {
        item["stage_id"]: item for item in bindings
        if isinstance(item, dict) and isinstance(item.get("stage_id"), str)
    }
    result: dict[str, dict[str, Any]] = {}
    for stage_id in stage_ids:
        binding = by_id.get(stage_id)
        if binding is None:
            raise ValueError(f"Stage {stage_id} has no execution action binding.")
        variant = next(
            (item for item in binding.get("route_variants", [])
             if isinstance(item, dict) and item.get("route") == route),
            None,
        )
        if variant is None:
            raise ValueError(f"Stage {stage_id} has no {route} execution variant.")
        result[stage_id] = {
            "route": route,
            "action_type": binding.get("action_type"),
            "executor": variant.get("executor"),
            "runtime_command": binding.get("cli_command"),
            "validator_command": binding.get("validator_command"),
            "authorization_command": binding.get("authorization_command"),
            "host_action": binding.get("host_action"),
        }
    return result


def inspect_supported_run_plan_execution_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a compact validation report for a supported Run Plan's action bindings."""
    validate_supported_run_plan_execution_contract(plan)
    stage_ids = [item["stage_id"] for item in plan["stages"]]
    route = "STRUCTURED_DATASET" if "source_audit" in stage_ids else "CANONICAL_BUNDLE"
    contract = _load_contract()
    binding_by_id = {item["stage_id"]: item for item in contract["stages"]}
    action_counts: dict[str, int] = {}
    actions = []
    for stage_id in stage_ids:
        binding = binding_by_id[stage_id]
        kind = binding["action_type"]
        action_counts[kind] = action_counts.get(kind, 0) + 1
        actions.append({
            "stage_id": stage_id,
            "action_type": kind,
            "cli_command": binding.get("cli_command"),
            "validator_command": binding.get("validator_command"),
            "authorization_command": binding.get("authorization_command"),
        })
    return {
        "schema_version": "1.0",
        "valid": True,
        "route": route,
        "stage_count": len(stage_ids),
        "action_counts": action_counts,
        "stage_actions": actions,
        "validation_scope": "SUPPORTED_RUN_PLAN_TO_RUNTIME_AND_HOST_ACTION_BINDINGS_ONLY",
    }

