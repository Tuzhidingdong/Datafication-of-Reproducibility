"""Read-only CSV/JSON inspection for the V0.1 foundation."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _type_hint(values: list[str]) -> str:
    nonempty = [value.strip() for value in values if value is not None and value.strip()]
    if not nonempty:
        return "unknown"
    numeric = 0
    integer = 0
    for value in nonempty:
        try:
            number = float(value)
            numeric += 1
            if number.is_integer():
                integer += 1
        except ValueError:
            continue
    if numeric == len(nonempty):
        return "integer-like" if integer == numeric else "numeric"
    return "string_or_mixed"


def inspect_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV input does not exist: {path}")
    before_hash = sha256_file(path)
    column_count: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    row_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header row: {path}")
        fieldnames = [name if name is not None else "" for name in reader.fieldnames]
        if any(not name.strip() for name in fieldnames):
            raise ValueError(f"CSV contains an empty column name: {path}")
        if len(set(fieldnames)) != len(fieldnames):
            raise ValueError(f"CSV contains duplicate column names: {path}")
        for name in fieldnames:
            samples[name] = []
        for row in reader:
            row_count += 1
            for name in fieldnames:
                value = row.get(name)
                if value is not None and str(value).strip() != "":
                    column_count[name] += 1
                    if len(samples[name]) < 200:
                        samples[name].append(str(value))
    after_hash = sha256_file(path)
    if before_hash != after_hash:
        raise RuntimeError(f"Source changed during inspection: {path}")

    columns = []
    for name in fieldnames:
        nonempty = column_count[name]
        columns.append({
            "column": name,
            "nonempty_count": nonempty,
            "blank_or_missing_count": row_count - nonempty,
            "coverage": (nonempty / row_count) if row_count else 0.0,
            "sampled_type_hint": _type_hint(samples[name]),
            "type_hint_sample_size": len(samples[name]),
        })

    return {
        "role": "wide_table",
        "format": "csv",
        "file_name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": before_hash,
        "row_count": row_count,
        "column_count": len(fieldnames),
        "columns": columns,
    }


def inspect_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON input does not exist: {path}")
    before_hash = sha256_file(path)
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    after_hash = sha256_file(path)
    if before_hash != after_hash:
        raise RuntimeError(f"Source changed during inspection: {path}")

    top_level_type = type(payload).__name__
    top_level_keys = list(payload.keys()) if isinstance(payload, dict) else []
    top_level_length = len(payload) if isinstance(payload, (dict, list)) else None

    return {
        "role": "evidence_database",
        "format": "json",
        "file_name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": before_hash,
        "top_level_type": top_level_type,
        "top_level_length": top_level_length,
        "top_level_keys": top_level_keys[:200],
        "nested_schema_status": "PARSE_VALIDATED_BUT_NOT_SEMANTICALLY_MAPPED",
    }


def run_audit(csv_path: Path | None, json_path: Path | None, output_dir: Path) -> dict[str, Any]:
    if csv_path is None and json_path is None:
        raise ValueError("At least one of --csv or --json must be supplied.")

    output_dir = output_dir.expanduser().resolve()
    source_paths = [p.expanduser().resolve() for p in (csv_path, json_path) if p is not None]
    if output_dir in source_paths:
        raise ValueError("Output directory cannot be a source file.")
    if any(source.is_relative_to(output_dir) for source in source_paths):
        raise ValueError("Output directory cannot contain a protected source file.")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite a non-empty output directory: {output_dir}")

    # Source inspection is read-only. All generated files are written only under output_dir.
    csv_record = inspect_csv(csv_path.expanduser().resolve()) if csv_path else None
    json_record = inspect_json(json_path.expanduser().resolve()) if json_path else None
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("AUDIT_%Y%m%dT%H%M%S_%fZ")
    source_records = [item for item in (csv_record, json_record) if item is not None]

    manifest = {
        "schema_version": "1.0",
        "audit_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audit_scope": "READ_ONLY_STRUCTURAL_INSPECTION",
        "sources": source_records,
        "semantic_mapping_status": "NOT_PERFORMED",
        "warnings": [
            "Column names and sampled type hints do not establish scientific meaning.",
            "Nested JSON shape is summarized but not semantically mapped.",
            "A CSV row is not assumed to be an independent experimental replicate.",
            "No missing-value imputation or source-data modification was performed."
        ],
    }

    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report_lines = [
        "# Read-only data audit",
        "",
        f"- Audit ID: {run_id}",
        f"- Created (UTC): {manifest['created_at']}",
        "- Scope: read-only structural inspection; no semantic mapping or imputation.",
        "",
        "## Sources",
        "",
    ]
    for source in source_records:
        report_lines.extend([
            f"### {source['file_name']}",
            f"- Format: {source['format']}",
            f"- Size: {source['size_bytes']} bytes",
            f"- SHA-256: {source['sha256']}",
        ])
        if source["format"] == "csv":
            report_lines.extend([
                f"- Rows: {source['row_count']}",
                f"- Columns: {source['column_count']}",
                "",
                "| Column | Non-empty | Blank/missing | Coverage | Sampled type hint |",
                "|---|---:|---:|---:|---|",
            ])
            for column in source["columns"]:
                report_lines.append(
                    f"| {column['column']} | {column['nonempty_count']} | "
                    f"{column['blank_or_missing_count']} | {column['coverage']:.4f} | "
                    f"{column['sampled_type_hint']} |"
                )
        else:
            report_lines.extend([
                f"- Top-level type: {source['top_level_type']}",
                f"- Top-level length: {source['top_level_length']}",
                f"- Top-level keys (first 200): {', '.join(source['top_level_keys']) or 'none'}",
                "- Nested semantic mapping: not performed.",
            ])
        report_lines.append("")

    report_lines.extend(["## Warnings", ""])
    report_lines.extend(f"- {warning}" for warning in manifest["warnings"])
    report_lines.extend([
        "",
        "## Next step",
        "",
        "Review this report, inspect the actual source schema and evidence structure, then define "
        "a domain-specific mapping. Do not infer scientific feature meanings from names or sampled values alone.",
        "",
    ])
    (output_dir / "data_audit_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    if csv_record:
        coverage_path = output_dir / "column_coverage.csv"
        with coverage_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "column", "nonempty_count", "blank_or_missing_count",
                    "coverage", "sampled_type_hint", "type_hint_sample_size"
                ],
            )
            writer.writeheader()
            writer.writerows(csv_record["columns"])

    return manifest
