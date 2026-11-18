import json
import unittest
from pathlib import Path, PureWindowsPath

from dor.publication import _validate_plan


ROOT = Path(__file__).resolve().parents[2]
OPTIONAL_STAGE_IDS = {
    "mechanism_plan_preparation",
    "response_surface_generation",
    "mechanism_evidence_bridge",
}
RECONCILIATION_STAGE_IDS = {
    "reconciliation_decision_review",
    "reconciliation_decision_validation",
}


class ConditionalRunPlanTemplateTests(unittest.TestCase):
    def _load_plan(self, relative_path):
        return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))

    def test_both_adapter_routes_declare_the_same_conditional_follow_on_stages(self):
        plans = [
            self._load_plan("templates/run_plan.example.json"),
            self._load_plan("templates/run_plan.canonical_adapter.example.json"),
        ]
        for plan in plans:
            with self.subTest(plan=plan["project_id"]):
                stages = {item["stage_id"]: item for item in plan["stages"]}
                self.assertTrue(OPTIONAL_STAGE_IDS.issubset(stages))
                producers = {
                    output["artifact_id"]: stage["stage_id"]
                    for stage in plan["stages"]
                    for output in stage["outputs"]
                }
                for stage_id in OPTIONAL_STAGE_IDS:
                    stage = stages[stage_id]
                    activation = stage["activation"]
                    self.assertEqual(activation, {
                        "artifact_id": "interaction_selection",
                        "json_pointer": "/selected_interaction_ids",
                        "operator": "array_non_empty",
                    })
                    self.assertIn(activation["artifact_id"], stage["inputs"])
                    for artifact_id in stage["inputs"]:
                        producer = producers.get(artifact_id)
                        if producer is not None:
                            self.assertIn(producer, stage["depends_on"])

                self.assertEqual(
                    stages["response_surface_generation"]["required_gate"], "G3"
                )
                self.assertEqual(
                    stages["mechanism_evidence_bridge"]["required_gate"], "G3"
                )
                self.assertIn(
                    "mechanism_plan_preparation",
                    stages["mechanism_evidence_bridge"]["depends_on"],
                )
                self.assertIn(
                    "response_surface_generation",
                    stages["mechanism_evidence_bridge"]["depends_on"],
                )

    def test_both_routes_bind_reconciliation_review_and_validation_before_g2(self):
        cases = [
            (
                "templates/run_plan.example.json",
                "canonical_build",
                "03_canonical/canonical_bundle.json",
            ),
            (
                "templates/run_plan.canonical_adapter.example.json",
                "adapter_artifact_materialization",
                "00_adapter/materialized/canonical_bundle.json",
            ),
        ]
        for path, canonical_producer, bundle_path in cases:
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            producers = {
                output["artifact_id"]: stage["stage_id"]
                for stage in plan["stages"]
                for output in stage["outputs"]
            }
            with self.subTest(path=path):
                self.assertTrue(RECONCILIATION_STAGE_IDS.issubset(stages))
                review = stages["reconciliation_decision_review"]
                validation = stages["reconciliation_decision_validation"]
                g2 = stages["g2_review_packet"]
                self.assertIn("canonical_reconciliation", review["depends_on"])
                self.assertIn(canonical_producer, review["depends_on"])
                self.assertIn("reconciliation_report", review["inputs"])
                self.assertIn("reconciliation_review_queue", review["inputs"])
                self.assertEqual(
                    review["outputs"],
                    [{
                        "artifact_id": "reconciliation_decisions",
                        "path": "04_reconciliation/reconciliation_decisions.json",
                    }],
                )
                self.assertIn("reconciliation_decision_review", validation["depends_on"])
                self.assertIn("canonical_reconciliation", validation["depends_on"])
                self.assertIn(canonical_producer, validation["depends_on"])
                self.assertEqual(
                    validation["inputs"],
                    ["canonical_bundle", "reconciliation_report", "reconciliation_decisions"],
                )
                self.assertEqual(
                    validation["outputs"],
                    [{
                        "artifact_id": "reconciliation_decision_validation",
                        "path": "04_reconciliation/reconciliation_decision_validation.json",
                    }],
                )
                self.assertIn("reconciliation_decision_review", g2["depends_on"])
                self.assertIn("reconciliation_decision_validation", g2["depends_on"])
                self.assertIn("reconciliation_decisions", g2["inputs"])
                self.assertIn("reconciliation_decision_validation", g2["inputs"])
                self.assertEqual(producers["canonical_bundle"], canonical_producer)
                self.assertEqual(
                    next(output["path"] for output in stages[canonical_producer]["outputs"]
                         if output["artifact_id"] == "canonical_bundle"),
                    bundle_path,
                )
                for artifact_id in g2["inputs"]:
                    producer = producers.get(artifact_id)
                    if producer is not None:
                        self.assertIn(producer, g2["depends_on"])

    def test_g2_binds_discovery_report_and_selected_scope_record(self):
        for path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
        ):
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            g2 = stages["g2_review_packet"]
            with self.subTest(path=path):
                self.assertIn("discovery_report", g2["inputs"])
                self.assertIn("research_scope_record", g2["inputs"])
                self.assertIn("exploratory_discovery", g2["depends_on"])
                self.assertIn("research_scope_selection", g2["depends_on"])
                self.assertIn(
                    {"artifact_id": "research_scope_record", "path": "05_scope/research_scope_record.json"},
                    stages["research_scope_selection"]["outputs"],
                )
    def test_discovery_engine_outputs_are_declared_and_available_to_scope_review(self):
        expected = {
            "discovery_manifest", "discovery_report", "discovery_brief",
            "discovery_data_profile", "target_support", "study_coverage",
            "condition_support", "joint_support", "signal_catalogue",
            "condition_level_support", "condition_outcome_contrasts",
            "condition_outcome_correlations", "research_opportunities",
            "evidence_ledger", "scientific_analysis_profile",
            "candidate_value_inventory", "candidate_value_reconciliation",
            "candidate_pairwise_reconciliation", "candidate_reconciliation_profile",
            "missingness_opportunity_profile", "candidate_sensitivity_opportunities",
            "candidate_sensitivity_profile",
            "deep_research_opportunities", "deep_scientific_discovery_profile",
            "deep_condition_response", "deep_interaction_candidates",
            "multiobjective_tradeoff_candidates", "multiobjective_frontiers",
            "deep_evidence_ledger",
        }
        for path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
            "templates/run_plan.single_study.example.json",
            "templates/run_plan.canonical_adapter.single_study.example.json",
        ):
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            discovery = stages["exploratory_discovery"]
            scope = stages["research_scope_selection"]
            with self.subTest(path=path):
                output_ids = {item["artifact_id"] for item in discovery["outputs"]}
                self.assertEqual(output_ids, expected)
                scope_expected = expected - {
                    "candidate_value_inventory", "candidate_value_reconciliation",
                    "candidate_pairwise_reconciliation", "candidate_sensitivity_opportunities",
                    "deep_scientific_discovery_profile", "deep_condition_response",
                    "deep_interaction_candidates", "multiobjective_tradeoff_candidates",
                    "multiobjective_frontiers", "deep_evidence_ledger",
                }
                self.assertTrue(scope_expected.issubset(set(scope["inputs"])))
                self.assertIn("deep_research_opportunities", scope["inputs"])
                self.assertFalse({
                    "candidate_value_inventory", "candidate_value_reconciliation",
                    "candidate_pairwise_reconciliation", "candidate_sensitivity_opportunities",
                }.intersection(scope["inputs"]))
                self.assertIn("candidate_reconciliation_profile", scope["inputs"])
                for artifact_id in expected:
                    output = next(item for item in discovery["outputs"] if item["artifact_id"] == artifact_id)
                    self.assertTrue(output["path"].startswith("04_discovery/"))

    def test_stage_execution_contract_registers_every_discovery_output(self):
        contract = json.loads(
            (ROOT / "runtime/src/dor/stage_execution_contract.json").read_text(encoding="utf-8")
        )
        stages = {item["stage_id"]: item for item in contract["stages"]}
        expected = {
            "discovery_manifest", "discovery_report", "discovery_brief",
            "discovery_data_profile", "target_support", "study_coverage",
            "condition_support", "joint_support", "signal_catalogue",
            "condition_level_support", "condition_outcome_contrasts",
            "condition_outcome_correlations", "research_opportunities",
            "evidence_ledger", "scientific_analysis_profile",
            "candidate_value_inventory", "candidate_value_reconciliation",
            "candidate_pairwise_reconciliation", "candidate_reconciliation_profile",
            "missingness_opportunity_profile", "candidate_sensitivity_opportunities",
            "candidate_sensitivity_profile",
            "deep_research_opportunities", "deep_scientific_discovery_profile",
            "deep_condition_response", "deep_interaction_candidates",
            "multiobjective_tradeoff_candidates", "multiobjective_frontiers",
            "deep_evidence_ledger",
        }
        discovery = stages["exploratory_discovery"]
        scope = stages["research_scope_selection"]
        for variant in discovery["route_variants"]:
            with self.subTest(route=variant["route"]):
                self.assertEqual(
                    {item["artifact_id"] for item in variant["outputs"]},
                    expected,
                )
        scope_expected = expected - {
            "candidate_value_inventory", "candidate_value_reconciliation",
            "candidate_pairwise_reconciliation", "candidate_sensitivity_opportunities",
            "deep_scientific_discovery_profile", "deep_condition_response",
            "deep_interaction_candidates", "multiobjective_tradeoff_candidates",
            "multiobjective_frontiers", "deep_evidence_ledger",
        }
        for variant in scope["route_variants"]:
            with self.subTest(scope_route=variant["route"]):
                self.assertTrue(scope_expected.issubset(set(variant["inputs"])))
                self.assertIn("deep_research_opportunities", variant["inputs"])
                self.assertFalse({
                    "candidate_value_inventory", "candidate_value_reconciliation",
                    "candidate_pairwise_reconciliation", "candidate_sensitivity_opportunities",
                }.intersection(variant["inputs"]))
                self.assertIn("candidate_reconciliation_profile", variant["inputs"])

    def test_canonical_route_uses_materialized_bundle_as_the_bundle_producer(self):
        plan = self._load_plan("templates/run_plan.canonical_adapter.example.json")
        stages = {item["stage_id"]: item for item in plan["stages"]}
        producers = {
            output["artifact_id"]: stage["stage_id"]
            for stage in plan["stages"]
            for output in stage["outputs"]
        }
        self.assertEqual(producers["canonical_bundle"], "adapter_artifact_materialization")
        self.assertIn(
            "adapter_artifact_materialization",
            stages["mechanism_plan_preparation"]["depends_on"],
        )
        self.assertIn(
            "adapter_artifact_materialization",
            stages["mechanism_evidence_bridge"]["depends_on"],
        )

    def test_controlled_single_study_templates_keep_both_entry_routes_and_all_gates(self):
        cases = (
            ("templates/run_plan.single_study.example.json", "STRUCTURED_DATASET"),
            ("templates/run_plan.canonical_adapter.single_study.example.json", "CANONICAL_BUNDLE"),
        )
        for path, route in cases:
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            outputs = {
                output["artifact_id"]: output["path"]
                for stage in plan["stages"] for output in stage["outputs"]
            }
            with self.subTest(path=path):
                self.assertEqual(plan["execution_profile"], "CONTROLLED_SINGLE_STUDY")
                self.assertIn("adapter_package_validation", stages)
                self.assertIn(
                    "source_audit" if route == "STRUCTURED_DATASET"
                    else "adapter_artifact_materialization",
                    stages,
                )
                self.assertEqual(
                    stages["single_study_scope_review"]["required_gate"], "G2"
                )
                self.assertEqual(
                    stages["single_study_scope_validation"]["required_gate"], "G2"
                )
                self.assertEqual(
                    stages["single_study_na_artifacts"]["required_gate"], "G2"
                )
                self.assertEqual(
                    stages["independent_result_review"]["required_gate"], "G3"
                )
                self.assertEqual(
                    stages["publication_package_assembly"]["required_gate"], "G4"
                )
                self.assertEqual(
                    stages["independent_result_review"]["executor"], "worker"
                )
                self.assertNotIn("baseline_model_fit", stages)
                self.assertNotIn("nested_reproducibility_evaluation", stages)
                self.assertNotIn("interaction_discovery", stages)
                self.assertNotIn("interaction_robustness", stages)
                self.assertEqual(
                    outputs["virtual_prediction"],
                    "06_modeling/not_applicable/virtual_prediction.json",
                )
                self.assertEqual(
                    outputs["single_study_applicability_record"],
                    "05_scope/single_study_applicability_record.json",
                )
                self.assertEqual(
                    outputs["single_study_applicability_validation"],
                    "05_scope/single_study_applicability_validation.json",
                )
                worker_inputs = set(stages["independent_result_review"]["inputs"])
                self.assertTrue({
                    "single_study_applicability_record",
                    "single_study_applicability_validation",
                    "canonical_bundle",
                    "modeling_task",
                    "model_report",
                    "reproducibility_evaluation",
                    "interaction_report",
                    "robustness_report",
                    "interaction_selection",
                }.issubset(worker_inputs))
                self.assertIn(
                    "single_study_scope_validation",
                    stages["publication_package_assembly"]["depends_on"],
                )

    def test_single_study_publication_plans_include_traceable_na_records_for_each_route(self):
        cases = (
            ("templates/publication_package_plan.single_study.example.json",
             "03_canonical/canonical_bundle.json"),
            ("templates/publication_package_plan.canonical_adapter.single_study.example.json",
             "00_adapter/materialized/canonical_bundle.json"),
        )
        required = {
            "SINGLE_STUDY_APPLICABILITY_RECORD",
            "SINGLE_STUDY_APPLICABILITY_VALIDATION",
            "MODEL_NOT_APPLICABLE_RECORD",
            "REPRODUCIBILITY_NOT_APPLICABLE_RECORD",
            "INTERACTION_NOT_APPLICABLE_RECORD",
            "INTERACTION_NOT_APPLICABLE_MANIFEST",
            "ROBUSTNESS_NOT_APPLICABLE_RECORD",
            "ROBUSTNESS_NOT_APPLICABLE_MANIFEST",
            "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD",
            "INTERACTION_SELECTION",
            "WORKER_REVIEW_RECORD",
            "HUMAN_DISPOSITION_RECORD",
            "HUMAN_DISPOSITION_VALIDATION",
        }
        for path, expected_bundle in cases:
            plan = self._load_plan(path)
            artifacts = {item["artifact_id"]: item for item in plan["artifacts"]}
            with self.subTest(path=path):
                self.assertTrue(required.issubset(artifacts))
                self.assertEqual(artifacts["CANONICAL_BUNDLE"]["source_path"], expected_bundle)
                self.assertEqual(artifacts["SINGLE_STUDY_APPLICABILITY_RECORD"]["status"], "requires_review")
                self.assertEqual(_validate_plan(plan), plan["artifacts"])
                run_plan_path = (
                    "templates/run_plan.single_study.example.json"
                    if "canonical_adapter" not in path
                    else "templates/run_plan.canonical_adapter.single_study.example.json"
                )
                run_plan = self._load_plan(run_plan_path)
                run_outputs = {
                    output["artifact_id"]: output["path"]
                    for stage in run_plan["stages"] for output in stage["outputs"]
                }
                for artifact_id, item in artifacts.items():
                    if item.get("source_path") and artifact_id.lower() in {
                        "single_study_applicability_record",
                        "single_study_applicability_validation",
                        "model_not_applicable_record",
                        "reproducibility_not_applicable_record",
                        "interaction_not_applicable_record",
                        "interaction_not_applicable_manifest",
                        "robustness_not_applicable_record",
                        "robustness_not_applicable_manifest",
                        "virtual_prediction_not_applicable_record",
                        "interaction_selection",
                        "worker_review_record",
                        "human_disposition_record",
                        "human_disposition_validation",
                    }:
                        self.assertEqual(item["source_path"],
                                         run_outputs[{
                                             "single_study_applicability_record": "single_study_applicability_record",
                                             "single_study_applicability_validation": "single_study_applicability_validation",
                                             "model_not_applicable_record": "model_report",
                                             "reproducibility_not_applicable_record": "reproducibility_evaluation",
                                             "interaction_not_applicable_record": "interaction_report",
                                             "interaction_not_applicable_manifest": "interaction_manifest",
                                             "robustness_not_applicable_record": "robustness_report",
                                             "robustness_not_applicable_manifest": "robustness_manifest",
                                             "virtual_prediction_not_applicable_record": "virtual_prediction",
                                             "interaction_selection": "interaction_selection",
                                             "worker_review_record": "worker_review_output",
                                             "human_disposition_record": "reviewed_findings",
                                             "human_disposition_validation": "reviewed_findings_validation",
                                         }[artifact_id.lower()]])
                for artifact_id in (
                    "MODEL_NOT_APPLICABLE_RECORD",
                    "REPRODUCIBILITY_NOT_APPLICABLE_RECORD",
                    "INTERACTION_NOT_APPLICABLE_RECORD",
                    "INTERACTION_NOT_APPLICABLE_MANIFEST",
                    "ROBUSTNESS_NOT_APPLICABLE_RECORD",
                    "ROBUSTNESS_NOT_APPLICABLE_MANIFEST",
                    "VIRTUAL_PREDICTION_NOT_APPLICABLE_RECORD",
                ):
                    self.assertEqual(artifacts[artifact_id]["status"], "complete")
                    self.assertIsNotNone(artifacts[artifact_id]["source_path"])
                    self.assertTrue("NOT_APPLICABLE" in artifacts[artifact_id]["description"].upper()
                                    or "not applicable" in artifacts[artifact_id]["description"].lower())

    def test_core_skill_and_adapter_contract_preserve_cross_disciplinary_boundary(self):
        skill = (ROOT / ".agents" / "skills" / "datafication-of-reproducibility" / "SKILL.md").read_text(encoding="utf-8")
        adapter_contract = (ROOT / "docs" / "ADAPTER_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("Cross-disciplinary boundary (immutable)", skill)
        self.assertIn("hard architectural boundary", adapter_contract)
        self.assertIn("independently maintained external adapters", adapter_contract)

    def test_manual_review_outputs_have_formal_schemas_and_examples(self):
        review_schema = json.loads(
            (ROOT / "schemas" / "run_review_packet.schema.json").read_text(encoding="utf-8")
        )
        findings_schema = json.loads(
            (ROOT / "schemas" / "reviewed_findings.schema.json").read_text(encoding="utf-8")
        )
        worker_schema = json.loads(
            (ROOT / "schemas" / "worker_result.schema.json").read_text(encoding="utf-8")
        )
        worker_example = json.loads(
            (ROOT / "templates" / "worker_result.example.json").read_text(encoding="utf-8")
        )
        review_example = json.loads(
            (ROOT / "templates" / "run_review_packet.example.json").read_text(encoding="utf-8")
        )
        findings_example = json.loads(
            (ROOT / "templates" / "reviewed_findings.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(review_example["packet_status"], "AWAITING_HUMAN_REVIEW")
        self.assertIn("g2_review_packet", review_schema["properties"]["stage_id"]["enum"])
        self.assertEqual(
            findings_example["worker_output"]["artifact_id"], "worker_review_output"
        )
        self.assertIn(
            "ACCEPT_WITH_CHANGES",
            findings_schema["properties"]["findings"]["items"]["properties"]["disposition"]["enum"],
        )
        worker_finding = worker_schema["properties"]["findings"]["items"]
        self.assertTrue({
            "finding_id", "summary", "supporting_artifact_ids", "evidence",
        }.issubset(set(worker_finding["required"])))
        self.assertEqual(worker_example["schema_version"], "1.0")
        self.assertIn("evidence", worker_example["findings"][0])
        publication_plan = json.loads(
            (ROOT / "templates" / "publication_package_plan.example.json").read_text(encoding="utf-8")
        )
        self.assertIsNone(publication_plan.get("domain_profile"))
        publication_ids = {item["artifact_id"] for item in publication_plan["artifacts"]}
        self.assertTrue({
            "WORKER_REVIEW_RECORD",
            "HUMAN_DISPOSITION_RECORD",
            "HUMAN_DISPOSITION_VALIDATION",
            "COHORT_REVIEW_RECORD",
            "COHORT_REVIEW_VALIDATION",
        }.issubset(publication_ids))
        plan_items = {item["artifact_id"]: item for item in publication_plan["artifacts"]}
        self.assertNotIn("domain_profile", publication_plan)
        for item in publication_plan["artifacts"]:
            if item.get("source_path") is not None:
                self.assertTrue(
                    isinstance(item.get("source_artifact_id"), str)
                    and item["source_artifact_id"].strip()
                )
        self.assertEqual(plan_items["DATA_DICTIONARY_001"]["status"], "not_generated")
        self.assertNotIn("source_path", plan_items["DATA_DICTIONARY_001"])
        for relative_path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
        ):
            run_plan = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
            output_paths = {
                output["artifact_id"]: output["path"]
                for stage in run_plan["stages"]
                for output in stage["outputs"]
            }
            source_bindings = {
                "MODEL_ARTIFACT_001": "model_artifact",
                "MODEL_REPORT_001": "model_report",
                "REPRODUCIBILITY_EVALUATION_001": "reproducibility_evaluation",
                "INTERACTION_REPORT_001": "interaction_report",
                "INTERACTION_ROBUSTNESS_001": "robustness_report",
                "INTERACTION_SELECTION_001": "interaction_selection",
                "VIRTUAL_PREDICTION_001": "virtual_prediction",
                "WORKER_REVIEW_RECORD": "worker_review_output",
                "HUMAN_DISPOSITION_RECORD": "reviewed_findings",
                "HUMAN_DISPOSITION_VALIDATION": "reviewed_findings_validation",
                "COHORT_REVIEW_RECORD": "cohort_review_record",
                "COHORT_REVIEW_VALIDATION": "cohort_review_validation",
            }
            for package_id, run_artifact_id in source_bindings.items():
                self.assertEqual(
                    plan_items[package_id]["source_path"],
                    output_paths[run_artifact_id],
                )
                self.assertEqual(
                    plan_items[package_id]["source_artifact_id"],
                    run_artifact_id,
                )
            # Virtual prediction is conditional on virtual_query_decision (RUN_PREDICTION vs NOT_APPLICABLE).
            self.assertIn(plan_items["VIRTUAL_PREDICTION_001"]["artifact_id"], {"VIRTUAL_PREDICTION_001"})
            self.assertIn("status", plan_items["VIRTUAL_PREDICTION_001"])
            optional_paths = {
                "MECHANISM_PLAN_001": "review/mechanism_plan.json",
                "MECHANISM_BRIDGE_001": "07_mechanism_bridge/mechanism_evidence_bridge_report.json",
                "MECHANISM_FINDINGS_001": "07_mechanism_bridge/mechanism_findings.json",
                "MECHANISM_LEDGER_001": "07_mechanism_bridge/mechanism_evidence_ledger.csv",
                "MECHANISM_REVIEW_QUEUE_001": "07_mechanism_bridge/mechanism_review_queue.csv",
                "MECHANISM_MANIFEST_001": "07_mechanism_bridge/mechanism_evidence_bridge_manifest.json",
                "RESPONSE_SURFACE_REPORT_001": "07_response_surface/interaction_response_surface_report.json",
                "RESPONSE_SURFACE_DATA_001": "07_response_surface/interaction_response_surface.csv",
                "RESPONSE_SURFACE_MANIFEST_001": "response_surface/interaction_response_surface_manifest.json",
                "RESPONSE_SURFACE_SUPPORT_001": "07_response_surface/interaction_observed_support.csv",
                "RESPONSE_SURFACE_MARGINALS_001": "07_response_surface/interaction_marginal_effects.csv",
            }
            for package_id, expected_path in optional_paths.items():
                self.assertEqual(plan_items[package_id]["path"], expected_path)
                self.assertEqual(plan_items[package_id]["status"], "not_generated")
                self.assertNotIn("source_path", plan_items[package_id])
        for relative_path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
        ):
            plan = self._load_plan(relative_path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            for stage_id in ("g0_review_packet", "g1_review_packet", "g2_review_packet"):
                self.assertEqual(stages[stage_id]["executor"], "manual")
                self.assertEqual(stages[stage_id]["outputs"][0]["artifact_id"], stage_id)
            expected_g0_inputs = {
                frozenset({
                    "dataset_manifest", "source_inventory", "data_audit_report",
                    "mapping_review_queue", "adapter_handoff",
                }),
                frozenset({
                    "dataset_manifest", "source_inventory", "adapter_handoff",
                    "materialization_manifest",
                }),
            }
            self.assertIn(frozenset(stages["g0_review_packet"]["inputs"]), expected_g0_inputs)
            self.assertEqual(
                frozenset(stages["g1_review_packet"]["inputs"]),
                frozenset({
                    "mapping_plan", "mapping_validation", "source_inventory",
                    "build_spec", "build_spec_validation",
                }),
            )
            self.assertTrue({
                "canonical_bundle", "canonical_validation_report",
                "reconciliation_report", "reconciliation_review_queue",
                "reconciliation_decisions", "reconciliation_decision_validation",
                "discovery_report", "research_scope_record", "modeling_task",
                "virtual_query_decision",
            }.issubset(set(stages["g2_review_packet"]["inputs"])))
            expected_packet_dirs = {
                "g0_review_packet": "01_audit" if "data_audit_report" in stages["g0_review_packet"]["inputs"] else "01_review",
                "g1_review_packet": "02_mapping",
                "g2_review_packet": "04_reconciliation",
            }
            for stage_id, directory in expected_packet_dirs.items():
                packet_output = next(item for item in stages[stage_id]["outputs"] if item["artifact_id"] == stage_id)
                validation_output = next(item for item in stages[stage_id]["outputs"] if item["artifact_id"] == stage_id + "_validation")
                self.assertTrue(packet_output["path"].startswith(directory + "/"))
                self.assertTrue(validation_output["path"].startswith(directory + "/"))
            self.assertEqual(
                stages["human_review_and_promotion"]["outputs"][0]["artifact_id"],
                "reviewed_findings",
            )
            for stage_id in ("g0_review_packet", "g1_review_packet", "g2_review_packet"):
                output_ids = {item["artifact_id"] for item in stages[stage_id]["outputs"]}
                self.assertIn(stage_id + "_validation", output_ids)
            promotion_outputs = {item["artifact_id"] for item in stages["human_review_and_promotion"]["outputs"]}
            self.assertIn("reviewed_findings_validation", promotion_outputs)
            self.assertTrue(
                set(stages["independent_result_review"]["inputs"]).issubset(
                    set(stages["human_review_and_promotion"]["inputs"])
                )
            )
            source_artifact_ids = {item["artifact_id"] for item in plan["source_artifacts"]}
            self.assertIn("publication_plan_template", source_artifact_ids)
            self.assertNotIn("publication_plan", source_artifact_ids)
            preparation = stages["publication_plan_preparation"]
            self.assertEqual(preparation["executor"], "manual")
            self.assertEqual(preparation["required_gate"], "G3")
            self.assertIn("publication_plan_template", preparation["inputs"])
            self.assertTrue({
                "publication_plan", "publication_plan_validation",
            } == {item["artifact_id"] for item in preparation["outputs"]})
            publication = stages["publication_package_assembly"]
            self.assertEqual(publication["required_gate"], "G4")
            self.assertTrue({
                "publication_plan", "publication_plan_validation",
                "worker_review_output", "reviewed_findings",
                "reviewed_findings_validation", "cohort_review_record",
                "cohort_review_validation",
            }.issubset(set(publication["inputs"])))
            self.assertIn("publication_plan_preparation", publication["depends_on"])
            self.assertIn("independent_result_review", publication["depends_on"])

    def test_all_four_run_plans_bind_a_late_publication_plan_stage(self):
        cases = (
            ("templates/run_plan.example.json", "STRUCTURED_DATASET", "FULL_ANALYSIS"),
            ("templates/run_plan.canonical_adapter.example.json", "CANONICAL_BUNDLE", "FULL_ANALYSIS"),
            ("templates/run_plan.single_study.example.json", "STRUCTURED_DATASET", "CONTROLLED_SINGLE_STUDY"),
            ("templates/run_plan.canonical_adapter.single_study.example.json", "CANONICAL_BUNDLE", "CONTROLLED_SINGLE_STUDY"),
        )
        for path, route, profile in cases:
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            with self.subTest(path=path):
                publication_template = next(
                    item for item in plan["source_artifacts"]
                    if item["artifact_id"] == "publication_plan_template"
                )
                self.assertTrue(
                    Path(publication_template["path"]).is_absolute()
                    or PureWindowsPath(publication_template["path"]).is_absolute()
                )
                preparation = stages["publication_plan_preparation"]
                assembly = stages["publication_package_assembly"]
                self.assertEqual(preparation["executor"], "manual")
                self.assertEqual(preparation["required_gate"], "G3")
                self.assertIn("publication_plan_template", preparation["inputs"])
                self.assertEqual(
                    {item["artifact_id"] for item in preparation["outputs"]},
                    {"publication_plan", "publication_plan_validation"},
                )
                self.assertIn("publication_plan_preparation", assembly["depends_on"])
                self.assertEqual(assembly["required_gate"], "G4")
                self.assertTrue({
                    "publication_plan", "publication_plan_validation",
                }.issubset(set(assembly["inputs"])))
                if profile == "FULL_ANALYSIS":
                    self.assertTrue({
                        "cohort_review_record", "cohort_review_validation",
                    }.issubset(set(preparation["inputs"])))
                else:
                    lineage_inputs = {
                        "adapter_handoff", "dataset_manifest", "source_inventory",
                        "mapping_plan", "mapping_validation", "build_spec",
                        "build_spec_validation", "reconciliation_decision_validation",
                        "discovery_report", "g2_review_packet",
                    }
                    self.assertTrue(lineage_inputs.issubset(set(preparation["inputs"])))
                    self.assertTrue(lineage_inputs.issubset(set(assembly["inputs"])))
                    producers = {
                        output["artifact_id"]: stage["stage_id"]
                        for stage in plan["stages"]
                        for output in stage["outputs"]
                    }
                    for consumer in (preparation, assembly):
                        for artifact_id in lineage_inputs:
                            self.assertIn(producers[artifact_id], consumer["depends_on"])

    def test_both_run_plans_require_cohort_review_before_modelling(self):
        consumer_ids = {
            "baseline_model_fit", "nested_reproducibility_evaluation",
            "interaction_discovery", "interaction_robustness",
            "response_surface_generation", "mechanism_evidence_bridge",
            "independent_result_review", "human_review_and_promotion",
            "publication_package_assembly",
        }
        for path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
        ):
            plan = self._load_plan(path)
            stages = {item["stage_id"]: item for item in plan["stages"]}
            producers = {
                output["artifact_id"]: stage["stage_id"]
                for stage in plan["stages"]
                for output in stage["outputs"]
            }
            with self.subTest(path=path):
                review = stages["cohort_review"]
                self.assertEqual(review["executor"], "manual")
                self.assertIsNone(review["required_gate"])
                self.assertIn("cohort_build", review["depends_on"])
                self.assertEqual(
                    {item["artifact_id"] for item in review["outputs"]},
                    {"cohort_review_record", "cohort_review_validation"},
                )
                for stage_id in consumer_ids:
                    stage = stages[stage_id]
                    self.assertIn("cohort_review", stage["depends_on"])
                    self.assertIn("cohort_review_record", stage["inputs"])
                    self.assertIn("cohort_review_validation", stage["inputs"])
                for stage_id in (
                    "independent_result_review",
                    "human_review_and_promotion",
                    "publication_plan_preparation",
                    "publication_package_assembly",
                ):
                    self.assertIn("model_artifact", stages[stage_id]["inputs"])
                self.assertIn("serialized model artifact", stages["independent_result_review"]["worker_task"]["objective"].lower())
                for stage in plan["stages"]:
                    for artifact_id in stage["inputs"]:
                        producer = producers.get(artifact_id)
                        if producer is not None:
                            self.assertIn(producer, stage["depends_on"])

        review_schema = json.loads(
            (ROOT / "schemas" / "cohort_review_record.schema.json").read_text(encoding="utf-8")
        )
        review_example = json.loads(
            (ROOT / "templates" / "cohort_review_record.example.json").read_text(encoding="utf-8")
        )
        self.assertIn("artifact_sha256", review_schema["required"])
        self.assertEqual(review_example["schema_version"], "1.0")
        self.assertEqual(review_example["decision"], "REVISE")

    def test_run_plan_schema_declares_activation_operators(self):
        schema = json.loads(
            (ROOT / "schemas" / "run_plan.schema.json").read_text(encoding="utf-8")
        )
        stage = schema["properties"]["stages"]["items"]
        activation = stage["properties"]["activation"]
        self.assertIn("array_non_empty", activation["properties"]["operator"]["enum"])
        self.assertIn("equals", activation["properties"]["operator"]["enum"])
        self.assertEqual(
            schema["properties"]["execution_profile"]["enum"],
            ["FULL_ANALYSIS", "CONTROLLED_SINGLE_STUDY"],
        )
        for relative_path in (
            "templates/run_plan.single_study.example.json",
            "templates/run_plan.canonical_adapter.single_study.example.json",
        ):
            plan = self._load_plan(relative_path)
            self.assertEqual(plan["execution_profile"], "CONTROLLED_SINGLE_STUDY")
            self.assertIn(plan["execution_profile"], schema["properties"]["execution_profile"]["enum"])



if __name__ == "__main__":
    unittest.main()
