from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.publication import audit_publication_package_files, build_publication_package_files


class PublicationPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "guide.md").write_text("# Writing guide\n", encoding="utf-8")
        (self.root / "result.json").write_text('{"value": 12}\n', encoding="utf-8")
        self.plan_path = self.root / "plan.json"
        self.package_dir = self.root / "package"
        plan = {
            "schema_version": "1.0",
            "project_id": "P1",
            "run_id": "R1",
            "package_version": "0.5.0",
            "writing_guide_source": "guide.md",
            "artifacts": [
                {"artifact_id": "RESULT_1", "path": "results/result.json",
                 "source_path": "result.json", "type": "results",
                 "description": "Executed result", "status": "complete",
                 "linked_record_ids": ["F1"], "manuscript_sections": ["Results"]},
                {"artifact_id": "FIGURE_1", "path": "figures/figure1.svg",
                 "source_path": None, "type": "figure",
                 "description": "Not generated", "status": "not_generated",
                 "linked_record_ids": [], "manuscript_sections": ["Results"]},
                {"artifact_id": "MECH_1", "path": "mechanisms/report.json",
                 "source_path": None, "type": "mechanism_report",
                 "description": "Pending review", "status": "requires_review",
                 "linked_record_ids": [], "manuscript_sections": ["Discussion"]}
            ]
        }
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_package_and_audit_verifies_hashes(self):
        source_before = (self.root / "result.json").read_bytes()
        result = build_publication_package_files(self.plan_path, self.root, self.package_dir)
        self.assertTrue(result["valid"])
        self.assertEqual(result["artifact_count"], 3)
        manifest = json.loads((self.package_dir / "package_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["completeness"]["status"], "requires_review")
        self.assertEqual(manifest["artifacts"][0]["status"], "complete")
        self.assertTrue((self.package_dir / "README_FOR_WRITING_SKILL.md").is_file())
        self.assertTrue(audit_publication_package_files(self.package_dir)["valid"])
        self.assertEqual(source_before, (self.root / "result.json").read_bytes())

    def test_tampered_artifact_is_rejected(self):
        build_publication_package_files(self.plan_path, self.root, self.package_dir)
        (self.package_dir / "results/result.json").write_text('{"value": 13}\n', encoding="utf-8")
        audit = audit_publication_package_files(self.package_dir)
        self.assertFalse(audit["valid"])
        self.assertTrue(any("SHA-256" in message for message in audit["errors"]))

    def test_nonempty_output_directory_is_protected(self):
        self.package_dir.mkdir()
        marker = self.package_dir / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            build_publication_package_files(self.plan_path, self.root, self.package_dir)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_path_traversal_is_rejected(self):
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        plan["artifacts"][0]["path"] = "../escape.json"
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "relative path"):
            build_publication_package_files(self.plan_path, self.root, self.package_dir)

    def test_windows_drive_path_is_rejected(self):
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        plan["artifacts"][0]["path"] = "C:/outside/result.json"
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "drive prefix"):
            build_publication_package_files(self.plan_path, self.root, self.package_dir)

    def test_unindexed_package_file_is_rejected(self):
        build_publication_package_files(self.plan_path, self.root, self.package_dir)
        (self.package_dir / "unexpected.txt").write_text("not listed", encoding="utf-8")
        report = audit_publication_package_files(self.package_dir)
        self.assertFalse(report["valid"])
        self.assertTrue(any("Unindexed file" in item for item in report["errors"]))

    def test_writing_guide_tampering_is_rejected(self):
        build_publication_package_files(self.plan_path, self.root, self.package_dir)
        (self.package_dir / "README_FOR_WRITING_SKILL.md").write_text("tampered", encoding="utf-8")
        report = audit_publication_package_files(self.package_dir)
        self.assertFalse(report["valid"])
        self.assertTrue(any("Writing Skill guide SHA-256" in item for item in report["errors"]))

    def test_integrity_report_must_be_outside_package(self):
        build_publication_package_files(self.plan_path, self.root, self.package_dir)
        with self.assertRaisesRegex(ValueError, "outside the package"):
            from dor.publication import audit_publication_package_file
            audit_publication_package_file(self.package_dir, self.package_dir / "audit.json")

    def test_absolute_domain_profile_path_is_rejected(self):
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        plan["domain_profile"] = "C:/private/profile.yaml"
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "relative path"):
            build_publication_package_files(self.plan_path, self.root, self.package_dir)


if __name__ == "__main__":
    unittest.main()
