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
        "condition_record_id": f"COND_TEST_{observation_id}_{condition_type}",
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
        with (out / "condition_outcome_links.csv").open(encoding="utf-8", newline="") as handle:
            links = list(csv.DictReader(handle))
        self.assertTrue(links[0]["condition_record_ids"])
        self.assertIn("COND_", links[0]["condition_record_ids"])

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

    def test_joint_condition_combinations_are_screened_within_same_observation(self):
        observations = []
        conditions = []
        for study_index in range(3):
            doi = f"10.1/combo-{study_index}"
            for level_index, (additive, additive_value, outcome_value) in enumerate((
                ("1% TAC", 1.0, 10 + study_index),
                ("2% TAC", 2.0, 15 + study_index),
            )):
                oid = f"COMBO_{study_index}_{level_index}"
                observations.append(observation(oid, doi, outcome_value))
                conditions.append(condition(oid, "ZnSO4|2 M", numeric_value=2.0))
                conditions.append({
                    "condition_record_id": f"COND_TEST_{oid}_percentage_modifier",
                    "observation_id": oid,
                    "condition_type": "percentage_modifier",
                    "normalized_value": additive,
                    "raw_value": additive,
                    "numeric_value": additive_value,
                    "numeric_unit": "%",
                    "unit_basis": "UNSPECIFIED_PERCENT_BASIS",
                    "source_field": "target_system",
                    "extraction_method": "RULE_PERCENT_MODIFIER",
                    "confidence": "HIGH",
                    "review_status": "CANDIDATE_NOT_HUMAN_ACCEPTED",
                    "data_eligibility": "ELIGIBLE_FOR_EXPLORATORY_ANALYSIS",
                })
        out, summary = self.run_analysis(observations, conditions)
        with (out / "condition_combination_performance.csv").open(encoding="utf-8", newline="") as handle:
            combinations = list(csv.DictReader(handle))
        supported = [row for row in combinations if row["screening_status"] == "SUPPORTED_JOINT_CONDITION_STRATUM"]
        self.assertEqual(len(supported), 2)
        self.assertEqual({row["doi_study_count"] for row in supported}, {"3"})
        self.assertEqual(summary["joint_condition_combination_contrast_count"], 1)
        self.assertEqual(summary["joint_condition_hypothesis_candidate_count"], 1)
        self.assertTrue(all(
            row["interpretation_status"] == "JOINT_CONDITION_SUPPORT_NOT_A_STATISTICAL_INTERACTION"
            for row in supported
        ))
        with (out / "condition_combination_contrasts.csv").open(encoding="utf-8", newline="") as handle:
            contrasts = list(csv.DictReader(handle))
        self.assertEqual(contrasts[0]["shared_doi_study_count"], "3")
        self.assertEqual(contrasts[0]["shared_doi_higher_outcome_count"], "3")
        self.assertEqual(contrasts[0]["shared_doi_opposite_direction_count"], "0")
        self.assertTrue((out / "condition_combination_hypothesis_candidates.csv").is_file())

    def test_paired_doi_contrasts_retain_direction_and_counterexamples(self):
        observations = []
        conditions = []
        for index in range(1, 4):
            doi = f"10.1/paired-{index}"
            for level, numeric, value in (("1 M", 1.0, 10 + index), ("2 M", 2.0, 12 + index)):
                oid = f"P{index}_{numeric}"
                observations.append(observation(oid, doi, value))
                conditions.append(condition(oid, f"ZnSO4|{level}", numeric_value=numeric))
        out, summary = self.run_analysis(observations, conditions)
        with (out / "condition_performance_contrasts.csv").open(encoding="utf-8", newline="") as handle:
            contrasts = list(csv.DictReader(handle))
        self.assertEqual(len(contrasts), 1)
        row = contrasts[0]
        self.assertEqual(row["paired_study_count"], "3")
        self.assertEqual(row["paired_higher_outcome_in_level_b_count"], "3")
        self.assertEqual(row["paired_lower_outcome_in_level_b_count"], "0")
        self.assertEqual(row["paired_opposite_to_aggregate_direction_count"], "0")
        self.assertEqual(summary["descriptive_contrast_count"], 1)

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

    def test_mixed_electrolyte_components_are_not_treated_as_exclusive_levels(self):
        observations = [
            observation("O1", "10.1/a", 10),
            observation("O2", "10.1/b", 12),
        ]
        conditions = [
            condition("O1", "ZnSO4", numeric_value=None, numeric_unit="", condition_type="electrolyte_component"),
            condition("O1", "MnSO4", numeric_value=None, numeric_unit="", condition_type="electrolyte_component"),
            condition("O2", "ZnSO4", numeric_value=None, numeric_unit="", condition_type="electrolyte_component"),
        ]
        _out, summary = self.run_analysis(observations, conditions, minimum_studies=2)
        self.assertEqual(summary["condition_outcome_link_row_count"], 0)
        self.assertEqual(summary["excluded_condition_candidate_count"], 3)

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
