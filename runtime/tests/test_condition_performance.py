from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from dor.condition_performance import build_condition_performance_analysis


def observation(
    observation_id: str,
    doi: str,
    value: float,
    *,
    unit: str = "mAh g-1",
    batch_id: str = "BATCH_REAL",
    status: str = "AGREED_MATCH",
    requires_human_review: bool = False,
) -> dict:
    return {
        "observation_id": observation_id,
        "paper_id": "P_" + doi.rsplit("/", 1)[-1],
        "doi": doi,
        "feature_id": "FEAT_UNMAPPED_X",
        "resolved_value": value,
        "resolved_unit": unit,
        "status": status,
        "requires_human_review": requires_human_review,
        "source_origin": "AGGREGATED_JSON",
        "batch_id": batch_id,
        "target_system": "Zn||Zn",
    }


def condition(
    observation_id: str,
    normalized_value: str,
    *,
    numeric_value: float | None,
    numeric_unit: str = "M",
    condition_type: str = "salt_concentration",
    data_eligibility: str = "ELIGIBLE_FOR_EXPLORATORY_ANALYSIS",
    review_status: str = "CANDIDATE_NOT_HUMAN_ACCEPTED",
) -> dict:
    return {
        "observation_id": observation_id,
        "condition_type": condition_type,
        "normalized_value": normalized_value,
        "raw_value": normalized_value,
        "numeric_value": numeric_value,
        "numeric_unit": numeric_unit,
        "unit_basis": "MOLARITY",
        "source_field": "target_system",
        "extraction_method": "RULE_CONCENTRATION_SALT",
        "confidence": "HIGH",
        "review_status": review_status,
        "data_eligibility": data_eligibility,
    }


class ConditionPerformanceTests(unittest.TestCase):
    def run_analysis(self, observations, condition_records, minimum_studies=3):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name)
        summary = build_condition_performance_analysis(
            observations, condition_records, out, minimum_studies=minimum_studies
        )
        return out, summary

    def test_compares_condition_levels_using_doi_study_medians(self):
        observations = []
        conditions = []
        for index, (doi, values) in enumerate([
            ("10.1/a", (10, 12)),
            ("10.1/b", (11, 13)),
            ("10.1/c", (9, 11)),
            ("10.1/d", (14, 16)),
            ("10.1/e", (15, 17)),
            ("10.1/f", (13, 15)),
        ]):
            level = "1 M" if index < 3 else "2 M"
            concentration = 1.0 if index < 3 else 2.0
            for replicate, value in enumerate(values):
                oid = f"OBS_{index}_{replicate}"
                observations.append(observation(oid, doi, value))
                conditions.append(condition(oid, f"ZnSO4|{level}", numeric_value=concentration))
        out, summary = self.run_analysis(observations, conditions)
        with (out / "condition_performance_contrasts.csv").open(encoding="utf-8", newline="") as handle:
            contrasts = list(csv.DictReader(handle))
        self.assertEqual(len(contrasts), 1)
        contrast = contrasts[0]
        self.assertEqual(contrast["study_count_a"], "3")
        self.assertEqual(contrast["study_count_b"], "3")
        self.assertAlmostEqual(float(contrast["median_difference_b_minus_a"]), 4.0)
        self.assertEqual(summary["hypothesis_candidate_count"], 1)
        self.assertEqual(summary["endpoint_semantics_status"], "UNMAPPED_FEATURE_SEMANTICS")
        with (out / "condition_performance_feature_coverage.csv").open(encoding="utf-8", newline="") as handle:
            coverage = list(csv.DictReader(handle))
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0]["eligible_numeric_outcome_observation_count"], "12")
        self.assertEqual(coverage[0]["condition_linked_observation_count"], "12")

    def test_repeated_observations_within_one_doi_count_as_one_study(self):
        observations = [
            observation("O1", "10.1/a", 10),
            observation("O2", "10.1/a", 20),
            observation("O3", "10.1/b", 12),
        ]
        conditions = [
            condition("O1", "ZnSO4|1 M", numeric_value=1),
            condition("O2", "ZnSO4|1 M", numeric_value=1),
            condition("O3", "ZnSO4|1 M", numeric_value=1),
        ]
        out, summary = self.run_analysis(observations, conditions, minimum_studies=2)
        with (out / "condition_performance_study_strata.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        doi_a = next(row for row in rows if row["study_group_id"] == "DOI:10.1/a")
        self.assertEqual(doi_a["study_observation_count"], "2")
        self.assertEqual(float(doi_a["study_outcome_median"]), 15.0)
        self.assertEqual(summary["condition_stratum_row_count"], 1)
        with (out / "condition_performance_strata.csv").open(encoding="utf-8", newline="") as handle:
            strata = list(csv.DictReader(handle))
        self.assertEqual(strata[0]["study_count"], "2")

    def test_conflicting_condition_levels_on_one_observation_are_excluded(self):
        observations = [observation("O1", "10.1/a", 10)]
        conditions = [
            condition("O1", "ZnSO4|1 M", numeric_value=1),
            condition("O1", "ZnSO4|2 M", numeric_value=2),
        ]
        _out, summary = self.run_analysis(observations, conditions)
        self.assertEqual(summary["condition_outcome_link_row_count"], 0)
        self.assertEqual(summary["ambiguous_observation_dimension_count"], 1)

    def test_incompatible_condition_units_are_not_compared(self):
        observations = [
            observation("O1", "10.1/a", 10),
            observation("O2", "10.1/b", 12),
            observation("O3", "10.1/c", 14),
            observation("O4", "10.1/d", 16),
        ]
        conditions = [
            condition("O1", "ZnSO4|1 M", numeric_value=1, numeric_unit="M"),
            condition("O2", "ZnSO4|1 M", numeric_value=1, numeric_unit="M"),
            condition("O3", "ZnSO4|1 mol/L", numeric_value=1, numeric_unit="mol/L"),
            condition("O4", "ZnSO4|1 mol/L", numeric_value=1, numeric_unit="mol/L"),
        ]
        _out, summary = self.run_analysis(observations, conditions, minimum_studies=2)
        self.assertEqual(summary["condition_stratum_row_count"], 2)
        self.assertEqual(summary["descriptive_contrast_count"], 0)

    def test_test_batches_and_unverified_paper_ids_do_not_enter_analysis(self):
        observations = [
            observation("O1", "10.1/a", 10),
            observation("O2", "10.1/b", 20, batch_id="BATCH_20261106_LIMITS_PROBE"),
            observation("O3", "", 30),
        ]
        conditions = [
            condition("O1", "ZnSO4|1 M", numeric_value=1),
            condition("O2", "ZnSO4|2 M", numeric_value=2),
            condition("O3", "ZnSO4|3 M", numeric_value=3),
        ]
        _out, summary = self.run_analysis(observations, conditions)
        self.assertEqual(summary["numeric_outcome_observation_count"], 1)
        self.assertEqual(summary["condition_outcome_link_row_count"], 1)

    def test_context_review_table_candidates_are_not_promoted(self):
        observations = [observation("O1", "10.1/a", 10)]
        conditions = [
            condition(
                "O1", "1 mA cm-2", numeric_value=1, numeric_unit="mA cm-2",
                condition_type="current_density",
                review_status="CANDIDATE_REQUIRES_CONTEXT_REVIEW",
            )
        ]
        _out, summary = self.run_analysis(observations, conditions)
        self.assertEqual(summary["condition_outcome_link_row_count"], 0)
        self.assertEqual(summary["excluded_condition_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
