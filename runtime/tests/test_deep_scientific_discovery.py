from __future__ import annotations

import unittest

from dor.deep_scientific_discovery import build_deep_scientific_discovery


def _bundle():
    return {
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "evidence": [],
        "comparisons": [],
    }


def _add_experiment(bundle, study_no, experiment_no, *, conditions=None, outcomes=None, system_no=None):
    study_id = f"STUDY_{study_no}"
    system_id = f"SYSTEM_{study_no}" if system_no is None else f"SYSTEM_{study_no}_{system_no}"
    experiment_id = f"EXP_{study_no}_{experiment_no}"
    if not any(item["study_id"] == study_id for item in bundle["studies"]):
        bundle["studies"].append({"study_id": study_id, "source_locators": []})
    if not any(item["system_id"] == system_id for item in bundle["systems"]):
        bundle["systems"].append({
            "system_id": system_id, "study_ids": [study_id], "system_type": "synthetic"
        })
    condition_ids = []
    for name, value in (conditions or {}).items():
        condition_id = f"COND_{study_no}_{experiment_no}_{name}"
        condition_ids.append(condition_id)
        bundle["conditions"].append({
            "condition_id": condition_id, "system_ids": [system_id],
            "condition_type": name, "raw_value": value, "raw_unit": f"unit_{name}",
            "value_state": "REPORTED",
        })
    bundle["experiments"].append({
        "experiment_id": experiment_id, "study_id": study_id,
        "system_id": system_id, "condition_ids": condition_ids,
    })
    for target, value in (outcomes or {}).items():
        bundle["observations"].append({
            "observation_id": f"OBS_{study_no}_{experiment_no}_{target}",
            "experiment_id": experiment_id, "target_id": target,
            "endpoint_definition": "endpoint", "timepoint": "t0",
            "value_state": "REPORTED", "raw_value": value,
            "raw_unit": f"unit_{target}", "evidence_ids": [],
        })


class DeepScientificDiscoveryTests(unittest.TestCase):
    def test_quadratic_response_is_detected_with_one_effect_per_study(self):
        bundle = _bundle()
        for study in range(1, 5):
            for index, x in enumerate(range(-4, 5), start=1):
                _add_experiment(
                    bundle, study, index,
                    conditions={"dose": float(x)},
                    outcomes={"response": float(x * x + study * 2)},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["nonlinear_opportunities"]
            if item["signal_type"] == "NONLINEAR_QUADRATIC_RESPONSE"
        ]
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["independent_study_count"], 4)
        self.assertEqual(candidate["analysis_unit"] if "analysis_unit" in candidate else "INDEPENDENT_STUDY",
                         "INDEPENDENT_STUDY")
        self.assertGreater(candidate["effect_estimate"], 0.10)
        self.assertEqual(len(candidate["study_effects"]), 4)
        self.assertEqual(candidate["model_comparison"], "LEAVE_ONE_EXPERIMENT_OUT_LINEAR_VS_QUADRATIC")


    def test_piecewise_linear_threshold_response_is_reported_as_a_candidate(self):
        bundle = _bundle()
        levels = (-4, -3, -2, -1, 1, 2, 3, 4, 5, 6)
        for study in range(1, 5):
            for index, x in enumerate(levels, start=1):
                y = float(x + 3 * max(0.0, x) + study * 5)
                _add_experiment(
                    bundle, study, index,
                    conditions={"dose": float(x)},
                    outcomes={"response": y},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["nonlinear_opportunities"]
            if item["signal_type"] == "NONLINEAR_THRESHOLD_RESPONSE"
        ]
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["independent_study_count"], 4)
        self.assertLess(abs(candidate["threshold_value_median_across_eligible_studies"]), 0.1)
        self.assertIn("PIECEWISE_LINEAR", candidate["model_comparison"])

    def test_two_way_interaction_is_detected_beyond_additive_terms(self):
        bundle = _bundle()
        levels = (-1.0, 0.0, 1.0)
        for study in range(1, 5):
            index = 0
            for x in levels:
                for z in levels:
                    index += 1
                    _add_experiment(
                        bundle, study, index,
                        conditions={"factor_a": x, "factor_b": z},
                        outcomes={"response": x * z},
                    )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["interaction_opportunities"]
            if item["interaction_order"] == 2
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertGreater(candidates[0]["effect_estimate"], 0.10)
        self.assertEqual(candidates[0]["model_comparison"],
                         "LEAVE_ONE_EXPERIMENT_OUT_ADDITIVE_VS_ADDITIVE_PLUS_PRODUCT_TERM")

    def test_three_way_interaction_is_tested_after_all_lower_order_terms(self):
        bundle = _bundle()
        levels = (-1.0, 0.0, 1.0)
        for study in range(1, 5):
            index = 0
            for x in levels:
                for z in levels:
                    for w in levels:
                        index += 1
                        _add_experiment(
                            bundle, study, index,
                            conditions={"factor_a": x, "factor_b": z, "factor_c": w},
                            outcomes={"response": x * z * w},
                        )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["interaction_opportunities"]
            if item["interaction_order"] == 3
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertGreater(candidates[0]["effect_estimate"], 0.10)
        self.assertIn("PLUS_THREE_WAY_PRODUCT", candidates[0]["model_comparison"])

    def test_pareto_frontiers_report_all_objective_directions(self):
        bundle = _bundle()
        for study in range(1, 6):
            for index, value in enumerate((1, 2, 3, 4, 5), start=1):
                objective_b = value if study == 5 else 10 - value
                _add_experiment(
                    bundle, study, index,
                    outcomes={"objective_a": float(value), "objective_b": float(objective_b)},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        self.assertEqual(len(result["multiobjective_opportunities"]), 1)
        candidate = result["multiobjective_opportunities"][0]
        self.assertEqual(candidate["independent_study_count"], 5)
        self.assertLess(candidate["effect_estimate"], -0.9)
        self.assertEqual(candidate["effect_direction"], "NEGATIVE")
        self.assertEqual(candidate["counterexample_direction"],
                         "OPPOSITE_TO_MEDIAN_STUDY_EFFECT_DIRECTION")
        self.assertEqual(candidate["counterexample_study_ids"], ["STUDY_5"])
        directions = {item["direction_scenario"] for item in result["pareto_frontier_rows"]}
        self.assertEqual(directions, {"MAX_MAX", "MAX_MIN", "MIN_MAX", "MIN_MIN"})
        self.assertTrue(all(not item["objective_direction_declared_by_user"]
                            for item in result["pareto_frontier_rows"]))

    def test_incomplete_features_are_not_forced_into_one_global_complete_case_set(self):
        bundle = _bundle()
        for study in range(1, 4):
            for index in range(1, 13):
                conditions = {}
                if index <= 9:
                    conditions["feature_a"] = float(index)
                if index >= 4:
                    conditions["feature_b"] = float(index - 3)
                _add_experiment(
                    bundle, study, index, conditions=conditions,
                    outcomes={"response": float(index * index)},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=0,
            minimum_model_improvement=0.01,
        )
        self.assertEqual(
            result["profile"]["data_subset_policy"],
            "PAIRWISE_AVAILABLE_SUBSETS_NO_GLOBAL_COMPLETE_CASE_REQUIREMENT",
        )
        self.assertGreaterEqual(result["profile"]["outcome_condition_hypothesis_count"], 2)
        self.assertGreater(
            len({row["condition"]["condition_type"] for row in result["nonlinear_opportunities"]}),
            0,
        )


    def test_between_system_quadratic_response_works_with_one_experiment_per_system(self):
        bundle = _bundle()
        for study in range(1, 5):
            for system_no, x in enumerate(range(-4, 5), start=1):
                _add_experiment(
                    bundle, study, system_no, system_no=system_no,
                    conditions={"dose": float(x)},
                    outcomes={"response": float(x * x + study * 3)},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["nonlinear_opportunities"]
            if item["signal_type"] == "NONLINEAR_QUADRATIC_RESPONSE"
            and item["analysis_design"] == "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertIn("LEAVE_ONE_SYSTEM_OUT", candidates[0]["model_comparison"])
        self.assertIn("System composition", candidates[0]["confounding_review"])
        self.assertEqual(len(candidates[0]["study_effects"]), 4)
        self.assertTrue(all(item["system_count"] == 9 for item in candidates[0]["study_effects"]))
        self.assertTrue(all(len(item["system_ids"]) == 9 for item in candidates[0]["study_effects"]))
        self.assertTrue(all(len(item["system_effects"]) == 1 for item in candidates[0]["study_effects"]))

    def test_between_system_two_way_interaction_works_with_one_experiment_per_system(self):
        bundle = _bundle()
        levels = (-1.0, 0.0, 1.0)
        for study in range(1, 5):
            system_no = 0
            for x in levels:
                for z in levels:
                    system_no += 1
                    _add_experiment(
                        bundle, study, system_no, system_no=system_no,
                        conditions={"factor_a": x, "factor_b": z},
                        outcomes={"response": x * z},
                    )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["interaction_opportunities"]
            if item["interaction_order"] == 2
            and item["analysis_design"] == "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertIn("LEAVE_ONE_SYSTEM_OUT", candidates[0]["model_comparison"])
        self.assertTrue(all(item["system_count"] == 9 for item in candidates[0]["study_effects"]))


    def test_between_system_three_way_interaction_uses_systems_as_validation_units(self):
        bundle = _bundle()
        levels = (-1.0, 0.0, 1.0)
        for study in range(1, 5):
            system_no = 0
            for x in levels:
                for z in levels:
                    for w in levels:
                        system_no += 1
                        _add_experiment(
                            bundle, study, system_no, system_no=system_no,
                            conditions={"factor_a": x, "factor_b": z, "factor_c": w},
                            outcomes={"response": x * z * w},
                        )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["interaction_opportunities"]
            if item["interaction_order"] == 3
            and item["analysis_design"] == "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertIn("LEAVE_ONE_SYSTEM_OUT", candidates[0]["model_comparison"])
        self.assertTrue(all(item["system_count"] == 27 for item in candidates[0]["study_effects"]))

    def test_between_system_multiobjective_frontier_is_available_without_repeated_systems(self):
        bundle = _bundle()
        for study in range(1, 5):
            for system_no, value in enumerate((1, 2, 3, 4, 5), start=1):
                _add_experiment(
                    bundle, study, system_no, system_no=system_no,
                    outcomes={"objective_a": float(value), "objective_b": float(10 - value)},
                )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=200
        )
        candidates = [
            item for item in result["multiobjective_opportunities"]
            if item["analysis_design"] == "BETWEEN_SYSTEM_CROSS_SECTIONAL_WITHIN_STUDY"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["independent_study_count"], 4)
        self.assertTrue(all(item["system_count"] == 5 for item in candidates[0]["study_effects"]))
        between_fronts = [
            item for item in result["pareto_frontier_rows"]
            if item["population_type"] == "BETWEEN_SYSTEMS_CROSS_SECTIONAL_WITHIN_STUDY"
        ]
        self.assertEqual(len(between_fronts), 80)
        self.assertTrue(all(item["experiment_id"] is None for item in between_fronts))

    def test_repeated_experiments_do_not_become_independent_studies(self):
        bundle = _bundle()
        for index in range(1, 21):
            _add_experiment(
                bundle, 1, index,
                conditions={"dose": float(index)},
                outcomes={"response": float(index * index)},
            )
        result = build_deep_scientific_discovery(
            bundle, minimum_studies=3, bootstrap_iterations=0
        )
        self.assertEqual(result["profile"]["experiment_count_with_numeric_outcomes"], 20)
        self.assertEqual(result["opportunities"], [])


if __name__ == "__main__":
    unittest.main()
