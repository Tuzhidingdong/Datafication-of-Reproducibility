from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from dor.chem_literacy import _load_json_observations
from dor.conditions import (
    CONDITION_RULE_VERSION,
    EXCLUDED_TEST_BATCH_IDS,
    extract_observation_conditions,
    is_excluded_test_record,
    write_condition_outputs,
)


def observation(**updates):
    base = {
        "observation_id": "OBS1",
        "paper_id": "P1",
        "doi": "10.1/example",
        "reconciliation_id": "R1",
        "feature_id": "FEAT_LIFE_SYM",
        "batch_id": "BATCH_NORMAL",
        "target_system": "Zn||Zn, 2 M ZnSO4 + 0.1 M MnSO4, 1% TAC",
        "measurement_conditions": {},
        "worker_a_evidence": {},
        "worker_b_evidence": {},
    }
    base.update(updates)
    return base


class ConditionExtractionTests(unittest.TestCase):
    def test_extracts_cell_configuration_and_multiple_salt_concentrations(self):
        rows = extract_observation_conditions(observation())
        values = {(x["condition_type"], x["normalized_value"]) for x in rows}
        self.assertIn(("cell_configuration", "Zn||Zn"), values)
        self.assertIn(("salt_concentration", "ZnSO4|2 M"), values)
        self.assertIn(("salt_concentration", "MnSO4|0.1 M"), values)

    def test_percentage_basis_is_never_inferred(self):
        rows = extract_observation_conditions(observation())
        additive = next(x for x in rows if x["condition_type"] == "percentage_modifier")
        self.assertEqual(additive["normalized_value"], "1% TAC")
        self.assertEqual(additive["unit_basis"], "UNSPECIFIED_PERCENT_BASIS")
        self.assertEqual(additive["target_system_raw"], "Zn||Zn, 2 M ZnSO4 + 0.1 M MnSO4, 1% TAC")

    def test_preserves_abbreviation_without_expansion(self):
        rows = extract_observation_conditions(observation(target_system="Zn||Zn, 1% TAC"))
        additive = next(x for x in rows if x["condition_type"] == "percentage_modifier")
        self.assertEqual(additive["normalized_value"], "1% TAC")

    def test_extracts_cell_classes_and_material(self):
        rows = extract_observation_conditions(observation(
            target_system="Zn-MnO2 full cell with bare Zn anode"
        ))
        values = {(x["condition_type"], x["normalized_value"]) for x in rows}
        self.assertIn(("cell_configuration_class", "FULL_CELL"), values)
        self.assertIn(("cell_chemistry", "Zn-MnO2"), values)
        self.assertIn(("electrode_or_substrate_material", "bare Zn anode"), values)
        materials = [x["normalized_value"] for x in rows if x["condition_type"] == "electrode_or_substrate_material"]
        self.assertEqual(materials, ["bare Zn anode"])

    def test_dft_context_is_not_classified_as_battery_cell(self):
        rows = extract_observation_conditions(observation(target_system="1% TAC-Zn2+ (DFT)"))
        self.assertIn(("system_domain", "COMPUTATIONAL_MODEL"),
                      {(x["condition_type"], x["normalized_value"]) for x in rows})
        self.assertFalse(any(x["condition_type"] == "cell_configuration" for x in rows))

    def test_surface_and_wetting_context_is_detected(self):
        rows = extract_observation_conditions(observation(
            target_system="0.5% TAC substrate, water droplet"
        ))
        self.assertIn(("system_domain", "SURFACE_OR_WETTING_TEST"),
                      {(x["condition_type"], x["normalized_value"]) for x in rows})

    def test_missing_target_system_does_not_generate_fake_condition(self):
        for value in ("N/A", "not reported", "-", ""):
            self.assertEqual(extract_observation_conditions(observation(target_system=value)), [])

    def test_structured_conditions_are_preserved(self):
        rows = extract_observation_conditions(observation(
            measurement_conditions={
                "current_density": {"value": 1.0, "unit": "mA cm-2"},
                "temperature": 25,
            }
        ))
        values = {(x["condition_type"], x["normalized_value"]) for x in rows}
        self.assertIn(("current_density", "1.0 mA cm-2"), values)
        self.assertIn(("temperature", "25"), values)

    def test_extracts_explicit_evidence_phrase_with_provenance(self):
        rows = extract_observation_conditions(observation(
            target_system="Zn||Zn",
            worker_a_evidence={
                "file": "main_analysis.md",
                "location": "Page 7",
                "quote": "The current density was 0.5 mA cm-2 during cycling.",
            }
        ))
        item = next(x for x in rows if x["condition_type"] == "current_density")
        self.assertEqual(item["normalized_value"], "0.5 mA cm-2")
        self.assertEqual(item["source_file"], "main_analysis.md")
        self.assertEqual(item["source_location"], "Page 7")
        self.assertEqual(item["confidence"], "HIGH")

    def test_table_value_remains_bound_to_row_and_column_headers(self):
        rows = extract_observation_conditions(observation(
            target_system="Zn||Zn",
            worker_b_evidence={
                "file": "supporting_information.md",
                "location": "Table S4",
                "table_reference": "Table S4",
                "row_header": "Current density",
                "col_header": "Zn||Zn",
                "cell_value": "1 mA cm-2",
            }
        ))
        item = next(x for x in rows if x["condition_type"] == "current_density")
        self.assertEqual(item["raw_value"], "1 mA cm-2")
        self.assertEqual(item["row_header"], "Current density")
        self.assertEqual(item["col_header"], "Zn||Zn")
        self.assertEqual(item["table_id"], "Table S4")
        self.assertEqual(item["extraction_method"], "RULE_TABLE_HEADER_VALUE")

    def test_performance_only_quote_does_not_become_condition(self):
        rows = extract_observation_conditions(observation(
            target_system="Zn||Zn",
            worker_a_evidence={
                "quote": "The coulombic efficiency reached 99.9% after 1000 cycles."
            }
        ))
        self.assertFalse(any(x["condition_type"] in {
            "current_density", "areal_capacity", "measurement_temperature",
            "salt_concentration", "electrolyte_component", "percentage_modifier",
        } for x in rows))

    def test_explicit_test_batches_are_excluded_but_retained(self):
        self.assertEqual(EXCLUDED_TEST_BATCH_IDS, {
            "BATCH_20261106_LIMITS_PROBE",
            "BATCH_20261106_SMOKE_NR_94908118",
        })
        item = observation(batch_id="BATCH_20261106_LIMITS_PROBE")
        self.assertTrue(is_excluded_test_record(item))
        rows = extract_observation_conditions(item)
        self.assertTrue(rows)
        self.assertTrue(all(x["data_eligibility"] == "EXCLUDED_TEST_DATA" for x in rows))

    def test_does_not_exclude_doi_missing_records_or_reconciliation_batches(self):
        self.assertFalse(is_excluded_test_record(observation(doi=None)))
        self.assertFalse(is_excluded_test_record(observation(batch_id="BATCH_REC_20261114_001")))

    def test_outputs_include_hashes_and_eligible_only_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [
                observation(),
                observation(
                    observation_id="OBS2", paper_id="P2", doi="10.1/other",
                    batch_id="BATCH_20261106_LIMITS_PROBE",
                ),
            ]
            summary = write_condition_outputs(records, root, {"db.json": "abc123"})
            self.assertEqual(summary["input_observation_count"], 2)
            self.assertEqual(summary["eligible_observation_count"], 1)
            self.assertEqual(summary["excluded_test_observation_count"], 1)
            self.assertEqual(summary["target_system_reported_observation_count"], 1)
            self.assertEqual(summary["target_system_parsed_observation_count"], 1)
            with (root / "condition_records.csv").open(encoding="utf-8", newline="") as handle:
                output_rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["data_eligibility"] == "EXCLUDED_TEST_DATA" for row in output_rows))
            manifest = json.loads((root / "condition_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["rule_version"], CONDITION_RULE_VERSION)
            self.assertEqual(manifest["llm_calls"], 0)
            self.assertFalse(manifest["source_files_modified"])
            summary_json = json.loads((root / "condition_extraction_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_json["eligible_observation_count"], 1)


    def test_json_loader_preserves_table_headers_for_condition_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "db.json"
            source.write_text(json.dumps({
                "metadata": {},
                "papers": [{
                    "paper_id": "P_TABLE",
                    "doi": "10.1/table",
                    "observations": [{
                        "reconciliation_id": "R_TABLE",
                        "feature_id": "FEAT_CE",
                        "target_system": "Zn||Zn",
                        "worker_a_evidence": {
                            "file_path": "supporting_information.md",
                            "section_or_page": "Table S4",
                            "table_id": "Table S4",
                            "row_header": "Current density",
                            "col_header": "Zn||Zn",
                            "cell_value": "1 mA cm-2",
                            "verbatim_quote": "Current density of 1 mA cm-2.",
                        },
                    }],
                }],
            }), encoding="utf-8")
            _metadata, normalized = _load_json_observations(source)
            evidence = normalized[0]["worker_a_evidence"]
            self.assertEqual(evidence["row_header"], "Current density")
            self.assertEqual(evidence["col_header"], "Zn||Zn")
            self.assertEqual(evidence["cell_value"], "1 mA cm-2")
            extracted = extract_observation_conditions(normalized[0])
            table_record = next(x for x in extracted if x["extraction_method"] == "RULE_TABLE_HEADER_VALUE")
            self.assertEqual(table_record["source_file"], "supporting_information.md")
            self.assertEqual(table_record["row_header"], "Current density")
            self.assertEqual(table_record["normalized_value"], "1 mA cm-2")


if __name__ == "__main__":
    unittest.main()
