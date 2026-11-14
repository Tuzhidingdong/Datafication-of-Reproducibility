from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.adapter_handoff import (
    canonical_bundle_from_handoff,
    prepare_adapter_handoff_files,
)
from dor.audit import run_audit_from_adapter_handoff
from dor.cli import build_parser


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def empty_canonical_bundle() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "generic-adapter-test",
        "mapping_version": "external-test-1",
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "comparisons": [],
        "evidence": [],
    }


class AdapterHandoffTests(unittest.TestCase):
    def _source(self, package: Path) -> Path:
        source = package / "sources" / "original.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"original source bytes")
        return source

    def _write_manifest(self, package: Path, artifacts: list[dict]) -> Path:
        source = self._source(package)
        manifest = {
            "schema_version": "1.0",
            "package_id": "package-generic-test",
            "adapter": {"adapter_id": "external.adapter", "adapter_version": "1.0"},
            "sources": [{
                "source_id": "source-1",
                "path": "sources/original.bin",
                "sha256": digest(source),
                "format": "binary",
            }],
            "artifacts": artifacts,
        }
        path = package / "adapter_manifest.json"
        write_json(path, manifest)
        return path

    def test_structured_route_audits_multiple_declared_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            csv_path = package / "tables" / "records.csv"
            json_path = package / "records" / "nested.json"
            csv_path.parent.mkdir(parents=True)
            json_path.parent.mkdir(parents=True)
            csv_path.write_text("record_id,value\nA,1\nB,2\n", encoding="utf-8")
            write_json(json_path, {"records": [{"id": "A"}, {"id": "B"}]})
            manifest = self._write_manifest(package, [
                {
                    "artifact_id": "dataset-csv", "role": "standardized_dataset",
                    "path": "tables/records.csv", "sha256": digest(csv_path), "format": "csv",
                },
                {
                    "artifact_id": "dataset-json", "role": "standardized_dataset",
                    "path": "records/nested.json", "sha256": digest(json_path), "format": "json",
                },
            ])
            handoff_path = root / "adapter_handoff.json"
            report = prepare_adapter_handoff_files(manifest, package, handoff_path)
            self.assertTrue(report["valid"])
            self.assertEqual(report["route"], "STRUCTURED_DATASET")
            self.assertEqual(len(report["standardized_datasets"]), 2)

            audit_dir = root / "audit"
            audit = run_audit_from_adapter_handoff(handoff_path, audit_dir)
            self.assertEqual(len(audit["sources"]), 2)
            inventory = json.loads((audit_dir / "source_inventory.json").read_text(encoding="utf-8"))
            source_files = {item["source_file"] for item in inventory["items"]}
            self.assertIn("tables/records.csv", source_files)
            self.assertIn("records/nested.json", source_files)
            self.assertEqual({item["artifact_id"] for item in inventory["items"]},
                             {"dataset-csv", "dataset-json"})

    def test_modified_dataset_is_rejected_after_handoff_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            csv_path = package / "records.csv"
            package.mkdir()
            csv_path.write_text("id,value\nA,1\n", encoding="utf-8")
            manifest = self._write_manifest(package, [{
                "artifact_id": "dataset-csv", "role": "standardized_dataset",
                "path": "records.csv", "sha256": digest(csv_path), "format": "csv",
            }])
            handoff_path = root / "adapter_handoff.json"
            prepare_adapter_handoff_files(manifest, package, handoff_path)
            csv_path.write_text("id,value\nA,999\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                run_audit_from_adapter_handoff(handoff_path, root / "audit")

    def test_canonical_route_is_structurally_validated_and_resolvable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            bundle_path = package / "canonical_bundle.json"
            write_json(bundle_path, empty_canonical_bundle())
            manifest = self._write_manifest(package, [{
                "artifact_id": "canonical-data",
                "role": "canonical_bundle",
                "path": "canonical_bundle.json",
                "sha256": digest(bundle_path),
                "format": "json",
            }])
            handoff_path = root / "adapter_handoff.json"
            report = prepare_adapter_handoff_files(manifest, package, handoff_path)
            self.assertEqual(report["route"], "CANONICAL_BUNDLE")
            self.assertEqual(canonical_bundle_from_handoff(handoff_path), bundle_path.resolve())

    def test_multiple_canonical_bundles_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            first = package / "one.json"
            second = package / "two.json"
            write_json(first, empty_canonical_bundle())
            write_json(second, empty_canonical_bundle())
            manifest = self._write_manifest(package, [
                {"artifact_id": "canonical-one", "role": "canonical_bundle", "path": "one.json", "sha256": digest(first), "format": "json"},
                {"artifact_id": "canonical-two", "role": "canonical_bundle", "path": "two.json", "sha256": digest(second), "format": "json"},
            ])
            with self.assertRaisesRegex(ValueError, "at most one canonical_bundle"):
                prepare_adapter_handoff_files(manifest, package, root / "handoff.json")

    def test_cli_exposes_generic_handoff_and_discovery_routes(self):
        handoff_args = build_parser().parse_args([
            "prepare-adapter-handoff", "--manifest", "adapter_manifest.json",
            "--package-root", "package", "--out", "adapter_handoff.json",
        ])
        self.assertEqual(handoff_args.command, "prepare-adapter-handoff")
        discovery_args = build_parser().parse_args([
            "discover-opportunities", "--adapter-handoff", "adapter_handoff.json",
            "--out-dir", "discovery",
        ])
        self.assertEqual(discovery_args.adapter_handoff, Path("adapter_handoff.json"))
        audit_args = build_parser().parse_args([
            "audit", "--adapter-handoff", "adapter_handoff.json", "--out", "audit",
        ])
        self.assertEqual(audit_args.adapter_handoff, Path("adapter_handoff.json"))


if __name__ == "__main__":
    unittest.main()
