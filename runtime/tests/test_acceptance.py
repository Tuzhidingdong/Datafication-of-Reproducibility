import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import contextlib
from pathlib import Path
from unittest.mock import patch

from dor.acceptance import STAGE_ORDER, validate_acceptance_record
from dor.cli import build_parser, main
from dor.run_manager import initialize_run, record_stage_status


class AcceptanceValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_root = self.root / "sources"
        self.source_root.mkdir()
        self.paper = self.source_root / "paper.pdf"
        self.si = self.source_root / "paper_si.pdf"
        self.table = self.source_root / "paired.csv"
        self.paper.write_bytes(b"synthetic paper bytes")
        self.si.write_bytes(b"synthetic SI bytes")
        self.table.write_text("feature,value\nconcentration,1.0\n", encoding="utf-8")
        self._create_run(["STUDY_1"])

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.sha(path)

    def _create_run(self, study_ids):
        self.run_id = "RUN_MULTI" if len(study_ids) > 1 else "RUN_1"
        self.study_ids = list(study_ids)
        self.run_root = self.root / "runs" / self.run_id
        self.plan_path = self.root / f"{self.run_id}_plan.json"
        self.source_records = [
            {"source_id": "paper", "role": "PRIMARY_PAPER", "path": str(self.paper), "sha256": self.sha(self.paper)},
            {"source_id": "si", "role": "SUPPLEMENTARY_INFORMATION", "path": str(self.si), "sha256": self.sha(self.si)},
            {"source_id": "paired", "role": "STRUCTURED_DATA", "path": str(self.table), "sha256": self.sha(self.table)},
        ]
        artifact_paths = {
            "selection_manifest": "evidence/source_selection_manifest.json",
            "source_inventory": "evidence/source_inventory.json",
            "extraction_review": "evidence/extraction_review_record.json",
            "mapping_plan": "evidence/mapping_plan.json",
            "canonical_bundle": "evidence/canonical_bundle.json",
            "reconciliation_report": "evidence/reconciliation_report.json",
            "reconciliation_decisions": "evidence/reconciliation_decisions.json",
            "modeling_task": "evidence/modeling_task.json",
            "cohort_report": "evidence/cohort_report.json",
            "split_manifest": "evidence/split_manifest.json",
            "modeling_cohort_manifest": "evidence/modeling_cohort_manifest.json",
            "modeling_cohort_csv": "evidence/modeling_cohort.csv",
            "model_report": "evidence/model_report.json",
            "model_artifact": "evidence/model_artifact.json",
            "modeling_run_manifest": "evidence/modeling_run_manifest.json",
            "reproducibility_evaluation": "evidence/reproducibility_evaluation.json",
            "reproducibility_evaluation_manifest": "evidence/reproducibility_evaluation_manifest.json",
            "publication_manifest": "evidence/publication_package_manifest.json",
            "publication_integrity": "evidence/publication_integrity_report.json",
        }
        outputs = [{"artifact_id": artifact_id, "path": relpath}
                   for artifact_id, relpath in artifact_paths.items()]
        plan = {
            "schema_version": "1.0",
            "project_id": "PROJECT_1",
            "source_roots": [str(self.source_root)],
            "source_artifacts": [
                {"artifact_id": "paper", "path": str(self.paper)},
                {"artifact_id": "si", "path": str(self.si)},
                {"artifact_id": "paired", "path": str(self.table)},
            ],
            "stages": [{
                "stage_id": "acceptance_evidence",
                "executor": "local",
                "depends_on": [],
                "inputs": ["paper", "si", "paired"],
                "outputs": outputs,
            }],
        }
        self.plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        initialized = initialize_run(self.plan_path, self.run_root, self.run_id)
        self.manifest = Path(initialized["manifest_path"])
        record_stage_status(
            self.manifest, "acceptance_evidence", "RUNNING", "local",
            command="synthetic acceptance fixture",
        )

        paths = {key: self.run_root / relpath for key, relpath in artifact_paths.items()}
        ids = list(study_ids)
        groups = {}
        for index, study_id in enumerate(ids):
            groups[study_id] = ("train", "validation", "test")[index] if index < 3 else "train"
        study_groups = {
            name: sorted(study_id for study_id, partition in groups.items() if partition == name)
            for name in ("train", "validation", "test")
        }
        source_hashes = {item["source_id"]: item["sha256"] for item in self.source_records}

        selection = {
            "schema_version": "1.0",
            "selection_rationale": "Synthetic fixture: only the declared input set is selected.",
            "scope_statement": "Synthetic controlled acceptance fixture.",
            "study_ids": sorted(ids),
            "selected_sources": [
                {"source_id": item["source_id"], "role": item["role"],
                 "path": item["path"], "sha256": item["sha256"]}
                for item in self.source_records
            ],
            "excluded_sources": [],
            "a/b": [{"~key": 7}],
            "ids": ["S1", "S1"],
        }
        self._write_json(paths["selection_manifest"], selection)

        inventory = {
            "schema_version": "1.0",
            "items": [{
                "inventory_id": "INV_1",
                "source_role": "STRUCTURED_DATA",
                "source_file": self.table.name,
                "source_sha256": source_hashes["paired"],
                "source_format": "csv",
                "locator_type": "csv_column",
                "locator": "value",
                "observed_types": ["numeric"],
                "coverage": 1.0,
                "mapping_status": "UNRESOLVED",
            }],
        }
        inventory_hash = self._write_json(paths["source_inventory"], inventory)

        extraction = {
            "schema_version": "1.0",
            "source_hashes": source_hashes,
            "reviewed_locators": [
                {"source_id": item["source_id"],
                 "locator_type": "pdf_page" if item["source_id"] != "paired" else "csv_row",
                 "locator": "page 1" if item["source_id"] != "paired" else "row 2",
                 "review_status": "SPOT_CHECKED"}
                for item in self.source_records
            ],
            "human_review": {
                "reviewer": "synthetic reviewer",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "decision": "ACCEPTED_WITH_LIMITATIONS",
            },
        }
        self._write_json(paths["extraction_review"], extraction)

        mapping = {
            "schema_version": "1.0",
            "mapping_version": "MAPPING_1",
            "source_inventory_sha256": inventory_hash,
            "rules": [{
                "mapping_rule_id": "MAP_1",
                "source_item_id": "INV_1",
                "target_entity": "conditions",
                "target_field_id": "concentration",
                "status": "APPROVED",
                "transformation": {"type": "IDENTITY", "parameters": {"unit": "mol/L"}},
                "review": {
                    "reviewer": "synthetic reviewer",
                    "reviewed_at": "2026-01-01T00:00:00Z",
                    "decision_note": "Synthetic fixture only.",
                },
            }],
        }
        self._write_json(paths["mapping_plan"], mapping)

        studies = []
        systems = []
        conditions = []
        experiments = []
        observations = []
        evidence = []
        for index, study_id in enumerate(ids):
            suffix = study_id.replace("-", "_")
            system_id = f"SYS_{suffix}"
            condition_id = f"COND_{suffix}"
            experiment_id = f"EXP_{suffix}"
            observation_id = f"OBS_{suffix}"
            evidence_id = f"EV_{suffix}"
            studies.append({"study_id": study_id, "source_locators": []})
            systems.append({"system_id": system_id, "study_ids": [study_id], "system_type": "synthetic_system"})
            conditions.append({
                "condition_id": condition_id, "system_ids": [system_id],
                "condition_type": "concentration", "value_state": "REPORTED",
                "raw_value": 1.0 + index, "raw_unit": "mol/L",
            })
            experiments.append({
                "experiment_id": experiment_id, "study_id": study_id,
                "system_id": system_id, "condition_ids": [condition_id],
            })
            observations.append({
                "observation_id": observation_id, "experiment_id": experiment_id,
                "target_id": "CAPACITY", "value_state": "REPORTED",
                "raw_value": 100.0 + index, "raw_unit": "mAh/g",
                "endpoint_definition": "specific discharge capacity",
                "evidence_ids": [evidence_id],
            })
            evidence.append({
                "evidence_id": evidence_id, "study_id": study_id,
                "source_locator": {
                    "source_file": self.paper.name, "source_sha256": source_hashes["paper"],
                    "locator_type": "pdf_page", "locator": f"page {index + 1}",
                },
                "evidence_type": "table_value",
                "extraction_status": "VERIFIED",
            })
        canonical = {
            "schema_version": "1.0", "project_id": "PROJECT_1",
            "mapping_version": "MAPPING_1",
            "build_provenance": {
                "mapping_plan_sha256": self.sha(paths["mapping_plan"]),
                "source_inventory_sha256": inventory_hash,
            },
            "studies": studies, "systems": systems, "conditions": conditions,
            "experiments": experiments, "observations": observations,
            "comparisons": [], "evidence": evidence,
        }
        canonical_hash = self._write_json(paths["canonical_bundle"], canonical)
        reconciliation = {
            "schema_version": "1.0", "bundle_sha256": canonical_hash,
            "valid_bundle": True, "issue_count": 0, "issues": [],
            "decision_policy": "HUMAN_REVIEW_ONLY_NO_CANONICAL_DATA_MUTATION",
            "validation_scope": "DETERMINISTIC_CANDIDATE_DETECTION_NOT_SCIENTIFIC_RECONCILIATION",
        }
        reconciliation_hash = self._write_json(paths["reconciliation_report"], reconciliation)
        decisions = {
            "schema_version": "1.0",
            "reconciliation_report_sha256": reconciliation_hash,
            "decisions": [],
        }
        self._write_json(paths["reconciliation_decisions"], decisions)

        task = {
            "schema_version": "1.0", "task_id": "TASK_1",
            "target_id": "CAPACITY", "endpoint_definition": "specific discharge capacity",
            "outcome_type": "NUMERIC", "outcome_value_field": "raw_value",
            "outcome_unit": "mAh/g",
            "feature_bindings": [{
                "feature_id": "concentration", "condition_type": "concentration",
                "value_field": "raw_value", "value_type": "NUMERIC", "expected_unit": "mol/L",
            }],
            "split": {
                "strategy": "EXPLICIT_STUDIES",
                "validation_study_ids": sorted(sid for sid, part in groups.items() if part == "validation"),
                "test_study_ids": sorted(sid for sid, part in groups.items() if part == "test"),
            },
        }
        task_hash = self._write_json(paths["modeling_task"], task)

        cohort = {
            "schema_version": "1.0", "valid": True, "task_id": "TASK_1",
            "target_id": "CAPACITY", "endpoint_definition": "specific discharge capacity",
            "eligible_observation_count": len(ids), "eligible_study_count": len(ids),
            "eligible_study_ids": sorted(ids),
            "bundle_sha256": canonical_hash, "task_sha256": task_hash,
            "split_counts": {
                name: {"study_count": len(study_groups[name]), "observation_count": len(study_groups[name])}
                for name in ("train", "validation", "test")
            },
        }
        self._write_json(paths["cohort_report"], cohort)
        split_manifest = {
            "schema_version": "1.0", "task_id": "TASK_1", "study_group_field": "study_id",
            "strategy": "EXPLICIT_STUDIES", "seed": 42,
            "study_to_split": groups,
            "observation_ids_by_split": {
                name: [f"OBS_{sid.replace('-', '_')}" for sid in ids if groups[sid] == name]
                for name in ("train", "validation", "test")
            },
            "leakage_check": {
                "valid": True, "study_overlap_count": 0,
                "study_ids_by_split": study_groups,
            },
            "validation_scope": "DETERMINISTIC_GROUPED_STUDY_SPLIT_NOT_SCIENTIFIC_VALIDATION",
        }
        split_hash = self._write_json(paths["split_manifest"], split_manifest)
        csv_text = "study_id,observation_id,split\\n" + "".join(
            f"{sid},OBS_{sid.replace('-', '_')},{groups[sid]}\\n" for sid in sorted(ids)
        )
        paths["modeling_cohort_csv"].parent.mkdir(parents=True, exist_ok=True)
        paths["modeling_cohort_csv"].write_text(csv_text, encoding="utf-8")
        cohort_manifest = {
            "schema_version": "1.0", "task_id": "TASK_1",
            "bundle_sha256": canonical_hash, "task_sha256": task_hash,
            "artifacts": ["modeling_cohort.csv", "cohort_report.json", "split_manifest.json"],
            "eligible_observation_count": len(ids), "eligible_study_count": len(ids),
            "artifact_sha256": {
                "modeling_cohort.csv": self.sha(paths["modeling_cohort_csv"]),
                "cohort_report.json": self.sha(paths["cohort_report"]),
                "split_manifest.json": split_hash,
            },
            "source_policy": "SYNTHETIC_FIXTURE_ONLY",
        }
        cohort_manifest_hash = self._write_json(paths["modeling_cohort_manifest"], cohort_manifest)

        training_study_ids = sorted(study_id for study_id, partition in groups.items() if partition != "test")
        test_study_ids = sorted(study_id for study_id, partition in groups.items() if partition == "test")
        model_report = {
            "schema_version": "1.0", "task_id": "TASK_1", "target_id": "CAPACITY",
            "endpoint_definition": "specific discharge capacity", "outcome_type": "NUMERIC",
            "selected_model": "Ridge", "selected_candidate_id": "ridge_1",
            "primary_selection_metric": "mae", "validation_comparison": [{"candidate_id": "ridge_1"}],
            "test_evaluation": {"n": 1, "mae": 0.1},
            "training_observation_count": len(training_study_ids),
            "validation_observation_count": 1, "refit_observation_count": len(training_study_ids),
            "test_observation_count": 1,
        }
        model_report_hash = self._write_json(paths["model_report"], model_report)
        model_artifact = {
            "schema_version": "1.0", "engine_version": "synthetic", "task_id": "TASK_1",
            "model_type": "ridge_regression", "target_id": "CAPACITY",
            "endpoint_definition": "specific discharge capacity",
            "outcome_value_field": "raw_value", "outcome_unit": "mAh/g",
            "feature_bindings": [{
                "feature_id": "concentration", "condition_type": "concentration",
                "value_field": "raw_value", "value_type": "NUMERIC", "expected_unit": "mol/L",
            }], "selected_candidate_id": "ridge_1",
            "selection_metric": "validation_mae",
            "training_observation_ids": [f"OBS_{sid.replace('-', '_')}" for sid in training_study_ids],
            "training_study_ids": training_study_ids,
            "test_observation_ids": [f"OBS_{sid.replace('-', '_')}" for sid in test_study_ids],
            "model_parameters": {"alpha": 1.0},
        }
        model_artifact_hash = self._write_json(paths["model_artifact"], model_artifact)
        model_manifest = {
            "schema_version": "1.0", "task_id": "TASK_1", "engine_version": "synthetic",
            "input_hashes": {
                "cohort_sha256": self.sha(paths["modeling_cohort_csv"]),
                "cohort_report_sha256": self.sha(paths["cohort_report"]),
                "split_manifest_sha256": self.sha(paths["split_manifest"]),
                "cohort_manifest_sha256": cohort_manifest_hash, "task_sha256": task_hash,
            },
            "output_hashes": {
                "model_report.json": model_report_hash,
                "model_artifact.json": model_artifact_hash,
            },
            "split_strategy": "EXPLICIT_STUDIES", "split_seed": 42,
            "study_ids_by_split": study_groups, "selected_model": "Ridge",
            "selection_rule": "Validation metric only; test set evaluated after selection.",
            "source_policy": "SYNTHETIC_FIXTURE_ONLY",
        }
        self._write_json(paths["modeling_run_manifest"], model_manifest)

        evaluation_folds = []
        per_study = []
        for fold_index, held_out_id in enumerate(sorted(ids), start=1):
            outer_training_ids = sorted(study_id for study_id in ids if study_id != held_out_id)
            inner_validation_ids = outer_training_ids[:1]
            inner_training_ids = outer_training_ids[1:]
            evaluation_folds.append({
                "fold": fold_index, "test_study_ids": [held_out_id],
                "outer_training_study_ids": outer_training_ids,
                "inner_training_study_ids": inner_training_ids,
                "inner_validation_study_ids": inner_validation_ids,
                "selected_model": "Ridge",
                "inner_validation_comparison": [{}],
                "outer_test_metrics": {"n": 1}, "outer_test_baseline_metrics": {"n": 1},
            })
            per_study.append({"study_id": held_out_id, "fold": fold_index, "n": 1, "selected_model": "Ridge"})
        evaluation = {
            "schema_version": "1.0", "task_id": "TASK_1", "target_id": "CAPACITY",
            "endpoint_definition": "specific discharge capacity", "outcome_type": "NUMERIC",
            "fold_count": len(ids), "study_count": len(ids), "observation_count": len(ids),
            "seed": 42, "outer_split_strategy": "DETERMINISTIC_GROUPED_K_FOLD_BY_STUDY",
            "inner_selection_strategy": "NESTED_STUDY_HOLDOUT_WITHIN_OUTER_TRAINING_STUDIES",
            "pooled_out_of_fold_metrics": {}, "pooled_baseline_metrics": {},
            "per_study_performance": per_study,
            "between_study_error_or_bias_distribution": {},
            "folds": evaluation_folds, "model_selection_frequency": {"Ridge": len(ids)},
            "applicability_domain": {
                "method": "MIXED_FEATURE_NEAREST_NEIGHBOUR_DISTANCE",
                "distance_definition": "Synthetic grouped-fold fixture.",
                "reference_threshold": "Synthetic fixture threshold.",
                "quantile": 0.95, "counts": {"IN_DOMAIN": len(ids)},
                "warning": "Synthetic fixture only; heuristic support diagnostic.",
            },
            "uncertainty": {
                "status": "NOT_CALIBRATED", "reason": "Synthetic fixture; no calibrated prediction intervals.",
                "descriptive_absolute_error_distribution": {},
            },
            "validation_scope": "NESTED_STUDY_GROUPED_CROSS_VALIDATION_AND_HEURISTIC_FEATURE_SUPPORT_DIAGNOSTICS_NOT_PROSPECTIVE_VALIDATION",
        }
        evaluation_hash = self._write_json(paths["reproducibility_evaluation"], evaluation)
        evaluation_manifest = {
            "schema_version": "1.0", "task_id": "TASK_1", "engine_version": "synthetic",
            "input_hashes": {
                "cohort_sha256": self.sha(paths["modeling_cohort_csv"]),
                "cohort_report_sha256": self.sha(paths["cohort_report"]),
                "split_manifest_sha256": self.sha(paths["split_manifest"]),
                "cohort_manifest_sha256": cohort_manifest_hash, "task_sha256": task_hash,
            },
            "output_hashes": {"reproducibility_evaluation.json": evaluation_hash},
            "fold_count": len(ids), "seed": 42, "study_ids": sorted(ids),
            "selection_protocol": "NESTED_INNER_STUDY_HOLDOUT",
            "test_protocol": "OUTER_GROUPED_K_FOLD_EACH_STUDY_HELD_OUT_ONCE",
            "applicability_domain_method": "MIXED_FEATURE_NEAREST_NEIGHBOUR_EMPIRICAL_REFERENCE_Q95",
            "uncertainty_status": "DESCRIPTIVE_CROSS_STUDY_ERROR_ONLY_NOT_CALIBRATED",
            "source_policy": "SYNTHETIC_FIXTURE_ONLY",
        }
        self._write_json(paths["reproducibility_evaluation_manifest"], evaluation_manifest)

        publication_manifest = {
            "schema_version": "1.0", "project_id": "PROJECT_1", "run_id": self.run_id,
            "package_version": "1.0", "writing_guide": "README_FOR_WRITING_SKILL.md",
            "writing_guide_sha256": "e" * 64, "artifacts": [],
            "completeness": {"status": "complete", "unresolved_items": []},
        }
        self._write_json(paths["publication_manifest"], publication_manifest)
        self._write_json(paths["publication_integrity"], {
            "valid": True, "checked_file_count": 1, "errors": [],
        })

        record_stage_status(self.manifest, "acceptance_evidence", "SUCCEEDED", "local")

        self.output_paths = paths
        self.stage_types = {
            "source_selection": [("source_selection_manifest", "selection_manifest"),
                                 ("source_inventory", "source_inventory")],
            "source_integrity": [("run_manifest", None)],
            "extraction_review": [("extraction_review_record", "extraction_review")],
            "semantic_mapping": [("mapping_plan", "mapping_plan")],
            "canonical_reconciliation": [("canonical_bundle", "canonical_bundle"),
                                         ("reconciliation_report", "reconciliation_report"),
                                         ("reconciliation_decisions", "reconciliation_decisions")],
            "cohort_feasibility": [("modeling_task", "modeling_task"),
                                   ("cohort_report", "cohort_report"),
                                   ("split_manifest", "split_manifest"),
                                   ("modeling_cohort_manifest", "modeling_cohort_manifest"),
                                   ("modeling_cohort_csv", "modeling_cohort_csv")],
            "modeling_validation": [("model_report", "model_report"),
                                    ("model_artifact", "model_artifact"),
                                    ("modeling_run_manifest", "modeling_run_manifest"),
                                    ("reproducibility_evaluation", "reproducibility_evaluation"),
                                    ("reproducibility_evaluation_manifest", "reproducibility_evaluation_manifest")],
            "publication_handoff": [("publication_package_manifest", "publication_manifest"),
                                    ("publication_integrity_report", "publication_integrity")],
        }
        self.stage_evidence = {}
        for stage_id, entries in self.stage_types.items():
            items = []
            for artifact_type, key in entries:
                if key is None:
                    path = self.manifest
                    artifact_id = "run_manifest"
                else:
                    path = paths[key]
                    artifact_id = {
                        "selection_manifest": "selection_manifest", "source_inventory": "source_inventory",
                        "extraction_review": "extraction_review", "mapping_plan": "mapping_plan",
                        "canonical_bundle": "canonical_bundle", "reconciliation_report": "reconciliation_report",
                        "reconciliation_decisions": "reconciliation_decisions",
                        "modeling_task": "modeling_task", "cohort_report": "cohort_report",
                        "split_manifest": "split_manifest", "modeling_cohort_manifest": "modeling_cohort_manifest",
                        "modeling_cohort_csv": "modeling_cohort_csv",
                        "model_report": "model_report", "model_artifact": "model_artifact",
                        "modeling_run_manifest": "modeling_run_manifest",
                        "reproducibility_evaluation": "reproducibility_evaluation",
                        "reproducibility_evaluation_manifest": "reproducibility_evaluation_manifest",
                        "publication_manifest": "publication_manifest", "publication_integrity": "publication_integrity",
                    }[key]
                items.append({
                    "artifact_id": artifact_id, "artifact_type": artifact_type,
                    "path": str(path), "sha256": self.sha(path),
                })
            self.stage_evidence[stage_id] = items

        self.record_path = self.root / f"{self.run_id}_acceptance.json"
        self.record = {
            "schema_version": "1.0", "acceptance_id": "ACC_1", "project_id": "PROJECT_1",
            "scope": "MULTI_STUDY_PILOT" if len(ids) > 1 else "CONTROLLED_SINGLE_STUDY",
            "run_id": self.run_id, "run_manifest_sha256": self.sha(self.manifest),
            "source_snapshot": {
                "study_count": len(ids), "study_ids": ids,
                "artifacts": self.source_records,
            },
            "stages": [
                {"stage_id": stage, "status": "NOT_STARTED", "evidence": [], "limitations": [], "checks": []}
                for stage in STAGE_ORDER
            ],
            "final_assessment": {
                "decision": "NOT_ASSESSED", "assessed_by": "reviewer",
                "rationale": "Not yet reviewed.", "blocking_issue_ids": [],
            },
        }
        self.write_record()

    def write_record(self):
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")

    def set_stage(self, stage_id, status, evidence=True, **extra):
        stage = next(item for item in self.record["stages"] if item["stage_id"] == stage_id)
        stage["status"] = status
        stage.update(extra)
        if evidence:
            stage["evidence"] = [dict(item) for item in self.stage_evidence[stage_id]]
            first = stage["evidence"][0]
            stage["checks"] = [{
                "check_id": f"{stage_id}_schema_version",
                "artifact_id": first["artifact_id"],
                "json_pointer": "/run_id" if stage_id == "source_integrity" else "/schema_version",
                "operator": "equals",
                "expected": self.run_id if stage_id == "source_integrity" else "1.0",
            }]
        else:
            stage["evidence"] = []
            stage["checks"] = []
        self.write_record()

    def validate(self):
        return validate_acceptance_record(self.record_path, self.manifest)

    def test_initial_record_is_valid_but_not_scientifically_accepted(self):
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["final_decision"], "NOT_ASSESSED")
        self.assertTrue(report["scientific_review_required"])

    def test_all_pass_requires_typed_evidence_and_cross_stage_bindings(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.write_record()
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])

    def test_multi_study_scope_requires_multiple_studies(self):
        self.record["scope"] = "MULTI_STUDY_PILOT"
        self.record["source_snapshot"]["study_count"] = 1
        self.write_record()
        self.assertIn("MULTI_STUDY_SCOPE_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_single_study_cannot_pass_model_validation(self):
        self.set_stage("modeling_validation", "PASS")
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("SINGLE_STUDY_MODEL_VALIDATION_INVALID", codes)

    def test_conditional_pass_allows_na_only_with_reason(self):
        for stage in STAGE_ORDER:
            if stage in {"cohort_feasibility", "modeling_validation"}:
                self.set_stage(stage, "NOT_APPLICABLE", evidence=False,
                    not_applicable_reason="Single Study cannot support Study-held-out validation.")
            else:
                self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "CONDITIONAL_PASS"
        self.write_record()
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])

    def test_na_without_reason_is_rejected(self):
        self.set_stage("modeling_validation", "NOT_APPLICABLE", evidence=False)
        self.assertIn("NA_WITHOUT_REASON", {item["code"] for item in self.validate()["issues"]})

    def test_source_or_evidence_tampering_is_detected(self):
        self.set_stage("source_integrity", "PASS")
        self.paper.write_bytes(b"changed paper")
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertTrue({"SOURCE_HASH_MISMATCH", "RUN_INTEGRITY_INVALID", "RUN_SOURCE_INTEGRITY_CHANGED"} & codes)

    def test_run_manifest_hash_mismatch_is_detected(self):
        self.record["run_manifest_sha256"] = "f" * 64
        self.write_record()
        self.assertIn("RUN_MANIFEST_HASH_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_stage_order_is_fixed(self):
        self.record["stages"].reverse()
        self.write_record()
        self.assertIn("STAGE_ORDER_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_cli_registers_and_executes_validator(self):
        parser = build_parser()
        subparsers = next(action.choices for action in parser._actions if hasattr(action, "choices") and action.choices)
        self.assertIn("validate-acceptance", subparsers)
        args = ["dor", "validate-acceptance", "--record", str(self.record_path), "--run-manifest", str(self.manifest)]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            code = main()
        self.assertEqual(code, 0)
        self.assertIn('"valid": true', stdout.getvalue())

    def test_acceptance_sources_must_exactly_match_run_snapshot(self):
        self.record["source_snapshot"]["artifacts"].pop()
        self.write_record()
        self.assertIn("SOURCE_SET_DIFFERS_FROM_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_source_path_cannot_be_repointed_outside_run_snapshot(self):
        self.record["source_snapshot"]["artifacts"][0]["path"] = str(self.si)
        self.record["source_snapshot"]["artifacts"][0]["sha256"] = self.sha(self.si)
        self.write_record()
        self.assertIn("SOURCE_PATH_NOT_BOUND_TO_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_evidence_must_be_a_successful_run_artifact(self):
        self.set_stage("source_integrity", "PASS")
        self.record["stages"][1]["evidence"][0]["artifact_id"] = "invented_report"
        self.write_record()
        self.assertIn("EVIDENCE_NOT_A_COMPLETED_RUN_ARTIFACT", {item["code"] for item in self.validate()["issues"]})

    def test_evidence_hash_must_match_success_event_snapshot(self):
        self.set_stage("source_integrity", "PASS")
        self.record["stages"][1]["evidence"][0]["sha256"] = "f" * 64
        self.write_record()
        self.assertIn("EVIDENCE_HASH_NOT_BOUND_TO_RUN", {item["code"] for item in self.validate()["issues"]})

    def test_study_count_must_match_explicit_unique_study_ids(self):
        self.record["source_snapshot"]["study_count"] = 2
        self.write_record()
        self.assertIn("STUDY_ID_COUNT_MISMATCH", {item["code"] for item in self.validate()["issues"]})

    def test_stage_cannot_pass_before_prior_stage_is_complete(self):
        self.set_stage("source_integrity", "PASS")
        self.assertIn("STAGE_SEQUENCE_GAP", {item["code"] for item in self.validate()["issues"]})

    def test_stage_cannot_proceed_after_failed_stage(self):
        self.set_stage("source_selection", "FAIL", evidence=False, blocker_reason="Selected source is unreadable.")
        self.set_stage("source_integrity", "IN_PROGRESS", evidence=False)
        self.assertIn("STAGE_AFTER_BLOCKER", {item["code"] for item in self.validate()["issues"]})

    def test_single_study_cannot_mark_unrelated_stage_not_applicable(self):
        self.set_stage("semantic_mapping", "NOT_APPLICABLE", evidence=False,
            not_applicable_reason="Not applicable for this test.")
        self.assertIn("SINGLE_STUDY_NA_NOT_ALLOWED", {item["code"] for item in self.validate()["issues"]})

    def test_full_pass_cannot_retain_blocking_issue_ids(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.record["final_assessment"]["blocking_issue_ids"] = ["ISSUE_1"]
        self.write_record()
        self.assertIn("FULL_PASS_HAS_BLOCKERS", {item["code"] for item in self.validate()["issues"]})

    def test_passing_stage_requires_deterministic_content_check(self):
        self.set_stage("source_selection", "PASS")
        self.record["stages"][0]["checks"] = []
        self.write_record()
        self.assertIn("PASS_WITHOUT_DETERMINISTIC_CHECKS", {item["code"] for item in self.validate()["issues"]})

    def test_content_assertion_is_evaluated_against_actual_json(self):
        self.set_stage("source_selection", "PASS")
        self.record["stages"][0]["checks"][0]["expected"] = False
        self.write_record()
        report = self.validate()
        self.assertIn("CONTENT_ASSERTION_FAILED", {item["code"] for item in report["issues"]})
        self.assertFalse(report["assertion_checks"][0]["passed"])

    def test_json_pointer_supports_escaped_keys_and_array_indices(self):
        self.set_stage("source_selection", "PASS")
        check = self.record["stages"][0]["checks"][0]
        check.update({"json_pointer": "/a~1b/0/~0key", "operator": "gte", "expected": 7})
        self.write_record()
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["assertion_checks"][0]["actual"], 7)

    def test_unique_assertion_detects_duplicate_array_values(self):
        self.set_stage("source_selection", "PASS")
        self.record["stages"][0]["checks"][0].update({"json_pointer": "/ids", "operator": "unique"})
        self.write_record()
        self.assertIn("CONTENT_ASSERTION_FAILED", {item["code"] for item in self.validate()["issues"]})

    def test_check_must_reference_evidence_attached_to_same_stage(self):
        self.set_stage("source_selection", "PASS")
        self.record["stages"][0]["checks"][0]["artifact_id"] = "paper"
        self.write_record()
        self.assertIn("CHECK_ARTIFACT_NOT_STAGE_EVIDENCE", {item["code"] for item in self.validate()["issues"]})

    def test_passing_stage_cannot_omit_required_typed_evidence(self):
        self.set_stage("source_selection", "PASS")
        self.record["stages"][0]["evidence"].pop()
        self.write_record()
        self.assertIn("STAGE_REQUIRED_EVIDENCE_TYPE_MISSING", {item["code"] for item in self.validate()["issues"]})


if __name__ == "__main__":
    unittest.main()
