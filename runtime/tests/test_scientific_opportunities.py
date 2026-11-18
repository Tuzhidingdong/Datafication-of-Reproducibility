from __future__ import annotations

import unittest

from dor.scientific_opportunities import (
    _apply_bh,
    _identifier_key,
    _semantic_metadata_index,
    _sign_test_p,
    _target_semantic_key,
    build_scientific_opportunities,
)


def _bundle():
    return {
        "schema_version": "1.0",
        "project_id": "scientific-opportunity-test",
        "mapping_version": "synthetic-1",
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "comparisons": [],
        "evidence": [],
    }


def _add_study(bundle, study_number, condition_values, outcome_values, condition_type="condition_x",
               condition_unit=None, replicate_observations=1):
    study_id = f"S{study_number}"
    system_id = f"SYS{study_number}"
    bundle["studies"].append({"study_id": study_id, "source_locators": []})
    bundle["systems"].append({
        "system_id": system_id, "study_ids": [study_id], "system_type": "synthetic-system"
    })
    for experiment_number, (condition_value, outcome_value) in enumerate(
        zip(condition_values, outcome_values), start=1
    ):
        condition_id = f"C{study_number}_{experiment_number}"
        experiment_id = f"E{study_number}_{experiment_number}"
        bundle["conditions"].append({
            "condition_id": condition_id,
            "system_ids": [system_id],
            "condition_type": condition_type,
            "raw_value": condition_value,
            "raw_unit": condition_unit,
            "value_state": "REPORTED",
        })
        bundle["experiments"].append({
            "experiment_id": experiment_id,
            "study_id": study_id,
            "system_id": system_id,
            "condition_ids": [condition_id],
        })
        for replicate in range(replicate_observations):
            bundle["observations"].append({
                "observation_id": f"O{study_number}_{experiment_number}_{replicate}",
                "experiment_id": experiment_id,
                "target_id": "TARGET_Y",
                "endpoint_definition": "endpoint-definition-1",
                "timepoint": "cycle-100",
                "value_state": "REPORTED",
                "raw_value": outcome_value + replicate * 0.01,
                "raw_unit": "outcome-unit",
                "evidence_ids": [],
            })





def _add_system_level_study(bundle, study_number, condition_values, outcome_values,
                            condition_type="condition_x", condition_unit=None):
    study_id = f"BS{study_number}"
    bundle["studies"].append({"study_id": study_id, "source_locators": []})
    for index, (condition_value, outcome_value) in enumerate(zip(condition_values, outcome_values), start=1):
        system_id = f"BSYS{study_number}_{index}"
        condition_id = f"BC{study_number}_{index}"
        experiment_id = f"BE{study_number}_{index}"
        bundle["systems"].append({
            "system_id": system_id, "study_ids": [study_id], "system_type": "synthetic-system"
        })
        bundle["conditions"].append({
            "condition_id": condition_id,
            "system_ids": [system_id],
            "condition_type": condition_type,
            "raw_value": condition_value,
            "raw_unit": condition_unit,
            "value_state": "REPORTED",
        })
        bundle["experiments"].append({
            "experiment_id": experiment_id,
            "study_id": study_id,
            "system_id": system_id,
            "condition_ids": [condition_id],
        })
        bundle["observations"].append({
            "observation_id": f"BO{study_number}_{index}",
            "experiment_id": experiment_id,
            "target_id": "TARGET_Y",
            "endpoint_definition": "endpoint-definition-1",
            "timepoint": "cycle-100",
            "value_state": "REPORTED",
            "raw_value": outcome_value,
            "raw_unit": "outcome-unit",
            "evidence_ids": [],
        })


def _add_bidirectional_feature_study(bundle, study_number, feature_a_values, feature_b_values):
    study_id = f"MIRROR_STUDY_{study_number}"
    bundle["studies"].append({"study_id": study_id, "source_locators": []})
    for index, (value_a, value_b) in enumerate(zip(feature_a_values, feature_b_values), start=1):
        system_id = f"MIRROR_SYS_{study_number}_{index}"
        condition_a = f"MIRROR_CA_{study_number}_{index}"
        condition_b = f"MIRROR_CB_{study_number}_{index}"
        experiment_id = f"MIRROR_E_{study_number}_{index}"
        bundle["systems"].append({
            "system_id": system_id, "study_ids": [study_id], "system_type": "synthetic-system"
        })
        bundle["conditions"].extend([
            {
                "condition_id": condition_a, "system_ids": [system_id],
                "condition_type": "FEATURE_A", "raw_value": value_a, "raw_unit": "feature-unit",
                "value_state": "REPORTED",
            },
            {
                "condition_id": condition_b, "system_ids": [system_id],
                "condition_type": "FEATURE_B", "raw_value": value_b, "raw_unit": "feature-unit",
                "value_state": "REPORTED",
            },
        ])
        bundle["experiments"].append({
            "experiment_id": experiment_id, "study_id": study_id, "system_id": system_id,
            "condition_ids": [condition_a, condition_b],
        })
        bundle["observations"].extend([
            {
                "observation_id": f"MIRROR_OA_{study_number}_{index}", "experiment_id": experiment_id,
                "target_id": "FEATURE_A", "endpoint_definition": "endpoint-1", "timepoint": "t1",
                "value_state": "REPORTED", "raw_value": value_a, "raw_unit": "feature-unit",
                "evidence_ids": [],
            },
            {
                "observation_id": f"MIRROR_OB_{study_number}_{index}", "experiment_id": experiment_id,
                "target_id": "FEATURE_B", "endpoint_definition": "endpoint-1", "timepoint": "t1",
                "value_state": "REPORTED", "raw_value": value_b, "raw_unit": "feature-unit",
                "evidence_ids": [],
            },
        ])


class ScientificOpportunityTests(unittest.TestCase):
    def test_exact_sign_test_uses_study_direction_not_observation_count(self):
        self.assertEqual(_sign_test_p([1.0, 1.0, 1.0, 1.0, 1.0]), 0.0625)
        self.assertEqual(_sign_test_p([1.0, -1.0, 1.0, -1.0, 1.0]), 1.0)
        self.assertIsNone(_sign_test_p([0.0, 0.0]))

    def test_benjamini_hochberg_is_monotone_and_bounded(self):
        rows = [
            {"analysis_family": "A", "p_value": 0.01, "q_value": None},
            {"analysis_family": "A", "p_value": 0.04, "q_value": None},
            {"analysis_family": "A", "p_value": 0.03, "q_value": None},
            {"analysis_family": "B", "p_value": 0.001, "q_value": None},
        ]
        _apply_bh(rows, "A")
        self.assertAlmostEqual(rows[0]["q_value"], 0.03)
        self.assertAlmostEqual(rows[2]["q_value"], 0.04)
        self.assertAlmostEqual(rows[1]["q_value"], 0.04)
        self.assertIsNone(rows[3]["q_value"])
        self.assertTrue(all(0 <= rows[i]["q_value"] <= 1 for i in range(3)))

    def test_repeated_observations_do_not_inflate_independent_studies(self):
        bundle = _bundle()
        for study in range(1, 6):
            baseline = float(study * 10)
            _add_study(
                bundle, study,
                condition_values=["low", "high"],
                outcome_values=[baseline + 2.0, baseline + 8.0],
                replicate_observations=12,
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(len(result["contrasts"]), 1)
        contrast = result["contrasts"][0]
        self.assertEqual(contrast["paired_study_count"], 5)
        # Nominal string labels are not assigned an invented ordinal order:
        # serialized label order determines A/B and the signed b-minus-a value.
        self.assertEqual(contrast["contrast_orientation"], "SERIALIZED_LABEL_ORDER")
        self.assertEqual(contrast["positive_study_count"], 0)
        self.assertEqual(contrast["negative_study_count"], 5)
        self.assertEqual(contrast["observation_count"], 120)
        self.assertAlmostEqual(contrast["median_study_difference_b_minus_a"], -6.0)
        self.assertAlmostEqual(contrast["p_value"], 0.0625)
        self.assertAlmostEqual(contrast["q_value"], 0.0625)
        self.assertEqual(result["profile"]["analysis_unit"], "INDEPENDENT_STUDY")
        self.assertEqual(len(contrast["study_effects"]), 5)
        self.assertTrue(all(len(item["supporting_observation_ids"]) == 24 for item in contrast["study_effects"]))
        self.assertTrue(result["opportunities"])
        self.assertEqual(result["opportunities"][0]["screen_status"], "FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW")
        self.assertEqual(
            result["opportunities"][0]["semantic_status"],
            "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
        )

    def test_numeric_condition_trend_uses_one_spearman_per_study(self):
        bundle = _bundle()
        for study in range(1, 5):
            x_values = [1.0, 2.0, 3.0, 4.0, 5.0]
            y_values = [study * value for value in x_values]
            _add_study(
                bundle, study, x_values, y_values,
                condition_type="current_density",
                condition_unit="mA cm-2",
                replicate_observations=1,
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(len(result["correlations"]), 1)
        row = result["correlations"][0]
        self.assertEqual(row["independent_study_count"], 4)
        self.assertEqual(row["system_correlation_count"], 4)
        self.assertAlmostEqual(row["median_study_spearman_rho"], 1.0)
        self.assertAlmostEqual(row["p_value"], 0.125)
        self.assertAlmostEqual(row["q_value"], 0.125)
        self.assertEqual(len(row["study_effects"]), 4)
        self.assertEqual(len(result["opportunities"]), 1)
        self.assertEqual(result["opportunities"][0]["signal_type"], "WITHIN_STUDY_SYSTEM_NUMERIC_CONDITION_TREND")

    def test_between_system_numeric_trend_recovers_one_study_rho_per_paper(self):
        bundle = _bundle()
        for study in range(1, 5):
            x_values = [1.0, 2.0, 3.0, 4.0, 5.0]
            y_values = [float(study * 10 + value * 2) for value in x_values]
            _add_system_level_study(
                bundle, study, x_values, y_values,
                condition_type="current_density", condition_unit="mA cm-2",
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        rows = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["independent_study_count"], 4)
        self.assertEqual(rows[0]["system_correlation_count"], 20)
        self.assertAlmostEqual(rows[0]["median_study_spearman_rho"], 1.0)
        self.assertAlmostEqual(rows[0]["p_value"], 0.125)
        self.assertEqual(len(rows[0]["study_effects"]), 4)
        opportunities = [
            item for item in result["opportunities"]
            if item["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(
            opportunities[0]["identifiability"],
            "WITHIN_STUDY_BETWEEN_SYSTEM_CROSS_SECTIONAL_RANK_ASSOCIATION",
        )

    def test_between_system_categorical_contrast_requires_replicated_systems_per_group(self):
        bundle = _bundle()
        for study in range(1, 6):
            base = float(study * 10)
            _add_system_level_study(
                bundle, study,
                ["low", "low", "high", "high"],
                [base + 1.0, base + 3.0, base + 7.0, base + 9.0],
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        rows = [
            row for row in result["contrasts"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_CONTRAST"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["independent_study_count"], 5)
        self.assertEqual(rows[0]["level_a_system_count"], 10)
        self.assertEqual(rows[0]["level_b_system_count"], 10)
        self.assertEqual(rows[0]["contrast_orientation"], "SERIALIZED_LABEL_ORDER")
        self.assertAlmostEqual(rows[0]["median_study_difference_b_minus_a"], -6.0)
        self.assertEqual(rows[0]["negative_study_count"], 5)
        self.assertAlmostEqual(rows[0]["p_value"], 0.0625)
        self.assertEqual(rows[0]["interpretation_status"],
                         "BETWEEN_SYSTEM_WITHIN_STUDY_CROSS_SECTIONAL_CONTRAST_CANDIDATE_NOT_CAUSAL")

    def test_multiple_condition_levels_in_one_experiment_are_excluded_as_ambiguous(self):
        bundle = _bundle()
        _add_study(bundle, 1, ["low"], [1.0])
        # Attach a second, conflicting value for the same condition type to the same Experiment.
        bundle["conditions"].append({
            "condition_id": "C1_conflict",
            "system_ids": ["SYS1"],
            "condition_type": "condition_x",
            "raw_value": "high",
            "raw_unit": None,
            "value_state": "REPORTED",
        })
        bundle["experiments"][0]["condition_ids"].append("C1_conflict")
        result = build_scientific_opportunities(bundle)
        self.assertEqual(result["profile"]["ambiguous_condition_experiment_assignments_excluded"], 1)
        self.assertEqual(result["opportunities"], [])

    def test_unmapped_identifiers_are_preserved_without_semantic_guessing(self):
        bundle = _bundle()
        for study in range(1, 4):
            _add_study(bundle, study, ["A", "B"], [1.0 + study, 2.0 + study])
        result = build_scientific_opportunities(bundle, bootstrap_iterations=0)
        opportunity = result["opportunities"][0]
        self.assertIn("TARGET_Y", opportunity["scientific_question"])
        self.assertIn("condition_x", opportunity["scientific_question"])
        self.assertEqual(
            opportunity["semantic_status"],
            "CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW",
        )
        self.assertIn("not", " ".join(opportunity["limitations"]).lower())

    def test_same_canonical_attribute_is_excluded_before_statistics_and_fdr(self):
        bundle = _bundle()
        for study in range(1, 5):
            x_values = [1.0, 2.0, 3.0, 4.0]
            _add_system_level_study(
                bundle, study, x_values, [value * 2 for value in x_values],
                condition_type="TARGET_Y", condition_unit="outcome-unit",
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(result["correlations"], [])
        self.assertEqual(result["contrasts"], [])
        self.assertEqual(result["profile"]["self_association_exclusion_count"], 1)
        exclusion = result["self_association_exclusions"][0]
        self.assertEqual(exclusion["exclusion_reason"], "SAME_CANONICAL_ATTRIBUTE")
        self.assertEqual(exclusion["admission_status"], "EXCLUDED_FROM_SCIENTIFIC_OPPORTUNITIES_AND_FDR")

    def test_identical_same_unit_values_are_excluded_as_structural_identity(self):
        bundle = _bundle()
        for study in range(1, 5):
            x_values = [1.0, 2.0, 3.0, 4.0]
            _add_system_level_study(
                bundle, study, x_values, x_values,
                condition_type="condition_x", condition_unit="outcome-unit",
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(result["correlations"], [])
        self.assertEqual(result["profile"]["self_association_exclusion_reason_counts"],
                         {"IDENTICAL_VALUES": 1})
        self.assertEqual(result["self_association_exclusions"][0]["independent_study_count"], 4)

    def test_perfect_rank_correlation_alone_is_not_excluded(self):
        bundle = _bundle()
        for study in range(1, 5):
            x_values = [1.0, 2.0, 3.0, 4.0]
            _add_system_level_study(
                bundle, study, x_values, [value * 2 for value in x_values],
                condition_type="condition_x", condition_unit="outcome-unit",
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(result["profile"]["self_association_exclusion_count"], 0)
        within_system = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_WITHIN_SYSTEM_SPEARMAN"
        ]
        between_system = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        # The fixture has one Experiment per System, so the within-System family
        # is retained as a zero-support diagnostic row, not an inferential result.
        self.assertEqual(len(within_system), 1)
        self.assertEqual(within_system[0]["independent_study_count"], 0)
        self.assertIsNone(within_system[0]["p_value"])
        self.assertEqual(len(between_system), 1)
        self.assertEqual(between_system[0]["independent_study_count"], 4)
        self.assertEqual(between_system[0]["median_study_spearman_rho"], 1.0)
        self.assertEqual(len(result["opportunities"]), 1)

    def test_exact_reciprocal_between_system_relations_are_deduplicated_before_fdr(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_bidirectional_feature_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]
            )
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        rows = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(rows), 2)
        duplicates = [row for row in rows if row.get("mirror_duplicate_of_opportunity_id")]
        representatives = [row for row in rows if row.get("deduplication_status") == "UNIQUE_MIRROR_GROUP_REPRESENTATIVE"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(representatives), 1)
        self.assertIsNone(duplicates[0]["q_value"])
        self.assertAlmostEqual(representatives[0]["q_value"], 0.125)
        self.assertEqual(len(result["opportunities"]), 1)
        self.assertEqual(len(result["mirror_duplicates"]), 1)
        self.assertEqual(result["profile"]["opportunity_count_before_mirror_deduplication"], 2)
        self.assertEqual(result["profile"]["mirror_duplicate_opportunity_count"], 1)
        self.assertEqual(result["profile"]["opportunity_count_before_limit"], 1)
        self.assertEqual(result["profile"]["numeric_trend_fdr_test_count"], 1)
        proof = result["mirror_duplicates"][0]["proof"]
        self.assertTrue(proof["exact_reciprocal_values"])
        self.assertTrue(proof["identical_experiment_support_within_each_system"])
        self.assertEqual(proof["matched_system_count"], 16)
        self.assertEqual(proof["matched_experiment_count"], 16)
        self.assertEqual(proof["matched_observation_count"], 32)

    def test_near_mirror_with_a_different_system_value_is_not_deduplicated(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_bidirectional_feature_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]
            )
        altered = next(
            row for row in bundle["conditions"]
            if row["condition_type"] == "FEATURE_B" and row["condition_id"] == "MIRROR_CB_1_1"
        )
        altered["raw_value"] = 4.25
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        rows = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(rows), 2)
        self.assertEqual(result["mirror_duplicates"], [])
        self.assertEqual(result["profile"]["numeric_trend_fdr_test_count"], 2)
        self.assertEqual(len(result["opportunities"]), 2)

    def test_approved_semantic_alias_is_excluded_before_tests_and_fdr(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_system_level_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0],
                condition_type="condition_alias", condition_unit="outcome-unit",
            )
        approved = {
            "canonical_concept_id": "CONCEPT_SHARED",
            "measurement_context": "same-cycle-100-measurement",
            "display_name": "Reviewed shared feature",
            "definition": "Explicitly supplied test definition",
            "review_status": "APPROVED",
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-01-01",
        }
        for row in bundle["observations"]:
            row["semantic_metadata"] = approved
        for row in bundle["conditions"]:
            row["semantic_metadata"] = approved
        result = build_scientific_opportunities(bundle, bootstrap_iterations=200)
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(result["correlations"], [])
        self.assertEqual(
            result["profile"]["self_association_exclusion_reason_counts"],
            {"SAME_APPROVED_SEMANTIC_CONCEPT": 1},
        )

    def test_same_approved_concept_with_different_measurement_context_is_not_auto_excluded(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_system_level_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0],
                condition_type="condition_alias", condition_unit="outcome-unit",
            )
        for row in bundle["observations"]:
            row["semantic_metadata"] = {
                "canonical_concept_id": "CONCEPT_SHARED",
                "measurement_context": "endpoint-cycle-100",
                "review_status": "APPROVED",
            }
        for row in bundle["conditions"]:
            row["semantic_metadata"] = {
                "canonical_concept_id": "CONCEPT_SHARED",
                "measurement_context": "initial-condition",
                "review_status": "APPROVED",
            }
        result = build_scientific_opportunities(bundle, bootstrap_iterations=200)
        self.assertEqual(result["profile"]["self_association_exclusion_count"], 0)
        between_system_rows = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(between_system_rows), 1)
        self.assertEqual(len(result["opportunities"]), 1)
        review = result["opportunities"][0]["semantic_review"]
        self.assertEqual(review["relationship_status"], "SAME_APPROVED_CONCEPT_CONTEXT_UNRESOLVED")
        self.assertEqual(review["status"], "APPROVED_METADATA_AVAILABLE_FOR_DOMAIN_REVIEW")

    def test_approved_direct_derivation_is_excluded_before_tests_and_fdr(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_system_level_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0],
                condition_type="condition_alias", condition_unit="outcome-unit",
            )
        for row in bundle["observations"]:
            row["semantic_metadata"] = {
                "canonical_concept_id": "OUTCOME_CONCEPT",
                "review_status": "APPROVED",
                "derivation_type": "CALCULATED",
                "derived_from": ["condition_alias"],
            }
        for row in bundle["conditions"]:
            row["semantic_metadata"] = {
                "canonical_concept_id": "CONDITION_CONCEPT",
                "review_status": "APPROVED",
            }
        result = build_scientific_opportunities(bundle, bootstrap_iterations=200)
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(
            result["profile"]["self_association_exclusion_reason_counts"],
            {"DECLARED_DIRECT_DERIVATION": 1},
        )

    def test_recorded_perfectly_co_varying_condition_is_flagged_for_confounding_review(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_system_level_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0],
                condition_type="current_density", condition_unit="mA cm-2",
            )
            for index, value in enumerate([10.0, 20.0, 30.0, 40.0], start=1):
                experiment = next(
                    row for row in bundle["experiments"]
                    if row["experiment_id"] == f"BE{study}_{index}"
                )
                condition_id = f"VOLTAGE_{study}_{index}"
                bundle["conditions"].append({
                    "condition_id": condition_id,
                    "system_ids": [experiment["system_id"]],
                    "condition_type": "voltage",
                    "raw_value": value,
                    "raw_unit": "V",
                    "value_state": "REPORTED",
                })
                experiment["condition_ids"].append(condition_id)
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=200
        )
        row = next(
            item for item in result["correlations"]
            if item["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
            and item["condition_type"] == "current_density"
        )
        review = row["confounding_review"]
        self.assertEqual(review["status"], "POTENTIAL_CO_EXPOSURE_REQUIRES_DOMAIN_REVIEW")
        finding = next(item for item in review["findings"] if item["condition_type"] == "voltage")
        self.assertEqual(finding["study_count"], 4)
        self.assertTrue(all(
            item["spearman_rho_with_primary_condition"] == 1.0
            for item in finding["study_details"]
        ))


    def test_canonical_identifier_matching_does_not_fold_case_or_punctuation(self):
        self.assertEqual(_identifier_key("Exact-ID.1"), "Exact-ID.1")
        self.assertNotEqual(_identifier_key("Exact-ID.1"), _identifier_key("exactid1"))


    def test_target_semantic_metadata_is_scoped_by_exact_endpoint_and_timepoint_type(self):
        records = [
            {
                "target_id": "Target-A",
                "endpoint_definition": "endpoint-a",
                "timepoint": 100,
                "semantic_metadata": {"review_status": "APPROVED", "canonical_concept_id": "concept:numeric"},
            },
            {
                "target_id": "Target-A",
                "endpoint_definition": "endpoint-a",
                "timepoint": "100",
                "semantic_metadata": {"review_status": "APPROVED", "canonical_concept_id": "concept:string"},
            },
        ]
        index = _semantic_metadata_index(
            records, ("target_id", "endpoint_definition", "timepoint")
        )
        numeric_key = _target_semantic_key("Target-A", "endpoint-a", 100)
        string_key = _target_semantic_key("Target-A", "endpoint-a", "100")
        self.assertNotEqual(numeric_key, string_key)
        self.assertEqual(index[numeric_key]["status"], "APPROVED")
        self.assertEqual(index[string_key]["status"], "APPROVED")
        self.assertEqual(index[numeric_key]["metadata"]["canonical_concept_id"], "concept:numeric")
        self.assertEqual(index[string_key]["metadata"]["canonical_concept_id"], "concept:string")

    def test_identifier_variants_are_not_excluded_as_the_same_attribute(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_system_level_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0],
                condition_type="target-y", condition_unit="outcome-unit",
            )
        result = build_scientific_opportunities(bundle, bootstrap_iterations=0)
        self.assertEqual(result["self_association_exclusions"], [])
        self.assertGreaterEqual(len(result["opportunities"]), 1)

    def test_reciprocal_pattern_with_different_endpoint_is_related_not_deduplicated(self):
        bundle = _bundle()
        for study in range(1, 5):
            _add_bidirectional_feature_study(
                bundle, study, [1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]
            )
        for observation in bundle["observations"]:
            if observation["target_id"] == "FEATURE_B":
                observation["endpoint_definition"] = "distinct-endpoint"
        result = build_scientific_opportunities(
            bundle, minimum_paired_studies=3, bootstrap_iterations=0
        )
        between_rows = [
            row for row in result["correlations"]
            if row["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        between_opportunities = [
            item for item in result["opportunities"]
            if item["analysis_family"] == "CONDITION_OUTCOME_BETWEEN_SYSTEM_SPEARMAN"
        ]
        self.assertEqual(len(between_rows), 2)
        self.assertEqual(len(between_opportunities), 2)
        self.assertTrue(all(row["p_value"] is not None for row in between_rows))
        self.assertEqual(result["mirror_duplicates"], [])
        self.assertEqual(result["profile"]["numeric_trend_fdr_test_count"], 2)
        self.assertEqual(len(result["related_opportunity_groups"]), 1)
        group = result["related_opportunity_groups"][0]
        self.assertEqual(len(group["member_opportunity_ids"]), 2)
        self.assertEqual(group["review_status"], "REQUIRES_DOMAIN_REVIEW")
        self.assertEqual(group["statistical_action"], "NO_DEDUPLICATION_NO_FDR_CHANGE")
        self.assertEqual(group["proof"]["context_dimensions_differ"], ["endpoint_definition"])

    def test_high_cardinality_conditions_keep_full_coverage_but_bound_pairwise_screen(self):
        bundle = _bundle()
        levels = [f"level_{index:02d}" for index in range(22)]
        for study in range(1, 4):
            _add_study(
                bundle, study, levels,
                [float(study * 100 + index) for index in range(len(levels))],
            )
        result = build_scientific_opportunities(
            bundle, bootstrap_iterations=0, maximum_levels_per_condition=20
        )
        self.assertEqual(len(result["condition_level_support"]), 22)
        self.assertEqual(result["profile"]["condition_level_count_total"], 22)
        self.assertEqual(
            result["profile"]["categorical_level_count_excluded_from_pairwise_screen"], 2
        )
        self.assertEqual(len(result["contrasts"]), 190)
        selected_levels = {
            row["level_a"] for row in result["contrasts"]
        } | {row["level_b"] for row in result["contrasts"]}
        self.assertEqual(len(selected_levels), 20)


if __name__ == "__main__":
    unittest.main()
