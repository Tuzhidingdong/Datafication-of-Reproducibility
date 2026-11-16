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


def _route_and_profile(plan: dict[str, Any]) -> tuple[str | None, str]:
    stages = plan.get("stages")
    if not isinstance(stages, list):
        return None, "FULL_ANALYSIS"
    stage_ids = {
        item.get("stage_id") for item in stages if isinstance(item, dict)
    }
    if "source_audit" in stage_ids:
        route = "STRUCTURED_DATASET"
    elif "adapter_artifact_materialization" in stage_ids:
        route = "CANONICAL_BUNDLE"
    else:
        return None, str(plan.get("execution_profile", "FULL_ANALYSIS"))
    profile = plan.get("execution_profile", "FULL_ANALYSIS")
    if profile not in {"FULL_ANALYSIS", "CONTROLLED_SINGLE_STUDY"}:
        raise ValueError(f"Unsupported Run Plan execution_profile: {profile!r}.")
    return route, profile


def _select_route_variant(binding: dict[str, Any], route: str, profile: str) -> dict[str, Any] | None:
    variants = binding.get("route_variants", [])
    if not isinstance(variants, list):
        return None
    exact = next(
        (item for item in variants if isinstance(item, dict)
         and item.get("route") == route and item.get("profile") == profile),
        None,
    )
    if exact is not None:
        return exact
    # Existing route variants are the shared upstream implementation. They are
    # intentionally reused by profile-specific plans unless an explicit variant
    # overrides the same stage for that profile.
    return next(
        (item for item in variants if isinstance(item, dict)
         and item.get("route") == route and "profile" not in item),
        None,
    )


def _validate_argv_template(
    stage_id: str, template: Any, available_artifact_ids: set[str],
) -> None:
    """Validate the small, non-executable argument-binding language in the contract."""
    if not isinstance(template, list) or not template:
        raise ValueError(f"Local Stage {stage_id} has no automatic argv_template.")
    for index, token in enumerate(template):
        if isinstance(token, str):
            if not token:
                raise ValueError(f"Stage {stage_id} argv_template token {index} is empty.")
            continue
        if not isinstance(token, dict) or len(token) != 1:
            raise ValueError(f"Stage {stage_id} argv_template token {index} is malformed.")
        operation, value = next(iter(token.items()))
        if operation in {"artifact", "artifact_parent"}:
            if not isinstance(value, str) or value not in available_artifact_ids:
                raise ValueError(
                    f"Stage {stage_id} argv_template references unknown Artifact {value!r}."
                )
        elif operation == "run_root":
            if value is not True:
                raise ValueError(f"Stage {stage_id} run_root binding must be true.")
        elif operation in {"json_value", "single_json_array_item"}:
            if (
                not isinstance(value, dict)
                or set(value) != {"artifact_id", "pointer"}
                or value.get("artifact_id") not in available_artifact_ids
                or not isinstance(value.get("pointer"), str)
                or (value["pointer"] and not value["pointer"].startswith("/"))
            ):
                raise ValueError(
                    f"Stage {stage_id} argv_template {operation} binding must name a known Artifact and JSON pointer."
                )
        else:
            raise ValueError(
                f"Stage {stage_id} argv_template uses unsupported binding operation {operation!r}."
            )


def validate_supported_run_plan_execution_contract(plan: dict[str, Any]) -> None:
    """Fail closed when a supported adapter Run Plan drifts from its action contract.

    The two input routes each support the full-analysis profile and the explicitly
    bounded controlled-single-study profile. Other custom Run Plans remain extensible.
    """
    route, profile = _route_and_profile(plan)
    if route is None:
        return
    stages = plan["stages"]
    stage_ids = [item.get("stage_id") for item in stages if isinstance(item, dict)]
    contract = _load_contract()
    if profile == "FULL_ANALYSIS":
        expected_ids = contract.get("routes", {}).get(route)
    else:
        expected_ids = contract.get("profiles", {}).get(profile, {}).get(route)
    if not isinstance(expected_ids, list):
        raise ValueError(f"Stage execution contract does not declare {profile} profile for route {route}.")
    actual_ids = set(stage_ids)
    expected_set = set(expected_ids)
    if actual_ids != expected_set or len(stage_ids) != len(expected_ids):
        missing = sorted(expected_set - actual_ids)
        extra = sorted(actual_ids - expected_set)
        raise ValueError(
            f"Run Plan stage set differs from the {route}/{profile} execution contract; "
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

    available_artifact_ids = {
        item.get("artifact_id") for item in plan.get("source_artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    }
    available_artifact_ids.update(
        output.get("artifact_id")
        for stage in stages if isinstance(stage, dict)
        for output in stage.get("outputs", []) if isinstance(output, dict)
        and isinstance(output.get("artifact_id"), str)
    )

    for stage in stages:
        stage_id = stage["stage_id"]
        binding = by_id.get(stage_id)
        if binding is None:
            raise ValueError(f"Stage {stage_id} has no execution action binding.")
        variant = _select_route_variant(binding, route, profile)
        if variant is None:
            raise ValueError(f"Stage {stage_id} has no {route}/{profile} execution variant.")
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

        if executor == "local":
            if not isinstance(binding.get("cli_command"), str):
                raise ValueError(f"Local Stage {stage_id} has no Runtime CLI command.")
            _validate_argv_template(
                stage_id, variant.get("argv_template"), available_artifact_ids,
            )
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
    route, profile = _route_and_profile(plan)
    if route is None:
        return {}
    stages = plan.get("stages")
    stage_ids = {
        item.get("stage_id") for item in stages if isinstance(item, dict)
    }
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
        variant = _select_route_variant(binding, route, profile)
        if variant is None:
            raise ValueError(f"Stage {stage_id} has no {route} execution variant.")
        result[stage_id] = {
            "route": route,
            "execution_profile": profile,
            "action_type": binding.get("action_type"),
            "executor": variant.get("executor"),
            "runtime_command": binding.get("cli_command"),
            "validator_command": binding.get("validator_command"),
            "authorization_command": binding.get("authorization_command"),
            "host_action": binding.get("host_action"),
            "argv_template": variant.get("argv_template"),
        }
    return result


def inspect_supported_run_plan_execution_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a compact validation report for a supported Run Plan's action bindings."""
    validate_supported_run_plan_execution_contract(plan)
    stage_ids = [item["stage_id"] for item in plan["stages"]]
    route, profile = _route_and_profile(plan)
    if route is None:
        raise ValueError("Run Plan is not one of the supported adapter routes.")
    contract = _load_contract()
    binding_by_id = {item["stage_id"]: item for item in contract["stages"]}
    action_counts: dict[str, int] = {}
    actions = []
    for stage_id in stage_ids:
        binding = binding_by_id[stage_id]
        variant = _select_route_variant(binding, route, profile)
        if variant is None:
            raise ValueError(f"Stage {stage_id} has no {route}/{profile} execution variant.")
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
        "execution_profile": profile,
        "stage_count": len(stage_ids),
        "action_counts": action_counts,
        "stage_actions": actions,
        "validation_scope": "SUPPORTED_RUN_PLAN_TO_RUNTIME_AND_HOST_ACTION_BINDINGS_ONLY",
    }

