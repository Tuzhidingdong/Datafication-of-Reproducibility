from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.adapter_handoff import prepare_adapter_handoff_files
from dor.adapter_package import initialize_adapter_package
from dor.audit import run_audit_from_adapter_handoff
from dor.cli import build_parser


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AdapterPackageInitializerTests(unittest.TestCase):
    def test_explicit_files_create_valid_manifest_and_handoff_routes_to_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "adapter-package"
            data = package / "data" / "experiments.csv"
            source = root / "sources" / "paper.pdf"
            data.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            data.write_text("record_id,value\nA,1\nB,2\n", encoding="utf-8")
            source.write_bytes(b"%PDF-1.7 provenance only")

            result = initialize_adapter_package(
                package,
                "manual-structured-input",
                "1.0",
                [f"paper={source}"],
                ["experiments=standardized_dataset=" + str(data)],
            )

            manifest_path = package / "adapter_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(result["valid"])
            self.assertEqual(result["source_count"], 1)
            self.assertEqual(result["artifact_count"], 1)
            self.assertEqual(manifest["sources"][0]["path"], str(source.resolve()))
            self.assertEqual(manifest["sources"][0]["format"], "binary")
            self.assertEqual(manifest["sources"][0]["sha256"], digest(source))
            self.assertEqual(manifest["artifacts"][0]["path"], "data/experiments.csv")
            self.assertEqual(manifest["artifacts"][0]["format"], "csv")
            self.assertEqual(manifest["artifacts"][0]["sha256"], digest(data))

            handoff_path = root / "run" / "adapter_handoff.json"
            handoff = prepare_adapter_handoff_files(
                manifest_path, package, handoff_path,
            )
            self.assertTrue(handoff["valid"])
            self.assertEqual(handoff["route"], "STRUCTURED_DATASET")

            audit = run_audit_from_adapter_handoff(
                handoff_path, root / "run" / "audit",
            )
            self.assertEqual(len(audit["sources"]), 1)
            inventory = json.loads(
                (root / "run" / "audit" / "source_inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(inventory["items"][0]["source_file"], "data/experiments.csv")

    def test_relative_source_and_artifact_paths_resolve_from_package_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            (package / "data").mkdir(parents=True)
            (package / "source").mkdir()
            (package / "source" / "paper.pdf").write_bytes(b"provenance")
            (package / "data" / "records.csv").write_text(
                "record_id,value\nA,1\n", encoding="utf-8"
            )

            result = initialize_adapter_package(
                package,
                "manual",
                "1.0",
                ["paper=source/paper.pdf"],
                ["records=standardized_dataset=data/records.csv"],
            )

            manifest = json.loads(
                (package / "adapter_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(result["valid"])
            self.assertEqual(manifest["sources"][0]["path"], "source/paper.pdf")
            self.assertEqual(manifest["artifacts"][0]["path"], "data/records.csv")

    def test_package_id_defaults_to_safe_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "My research package"
            package.mkdir()
            source = root / "source.txt"
            data = package / "data.csv"
            source.write_text("provenance", encoding="utf-8")
            data.write_text("id,value\nA,1\n", encoding="utf-8")

            result = initialize_adapter_package(
                package,
                "manual",
                "0.1",
                [f"source={source}"],
                [f"dataset=standardized_dataset={data}"],
            )
            self.assertEqual(result["package_id"], "My-research-package")

    def test_artifact_outside_package_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            source = root / "source.txt"
            external_data = root / "data.csv"
            source.write_text("source", encoding="utf-8")
            external_data.write_text("id,value\nA,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be inside package_root"):
                initialize_adapter_package(
                    package, "manual", "1.0",
                    [f"source={source}"],
                    [f"dataset=standardized_dataset={external_data}"],
                )
            self.assertFalse((package / "adapter_manifest.json").exists())

    def test_standardized_dataset_must_be_csv_or_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            source = root / "source.txt"
            data = package / "data.txt"
            source.write_text("source", encoding="utf-8")
            data.write_text("not structured", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be CSV or JSON"):
                initialize_adapter_package(
                    package, "manual", "1.0",
                    [f"source={source}"],
                    ["dataset=standardized_dataset=" + str(data)],
                )
            self.assertFalse((package / "adapter_manifest.json").exists())

    def test_duplicate_ids_and_missing_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            source = root / "source.txt"
            data = package / "data.csv"
            source.write_text("source", encoding="utf-8")
            data.write_text("id,value\nA,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source IDs must be unique"):
                initialize_adapter_package(
                    package, "manual", "1.0",
                    [f"source={source}", f"source={source}"],
                    [f"dataset=standardized_dataset={data}"],
                )
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                initialize_adapter_package(
                    package, "manual", "1.0",
                    [f"source={root / 'missing.txt'}"],
                    [f"dataset=standardized_dataset={data}"],
                )
            self.assertFalse((package / "adapter_manifest.json").exists())

    def test_existing_manifest_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            source = root / "source.txt"
            data = package / "data.csv"
            source.write_text("source", encoding="utf-8")
            data.write_text("id,value\nA,1\n", encoding="utf-8")
            manifest = package / "adapter_manifest.json"
            manifest.write_text('{"preserve": true}\n', encoding="utf-8")
            before = manifest.read_bytes()
            with self.assertRaises(FileExistsError):
                initialize_adapter_package(
                    package, "manual", "1.0",
                    [f"source={source}"],
                    [f"dataset=standardized_dataset={data}"],
                )
            self.assertEqual(manifest.read_bytes(), before)

    def test_cli_exposes_explicit_package_initialization(self):
        args = build_parser().parse_args([
            "init-adapter-package",
            "--package-root", "package",
            "--adapter-id", "manual",
            "--adapter-version", "1.0",
            "--source", "paper=paper.pdf",
            "--artifact", "experiments=standardized_dataset=data/experiments.csv",
            "--out", "package/adapter_manifest.json",
        ])
        self.assertEqual(args.command, "init-adapter-package")
        self.assertEqual(args.source, ["paper=paper.pdf"])
        self.assertEqual(
            args.artifact,
            ["experiments=standardized_dataset=data/experiments.csv"],
        )
        self.assertEqual(args.out, Path("package/adapter_manifest.json"))


if __name__ == "__main__":
    unittest.main()
