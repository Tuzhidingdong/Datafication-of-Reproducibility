from __future__ import annotations

import argparse
import json
import unittest
import tempfile
from pathlib import Path

from dor.cli import build_parser
from dor.execution_contract import (validate_supported_run_plan_execution_contract, inspect_supported_run_plan_execution_contract, stage_action_bindings_for_plan)
from dor.run_manager import build_resume_plan, initialize_run


ROOT = Path(__file__).resolve().parents[2]


class StageExecutionContractTests(unittest.TestCase):
    def _load_plan(self, path: str):
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_both_supported_routes_match_the_bundled_execution_contract(self):
        for path in (
            "templates/run_plan.example.json",
            "templates/run_plan.canonical_adapter.example.json",
        ):
            with self.subTest(path=path):
                plan = self._load_plan(path)
                validate_supported_run_plan_execution_contract(plan)

    def test_formal_run_resume_plan_exposes_exact_route_action_and_paths(self):
        cases = (
            ("templates/run_plan.example.json", "STRUCTURED_DATASET", "FULL_ANALYSIS"),
            ("templates/run_plan.canonical_adapter.example.json", "CANONICAL_BUNDLE", "FULL_ANALYSIS"),
            ("templates/run_plan.single_study.example.json", "STRUCTURED_DATASET", "CONTROLLED_SINGLE_STUDY"),
            ("templates/run_plan.canonical_adapter.single_study.example.json", "CANONICAL_BUNDLE", "CONTROLLED_SINGLE_STUDY"),
        )
        for index, (relative_path, expected_route, expected_profile) in enumerate(cases):
            with self.subTest(path=relative_path):
                with tempfile.TemporaryDirectory(prefix="dor-formal-run-plan-") as temporary:
                    root = Path(temporary)
                    package_root = root / "adapter_package"
                    config_root = root / "configuration"
                    package_root.mkdir()
                    config_root.mkdir()
                    adapter_manifest = package_root / "adapter_manifest.json"
                    publication_plan_template = config_root / "publication_package_plan.json"
                    for path in (adapter_manifest, publication_plan_template):
                        path.write_text("{}\n", encoding="utf-8")

                    plan = self._load_plan(relative_path)
                    plan["source_roots"] = [str(package_root), str(config_root)]
                    plan["workflow_ledger_path"] = str(root / "workflow_gate_ledger.jsonl")
                    source_paths = {
                        "adapter_package_manifest": adapter_manifest,
                        "publication_plan_template": publication_plan_template,
                    }
                    for artifact in plan["source_artifacts"]:
                        artifact["path"] = str(source_paths[artifact["artifact_id"]])
                    plan_path = root / "configured_run_plan.json"
                    plan_path.write_text(
                        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
                    )
                    run_root = root / "runs" / f"RUN_FORMAL_ROUTE_{index}"
                    initialized = initialize_run(
                        plan_path, run_root, f"RUN_FORMAL_ROUTE_{index}"
                    )
                    self.assertEqual(initialized["status"], "initialized")

                    resume = build_resume_plan(run_root / "run_manifest.json")
                    self.assertEqual(resume["next_actions"][0]["stage_id"], "adapter_package_validation")
                    first_action = resume["next_actions"][0]
                    self.assertEqual(first_action["action_binding"]["route"], expected_route)
                    self.assertEqual(first_action["action_binding"]["execution_profile"], expected_profile)
                    self.assertEqual(first_action["action"], "READY_TO_RUN")
                    self.assertEqual(first_action["action_binding"]["runtime_command"], "prepare-adapter-handoff")
                    self.assertEqual(
                        first_action["action_binding"]["argv_template"][:2],
                        ["--manifest", {"artifact": "adapter_package_manifest"}],
                    )
                    self.assertEqual(
                        first_action["action_binding"]["input_artifacts"][0]["path"],
                        str(adapter_manifest.resolve()),
                    )
                    self.assertTrue(
                        first_action["action_binding"]["output_artifacts"][0]["path"].startswith(
                            str(run_root.resolve())
                        )
                    )

                    worker_stage = next(
                        stage for stage in resume["stages"]
                        if stage["stage_id"] == "independent_result_review"
                    )
                    worker_binding = worker_stage["action_binding"]
                    self.assertEqual(worker_binding["action_type"], "WORKER")
                    self.assertEqual(worker_binding["authorization_command"], "run-worker-authorize")
                    self.assertEqual(worker_binding["host_action"], "dispatch-authorized-worker-packet")
                    self.assertIn("objective", worker_binding["worker_task"])
                    self.assertIn("permitted_actions", worker_binding["worker_task"])

    def test_controlled_single_study_profiles_bind_both_adapter_routes(self):
        cases = (
            ("templates/run_plan.single_study.example.json", "STRUCTURED_DATASET"),
            ("templates/run_plan.canonical_adapter.single_study.example.json", "CANONICAL_BUNDLE"),
        )
        for relative_path, expected_route in cases:
            with self.subTest(path=relative_path):
                plan = self._load_plan(relative_path)
                self.assertEqual(plan["execution_profile"], "CONTROLLED_SINGLE_STUDY")
                report = inspect_supported_run_plan_execution_contract(plan)
                self.assertTrue(report["valid"])
                self.assertEqual(report["route"], expected_route)
                self.assertEqual(report["execution_profile"], "CONTROLLED_SINGLE_STUDY")
                self.assertEqual(report["stage_count"], len(plan["stages"]))
                bindings = stage_action_bindings_for_plan(plan)
                self.assertEqual(set(bindings), {stage["stage_id"] for stage in plan["stages"]})
                self.assertEqual(
                    bindings["single_study_na_artifacts"]["runtime_command"],
                    "prepare-single-study-not-applicable-artifacts",
                )
                self.assertEqual(
                    bindings["single_study_scope_validation"]["runtime_command"],
                    "validate-single-study-applicability",
                )
                self.assertEqual(bindings["independent_result_review"]["executor"], "worker")
                self.assertTrue(bindings["single_study_na_artifacts"]["argv_template"])
                self.assertEqual(
                    bindings["single_study_na_artifacts"]["argv_template"][0:2],
                    ["--record", {"artifact": "single_study_applicability_record"}],
                )

    def test_controlled_single_study_profile_rejects_omitted_na_stage(self):
        plan = self._load_plan("templates/run_plan.single_study.example.json")
        plan["stages"] = [
            stage for stage in plan["stages"]
            if stage["stage_id"] != "single_study_na_artifacts"
        ]
        with self.assertRaisesRegex(ValueError, "stage set differs"):
            validate_supported_run_plan_execution_contract(plan)

    def test_controlled_single_study_worker_packet_reviews_scope_not_fake_results(self):
        for relative_path in (
            "templates/run_plan.single_study.example.json",
            "templates/run_plan.canonical_adapter.single_study.example.json",
        ):
            plan = self._load_plan(relative_path)
            stage = next(item for item in plan["stages"] if item["stage_id"] == "independent_result_review")
            objective = stage["worker_task"]["objective"].lower()
            self.assertIn("not_applicable", objective)
            self.assertIn("not fabricate", objective)
            self.assertNotIn("fit models", objective)

    def test_publication_plan_preparation_and_g4_build_use_the_bound_validation(self):
        cases = (
            ("templates/run_plan.example.json", "STRUCTURED_DATASET", None),
            ("templates/run_plan.canonical_adapter.example.json", "CANONICAL_BUNDLE", None),
            ("templates/run_plan.single_study.example.json", "STRUCTURED_DATASET", "CONTROLLED_SINGLE_STUDY"),
            ("templates/run_plan.canonical_adapter.single_study.example.json", "CANONICAL_BUNDLE", "CONTROLLED_SINGLE_STUDY"),
        )
        for relative_path, expected_route, expected_profile in cases:
            plan = self._load_plan(relative_path)
            bindings = stage_action_bindings_for_plan(plan)
            with self.subTest(path=relative_path):
                preparation = bindings["publication_plan_preparation"]
                preparation_stage = next(
                    item for item in plan["stages"]
                    if item["stage_id"] == "publication_plan_preparation"
                )
                assembly = bindings["publication_package_assembly"]
                self.assertEqual(preparation["route"], expected_route)
                self.assertEqual(preparation["execution_profile"], expected_profile or "FULL_ANALYSIS")
                self.assertEqual(preparation["executor"], "manual")
                self.assertEqual(preparation["validator_command"], "validate-publication-plan")
                self.assertEqual(assembly["executor"], "local")
                self.assertEqual(assembly["runtime_command"], "build-publication-package")
                self.assertIn(
                    ["--validation", {"artifact": "publication_plan_validation"}],
                    [
                        assembly["argv_template"][index:index + 2]
                        for index in range(len(assembly["argv_template"]) - 1)
                    ],
                )
                self.assertIn("publication_plan_template", {
                    item["artifact_id"] for item in plan["source_artifacts"]
                })
                if expected_profile is None:
                    self.assertTrue({
                        "mechanism_plan_preparation", "response_surface_generation",
                        "mechanism_evidence_bridge",
                    }.issubset(set(preparation_stage["depends_on"])))
                    self.assertFalse({
                        "mechanism_plan", "interaction_response_surface_report",
                        "interaction_response_surface_manifest",
                        "mechanism_evidence_bridge_report",
                    }.intersection(set(preparation_stage["inputs"])))

        parser = build_parser()
        validation_args = parser.parse_args([
            "validate-publication-plan", "--plan", "final_plan.json",
            "--manifest", "run_manifest.json", "--out", "validation.json",
        ])
        self.assertEqual(validation_args.command, "validate-publication-plan")
        build_args = parser.parse_args([
            "build-publication-package", "--plan", "final_plan.json",
            "--validation", "validation.json",
            "--workspace-root", "run_root", "--out-dir", "package",
            "--workflow-ledger", "workflow_gate_ledger.jsonl",
        ])
        self.assertEqual(build_args.validation, Path("validation.json"))

    def test_contract_cli_and_validator_actions_exist_in_runtime_parser(self):
        contract = json.loads(
            (ROOT / "runtime" / "src" / "dor" / "stage_execution_contract.json").read_text(encoding="utf-8")
        )
        parser = build_parser()
        subparser_action = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        commands = set(subparser_action.choices)
        for binding in contract["stages"]:
            for field in ("cli_command", "validator_command", "authorization_command"):
                command = binding.get(field)
                if command:
                    self.assertIn(command, commands, f"{binding['stage_id']} references missing CLI command {command}")

    def test_cli_exposes_contract_preflight(self):
        args = build_parser().parse_args([
            "validate-execution-contract", "--plan", "run_plan.json",
        ])
        self.assertEqual(args.command, "validate-execution-contract")
        self.assertEqual(args.plan, Path("run_plan.json"))

    def test_action_binding_rejects_dependency_graph_drift(self):
        plan = self._load_plan("templates/run_plan.example.json")
        stage = next(item for item in plan["stages"] if item["stage_id"] == "cohort_review")
        stage["depends_on"].remove("research_scope_selection")
        with self.assertRaisesRegex(ValueError, "dependencies differ"):
            validate_supported_run_plan_execution_contract(plan)

    def test_action_binding_rejects_an_input_artifact_drift(self):
        plan = self._load_plan("templates/run_plan.example.json")
        baseline = next(stage for stage in plan["stages"] if stage["stage_id"] == "baseline_model_fit")
        baseline["inputs"].append("unbound_extra_input")
        with self.assertRaisesRegex(ValueError, "input Artifact IDs"):
            validate_supported_run_plan_execution_contract(plan)

    def test_action_binding_rejects_executor_and_command_contract_drift(self):
        plan = self._load_plan("templates/run_plan.example.json")
        stage = next(item for item in plan["stages"] if item["stage_id"] == "independent_result_review")
        stage["executor"] = "local"
        with self.assertRaisesRegex(ValueError, "executor drift"):
            validate_supported_run_plan_execution_contract(plan)

    def test_execution_contract_schema_and_package_data_are_declared(self):
        schema = json.loads(
            (ROOT / "schemas" / "stage_execution_contract.schema.json").read_text(encoding="utf-8")
        )
        contract = json.loads(
            (ROOT / "runtime" / "src" / "dor" / "stage_execution_contract.json").read_text(encoding="utf-8")
        )
        pyproject = (ROOT / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(contract["schema_version"], "1.0")
        self.assertIn("routes", schema["required"])
        self.assertIn("profiles", schema["required"])
        self.assertIn("CONTROLLED_SINGLE_STUDY", contract["profiles"])
        self.assertIn("stage_execution_contract.json", pyproject)
        worker_packet_schema = json.loads(
            (ROOT / "schemas" / "run_worker_task_packet.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("authorization_event_hash", worker_packet_schema["required"])
        self.assertIn("task_id", worker_packet_schema["required"])


if __name__ == "__main__":
    unittest.main()
