from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dor.cli import main


class ApplicationQuickStartIntegrationTests(unittest.TestCase):
    def _cli(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["dor", *[str(item) for item in args]]):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return_code = main()
        return return_code, stdout.getvalue(), stderr.getvalue()

    def _json_result(self, *args: str) -> dict:
        return_code, stdout, stderr = self._cli(*args)
        self.assertEqual(
            return_code,
            0,
            msg=f"CLI returned {return_code}\nstdout:\n{stdout}\nstderr:\n{stderr}",
        )
        return json.loads(stdout)

    def test_structured_data_quick_start_runs_to_g0_human_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            package = project / "raw_sources" / "adapter_package"
            dataset = package / "data" / "records.csv"
            paper = project / "raw_sources" / "paper.pdf"
            dataset.parent.mkdir(parents=True)
            paper.parent.mkdir(parents=True)
            dataset.write_text(
                "record_id,value\nREC_001,1.0\nREC_002,2.0\n",
                encoding="utf-8",
            )
            # The paper is a provenance-only byte stream. The workflow must
            # hash it without parsing or sending its contents to a Worker.
            paper.write_bytes(b"%PDF-1.7 synthetic provenance fixture")

            manifest = self._json_result(
                "init-adapter-package",
                "--package-root", str(package),
                "--adapter-id", "test-structured-input",
                "--adapter-version", "1.0",
                "--source", f"paper={paper}",
                "--artifact", "records=standardized_dataset=data/records.csv",
            )
            self.assertTrue(manifest["valid"])
            manifest_path = Path(manifest["manifest_path"])
            self.assertTrue(manifest_path.is_file())

            preflight_path = project / "run_control" / "adapter_route_preflight.json"
            preflight = self._json_result(
                "prepare-adapter-handoff",
                "--manifest", str(manifest_path),
                "--package-root", str(package),
                "--out", str(preflight_path),
            )
            self.assertTrue(preflight["valid"])
            self.assertEqual(preflight["route"], "STRUCTURED_DATASET")

            run_root = project / "runs" / "controlled-single-study-001"
            plan_result = self._json_result(
                "init-run-plan",
                "--adapter-handoff", str(preflight_path),
                "--project-root", str(project),
                "--run-root", str(run_root),
            )
            self.assertTrue(plan_result["valid"])
            self.assertEqual(plan_result["profile"], "CONTROLLED_SINGLE_STUDY")
            run_plan = Path(plan_result["run_plan_path"])
            self.assertTrue(run_plan.is_file())

            initialized = self._json_result(
                "run-init",
                "--plan", str(run_plan),
                "--run-root", str(run_root),
            )
            self.assertTrue(initialized.get("run_id"))
            run_manifest = run_root / "run_manifest.json"
            self.assertTrue(run_manifest.is_file())

            verified = self._json_result(
                "run-verify",
                "--manifest", str(run_manifest),
            )
            self.assertTrue(verified["valid"], msg=json.dumps(verified, indent=2))

            advanced = self._json_result(
                "run-advance",
                "--manifest", str(run_manifest),
                "--max-local-stages", "10",
            )
            self.assertEqual(advanced["status"], "PAUSED_FOR_HUMAN", msg=json.dumps(advanced, indent=2))
            self.assertTrue((run_root / "00_adapter" / "adapter_handoff.json").is_file())
            self.assertTrue((run_root / "01_audit" / "source_inventory.json").is_file())
            self.assertTrue((run_root / "01_audit" / "data_audit_report.md").is_file())

            inventory = json.loads(
                (run_root / "01_audit" / "source_inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(inventory["items"]), 1)
            self.assertEqual(inventory["items"][0]["source_file"], "data/records.csv")

            final_verification = self._json_result(
                "run-verify",
                "--manifest", str(run_manifest),
            )
            self.assertTrue(final_verification["valid"], msg=json.dumps(final_verification, indent=2))
            stage_states = {
                item["stage_id"]: item["state"]
                for item in final_verification["resume_plan"]["stages"]
            }
            self.assertEqual(stage_states["adapter_package_validation"], "SUCCEEDED")
            self.assertEqual(stage_states["source_audit"], "SUCCEEDED")
            self.assertEqual(stage_states["g0_review_packet"], "WAITING_FOR_HUMAN")


if __name__ == "__main__":
    unittest.main()
