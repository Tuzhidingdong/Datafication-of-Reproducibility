from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dor.cohort import build_modeling_cohort_files
from dor.interactions import discover_interactions_files
from dor.mechanism_bridge import build_mechanism_evidence_bridge_files
from dor.response_surface import generate_interaction_surface_files
from dor.robustness import assess_interaction_robustness_files
from test_interactions import interaction_bundle, interaction_task


def _evidence_record(evidence_id, study_id, evidence_type="direct_quote",
                     extraction_status="VERIFIED", page="p.4", quote="source statement"):
    return {
        "evidence_id": evidence_id,
        "study_id": study_id,
        "source_locator": {
            "source_file": "paper_" + study_id + ".pdf",
            "source_sha256": "a" * 64,
            "locator_type": "pdf_page",
            "locator": page
        },
        "evidence_type": evidence_type,
        "quoted_text": quote,
        "extraction_status": extraction_status
    }


def mechanism_bundle():
    data = interaction_bundle()
    observation_index = {row["observation_id"]: row for row in data["observations"]}
    evidence = [
        _evidence_record("EV_DIRECT", "ST1", quote="A direct measured process observable changed."),
        _evidence_record("EV_CONTRA", "ST2", quote="The predicted process change was not observed."),
        _evidence_record("EV_THEORY", "ST3", evidence_type="method_description",
                         quote="A theoretical calculation supports the proposed intermediate."),
        _evidence_record("EV_PENDING", "ST4", extraction_status="REVIEW_REQUIRED",
                         quote="This extraction has not been independently verified.")
    ]
    for evidence_id, observation_id in [
        ("EV_DIRECT", "IO_1_1"),
        ("EV_CONTRA", "IO_2_1"),
        ("EV_PENDING", "IO_4_1")
    ]:
        observation_index[observation_id]["evidence_ids"].append(evidence_id)
    data["evidence"].extend(evidence)

    data["studies"].append({
        "study_id": "ST9", "doi": "10.3000/prospective", "title": "Independent prospective probe",
        "year": 2026, "source_locators": []
    })
    data["systems"].append({"system_id": "SY9", "study_ids": ["ST9"], "system_type": "mechanism_probe"})
    data["experiments"].append({
        "experiment_id": "EX_PROS", "study_id": "ST9", "system_id": "SY9", "condition_ids": []
    })
    data["observations"].append({
        "observation_id": "OBS_PROS", "experiment_id": "EX_PROS", "target_id": "TARGET_MECHANISM_PROBE",
        "raw_value": 1.0, "raw_unit": "a.u.", "normalized_value": 1.0,
        "normalized_unit": "a.u.", "value_state": "REPORTED",
        "endpoint_definition": "independent mechanism probe", "evidence_ids": ["EV_PROS"]
    })
    data["evidence"].append(_evidence_record(
        "EV_PROS", "ST9", evidence_type="table_value", quote="An independent probe confirmed the predicted process."
    ))
    return data


def mechanism_plan(interaction_id):
    return {
        "schema_version": "1.0",
        "plan_id": "PLAN_MECH_1",
        "task_id": "TASK_INTERACTION",
        "target_id": "TARGET_Y",
        "endpoint_definition": "exact endpoint A",
        "interaction_id": interaction_id,
        "prepared_by": "researcher",
        "proposal_origin": "USER_DRAFT",
        "notes": "Draft for Gate G3 review.",
        "mechanism_hypotheses": [{
            "hypothesis_id": "HYP_1",
            "title": "Coordination-mediated interfacial response",
            "hypothesis_statement": "the first condition changes local coordination and thereby modifies the response to the second condition",
            "proposed_process_chain": [
                "the first condition changes the coordination environment",
                "the coordination environment changes an interfacial process",
                "the altered process modifies the measured endpoint"
            ],
            "scope_statement": "Only within the materials, endpoint definition, and condition ranges represented by the linked sources.",
            "predicted_observations": ["a measurable coordination change", "a corresponding change in the interfacial process"],
            "alternative_explanations": ["study-level protocol differences", "an unmeasured co-varying condition"],
            "unresolved_variables": ["local pH", "realized rather than nominal condition state"],
            "evidence_assessments": [
                {"evidence_id": "EV_DIRECT", "relationship": "SUPPORTS",
                 "evidence_class": "DIRECT_OBSERVATION",
                 "interpretation_summary": "A direct process measurement changes with the relevant condition.",
                 "observation_ids": ["IO_1_1"]},
                {"evidence_id": "EV_CONTRA", "relationship": "CONTRADICTS",
                 "evidence_class": "DIRECT_OBSERVATION",
                 "interpretation_summary": "A measured Study does not show the predicted process change.",
                 "observation_ids": ["IO_2_1"]},
                {"evidence_id": "EV_THEORY", "relationship": "SUPPORTS",
                 "evidence_class": "THEORETICAL_SUPPORT",
                 "interpretation_summary": "A calculation supports the proposed intermediate process."},
                {"evidence_id": "EV_PROS", "relationship": "SUPPORTS",
                 "evidence_class": "PROSPECTIVE_VALIDATION",
                 "interpretation_summary": "An independent Study tests and supports the predicted process.",
                 "observation_ids": ["OBS_PROS"]},
                {"evidence_id": "EV_PENDING", "relationship": "SUPPORTS",
                 "evidence_class": "DIRECT_OBSERVATION",
                 "interpretation_summary": "A potentially relevant measured process observation awaits extraction verification.",
                 "observation_ids": ["IO_4_1"]}
            ]
        }]
    }


class MechanismEvidenceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle_path = self.root / "canonical_bundle.json"
        self.task_path = self.root / "modeling_task.json"
        self.cohort_dir = self.root / "cohort"
        self.interaction_dir = self.root / "interactions"
        self.bundle_path.write_text(json.dumps(mechanism_bundle()), encoding="utf-8")
        task = interaction_task()
        task["task_id"] = "TASK_INTERACTION"
        self.task_path.write_text(json.dumps(task), encoding="utf-8")
        built = build_modeling_cohort_files(self.bundle_path, self.task_path, self.cohort_dir)
        self.assertTrue(built["valid"], built)
        discovered = discover_interactions_files(self.cohort_dir, self.task_path,
                                                  self.interaction_dir, folds=4, seed=19)
        self.assertEqual(discovered["report"]["eligible_pair_count"], 1)
        self.interaction_id = discovered["report"]["interaction_catalogue"][0]["interaction_id"]
        self.plan_path = self.root / "mechanism_plan.json"
        self.plan_path.write_text(json.dumps(mechanism_plan(self.interaction_id)), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _build(self, name="bridge", **kwargs):
        return build_mechanism_evidence_bridge_files(
            self.bundle_path, self.cohort_dir, self.task_path, self.interaction_dir,
            self.plan_path, self.root / name, **kwargs
        )

    def test_verified_support_contradiction_theory_and_prospective_evidence_are_linked(self):
        result = self._build()
        report = result["report"]
        mechanism = report["mechanism_catalogue"][0]
        self.assertEqual(mechanism["evidence_status"], "SUPPORT_AND_CONTRADICTION_RECORDED")
        self.assertEqual(mechanism["evidence_counts"]["direct_observation_support"], 1)
        self.assertEqual(mechanism["evidence_counts"]["theoretical_support"], 1)
        self.assertEqual(mechanism["evidence_counts"]["independent_prospective_support"], 1)
        self.assertIn("EV_CONTRA", mechanism["contradicting_evidence_ids"])
        self.assertEqual(mechanism["review_state"], "PENDING_G3_USER_REVIEW")
        self.assertEqual(report["review_state"], "PENDING_G3_USER_REVIEW")
        self.assertGreaterEqual(report["review_issue_count"], 1)
        self.assertEqual(mechanism["evidence_counts"]["pending_source_verification"], 1)
        self.assertTrue((self.root / "bridge" / "mechanism_evidence_ledger.csv").is_file())
        self.assertTrue((self.root / "bridge" / "mechanism_review_queue.csv").is_file())
        self.assertTrue((self.root / "bridge" / "mechanism_evidence_bridge_manifest.json").is_file())

    def test_finding_is_never_promoted_to_established_mechanism(self):
        findings = self._build()["findings"]["findings"]
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["claim_type"], "mechanism_hypothesis")
        self.assertEqual(finding["status"], "candidate")
        self.assertEqual(finding["mechanism_status"], "hypothesis")
        self.assertIn("remains a mechanism hypothesis", finding["manuscript_wording"])

    def test_unverified_evidence_is_not_counted_as_support(self):
        plan = mechanism_plan(self.interaction_id)
        plan["mechanism_hypotheses"][0]["evidence_assessments"] = [
            item for item in plan["mechanism_hypotheses"][0]["evidence_assessments"]
            if item["evidence_id"] == "EV_PENDING"
        ]
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        mechanism = self._build("pending_only")["report"]["mechanism_catalogue"][0]
        self.assertEqual(mechanism["evidence_status"], "EVIDENCE_REVIEW_REQUIRED")
        self.assertEqual(mechanism["evidence_counts"]["supporting_verified_evidence"], 0)
        self.assertEqual(mechanism["evidence_counts"]["pending_source_verification"], 1)

    def test_prospective_label_is_not_counted_when_source_study_overlaps_discovery(self):
        plan = mechanism_plan(self.interaction_id)
        assessment = next(item for item in plan["mechanism_hypotheses"][0]["evidence_assessments"]
                          if item["evidence_id"] == "EV_DIRECT")
        assessment["evidence_class"] = "PROSPECTIVE_VALIDATION"
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result = self._build("not_independent")
        mechanism = result["report"]["mechanism_catalogue"][0]
        self.assertEqual(mechanism["evidence_counts"]["independent_prospective_support"], 1)
        self.assertTrue(any(item["issue_code"] == "PROSPECTIVE_EVIDENCE_NOT_INDEPENDENT"
                            for item in result["report"]["review_queue"]))

    def test_direct_observation_requires_an_exact_canonical_observation_link(self):
        plan = mechanism_plan(self.interaction_id)
        assessment = plan["mechanism_hypotheses"][0]["evidence_assessments"][0]
        assessment["observation_ids"] = []
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must provide observation_ids"):
            self._build("missing_obs")

    def test_unknown_evidence_reference_is_rejected(self):
        plan = mechanism_plan(self.interaction_id)
        plan["mechanism_hypotheses"][0]["evidence_assessments"][0]["evidence_id"] = "EV_MISSING"
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown canonical Evidence ID"):
            self._build("unknown_evidence")

    def test_stale_interaction_report_hash_is_rejected(self):
        report_path = self.interaction_dir / "interaction_discovery_report.json"
        report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash does not match its manifest"):
            self._build("stale_report")

    def test_canonical_bundle_must_match_cohort_provenance(self):
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        bundle["studies"][0]["title"] = "modified after cohort construction"
        self.bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bundle hash does not match"):
            self._build("bundle_mismatch")

    def test_optional_robustness_and_surface_packages_are_hash_checked_and_linked(self):
        robustness_dir = self.root / "robustness"
        assess_interaction_robustness_files(self.cohort_dir, self.task_path,
            robustness_dir, seeds=[11, 23, 42], folds=4)
        surface_dir = self.root / "surface"
        generate_interaction_surface_files(self.cohort_dir, self.task_path,
            self.interaction_dir, self.interaction_id, surface_dir)
        result = self._build("with_optional", robustness_dir=robustness_dir,
                             response_surface_dir=surface_dir)
        self.assertEqual(result["report"]["robustness_status"], "SEED_STABLE_PREDICTIVE_INTERACTION_CANDIDATE")
        self.assertEqual(result["report"]["response_surface_scope"],
                         "DESCRIPTIVE_RESPONSE_SURFACE_NOT_INDEPENDENT_VALIDATION_OR_CAUSAL_INFERENCE")

    def test_all_inputs_remain_unchanged(self):
        paths = [
            self.bundle_path, self.task_path, self.plan_path,
            self.cohort_dir / "modeling_cohort.csv",
            self.cohort_dir / "cohort_report.json",
            self.cohort_dir / "split_manifest.json",
            self.cohort_dir / "modeling_cohort_manifest.json",
            self.interaction_dir / "interaction_discovery_report.json",
            self.interaction_dir / "interaction_discovery_manifest.json"
        ]
        before = {path: path.read_bytes() for path in paths}
        self._build("readonly")
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_nonempty_output_directory_is_not_overwritten(self):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "preserve.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self._build("existing")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
