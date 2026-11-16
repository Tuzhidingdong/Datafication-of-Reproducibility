"""Create a hash-bound DoR handoff manifest for explicitly selected existing files.

This helper is deliberately not a scientific adapter: it does not scan directories,
convert files, infer field meanings, or inspect original-document contents.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from dor.adapters import validate_adapter_package_files

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARTIFACT_ROLES = {
    "standardized_dataset",
    "discovery_dataset",
    "source_inventory",
    "mapping_plan",
    "build_spec",
    "canonical_bundle",
    "domain_profile",
    "evidence_index",
    "auxiliary",
}
_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".tsv": "tsv",
    ".xml": "xml",
    ".txt": "text",
    ".md": "text",
    ".rst": "text",
    ".pdf": "binary",
    ".png": "binary",
    ".jpg": "binary",
    ".jpeg": "binary",
    ".tif": "binary",
    ".tiff": "binary",
    ".webp": "binary",
    ".doc": "binary",
    ".docx": "binary",
    ".xls": "binary",
    ".xlsx": "binary",
    ".zip": "binary",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_for(path: Path) -> str:
    return _FORMAT_BY_SUFFIX.get(path.suffix.lower(), "other")


def _validate_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not _ID.fullmatch(normalized):
        raise ValueError(
            f"{label} must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, or hyphens (maximum 128 characters)."
        )
    return normalized


def _parse_source_binding(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--source must use SOURCE_ID=FILE_PATH syntax.")
    source_id, raw_path = value.split("=", 1)
    if not source_id.strip() or not raw_path.strip():
        raise ValueError("--source must contain a non-empty ID and file path.")
    return _validate_id(source_id, "Source ID"), Path(raw_path).expanduser()


def _parse_artifact_binding(value: str) -> tuple[str, str, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(
            "--artifact must use ARTIFACT_ID=ROLE=FILE_PATH syntax."
        )
    artifact_id, role, raw_path = parts
    artifact_id = _validate_id(artifact_id, "Artifact ID")
    role = role.strip()
    if role not in _ARTIFACT_ROLES:
        raise ValueError(
            f"Unsupported artifact role {role!r}; expected one of "
            + ", ".join(sorted(_ARTIFACT_ROLES))
            + "."
        )
    return artifact_id, role, Path(raw_path).expanduser()


def _resolve_input(raw_path: Path, package_root: Path, label: str) -> Path:
    if raw_path.is_absolute():
        candidate = raw_path
    else:
        normalized = str(raw_path).replace("\\", "/")
        windows_path = PureWindowsPath(normalized)
        if (
            windows_path.is_absolute()
            or windows_path.drive
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise ValueError(
                f"{label} relative path must stay inside package_root and cannot contain "
                f"absolute, drive, empty, current-directory, or parent-directory components: {raw_path!s}"
            )
        candidate = package_root / Path(normalized)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"{label} file does not exist (relative paths resolve from package_root): {candidate}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"{label} path is not a regular file: {resolved}")
    if not raw_path.is_absolute() and not resolved.is_relative_to(package_root):
        raise ValueError(f"{label} relative path escapes package_root: {raw_path!s}")
    return resolved


def _source_descriptor(source_id: str, raw_path: Path, package_root: Path) -> dict[str, Any]:
    resolved = _resolve_input(raw_path, package_root, f"Source {source_id}")
    try:
        stored_path = resolved.relative_to(package_root).as_posix()
    except ValueError:
        # External sources are allowed by the Adapter Contract and remain
        # provenance-only inputs. Store their resolved path unambiguously.
        stored_path = str(resolved)
    return {
        "source_id": source_id,
        "path": stored_path,
        "sha256": _sha256(resolved),
        "format": _format_for(resolved),
    }


def _artifact_descriptor(
    artifact_id: str,
    role: str,
    raw_path: Path,
    package_root: Path,
) -> dict[str, Any]:
    resolved = _resolve_input(raw_path, package_root, f"Artifact {artifact_id}")
    try:
        stored_path = resolved.relative_to(package_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Artifact {artifact_id} must be inside package_root; "
            "only provenance sources may be external."
        ) from exc
    if not stored_path:
        raise ValueError(f"Artifact {artifact_id} path cannot be the package root.")
    file_format = _format_for(resolved)
    if role == "standardized_dataset" and file_format not in {"csv", "json"}:
        raise ValueError(
            f"standardized_dataset artifact {artifact_id} must be CSV or JSON; "
            f"detected format {file_format!r}."
        )
    return {
        "artifact_id": artifact_id,
        "role": role,
        "path": stored_path,
        "sha256": _sha256(resolved),
        "format": file_format,
    }


def _default_package_id(package_root: Path) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", package_root.name).strip("._-")
    candidate = candidate[:128].strip("._-")
    if not candidate or not candidate[0].isalnum():
        candidate = "adapter-" + candidate
    return _validate_id(candidate, "Package ID")


def initialize_adapter_package(
    package_root: Path,
    adapter_id: str,
    adapter_version: str,
    sources: list[str],
    artifacts: list[str],
    manifest_path: Path | None = None,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Create a manifest from explicitly supplied source and artifact files.

    Relative input paths resolve from package_root; external provenance sources must use absolute paths.
    Artifact paths must resolve inside package_root.
    The manifest is created exclusively and is never overwritten.
    """
    root = package_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Package root is not a directory: {root}")

    adapter_id = _validate_id(adapter_id, "Adapter ID")
    if not adapter_version.strip():
        raise ValueError("Adapter version must be a non-empty string.")
    resolved_package_id = (
        _validate_id(package_id, "Package ID")
        if package_id is not None
        else _default_package_id(root)
    )

    if not sources:
        raise ValueError("At least one --source entry is required.")
    if not artifacts:
        raise ValueError("At least one --artifact entry is required.")

    source_entries = [_parse_source_binding(item) for item in sources]
    artifact_entries = [_parse_artifact_binding(item) for item in artifacts]
    source_ids = [item[0] for item in source_entries]
    artifact_ids = [item[0] for item in artifact_entries]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Source IDs must be unique.")
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("Artifact IDs must be unique.")

    source_records = [
        _source_descriptor(source_id, raw_path, root)
        for source_id, raw_path in source_entries
    ]
    artifact_records = [
        _artifact_descriptor(artifact_id, role, raw_path, root)
        for artifact_id, role, raw_path in artifact_entries
    ]

    requested_output = (
        manifest_path.expanduser()
        if manifest_path is not None
        else Path("adapter_manifest.json")
    )
    output = (
        requested_output
        if requested_output.is_absolute()
        else root / requested_output
    ).resolve(strict=False)
    if not output.is_relative_to(root):
        raise ValueError("Adapter manifest output must be inside package_root.")
    if output in {
        (root / item["path"]).resolve(strict=False)
        for item in artifact_records
    }:
        raise ValueError("Adapter manifest cannot also be a declared artifact.")
    if output.is_symlink() or output.exists():
        raise FileExistsError(
            f"Adapter manifest already exists; refusing to overwrite: {output}"
        )

    manifest = {
        "schema_version": "1.0",
        "package_id": resolved_package_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adapter": {
            "adapter_id": adapter_id,
            "adapter_version": adapter_version.strip(),
        },
        "sources": source_records,
        "artifacts": artifact_records,
    }
    rendered = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    except BaseException:
        output.unlink(missing_ok=True)
        raise

    validation = validate_adapter_package_files(output, root)
    if not validation["valid"]:
        output.unlink(missing_ok=True)
        raise ValueError(
            "Generated Adapter Manifest failed its own integrity validation: "
            + json.dumps(validation["errors"], ensure_ascii=False)
        )

    return {
        "status": "created",
        "valid": True,
        "manifest_path": str(output),
        "package_root": str(root),
        "package_id": resolved_package_id,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version.strip(),
        "source_count": len(source_records),
        "artifact_count": len(artifact_records),
        "artifact_roles": sorted({item["role"] for item in artifact_records}),
        "manifest_sha256": _sha256(output),
        "validation": validation,
        "interpretation_boundary": (
            "This command records explicitly selected files and verifies their hashes. "
            "It does not scan directories, convert data, infer semantic mappings, "
            "inspect original-document contents, or approve scientific suitability."
        ),
    }
