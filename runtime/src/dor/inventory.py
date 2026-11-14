"""Create neutral source inventories and unresolved mapping review queues."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
from typing import Any

def _stable_id(source_sha256: str, locator_type: str, locator: str, source_file: str | None = None) -> str:
    raw = f"{source_sha256}|{locator_type}|{locator}".encode("utf-8")
    identifier = "SRC_" + hashlib.sha256(raw).hexdigest()[:16].upper()
    return identifier if source_file is None else identifier + "_" + hashlib.sha256(source_file.encode("utf-8")).hexdigest()[:8].upper()

def build_source_inventory(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for source in sources:
        source_file = source.get("source_file", source["file_name"])
        source_id = source.get("source_id")
        artifact_id = source.get("artifact_id")
        if source["format"] == "csv":
            for column in source.get("columns", []):
                locator_type, locator = "csv_column", column["column"]
                items.append({
                    "inventory_id": _stable_id(source["sha256"], locator_type, locator, source_file if source_id or artifact_id else None),
                    "source_role": source["role"], "source_file": source_file,
                    "source_sha256": source["sha256"], "source_format": "csv",
                    "source_id": source_id, "artifact_id": artifact_id,
                    "locator_type": locator_type, "locator": locator,
                    "observed_types": [column["sampled_type_hint"]],
                    "coverage": column["coverage"], "mapping_status": "UNRESOLVED",
                })
        elif source["format"] == "json":
            for node in source.get("structure_profile", {}).get("paths", []):
                locator_type, locator = "json_path", node["path"]
                items.append({
                    "inventory_id": _stable_id(source["sha256"], locator_type, locator, source_file if source_id or artifact_id else None),
                    "source_role": source["role"], "source_file": source_file,
                    "source_sha256": source["sha256"], "source_format": "json",
                    "source_id": source_id, "artifact_id": artifact_id,
                    "locator_type": locator_type, "locator": locator,
                    "observed_types": sorted(node["value_types"]),
                    "coverage": None, "mapping_status": "UNRESOLVED",
                })
    return items

def write_source_inventory(items: list[dict[str, Any]], output_dir: Path) -> None:
    (output_dir / "source_inventory.json").write_text(
        json.dumps({"schema_version": "1.0", "items": items}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    fields = ["inventory_id", "source_id", "artifact_id", "source_role", "source_file", "source_sha256",
        "source_format", "locator_type", "locator", "observed_types", "coverage",
        "canonical_entity", "canonical_field_id", "normalized_unit",
        "mapping_status", "reviewer_decision"]
    with (output_dir / "mapping_review_queue.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in items:
            writer.writerow({**item, "observed_types": json.dumps(item["observed_types"], ensure_ascii=False),
                "canonical_entity": "", "canonical_field_id": "", "normalized_unit": "",
                "reviewer_decision": ""})
