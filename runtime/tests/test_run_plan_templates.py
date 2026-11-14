import json
import unittest
from pathlib import Path


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
