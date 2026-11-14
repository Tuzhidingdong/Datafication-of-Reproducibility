from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from dor.feature_semantics import build_feature_semantics_review_queue


def record(
    observation_id: str,
    doi: str,
    *,
    status: str = "AGREED_MATCH",
    requires_review: bool = False,
    batch_id: str = "BATCH_REAL",
    quote_a: str = "",
    quote_b: str = "",
    unit: str = "mAh g-1",
) -> dict:
    return {
        "observation_id": observation_id,
        "paper_id": "P_" + observation_id,
        "doi": doi,
        "feature_id": "FEAT_UNMAPPED",
        "resolved_unit": unit,
        "resolved_value": 123.4,
        "status": status,
        "requires_human_review": requires_review,
        "batch_id": batch_id,
        "target_system": "Zn||Zn, 2 M ZnSO4",
        "source_origin": "AGGREGATED_JSON",
        "worker_a_evidence": {
            "quote": quote_a,
            "file": "main_analysis.md" if quote_a else "",
            "location": "Page 2" if quote_a else "",
        },
        "worker_b_evidence": {
            "quote": quote_b,
            "file": "si_analysis.md" if quote_b else "",
            "location": "Table S2" if quote_b else "",
            "table_reference": "Table S2" if quote_b else "",
            "row_header": "Electrolyte" if quote_b else "",
            "col_header": "Concentration" if quote_b else "",
        },
    }


class FeatureSemanticsReviewTests(unittest.TestCase):
    def test_queue_is_doi_distinct_bounded_and_prefers_agreed_evidence(self):
        records = [
            record("O1", "10.1/a", status="PASS_A_ONLY", requires_review=True, quote_a="Weak candidate excerpt."),
            record("O2", "10.1/a", status="AGREED_MATCH", quote_a="A verified result label.", quote_b="The corresponding supplementary result definition."),
            record("O3", "10.1/b", quote_a="Second study evidence."),
            record("O4", "10.1/c", quote_a="Third study evidence."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = build_feature_semantics_review_queue(records, out, max_examples_per_feature_unit=2)
            with (out / "feature_semantics_review_queue.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["doi"] for row in rows}), 2)
            self.assertIn("O2", {row["observation_id"] for row in rows})
            self.assertEqual(summary["feature_unit_group_count"], 1)
            self.assertEqual(summary["representative_evidence_row_count"], 2)
            self.assertTrue(all(row["review_status"] == "PENDING_HUMAN_SEMANTIC_MAPPING" for row in rows))
            self.assertTrue(all(row["mapping_must_not_be_auto_approved"] == "True" for row in rows))
            self.assertFalse((out / "feature_mapping.yaml").exists())

    def test_quotes_are_clipped_and_table_locators_are_preserved(self):
        long_quote = "A" * 600
        records = [record(
            "O1", "10.1/a", quote_a=long_quote, quote_b="Cell value shown in Table S2."
        )]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            build_feature_semantics_review_queue(records, out, max_quote_chars=100)
            with (out / "feature_semantics_review_queue.csv").open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertLessEqual(len(row["worker_a_evidence_text"]), 100)
            self.assertEqual(row["worker_a_quote_truncated"], "True")
            self.assertEqual(row["worker_b_table_reference"], "Table S2")
            self.assertEqual(row["worker_b_row_header"], "Electrolyte")
            self.assertEqual(row["worker_b_col_header"], "Concentration")

    def test_doi_less_test_batch_and_no_evidence_records_are_not_selected(self):
        records = [
            record("O1", "", quote_a="No DOI."),
            record("O2", "10.1/test", batch_id="BATCH_20261106_LIMITS_PROBE", quote_a="Probe."),
            record("O3", "10.1/none", quote_a="", quote_b=""),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = build_feature_semantics_review_queue(records, out)
            with (out / "feature_semantics_review_queue.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows, [])
            self.assertEqual(summary["excluded_without_doi_count"], 1)
            self.assertEqual(summary["excluded_test_batch_observation_count"], 1)
            self.assertEqual(summary["excluded_without_evidence_quote_or_cell_count"], 1)


if __name__ == "__main__":
    unittest.main()
