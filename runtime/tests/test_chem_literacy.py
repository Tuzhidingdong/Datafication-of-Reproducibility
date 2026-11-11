from __future__ import annotations
import csv, json, tempfile, unittest
from pathlib import Path
from dor.chem_literacy import ingest_chem_literacy_files, validate_condition_recovery_files
from dor.cli import build_parser


class ChemLiteracyAdapterTests(unittest.TestCase):
    def _csv(self, path: Path, rows: list[dict]) -> None:
        fields = ["paper_id","doi","title","batch_id","reconciliation_id","feature_id","target_system",
            "status","resolved_value","resolved_unit","worker_a_value","worker_a_unit","worker_b_value",
            "worker_b_unit","relative_difference","requires_human_review","review_reason","evidence_file_a",
            "location_a","verbatim_quote_a","table_reference_a","grounding_type_a","evidence_file_b",
            "location_b","verbatim_quote_b","table_reference_b","grounding_type_b"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_flat_csv_preserves_repeated_measurements_and_filters_target_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"ledger.csv"; rows=[]
            for i,value in enumerate((32.81,36.0,46.33,55.94),start=5):
                rows.append({"paper_id":"paper-A","doi":"10.1000/a","reconciliation_id":f"REC_{i:04d}",
                    "feature_id":"FEAT_OVERPOT_PLAT","target_system":"Zn||Zn, 2 M ZnSO4 + 1% TAC",
                    "status":"PASS_A_ONLY","resolved_value":value,"resolved_unit":"mV",
                    "worker_a_value":value,"worker_a_unit":"mV","requires_human_review":"True",
                    "evidence_file_a":"main_analysis.md","location_a":"Page 7",
                    "verbatim_quote_a":"32.81, 36.00, 46.33, and 55.94 mV at current densities",
                    "grounding_type_a":"SOURCE_DIRECT"})
            rows.append({"paper_id":"paper-A","doi":"10.1000/a","reconciliation_id":"REC_0100",
                "feature_id":"FEAT_CE","target_system":"Zn||Cu","status":"AGREED_MATCH",
                "resolved_value":"99.5","resolved_unit":"%","requires_human_review":"False"})
            self._csv(source,rows); output=root/"out"
            result=ingest_chem_literacy_files(None,source,None,None,output)
            self.assertEqual(result["observation_count"],5)
            with (output/"observations_normalized.csv").open(encoding="utf-8",newline="") as handle:
                imported=list(csv.DictReader(handle))
            series=[r for r in imported if r["feature_id"]=="FEAT_OVERPOT_PLAT"]
            self.assertEqual([r["resolved_value"] for r in series],["32.81","36.0","46.33","55.94"])
            self.assertEqual(len({r["observation_id"] for r in series}),4)
            with (output/"numeric_target_candidates.csv").open(encoding="utf-8",newline="") as handle:
                candidates=list(csv.DictReader(handle))
            self.assertEqual(len(candidates),1)
            self.assertEqual(candidates[0]["feature_id"],"FEAT_CE")
            report=json.loads((output/"data_quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["unique_doi_count"],1)
            self.assertEqual(report["feature_summary"]["FEAT_OVERPOT_PLAT"]["single_worker_count"],4)

    def test_json_and_ledger_merge_by_composite_key_and_keep_paper_id_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); database=root/"database.json"
            database.write_text(json.dumps({"metadata":{"unique_papers_count":1},"papers":[{
                "paper_id":"paper-A","doi":"","title":"Title A","observations":[{
                    "reconciliation_id":"REC_0001","feature_id":"FEAT_CE","target_system":"Zn||Cu",
                    "status":"PASS_A_ONLY","worker_a_value":99.9,"worker_a_unit":"%",
                    "worker_a_evidence":{"file_path":"main_analysis.md","section_or_page":"Page 1",
                    "verbatim_quote":"CE reached 99.9%."}}]}]}),encoding="utf-8")
            ledger=root/"ledger.csv"
            self._csv(ledger,[{"paper_id":"paper-A","doi":"","title":"Title A","reconciliation_id":"REC_0001",
                "feature_id":"FEAT_CE","target_system":"Zn||Cu","status":"PASS_A_ONLY",
                "worker_a_value":"99.9","worker_a_unit":"%","requires_human_review":"True",
                "evidence_file_a":"main_analysis.md","location_a":"Page 1","verbatim_quote_a":"CE reached 99.9%."}])
            output=root/"out"; ingest_chem_literacy_files(database,None,ledger,None,output)
            report=json.loads((output/"data_quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["observation_count"],1); self.assertEqual(report["source_merge_issue_count"],0)
            with (output/"observations_normalized.csv").open(encoding="utf-8",newline="") as handle:
                row=next(csv.DictReader(handle))
            self.assertEqual(row["study_group_id"],"paper-A")
            self.assertEqual(row["study_group_id_source"],"PAPER_ID_FALLBACK_NOT_VERIFIED_DOI")
            self.assertEqual(json.loads(row["worker_a_evidence"])["quote"],"CE reached 99.9%.")

    def test_json_csv_disagreement_is_flagged_and_json_value_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); database=root/"db.json"
            database.write_text(json.dumps({"papers":[{"paper_id":"p1","observations":[{
                "reconciliation_id":"R1","feature_id":"FEAT_CE","status":"AGREED_MATCH",
                "resolved_value":99.1,"resolved_unit":"%"}]}]}),encoding="utf-8")
            ledger=root/"ledger.csv"
            self._csv(ledger,[{"paper_id":"p1","reconciliation_id":"R1","feature_id":"FEAT_CE",
                "status":"AGREED_MATCH","resolved_value":"99.9","resolved_unit":"%"}])
            output=root/"out"; ingest_chem_literacy_files(database,None,ledger,None,output)
            report=json.loads((output/"data_quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["source_merge_issue_count"],1)
            with (output/"observations_normalized.csv").open(encoding="utf-8",newline="") as handle:
                row=next(csv.DictReader(handle))
            self.assertEqual(row["resolved_value"],"99.1")

    def test_missing_condition_is_not_promoted_to_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"data.csv"
            self._csv(source,[{"paper_id":"p1","doi":"10.1/p1","reconciliation_id":"R1",
                "feature_id":"FEAT_CE","target_system":"Zn||Cu","status":"AGREED_MATCH",
                "resolved_value":99.5,"resolved_unit":"%"}])
            output=root/"out"; ingest_chem_literacy_files(None,source,None,None,output)
            with (output/"condition_recovery_queue.csv").open(encoding="utf-8",newline="") as handle:
                queue=list(csv.DictReader(handle))
            self.assertTrue(queue)
            self.assertEqual({row["retrieval_status"] for row in queue},{"SOURCE_FILES_NOT_AVAILABLE"})
            self.assertTrue(all(row["condition_decision"]=="UNRESOLVED" for row in queue))
            self.assertTrue(all("NOT_REPORTED" not in row["retrieval_status"] for row in queue))

    def test_targeted_search_creates_unverified_candidate_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"data.csv"
            self._csv(source,[{"paper_id":"p1","doi":"10.1/p1","reconciliation_id":"R1",
                "feature_id":"FEAT_CE","target_system":"Zn||Cu","status":"AGREED_MATCH",
                "resolved_value":99.5,"resolved_unit":"%","evidence_file_a":"main_analysis.md"}])
            paper=root/"sources"/"p1"; paper.mkdir(parents=True)
            (paper/"main_analysis.md").write_text(
                "The CE was measured at a current density of 1 mA cm-2 and an areal capacity of 1 mAh cm-2.",
                encoding="utf-8")
            output=root/"out"; ingest_chem_literacy_files(None,source,None,root/"sources",output)
            with (output/"condition_recovery_queue.csv").open(encoding="utf-8",newline="") as handle:
                queue=list(csv.DictReader(handle))
            current=next(row for row in queue if row["condition_type"]=="current_density")
            self.assertEqual(current["retrieval_status"],"CANDIDATE_CONTEXT_FOUND_NOT_VERIFIED")
            tasks=json.loads((output/"condition_recovery_tasks.json").read_text(encoding="utf-8"))["tasks"]
            self.assertTrue(tasks)
            self.assertTrue(all(task["human_review_required_before_promotion"] for task in tasks))

    def test_source_root_is_protected_and_cli_is_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"data.csv"
            self._csv(source,[{"paper_id":"p1","reconciliation_id":"R1","feature_id":"FEAT_CE","status":"PASS_A_ONLY"}])
            original=source.read_bytes()
            with self.assertRaises(ValueError):
                ingest_chem_literacy_files(None,source,None,root,root/"nested_out")
            self.assertEqual(source.read_bytes(),original)
        args=build_parser().parse_args(["ingest-chem-literacy","--database-csv","obs.csv","--out-dir","out"])
        self.assertEqual(args.command,"ingest-chem-literacy")
        self.assertEqual(args.database_csv,Path("obs.csv"))


    def test_worker_found_result_requires_exact_source_quote_and_stays_pending_human_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); paper=root/"sources"/"p1"; paper.mkdir(parents=True)
            source=paper/"main_analysis.md"
            source.write_text("The cell was tested at 1 mA cm-2 current density.",encoding="utf-8")
            import hashlib
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            task={"schema_version":"1.0","task_id":"T1","paper_id":"p1",
                "observation_ids":["O1"],
                "source_files":[{"path":str(source),"sha256":digest}],
                "requested_conditions":[{"condition_type":"current_density","search_terms":["current density"]}]}
            task_path=root/"task.json"; task_path.write_text(json.dumps(task),encoding="utf-8")
            result={"schema_version":"1.0","task_id":"T1","paper_id":"p1",
                "source_hashes":{str(source):digest},
                "field_reviews":[{"condition_type":"current_density","status":"FOUND",
                    "candidate_value":1,"candidate_unit":"mA cm-2","source_file":str(source),
                    "page_or_locator":"Page 2","verbatim_quote":"1 mA cm-2 current density",
                    "linked_observation_ids":["O1"],"rationale":"Explicit value and unit in source."}]}
            result_path=root/"result.json"; result_path.write_text(json.dumps(result),encoding="utf-8")
            report=validate_condition_recovery_files(task_path,result_path,root/"sources",root/"validation.json")
            self.assertTrue(report["valid"],report["errors"])
            self.assertEqual(report["promotion_status"],"PENDING_HUMAN_REVIEW")
            self.assertFalse(report["not_reported_decisions_accepted"])
            result["field_reviews"][0]["verbatim_quote"]="a fabricated quote"
            result_path.write_text(json.dumps(result),encoding="utf-8")
            report=validate_condition_recovery_files(task_path,result_path,root/"sources",root/"validation2.json")
            self.assertFalse(report["valid"])
            self.assertTrue(any(item["code"]=="QUOTE_NOT_FOUND_IN_SOURCE" for item in report["errors"]))

    def test_not_found_result_does_not_become_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); paper=root/"sources"/"p1"; paper.mkdir(parents=True)
            source=paper/"main_analysis.md"; source.write_text("Experimental section.",encoding="utf-8")
            import hashlib
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            task={"schema_version":"1.0","task_id":"T2","paper_id":"p1","observation_ids":["O1"],
                "source_files":[{"path":str(source),"sha256":digest}],
                "requested_conditions":[{"condition_type":"areal_capacity","search_terms":["areal capacity"]}]}
            task_path=root/"task.json"; task_path.write_text(json.dumps(task),encoding="utf-8")
            result={"schema_version":"1.0","task_id":"T2","paper_id":"p1","source_hashes":{str(source):digest},
                "field_reviews":[{"condition_type":"areal_capacity","status":"NOT_FOUND_IN_SEARCH",
                    "candidate_value":None,"candidate_unit":None,"source_file":None,"page_or_locator":None,
                    "verbatim_quote":None,"linked_observation_ids":["O1"],"rationale":"No matching statement in the targeted excerpts."}],
                "main_text_reviewed":True,"si_reviewed":True}
            result_path=root/"result.json"; result_path.write_text(json.dumps(result),encoding="utf-8")
            report=validate_condition_recovery_files(task_path,result_path,root/"sources",root/"validation.json")
            self.assertTrue(report["valid"],report["errors"])
            self.assertFalse(report["not_reported_decisions_accepted"])
            self.assertTrue(any(item["code"]=="NOT_FOUND_IS_NOT_NOT_REPORTED" for item in report["warnings"]))

    def test_recovery_validation_cli_is_registered(self):
        args=build_parser().parse_args(["validate-condition-recovery","--task","task.json",
            "--result","result.json","--source-root","sources","--out","validation.json"])
        self.assertEqual(args.command,"validate-condition-recovery")


if __name__ == "__main__":
    unittest.main()
