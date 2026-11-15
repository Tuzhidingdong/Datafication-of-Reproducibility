from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path

from dor.cli import build_parser
from dor.execution_contract import validate_supported_run_plan_execution_contract


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
        self.assertIn("stage_execution_contract.json", pyproject)


if __name__ == "__main__":
    unittest.main()
