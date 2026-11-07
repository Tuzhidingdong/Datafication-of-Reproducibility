from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from dor.audit import run_audit, sha256_file


class ReadOnlyAuditTests(unittest.TestCase):
    def test_audit_creates_derived_outputs_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_csv = root / "source.csv"
            source_json = root / "source.json"
            output = root / "derived" / "audit"

            source_csv.write_text("DOI,CE,Condition\n10.1/example,99.7,AB\n10.1/example,,control\n", encoding="utf-8")
            source_json.write_text(json.dumps({"records": [{"evidence": "quote"}]}), encoding="utf-8")

            csv_hash_before = sha256_file(source_csv)
            json_hash_before = sha256_file(source_json)

            result = run_audit(source_csv, source_json, output)

            self.assertEqual(result["audit_scope"], "READ_ONLY_STRUCTURAL_INSPECTION")
            self.assertTrue((output / "dataset_manifest.json").is_file())
            self.assertTrue((output / "data_audit_report.md").is_file())
            self.assertTrue((output / "column_coverage.csv").is_file())
            self.assertEqual(csv_hash_before, sha256_file(source_csv))
            self.assertEqual(json_hash_before, sha256_file(source_json))

            with (output / "column_coverage.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            ce = next(row for row in rows if row["column"] == "CE")
            self.assertEqual(ce["nonempty_count"], "1")
            self.assertEqual(ce["blank_or_missing_count"], "1")

    def test_rejects_output_directory_that_contains_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_csv = root / "source.csv"
            source_csv.write_text("x\n1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_audit(source_csv, None, root)

    def test_json_invalid_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_json = root / "broken.json"
            source_json.write_text("{not-json}", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_audit(None, source_json, root / "out")


if __name__ == "__main__":
    unittest.main()
