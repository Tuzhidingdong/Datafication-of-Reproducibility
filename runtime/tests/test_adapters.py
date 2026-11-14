from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.adapters import validate_adapter_package_files
from dor.cli import build_parser


class AdapterPackageTests(unittest.TestCase):
    def _digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _package(self, root: Path) -> Path:
        source = root / "source.csv"
        source.write_text("x,y\n1,2\n", encoding="utf-8")
        standardized = root / "standardized.csv"
        standardized.write_text("id,value\nA,1\n", encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "package_id": "package-test",
            "adapter": {"adapter_id": "adapter.test", "adapter_version": "1.0"},
            "sources": [{
                "source_id": "source-1", "path": str(source),
                "sha256": self._digest(source), "format": "csv"
            }],
            "artifacts": [{
                "artifact_id": "dataset-1", "role": "standardized_dataset",
                "path": "standardized.csv", "sha256": self._digest(standardized),
                "format": "csv"
            }]
        }
        manifest_path = root / "adapter_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_valid_package_verifies_sources_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._package(root)
            report = validate_adapter_package_files(manifest)
            self.assertTrue(report["valid"])
            self.assertEqual(report["verified_source_count"], 1)
            self.assertEqual(report["verified_artifact_count"], 1)

    def test_artifact_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._package(root)
            (root / "standardized.csv").write_text("id,value\nA,2\n", encoding="utf-8")
            report = validate_adapter_package_files(manifest)
            self.assertFalse(report["valid"])
            self.assertIn("ARTIFACT_HASH_MISMATCH", {item["code"] for item in report["errors"]})

    def test_artifact_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._package(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["artifacts"][0]["path"] = "../outside.csv"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            report = validate_adapter_package_files(manifest)
            self.assertFalse(report["valid"])
            self.assertIn("ARTIFACT_PATH_INVALID", {item["code"] for item in report["errors"]})

    def test_report_must_be_outside_package_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._package(root)
            with self.assertRaises(ValueError):
                validate_adapter_package_files(manifest, report_path=root / "validation.json")

    def test_cli_registers_generic_adapter_validation(self):
        args = build_parser().parse_args([
            "validate-adapter-package", "--manifest", "adapter_manifest.json",
            "--package-root", "package", "--out", "validation.json"
        ])
        self.assertEqual(args.command, "validate-adapter-package")
        self.assertEqual(args.manifest, Path("adapter_manifest.json"))


if __name__ == "__main__":
    unittest.main()
