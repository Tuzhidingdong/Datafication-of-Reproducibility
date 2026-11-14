import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPTIONAL_STAGE_IDS = {
    "mechanism_plan_preparation",
    "response_surface_generation",
    "mechanism_evidence_bridge",
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

    def test_core_skill_and_adapter_contract_preserve_cross_disciplinary_boundary(self):
        skill = (ROOT / ".agents" / "skills" / "datafication-of-reproducibility" / "SKILL.md").read_text(encoding="utf-8")
        adapter_contract = (ROOT / "docs" / "ADAPTER_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("Cross-disciplinary boundary (immutable)", skill)
        self.assertIn("hard architectural boundary", adapter_contract)
        self.assertIn("independently maintained external adapters", adapter_contract)

    def test_run_plan_schema_declares_activation_operators(self):
        schema = json.loads(
            (ROOT / "schemas" / "run_plan.schema.json").read_text(encoding="utf-8")
        )
        stage = schema["properties"]["stages"]["items"]
        activation = stage["properties"]["activation"]
        self.assertIn("array_non_empty", activation["properties"]["operator"]["enum"])
        self.assertIn("equals", activation["properties"]["operator"]["enum"])


if __name__ == "__main__":
    unittest.main()
