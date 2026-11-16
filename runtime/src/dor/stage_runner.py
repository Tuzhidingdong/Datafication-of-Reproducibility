"""Contract-bound execution of one local Run stage.

The runner owns Run Manager status transitions; the stage CLI remains the
single implementation of scientific and data-processing behaviour.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from dor.execution_contract import stage_action_bindings_for_plan
from dor.mapping import sha256_file
from dor.run_manager import (
    _artifact_path,
    _manifest_context,
    _stage_map,
    build_resume_plan,
    record_stage_status,
)

_GATED_COMMANDS = {
    "build-canonical",
    "build-cohort",
    "fit-baselines",
    "evaluate-reproducibility",
    "discover-interactions",
    "assess-interaction-robustness",
    "generate-interaction-surface",
    "build-mechanism-evidence-bridge",
    "build-publication-package",
    "predict-virtual-condition",
}
_COHORT_REVIEW_COMMANDS = {
    "fit-baselines",
    "evaluate-reproducibility",
    "discover-interactions",
    "assess-interaction-robustness",
    "generate-interaction-surface",
    "build-mechanism-evidence-bridge",
}
_EXPLICIT_LEDGER_COMMANDS = {
    "validate-single-study-applicability",
    "prepare-single-study-not-applicable-artifacts",
}


def _normalise_arguments(arguments: Sequence[str]) -> list[str]:
    if isinstance(arguments, (str, bytes)):
        raise ValueError("CLI arguments must be a sequence of individual strings, not one command string.")
    result = list(arguments)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError("Every CLI argument must be a non-empty string.")
    forbidden = {"--allow-untracked-legacy", "--workflow-ledger", "--run-manifest"}
    supplied = {
        item for item in result
        if item in forbidden or any(item.startswith(option + "=") for option in forbidden)
    }
    if supplied:
        raise ValueError(
            "The runner controls workflow trust arguments; do not supply "
            + ", ".join(sorted(supplied))
            + "."
        )
    return result


def _runtime_environment() -> dict[str, str]:
    """Make the exact Runtime package loaded by this process importable to the child."""
    environment = os.environ.copy()
    runtime_src = str(Path(__file__).resolve().parent.parent)
    existing = environment.get("PYTHONPATH")
    entries = [runtime_src]
    if existing:
        entries.extend(item for item in existing.split(os.pathsep) if item and item != runtime_src)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


def _format_archived_outputs(records: list[dict[str, Any]]) -> str:
    """Render preserved output evidence as readable, directly searchable text."""
    return "; ".join(
        "artifact_id={artifact_id} path={archive_path} sha256={sha256}".format(
            artifact_id=item["artifact_id"],
            archive_path=item["archive_path"],
            sha256=item.get("sha256") or "UNHASHED_NON_FILE",
        )
        for item in records
    )


def _archive_outputs(
    root: Path,
    stage: dict[str, Any],
    attempt: int,
    category: str,
) -> list[dict[str, Any]]:
    """Move existing declared outputs aside without deleting failed/stale work."""
    existing = [
        (output, _artifact_path(root, output))
        for output in stage["outputs"]
        if _artifact_path(root, output).exists()
    ]
    if not existing:
        return []
    archive_root = root / ".dor_attempt_archive" / stage["stage_id"] / f"{category}-{attempt:04d}"
    if archive_root.exists():
        raise FileExistsError(f"Attempt archive already exists; refusing to overwrite: {archive_root}")
    archive_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for output, source in existing:
        relative = Path(output["path"])
        destination = archive_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256_file(source) if source.is_file() else None
        os.replace(source, destination)
        records.append({
            "artifact_id": output["artifact_id"],
            "original_path": str(source),
            "archive_path": str(destination),
            "sha256": digest,
        })
    manifest = {
        "schema_version": "1.0",
        "stage_id": stage["stage_id"],
        "attempt": attempt,
        "category": category,
        "archived_outputs": records,
        "policy": "PRESERVED_BEFORE_REBUILD_OR_AFTER_FAILED_LOCAL_EXECUTION",
    }
    (archive_root / "archive_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return records


class StageArgumentBindingError(ValueError):
    """A contract-bound stage needs an explicit input before it can run."""

    def __init__(self, message: str, status: str = "INPUT_REQUIRED"):
        super().__init__(message)
        self.status = status


def _artifact_definitions(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = {
        item["artifact_id"]: {**item, "kind": "source"}
        for item in plan.get("source_artifacts", [])
    }
    for stage in plan.get("stages", []):
        for output in stage.get("outputs", []):
            definitions[output["artifact_id"]] = output
    return definitions


def _json_pointer_value(document: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "":
        return True, document
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _artifact_json_value(
    root: Path, definitions: dict[str, dict[str, Any]],
    artifact_id: str, pointer: str,
) -> Any:
    definition = definitions.get(artifact_id)
    if definition is None:
        raise ValueError(f"Argument binding references unknown Artifact {artifact_id!r}.")
    path = _artifact_path(root, definition)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageArgumentBindingError(
            f"Stage input Artifact {artifact_id!r} must contain readable JSON before this command can be assembled: {exc}"
        ) from exc
    found, value = _json_pointer_value(document, pointer)
    if not found:
        raise StageArgumentBindingError(
            f"Stage input {artifact_id!r} does not contain the required JSON field {pointer!r}."
        )
    return value


def _bind_contract_arguments(
    template: Any, root: Path, plan: dict[str, Any],
) -> list[str]:
    if not isinstance(template, list) or not template:
        raise StageArgumentBindingError(
            "This local Stage has no automatic argv_template; supply an explicit argument file for this custom Stage.",
            status="ARGUMENTS_REQUIRED",
        )
    definitions = _artifact_definitions(plan)
    arguments: list[str] = []
    for index, token in enumerate(template):
        if isinstance(token, str):
            if not token:
                raise ValueError(f"Automatic argument template contains an empty token at index {index}.")
            arguments.append(token)
            continue
        if not isinstance(token, dict) or len(token) != 1:
            raise ValueError(f"Automatic argument template token {index} is malformed.")
        operation, value = next(iter(token.items()))
        if operation in {"artifact", "artifact_parent"}:
            if not isinstance(value, str) or value not in definitions:
                raise ValueError(f"Automatic argument template references unknown Artifact {value!r}.")
            path = _artifact_path(root, definitions[value])
            resolved = path if operation == "artifact" else path.parent
            arguments.append(str(resolved))
        elif operation == "run_root":
            if value is not True:
                raise ValueError("run_root argument binding must be true.")
            arguments.append(str(root))
        elif operation in {"json_value", "single_json_array_item"}:
            if not isinstance(value, dict):
                raise ValueError(f"Automatic {operation} binding is malformed.")
            artifact_id = value.get("artifact_id")
            pointer = value.get("pointer")
            if not isinstance(artifact_id, str) or not isinstance(pointer, str):
                raise ValueError(f"Automatic {operation} binding requires artifact_id and pointer.")
            selected = _artifact_json_value(root, definitions, artifact_id, pointer)
            if operation == "single_json_array_item":
                if not isinstance(selected, list) or len(selected) != 1:
                    count = len(selected) if isinstance(selected, list) else "not an array"
                    raise StageArgumentBindingError(
                        f"Stage requires exactly one selected value at {artifact_id}:{pointer}; found {count}. "
                        "Review the selection record and choose exactly one item before continuing."
                    )
                selected = selected[0]
            if not isinstance(selected, str) or not selected.strip():
                raise StageArgumentBindingError(
                    f"Required value at {artifact_id}:{pointer} must be a non-empty string."
                )
            arguments.append(selected)
        else:
            raise ValueError(f"Unsupported automatic argument binding operation: {operation!r}.")
    return arguments


def execute_local_stage(
    manifest_path: Path,
    stage_id: str,
    arguments: Sequence[str] | None = None,
    timeout_seconds: int = 3600,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the next eligible local CLI stage and record its outcome.

    Only the CLI subcommand bound by the checked-in execution contract can run.
    Arguments are passed as an argv array (never through a shell). Gate ledger
    and Run manifest arguments are injected by the runner for commands that
    enforce them.
    """
    if type(timeout_seconds) is not int or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be a positive integer.")
    root, manifest, plan, _events = _manifest_context(manifest_path)
    stages = _stage_map(plan)
    stage = stages.get(stage_id)
    if stage is None:
        raise ValueError(f"Unknown stage_id: {stage_id}.")
    if stage.get("executor", "local") != "local":
        raise ValueError(
            f"Stage {stage_id} is {stage.get('executor')} executed; "
            "the local runner never substitutes for manual review or Worker dispatch."
        )

    resume = build_resume_plan(manifest_path)
    state = next(item for item in resume["stages"] if item["stage_id"] == stage_id)
    if state["action"] not in {"READY_TO_RUN", "RETRY_REQUIRED", "REBUILD_REQUIRED"}:
        raise ValueError(
            f"Stage {stage_id} is not executable now (action={state['action']}). "
            "Resolve dependencies, Gate approval, or interruption state first."
        )

    bindings = stage_action_bindings_for_plan(plan)
    binding = bindings.get(stage_id)
    runtime_command = binding.get("runtime_command") if isinstance(binding, dict) else None
    if not isinstance(runtime_command, str) or not runtime_command.strip():
        raise ValueError(
            f"Stage {stage_id} has no contract-bound Runtime CLI command; "
            "custom/unbound stages must use their explicitly configured executor."
        )
    if any(character.isspace() for character in runtime_command):
        raise ValueError(f"Invalid Runtime CLI command binding for stage {stage_id}.")

    argument_source = "EXPLICIT"
    if arguments is None:
        cli_arguments = _bind_contract_arguments(
            binding.get("argv_template"), root, plan,
        )
        argument_source = "EXECUTION_CONTRACT"
    else:
        if isinstance(binding.get("argv_template"), list) and binding.get("argv_template"):
            raise ValueError(
                f"Stage {stage_id} has a machine-declared argv_template; "
                "supported Run stages must use Artifact-bound automatic arguments, not an args-file override."
            )
        cli_arguments = _normalise_arguments(arguments)
    workflow_ledger = manifest.get("workflow_ledger_path")
    if runtime_command in _GATED_COMMANDS or runtime_command in _EXPLICIT_LEDGER_COMMANDS:
        if not workflow_ledger:
            raise ValueError(
                f"Stage {stage_id} requires a configured workflow_ledger_path in the Run Plan."
            )
        cli_arguments.extend(["--workflow-ledger", str(workflow_ledger)])
    if runtime_command in _COHORT_REVIEW_COMMANDS:
        cli_arguments.extend(["--run-manifest", str(Path(manifest_path).expanduser().resolve())])

    command = [sys.executable, "-m", "dor.cli", runtime_command, *cli_arguments]
    if dry_run:
        return {
            "status": "DRY_RUN",
            "run_id": manifest["run_id"],
            "stage_id": stage_id,
            "action": state["action"],
            "executor": "local",
            "command_argv": command,
            "cwd": str(root),
            "timeout_seconds": timeout_seconds,
            "argument_source": argument_source,
            "outputs": [
                {"artifact_id": item["artifact_id"], "path": str(_artifact_path(root, item))}
                for item in stage["outputs"]
            ],
        }

    attempt = int(state.get("attempt", 0)) + 1
    archived_before = _archive_outputs(root, stage, attempt, "before-retry")
    producer_command = json.dumps(
        {"argv": command, "archived_before": archived_before},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    running = record_stage_status(
        manifest_path,
        stage_id,
        "RUNNING",
        "local",
        command=producer_command,
    )
    attempt = int(running["attempt"])

    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            check=False,
            timeout=timeout_seconds,
            env=_runtime_environment(),
        )
        return_code = int(completed.returncode)
        failure_reason = (
            None if return_code == 0
            else f"Contract-bound command {runtime_command} exited with code {return_code}."
        )
    except subprocess.TimeoutExpired:
        return_code = -1
        failure_reason = (
            f"Contract-bound command {runtime_command} exceeded timeout "
            f"of {timeout_seconds} seconds."
        )
    except OSError as exc:
        return_code = -1
        failure_reason = f"Could not start contract-bound command {runtime_command}: {exc}"

    if failure_reason is not None:
        archived_after = _archive_outputs(root, stage, attempt, "failed")
        event_reason = failure_reason
        if archived_after:
            event_reason += " Preserved partial outputs: " + _format_archived_outputs(archived_after)
        failed = record_stage_status(
            manifest_path,
            stage_id,
            "FAILED",
            "local",
            command=producer_command,
            reason=event_reason,
        )
        return {
            "status": "FAILED",
            "run_id": manifest["run_id"],
            "stage_id": stage_id,
            "attempt": attempt,
            "return_code": return_code,
            "reason": failure_reason,
            "argument_source": argument_source,
            "command_argv": command,
            "archived_before": archived_before,
            "archived_after": archived_after,
            "event_hash": failed["event_hash"],
        }

    try:
        succeeded = record_stage_status(
            manifest_path,
            stage_id,
            "SUCCEEDED",
            "local",
            command=producer_command,
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        archived_after = _archive_outputs(root, stage, attempt, "output-contract-failed")
        reason = f"Command exited 0 but the declared output contract was not met: {exc}"
        if archived_after:
            reason += " Preserved partial outputs: " + _format_archived_outputs(archived_after)
        failed = record_stage_status(
            manifest_path,
            stage_id,
            "FAILED",
            "local",
            command=producer_command,
            reason=reason,
        )
        return {
            "status": "FAILED_OUTPUT_CONTRACT",
            "run_id": manifest["run_id"],
            "stage_id": stage_id,
            "attempt": attempt,
            "return_code": 0,
            "reason": reason,
            "argument_source": argument_source,
            "command_argv": command,
            "archived_before": archived_before,
            "archived_after": archived_after,
            "event_hash": failed["event_hash"],
        }

    return {
        "status": "SUCCEEDED",
        "run_id": manifest["run_id"],
        "stage_id": stage_id,
        "attempt": attempt,
        "return_code": 0,
        "argument_source": argument_source,
        "command_argv": command,
        "archived_before": archived_before,
        "event_hash": succeeded["event_hash"],
        "next_actions": build_resume_plan(manifest_path)["next_actions"],
    }


def advance_run(
    manifest_path: Path,
    arguments_dir: Path | None = None,
    max_local_stages: int = 10,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run consecutive local stages until a human/Worker/Gate/input boundary.

    Supported adapter Runs derive argv from the execution contract. An optional
    arguments directory can override argv for custom or explicitly exceptional stages.
    Missing or ambiguous user-choice values are returned as actionable pauses.
    """
    if type(max_local_stages) is not int or max_local_stages < 1:
        raise ValueError("max_local_stages must be a positive integer.")
    arguments_root = None
    if arguments_dir is not None:
        arguments_root = arguments_dir.expanduser().resolve(strict=True)
        if not arguments_root.is_dir():
            raise NotADirectoryError(f"Stage arguments path must be a directory: {arguments_root}")

    completed: list[dict[str, Any]] = []
    for _ in range(max_local_stages):
        root, manifest, plan, _events = _manifest_context(manifest_path)
        resume = build_resume_plan(manifest_path)
        next_actions = resume.get("next_actions", [])
        if not next_actions:
            gate_blockers = [
                item for item in resume["stages"]
                if item["action"] == "BLOCKED_GATE"
            ]
            if gate_blockers:
                blocker = gate_blockers[0]
                stage = _stage_map(plan)[blocker["stage_id"]]
                return {
                    "status": "PAUSED_FOR_GATE",
                    "run_id": manifest["run_id"],
                    "completed_local_stages": completed,
                    "required_gate": stage.get("required_gate"),
                    "stage_id": blocker["stage_id"],
                    "reasons": blocker.get("reasons", []),
                    "action_binding": blocker.get("action_binding"),
                }
            unresolved = [
                item for item in resume["stages"]
                if item["action"] not in {"REUSE", "SKIPPED"}
            ]
            if not unresolved:
                return {
                    "status": "COMPLETE",
                    "run_id": manifest["run_id"],
                    "completed_local_stages": completed,
                    "next_actions": [],
                }
            return {
                "status": "BLOCKED",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "unresolved_stages": unresolved,
            }

        next_action = next_actions[0]
        stage_id = next_action["stage_id"]
        stage = _stage_map(plan)[stage_id]
        executor = stage.get("executor", "local")
        if next_action["action"] == "SKIP_REQUIRED":
            skipped = record_stage_status(
                manifest_path,
                stage_id,
                "SKIPPED",
                executor,
                reason="Run Manager evaluated the declared stage activation condition as INACTIVE.",
            )
            completed.append({
                "stage_id": stage_id,
                "status": "SKIPPED",
                "event_hash": skipped["event_hash"],
            })
            continue

        action_binding = next_action.get("action_binding")
        if executor == "manual":
            return {
                "status": "PAUSED_FOR_HUMAN",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "required_gate": stage.get("required_gate"),
                "action": next_action["action"],
                "reasons": next_action.get("reasons", []),
                "action_binding": action_binding,
                "required_inputs": action_binding.get("input_artifacts", []) if action_binding else [],
                "required_outputs": action_binding.get("output_artifacts", []) if action_binding else [],
            }
        if executor == "worker":
            return {
                "status": "PAUSED_FOR_WORKER_AUTHORIZATION",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "required_gate": stage.get("required_gate"),
                "action": next_action["action"],
                "reasons": next_action.get("reasons", []),
                "action_binding": action_binding,
                "worker_task": stage.get("worker_task"),
                "authorization_required": True,
                "dispatch_performed": False,
            }
        if executor != "local":
            return {
                "status": "BLOCKED",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "reason": f"Unsupported stage executor: {executor}.",
            }

        args_path = arguments_root / f"{stage_id}.json" if arguments_root is not None else None
        arguments = None
        has_automatic_binding = (
            isinstance(action_binding, dict)
            and isinstance(action_binding.get("argv_template"), list)
            and bool(action_binding.get("argv_template"))
        )
        if has_automatic_binding and args_path is not None and args_path.is_file():
            return {
                "status": "ARGUMENT_OVERRIDE_NOT_ALLOWED",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "arguments_file": str(args_path),
                "reason": (
                    "This supported Run Stage is bound to the checked-in argv_template. "
                    "Remove the manual override file and let Run Manager derive arguments from its Artifacts."
                ),
                "action_binding": action_binding,
            }
        if not has_automatic_binding and args_path is not None and args_path.is_file():
            try:
                arguments = json.loads(args_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                return {
                    "status": "INVALID_ARGUMENTS_FILE",
                    "run_id": manifest["run_id"],
                    "completed_local_stages": completed,
                    "stage_id": stage_id,
                    "arguments_file": str(args_path),
                    "reason": str(exc),
                }
            if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
                return {
                    "status": "INVALID_ARGUMENTS_FILE",
                    "run_id": manifest["run_id"],
                    "completed_local_stages": completed,
                    "stage_id": stage_id,
                    "arguments_file": str(args_path),
                    "reason": "Arguments file must contain a JSON array of strings.",
                }
        if arguments is None and not has_automatic_binding:
            return {
                "status": "ARGUMENTS_REQUIRED",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "action": next_action["action"],
                "arguments_file": str(args_path) if args_path is not None else None,
                "reason": (
                    "This custom/unbound Stage has no automatic argv_template. "
                    "Supply an explicit per-stage argv override before execution."
                ),
                "action_binding": action_binding,
                "required_inputs": action_binding.get("input_artifacts", []) if action_binding else [],
                "required_outputs": action_binding.get("output_artifacts", []) if action_binding else [],
            }
        try:
            result = execute_local_stage(
                manifest_path,
                stage_id,
                arguments,
                timeout_seconds=timeout_seconds,
            )
        except StageArgumentBindingError as exc:
            return {
                "status": exc.status,
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "stage_id": stage_id,
                "action": next_action["action"],
                "reason": str(exc),
                "action_binding": action_binding,
                "required_inputs": action_binding.get("input_artifacts", []) if action_binding else [],
                "required_outputs": action_binding.get("output_artifacts", []) if action_binding else [],
            }
        completed.append({
            "stage_id": stage_id,
            "status": result["status"],
            "attempt": result.get("attempt"),
            "event_hash": result.get("event_hash"),
            "command_argv": result.get("command_argv"),
            "argument_source": result.get("argument_source"),
        })
        if result["status"] != "SUCCEEDED":
            return {
                "status": "LOCAL_STAGE_FAILED",
                "run_id": manifest["run_id"],
                "completed_local_stages": completed,
                "failed_stage": result,
            }

    latest = build_resume_plan(manifest_path)
    return {
        "status": "YIELDED_AFTER_LOCAL_STAGE_LIMIT",
        "run_id": latest["run_id"],
        "completed_local_stages": completed,
        "next_actions": latest["next_actions"],
        "max_local_stages": max_local_stages,
    }
