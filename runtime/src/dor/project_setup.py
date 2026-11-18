"""Prepare a project-specific Run Plan from a validated Adapter handoff.

This module selects only the repository's supported generic route/profile templates.
It does not infer scientific scope, mappings, Study counts, or analysis suitability.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from dor.adapter_handoff import prepare_adapter_handoff_files
from dor.run_manager import _validate_plan
from dor.semantic_registry import validate_semantic_registry_file

_PROFILES = {"CONTROLLED_SINGLE_STUDY", "FULL_ANALYSIS"}
_ACCEPTANCE_ROLES = {
    "PRIMARY_PAPER",
    "SUPPLEMENTARY_INFORMATION",
    "STRUCTURED_DATA",
    "OTHER",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _repository_root() -> Path:
    # runtime/src/dor/project_setup.py -> repository root
    return Path(__file__).resolve().parents[3]


def _default_project_id(project_root: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", project_root.name).strip("._-")[:128]
    if not value or not value[0].isalnum():
        value = "project-" + value
    if not _ID.fullmatch(value):
        raise ValueError("Could not derive a safe project_id; supply --project-id explicitly.")
    return value


def _parse_acceptance_source(value: str) -> dict[str, str]:
    parts = value.split("=", 2)
    if len(parts) != 3 or not all(item.strip() for item in parts):
        raise ValueError(
            "--acceptance-source must use SOURCE_ID=ROLE=FILE_PATH syntax."
        )
    source_id, role, raw_path = (item.strip() for item in parts)
    if not _ID.fullmatch(source_id):
        raise ValueError(f"Invalid acceptance source ID: {source_id!r}.")
    if role not in _ACCEPTANCE_ROLES:
        raise ValueError(
            f"Unsupported acceptance source role {role!r}; expected one of "
            + ", ".join(sorted(_ACCEPTANCE_ROLES))
            + "."
        )
    path = Path(raw_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Acceptance source must be a file: {path}")
    return {"source_id": source_id, "role": role, "path": str(path)}


def _unique_directories(paths: list[Path]) -> list[str]:
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"Run Plan source root is not a directory: {resolved}")
        unique[str(resolved)] = resolved
    return sorted(unique)


def _template_names(route: str, profile: str) -> tuple[str, str, str]:
    if route == "STRUCTURED_DATASET":
        if profile == "CONTROLLED_SINGLE_STUDY":
            return (
                "run_plan.single_study.example.json",
                "publication_package_plan.single_study.example.json",
                "structured_dataset.single_study",
            )
        return (
            "run_plan.example.json",
            "publication_package_plan.example.json",
            "structured_dataset.full_analysis",
        )
    if route == "CANONICAL_BUNDLE":
        if profile == "CONTROLLED_SINGLE_STUDY":
            return (
                "run_plan.canonical_adapter.single_study.example.json",
                "publication_package_plan.canonical_adapter.single_study.example.json",
                "canonical_bundle.single_study",
            )
        return (
            "run_plan.canonical_adapter.example.json",
            "publication_package_plan.example.json",
            "canonical_bundle.full_analysis",
        )
    raise ValueError(f"Unsupported Adapter route: {route!r}.")


def initialize_project_run_plan(
    adapter_handoff_path: Path,
    project_root: Path,
    run_root: Path,
    profile: str = "CONTROLLED_SINGLE_STUDY",
    project_id: str | None = None,
    workflow_ledger_path: Path | None = None,
    virtual_query_input: Path | None = None,
    publication_plan_template: Path | None = None,
    acceptance_sources: list[str] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Create and validate a non-overwriting project-specific Run Plan.

    FULL_ANALYSIS Runs no longer require a pre-generated Virtual Query at
    initialization. A formal, human-provided query is prepared later after the
    modeling task is confirmed.
    """
    if profile not in _PROFILES:
        raise ValueError(f"profile must be one of {sorted(_PROFILES)}.")

    handoff_file = adapter_handoff_path.expanduser().resolve(strict=True)
    if not handoff_file.is_file():
        raise ValueError(f"Adapter handoff is not a file: {handoff_file}")
    try:
        handoff_payload = json.loads(handoff_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Adapter handoff is not valid JSON: {exc}") from exc
    if not isinstance(handoff_payload, dict) or handoff_payload.get("valid") is not True:
        raise ValueError("Adapter handoff must be a valid, successful preflight report.")

    manifest_path = Path(handoff_payload.get("manifest_path", "")).expanduser()
    package_root = Path(handoff_payload.get("package_root", "")).expanduser()
    refreshed = prepare_adapter_handoff_files(manifest_path, package_root)
    if (
        refreshed.get("route") != handoff_payload.get("route")
        or refreshed.get("manifest_sha256") != handoff_payload.get("manifest_sha256")
    ):
        raise ValueError(
            "Adapter handoff is stale or its route/manifest binding changed; regenerate the handoff."
        )
    route = refreshed["route"]

    manifest_payload = json.loads(
        manifest_path.resolve(strict=True).read_text(encoding="utf-8-sig")
    )
    if route == "CANONICAL_BUNDLE":
        roles = [item.get("role") for item in manifest_payload.get("artifacts", [])]
        for required_role in ("source_inventory", "mapping_plan", "build_spec", "canonical_bundle"):
            count = roles.count(required_role)
            if count != 1:
                raise ValueError(
                    "CANONICAL_BUNDLE formal Runs require exactly one artifact for role "
                    f"{required_role!r}; found {count}."
                )

    root = project_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")

    if profile == "FULL_ANALYSIS":
        if virtual_query_input is not None:
            virtual_path = virtual_query_input.expanduser().resolve(strict=True)
            if not virtual_path.is_file():
                raise ValueError(f"Virtual reproduction query must be a file: {virtual_path}")
        else:
            virtual_path = None
    else:
        if virtual_query_input is not None:
            raise ValueError(
                "CONTROLLED_SINGLE_STUDY does not consume a virtual query; omit --virtual-query-input."
            )
        virtual_path = None

    acceptance_records = [
        _parse_acceptance_source(item) for item in (acceptance_sources or [])
    ]
    acceptance_ids = [item["source_id"] for item in acceptance_records]
    if len(acceptance_ids) != len(set(acceptance_ids)):
        raise ValueError("Acceptance source IDs must be unique.")
    if profile == "CONTROLLED_SINGLE_STUDY" and acceptance_records:
        supplied_roles = {item["role"] for item in acceptance_records}
        required_roles = {"PRIMARY_PAPER", "SUPPLEMENTARY_INFORMATION"}
        missing_roles = sorted(required_roles - supplied_roles)
        if missing_roles:
            raise ValueError(
                "A controlled single-Study V1.0 Acceptance source snapshot requires both "
                "PRIMARY_PAPER and SUPPLEMENTARY_INFORMATION; missing: "
                + ", ".join(missing_roles)
                + ". Add the linked source files explicitly or omit --acceptance-source "
                "only when this Run will not be used for V1.0 Acceptance."
            )

    config_root = root / "configuration"
    control_root = root / "run_control"
    config_root.mkdir(parents=True, exist_ok=True)
    control_root.mkdir(parents=True, exist_ok=True)

    run_template_name, publication_template_name, route_profile = _template_names(route, profile)
    repository_templates = _repository_root() / "templates"
    run_template_path = repository_templates / run_template_name
    bundled_publication_template = repository_templates / publication_template_name
    bundled_semantic_registry_template = repository_templates / "semantic_registry.example.json"
    if not run_template_path.is_file():
        raise FileNotFoundError(f"Bundled Run Plan template is unavailable: {run_template_path}")
    if not bundled_publication_template.is_file():
        raise FileNotFoundError(
            f"Bundled Publication Plan template is unavailable: {bundled_publication_template}"
        )
    if not bundled_semantic_registry_template.is_file():
        raise FileNotFoundError(
            f"Bundled Semantic Registry template is unavailable: {bundled_semantic_registry_template}"
        )

    semantic_registry_path = (config_root / "semantic_registry.json").resolve(strict=False)
    semantic_registry_created = False
    if semantic_registry_path.exists() or semantic_registry_path.is_symlink():
        if semantic_registry_path.is_symlink() or not semantic_registry_path.is_file():
            raise FileExistsError(
                f"Refusing to replace non-regular Semantic Registry: {semantic_registry_path}"
            )
        registry_validation = validate_semantic_registry_file(semantic_registry_path)
        if not registry_validation["valid"]:
            raise ValueError(
                "Existing project Semantic Registry is invalid: "
                + "; ".join(registry_validation.get("errors", [])[:12])
            )
    else:
        shutil.copyfile(bundled_semantic_registry_template, semantic_registry_path)
        semantic_registry_created = True

    if publication_plan_template is not None:
        publication_path = publication_plan_template.expanduser().resolve(strict=True)
        if not publication_path.is_file():
            raise ValueError(f"Publication Plan template is not a file: {publication_path}")
        publication_created = False
    else:
        publication_path = (
            config_root / f"publication_package_plan.{route_profile}.json"
        ).resolve(strict=False)
        if publication_path.exists() or publication_path.is_symlink():
            if publication_path.is_symlink() or not publication_path.is_file():
                raise FileExistsError(
                    f"Refusing to replace non-regular Publication Plan template: {publication_path}"
                )
            if publication_path.read_bytes() != bundled_publication_template.read_bytes():
                raise FileExistsError(
                    f"A different Publication Plan template already exists at {publication_path}; "
                    "pass --publication-plan-template to use it explicitly or choose a new project configuration."
                )
            publication_created = False
        else:
            shutil.copyfile(bundled_publication_template, publication_path)
            publication_created = True

    run_template = json.loads(run_template_path.read_text(encoding="utf-8"))
    if not isinstance(run_template, dict):
        raise ValueError("Bundled Run Plan template must be a JSON object.")

    selected_project_id = (
        project_id.strip() if project_id and project_id.strip()
        else _default_project_id(root)
    )
    if not _ID.fullmatch(selected_project_id):
        raise ValueError("project_id must be a stable ID using letters, digits, dots, underscores, or hyphens.")

    ledger_path = (
        workflow_ledger_path.expanduser().resolve(strict=False)
        if workflow_ledger_path is not None
        else (control_root / "workflow_gate_ledger.jsonl").resolve(strict=False)
    )
    if not ledger_path.is_absolute():
        raise ValueError("workflow ledger path must be absolute.")

    source_roots = [package_root.resolve(strict=True), publication_path.parent, config_root]
    # Protect external provenance sources declared by the Adapter Manifest too;
    # the package directory alone may not contain original paper/SI files.
    source_roots.extend(Path(item["path"]).parent for item in refreshed.get("sources", []))
    if virtual_path is not None:
        source_roots.append(virtual_path.parent)
    source_roots.extend(Path(item["path"]).parent for item in acceptance_records)
    roots = _unique_directories(source_roots)

    source_artifacts = [
        {
            "artifact_id": "adapter_package_manifest",
            "path": str(manifest_path.resolve(strict=True)),
        },
        {
            "artifact_id": "publication_plan_template",
            "path": str(publication_path.resolve(strict=True)),
        },
        {
            "artifact_id": "semantic_registry",
            "path": str(semantic_registry_path.resolve(strict=True)),
        },
    ]

    plan = {
        **run_template,
        "project_id": selected_project_id,
        "source_roots": roots,
        "workflow_ledger_path": str(ledger_path),
        "source_artifacts": source_artifacts,
    }
    if profile == "CONTROLLED_SINGLE_STUDY":
        plan["execution_profile"] = "CONTROLLED_SINGLE_STUDY"
    else:
        plan.pop("execution_profile", None)
    if acceptance_records:
        plan["acceptance_source_artifacts"] = acceptance_records
    else:
        plan.pop("acceptance_source_artifacts", None)

    run_root_path = run_root.expanduser().resolve(strict=False)
    if run_root_path.exists() and not run_root_path.is_dir():
        raise ValueError(f"Run root exists and is not a directory: {run_root_path}")
    # Reuse the Runtime's own plan validator so the generated file is checked
    # against the same route/profile contracts and path rules as run-init.
    _validate_plan(plan, run_root_path)

    output = (
        output_path.expanduser().resolve(strict=False)
        if output_path is not None
        else (control_root / f"run_plan.{route_profile}.json").resolve(strict=False)
    )
    if any(output.is_relative_to(Path(item)) for item in roots):
        raise ValueError("Run Plan output must be outside all protected source roots.")
    if output.is_symlink() or output.exists():
        raise FileExistsError(f"Refusing to overwrite an existing Run Plan: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)

    return {
        "status": "created",
        "valid": True,
        "route": route,
        "profile": profile,
        "project_id": selected_project_id,
        "run_plan_path": str(output),
        "run_plan_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "adapter_manifest_path": str(manifest_path.resolve(strict=True)),
        "adapter_manifest_sha256": refreshed["manifest_sha256"],
        "source_roots": roots,
        "workflow_ledger_path": str(ledger_path),
        "publication_plan_template": str(publication_path.resolve(strict=True)),
        "publication_template_created": publication_created,
        "semantic_registry_path": str(semantic_registry_path.resolve(strict=True)),
        "semantic_registry_sha256": hashlib.sha256(semantic_registry_path.read_bytes()).hexdigest(),
        "semantic_registry_created": semantic_registry_created,
        "virtual_query_reference": str(virtual_path) if virtual_path is not None else None,
        "acceptance_source_count": len(acceptance_records),
        "run_init_command": (
            f'dor run-init --plan "{output}" --run-root "{run_root_path}"'
        ),
        "interpretation_boundary": (
            "Run Plan route/profile configuration only. It does not approve scientific scope, "
            "mappings, cohort eligibility, analysis suitability, or any G0-G4 decision."
        ),
    }
