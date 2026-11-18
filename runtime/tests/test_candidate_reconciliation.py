from __future__ import annotations

import unittest

from dor.candidate_reconciliation import build_candidate_pairwise_reconciliation
from dor.semantic_registry import approved_unit_symbol_lookup, validate_semantic_registry_data


def _metadata(**overrides):
    value = {
        "canonical_concept_id": "concept:potential",
        "display_name": "Potential difference",
        "definition": "A generic reviewed potential-difference definition.",
        "measurement_basis": "Declared basis.",
        "measurement_context": "context:declared",
        "derivation_type": "MEASURED",
        "derived_from": [],
        "review_status": "APPROVED",
        "reviewer": "reviewer-label",
        "reviewed_at": "2026-11-18T00:00:00Z",
        "review_rationale": "Reviewed against the cited source.",
        "source_refs": [{
            "source_id": "source:semantic",
            "source_sha256": "a" * 64,
            "locator": "opaque:semantic-definition",
        }],
    }
    value.update(overrides)
    return value


def _candidate(candidate_id, source, value, unit, quote):
    return {
        "candidate_id": candidate_id,
        "candidate_source": source,
        "raw_value": value,
        "raw_unit": unit,
        "quoted_text": quote,
        "source_metadata": {"review_state": "UNREVIEWED"},
        "source_locators": [{
            "source_file": "structured-source.csv",
            "source_sha256": "b" * 64,
            "locator_type": "csv_row",
            "locator": f"row:{candidate_id}",
        }],
    }


def _bundle(candidates):
    return {
        "studies": [{"study_id": "study-1", "source_locators": []}],
        "systems": [{
            "system_id": "system-1",
            "study_ids": ["study-1"],
            "system_type": "unspecified",
        }],
        "experiments": [{
            "experiment_id": "experiment-1",
            "study_id": "study-1",
            "system_id": "system-1",
            "condition_ids": [],
        }],
        "conditions": [],
        "observations": [{
            "observation_id": "observation-1",
            "experiment_id": "experiment-1",
            "target_id": "potential",
            "value_state": "REPORTED",
            "raw_value": 1,
            "raw_unit": "V",
            "evidence_ids": [],
            "value_candidates": candidates,
        }],
    }


def _approved_registry(unit_definitions, *, include_parent_semantics=True):
    records = []
    if include_parent_semantics:
        records.append({
            "entity_type": "TARGET",
            "canonical_identifier": "potential",
            "semantic_metadata": _metadata(),
        })
    return {
        "schema_version": "1.1",
        "registry_id": "registry:approved-units",
        "records": records,
        "unit_definitions": unit_definitions,
    }


def _unit_definition(unit_id, dimension_id, canonical_unit, symbols, status="APPROVED"):
    payload = {
        "unit_id": unit_id,
        "dimension_id": dimension_id,
        "canonical_unit": canonical_unit,
        "unit_symbols": symbols,
        "review_status": status,
    }
    if status == "APPROVED":
        payload.update({
            "reviewer": "reviewer-label",
            "reviewed_at": "2026-11-18T00:00:00Z",
            "review_rationale": "Conversion checked against a cited standard.",
            "source_refs": [{
                "source_id": f"source:{unit_id}",
                "source_sha256": "c" * 64,
                "locator": f"opaque:{unit_id}",
            }],
        })
    return payload


class CandidatePairwiseReconciliationTests(unittest.TestCase):
    def test_decimal_numeric_equality_distinguishes_text_from_value(self):
        bundle = _bundle([
            _candidate("candidate-a", "extractor-a", "1", "V", "reported 1 V"),
            _candidate("candidate-b", "extractor-b", "1.0", "V", "reported 1.0 V"),
        ])
        result = build_candidate_pairwise_reconciliation(bundle)
        row = result["pairwise_rows"][0]
        self.assertEqual(row["candidate_source_relation"], "CROSS_SOURCE")
        self.assertEqual(row["value_comparison_status"], "NUMERICALLY_EQUAL")
        self.assertEqual(row["unit_comparison_status"], "EXACT_UNIT_LABEL_MATCH")
        self.assertEqual(row["unit_adjusted_comparison_status"], "NUMERICALLY_EQUAL")
        self.assertEqual(row["overall_comparison_status"], "NUMERICALLY_EQUIVALENT_WITHIN_DECLARED_UNIT_BASIS")
        self.assertEqual(result["profile"]["cross_source_comparison_count"], 1)

    def test_approved_same_dimension_unit_conversion_is_diagnostic_only(self):
        registry = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [
                    {"symbol": "V", "scale_to_canonical": 1},
                    {"symbol": "mV", "scale_to_canonical": 0.001},
                ],
            )
        ])
        bundle = _bundle([
            _candidate("candidate-mv", "extractor-a", "1000", "mV", "reported 1000 mV"),
            _candidate("candidate-v", "extractor-b", "1", "V", "reported 1 V"),
        ])
        before = bundle["observations"][0]["value_candidates"][0]["raw_value"]
        result = build_candidate_pairwise_reconciliation(bundle, semantic_registry=registry)
        row = result["pairwise_rows"][0]
        self.assertEqual(row["unit_comparison_status"], "APPROVED_SAME_DIMENSION_CONVERSION")
        self.assertEqual(row["comparable_unit"], "V")
        self.assertEqual(row["comparable_value_a"], "1")
        self.assertEqual(row["comparable_value_b"], "1")
        self.assertEqual(row["unit_adjusted_comparison_status"], "NUMERICALLY_EQUAL")
        self.assertEqual(row["overall_comparison_status"], "NUMERICALLY_EQUIVALENT_WITHIN_DECLARED_UNIT_BASIS")
        self.assertEqual(
            row["parent_semantic_status"],
            "APPROVED_PARENT_ATTRIBUTE_SEMANTICS_CANDIDATE_QUOTE_SCOPE_UNVERIFIED",
        )
        self.assertEqual(bundle["observations"][0]["value_candidates"][0]["raw_value"], before)
        self.assertEqual(result["profile"]["unit_conversion_applied_comparison_count"], 1)

    def test_approved_unit_conversion_preserves_high_precision_decimal_values(self):
        registry = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [
                    {"symbol": "V", "scale_to_canonical": 1},
                    {"symbol": "mV", "scale_to_canonical": 0.001},
                ],
            )
        ])
        bundle = _bundle([
            _candidate("candidate-mv", "extractor-a", "1234.5678901234567890123456789", "mV", "high precision mV"),
            _candidate("candidate-v", "extractor-b", "1.2345678901234567890123456789", "V", "high precision V"),
        ])
        row = build_candidate_pairwise_reconciliation(bundle, semantic_registry=registry)["pairwise_rows"][0]
        self.assertEqual(row["comparable_value_a"], "1.2345678901234567890123456789")
        self.assertEqual(row["comparable_value_b"], "1.2345678901234567890123456789")
        self.assertEqual(row["unit_adjusted_comparison_status"], "NUMERICALLY_EQUAL")

    def test_different_unknown_unit_labels_remain_unresolved(self):
        bundle = _bundle([
            _candidate("candidate-a", "extractor-a", "1000", "mV", "reported 1000 mV"),
            _candidate("candidate-b", "extractor-b", "1", "V", "reported 1 V"),
        ])
        row = build_candidate_pairwise_reconciliation(bundle)["pairwise_rows"][0]
        self.assertEqual(row["unit_comparison_status"], "UNIT_LABELS_DIFFER_UNRESOLVED")
        self.assertEqual(row["unit_adjusted_comparison_status"], "NOT_COMPARABLE_UNRESOLVED_UNIT_LABELS")
        self.assertEqual(row["overall_comparison_status"], "UNIT_EQUIVALENCE_UNRESOLVED")

    def test_approved_but_different_dimensions_are_not_comparable(self):
        registry = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [{"symbol": "V", "scale_to_canonical": 1}],
            ),
            _unit_definition(
                "unit:current",
                "dimension:current",
                "A",
                [{"symbol": "A", "scale_to_canonical": 1}],
            ),
        ])
        bundle = _bundle([
            _candidate("candidate-v", "extractor-a", "1", "V", "reported 1 V"),
            _candidate("candidate-a", "extractor-b", "1", "A", "reported 1 A"),
        ])
        row = build_candidate_pairwise_reconciliation(bundle, semantic_registry=registry)["pairwise_rows"][0]
        self.assertEqual(row["unit_comparison_status"], "APPROVED_INCOMPATIBLE_DIMENSIONS")
        self.assertEqual(row["overall_comparison_status"], "INCOMPATIBLE_UNIT_DIMENSIONS_REVIEW")
        self.assertIsNone(row["comparable_value_a"])
        self.assertIsNone(row["comparable_value_b"])

    def test_unapproved_unit_definitions_do_not_enable_conversion(self):
        registry = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [
                    {"symbol": "V", "scale_to_canonical": 1},
                    {"symbol": "mV", "scale_to_canonical": 0.001},
                ],
                status="PENDING",
            )
        ])
        self.assertEqual(approved_unit_symbol_lookup(registry), {})
        bundle = _bundle([
            _candidate("candidate-mv", "extractor-a", "1000", "mV", "reported 1000 mV"),
            _candidate("candidate-v", "extractor-b", "1", "V", "reported 1 V"),
        ])
        row = build_candidate_pairwise_reconciliation(bundle, semantic_registry=registry)["pairwise_rows"][0]
        self.assertEqual(row["unit_comparison_status"], "UNIT_LABELS_DIFFER_UNRESOLVED")

    def test_same_source_conflict_and_both_provenance_chains_are_retained(self):
        bundle = _bundle([
            _candidate("candidate-a1", "extractor-a", "1", "V", "quote one"),
            _candidate("candidate-a2", "extractor-a", "2", "V", "quote two"),
        ])
        row = build_candidate_pairwise_reconciliation(bundle)["pairwise_rows"][0]
        self.assertEqual(row["candidate_source_relation"], "SAME_SOURCE")
        self.assertEqual(row["value_comparison_status"], "NUMERICALLY_DIFFERENT")
        self.assertIn("quote one", row["candidate_a_quoted_text"])
        self.assertIn("quote two", row["candidate_b_quoted_text"])
        self.assertIn("candidate-a1", row["candidate_a_source_locators_json"])
        self.assertIn("candidate-a2", row["candidate_b_source_locators_json"])
        self.assertEqual(row["overall_comparison_status"], "NUMERICALLY_DIFFERENT_WITHIN_DECLARED_UNIT_BASIS")
        self.assertEqual(build_candidate_pairwise_reconciliation(bundle)["profile"]["same_source_comparison_count"], 1)

    def test_single_candidate_produces_no_pairwise_comparison(self):
        bundle = _bundle([
            _candidate("candidate-a", "extractor-a", "1", "V", "quote one"),
        ])
        result = build_candidate_pairwise_reconciliation(bundle)
        self.assertEqual(result["profile"]["pairwise_comparison_count"], 0)
        self.assertEqual(result["pairwise_rows"], [])

    def test_v1_0_remains_valid_and_cannot_carry_v1_1_unit_definitions(self):
        legacy = {"schema_version": "1.0", "registry_id": "registry:v1", "records": []}
        self.assertTrue(validate_semantic_registry_data(legacy)["valid"])
        self.assertEqual(approved_unit_symbol_lookup(legacy), {})
        invalid = {**legacy, "unit_definitions": []}
        report = validate_semantic_registry_data(invalid)
        self.assertFalse(report["valid"])
        self.assertTrue(any("requires semantic registry schema_version '1.1'" in item for item in report["errors"]))

    def test_v1_1_unit_definitions_require_exact_valid_canonical_symbol(self):
        registry = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [
                    {"symbol": "V", "scale_to_canonical": 1},
                    {"symbol": "mV", "scale_to_canonical": 0.001},
                ],
            )
        ])
        self.assertTrue(validate_semantic_registry_data(registry)["valid"])
        invalid = _approved_registry([
            _unit_definition(
                "unit:potential",
                "dimension:potential",
                "V",
                [
                    {"symbol": "V", "scale_to_canonical": 2},
                    {"symbol": "mV", "scale_to_canonical": 0.001},
                ],
            )
        ])
        report = validate_semantic_registry_data(invalid)
        self.assertFalse(report["valid"])
        self.assertTrue(any("canonical_unit must have scale_to_canonical=1" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
