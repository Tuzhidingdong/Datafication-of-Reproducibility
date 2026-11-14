"""Read-only CSV/JSON inspection for the DOR runtime."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dor.structure import profile_json_structure
from dor.inventory import build_source_inventory, write_source_inventory

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""): digest.update(chunk)
    return digest.hexdigest()

def _type_hint(values: list[str]) -> str:
    nonempty = [v.strip() for v in values if v is not None and v.strip()]
    if not nonempty: return "unknown"
    numeric = integer = 0
    for value in nonempty:
        try:
            number = float(value); numeric += 1
            if number.is_integer(): integer += 1
        except ValueError: continue
    if numeric == len(nonempty): return "integer-like" if integer == numeric else "numeric"
    return "string_or_mixed"

def inspect_csv(path: Path) -> dict[str, Any]:
    if not path.is_file(): raise FileNotFoundError(f"CSV input does not exist: {path}")
    before_hash = sha256_file(path)
    counts: Counter[str] = Counter(); samples: dict[str, list[str]] = {}
    row_count = short_rows = long_rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try: fieldnames = next(reader)
        except StopIteration: raise ValueError(f"CSV has no header row: {path}")
        if any(not name.strip() for name in fieldnames): raise ValueError(f"CSV contains an empty column name: {path}")
        if len(set(fieldnames)) != len(fieldnames): raise ValueError(f"CSV contains duplicate column names: {path}")
        samples = {name: [] for name in fieldnames}
        for row in reader:
            row_count += 1
            if len(row) < len(fieldnames): short_rows += 1
            elif len(row) > len(fieldnames): long_rows += 1
            for index, name in enumerate(fieldnames):
                value = row[index] if index < len(row) else ""
                if value.strip():
                    counts[name] += 1
                    if len(samples[name]) < 200: samples[name].append(value)
    after_hash = sha256_file(path)
    if before_hash != after_hash: raise RuntimeError(f"Source changed during inspection: {path}")
    columns = []
    for name in fieldnames:
        nonempty = counts[name]
        columns.append({"column": name, "nonempty_count": nonempty,
            "blank_or_missing_count": row_count - nonempty,
            "coverage": nonempty / row_count if row_count else 0.0,
            "sampled_type_hint": _type_hint(samples[name]),
            "type_hint_sample_size": len(samples[name])})
    return {"role": "wide_table", "format": "csv", "file_name": path.name,
        "size_bytes": path.stat().st_size, "sha256": before_hash,
        "row_count": row_count, "column_count": len(fieldnames),
        "row_shape": {"short_rows": short_rows, "long_rows": long_rows,
            "consistent_rows": row_count - short_rows - long_rows}, "columns": columns}

def inspect_json(path: Path) -> dict[str, Any]:
    if not path.is_file(): raise FileNotFoundError(f"JSON input does not exist: {path}")
    before_hash = sha256_file(path)
    try:
        with path.open("r", encoding="utf-8-sig") as handle: payload = json.load(handle)
    except json.JSONDecodeError as exc: raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    after_hash = sha256_file(path)
    if before_hash != after_hash: raise RuntimeError(f"Source changed during inspection: {path}")
    return {"role": "evidence_database", "format": "json", "file_name": path.name,
        "size_bytes": path.stat().st_size, "sha256": before_hash,
        "top_level_type": type(payload).__name__,
        "top_level_length": len(payload) if isinstance(payload, (dict, list)) else None,
        "top_level_keys": list(payload.keys())[:200] if isinstance(payload, dict) else [],
        "nested_schema_status": "STRUCTURAL_PROFILED_NOT_SEMANTICALLY_MAPPED",
        "structure_profile": profile_json_structure(payload)}

def run_audit_sources(source_specs: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    """Audit any number of declared CSV/JSON sources without changing them."""
    if not source_specs:
        raise ValueError("At least one CSV or JSON source must be supplied.")
    output_dir = output_dir.expanduser().resolve()
    seen_source_files: set[str] = set()
    resolved_specs: list[dict[str, Any]] = []
    for spec in source_specs:
        if not isinstance(spec, dict):
            raise ValueError("Each audit source must be an object.")
        path = Path(spec.get("path", "")).expanduser().resolve()
        fmt = spec.get("format")
        source_file = spec.get("source_file") or path.name
        if fmt not in {"csv", "json"}:
            raise ValueError(f"Unsupported structural audit format {fmt!r}; expected csv or json.")
        if not path.is_file():
            raise FileNotFoundError(f"Audit source does not exist: {path}")
        if not isinstance(source_file, str) or not source_file.strip():
            raise ValueError("source_file must be a non-empty path or identifier.")
        if source_file in seen_source_files:
            raise ValueError(f"Duplicate source_file in audit input: {source_file}")
        seen_source_files.add(source_file)
        resolved_specs.append({**spec, "path": path, "format": fmt, "source_file": source_file})

    source_paths = [item["path"] for item in resolved_specs]
    if output_dir in source_paths or any(source.is_relative_to(output_dir) for source in source_paths):
        raise ValueError("Output directory cannot contain or overwrite a protected source file.")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Output path exists and is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise FileExistsError(f"Refusing to overwrite a non-empty output directory: {output_dir}")

    sources: list[dict[str, Any]] = []
    for spec in resolved_specs:
        record = inspect_csv(spec["path"]) if spec["format"] == "csv" else inspect_json(spec["path"])
        expected_hash = spec.get("sha256")
        if expected_hash is not None and record["sha256"] != str(expected_hash).lower():
            raise ValueError(f"Source SHA-256 differs from the validated adapter handoff: {spec['source_file']}")
        record["file_name"] = spec["source_file"]
        record["source_file"] = spec["source_file"]
        record["source_id"] = spec.get("source_id")
        record["artifact_id"] = spec.get("artifact_id")
        record["role"] = spec.get("role") or record["role"]
        sources.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("AUDIT_%Y%m%dT%H%M%S_%fZ")
    manifest = {
        "schema_version": "1.0",
        "audit_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audit_scope": "READ_ONLY_STRUCTURAL_INSPECTION",
        "sources": sources,
        "semantic_mapping_status": "NOT_PERFORMED",
        "warnings": [
            "Column names and sampled type hints do not establish scientific meaning.",
            "Nested JSON paths and value types are structural observations, not semantic mappings.",
            "A CSV row is not assumed to be an independent experimental replicate.",
            "Short and long CSV rows are counted; extra cell contents are not interpreted.",
            "No missing-value imputation or source-data modification was performed.",
        ],
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "# Read-only data audit", "",
        f"- Audit ID: {run_id}",
        f"- Created (UTC): {manifest['created_at']}",
        "- Scope: read-only structural inspection; no semantic mapping or imputation.", "",
        "## Sources", "",
    ]
    for source in sources:
        lines.extend([
            f"### {source['file_name']}",
            f"- Format: {source['format']}",
            f"- Size: {source['size_bytes']} bytes",
            f"- SHA-256: {source['sha256']}",
        ])
        if source["format"] == "csv":
            shape = source["row_shape"]
            lines.extend([
                f"- Rows: {source['row_count']}",
                f"- Columns: {source['column_count']}",
                f"- Short rows: {shape['short_rows']}",
                f"- Long rows: {shape['long_rows']}", "",
                "| Column | Non-empty | Blank/missing | Coverage | Sampled type hint |",
                "|---|---:|---:|---:|---|",
            ])
            for col in source["columns"]:
                lines.append(
                    f"| {col['column']} | {col['nonempty_count']} | "
                    f"{col['blank_or_missing_count']} | {col['coverage']:.4f} | "
                    f"{col['sampled_type_hint']} |"
                )
        else:
            profile = source["structure_profile"]
            lines.extend([
                f"- Top-level type: {source['top_level_type']}",
                f"- Top-level length: {source['top_level_length']}",
                f"- Top-level keys (first 200): {', '.join(source['top_level_keys']) or 'none'}",
                f"- Nested structural paths: {profile['path_count']}",
                f"- Depth truncations: {profile['truncated_depth_occurrences']}",
                "- Nested semantic mapping: not performed.",
            ])
        lines.append("")
    lines.extend(["## Warnings", ""])
    lines.extend(f"- {warning}" for warning in manifest["warnings"])
    lines.extend([
        "", "## Next step", "",
        "Review this report and the bounded structural profile, inspect source evidence, "
        "then define explicit mappings. Do not infer scientific meanings from identifiers, "
        "filenames, or sampled values alone.", "",
    ])
    (output_dir / "data_audit_report.md").write_text("\n".join(lines), encoding="utf-8")

    csv_columns = [
        "source_id", "artifact_id", "source_file", "column", "nonempty_count",
        "blank_or_missing_count", "coverage", "sampled_type_hint", "type_hint_sample_size",
    ]
    csv_rows = []
    json_columns = ["source_id", "artifact_id", "source_file", "path", "occurrences",
                    "value_types", "list_length_min", "list_length_max"]
    json_rows = []
    for source in sources:
        if source["format"] == "csv":
            for column in source["columns"]:
                csv_rows.append({
                    "source_id": source.get("source_id"),
                    "artifact_id": source.get("artifact_id"),
                    "source_file": source["source_file"],
                    **column,
                })
        else:
            for item in source["structure_profile"]["paths"]:
                json_rows.append({
                    "source_id": source.get("source_id"),
                    "artifact_id": source.get("artifact_id"),
                    "source_file": source["source_file"],
                    **item,
                    "value_types": json.dumps(item["value_types"], ensure_ascii=False, sort_keys=True),
                })
    if any(source["format"] == "csv" for source in sources):
        with (output_dir / "column_coverage.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_columns)
            writer.writeheader()
            writer.writerows(csv_rows)
    if any(source["format"] == "json" for source in sources):
        with (output_dir / "json_structure_paths.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=json_columns)
            writer.writeheader()
            writer.writerows(json_rows)

    inventory = build_source_inventory(sources)
    write_source_inventory(inventory, output_dir)
    return manifest


def run_audit(csv_path: Path | None, json_path: Path | None, output_dir: Path) -> dict[str, Any]:
    """Backward-compatible single-CSV/single-JSON audit entry point."""
    if csv_path is None and json_path is None:
        raise ValueError("At least one of --csv or --json must be supplied.")
    specs = []
    if csv_path is not None:
        specs.append({"path": str(csv_path), "format": "csv", "source_file": Path(csv_path).name})
    if json_path is not None:
        specs.append({"path": str(json_path), "format": "json", "source_file": Path(json_path).name})
    return run_audit_sources(specs, output_dir)


def run_audit_from_adapter_handoff(handoff_path: Path, output_dir: Path) -> dict[str, Any]:
    """Audit all CSV/JSON standardized_dataset artifacts in a validated adapter handoff."""
    from dor.adapter_handoff import load_validated_adapter_handoff

    handoff = load_validated_adapter_handoff(handoff_path)
    if handoff["route"] != "STRUCTURED_DATASET":
        raise ValueError("This adapter handoff contains a Canonical Bundle; use it for discovery instead of source audit.")
    datasets = handoff.get("standardized_datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("Validated adapter handoff contains no supported standardized datasets.")
    specs = []
    for item in datasets:
        specs.append({
            "source_id": item["artifact_id"],
            "artifact_id": item["artifact_id"],
            "source_file": item["package_path"].replace("\\\\", "/"),
            "path": item["path"],
            "format": item["format"],
            "role": item["role"],
            "sha256": item["sha256"],
        })
    return run_audit_sources(specs, output_dir)
