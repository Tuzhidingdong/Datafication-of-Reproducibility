import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from dor.acceptance import STAGE_ORDER, validate_acceptance_record
from dor.acceptance_ledger import initialize_acceptance_ledger, record_acceptance_revision, validate_acceptance_ledger, inspect_acceptance_history
from dor.cli import build_parser, main
from dor.run_manager import initialize_run, record_stage_status
from dor.publication import audit_publication_package_files


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
            "publication_manifest": "evidence/publication_package/package_manifest.json",
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
        csv_text = "study_id,observation_id,split\n" + "".join(
            f"{sid},OBS_{sid.replace('-', '_')},{groups[sid]}\n" for sid in sorted(ids)
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
            "outcome_value_field": "raw_value", "outcome_unit": "mAh/g",
            "selected_model": "ridge_regression", "selected_candidate_id": "ridge_1",
            "primary_selection_metric": "validation_mae", "validation_comparison": [{"candidate_id": "ridge_1"}],
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
            "study_ids_by_split": study_groups, "selected_model": "ridge_regression",
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

        package_dir = paths["publication_manifest"].parent
        package_dir.mkdir(parents=True, exist_ok=True)
        guide_path = package_dir / "README_FOR_WRITING_SKILL.md"
        guide_path.write_text("# Synthetic writing guide\n", encoding="utf-8")
        package_result = package_dir / "results" / "result.json"
        package_result.parent.mkdir(parents=True, exist_ok=True)
        package_result.write_text('{"fixture":"synthetic"}\n', encoding="utf-8")
        publication_manifest = {
            "schema_version": "1.0", "project_id": "PROJECT_1", "run_id": self.run_id,
            "package_version": "1.0", "source_hashes": source_hashes,
            "writing_guide": "README_FOR_WRITING_SKILL.md",
            "writing_guide_sha256": self.sha(guide_path),
            "artifacts": [{
                "artifact_id": "SYNTHETIC_RESULT", "path": "results/result.json",
                "type": "synthetic_result", "description": "Synthetic fixture result.",
                "status": "complete", "sha256": self.sha(package_result),
                "linked_record_ids": [], "manuscript_sections": ["Results"],
            }],
            "completeness": {"status": "complete", "unresolved_items": []},
        }
        self._write_json(paths["publication_manifest"], publication_manifest)
        integrity_report = audit_publication_package_files(package_dir)
        self._write_json(paths["publication_integrity"], integrity_report)

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
        self.ledger_path = self.root / f"{self.run_id}_acceptance_events.jsonl"
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
        if self.ledger_path.exists():
            events = [json.loads(line) for line in self.ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            next_revision = len(events) + 1
            latest = events[-1]
            snapshot_path = self.ledger_path.with_name(self.ledger_path.name + ".revisions") / latest["snapshot_file"]
            previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
            old_stages = {item["stage_id"]: item for item in previous.get("stages", [])}
            for stage in self.record.get("stages", []):
                if stage.get("stage_id") in old_stages and stage != old_stages[stage["stage_id"]] and stage.get("status") in {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}:
                    stage.update({
                        "reviewed_by": "synthetic-reviewer",
                        "reviewed_at": f"2026-11-08T00:00:{next_revision % 60:02d}Z",
                        "review_rationale": f"Synthetic fixture review revision {next_revision}.",
                    })
            if self.record["final_assessment"].get("decision") != previous.get("final_assessment", {}).get("decision") and self.record["final_assessment"].get("decision") != "NOT_ASSESSED":
                self.record["final_assessment"]["assessed_by"] = "synthetic-reviewer"
                self.record["final_assessment"]["assessed_at"] = f"2026-11-08T00:01:{next_revision % 60:02d}Z"
                if not self.record["final_assessment"].get("rationale"):
                    self.record["final_assessment"]["rationale"] = "Synthetic final-decision review."
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        try:
            if self.ledger_path.exists():
                record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Synthetic test fixture revision; no real scientific data.",
                )
            else:
                initialize_acceptance_ledger(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Created a synthetic acceptance record fixture.",
                )
        except ValueError:
            # Deliberately malformed/tampered test records remain unregistered;
            # the validator must report the latest-snapshot mismatch as well.
            pass

    def set_stage(self, stage_id, status, evidence=True, **extra):
        stage = next(item for item in self.record["stages"] if item["stage_id"] == stage_id)
        stage["status"] = status
        stage.update(extra)
        if status in {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}:
            stage.update({
                "reviewed_by": "synthetic-reviewer",
                "reviewed_at": "2026-11-08T00:00:00Z",
                "review_rationale": "Synthetic fixture stage review only.",
            })
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
        if hasattr(self, "gate_ledger_path"):
            with patch("dor.gates.inspect_gate_ledger", return_value=self.gate_report):
                return validate_acceptance_record(self.record_path, self.manifest, self.ledger_path)
        return validate_acceptance_record(self.record_path, self.manifest, self.ledger_path)

    def bind_synthetic_gate_ledger(self):
        self.gate_ledger_path = self.root / "workflow_gates.jsonl"
        self.gate_ledger_path.write_text("synthetic gate ledger snapshot\\n", encoding="utf-8")
        self.gate_event_hashes = {gate: hashlib.sha256(gate.encode()).hexdigest()
                                  for gate in ("G0", "G1", "G2", "G3", "G4")}
        evidence_by_id = {
            artifact["artifact_id"]: {
                "artifact_id": artifact["artifact_id"],
                "path": str((self.root / artifact["path"]).resolve(strict=False)),
                "sha256": artifact["sha256"],
            }
            for stage in self.record["stages"] if stage["status"] == "PASS"
            for artifact in stage["evidence"]
        }
        gate_artifact_ids = {
            "G0": ["source_inventory"],
            "G1": ["mapping_plan", "source_inventory"],
            "G2": ["canonical_bundle", "reconciliation_report", "modeling_task"],
            "G3": ["cohort_report", "split_manifest", "modeling_cohort_manifest"],
            "G4": ["model_report"],
        }
        events = {}
        gate_artifacts = {}
        for gate, artifact_ids in gate_artifact_ids.items():
            artifacts = [evidence_by_id[artifact_id] for artifact_id in artifact_ids]
            gate_artifacts[gate] = artifacts
            events[gate] = {"artifacts": artifacts}
        run_event_path = self.manifest.parent / "run_events.jsonl"
        run_events = [json.loads(line) for line in run_event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.record["run_event_ledger"] = {
            "path": str(run_event_path.resolve()),
            "sha256": self.sha(run_event_path),
            "event_count": len(run_events),
            "last_event_hash": run_events[-1]["event_hash"] if run_events else None,
        }
        self.record["workflow_gate_ledger"] = {
            "path": str(self.gate_ledger_path),
            "sha256": self.sha(self.gate_ledger_path),
            "gate_event_hashes": dict(self.gate_event_hashes),
            "gate_artifacts": gate_artifacts,
        }
        self.gate_report = {
            "gates": {gate: {"status": "APPROVED", "event_hash": digest}
                      for gate, digest in self.gate_event_hashes.items()},
            "events": events,
        }


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
        self.bind_synthetic_gate_ledger()
        self.write_record()
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])

    def test_full_pass_requires_current_g0_g4_gate_binding(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.write_record()
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATE_BINDING_REQUIRED", codes)

    def test_gate_artifact_path_hash_must_match_accepted_evidence(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        event_artifact = self.gate_report["events"]["G2"]["artifacts"][0]
        event_artifact["sha256"] = "f" * 64
        self.record["workflow_gate_ledger"]["gate_artifacts"]["G2"][0]["sha256"] = "f" * 64
        self.write_record()
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATE_EVIDENCE_IDENTITY_MISMATCH", codes)

    def test_each_gate_requires_an_accepted_evidence_overlap(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.gate_report["events"]["G3"]["artifacts"] = []
        self.record["workflow_gate_ledger"]["gate_artifacts"]["G3"] = []
        self.write_record()
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATE_HAS_NO_ACCEPTED_EVIDENCE", codes)

    def test_gate_binding_revision_invalidates_all_stages_and_rejects_ledger_rollback(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"].update({
            "decision": "PASS", "assessed_by": "synthetic-reviewer",
            "assessed_at": "2026-11-08T00:00:00Z",
            "rationale": "Synthetic approval before a later Gate revision.",
        })
        self.bind_synthetic_gate_ledger()
        self.write_record()
        self.assertTrue(self.validate()["valid"], self.validate()["issues"])
        previous_binding = json.loads(json.dumps(self.record["workflow_gate_ledger"]))
        self.gate_ledger_path.write_text(
            self.gate_ledger_path.read_text(encoding="utf-8") + "synthetic appended event\\n",
            encoding="utf-8",
        )
        revised_hashes = dict(previous_binding["gate_event_hashes"])
        revised_hashes["G2"] = hashlib.sha256(b"G2 revised approval").hexdigest()
        self.record["workflow_gate_ledger"]["sha256"] = self.sha(self.gate_ledger_path)
        self.record["workflow_gate_ledger"]["gate_event_hashes"] = revised_hashes
        event_history = []
        for gate, old_hash in previous_binding["gate_event_hashes"].items():
            event_history.append({"gate_id": gate, "event_hash": old_hash})
            if gate == "G2":
                event_history.append({"gate_id": gate, "event_hash": revised_hashes[gate]})
        with patch("dor.acceptance_ledger._load_events", return_value=event_history):
            self.write_record()
        current = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertTrue(all(stage["status"] == "NOT_STARTED" for stage in current["stages"]))
        self.assertEqual(current["final_assessment"]["decision"], "NOT_ASSESSED")
        history = validate_acceptance_ledger(self.record_path, self.ledger_path)
        self.assertTrue(history["valid"], history["issues"])
        self.assertEqual(history["latest_event_type"], "UPSTREAM_LEDGER_RECORDED")
        self.assertEqual(history["changed_gate_ids"], ["G2"])

        current["workflow_gate_ledger"] = previous_binding
        current["workflow_gate_ledger"]["sha256"] = self.sha(self.gate_ledger_path)
        self.record_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        with patch("dor.acceptance_ledger._load_events", return_value=event_history):
            with self.assertRaisesRegex(ValueError, "do not match the append-only Gate ledger tip"):
                record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Attempt to restore a previous Gate ledger binding.",
                )

    def test_run_event_ledger_rebinding_invalidates_stages_and_rejects_rollback(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.write_record()
        old_binding = json.loads(json.dumps(self.record["run_event_ledger"]))
        run_event_path = self.manifest.parent / "run_events.jsonl"
        previous_events = [json.loads(line) for line in run_event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        new_event = {"event_hash": hashlib.sha256(b"synthetic run event extension").hexdigest()}
        run_event_path.write_text(run_event_path.read_text(encoding="utf-8") + "synthetic appended event\\n", encoding="utf-8")
        self.record["run_event_ledger"] = {
            "path": old_binding["path"],
            "sha256": self.sha(run_event_path),
            "event_count": len(previous_events) + 1,
            "last_event_hash": new_event["event_hash"],
        }
        with patch("dor.run_manager._load_events", return_value=previous_events + [new_event]):
            self.write_record()
        current = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertTrue(all(stage["status"] == "NOT_STARTED" for stage in current["stages"]))
        history = validate_acceptance_ledger(self.record_path, self.ledger_path)
        self.assertTrue(history["valid"], history["issues"])
        self.assertEqual(history["latest_event_type"], "UPSTREAM_LEDGER_RECORDED")
        self.assertEqual(history["changed_ledger_ids"], ["run_event_ledger"])

        current["run_event_ledger"]["event_count"] = old_binding["event_count"]
        current["run_event_ledger"]["last_event_hash"] = old_binding["last_event_hash"]
        self.record_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        with patch("dor.run_manager._load_events", return_value=previous_events + [new_event]):
            with self.assertRaisesRegex(ValueError, "does not match its current append-only tip"):
                record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Attempt to restore an earlier Run Event Ledger tip.",
                )

    def test_run_event_ledger_append_invalidates_previous_acceptance_pass(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.write_record()
        self.assertTrue(self.validate()["valid"], self.validate()["issues"])
        run_event_path = self.manifest.parent / "run_events.jsonl"
        with run_event_path.open("a", encoding="utf-8") as handle:
            handle.write("synthetic later event\\n")
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("RUN_EVENT_LEDGER_CHANGED", codes)

    def test_full_pass_requires_run_event_ledger_binding(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.record.pop("run_event_ledger")
        self.write_record()
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("RUN_EVENT_LEDGER_BINDING_REQUIRED", codes)

    def test_gate_ledger_append_invalidates_previous_acceptance_pass(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.write_record()
        self.assertTrue(self.validate()["valid"], self.validate()["issues"])
        with self.gate_ledger_path.open("a", encoding="utf-8") as handle:
            handle.write("synthetic later G3 review\\n")
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATE_LEDGER_CHANGED", codes)

    def test_workflow_gate_ledger_symlink_is_rejected(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        link = self.root / "workflow_gates_link.jsonl"
        try:
            link.symlink_to(self.gate_ledger_path)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable in this environment.")
        self.record["workflow_gate_ledger"]["path"] = str(link)
        self.write_record()
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATE_LEDGER_INVALID", codes)

    def test_revoked_gate_blocks_full_acceptance_pass(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.bind_synthetic_gate_ledger()
        self.write_record()
        self.gate_report["gates"]["G3"]["status"] = "REVISE"
        codes = {item["code"] for item in self.validate()["issues"]}
        self.assertIn("WORKFLOW_GATES_NOT_APPROVED", codes)

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

    def test_invalidated_run_artifact_cannot_support_acceptance_pass(self):
        from dor.run_manager import verify_run

        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"]["decision"] = "PASS"
        self.write_record()

        report = verify_run(self.manifest)
        artifacts = report["artifact_manifest"]["artifacts"]
        stale = next(item for item in artifacts if item["artifact_id"] == "selection_manifest")
        stale["status"] = "STALE_OR_MISSING"
        stage_state = next(item for item in report["resume_plan"]["stages"]
                           if item["stage_id"] == "acceptance_evidence")
        stage_state["action"] = "REBUILD_REQUIRED"

        with patch("dor.acceptance.verify_run", return_value=report):
            validation = self.validate()
        codes = {item["code"] for item in validation["issues"]}
        self.assertIn("EVIDENCE_RUN_ARTIFACT_NOT_CURRENT", codes)
        self.assertFalse(validation["valid"])

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
        args = ["dor", "validate-acceptance", "--record", str(self.record_path), "--run-manifest", str(self.manifest), "--ledger", str(self.ledger_path)]
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



    def test_stage_revision_invalidates_downstream_reviews_and_final_pass(self):
        self._create_run(["STUDY_1", "STUDY_2", "STUDY_3", "STUDY_4"])
        for stage in STAGE_ORDER:
            self.set_stage(stage, "PASS")
        self.record["final_assessment"].update({
            "decision": "PASS", "assessed_by": "synthetic-reviewer",
            "assessed_at": "2026-11-08T00:00:00Z",
            "rationale": "All synthetic fixture stages were reviewed.",
        })
        self.write_record()
        self.assertTrue(self.validate()["valid"], self.validate()["issues"])

        self.record["stages"][0]["reviewed_at"] = "2026-11-08T01:00:00Z"
        self.record["stages"][0]["review_rationale"] = "Re-reviewed the source inventory binding."
        self.write_record()
        revised = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertEqual(revised["stages"][0]["status"], "PASS")
        self.assertTrue(all(item["status"] == "NOT_STARTED" for item in revised["stages"][1:]))
        self.assertTrue(all(item["evidence"] == [] and item["checks"] == [] for item in revised["stages"][1:]))
        self.assertEqual(revised["final_assessment"]["decision"], "NOT_ASSESSED")
        history = validate_acceptance_ledger(self.record_path, self.ledger_path)
        self.assertTrue(history["valid"], history["issues"])
        self.assertEqual(history["latest_event_type"], "STAGE_REVIEW_RECORDED")
        report = self.validate()
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["final_decision"], "NOT_ASSESSED")

    def test_unregistered_acceptance_edit_is_rejected_by_revision_ledger(self):
        self.record["final_assessment"]["rationale"] = "Unregistered edit."
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        report = self.validate()
        self.assertFalse(report["valid"])
        self.assertIn("ACCEPTANCE_LEDGER_INVALID", {item["code"] for item in report["issues"]})

    def test_revision_cli_records_stage_change_and_invalidates_downstream(self):
        self.record["stages"][0].update({
            "status": "PASS",
            "evidence": [dict(item) for item in self.stage_evidence["source_selection"]],
            "checks": [{
                "check_id": "source_selection_schema_version",
                "artifact_id": "selection_manifest",
                "json_pointer": "/schema_version",
                "operator": "equals",
                "expected": "1.0",
            }],
            "reviewed_by": "synthetic-reviewer",
            "reviewed_at": "2026-11-08T02:00:00Z",
            "review_rationale": "Reviewed source-selection manifest.",
        })
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        args = [
            "dor", "record-acceptance-revision", "--record", str(self.record_path),
            "--ledger", str(self.ledger_path), "--actor", "synthetic-reviewer",
            "--rationale", "Recorded a source-selection review.",
        ]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            code = main()
        self.assertEqual(code, 0, stdout.getvalue())
        revised = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertEqual(revised["stages"][0]["status"], "PASS")
        self.assertTrue(all(item["status"] == "NOT_STARTED" for item in revised["stages"][1:]))
        self.assertEqual(revised["final_assessment"]["decision"], "NOT_ASSESSED")

    def test_acceptance_history_cli_lists_review_and_invalidation_basis(self):
        self.set_stage("source_selection", "BLOCKED", evidence=False,
            blocker_reason="Synthetic review found a source selection blocker.")
        args = ["dor", "acceptance-history", "--ledger", str(self.ledger_path)]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            code = main()
        self.assertEqual(code, 0, stdout.getvalue())
        history = json.loads(stdout.getvalue())
        self.assertTrue(history["valid"])
        self.assertEqual(history["event_count"], 2)
        latest = history["events"][-1]
        self.assertEqual(latest["event_type"], "STAGE_REVIEW_RECORDED")
        self.assertEqual(latest["changed_stage_ids"], ["source_selection"])
        self.assertEqual(latest["invalidated_stage_ids"], list(STAGE_ORDER[1:]))
        self.assertEqual(latest["actor"], "synthetic-reviewer")
        self.assertTrue(latest["rationale"].strip())
        self.assertEqual(latest["final_decision"], "NOT_ASSESSED")

    def test_unreferenced_revision_snapshot_is_rejected(self):
        extra = self.ledger_path.with_name(self.ledger_path.name + ".revisions") / "unreferenced.json"
        extra.write_text("{}", encoding="utf-8")
        report = validate_acceptance_ledger(self.record_path, self.ledger_path)
        self.assertFalse(report["valid"])
        self.assertIn("ACCEPTANCE_LEDGER_INVALID", {item["code"] for item in report["issues"]})
        self.assertIn("unreferenced", report["issues"][0]["message"])

    def test_final_decision_cannot_smuggle_unreviewed_root_fields(self):
        self.record["unreviewed_metadata"] = {"note": "must not enter event history"}
        self.record["final_assessment"].update({
            "decision": "FAIL", "assessed_by": "synthetic-reviewer",
            "assessed_at": "2026-11-08T03:00:00Z",
            "rationale": "Synthetic final review.",
        })
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside the permitted review state"):
            record_acceptance_revision(
                self.record_path, self.ledger_path, "synthetic-reviewer",
                "Attempted to combine a decision with an unrelated root edit.",
            )

    def test_stage_revision_cannot_smuggle_unreviewed_root_fields(self):
        stage = self.record["stages"][0]
        stage.update({
            "status": "BLOCKED", "blocker_reason": "Synthetic blocker.",
            "reviewed_by": "synthetic-reviewer", "reviewed_at": "2026-11-08T03:10:00Z",
            "review_rationale": "Synthetic blocker review.",
        })
        self.record["unreviewed_metadata"] = "not an acceptance review field"
        self.record_path.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside the permitted review state"):
            record_acceptance_revision(
                self.record_path, self.ledger_path, "synthetic-reviewer",
                "Attempted to combine a stage review with an unrelated root edit.",
            )

    def test_interrupted_record_replacement_recovers_latest_committed_snapshot(self):
        draft = json.loads(self.record_path.read_text(encoding="utf-8"))
        draft["stages"][0]["status"] = "IN_PROGRESS"
        self.record_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        from dor import acceptance_ledger
        with patch.object(acceptance_ledger, "_atomic_write", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Synthetic interruption after event commit.",
                )
        self.assertFalse(validate_acceptance_ledger(self.record_path, self.ledger_path)["valid"])
        result = recover_acceptance_record(self.record_path, self.ledger_path)
        self.assertTrue(result["recovered"])
        self.assertTrue(validate_acceptance_ledger(self.record_path, self.ledger_path)["valid"])

    def test_concurrent_acceptance_revisions_serialize_without_lost_updates(self):
        draft = json.loads(self.record_path.read_text(encoding="utf-8"))
        draft["stages"][0]["status"] = "IN_PROGRESS"
        self.record_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        def revise():
            try:
                return record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Concurrent synthetic revision attempt.",
                )
            except ValueError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: revise(), range(2)))
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        self.assertTrue(validate_acceptance_ledger(self.record_path, self.ledger_path)["valid"])

    def test_failed_event_append_rolls_back_uncommitted_snapshot(self):
        draft = json.loads(self.record_path.read_text(encoding="utf-8"))
        draft["stages"][0]["status"] = "IN_PROGRESS"
        self.record_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        from dor import acceptance_ledger
        revision_dir = self.ledger_path.with_name(self.ledger_path.name + ".revisions")
        before = set(revision_dir.iterdir())
        original = acceptance_ledger._canonical_json
        calls = {"count": 0}
        def fail_during_ledger_write(payload):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated append failure")
            return original(payload)
        with patch.object(acceptance_ledger, "_canonical_json", side_effect=fail_during_ledger_write):
            with self.assertRaises(OSError):
                record_acceptance_revision(
                    self.record_path, self.ledger_path, "synthetic-reviewer",
                    "Synthetic failed append.",
                )
        self.assertEqual(set(revision_dir.iterdir()), before)
        self.assertTrue(validate_acceptance_ledger(self.record_path, self.ledger_path)["valid"])

    def test_recovery_cleans_uncommitted_snapshot_and_truncated_jsonl_tail(self):
        revision_dir = self.ledger_path.with_name(self.ledger_path.name + ".revisions")
        events = self.ledger_path.read_text(encoding="utf-8").splitlines()
        next_name = f"revision-{len(events) + 1:06d}.json"
        (revision_dir / next_name).write_bytes(b'{"partial":')
        (revision_dir / (next_name + ".tmp")).write_bytes(b'{"temporary":')
        with self.ledger_path.open("ab") as handle:
            handle.write(b'{"partial":')
        result = recover_acceptance_record(self.record_path, self.ledger_path)
        self.assertFalse(result["recovered"])
        self.assertFalse((revision_dir / next_name).exists())
        self.assertFalse((revision_dir / (next_name + ".tmp")).exists())
        self.assertTrue(self.ledger_path.read_bytes().endswith(b"\n"))
        self.assertTrue(validate_acceptance_ledger(self.record_path, self.ledger_path)["valid"])

    def test_acceptance_ledger_event_tampering_is_detected(self):
        lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[0])
        event["rationale"] = "Tampered history."
        lines[0] = json.dumps(event)
        self.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = validate_acceptance_ledger(self.record_path, self.ledger_path)
        self.assertFalse(report["valid"])
        self.assertIn("ACCEPTANCE_LEDGER_INVALID", {item["code"] for item in report["issues"]})

    def test_init_acceptance_ledger_cli(self):
        copied_record = self.root / "copy_acceptance.json"
        copied_record.write_text(self.record_path.read_text(encoding="utf-8"), encoding="utf-8")
        copied_ledger = self.root / "copy_acceptance_events.jsonl"
        args = [
            "dor", "init-acceptance-ledger", "--record", str(copied_record),
            "--ledger", str(copied_ledger), "--actor", "synthetic-reviewer",
            "--rationale", "Initialize a copied synthetic acceptance record.",
        ]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            code = main()
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertTrue(validate_acceptance_ledger(copied_record, copied_ledger)["valid"])

    def test_terminal_stage_review_requires_reviewer_metadata_in_schema(self):
        stage_schema = __import__("json").loads(
            (Path(__file__).parents[2] / "schemas" / "v1_acceptance_record.schema.json").read_text(encoding="utf-8")
        )
        item_schema = stage_schema["properties"]["stages"]["items"]
        required = {
            key for condition in item_schema["allOf"]
            if condition.get("if", {}).get("properties", {}).get("status", {}).get("enum")
            for key in condition.get("then", {}).get("required", [])
        }
        self.assertTrue({"reviewed_by", "reviewed_at", "review_rationale"}.issubset(required))

if __name__ == "__main__":
    unittest.main()
