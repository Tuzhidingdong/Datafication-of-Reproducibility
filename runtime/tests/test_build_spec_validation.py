from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.builder import validate_build_spec_files
from dor.mapping import sha256_file


class BuildSpecValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inventory_path = self.root / "source_inventory.json"
        self.inventory_path.write_text(json.dumps({
            "schema_version": "1.0",
            "items": [{
                "inventory_id": "SRC_TEST",
                "source_file": "records.csv",
                "source_sha256": "a" * 64,
                "source_format": "csv",
                "locator_type": "csv_column",
                "locator": "record_id",
                "observed_types": ["string"],
                "coverage": 1.0,
            }],
        }, indent=2) + "\n", encoding="utf-8")
        self.mapping_path = self.root / "mapping_plan.json"
        self.mapping_path.write_text(json.dumps({
            "schema_version": "1.0",
            "mapping_version": "mapping-test-1",
            "source_inventory_sha256": sha256_file(self.inventory_path),
            "rules": [],
        }, indent=2) + "\n", encoding="utf-8")
        self.spec_path = self.root / "build_spec.json"
        self._write_valid_spec()

    def tearDown(self):
        self.temp.cleanup()

    def _write_valid_spec(self):
        self.spec_path.write_text(json.dumps({
            "schema_version": "1.0",
            "project_id": "PROJECT_TEST",
            "mapping_version": "mapping-test-1",
            "mapping_plan_sha256": sha256_file(self.mapping_path),
            "source_inventory_sha256": sha256_file(self.inventory_path),
            "entity_definitions": [{
                "definition_id": "D_STUDY",
                "entity_type": "studies",
                "source_file": "records.csv",
                "source_format": "csv",
                "grouping": {"mode": "SOURCE_ROW", "source_item_ids": []},
                "field_rule_ids": [],
            }],
            "links": [],
        }, indent=2) + "\n", encoding="utf-8")

    def validate(self):
        return validate_build_spec_files(
            self.mapping_path, self.inventory_path, self.spec_path,
        )

    def test_valid_build_spec_is_accepted_without_canonical_build(self):
        report = self.validate()
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["mapping_plan_sha256"], sha256_file(self.mapping_path))
        self.assertEqual(report["source_inventory_sha256"], sha256_file(self.inventory_path))
        self.assertEqual(report["build_spec_sha256"], sha256_file(self.spec_path))
        self.assertIn("NO_CANONICAL_BUILD", report["validation_scope"])

    def test_stale_mapping_plan_hash_is_rejected(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        spec["mapping_plan_sha256"] = "f" * 64
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = self.validate()
        self.assertFalse(report["valid"])
        self.assertTrue(any(item["code"] == "STALE_BUILD_SPEC" for item in report["errors"]))

    def test_entity_source_must_exist_in_inventory(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        spec["entity_definitions"][0]["source_file"] = "missing.csv"
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = self.validate()
        self.assertFalse(report["valid"])
        self.assertTrue(any(item["code"] == "SOURCE_FILE_NOT_IN_INVENTORY" for item in report["errors"]))

    def test_source_format_must_match_inventory(self):
        spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        spec["entity_definitions"][0]["source_format"] = "json"
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = self.validate()
        self.assertFalse(report["valid"])
        self.assertTrue(any(item["code"] == "SOURCE_FORMAT_INVENTORY_MISMATCH" for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
