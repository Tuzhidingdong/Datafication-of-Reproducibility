from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from dor.audit import run_audit
from dor.builder import build_canonical_files
from dor.canonical import validate_canonical_bundle
from dor.cohort import build_modeling_cohort_files
from dor.cli import build_parser
from dor.interactions import discover_interactions_files
from dor.mapping import sha256_file, validate_mapping_files
from dor.mechanism_bridge import build_mechanism_evidence_bridge_files
from dor.modeling import run_baseline_models_files
from dor.publication import audit_publication_package_files, build_publication_package_files
from dor.reconciliation import reconcile_bundle_file
from dor.reproducibility import evaluate_reproducibility_files
from dor.response_surface import generate_interaction_surface_files
from dor.robustness import assess_interaction_robustness_files
from dor.virtual_reproduction import predict_virtual_condition_files


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class EndToEndSyntheticProjectTests(unittest.TestCase):
    """A complete synthetic CSV/JSON -> canonical -> analysis -> publication path."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dor-e2e-")
        cls.root = Path(cls.temp.name)
        cls.source_root = cls.root / "sources"
        cls.source_root.mkdir()

        cls.csv_path = cls.source_root / "experiment_records.csv"
        cls.json_path = cls.source_root / "extractions.json"
        cls.audit_dir = cls.root / "01_audit"
        cls.plan_path = cls.root / "mapping_plan.json"
        cls.spec_path = cls.root / "canonical_build_spec.json"
        cls.canonical_dir = cls.root / "02_canonical"
        cls.bundle_path = cls.canonical_dir / "canonical_bundle.json"
        cls.reconciliation_dir = cls.root / "03_reconciliation"
        cls.task_path = cls.root / "modeling_task.json"
        cls.cohort_dir = cls.root / "04_modeling" / "cohort"
        cls.model_dir = cls.root / "04_modeling" / "baseline_run"
        cls.evaluation_dir = cls.root / "04_modeling" / "reproducibility"
        cls.interaction_dir = cls.root / "04_modeling" / "interactions"
        cls.robustness_dir = cls.root / "04_modeling" / "interaction_robustness"
        cls.surface_dir = cls.root / "04_modeling" / "interaction_surface"
        cls.mechanism_plan_path = cls.root / "mechanism_plan.json"
        cls.mechanism_dir = cls.root / "05_mechanisms" / "bridge"
        cls.query_path = cls.root / "virtual_reproduction_query.json"
        cls.prediction_path = cls.root / "06_publication" / "virtual_prediction.json"
        cls.package_plan_path = cls.root / "publication_package_plan.json"
        cls.package_dir = cls.root / "06_publication" / "package"
        cls.package_audit_path = cls.root / "06_publication" / "package_integrity_report.json"

        cls._create_sources()
        cls._audit_sources()
        cls._create_mapping_and_build_spec()
        cls._build_canonical_bundle()
        cls._build_reconciliation_and_modeling()
        cls._run_interaction_and_evidence_stages()
        cls._run_virtual_prediction()
        cls._build_and_audit_publication_package()

        cls.protected_source_paths = [
            cls.csv_path, cls.json_path,
            cls.audit_dir / "source_inventory.json",
            cls.plan_path, cls.spec_path, cls.task_path,
            cls.mechanism_plan_path, cls.query_path,
        ]
        cls.source_bytes_after_build = {
            item: item.read_bytes() for item in cls.protected_source_paths
        }
        cls.bundle_integrity = validate_canonical_bundle(
            json.loads(cls.bundle_path.read_text(encoding="utf-8"))
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def _create_sources(cls):
        columns = [
            "DOI", "Title", "SystemKey", "SystemType", "ExperimentKey",
            "TargetID", "EndpointDefinition", "OutcomeValue", "OutcomeUnit",
            "ValueState", "EvidenceRef",
        ]
        experiments = []
        evidence_records = []
        coordinates = [(-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)]
        for study_number in range(1, 9):
            study_id = "ST" + str(study_number)
            doi = "10.8000/synthetic." + str(study_number)
            evidence_key = "EV_DIRECT_" + study_id
            for experiment_number, (x_value, z_value) in enumerate(coordinates, start=1):
                experiments.append([
                    doi, "Synthetic Study " + study_id, "CELL1", "zinc test cell",
                    study_id + "_EX" + str(experiment_number),
                    "TARGET_INTERACTION", "synthetic endpoint x-by-z",
                    str(x_value * z_value), "a.u.", "REPORTED", evidence_key,
                ])
            relationship = (
                "A measured process observable changed with the condition."
                if study_number != 2
                else "The predicted process change was not observed in this Study."
            )
            evidence_records.append({
                "source_evidence_key": evidence_key,
                "doi_ref": doi,
                "evidence_type": "direct_quote",
                "quoted_text": relationship,
                "extraction_status": "VERIFIED",
            })

        # This prospective probe is retained in the canonical bundle but excluded
        # from the interaction task by its exact target and endpoint definition.
        probe_doi = "10.8000/synthetic.probe"
        experiments.append([
            probe_doi, "Independent Synthetic Probe", "CELL_PROBE", "probe cell",
            "PROBE_EX1", "TARGET_MECHANISM_PROBE",
            "independent mechanism probe", "1.0", "a.u.", "REPORTED",
            "EV_PROSPECTIVE_ST9",
        ])
        evidence_records.extend([
            {
                "source_evidence_key": "EV_THEORY_ST3",
                "doi_ref": "10.8000/synthetic.3",
                "evidence_type": "method_description",
                "quoted_text": "A theoretical calculation supports the proposed intermediate.",
                "extraction_status": "VERIFIED",
            },
            {
                "source_evidence_key": "EV_PROSPECTIVE_ST9",
                "doi_ref": probe_doi,
                "evidence_type": "table_value",
                "quoted_text": "An independent prospective probe supports the predicted process.",
                "extraction_status": "VERIFIED",
            },
        ])

        with cls.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(experiments)

        conditions = []
        for row in experiments:
            doi, _title, system_key, _system_type, experiment_key = row[:5]
            probe = row[5] == "TARGET_MECHANISM_PROBE"
            x_value = 0.0 if probe else float(row[7])  # The interaction target is x*z.
            # The four design coordinates are recovered from the experiment suffix.
            if not probe:
                index = int(experiment_key.rsplit("EX", 1)[1]) - 1
                x_value, z_value = coordinates[index]
            else:
                z_value = 0.0
            for condition_type, value, unit in (
                ("temperature", x_value, "arb-x"),
                ("pressure", z_value, "arb-z"),
            ):
                conditions.append({
                    "experiment_ref": experiment_key,
                    "system_ref": system_key,
                    "condition_type": condition_type,
                    "raw_value": value,
                    "raw_unit": unit,
                    "normalized_value": value,
                    "normalized_unit": unit,
                    "value_state": "REPORTED",
                })

        write_json(cls.json_path, {
            "conditions": conditions,
            "evidence": evidence_records,
        })

    @classmethod
    def _audit_sources(cls):
        cls.raw_source_hashes = {
            cls.csv_path.name: sha256_file(cls.csv_path),
            cls.json_path.name: sha256_file(cls.json_path),
        }
        manifest = run_audit(cls.csv_path, cls.json_path, cls.audit_dir)
        cls.assert_audit = manifest
        inventory = json.loads(
            (cls.audit_dir / "source_inventory.json").read_text(encoding="utf-8")
        )
        cls.inventory_items = inventory["items"]
        cls.inventory_by_locator = {
            (item["source_file"], item["source_format"], item["locator"]): item["inventory_id"]
            for item in cls.inventory_items
        }
        if not cls.inventory_items:
            raise AssertionError("The structural audit produced an empty source inventory.")

    @classmethod
    def _source_id(cls, source_file: str, source_format: str, locator: str) -> str:
        key = (source_file, source_format, locator)
        if key not in cls.inventory_by_locator:
            raise AssertionError("Audit inventory does not contain declared source locator: " + repr(key))
        return cls.inventory_by_locator[key]

    @classmethod
    def _create_mapping_and_build_spec(cls):
        inventory_path = cls.audit_dir / "source_inventory.json"
        inventory_hash = sha256_file(inventory_path)
        rules = []
        rule_ids = {}

        def add_rule(name, source_file, source_format, locator,
                     entity, field, transform="IDENTITY"):
            rule_id = "MAP_" + name.upper()
            source_item_id = cls._source_id(source_file, source_format, locator)
            rules.append({
                "mapping_rule_id": rule_id,
                "source_item_id": source_item_id,
                "target_entity": entity,
                "target_field_id": field,
                "status": "APPROVED",
                "transformation": {"type": transform, "parameters": {}},
                "review": {
                    "reviewer": "synthetic integration fixture",
                    "reviewed_at": "2026-11-08",
                    "decision_note": "Explicitly defined for deterministic end-to-end software acceptance.",
                },
            })
            rule_ids[name] = rule_id
            return rule_id

        csv_file = cls.csv_path.name
        json_file = cls.json_path.name
        csv_fields = {
            "doi": ("DOI", "studies", "doi", "IDENTITY"),
            "title": ("Title", "studies", "title", "IDENTITY"),
            "system_key": ("SystemKey", "systems", "source_system_key", "IDENTITY"),
            "system_type": ("SystemType", "systems", "system_type", "IDENTITY"),
            "experiment_key": ("ExperimentKey", "experiments", "source_experiment_key", "IDENTITY"),
            "obs_experiment_ref": ("ExperimentKey", "observations", "experiment_ref", "IDENTITY"),
            "target": ("TargetID", "observations", "target_id", "IDENTITY"),
            "endpoint": ("EndpointDefinition", "observations", "endpoint_definition", "IDENTITY"),
            "outcome_raw": ("OutcomeValue", "observations", "raw_value", "NUMERIC_PARSE"),
            "outcome_norm": ("OutcomeValue", "observations", "normalized_value", "NUMERIC_PARSE"),
            "outcome_raw_unit": ("OutcomeUnit", "observations", "raw_unit", "IDENTITY"),
            "outcome_norm_unit": ("OutcomeUnit", "observations", "normalized_unit", "IDENTITY"),
            "obs_state": ("ValueState", "observations", "value_state", "IDENTITY"),
            "obs_evidence_ref": ("EvidenceRef", "observations", "evidence_ref", "IDENTITY"),
        }
        for name, (column, entity, field, transform) in csv_fields.items():
            add_rule(name, csv_file, "csv", column, entity, field, transform)

        json_fields = {
            "condition_experiment_ref": ("$['conditions'][]['experiment_ref']", "conditions", "experiment_ref", "IDENTITY"),
            "condition_system_ref": ("$['conditions'][]['system_ref']", "conditions", "system_ref", "IDENTITY"),
            "condition_type": ("$['conditions'][]['condition_type']", "conditions", "condition_type", "IDENTITY"),
            "condition_raw": ("$['conditions'][]['raw_value']", "conditions", "raw_value", "NUMERIC_PARSE"),
            "condition_raw_unit": ("$['conditions'][]['raw_unit']", "conditions", "raw_unit", "IDENTITY"),
            "condition_norm": ("$['conditions'][]['normalized_value']", "conditions", "normalized_value", "NUMERIC_PARSE"),
            "condition_norm_unit": ("$['conditions'][]['normalized_unit']", "conditions", "normalized_unit", "IDENTITY"),
            "condition_state": ("$['conditions'][]['value_state']", "conditions", "value_state", "IDENTITY"),
            "evidence_key": ("$['evidence'][]['source_evidence_key']", "evidence", "source_evidence_key", "IDENTITY"),
            "evidence_doi": ("$['evidence'][]['doi_ref']", "evidence", "doi_ref", "IDENTITY"),
            "evidence_type": ("$['evidence'][]['evidence_type']", "evidence", "evidence_type", "IDENTITY"),
            "evidence_quote": ("$['evidence'][]['quoted_text']", "evidence", "quoted_text", "IDENTITY"),
            "evidence_status": ("$['evidence'][]['extraction_status']", "evidence", "extraction_status", "IDENTITY"),
        }
        for name, (locator, entity, field, transform) in json_fields.items():
            add_rule(name, json_file, "json", locator, entity, field, transform)

        mapping_plan = {
            "schema_version": "1.0",
            "mapping_version": "synthetic-e2e-map-1",
            "source_inventory_sha256": inventory_hash,
            "rules": rules,
        }
        write_json(cls.plan_path, mapping_plan)
        mapping_hash = sha256_file(cls.plan_path)

        definitions = [
            {
                "definition_id": "D_STUDY", "entity_type": "studies",
                "source_file": csv_file,
                "grouping": {"mode": "GROUP_BY_FIELDS", "source_item_ids": [
                    cls._source_id(csv_file, "csv", "DOI")
                ]},
                "field_rule_ids": [rule_ids["doi"], rule_ids["title"]],
            },
            {
                "definition_id": "D_SYSTEM", "entity_type": "systems",
                "source_file": csv_file,
                "grouping": {"mode": "GROUP_BY_FIELDS", "source_item_ids": [
                    cls._source_id(csv_file, "csv", "DOI"),
                    cls._source_id(csv_file, "csv", "SystemKey"),
                ]},
                "field_rule_ids": [rule_ids["system_key"], rule_ids["system_type"]],
            },
            {
                "definition_id": "D_EXPERIMENT", "entity_type": "experiments",
                "source_file": csv_file,
                "grouping": {"mode": "GROUP_BY_FIELDS", "source_item_ids": [
                    cls._source_id(csv_file, "csv", "ExperimentKey")
                ]},
                "field_rule_ids": [rule_ids["experiment_key"]],
            },
            {
                "definition_id": "D_OBSERVATION", "entity_type": "observations",
                "source_file": csv_file,
                "grouping": {"mode": "GROUP_BY_FIELDS", "source_item_ids": [
                    cls._source_id(csv_file, "csv", "ExperimentKey"),
                    cls._source_id(csv_file, "csv", "TargetID"),
                ]},
                "field_rule_ids": [
                    rule_ids["obs_experiment_ref"], rule_ids["target"],
                    rule_ids["endpoint"], rule_ids["outcome_raw"],
                    rule_ids["outcome_raw_unit"], rule_ids["outcome_norm"],
                    rule_ids["outcome_norm_unit"], rule_ids["obs_state"],
                    rule_ids["obs_evidence_ref"],
                ],
            },
            {
                "definition_id": "D_CONDITION", "entity_type": "conditions",
                "source_file": json_file, "source_format": "json",
                "record_selector": "/conditions/*",
                "grouping": {"mode": "SOURCE_ROW", "source_item_ids": []},
                "field_rule_ids": [
                    rule_ids["condition_experiment_ref"], rule_ids["condition_system_ref"],
                    rule_ids["condition_type"], rule_ids["condition_raw"],
                    rule_ids["condition_raw_unit"], rule_ids["condition_norm"],
                    rule_ids["condition_norm_unit"], rule_ids["condition_state"],
                ],
            },
            {
                "definition_id": "D_EVIDENCE", "entity_type": "evidence",
                "source_file": json_file, "source_format": "json",
                "record_selector": "/evidence/*",
                "grouping": {"mode": "SOURCE_ROW", "source_item_ids": []},
                "field_rule_ids": [
                    rule_ids["evidence_key"], rule_ids["evidence_doi"],
                    rule_ids["evidence_type"], rule_ids["evidence_quote"],
                    rule_ids["evidence_status"],
                ],
            },
        ]
        links = [
            {"child_definition_id": "D_SYSTEM", "parent_definition_id": "D_STUDY", "field_id": "study_ids"},
            {"child_definition_id": "D_EXPERIMENT", "parent_definition_id": "D_STUDY", "field_id": "study_id"},
            {"child_definition_id": "D_EXPERIMENT", "parent_definition_id": "D_SYSTEM", "field_id": "system_id"},
            {
                "child_definition_id": "D_CONDITION", "parent_definition_id": "D_SYSTEM",
                "field_id": "system_ids", "match_mode": "FIELD_EQUALITY",
                "child_key_field": "system_ref", "parent_key_field": "source_system_key",
            },
            {
                "child_definition_id": "D_EXPERIMENT", "parent_definition_id": "D_CONDITION",
                "field_id": "condition_ids", "match_mode": "FIELD_EQUALITY",
                "child_key_field": "source_experiment_key", "parent_key_field": "experiment_ref",
            },
            {"child_definition_id": "D_OBSERVATION", "parent_definition_id": "D_EXPERIMENT", "field_id": "experiment_id"},
            {
                "child_definition_id": "D_OBSERVATION", "parent_definition_id": "D_EVIDENCE",
                "field_id": "evidence_ids", "match_mode": "FIELD_EQUALITY",
                "child_key_field": "evidence_ref", "parent_key_field": "source_evidence_key",
            },
            {
                "child_definition_id": "D_EVIDENCE", "parent_definition_id": "D_STUDY",
                "field_id": "study_id", "match_mode": "FIELD_EQUALITY",
                "child_key_field": "doi_ref", "parent_key_field": "doi",
            },
        ]
        write_json(cls.spec_path, {
            "schema_version": "1.0",
            "project_id": "SYNTHETIC_E2E_PROJECT",
            "mapping_version": "synthetic-e2e-map-1",
            "mapping_plan_sha256": mapping_hash,
            "source_inventory_sha256": inventory_hash,
            "entity_definitions": definitions,
            "links": links,
        })

        mapping_validation = validate_mapping_files(cls.plan_path, inventory_path)
        if not mapping_validation["valid"]:
            raise AssertionError("Synthetic mapping plan failed validation: " + repr(mapping_validation["errors"]))
        cls.mapping_validation = mapping_validation

    @classmethod
    def _build_canonical_bundle(cls):
        bundle, report = build_canonical_files(
            cls.plan_path, cls.audit_dir / "source_inventory.json",
            cls.spec_path, cls.source_root,
        )
        if bundle is None or not report.get("valid"):
            raise AssertionError("Canonical build failed: " + repr(report.get("errors")))
        integrity = validate_canonical_bundle(bundle)
        if not integrity["valid"]:
            raise AssertionError("Canonical bundle failed integrity: " + repr(integrity["errors"]))
        cls.bundle = bundle
        cls.canonical_report = report
        cls.canonical_dir.mkdir(parents=True, exist_ok=True)
        write_json(cls.bundle_path, bundle)
        write_json(cls.canonical_dir / "canonical_build_report.json", report)
        cls.canonical_hash = sha256_file(cls.bundle_path)

    @classmethod
    def _build_reconciliation_and_modeling(cls):
        cls.reconciliation = reconcile_bundle_file(cls.bundle_path, cls.reconciliation_dir)
        task = {
            "schema_version": "1.0",
            "task_id": "SYNTHETIC_INTERACTION_TASK",
            "target_id": "TARGET_INTERACTION",
            "endpoint_definition": "synthetic endpoint x-by-z",
            "outcome_type": "NUMERIC",
            "outcome_value_field": "normalized_value",
            "outcome_unit": "a.u.",
            "feature_bindings": [
                {
                    "feature_id": "temperature", "condition_type": "temperature",
                    "value_field": "normalized_value", "value_type": "NUMERIC",
                    "expected_unit": "arb-x",
                },
                {
                    "feature_id": "pressure", "condition_type": "pressure",
                    "value_field": "normalized_value", "value_type": "NUMERIC",
                    "expected_unit": "arb-z",
                },
            ],
            "split": {
                "strategy": "GROUPED_HOLDOUT", "seed": 42,
                "fractions": {"train": 0.5, "validation": 0.25, "test": 0.25},
            },
            "modeling": {"ridge_alphas": [0.001, 0.01, 0.1, 1.0, 10.0]},
            "interaction_discovery": {
                "minimum_joint_observations": 24,
                "minimum_joint_studies": 8,
                "minimum_positive_fold_fraction": 0.6,
                "maximum_feature_pairs": 4,
                "maximum_interaction_columns": 100,
            },
            "interaction_surface": {
                "grid_size": 9, "background_max_observations": 100,
                "range_quantiles": [0.0, 1.0],
                "support_distance_quantile": 0.95,
            },
        }
        write_json(cls.task_path, task)
        cls.task = task
        cohort = build_modeling_cohort_files(cls.bundle_path, cls.task_path, cls.cohort_dir)
        if not cohort["valid"]:
            raise AssertionError("Cohort build failed: " + repr(cohort["report"].get("errors")))
        cls.cohort_result = cohort
        cls.model_result = run_baseline_models_files(cls.cohort_dir, cls.task_path, cls.model_dir)
        cls.evaluation_result = evaluate_reproducibility_files(
            cls.cohort_dir, cls.task_path, cls.evaluation_dir, folds=4, seed=31
        )

    @classmethod
    def _run_interaction_and_evidence_stages(cls):
        cls.interaction_result = discover_interactions_files(
            cls.cohort_dir, cls.task_path, cls.interaction_dir, folds=4, seed=19
        )
        report = cls.interaction_result["report"]
        candidates = [
            item for item in report["interaction_catalogue"]
            if item["interpretation_status"] == "CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE"
        ]
        if len(candidates) != 1:
            raise AssertionError("Expected one synthetic bilinear interaction candidate, got: " + repr(report["interaction_catalogue"]))
        cls.interaction_id = candidates[0]["interaction_id"]
        cls.robustness_result = assess_interaction_robustness_files(
            cls.cohort_dir, cls.task_path, cls.robustness_dir,
            seeds=[11, 19, 23], folds=4, minimum_candidate_run_fraction=0.6,
        )
        cls.surface_result = generate_interaction_surface_files(
            cls.cohort_dir, cls.task_path, cls.interaction_dir,
            cls.interaction_id, cls.surface_dir, robustness_dir=cls.robustness_dir,
        )

        evidence_by_key = {
            record["source_evidence_key"]: record
            for record in cls.bundle["evidence"]
        }
        observation_by_evidence = {}
        for observation in cls.bundle["observations"]:
            for evidence_id in observation["evidence_ids"]:
                observation_by_evidence[evidence_id] = observation

        direct = evidence_by_key["EV_DIRECT_ST1"]
        contradictory = evidence_by_key["EV_DIRECT_ST2"]
        theoretical = evidence_by_key["EV_THEORY_ST3"]
        prospective = evidence_by_key["EV_PROSPECTIVE_ST9"]
        cls.direct_observation = observation_by_evidence[direct["evidence_id"]]
        cls.contradictory_observation = observation_by_evidence[contradictory["evidence_id"]]
        cls.prospective_observation = observation_by_evidence[prospective["evidence_id"]]

        plan = {
            "schema_version": "1.0",
            "plan_id": "SYNTHETIC_MECHANISM_PLAN",
            "task_id": cls.task["task_id"],
            "target_id": cls.task["target_id"],
            "endpoint_definition": cls.task["endpoint_definition"],
            "interaction_id": cls.interaction_id,
            "prepared_by": "synthetic integration reviewer",
            "proposal_origin": "USER_DRAFT",
            "notes": "Deterministic synthetic integration test; not a scientific claim.",
            "mechanism_hypotheses": [{
                "hypothesis_id": "SYNTHETIC_HYPOTHESIS_1",
                "title": "Synthetic condition interaction hypothesis",
                "hypothesis_statement": "The joint condition pattern changes the synthetic endpoint response.",
                "proposed_process_chain": [
                    "The first synthetic condition changes a putative process.",
                    "The second synthetic condition modifies the response to the first.",
                ],
                "scope_statement": "Only the synthetic observations and endpoint in this test fixture.",
                "predicted_observations": ["A direct process observable changes.", "An independent probe supports the proposed process."],
                "alternative_explanations": ["A study-level protocol difference."],
                "unresolved_variables": ["No physical chemistry is represented by the fixture."],
                "evidence_assessments": [
                    {
                        "evidence_id": direct["evidence_id"], "relationship": "SUPPORTS",
                        "evidence_class": "DIRECT_OBSERVATION",
                        "interpretation_summary": "A verified synthetic direct observation supports the proposed relationship.",
                        "observation_ids": [cls.direct_observation["observation_id"]],
                    },
                    {
                        "evidence_id": contradictory["evidence_id"], "relationship": "CONTRADICTS",
                        "evidence_class": "DIRECT_OBSERVATION",
                        "interpretation_summary": "A second synthetic Study records counterevidence.",
                        "observation_ids": [cls.contradictory_observation["observation_id"]],
                    },
                    {
                        "evidence_id": theoretical["evidence_id"], "relationship": "SUPPORTS",
                        "evidence_class": "THEORETICAL_SUPPORT",
                        "interpretation_summary": "A verified synthetic theory record is linked for interface coverage.",
                    },
                    {
                        "evidence_id": prospective["evidence_id"], "relationship": "SUPPORTS",
                        "evidence_class": "PROSPECTIVE_VALIDATION",
                        "interpretation_summary": "A separate Study supplies an independent synthetic probe.",
                        "observation_ids": [cls.prospective_observation["observation_id"]],
                    },
                ],
            }],
        }
        write_json(cls.mechanism_plan_path, plan)
        cls.mechanism_result = build_mechanism_evidence_bridge_files(
            cls.bundle_path, cls.cohort_dir, cls.task_path, cls.interaction_dir,
            cls.mechanism_plan_path, cls.mechanism_dir,
            robustness_dir=cls.robustness_dir,
            response_surface_dir=cls.surface_dir,
        )

    @classmethod
    def _run_virtual_prediction(cls):
        write_json(cls.query_path, {
            "schema_version": "1.0",
            "task_id": cls.task["task_id"],
            "target_id": cls.task["target_id"],
            "endpoint_definition": cls.task["endpoint_definition"],
            "features": {
                "temperature": {"value": 0.25, "unit": "arb-x"},
                "pressure": {"value": -0.5, "unit": "arb-z"},
            },
        })
        cls.prediction_result = predict_virtual_condition_files(
            cls.model_dir, cls.query_path, cls.prediction_path
        )

    @classmethod
    def _build_and_audit_publication_package(cls):
        artifacts = [
            ("AUDIT_MANIFEST", "provenance/dataset_manifest.json", "01_audit/dataset_manifest.json", "dataset_manifest", "complete"),
            ("SOURCE_INVENTORY", "provenance/source_inventory.json", "01_audit/source_inventory.json", "source_inventory", "complete"),
            ("CANONICAL_BUNDLE", "data/canonical_bundle.json", "02_canonical/canonical_bundle.json", "canonical_bundle", "complete"),
            ("RECONCILIATION", "data/reconciliation_report.json", "03_reconciliation/reconciliation_report.json", "reconciliation_report", "complete"),
            ("TASK", "modeling/modeling_task.json", "modeling_task.json", "modeling_task", "complete"),
            ("COHORT_REPORT", "modeling/cohort_report.json", "04_modeling/cohort/cohort_report.json", "modeling_cohort_report", "complete"),
            ("MODEL_REPORT", "modeling/model_report.json", "04_modeling/baseline_run/model_report.json", "model_report", "complete"),
            ("MODEL_ARTIFACT", "modeling/model_artifact.json", "04_modeling/baseline_run/model_artifact.json", "model_artifact", "complete"),
            ("REPRODUCIBILITY", "validation/reproducibility_evaluation.json", "04_modeling/reproducibility/reproducibility_evaluation.json", "reproducibility_evaluation", "complete"),
            ("INTERACTIONS", "interactions/interaction_discovery_report.json", "04_modeling/interactions/interaction_discovery_report.json", "interaction_discovery_report", "complete"),
            ("ROBUSTNESS", "interactions/interaction_robustness_report.json", "04_modeling/interaction_robustness/interaction_robustness_report.json", "interaction_robustness_report", "complete"),
            ("RESPONSE_SURFACE", "interactions/interaction_response_surface_report.json", "04_modeling/interaction_surface/interaction_response_surface_report.json", "interaction_response_surface_report", "complete"),
            ("MECHANISM_BRIDGE", "mechanisms/mechanism_evidence_bridge_report.json", "05_mechanisms/bridge/mechanism_evidence_bridge_report.json", "mechanism_evidence_bridge_report", "requires_review"),
            ("MECHANISM_LEDGER", "mechanisms/mechanism_evidence_ledger.csv", "05_mechanisms/bridge/mechanism_evidence_ledger.csv", "mechanism_evidence_ledger", "complete"),
            ("MECHANISM_REVIEW_QUEUE", "mechanisms/mechanism_review_queue.csv", "05_mechanisms/bridge/mechanism_review_queue.csv", "mechanism_review_queue", "complete"),
            ("MECHANISM_FINDINGS", "findings/mechanism_findings.json", "05_mechanisms/bridge/mechanism_findings.json", "research_findings", "requires_review"),
            ("VIRTUAL_PREDICTION", "predictions/virtual_prediction.json", "06_publication/virtual_prediction.json", "virtual_prediction", "complete"),
        ]
        plan_artifacts = []
        for artifact_id, destination, source, artifact_type, status in artifacts:
            source_path = cls.root / source
            if not source_path.is_file():
                raise AssertionError("Expected pipeline artifact is missing: " + source)
            plan_artifacts.append({
                "artifact_id": artifact_id,
                "path": destination,
                "source_path": source,
                "type": artifact_type,
                "description": "Synthetic end-to-end integration artifact: " + artifact_id,
                "status": status,
                "linked_record_ids": [],
                "manuscript_sections": ["Methods", "Results", "Supporting Information"],
            })
        write_json(cls.package_plan_path, {
            "schema_version": "1.0",
            "project_id": "SYNTHETIC_E2E_PROJECT",
            "run_id": "SYNTHETIC_E2E_RUN_001",
            "package_version": "0.6.0",
            "domain_profile": None,
            "writing_guide_source": None,
            "source_hashes": cls.raw_source_hashes,
            "artifacts": plan_artifacts + [{
                "artifact_id": "FIGURE_NOT_GENERATED",
                "path": "figures/figure_001/figure.svg",
                "type": "figure",
                "description": "No figure was generated in this synthetic acceptance fixture.",
                "status": "not_generated",
                "linked_record_ids": [],
                "manuscript_sections": ["Results"],
            }],
        })
        cls.package_result = build_publication_package_files(
            cls.package_plan_path, cls.root, cls.package_dir
        )
        cls.package_audit = audit_publication_package_files(cls.package_dir)
        write_json(cls.package_audit_path, cls.package_audit)

    def test_audit_inventory_and_cross_format_canonical_build_are_connected(self):
        self.assertEqual(self.assert_audit["audit_scope"], "READ_ONLY_STRUCTURAL_INSPECTION")
        self.assertGreater(len(self.inventory_items), 20)
        self.assertTrue(self.mapping_validation["valid"])
        self.assertTrue(self.bundle_integrity["valid"])
        self.assertEqual(len(self.bundle["studies"]), 9)
        self.assertEqual(len(self.bundle["systems"]), 9)
        self.assertEqual(len(self.bundle["experiments"]), 33)
        self.assertEqual(len(self.bundle["conditions"]), 66)
        self.assertEqual(len(self.bundle["observations"]), 33)
        self.assertEqual(len(self.bundle["evidence"]), 10)
        self.assertTrue(all(record["evidence_ids"] for record in self.bundle["observations"]))
        evidence_ids = {item["evidence_id"] for item in self.bundle["evidence"]}
        self.assertTrue(all(set(item["evidence_ids"]).issubset(evidence_ids) for item in self.bundle["observations"]))

    def test_endpoint_filter_and_study_grouping_survive_into_modeling(self):
        report = self.cohort_result["report"]
        self.assertEqual(report["eligible_study_count"], 8)
        self.assertEqual(report["eligible_observation_count"], 32)
        self.assertEqual(len(self.model_result["artifact"]["training_observation_ids"]) +
                         len(self.model_result["artifact"]["test_observation_ids"]), 32)
        self.assertEqual(self.evaluation_result["report"]["study_count"], 8)
        self.assertEqual(self.evaluation_result["report"]["fold_count"], 4)
        split = json.loads((self.cohort_dir / "split_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(split["leakage_check"]["study_overlap_count"], 0)
        cohort_rows = list(csv.DictReader((self.cohort_dir / "modeling_cohort.csv").open(encoding="utf-8")))
        self.assertTrue(all(row["target_id"] == "TARGET_INTERACTION" for row in cohort_rows))
        self.assertTrue(all(row["endpoint_definition"] == "synthetic endpoint x-by-z" for row in cohort_rows))

    def test_interaction_robustness_surface_and_mechanism_share_exact_provenance(self):
        interaction = self.interaction_result["report"]
        mechanism = self.mechanism_result["report"]
        self.assertEqual(interaction["task_id"], mechanism["task_id"])
        self.assertEqual(self.interaction_id, mechanism["interaction_id"])
        self.assertEqual(self.robustness_result["report"]["seed_count"], 3)
        self.assertEqual(self.surface_result["report"]["interaction_id"], self.interaction_id)
        self.assertEqual(mechanism["review_state"], "PENDING_USER_MECHANISM_REVIEW")
        finding = self.mechanism_result["findings"]["findings"][0]
        self.assertEqual(finding["claim_type"], "mechanism_hypothesis")
        self.assertEqual(finding["status"], "candidate")
        self.assertEqual(finding["mechanism_status"], "hypothesis")
        evidence_summary = mechanism["mechanism_catalogue"][0]["evidence_counts"]
        self.assertEqual(evidence_summary["direct_observation_support"], 1)
        self.assertEqual(evidence_summary["theoretical_support"], 1)
        self.assertEqual(evidence_summary["independent_prospective_support"], 1)
        self.assertIn(
            self.bundle_by_evidence_key("EV_DIRECT_ST2")["evidence_id"],
            mechanism["mechanism_catalogue"][0]["contradicting_evidence_ids"],
        )

    def bundle_by_evidence_key(self, key):
        return next(item for item in self.bundle["evidence"] if item.get("source_evidence_key") == key)

    def test_virtual_prediction_and_publication_package_preserve_claim_boundaries(self):
        prediction = self.prediction_result["report"]
        self.assertEqual(prediction["uncertainty_status"], "NOT_CALIBRATED")
        self.assertFalse(prediction["provenance"]["test_set_used_for_fit_or_selection"])
        self.assertIn("NOT_A_PHYSICAL_REPRODUCTION", " ".join(prediction["warnings"]))
        self.assertEqual(self.package_result["manifest"]["completeness"]["status"], "requires_review")
        self.assertTrue(self.package_audit["valid"], self.package_audit["errors"])
        manifest = json.loads((self.package_dir / "package_manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["status"] == "requires_review" for item in manifest["artifacts"]))
        self.assertTrue(any(item["status"] == "not_generated" for item in manifest["artifacts"]))
        self.assertTrue((self.package_dir / "README_FOR_WRITING_SKILL.md").is_file())
        self.assertTrue((self.package_dir / "predictions/virtual_prediction.json").is_file())

    def test_substituted_canonical_bundle_is_rejected_by_downstream_mechanism_bridge(self):
        substituted = copy.deepcopy(self.bundle)
        substituted["studies"][0]["title"] = "Modified after cohort construction"
        substituted_path = self.root / "substituted_canonical_bundle.json"
        write_json(substituted_path, substituted)
        with self.assertRaisesRegex(ValueError, "Canonical bundle hash does not match"):
            build_mechanism_evidence_bridge_files(
                substituted_path, self.cohort_dir, self.task_path, self.interaction_dir,
                self.mechanism_plan_path, self.root / "rejected_mechanism_output",
                robustness_dir=self.robustness_dir, response_surface_dir=self.surface_dir,
            )

    def test_all_original_input_and_approval_files_remain_unchanged(self):
        current = {path: path.read_bytes() for path in self.protected_source_paths}
        self.assertEqual(current, self.source_bytes_after_build)
        self.assertEqual(sha256_file(self.csv_path), self.raw_source_hashes[self.csv_path.name])
        self.assertEqual(sha256_file(self.json_path), self.raw_source_hashes[self.json_path.name])


    def test_cli_parser_exposes_each_pipeline_command(self):
        parser = build_parser()
        cases = [
            ["audit", "--csv", "input.csv", "--json", "input.json", "--out", "audit"],
            ["validate-mapping", "--plan", "mapping.json", "--inventory", "inventory.json"],
            ["build-canonical", "--plan", "mapping.json", "--inventory", "inventory.json",
             "--spec", "build.json", "--source-root", "sources", "--out-dir", "canonical"],
            ["validate-bundle", "--input", "canonical_bundle.json"],
            ["reconcile-bundle", "--input", "canonical_bundle.json", "--out-dir", "reconciliation"],
            ["build-cohort", "--bundle", "canonical_bundle.json", "--task", "task.json", "--out-dir", "cohort"],
            ["fit-baselines", "--cohort-dir", "cohort", "--task", "task.json", "--out-dir", "model"],
            ["evaluate-reproducibility", "--cohort-dir", "cohort", "--task", "task.json", "--out-dir", "evaluation"],
            ["discover-interactions", "--cohort-dir", "cohort", "--task", "task.json", "--out-dir", "interactions"],
            ["assess-interaction-robustness", "--cohort-dir", "cohort", "--task", "task.json", "--out-dir", "robustness"],
            ["generate-interaction-surface", "--cohort-dir", "cohort", "--task", "task.json",
             "--interaction-dir", "interactions", "--interaction-id", "INT_1", "--out-dir", "surface"],
            ["build-mechanism-evidence-bridge", "--bundle", "canonical_bundle.json", "--cohort-dir", "cohort",
             "--task", "task.json", "--interaction-dir", "interactions", "--plan", "mechanism.json",
             "--out-dir", "mechanism"],
            ["predict-virtual-condition", "--model-run-dir", "model", "--query", "query.json", "--out", "prediction.json"],
            ["build-publication-package", "--plan", "package_plan.json", "--workspace-root", ".", "--out-dir", "package"],
            ["audit-publication-package", "--package-dir", "package"],
        ]
        for arguments in cases:
            with self.subTest(command=arguments[0]):
                self.assertEqual(parser.parse_args(arguments).command, arguments[0])

    def test_z_package_audit_detects_downstream_tampering(self):
        copied = self.package_dir / "data/canonical_bundle.json"
        copied.write_text(copied.read_text(encoding="utf-8") + " ", encoding="utf-8")
        audit = audit_publication_package_files(self.package_dir)
        self.assertFalse(audit["valid"])
        self.assertTrue(any("SHA-256" in item for item in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
