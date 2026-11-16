"""Validated handoff routing for external, discipline-neutral adapter packages."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from dor.adapters import validate_adapter_package_files
from dor.canonical import validate_canonical_bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(package_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError("Adapter artifact paths must be package-relative.")
    resolved = (package_root / candidate).resolve()
    if not resolved.is_relative_to(package_root):
        raise ValueError(f"Adapter artifact path escapes package root: {raw_path!r}.")
    return resolved


def _source_path(package_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (package_root / candidate).resolve()
    if not candidate.is_absolute() and not resolved.is_relative_to(package_root):
        raise ValueError(f"Relative adapter source path escapes package root: {raw_path!r}.")
    return resolved


def _resolve_package_records(payload: dict[str, Any], package_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources = []
    for item in payload["sources"]:
        path = _source_path(package_root, item["path"])
        package_path = path.relative_to(package_root).as_posix() if path.is_relative_to(package_root) else item["path"]
        sources.append({
            "source_id": item["source_id"],
            "path": str(path),
            "package_path": package_path,
            "format": item["format"],
            "role": item.get("role"),
            "sha256": item["sha256"].lower(),
        })

    artifacts = []
    for item in payload["artifacts"]:
        path = _artifact_path(package_root, item["path"])
        artifacts.append({
            "artifact_id": item["artifact_id"],
            "role": item["role"],
            "path": str(path),
            "package_path": path.relative_to(package_root).as_posix(),
            "format": item["format"],
            "media_type": item.get("media_type"),
            "sha256": item["sha256"].lower(),
        })
    return sources, artifacts


def _validate_declared_files(records: list[dict[str, Any]], label: str) -> None:
    for item in records:
        path = Path(item["path"])
        if not path.is_file():
            raise FileNotFoundError(f"{label} file is missing: {path}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"{label} SHA-256 mismatch: {item['package_path']}")


def prepare_adapter_handoff_files(
    manifest_path: Path,
    package_root: Path | None = None,
    output_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a package and create one deterministic route description for DoR.

    The function checks delivery integrity and canonical structure only. It does not
    approve extraction quality, entity grain, mappings, scientific semantics, or
    suitability for analysis.
    """
    manifest_path = manifest_path.expanduser().resolve()
    root = (package_root.expanduser().resolve() if package_root else manifest_path.parent.resolve())
    validation = validate_adapter_package_files(manifest_path, root)
    if not validation.get("valid"):
        raise ValueError(
            "Adapter package validation failed: "
            + json.dumps(validation.get("errors", []), ensure_ascii=False)
        )

    manifest_hash = _sha256(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    sources, artifacts = _resolve_package_records(payload, root)
    _validate_declared_files(sources, "Adapter source")
    _validate_declared_files(artifacts, "Adapter artifact")
    if _sha256(manifest_path) != manifest_hash:
        raise RuntimeError("Adapter manifest changed while preparing the handoff.")

    canonical = [item for item in artifacts if item["role"] == "canonical_bundle"]
    if len(canonical) > 1:
        raise ValueError("An adapter package may declare at most one canonical_bundle artifact.")

    warnings: list[str] = []
    canonical_record: dict[str, Any] | None = None
    if canonical:
        canonical_record = canonical[0]
        if canonical_record["format"] != "json":
            raise ValueError("A canonical_bundle artifact must use JSON format.")
        bundle_path = Path(canonical_record["path"])
        bundle_hash = _sha256(bundle_path)
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Canonical bundle artifact is not valid JSON: {exc}") from exc
        bundle_validation = validate_canonical_bundle(bundle)
        if not bundle_validation.get("valid"):
            raise ValueError(
                "Adapter canonical_bundle failed structural/reference validation: "
                + json.dumps(bundle_validation.get("errors", [])[:20], ensure_ascii=False)
            )
        if _sha256(bundle_path) != bundle_hash:
            raise RuntimeError("Canonical bundle changed while preparing the handoff.")
        canonical_record = {
            **canonical_record,
            "validation": {
                "valid": True,
                "counts": bundle_validation.get("counts", {}),
                "warning_count": bundle_validation.get("warning_count", 0),
                "validation_scope": bundle_validation.get("validation_scope"),
            },
        }
        route = "CANONICAL_BUNDLE"
        standardized = [
            item for item in artifacts
            if item["role"] == "standardized_dataset" and item["format"] in {"csv", "json"}
        ]
        if any(item["role"] == "standardized_dataset" and item["format"] not in {"csv", "json"} for item in artifacts):
            warnings.append("Some standardized_dataset artifacts are not directly supported by the CSV/JSON structural audit.")
    else:
        standardized_all = [item for item in artifacts if item["role"] == "standardized_dataset"]
        standardized = [item for item in standardized_all if item["format"] in {"csv", "json"}]
        unsupported = [item for item in standardized_all if item["format"] not in {"csv", "json"}]
        if unsupported:
            warnings.append(
                "Unsupported standardized_dataset formats were not routed to dor audit: "
                + ", ".join(item["artifact_id"] for item in unsupported)
            )
        if not standardized:
            raise ValueError(
                "The package must provide one JSON canonical_bundle or at least one "
                "CSV/JSON standardized_dataset artifact."
            )
        route = "STRUCTURED_DATASET"

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "valid": True,
        "route": route,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "package_id": payload["package_id"],
        "adapter": payload["adapter"],
        "package_root": str(root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "sources": sources,
        "artifacts": artifacts,
        "standardized_datasets": standardized,
        "canonical_bundle": canonical_record,
        "warnings": warnings,
        "interpretation_boundary": (
            "PACKAGE_INTEGRITY_AND_CANONICAL_STRUCTURE_ONLY; "
            "NO_EXTRACTION_QUALITY_OR_SCIENTIFIC_SEMANTICS_APPROVED"
        ),
    }
    protected_files = {manifest_path, *(Path(item["path"]).resolve() for item in sources + artifacts)}
    output = output_path.expanduser().resolve() if output_path is not None else None
    dataset_output = dataset_manifest_path.expanduser().resolve() if dataset_manifest_path is not None else None

    for candidate, label in (
        (output, "Adapter handoff"),
        (dataset_output, "Dataset manifest"),
    ):
        if candidate is None:
            continue
        if candidate in protected_files or candidate.is_relative_to(root):
            raise ValueError(f"{label} output must be outside the protected package and all declared files.")
        if candidate.exists():
            raise FileExistsError(f"Refusing to overwrite an existing {label.lower()}: {candidate}")
    if output is not None and dataset_output is not None and output == dataset_output:
        raise ValueError("Handoff and dataset manifest outputs must be different files.")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if dataset_output is not None:
        dataset_manifest = {
            "schema_version": "1.0",
            "dataset_manifest_type": "EXTERNAL_ADAPTER_PACKAGE_SNAPSHOT",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "package_id": payload["package_id"],
            "adapter": payload["adapter"],
            "adapter_manifest_path": str(manifest_path),
            "adapter_manifest_sha256": manifest_hash,
            "source_count": len(sources),
            "artifact_count": len(artifacts),
            "sources": sources,
            "artifacts": artifacts,
            "semantic_mapping_status": "NOT_PERFORMED",
        }
        dataset_output.parent.mkdir(parents=True, exist_ok=True)
        dataset_output.write_text(
            json.dumps(dataset_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def _normalized_inventory_source_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Each source inventory item must declare a non-empty source_file.")
    value = raw.strip().replace("\\", "/")
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return str(candidate.resolve()).replace("\\", "/")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Unsafe source_file path in source inventory: {raw!r}")
    return value


def _validate_source_inventory_provenance(
    handoff: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    """Require every inventory source reference to resolve to a declared package file."""
    items = inventory.get("items") if isinstance(inventory, dict) else None
    if not isinstance(items, list):
        raise ValueError("Adapter source_inventory must contain an items array.")

    declared: dict[str, dict[str, Any]] = {}
    eligible_artifacts = [
        item for item in handoff.get("artifacts", [])
        if item.get("role") in {"standardized_dataset", "discovery_dataset", "evidence_index", "auxiliary"}
    ]
    for record in handoff.get("sources", []) + eligible_artifacts:
        keys = {
            _normalized_inventory_source_path(record["package_path"]),
            _normalized_inventory_source_path(record["path"]),
        }
        for key in keys:
            previous = declared.get(key)
            if previous is not None and (
                previous["sha256"] != record["sha256"]
                or previous["format"] != record["format"]
            ):
                raise ValueError(
                    f"Adapter manifest declares conflicting file identities for source path {key!r}."
                )
            declared[key] = record

    matched = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Adapter source_inventory item {index} must be an object.")
        source_path = _normalized_inventory_source_path(item.get("source_file"))
        descriptor = declared.get(source_path)
        if descriptor is None:
            raise ValueError(
                f"Adapter source_inventory item {index} references {source_path!r}, "
                "which is not declared by the adapter manifest."
            )
        source_hash = item.get("source_sha256")
        if not isinstance(source_hash, str) or source_hash.lower() != descriptor["sha256"].lower():
            raise ValueError(
                f"Adapter source_inventory item {index} SHA-256 does not match its declared source file."
            )
        source_format = item.get("source_format")
        if source_format != descriptor["format"]:
            raise ValueError(
                f"Adapter source_inventory item {index} format does not match its declared source file."
            )
        matched += 1

    return {
        "valid": True,
        "inventory_item_count": len(items),
        "matched_source_item_count": matched,
        "validation_scope": "SOURCE_INVENTORY_FILE_IDENTITY_AND_FORMAT_MATCHED_TO_ADAPTER_MANIFEST",
    }


def materialize_adapter_artifacts_files(
    handoff_path: Path,
    output_dir: Path,
    artifact_ids: list[str] | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    """Copy selected, hash-verified adapter artifacts into a new derived Run directory."""
    handoff = load_validated_adapter_handoff(handoff_path)
    use_ids = isinstance(artifact_ids, list) and bool(artifact_ids)
    use_roles = isinstance(roles, list) and bool(roles)
    if use_ids == use_roles:
        raise ValueError("Supply either one or more artifact_ids or one or more artifact roles, but not both.")
    if use_ids and len(set(artifact_ids)) != len(artifact_ids):
        raise ValueError("Adapter artifact IDs must be unique.")
    if use_ids and "materialization_manifest" in artifact_ids:
        raise ValueError("The artifact ID 'materialization_manifest' is reserved by DoR.")
    if use_roles and len(set(roles)) != len(roles):
        raise ValueError("Adapter artifact roles must be unique.")

    package_root = Path(handoff["package_root"]).resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == package_root or output_dir.is_relative_to(package_root):
        raise ValueError("Materialized artifacts must be written outside the protected adapter package.")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Materialization output path is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise FileExistsError(f"Refusing to overwrite a non-empty materialization directory: {output_dir}")

    by_id = {item["artifact_id"]: item for item in handoff["artifacts"]}
    selected: list[tuple[str, dict[str, Any]]] = []
    if use_ids:
        missing = set(artifact_ids) - set(by_id)
        if missing:
            raise ValueError("Adapter package does not declare requested artifact IDs: " + ", ".join(sorted(missing)))
        selected = [(artifact_id, by_id[artifact_id]) for artifact_id in artifact_ids]
    else:
        valid_roles = {item["role"] for item in handoff["artifacts"]}
        missing_roles = set(roles) - valid_roles
        if missing_roles:
            raise ValueError("Adapter package does not declare requested artifact roles: " + ", ".join(sorted(missing_roles)))
        json_roles = {"source_inventory", "mapping_plan", "build_spec", "canonical_bundle"}
        for role in roles:
            candidates = [item for item in handoff["artifacts"] if item["role"] == role]
            if len(candidates) != 1:
                raise ValueError(
                    f"Adapter role {role!r} must resolve to exactly one artifact for role-based materialization; found {len(candidates)}."
                )
            if role in json_roles and candidates[0]["format"] != "json":
                raise ValueError(f"Adapter role {role!r} must be delivered as JSON for the existing DoR validators.")
            selected.append((role, candidates[0]))

    inventory_artifacts = [artifact for _, artifact in selected if artifact["role"] == "source_inventory"]
    if len(inventory_artifacts) > 1:
        raise ValueError("Materialization may include at most one source_inventory artifact.")
    inventory_validation = None
    if inventory_artifacts:
        inventory_artifact = inventory_artifacts[0]
        try:
            inventory_payload = json.loads(
                Path(inventory_artifact["path"]).read_text(encoding="utf-8-sig")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Adapter source_inventory is not valid JSON: {exc}") from exc
        inventory_validation = _validate_source_inventory_provenance(handoff, inventory_payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for selection_key, artifact in selected:
        artifact_id = artifact["artifact_id"]
        source = Path(artifact["path"])
        before = _sha256(source)
        if before != artifact["sha256"]:
            raise ValueError(f"Adapter artifact changed before materialization: {artifact_id}")
        suffix = Path(artifact["package_path"]).suffix
        if use_roles and selection_key in {"source_inventory", "mapping_plan", "build_spec", "canonical_bundle"}:
            suffix = ".json"
        destination_name = (artifact_id if use_ids else selection_key) + suffix
        destination = output_dir / destination_name
        if destination.exists():
            raise FileExistsError(f"Materialization destination already exists: {destination}")
        shutil.copyfile(source, destination)
        copied_hash = _sha256(destination)
        if copied_hash != artifact["sha256"] or _sha256(source) != before:
            raise RuntimeError(f"Materialized artifact integrity check failed: {artifact_id}")
        copied.append({
            "artifact_id": artifact_id,
            "role": artifact["role"],
            "source_path": artifact["path"],
            "source_package_path": artifact["package_path"],
            "materialized_path": destination_name,
            "format": artifact["format"],
            "sha256": copied_hash,
        })

    manifest = {
        "schema_version": "1.0",
        "materialization_type": "READ_ONLY_ADAPTER_ARTIFACT_COPY",
        "package_id": handoff["package_id"],
        "adapter": handoff["adapter"],
        "adapter_manifest_sha256": handoff["manifest_sha256"],
        "adapter_handoff_path": str(Path(handoff_path).expanduser().resolve()),
        "artifacts": copied,
        "source_inventory_validation": inventory_validation,
        "source_files_modified": False,
    }
    manifest_path = output_dir / "materialization_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir),
        "materialization_manifest": str(manifest_path),
        "artifacts": copied,
        "artifact_count": len(copied),
        "source_inventory_validation": inventory_validation,
        "source_files_modified": False,
    }


def load_validated_adapter_handoff(handoff_path: Path) -> dict[str, Any]:
    """Load a handoff and re-check its manifest, declared paths, and exact file hashes."""
    handoff_path = handoff_path.expanduser().resolve()
    try:
        handoff = json.loads(handoff_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Adapter handoff must be readable JSON: {exc}") from exc
    if not isinstance(handoff, dict) or handoff.get("schema_version") != "1.0" or handoff.get("valid") is not True:
        raise ValueError("Adapter handoff is invalid or has an unsupported schema version.")

    manifest_path = Path(handoff.get("manifest_path", ""))
    if not manifest_path.is_file() or _sha256(manifest_path) != handoff.get("manifest_sha256"):
        raise ValueError("Adapter manifest is missing or differs from the handoff SHA-256.")
    package_root = Path(handoff.get("package_root", "")).resolve()
    validation = validate_adapter_package_files(manifest_path, package_root)
    if not validation.get("valid"):
        errors = validation.get("errors", [])
        details = "; ".join(
            f"{item.get('code', 'PACKAGE_VALIDATION_ERROR')}: {item.get('message', '')}"
            for item in errors if isinstance(item, dict)
        )
        message = "Adapter package no longer passes package validation."
        if details:
            message = f"Adapter package no longer passes package validation: {details}"
        raise ValueError(message)
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if handoff.get("package_id") != payload.get("package_id") or handoff.get("adapter") != payload.get("adapter"):
        raise ValueError("Adapter handoff identity does not match the package manifest.")
    expected_sources, expected_artifacts = _resolve_package_records(payload, package_root)

    for label, expected, supplied in (
        ("sources", expected_sources, handoff.get("sources")),
        ("artifacts", expected_artifacts, handoff.get("artifacts")),
    ):
        if not isinstance(supplied, list) or len(supplied) != len(expected):
            raise ValueError(f"Adapter handoff {label} do not match the package manifest.")
        expected_by_id = {
            item.get("source_id", item.get("artifact_id")): item for item in expected
        }
        supplied_by_id = {
            item.get("source_id", item.get("artifact_id")): item for item in supplied
            if isinstance(item, dict)
        }
        if set(expected_by_id) != set(supplied_by_id):
            raise ValueError(f"Adapter handoff {label} identifiers do not match the package manifest.")
        for identifier, expected_item in expected_by_id.items():
            supplied_item = supplied_by_id[identifier]
            for field in ("path", "package_path", "format", "sha256"):
                if supplied_item.get(field) != expected_item.get(field):
                    raise ValueError(f"Adapter handoff {label} entry {identifier!r} has a modified {field}.")
            if label == "artifacts" and supplied_item.get("role") != expected_item.get("role"):
                raise ValueError(f"Adapter handoff artifact {identifier!r} has a modified role.")
        _validate_declared_files(expected, f"Adapter {label[:-1]}")

    standardized_expected = [
        item for item in expected_artifacts
        if item["role"] == "standardized_dataset" and item["format"] in {"csv", "json"}
    ]
    canonical_expected = [item for item in expected_artifacts if item["role"] == "canonical_bundle"]
    if handoff.get("route") == "STRUCTURED_DATASET":
        if canonical_expected:
            raise ValueError("Structured-data handoff cannot omit a canonical_bundle declared in the package manifest.")
        if handoff.get("canonical_bundle") is not None:
            raise ValueError("Structured-data handoff must not declare a canonical bundle.")
        supplied_datasets = handoff.get("standardized_datasets")
        if not isinstance(supplied_datasets, list) or {
            item.get("artifact_id") for item in supplied_datasets if isinstance(item, dict)
        } != {item["artifact_id"] for item in standardized_expected}:
            raise ValueError("Adapter handoff standardized datasets do not match the package manifest.")
        expected_by_id = {item["artifact_id"]: item for item in standardized_expected}
        for item in supplied_datasets:
            expected = expected_by_id[item["artifact_id"]]
            for field in ("path", "package_path", "format", "sha256", "role"):
                if item.get(field) != expected.get(field):
                    raise ValueError(f"Adapter handoff standardized dataset {item['artifact_id']!r} has a modified {field}.")
    elif handoff.get("route") == "CANONICAL_BUNDLE":
        if len(canonical_expected) != 1:
            raise ValueError("Canonical handoff must resolve to exactly one canonical_bundle.")
        supplied = handoff.get("canonical_bundle")
        if not isinstance(supplied, dict):
            raise ValueError("Canonical handoff lacks its canonical_bundle descriptor.")
        expected = canonical_expected[0]
        for field in ("artifact_id", "path", "package_path", "format", "sha256"):
            if supplied.get(field) != expected.get(field):
                raise ValueError(f"Canonical bundle descriptor has a modified {field}.")
        bundle_path = Path(expected["path"])
        bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
        validation = validate_canonical_bundle(bundle)
        if not validation.get("valid"):
            raise ValueError("Canonical bundle no longer passes structural/reference validation.")
        if _sha256(bundle_path) != expected["sha256"]:
            raise ValueError("Canonical bundle changed after adapter handoff creation.")
        supplied_datasets = handoff.get("standardized_datasets")
        if not isinstance(supplied_datasets, list) or {
            item.get("artifact_id") for item in supplied_datasets if isinstance(item, dict)
        } != {item["artifact_id"] for item in standardized_expected}:
            raise ValueError("Canonical handoff standardized datasets do not match the package manifest.")
        expected_by_id = {item["artifact_id"]: item for item in standardized_expected}
        for item in supplied_datasets:
            expected_dataset = expected_by_id[item["artifact_id"]]
            for field in ("path", "package_path", "format", "sha256", "role"):
                if item.get(field) != expected_dataset.get(field):
                    raise ValueError(f"Canonical handoff standardized dataset {item['artifact_id']!r} has a modified {field}.")
    else:
        raise ValueError(f"Unsupported adapter handoff route: {handoff.get('route')!r}.")
    if _sha256(manifest_path) != handoff.get("manifest_sha256"):
        raise ValueError("Adapter manifest changed while consuming the handoff.")
    return handoff


def canonical_bundle_from_handoff(handoff_path: Path) -> Path:
    handoff = load_validated_adapter_handoff(handoff_path)
    if handoff["route"] != "CANONICAL_BUNDLE" or not isinstance(handoff.get("canonical_bundle"), dict):
        raise ValueError("This adapter handoff does not provide a validated canonical_bundle.")
    return Path(handoff["canonical_bundle"]["path"])
