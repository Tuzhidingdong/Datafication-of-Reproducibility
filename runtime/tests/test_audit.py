from __future__ import annotations
import csv, json, tempfile, unittest
from pathlib import Path
from dor.audit import run_audit, sha256_file
from dor.structure import profile_json_structure

class ReadOnlyAuditTests(unittest.TestCase):
    def test_audit_outputs_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source_csv=root/"source.csv"; source_json=root/"source.json"; output=root/"derived"/"audit"
            source_csv.write_text("DOI,CE,Condition\n10.1/example,99.7,AB\n10.1/example,,control\n",encoding="utf-8")
            source_json.write_text(json.dumps({"records":[{"evidence":"quote","values":[1,None,"x"]}]}),encoding="utf-8")
            hashes=(sha256_file(source_csv),sha256_file(source_json)); result=run_audit(source_csv,source_json,output)
            self.assertEqual(result["audit_scope"],"READ_ONLY_STRUCTURAL_INSPECTION")
            for name in ["dataset_manifest.json","data_audit_report.md","column_coverage.csv","json_structure_paths.csv","source_inventory.json","mapping_review_queue.csv"]:
                self.assertTrue((output/name).is_file())
            self.assertEqual(hashes,(sha256_file(source_csv),sha256_file(source_json)))
            with (output/"column_coverage.csv").open(encoding="utf-8",newline="") as h:
                ce=next(row for row in csv.DictReader(h) if row["column"]=="CE")
            self.assertEqual(ce["nonempty_count"],"1"); self.assertEqual(ce["blank_or_missing_count"],"1")
            with (output/"json_structure_paths.csv").open(encoding="utf-8",newline="") as h:
                paths=list(csv.DictReader(h))
            self.assertTrue(any(row["path"]=="$['records'][]['evidence']" for row in paths))
    def test_csv_row_shapes_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"shape.csv"; source.write_text("a,b\n1\n2,3,4\n",encoding="utf-8")
            record=run_audit(source,None,root/"out")["sources"][0]
            self.assertEqual(record["row_shape"]["short_rows"],1); self.assertEqual(record["row_shape"]["long_rows"],1)
    def test_output_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.csv"; source.write_text("x\n1\n",encoding="utf-8")
            output=root/"not-a-directory"; output.write_text("keep",encoding="utf-8")
            with self.assertRaises(NotADirectoryError): run_audit(source,None,output)
            self.assertEqual(output.read_text(encoding="utf-8"),"keep")
    def test_output_directory_cannot_contain_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.csv"; source.write_text("x\n1\n",encoding="utf-8")
            with self.assertRaises(ValueError): run_audit(source,None,root)
    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"broken.json"; source.write_text("{not-json}",encoding="utf-8")
            with self.assertRaises(ValueError): run_audit(None,source,root/"out")

class JsonStructureProfileTests(unittest.TestCase):
    def test_profiles_types_without_source_values(self):
        profile=profile_json_structure({"a":[{"b":1},{"b":None}],"secret":"do-not-copy"})
        by_path={item["path"]:item for item in profile["paths"]}
        self.assertEqual(by_path["$['a'][]['b']"]["value_types"],{"integer":1,"null":1})
        self.assertNotIn("do-not-copy",json.dumps(profile))
    def test_path_limit_is_enforced(self):
        profile=profile_json_structure({str(i):i for i in range(50)},max_paths=10)
        self.assertLessEqual(profile["path_count"],10); self.assertTrue(profile["truncated_paths"])

if __name__=="__main__": unittest.main()
