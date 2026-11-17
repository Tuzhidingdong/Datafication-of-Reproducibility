from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.adapter_handoff import prepare_adapter_handoff_files
from dor.adapter_package import initialize_adapter_package
from dor.project_setup import initialize_project_run_plan
from dor.cli import build_parser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def canonical_bundle() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "project-setup-test",
        "mapping_version": "external-test-1",
        "studies": [],
        "systems": [],
        "conditions": [],
        "experiments": [],
        "observations": [],
        "comparisons": [],
        "evidence": [],
    }


class ProjectRunPlanSetupTests(unittest.TestCase):
    def _structured_handoff(self, root: Path) -> tuple[Path, Path]:
        project = root / "project"
        package = project / "raw_sources" / "adapter_package"
        source = project / "raw_sources" / "paper.pdf"
        dataset = package / "data" / "records.csv"
        source.parent.mkdir(parents=True)
        dataset.parent.mkdir(parents=True)
        source.write_bytes(b"provenance-only source")
        dataset.write_text("record_id,value\nA,1\nB,2\n", encoding="utf-8")
        manifest = initialize_adapter_package(
            package, "manual-structured-input", "1.0",
            [f"paper={source}"],
            [f"records=standardized_dataset={dataset}"],
        )["manifest_path"]
        handoff = root / "preflight" / "adapter_handoff.json"
        prepare_adapter_handoff_files(Path(manifest), package, handoff)
        return project, handoff

    def test_single_study_setup_selects_structured_route_and_validates_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            run_root = root / "runs" / "single-study-001"

            result = initialize_project_run_plan(
                handoff, project, run_root,
            )

            plan_path = Path(result["run_plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertTrue(result["valid"])
            self.assertEqual(result["route"], "STRUCTURED_DATASET")
            self.assertEqual(result["profile"], "CONTROLLED_SINGLE_STUDY")
            self.assertEqual(plan["execution_profile"], "CONTROLLED_SINGLE_STUDY")
            self.assertNotIn("virtual_query_input", {item["artifact_id"] for item in plan["source_artifacts"]})
            self.assertIn("adapter_package_manifest", {item["artifact_id"] for item in plan["source_artifacts"]})
            self.assertIn("publication_plan_template", {item["artifact_id"] for item in plan["source_artifacts"]})
            self.assertTrue(Path(result["publication_plan_template"]).is_file())
            self.assertTrue(Path(result["workflow_ledger_path"]).is_absolute())
            self.assertIn("dor run-init", result["run_init_command"])
            self.assertTrue(any(Path(item) == (project / "raw_sources" / "adapter_package").resolve()
                                for item in plan["source_roots"]))
            self.assertTrue(any(Path(item) == (project / "raw_sources").resolve()
                                for item in plan["source_roots"]))

    def test_full_analysis_can_initialize_without_pre_generated_virtual_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)

            result = initialize_project_run_plan(
                handoff, project, root / "runs" / "full-analysis",
                profile="FULL_ANALYSIS",
            )

            plan_path = Path(result["run_plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertTrue(result["valid"])
            self.assertEqual(result["route"], "STRUCTURED_DATASET")
            self.assertEqual(result["profile"], "FULL_ANALYSIS")
            self.assertNotIn("execution_profile", plan)
            source_artifacts = {item["artifact_id"]: item["path"] for item in plan["source_artifacts"]}
            self.assertNotIn("virtual_query_input", source_artifacts)
            self.assertIsNone(result.get("virtual_query_reference"))

            # optional external query may be kept as non-authoritative reference only
            query = project / "configuration" / "virtual_query.json"
            write_json(query, {"schema_version": "1.0", "query_id": "reference-only"})
            result2 = initialize_project_run_plan(
                handoff, project, root / "runs" / "full-analysis-2",
                profile="FULL_ANALYSIS",
                virtual_query_input=query,
                output_path=project / "run_control" / "run_plan.full_analysis.ref.json",
            )
            plan2 = json.loads(Path(result2["run_plan_path"]).read_text(encoding="utf-8"))
            source_artifacts2 = {item["artifact_id"]: item["path"] for item in plan2["source_artifacts"]}
            self.assertNotIn("virtual_query_input", source_artifacts2)
            self.assertEqual(result2.get("virtual_query_reference"), str(query.resolve()))

    def test_single_study_rejects_unused_virtual_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            query = project / "configuration" / "query.json"
            write_json(query, {"query": "not used"})
            with self.assertRaisesRegex(ValueError, "does not consume a virtual query"):
                initialize_project_run_plan(
                    handoff, project, root / "runs" / "single",
                    virtual_query_input=query,
                )

    def test_stale_preflight_handoff_is_rejected_before_plan_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            dataset = project / "raw_sources" / "adapter_package" / "data" / "records.csv"
            dataset.write_text("record_id,value\nA,999\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                initialize_project_run_plan(
                    handoff, project, root / "runs" / "stale",
                )
            self.assertFalse((project / "run_control" / "run_plan.structured_dataset.single_study.json").exists())

    def test_canonical_route_succeeds_when_all_required_roles_are_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            package = project / "adapter_package"
            package.mkdir(parents=True)
            source = project / "raw_sources" / "paper.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"source")
            bundle_path = package / "canonical_bundle.json"
            inventory_path = package / "source_inventory.json"
            mapping_path = package / "mapping_plan.json"
            spec_path = package / "build_spec.json"
            write_json(bundle_path, canonical_bundle())
            write_json(inventory_path, {"schema_version": "1.0", "items": []})
            write_json(mapping_path, {"schema_version": "1.0", "rules": []})
            write_json(spec_path, {"schema_version": "1.0"})
            artifacts = [
                f"bundle=canonical_bundle={bundle_path}",
                f"inventory=source_inventory={inventory_path}",
                f"mapping=mapping_plan={mapping_path}",
                f"spec=build_spec={spec_path}",
            ]
            manifest = initialize_adapter_package(
                package, "external-bundle-adapter", "1.0",
                [f"paper={source}"], artifacts,
            )["manifest_path"]
            handoff = root / "preflight.json"
            prepare_adapter_handoff_files(Path(manifest), package, handoff)

            result = initialize_project_run_plan(
                handoff, project, root / "runs" / "canonical",
            )
            plan = json.loads(Path(result["run_plan_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["route"], "CANONICAL_BUNDLE")
            self.assertEqual(result["profile"], "CONTROLLED_SINGLE_STUDY")
            self.assertIn("adapter_artifact_materialization", {
                item["stage_id"] for item in plan["stages"]
            })

    def test_cli_exposes_project_run_plan_setup(self):
        args = build_parser().parse_args([
            "init-run-plan",
            "--adapter-handoff", "preflight/adapter_handoff.json",
            "--project-root", "project",
            "--run-root", "runs/run-001",
            "--profile", "FULL_ANALYSIS",
            "--virtual-query-input", "project/configuration/query.json",
            "--acceptance-source", "paper=PRIMARY_PAPER=project/paper.pdf",
        ])
        self.assertEqual(args.command, "init-run-plan")
        self.assertEqual(args.profile, "FULL_ANALYSIS")
        self.assertEqual(args.acceptance_source, ["paper=PRIMARY_PAPER=project/paper.pdf"])

    def test_canonical_route_requires_all_four_provenance_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            package = project / "adapter_package"
            package.mkdir(parents=True)
            source = project / "source.pdf"
            source.write_bytes(b"source")
            bundle_path = package / "canonical_bundle.json"
            write_json(bundle_path, canonical_bundle())
            artifacts = [
                "bundle=canonical_bundle=" + str(bundle_path),
            ]
            manifest = initialize_adapter_package(
                package, "external-bundle-adapter", "1.0",
                [f"paper={source}"], artifacts,
            )["manifest_path"]
            handoff = root / "preflight.json"
            prepare_adapter_handoff_files(Path(manifest), package, handoff)

            with self.assertRaisesRegex(ValueError, "require exactly one artifact for role"):
                initialize_project_run_plan(
                    handoff, project, root / "runs" / "canonical",
                )

    def test_acceptance_sources_are_explicitly_bound_and_included_in_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            si = project / "raw_sources" / "paper_si.pdf"
            si.write_bytes(b"si provenance only")
            primary = project / "raw_sources" / "paper.pdf"
            # Reuse the byte-identical source already bound by the Adapter manifest.
            result = initialize_project_run_plan(
                handoff, project, root / "runs" / "single",
                acceptance_sources=[
                    f"paper=PRIMARY_PAPER={primary}",
                    f"paper-si=SUPPLEMENTARY_INFORMATION={si}",
                ],
            )
            plan = json.loads(Path(result["run_plan_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                {item["role"] for item in plan["acceptance_source_artifacts"]},
                {"PRIMARY_PAPER", "SUPPLEMENTARY_INFORMATION"},
            )
            self.assertTrue(any(si.resolve().parent == Path(item) for item in plan["source_roots"]))
            self.assertTrue(any(primary.resolve().parent == Path(item) for item in plan["source_roots"]))

    def test_single_study_acceptance_snapshot_requires_primary_and_si(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            primary = project / "raw_sources" / "paper.pdf"
            # Keep the original manifest-bound source bytes unchanged.
            with self.assertRaisesRegex(ValueError, "requires both PRIMARY_PAPER and SUPPLEMENTARY_INFORMATION"):
                initialize_project_run_plan(
                    handoff, project, root / "runs" / "single",
                    acceptance_sources=[f"paper=PRIMARY_PAPER={primary}"],
                )
            self.assertFalse(
                (project / "run_control" / "run_plan.structured_dataset.single_study.json").exists()
            )
            self.assertFalse((project / "configuration").exists())
            self.assertFalse((project / "run_control").exists())

    def test_existing_plan_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, handoff = self._structured_handoff(root)
            output = project / "run_control" / "existing-plan.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"preserve": true}\n', encoding="utf-8")
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                initialize_project_run_plan(
                    handoff, project, root / "runs" / "single",
                    output_path=output,
                )
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
