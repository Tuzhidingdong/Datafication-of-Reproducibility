import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dor.publication import audit_publication_package_files
from dor.stage_contracts import CONTRACT_VERSION, STAGE_CONTRACTS, validate_stage_payload, validate_stage_evidence


class StageEvidenceContractTests(unittest.TestCase):
    def test_registry_covers_fixed_eight_stage_protocol_in_order(self):
        self.assertEqual(CONTRACT_VERSION, "1.0")
        self.assertEqual(tuple(STAGE_CONTRACTS), (
            "source_selection", "source_integrity", "extraction_review", "semantic_mapping",
            "canonical_reconciliation", "cohort_feasibility", "modeling_validation", "publication_handoff",
        ))

    def test_each_stage_has_nonempty_fixed_artifact_types_and_checks(self):
        for stage_id, contract in STAGE_CONTRACTS.items():
            with self.subTest(stage=stage_id):
                self.assertTrue(contract["required_artifact_types"])
                self.assertTrue(contract["checks"])

    def test_source_selection_allows_explicit_exclusion_as_snapshot_partition(self):
        snapshot = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": "/data/paper.pdf", "sha256": "a" * 64},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": "/data/paper_si.pdf", "sha256": "b" * 64},
        ]
        payload = {
            "schema_version": "1.0", "selection_rationale": "Selected the primary article for this scope.",
            "scope_statement": "One-study extraction pilot.", "study_ids": ["S1"],
            "selected_sources": [{
                "source_id": "paper", "role": "PRIMARY_PAPER",
                "path": "/data/paper.pdf", "sha256": "a" * 64,
            }],
            "excluded_sources": [{
                "source_id": "si", "role": "SUPPLEMENTARY_INFORMATION",
                "path": "/data/paper_si.pdf", "sha256": "b" * 64,
                "reason": "Supplementary file is outside this extraction scope.",
            }],
        }
        errors = validate_stage_payload(
            "source_selection_manifest", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=snapshot,
        )
        self.assertEqual([], errors)

    def test_source_selection_rejects_source_omitted_from_both_selected_and_excluded(self):
        snapshot = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": "/data/paper.pdf", "sha256": "a" * 64},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": "/data/paper_si.pdf", "sha256": "b" * 64},
        ]
        payload = {
            "schema_version": "1.0", "selection_rationale": "Selected the primary article.",
            "scope_statement": "Pilot.", "study_ids": ["S1"],
            "selected_sources": [{
                "source_id": "paper", "role": "PRIMARY_PAPER",
                "path": "/data/paper.pdf", "sha256": "a" * 64,
            }],
            "excluded_sources": [],
        }
        codes = {item["code"] for item in validate_stage_payload(
            "source_selection_manifest", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=snapshot,
        )}
        self.assertIn("SOURCE_SELECTION_PARTITION_MISMATCH", codes)

    def test_source_inventory_cannot_reference_an_explicitly_excluded_source(self):
        payload = {
            "schema_version": "1.0",
            "items": [{
                "inventory_id": "INV_1", "source_file": "paper_si.pdf",
                "source_sha256": "b" * 64, "source_format": "pdf",
                "locator_type": "pdf_page", "locator": "page 1",
                "mapping_status": "UNRESOLVED",
            }],
        }
        snapshot = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": "/data/paper.pdf", "sha256": "a" * 64},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": "/data/paper_si.pdf", "sha256": "b" * 64},
        ]
        codes = {item["code"] for item in validate_stage_payload(
            "source_inventory", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=snapshot, selected_source_ids={"paper"},
        )}
        self.assertIn("SOURCE_INVENTORY_SOURCE_NOT_SELECTED", codes)

    def test_source_inventory_requires_real_locator_and_sha_fields(self):
        bad = {"schema_version": "1.0", "items": [{"inventory_id": "I1", "source_file": "x.csv"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "source_inventory", bad, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("SOURCE_INVENTORY_ITEM_INCOMPLETE", codes)
        self.assertIn("SOURCE_INVENTORY_HASH_INVALID", codes)

    def test_mapping_plan_does_not_accept_unreviewed_proposed_rules(self):
        payload = {"schema_version": "1.0", "mapping_version": "M1", "source_inventory_sha256": "a" * 64,
                   "rules": [{"mapping_rule_id": "R1", "source_item_id": "I1", "status": "PROPOSED"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "mapping_plan", payload, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("MAPPING_RULE_UNREVIEWED", codes)

    def test_canonical_bundle_reuses_canonical_graph_validator(self):
        payload = {"schema_version": "1.0", "studies": [], "systems": [], "conditions": [],
                   "experiments": [], "observations": [], "comparisons": [], "evidence": []}
        codes = {item["code"] for item in validate_stage_payload(
            "canonical_bundle", payload, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertTrue({"CANONICAL_BUNDLE_INVALID", "CANONICAL_BUNDLE_METADATA_INVALID", "CANONICAL_BUILD_PROVENANCE_INVALID"} & codes)

    def test_reconciliation_report_must_bind_exact_bundle_hash(self):
        payload = {"schema_version": "1.0", "bundle_sha256": "b" * 64, "valid_bundle": True,
                   "issue_count": 0, "issues": []}
        codes = {item["code"] for item in validate_stage_payload(
            "reconciliation_report", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, canonical_sha256="a" * 64
        )}
        self.assertIn("RECONCILIATION_BUNDLE_HASH_MISMATCH", codes)

    def test_split_manifest_rejects_study_leakage(self):
        payload = {"schema_version": "1.0", "study_to_split": {"S1": "train", "S2": "train", "S3": "test"},
                   "leakage_check": {"valid": True, "study_overlap_count": 0}}
        codes = {item["code"] for item in validate_stage_payload(
            "split_manifest", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"}
        )}
        self.assertIn("STUDY_SPLIT_PARTITION_MISSING", codes)

    def test_model_manifest_rejects_overlapping_studies(self):
        payload = {"schema_version": "1.0", "input_hashes": {key: "a" * 64 for key in (
                       "cohort_sha256", "cohort_report_sha256", "split_manifest_sha256",
                       "cohort_manifest_sha256", "task_sha256")},
                   "output_hashes": {"model_report.json": "b" * 64},
                   "study_ids_by_split": {"train": ["S1"], "validation": ["S1"], "test": ["S3"]}}
        codes = {item["code"] for item in validate_stage_payload(
            "modeling_run_manifest", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"}
        )}
        self.assertIn("MODELING_STUDY_LEAKAGE", codes)

    def test_stage_evidence_rejects_missing_fixed_artifact_types(self):
        errors = validate_stage_evidence(
            "source_selection", [], run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=[],
        )
        codes = {item["code"] for item in errors}
        self.assertIn("STAGE_REQUIRED_EVIDENCE_TYPE_MISSING", codes)

    def test_source_selection_manifest_must_match_selected_source_snapshot(self):
        payload = {
            "schema_version": "1.0", "selection_rationale": "Selected by user.",
            "scope_statement": "One-study pilot.", "study_ids": ["S1"],
            "selected_sources": [{
                "source_id": "paper", "role": "PRIMARY_PAPER", "path": "/tmp/paper.pdf",
                "sha256": "a" * 64,
            }],
            "excluded_sources": [],
        }
        errors = validate_stage_payload(
            "source_selection_manifest", payload, run_id="R1", project_id="P1",
            study_ids={"S1"},
            source_snapshot=[{
                "source_id": "paper", "role": "PRIMARY_PAPER", "path": "/tmp/other.pdf",
                "sha256": "a" * 64,
            }],
        )
        self.assertIn("SOURCE_SELECTION_NOT_BOUND_TO_SNAPSHOT", {item["code"] for item in errors})

    def test_cohort_report_requires_explicit_eligible_study_ids(self):
        payload = {
            "valid": True, "task_id": "T1", "target_id": "Y", "endpoint_definition": "endpoint",
            "eligible_observation_count": 3, "eligible_study_count": 3,
            "split_counts": {},
        }
        errors = validate_stage_payload(
            "cohort_report", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2", "S3"},
        )
        self.assertIn("COHORT_REPORT_INVALID", {item["code"] for item in errors})

    def test_nested_evaluation_rejects_unhashable_per_study_ids_without_raising(self):
        study_ids = ["S1", "S2", "S3", "S4"]
        folds = []
        for index, held_out in enumerate(study_ids, start=1):
            outer = [sid for sid in study_ids if sid != held_out]
            folds.append({
                "fold": index, "test_study_ids": [held_out],
                "outer_training_study_ids": outer,
                "inner_training_study_ids": outer[1:],
                "inner_validation_study_ids": outer[:1],
                "selected_model": "Ridge", "inner_validation_comparison": [{}],
                "outer_test_metrics": {}, "outer_test_baseline_metrics": {},
            })
        payload = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "endpoint", "fold_count": 4, "study_count": 4,
            "observation_count": 4, "folds": folds,
            "per_study_performance": [{"study_id": ["not", "hashable"]}] + [
                {"study_id": sid} for sid in study_ids[1:]
            ],
            "uncertainty": {"status": "NOT_CALIBRATED"},
            "validation_scope": "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION",
        }
        errors = validate_stage_payload(
            "reproducibility_evaluation", payload, run_id="R1",
            project_id="P1", study_ids=set(study_ids),
        )
        self.assertIn("REPRODUCIBILITY_PER_STUDY_COVERAGE_MISMATCH", {item["code"] for item in errors})

    def test_model_artifact_accepts_explicit_feature_binding_objects(self):
        payload = {
            "schema_version": "1.0", "engine_version": "synthetic", "task_id": "T1",
            "model_type": "ridge_regression", "target_id": "Y",
            "endpoint_definition": "endpoint", "outcome_value_field": "raw_value",
            "outcome_unit": "mAh/g",
            "feature_bindings": [{
                "feature_id": "concentration", "condition_type": "concentration",
                "value_field": "raw_value", "value_type": "NUMERIC", "expected_unit": "mol/L",
            }],
            "selected_candidate_id": "ridge_1", "selection_metric": "validation_mae",
            "training_observation_ids": ["O1"], "training_study_ids": ["S1"],
            "test_observation_ids": ["O2"], "model_parameters": {"alpha": 1.0},
        }
        errors = validate_stage_payload(
            "model_artifact", payload, run_id="R1", project_id="P1", study_ids={"S1", "S2"},
        )
        codes = {item["code"] for item in errors}
        self.assertNotIn("MODEL_ARTIFACT_FEATURE_BINDINGS_INVALID", codes)

    def test_modeling_task_rejects_explicit_study_not_in_eligible_cohort(self):
        task = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "endpoint", "outcome_type": "NUMERIC",
            "outcome_value_field": "raw_value", "outcome_unit": "mAh/g",
            "feature_bindings": [{
                "feature_id": "concentration", "condition_type": "concentration",
                "value_field": "raw_value", "value_type": "NUMERIC", "expected_unit": "mol/L",
            }],
            "split": {
                "strategy": "EXPLICIT_STUDIES",
                "validation_study_ids": ["S2"], "test_study_ids": ["S3"],
            },
        }
        report = {"eligible_study_ids": ["S1", "S2"]}
        split = {"task_id": "T1", "strategy": "EXPLICIT_STUDIES",
                 "study_to_split": {"S1": "train", "S2": "validation"}}
        evidence = [
            {"artifact_id": "task", "artifact_type": "modeling_task", "payload": task, "sha256": "a" * 64},
            {"artifact_id": "report", "artifact_type": "cohort_report", "payload": report, "sha256": "b" * 64},
            {"artifact_id": "split", "artifact_type": "split_manifest", "payload": split, "sha256": "c" * 64},
            {"artifact_id": "manifest", "artifact_type": "modeling_cohort_manifest",
             "payload": {"schema_version": "1.0", "task_id": "T1",
                         "bundle_sha256": "d" * 64, "task_sha256": "a" * 64,
                         "eligible_observation_count": 2, "eligible_study_count": 2,
                         "artifact_sha256": {
                             "modeling_cohort.csv": "e" * 64,
                             "cohort_report.json": "b" * 64,
                             "split_manifest.json": "c" * 64}},
             "sha256": "f" * 64},
            {"artifact_id": "csv", "artifact_type": "modeling_cohort_csv", "payload": None, "sha256": "e" * 64},
        ]
        errors = validate_stage_evidence(
            "cohort_feasibility", evidence, run_id="R1", project_id="P1",
            study_ids={"S1", "S2"}, source_snapshot=[],
            prior_payloads={"canonical_bundle": {"payload": {
                "studies": [{"study_id": "S1"}, {"study_id": "S2"}]
            }, "sha256": "d" * 64}},
        )
        self.assertIn("COHORT_TASK_STUDY_NOT_ELIGIBLE", {item["code"] for item in errors})

    def test_publication_manifest_completeness_is_derived_from_artifact_states(self):
        payload = {
            "schema_version": "1.0", "project_id": "P1", "run_id": "R1",
            "package_version": "1.0", "source_hashes": {},
            "writing_guide": "README_FOR_WRITING_SKILL.md",
            "writing_guide_sha256": "a" * 64,
            "artifacts": [{
                "artifact_id": "FIGURE_1", "path": "figures/figure1.svg",
                "type": "figure", "description": "Figure not generated.",
                "status": "not_generated",
            }],
            "completeness": {"status": "complete", "unresolved_items": []},
        }
        codes = {item["code"] for item in validate_stage_payload(
            "publication_package_manifest", payload, run_id="R1",
            project_id="P1", study_ids={"S1"},
        )}
        self.assertIn("PUBLICATION_COMPLETENESS_DERIVATION_MISMATCH", codes)

    def test_publication_handoff_recomputes_package_integrity_from_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            package.mkdir()
            guide = package / "README_FOR_WRITING_SKILL.md"
            guide.write_text("# Synthetic writing guide\n", encoding="utf-8")
            result = package / "results" / "result.json"
            result.parent.mkdir()
            result.write_text('{"value": 1}\n', encoding="utf-8")

            def digest(path):
                return hashlib.sha256(path.read_bytes()).hexdigest()

            manifest = {
                "schema_version": "1.0", "project_id": "P1", "run_id": "R1",
                "package_version": "1.0", "source_hashes": {},
                "writing_guide": "README_FOR_WRITING_SKILL.md",
                "writing_guide_sha256": digest(guide),
                "artifacts": [{
                    "artifact_id": "RESULT_1", "path": "results/result.json",
                    "type": "result", "description": "Synthetic result",
                    "status": "complete", "sha256": digest(result),
                }],
                "completeness": {"status": "complete", "unresolved_items": []},
            }
            manifest_path = package / "package_manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            audit = audit_publication_package_files(package)
            audit_path = root / "publication_integrity_report.json"
            audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
            evidence = [
                {"artifact_id": "package_manifest", "artifact_type": "publication_package_manifest",
                 "path": str(manifest_path), "sha256": digest(manifest_path), "payload": manifest},
                {"artifact_id": "package_audit", "artifact_type": "publication_integrity_report",
                 "path": str(audit_path), "sha256": digest(audit_path), "payload": audit},
            ]
            errors = validate_stage_evidence(
                "publication_handoff", evidence, run_id="R1", project_id="P1",
                study_ids={"S1"}, source_snapshot=[],
            )
            self.assertEqual([], errors)

            # A stale report that still says valid=true cannot override a changed package file.
            result.write_text('{"value": 2}\n', encoding="utf-8")
            errors = validate_stage_evidence(
                "publication_handoff", evidence, run_id="R1", project_id="P1",
                study_ids={"S1"}, source_snapshot=[],
            )
            self.assertIn("PUBLICATION_PACKAGE_ACTUAL_AUDIT_FAILED", {item["code"] for item in errors})

    def test_nested_study_evaluation_rejects_fold_leakage(self):
        study_ids = ["S1", "S2", "S3", "S4"]
        folds = []
        for index, held_out in enumerate(study_ids, start=1):
            outer = [sid for sid in study_ids if sid != held_out]
            folds.append({
                "fold": index, "test_study_ids": [held_out],
                "outer_training_study_ids": outer,
                "inner_training_study_ids": outer[1:],
                "inner_validation_study_ids": outer[:1],
                "selected_model": "Ridge", "inner_validation_comparison": [{}],
                "outer_test_metrics": {}, "outer_test_baseline_metrics": {},
            })
        folds[0]["inner_validation_study_ids"] = [folds[0]["inner_training_study_ids"][0]]
        payload = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "endpoint", "fold_count": 4, "study_count": 4,
            "observation_count": 4, "folds": folds,
            "per_study_performance": [{"study_id": sid} for sid in study_ids],
            "uncertainty": {"status": "NOT_CALIBRATED"},
            "validation_scope": "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION",
        }
        errors = validate_stage_payload(
            "reproducibility_evaluation", payload, run_id="R1",
            project_id="P1", study_ids=set(study_ids),
        )
        self.assertIn("REPRODUCIBILITY_FOLD_LEAKAGE", {item["code"] for item in errors})

    def _valid_modeling_validation_evidence(self):
        study_ids = ["S1", "S2", "S3", "S4"]
        feature_bindings = [{
            "feature_id": "concentration", "condition_type": "concentration",
            "value_field": "raw_value", "value_type": "NUMERIC", "expected_unit": "mol/L",
        }]
        task = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "specific endpoint", "outcome_type": "NUMERIC",
            "outcome_value_field": "raw_value", "outcome_unit": "mAh/g",
            "feature_bindings": feature_bindings,
            "split": {"strategy": "GROUPED_HOLDOUT", "fractions": {
                "train": 0.5, "validation": 0.25, "test": 0.25,
            }},
        }
        report = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "specific endpoint", "outcome_type": "NUMERIC",
            "outcome_value_field": "raw_value", "outcome_unit": "mAh/g",
            "primary_selection_metric": "validation_rmse_minimized",
            "selected_model": "ridge_regression", "selected_candidate_id": "ridge_1",
            "validation_comparison": [{"candidate_id": "ridge_1"}],
            "test_evaluation": {"n": 1},
        }
        artifact = {
            "schema_version": "1.0", "engine_version": "synthetic", "task_id": "T1",
            "model_type": "ridge_regression", "target_id": "Y",
            "endpoint_definition": "specific endpoint", "outcome_value_field": "raw_value",
            "outcome_unit": "mAh/g", "feature_bindings": json.loads(json.dumps(feature_bindings)),
            "selected_candidate_id": "ridge_1", "selection_metric": "validation_rmse_minimized",
            "training_observation_ids": ["O1", "O2", "O3"],
            "training_study_ids": ["S1", "S2", "S3"], "test_observation_ids": ["O4"],
            "model_parameters": {"alpha": 1.0},
        }
        groups = {"train": ["S1", "S2"], "validation": ["S3"], "test": ["S4"]}
        split = {
            "study_to_split": {"S1": "train", "S2": "train", "S3": "validation", "S4": "test"},
            "observation_ids_by_split": {"train": ["O1", "O2"], "validation": ["O3"], "test": ["O4"]},
        }
        hashes = {
            "cohort_sha256": "e" * 64, "cohort_report_sha256": "c" * 64,
            "split_manifest_sha256": "b" * 64, "cohort_manifest_sha256": "d" * 64,
            "task_sha256": "a" * 64,
        }
        model_manifest = {
            "schema_version": "1.0", "task_id": "T1", "selected_model": "ridge_regression",
            "input_hashes": dict(hashes),
            "output_hashes": {"model_report.json": "f" * 64, "model_artifact.json": "1" * 64},
            "study_ids_by_split": groups,
        }
        folds = []
        for index, held_out in enumerate(study_ids, start=1):
            outer = [sid for sid in study_ids if sid != held_out]
            folds.append({
                "fold": index, "test_study_ids": [held_out],
                "outer_training_study_ids": outer,
                "inner_training_study_ids": outer[1:],
                "inner_validation_study_ids": outer[:1],
            })
        evaluation = {
            "schema_version": "1.0", "task_id": "T1", "target_id": "Y",
            "endpoint_definition": "specific endpoint", "fold_count": 4, "study_count": 4,
            "observation_count": 4, "folds": folds,
            "per_study_performance": [{"study_id": sid} for sid in study_ids],
            "validation_scope": "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION",
            "uncertainty": {"status": "NOT_CALIBRATED"},
        }
        evaluation_manifest = {
            "schema_version": "1.0", "task_id": "T1", "fold_count": 4,
            "study_ids": study_ids, "input_hashes": dict(hashes),
            "output_hashes": {"reproducibility_evaluation.json": "3" * 64},
            "selection_protocol": "NESTED_INNER_STUDY_HOLDOUT",
            "test_protocol": "OUTER_GROUPED_K_FOLD_EACH_STUDY_HELD_OUT_ONCE",
            "uncertainty_status": "DESCRIPTIVE_CROSS_STUDY_ERROR_ONLY_NOT_CALIBRATED",
        }
        evidence = [
            {"artifact_id": "model_report", "artifact_type": "model_report", "payload": report, "sha256": "f" * 64},
            {"artifact_id": "model_artifact", "artifact_type": "model_artifact", "payload": artifact, "sha256": "1" * 64},
            {"artifact_id": "model_manifest", "artifact_type": "modeling_run_manifest", "payload": model_manifest, "sha256": "2" * 64},
            {"artifact_id": "evaluation", "artifact_type": "reproducibility_evaluation", "payload": evaluation, "sha256": "3" * 64},
            {"artifact_id": "evaluation_manifest", "artifact_type": "reproducibility_evaluation_manifest", "payload": evaluation_manifest, "sha256": "4" * 64},
        ]
        prior = {
            "modeling_task": {"payload": task, "sha256": "a" * 64},
            "cohort_report": {"payload": {"eligible_study_ids": study_ids}, "sha256": "c" * 64},
            "split_manifest": {"payload": split, "sha256": "b" * 64},
            "modeling_cohort_manifest": {"payload": {}, "sha256": "d" * 64},
            "modeling_cohort_csv": {"payload": None, "sha256": "e" * 64},
        }
        return evidence, prior, set(study_ids)

    def test_model_validation_accepts_exact_task_feature_and_unit_bindings(self):
        evidence, prior, study_ids = self._valid_modeling_validation_evidence()
        errors = validate_stage_evidence(
            "modeling_validation", evidence, run_id="R1", project_id="P1",
            study_ids=study_ids, source_snapshot=[], prior_payloads=prior,
        )
        self.assertEqual([], errors)

    def test_model_validation_rejects_feature_binding_drift_from_task(self):
        evidence, prior, study_ids = self._valid_modeling_validation_evidence()
        evidence[1]["payload"]["feature_bindings"][0]["expected_unit"] = "mmol/L"
        codes = {item["code"] for item in validate_stage_evidence(
            "modeling_validation", evidence, run_id="R1", project_id="P1",
            study_ids=study_ids, source_snapshot=[], prior_payloads=prior,
        )}
        self.assertIn("MODEL_ARTIFACT_FEATURE_BINDING_MISMATCH", codes)

    def test_model_validation_rejects_outcome_unit_drift_from_task(self):
        evidence, prior, study_ids = self._valid_modeling_validation_evidence()
        evidence[1]["payload"]["outcome_unit"] = "g/Ah"
        evidence[0]["payload"]["outcome_unit"] = "g/Ah"
        codes = {item["code"] for item in validate_stage_evidence(
            "modeling_validation", evidence, run_id="R1", project_id="P1",
            study_ids=study_ids, source_snapshot=[], prior_payloads=prior,
        )}
        self.assertIn("MODEL_ARTIFACT_TASK_BINDING_MISMATCH", codes)
        self.assertIn("MODEL_REPORT_TASK_BINDING_MISMATCH", codes)

    def test_model_validation_rejects_selection_model_and_metric_mismatch(self):
        evidence, prior, study_ids = self._valid_modeling_validation_evidence()
        evidence[1]["payload"]["model_type"] = "mean_baseline"
        evidence[1]["payload"]["selection_metric"] = "validation_mae"
        codes = {item["code"] for item in validate_stage_evidence(
            "modeling_validation", evidence, run_id="R1", project_id="P1",
            study_ids=study_ids, source_snapshot=[], prior_payloads=prior,
        )}
        self.assertIn("MODEL_TYPE_SELECTION_MISMATCH", codes)
        self.assertIn("MODEL_SELECTION_METRIC_MISMATCH", codes)

    def test_source_inventory_rejects_ambiguous_same_name_same_hash_sources(self):
        snapshot = [
            {"source_id": "left", "role": "STRUCTURED_DATA", "path": "/left/data.csv", "sha256": "a" * 64},
            {"source_id": "right", "role": "STRUCTURED_DATA", "path": "/right/data.csv", "sha256": "a" * 64},
        ]
        payload = {"schema_version": "1.0", "items": [{
            "inventory_id": "INV_1", "source_file": "data.csv", "source_sha256": "a" * 64,
            "source_format": "csv", "locator_type": "csv_column", "locator": "capacity",
            "mapping_status": "UNRESOLVED",
        }]}
        codes = {item["code"] for item in validate_stage_payload(
            "source_inventory", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=snapshot, selected_source_ids={"left", "right"},
        )}
        self.assertIn("SOURCE_INVENTORY_SOURCE_ID_AMBIGUOUS", codes)

    def test_reconciliation_issue_count_rejects_boolean_integer_substitution(self):
        payload = {"schema_version": "1.0", "bundle_sha256": "a" * 64,
                   "valid_bundle": True, "issue_count": True,
                   "issues": [{"issue_id": "ISSUE_1"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "reconciliation_report", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, canonical_sha256="a" * 64,
        )}
        self.assertIn("RECONCILIATION_ISSUE_COUNT_MISMATCH", codes)

    def test_reconciliation_report_rejects_duplicate_or_missing_issue_ids(self):
        payload = {"schema_version": "1.0", "bundle_sha256": "a" * 64,
                   "valid_bundle": True, "issue_count": 2,
                   "issues": [{"issue_id": "ISSUE_1"}, {"issue_id": "ISSUE_1"}]}
        codes = {item["code"] for item in validate_stage_payload(
            "reconciliation_report", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, canonical_sha256="a" * 64,
        )}
        self.assertIn("RECONCILIATION_ISSUE_ID_DUPLICATE", codes)
        payload["issues"][1] = {"issue_id": []}
        codes = {item["code"] for item in validate_stage_payload(
            "reconciliation_report", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, canonical_sha256="a" * 64,
        )}
        self.assertIn("RECONCILIATION_ISSUE_ID_INVALID", codes)

    def test_malformed_reconciliation_issue_id_fails_closed_without_crashing(self):
        bundle = {
            "schema_version": "1.0", "project_id": "P1", "mapping_version": "M1",
            "build_provenance": {"mapping_plan_sha256": "a" * 64, "source_inventory_sha256": "b" * 64},
            "studies": [], "systems": [], "conditions": [], "experiments": [],
            "observations": [], "comparisons": [], "evidence": [],
        }
        report = {"schema_version": "1.0", "bundle_sha256": "a" * 64,
                  "valid_bundle": True, "issue_count": 1, "issues": [{"issue_id": []}]}
        decisions = {"schema_version": "1.0", "reconciliation_report_sha256": "b" * 64, "decisions": []}
        evidence = [
            {"artifact_id": "bundle", "artifact_type": "canonical_bundle", "payload": bundle, "sha256": "a" * 64},
            {"artifact_id": "report", "artifact_type": "reconciliation_report", "payload": report, "sha256": "b" * 64},
            {"artifact_id": "decisions", "artifact_type": "reconciliation_decisions", "payload": decisions, "sha256": "c" * 64},
        ]
        errors = validate_stage_evidence(
            "canonical_reconciliation", evidence, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=[],
        )
        codes = {item["code"] for item in errors}
        self.assertIn("RECONCILIATION_ISSUE_ID_INVALID", codes)
        self.assertIn("RECONCILIATION_DECISIONS_INPUT_INVALID", codes)

    def test_unknown_evidence_type_is_rejected(self):
        codes = {item["code"] for item in validate_stage_payload(
            "invented_type", {}, run_id="R1", project_id="P1", study_ids={"S1"}
        )}
        self.assertIn("UNKNOWN_STAGE_ARTIFACT_TYPE", codes)


    def test_extraction_review_hashes_only_the_sources_selected_by_prior_stage(self):
        snapshot = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": "/data/paper.pdf", "sha256": "a" * 64},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": "/data/paper_si.pdf", "sha256": "b" * 64},
        ]
        selection = {"payload": {
            "selected_sources": [{"source_id": "paper", "role": "PRIMARY_PAPER",
                                  "path": "/data/paper.pdf", "sha256": "a" * 64}],
            "excluded_sources": [{"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION",
                                  "path": "/data/paper_si.pdf", "sha256": "b" * 64,
                                  "reason": "Outside the selected scope."}],
        }, "sha256": "c" * 64}
        review = {
            "schema_version": "1.0", "source_hashes": {"paper": "a" * 64},
            "reviewed_locators": [{"source_id": "paper", "locator_type": "pdf_page",
                                   "locator": "page 1", "review_status": "SPOT_CHECKED"}],
            "human_review": {"reviewer": "reviewer", "reviewed_at": "2026-01-01T00:00:00Z",
                             "decision": "ACCEPTED_WITH_LIMITATIONS"},
        }
        evidence = [{"artifact_id": "review", "artifact_type": "extraction_review_record",
                     "payload": review, "sha256": "d" * 64}]
        errors = validate_stage_evidence(
            "extraction_review", evidence, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=snapshot,
            prior_payloads={"source_selection_manifest": selection},
        )
        self.assertEqual([], errors)

    def test_extraction_review_rejects_hashes_for_excluded_source(self):
        snapshot = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": "/data/paper.pdf", "sha256": "a" * 64},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": "/data/paper_si.pdf", "sha256": "b" * 64},
        ]
        selection = {"payload": {"selected_sources": [{
            "source_id": "paper", "role": "PRIMARY_PAPER",
            "path": "/data/paper.pdf", "sha256": "a" * 64,
        }]}, "sha256": "c" * 64}
        review = {
            "schema_version": "1.0", "source_hashes": {"paper": "a" * 64, "si": "b" * 64},
            "reviewed_locators": [{"source_id": "paper", "locator_type": "pdf_page",
                                   "locator": "page 1", "review_status": "SPOT_CHECKED"}],
            "human_review": {"reviewer": "reviewer", "reviewed_at": "2026-01-01T00:00:00Z",
                             "decision": "ACCEPTED_WITH_LIMITATIONS"},
        }
        errors = validate_stage_evidence(
            "extraction_review", [{"artifact_id": "review", "artifact_type": "extraction_review_record",
                                   "payload": review, "sha256": "d" * 64}],
            run_id="R1", project_id="P1", study_ids={"S1"}, source_snapshot=snapshot,
            prior_payloads={"source_selection_manifest": selection},
        )
        self.assertIn("EXTRACTION_SOURCE_HASH_BINDING_MISMATCH", {item["code"] for item in errors})

    def test_extraction_review_rejects_rejected_or_follow_up_decision_for_pass(self):
        base = {
            "schema_version": "1.0", "source_hashes": {"paper": "a" * 64},
            "reviewed_locators": [{"source_id": "paper", "locator_type": "pdf_page",
                                   "locator": "page 1", "review_status": "SPOT_CHECKED"}],
            "human_review": {"reviewer": "reviewer", "reviewed_at": "2026-01-01T00:00:00Z",
                             "decision": "REJECTED"},
        }
        for decision in ("REJECTED", "REQUIRES_FOLLOW_UP"):
            with self.subTest(decision=decision):
                payload = json.loads(json.dumps(base))
                payload["human_review"]["decision"] = decision
                codes = {item["code"] for item in validate_stage_payload(
                    "extraction_review_record", payload, run_id="R1", project_id="P1",
                    study_ids={"S1"}, source_snapshot=[{
                        "source_id": "paper", "role": "PRIMARY_PAPER",
                        "path": "/data/paper.pdf", "sha256": "a" * 64,
                    }],
                )}
                self.assertIn("EXTRACTION_REVIEW_NOT_ACCEPTED", codes)

    def test_extraction_review_requires_preceding_source_selection_evidence(self):
        review = {
            "schema_version": "1.0", "source_hashes": {},
            "reviewed_locators": [{"source_id": "paper", "locator_type": "pdf_page",
                                   "locator": "page 1", "review_status": "SPOT_CHECKED"}],
            "human_review": {"reviewer": "reviewer", "reviewed_at": "2026-01-01T00:00:00Z",
                             "decision": "ACCEPTED_WITH_LIMITATIONS"},
        }
        errors = validate_stage_evidence(
            "extraction_review", [{"artifact_id": "review", "artifact_type": "extraction_review_record",
                                   "payload": review, "sha256": "d" * 64}],
            run_id="R1", project_id="P1", study_ids={"S1"},
            source_snapshot=[{"source_id": "paper", "role": "PRIMARY_PAPER",
                              "path": "/data/paper.pdf", "sha256": "a" * 64}],
        )
        self.assertIn("EXTRACTION_SELECTION_MANIFEST_MISSING", {item["code"] for item in errors})

    def test_run_manifest_rejects_duplicate_source_artifact_ids(self):
        source = {"source_id": "paper", "role": "PRIMARY_PAPER",
                  "path": "/data/paper.pdf", "sha256": "a" * 64}
        payload = {
            "schema_version": "1.0", "run_id": "R1", "project_id": "P1",
            "source_artifacts": [
                {"artifact_id": "paper", "path": "/data/paper.pdf", "sha256": "a" * 64},
                {"artifact_id": "paper", "path": "/data/paper.pdf", "sha256": "a" * 64},
            ],
        }
        codes = {item["code"] for item in validate_stage_payload(
            "run_manifest", payload, run_id="R1", project_id="P1",
            study_ids={"S1"}, source_snapshot=[source],
        )}
        self.assertIn("RUN_MANIFEST_SOURCE_ID_DUPLICATE", codes)

    def test_stage_evidence_malformed_items_fail_closed_without_raising(self):
        errors = validate_stage_evidence(
            "source_selection", [None, "not-an-object"], run_id="R1",
            project_id="P1", study_ids={"S1"}, source_snapshot=[],
        )
        codes = {item["code"] for item in errors}
        self.assertIn("STAGE_EVIDENCE_ITEM_INVALID", codes)
        self.assertIn("STAGE_REQUIRED_EVIDENCE_TYPE_MISSING", codes)

if __name__ == "__main__":
    unittest.main()
