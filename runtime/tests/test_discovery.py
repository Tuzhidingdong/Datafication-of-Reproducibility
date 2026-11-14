from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from dor.discovery import summarize_observations, run_discovery_scan
from dor.cli import build_parser

def record(paper, doi, feature, value, unit="mAh g-1", status="AGREED_MATCH"):
    return {"paper_id":paper,"doi":doi,"feature_id":feature,"resolved_value":value,
        "resolved_unit":unit,"status":status,"requires_human_review":False,
        "source_origin":"AGGREGATED_JSON","target_system":"Zn||Zn","batch_id":"batch-A",
        "measurement_conditions":{"current_density":1.0}}

class DiscoveryTests(unittest.TestCase):
    def test_cli_exposes_discovery_entry_point(self):
        args=build_parser().parse_args([
            "discover-opportunities","--database-json","corpus.json","--out-dir","discovery-output"])
        self.assertEqual(args.command,"discover-opportunities")
        self.assertEqual(args.minimum_studies,3)

    def test_between_study_summary_uses_doi_medians(self):
        rows=[]
        for i, doi in enumerate(("10.1/a","10.1/b","10.1/c"),1):
            rows += [record(f"P{i}",doi,"FEAT_X",i*10),
                     record(f"P{i}",doi,"FEAT_X",i*10+2)]
        result=summarize_observations(rows)
        signal=next(x for x in result["signals"] if x["signal_type"]=="CROSS_STUDY_DESCRIPTIVE_HETEROGENEITY")
        self.assertEqual(signal["supporting_study_count"],3)
        self.assertEqual(signal["study_median_min"],11.0)
        self.assertEqual(signal["study_median_max"],31.0)

    def test_paper_fallback_does_not_count_as_verified_study(self):
        result=summarize_observations([record("P1",None,"FEAT_X",1),
            record("P2",None,"FEAT_X",2),record("P3",None,"FEAT_X",3)])
        self.assertEqual(result["profile"]["verified_doi_study_count"],0)
        self.assertFalse(any(x["signal_type"]=="CROSS_STUDY_DESCRIPTIVE_HETEROGENEITY" for x in result["signals"]))

    def test_units_are_not_merged(self):
        result=summarize_observations([record("P1","10.1/a","FEAT_X",1,"mAh g-1"),
            record("P2","10.1/b","FEAT_X",2,"mAh cm-2")])
        self.assertEqual({(x["feature_id"],x["unit"]) for x in result["feature_rows"]},
            {("FEAT_X","mAh g-1"),("FEAT_X","mAh cm-2")})

    def test_conflict_is_retained_but_not_eligible(self):
        result=summarize_observations([record("P1","10.1/a","FEAT_X",1,status="VALUE_CONFLICT"),
            record("P2","10.1/b","FEAT_X",2)])
        row=result["feature_rows"][0]
        self.assertEqual(row["observation_count"],2)
        self.assertEqual(row["status_counts"]["VALUE_CONFLICT"],1)
        self.assertEqual(row["agreed_numeric_candidate_count"],1)

    def test_pair_support_is_not_called_interaction(self):
        rows=[]
        for i in range(1,4):
            rows += [record(f"P{i}",f"10.1/{i}","FEAT_X",i),
                     record(f"P{i}",f"10.1/{i}","FEAT_Y",i+1)]
        result=summarize_observations(rows)
        pair=next(x for x in result["joint_rows"] if x["feature_a"]=="FEAT_X" and x["feature_b"]=="FEAT_Y")
        self.assertEqual(pair["verified_doi_study_count"],3)
        self.assertEqual(pair["linkage_status"],"CO_OCCURRENCE_ONLY_EXPERIMENTAL_LINKAGE_UNVERIFIED")
        self.assertTrue(any(x["screening_status"]=="CO_OCCURRENCE_ONLY_NOT_AN_INTERACTION" for x in result["signals"]))

    def test_condition_coverage_is_aggregated(self):
        result=summarize_observations([record(f"P{i}",f"10.1/{i}","FEAT_X",i) for i in range(1,4)])
        self.assertEqual(result["condition_rows"][0]["condition_type"],"current_density")
        self.assertTrue(any(x["signal_type"]=="CONDITION_COVERAGE_OPPORTUNITY" for x in result["signals"]))

    def test_real_scan_preserves_source_and_emits_aggregate_brief(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"database.json"
            out=root/"discovery"
            papers=[]
            for i in range(1,4):
                papers.append({"paper_id":f"P{i}","doi":f"10.1/{i}","title":f"Private title {i}",
                    "observations":[{"reconciliation_id":f"R{i}","feature_id":"FEAT_X",
                     "target_system":"Zn||Zn","status":"AGREED_MATCH","resolved_value":i*10,
                     "resolved_unit":"mAh g-1","requires_human_review":False,
                     "measurement_conditions":{"current_density":1.0}}]})
            source.write_text(json.dumps({"metadata":{},"papers":papers}),encoding="utf-8")
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            result=run_discovery_scan(source,None,out)
            after=hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(before,after)
            self.assertEqual(result["observation_count"],3)
            self.assertTrue((out/"discovery_manifest.json").is_file())
            brief=(out/"agent_research_brief.md").read_text(encoding="utf-8")
            self.assertNotIn("Private title",brief)
            self.assertIn("paper text",brief)
            manifest=json.loads((out/"discovery_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["source_files_modified"])
            self.assertFalse(manifest["raw_observations_in_agent_brief"])

    def test_nonempty_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"db.json"
            source.write_text(json.dumps({"metadata":{},"papers":[{"paper_id":"P1","observations":[
                {"reconciliation_id":"R1","feature_id":"X","status":"AGREED_MATCH",
                 "resolved_value":1,"resolved_unit":"u"}]}]}),encoding="utf-8")
            out=root/"existing"
            out.mkdir()
            marker=out/"keep.txt"
            marker.write_text("keep",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_discovery_scan(source,None,out)
            self.assertEqual(marker.read_text(encoding="utf-8"),"keep")

if __name__ == "__main__":
    unittest.main()
