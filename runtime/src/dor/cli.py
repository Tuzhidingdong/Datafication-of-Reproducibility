"""Command-line interface for the DOR runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from dor.audit import run_audit, run_audit_from_adapter_handoff
from dor.adapters import validate_adapter_package_files
from dor.adapter_handoff import (prepare_adapter_handoff_files, canonical_bundle_from_handoff,
    materialize_adapter_artifacts_files)
from dor.canonical_discovery import run_canonical_discovery_scan
from dor.cohort import build_modeling_cohort_files
from dor.cohort_review import validate_cohort_review_record, enforce_cohort_review
from dor.controlled_scope import (
    validate_single_study_applicability_files,
    prepare_single_study_not_applicable_artifacts_files,
)
from dor.execution_contract import inspect_supported_run_plan_execution_contract
from dor.builder import build_canonical_files, validate_build_spec_files
from dor.canonical import validate_canonical_bundle
from dor.diagnostics import diagnose_canonical_bundle
from dor.mapping import validate_mapping_files
from dor.modeling import run_baseline_models_files
from dor.reproducibility import evaluate_reproducibility_files
from dor.interactions import discover_interactions_files
from dor.robustness import assess_interaction_robustness_files
from dor.response_surface import generate_interaction_surface_files
from dor.mechanism_bridge import build_mechanism_evidence_bridge_files
from dor.reconciliation import reconcile_bundle_file, validate_reconciliation_decisions_files
from dor.research_scope import validate_research_scope_files
from dor.review import validate_run_review_packet_files, validate_reviewed_findings_files
from dor.publication import build_publication_package_files, audit_publication_package_files
from dor.virtual_reproduction import predict_virtual_condition_files
from dor.gates import inspect_gate_ledger, record_gate_decision, require_gate, require_selected_interaction, require_selected_interaction_id
from dor.acceptance import initialize_acceptance_record, validate_acceptance_record
from dor.acceptance_ledger import (initialize_acceptance_ledger, record_acceptance_revision,
    recover_acceptance_record, inspect_acceptance_history, create_acceptance_checkpoint,
    verify_acceptance_checkpoint)
from dor.run_manager import (
    authorize_worker, build_artifact_manifest, build_resume_plan, build_run_usage_report,
    initialize_run, record_stage_status, verify_run,
)
from dor.stage_runner import advance_run, execute_local_stage

def _write_json(path: Path | None, report: dict) -> str:
    rendered=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    if path:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(rendered,encoding="utf-8")
    return rendered


def _add_gate_args(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("--workflow-ledger", type=Path, default=None,
        help="Hash-bound G0-G4 approval ledger; required for guided project execution.")
    command_parser.add_argument("--run-manifest", type=Path, default=None,
        help="Exact active run_manifest.json; required for Cohort-review enforcement on modelling commands.")
    command_parser.add_argument("--allow-untracked-legacy", action="store_true",
        help="Explicit legacy-only bypass for archived scripts; never use in a real project.")


def _enforce_gate(args: argparse.Namespace, gate_id: str,
                  expected_artifacts: dict[str, Path] | None = None) -> None:
    if args.workflow_ledger is None:
        if args.allow_untracked_legacy:
            print(json.dumps({"warning":"UNTRACKED_LEGACY_WORKFLOW",
                "required_gate":gate_id,
                "message":"Workflow gate enforcement was explicitly bypassed for legacy compatibility."}),
                file=sys.stderr)
            return
        raise ValueError("This command requires --workflow-ledger and a current APPROVE decision for " + gate_id +
            ". The explicit --allow-untracked-legacy override is reserved for archived scripts.")
    require_gate(args.workflow_ledger, gate_id, expected_artifacts)


def _parse_artifact_bindings(values: list[str]) -> list[tuple[str, Path]]:
    bindings = []
    for value in values:
        if "=" not in value:
            raise ValueError("--artifact must use ARTIFACT_ID=FILE_PATH syntax.")
        artifact_id, path = value.split("=", 1)
        if not artifact_id.strip() or not path.strip():
            raise ValueError("--artifact must contain a non-empty ID and file path.")
        bindings.append((artifact_id.strip(), Path(path)))
    return bindings

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dor", description="Datafication of Reproducibility runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    adapter_validation = subparsers.add_parser(
        "validate-adapter-package",
        help="Validate an external adapter package without interpreting its data semantics",
    )
    adapter_validation.add_argument("--manifest", type=Path, required=True,
        help="Adapter package manifest JSON")
    adapter_validation.add_argument("--package-root", type=Path, default=None,
        help="Package root; defaults to the manifest directory")
    adapter_validation.add_argument("--out", type=Path, default=None,
        help="Optional validation report path outside the package root")
    adapter_handoff = subparsers.add_parser(
        "prepare-adapter-handoff",
        help="Validate an external adapter package and determine its generic DoR entry route",
    )
    adapter_handoff.add_argument("--manifest", type=Path, required=True,
        help="Adapter package manifest JSON")
    adapter_handoff.add_argument("--package-root", type=Path, default=None,
        help="Package root; defaults to the manifest directory")
    adapter_handoff.add_argument("--out", type=Path, required=True,
        help="New handoff JSON path outside the protected adapter package")
    adapter_handoff.add_argument("--dataset-manifest-out", type=Path, default=None,
        help="Optional package snapshot manifest path outside the protected adapter package")
    materialize = subparsers.add_parser(
        "materialize-adapter-artifacts",
        help="Copy selected hash-verified adapter artifacts into a new derived Run directory",
    )
    materialize.add_argument("--adapter-handoff", type=Path, required=True,
        help="Validated adapter_handoff.json")
    materialize_selector = materialize.add_mutually_exclusive_group(required=True)
    materialize_selector.add_argument("--artifact-id", action="append",
        help="Declared adapter artifact ID to materialize; repeat for multiple artifacts")
    materialize_selector.add_argument("--role", action="append",
        help="Declared adapter artifact role to materialize; each role must resolve to exactly one artifact")
    materialize.add_argument("--out-dir", type=Path, required=True,
        help="New or empty derived output directory outside the adapter package")
    discovery = subparsers.add_parser("discover-opportunities", help="Run a read-only exploratory scan over a canonical data bundle")
    discovery_source = discovery.add_mutually_exclusive_group(required=True)
    discovery_source.add_argument("--bundle", type=Path,
        help="Canonical data bundle produced by the reviewed mapping workflow")
    discovery_source.add_argument("--adapter-handoff", type=Path,
        help="Validated adapter handoff that declares a canonical_bundle artifact")
    discovery.add_argument("--out-dir", type=Path, required=True, help="New or empty derived discovery output directory")
    discovery.add_argument("--minimum-studies", type=int, default=3, help="Minimum Study groups for cross-Study descriptive signals")
    discovery.add_argument("--maximum-pairs", type=int, default=250,
        help="Maximum co-observed target pairs to catalogue")
    audit = subparsers.add_parser("audit", help="Perform a read-only structural audit of CSV/JSON inputs")
    audit.add_argument("--csv", type=Path, help="Path to a source CSV file")
    audit.add_argument("--json", type=Path, help="Path to a source JSON file")
    audit.add_argument("--adapter-handoff", type=Path, default=None,
        help="Validated adapter handoff; audits every supported standardized_dataset artifact")
    audit.add_argument("--out", type=Path, required=True, help="Separate output directory for derived audit artifacts")
    validate = subparsers.add_parser("validate-bundle", help="Validate canonical bundle structure and references")
    validate.add_argument("--input", type=Path, required=True, help="Canonical bundle JSON file")
    validate.add_argument("--out", type=Path, help="Optional path for a validation report JSON")
    diagnose = subparsers.add_parser("diagnose-bundle", help="Report potential duplicate and unreferenced canonical entities without changing records")
    diagnose.add_argument("--input", type=Path, required=True, help="Canonical bundle JSON file")
    diagnose.add_argument("--out", type=Path, help="Optional path for a diagnostics report JSON")
    reconcile = subparsers.add_parser("reconcile-bundle", help="Create evidence-linked data quality and reconciliation review queue without changing canonical data")
    reconcile.add_argument("--input", type=Path, required=True, help="Canonical bundle JSON file")
    reconcile.add_argument("--out-dir", type=Path, required=True, help="New or empty derived output directory")
    decisions = subparsers.add_parser("validate-reconciliation-decisions", help="Validate human review decisions against exact report and bundle hashes")
    decisions.add_argument("--decisions", type=Path, required=True, help="Human reconciliation decisions JSON")
    decisions.add_argument("--report", type=Path, required=True, help="Exact reconciliation_report.json")
    decisions.add_argument("--bundle", type=Path, required=True, help="Exact canonical_bundle.json referenced by the report")
    decisions.add_argument("--out", type=Path, help="Optional validation report JSON")
    scope_validation = subparsers.add_parser("validate-research-scope", help="Validate a human-selected scope against exact Discovery signal and task hashes")
    scope_validation.add_argument("--scope", type=Path, required=True, help="Human research_scope_record.json")
    scope_validation.add_argument("--discovery-report", type=Path, required=True, help="Exact Discovery report JSON")
    scope_validation.add_argument("--task", type=Path, required=True, help="Exact modeling_task.json")
    scope_validation.add_argument("--out", type=Path, help="Optional validation report JSON")
    mapping = subparsers.add_parser("validate-mapping", help="Validate mapping references, provenance, and approval gates")
    mapping.add_argument("--plan", type=Path, required=True, help="Mapping plan JSON")
    mapping.add_argument("--inventory", type=Path, required=True, help="Exact source_inventory.json used by the plan")
    mapping.add_argument("--out", type=Path, help="Optional path for a validation report JSON")
    build_spec_validation = subparsers.add_parser(
        "validate-build-spec",
        help="Validate explicit entity grouping and relationship rules without building a canonical bundle",
    )
    build_spec_validation.add_argument("--plan", type=Path, required=True, help="Exact mapping plan JSON")
    build_spec_validation.add_argument("--inventory", type=Path, required=True, help="Exact source inventory JSON")
    build_spec_validation.add_argument("--spec", type=Path, required=True, help="Canonical build specification JSON")
    build_spec_validation.add_argument("--out", type=Path, help="Optional validation report path")
    build = subparsers.add_parser("build-canonical", help="Build canonical entities from approved mappings and explicit grouping/link rules")
    build.add_argument("--plan", type=Path, required=True, help="Mapping plan JSON")
    build.add_argument("--inventory", type=Path, required=True, help="Exact source_inventory.json used by the plan")
    build.add_argument("--spec", type=Path, required=True, help="Canonical build specification JSON")
    build.add_argument("--source-root", type=Path, required=True, help="Directory containing source files named in the inventory")
    build.add_argument("--out-dir", type=Path, required=True, help="New or empty derived output directory")
    cohort = subparsers.add_parser("build-cohort", help="Build an endpoint-specific modelling cohort with study-level splits")
    cohort.add_argument("--bundle", type=Path, required=True, help="Validated canonical_bundle.json")
    cohort.add_argument("--task", type=Path, required=True, help="Explicit modeling_task.json")
    cohort.add_argument("--out-dir", type=Path, required=True, help="New or empty derived cohort output directory")
    cohort_review = subparsers.add_parser("validate-cohort-review", help="Validate the human record for cohort grain, independence, and split suitability")
    cohort_review.add_argument("--record", type=Path, required=True, help="Human-reviewed cohort_review_record.json")
    cohort_review.add_argument("--cohort-dir", type=Path, required=True, help="Exact output directory created by dor build-cohort")
    cohort_review.add_argument("--task", type=Path, required=True, help="Exact modeling task used to build the cohort")
    cohort_review.add_argument("--manifest", type=Path, default=None, help="Active Run manifest; required for a guided Run")
    cohort_review.add_argument("--out", type=Path, required=True, help="Declared cohort_review_validation.json output")
    models = subparsers.add_parser("fit-baselines", help="Fit deterministic baseline models and evaluate the selected model on held-out studies")
    models.add_argument("--cohort-dir", type=Path, required=True, help="Cohort output directory from dor build-cohort")
    models.add_argument("--task", type=Path, required=True, help="Exact modeling task JSON used to build the cohort")
    models.add_argument("--out-dir", type=Path, required=True, help="New or empty derived model output directory")
    evaluate = subparsers.add_parser("evaluate-reproducibility", help="Run nested study-group cross-validation and applicability-domain diagnostics")
    evaluate.add_argument("--cohort-dir", type=Path, required=True, help="Completed hash-verified modelling cohort directory")
    evaluate.add_argument("--task", type=Path, required=True, help="Exact modeling task JSON used to build the cohort")
    evaluate.add_argument("--out-dir", type=Path, required=True, help="New or empty derived reproducibility evaluation directory")
    evaluate.add_argument("--folds", type=int, default=None, help="Outer grouped CV folds; default is min(5, eligible Study count)")
    evaluate.add_argument("--seed", type=int, default=42, help="Deterministic grouped-fold seed")
    interaction = subparsers.add_parser("discover-interactions", help="Screen pairwise predictive interactions with nested Study-grouped validation")
    interaction.add_argument("--cohort-dir", type=Path, required=True, help="Completed hash-verified numeric modeling cohort directory")
    interaction.add_argument("--task", type=Path, required=True, help="Exact modeling task JSON with explicit interaction settings")
    interaction.add_argument("--out-dir", type=Path, required=True, help="New or empty derived interaction output directory")
    interaction.add_argument("--folds", type=int, default=None, help="Outer grouped CV folds; default is min(5, eligible Study count)")
    interaction.add_argument("--seed", type=int, default=42, help="Deterministic grouped-fold seed")
    robustness = subparsers.add_parser("assess-interaction-robustness", help="Repeat nested pairwise interaction screening across Study-group split seeds")
    robustness.add_argument("--cohort-dir", type=Path, required=True, help="Completed hash-verified numeric modeling cohort directory")
    robustness.add_argument("--task", type=Path, required=True, help="Exact modeling task JSON with explicit interaction settings")
    robustness.add_argument("--out-dir", type=Path, required=True, help="New or empty derived robustness output directory")
    robustness.add_argument("--folds", type=int, default=None, help="Outer grouped CV folds; default is min(5, eligible Study count)")
    robustness.add_argument("--seeds", type=str, default="11,23,42", help="At least three unique comma-separated integer seeds")
    robustness.add_argument("--minimum-candidate-run-fraction", type=float, default=0.8, help="Required fraction of runs labelled as candidates for seed-stable status")
    surface = subparsers.add_parser("generate-interaction-surface", help="Generate a descriptive pairwise response surface and support mask")
    surface.add_argument("--cohort-dir", type=Path, required=True, help="Completed hash-verified numeric modeling cohort directory")
    surface.add_argument("--task", type=Path, required=True, help="Exact modeling task JSON")
    surface.add_argument("--interaction-dir", type=Path, required=True, help="Hash-verified output directory from dor discover-interactions")
    surface.add_argument("--interaction-id", type=str, required=True, help="Exact interaction_id selected from interaction_catalogue.csv")
    surface.add_argument("--out-dir", type=Path, required=True, help="New or empty derived response-surface directory")
    surface.add_argument("--robustness-dir", type=Path, default=None, help="Optional hash-verified output directory from dor assess-interaction-robustness")
    surface.add_argument("--grid-size", type=int, default=None, help="Override task grid size (5-61)")
    surface.add_argument("--background-max", type=int, default=None, help="Override partial-dependence background cap (10-5000)")
    mechanism = subparsers.add_parser("build-mechanism-evidence-bridge", help="Validate source evidence links for explicit mechanism hypotheses tied to a selected interaction")
    mechanism.add_argument("--bundle", type=Path, required=True, help="Exact canonical_bundle.json used to build the modeling cohort")
    mechanism.add_argument("--cohort-dir", type=Path, required=True, help="Hash-verified endpoint-specific modeling cohort")
    mechanism.add_argument("--task", type=Path, required=True, help="Exact modeling_task.json used to build the cohort")
    mechanism.add_argument("--interaction-dir", type=Path, required=True, help="Hash-verified interaction discovery output")
    mechanism.add_argument("--plan", type=Path, required=True, help="Explicit mechanism_plan.json with evidence assessments")
    mechanism.add_argument("--out-dir", type=Path, required=True, help="New or empty derived mechanism bridge output directory")
    mechanism.add_argument("--robustness-dir", type=Path, default=None, help="Optional hash-verified repeated-seed robustness output")
    mechanism.add_argument("--response-surface-dir", type=Path, default=None, help="Optional hash-verified descriptive response-surface output")
    package = subparsers.add_parser("build-publication-package", help="Assemble an explicitly curated, hash-verified Writing Skill package")
    package.add_argument("--plan", type=Path, required=True, help="Explicit publication_package_plan.json")
    package.add_argument("--workspace-root", type=Path, required=True, help="Workspace root for declared relative source paths")
    package.add_argument("--out-dir", type=Path, required=True, help="New or empty publication package directory")
    package_audit = subparsers.add_parser("audit-publication-package", help="Verify publication package paths, completeness states, and SHA-256 hashes")
    package_audit.add_argument("--package-dir", type=Path, required=True, help="Publication package directory")
    package_audit.add_argument("--out", type=Path, help="Optional integrity report JSON outside the package")
    virtual = subparsers.add_parser("predict-virtual-condition", help="Predict a requested condition set with a hash-verified selected baseline model")
    virtual.add_argument("--model-run-dir", type=Path, required=True, help="Exact output directory from dor fit-baselines")
    virtual.add_argument("--query", type=Path, required=True, help="Explicit virtual_reproduction_query.json")
    virtual.add_argument("--out", type=Path, required=True, help="New JSON prediction report path")
    for gated_parser in (build, cohort, models, evaluate, interaction, robustness,
                         surface, mechanism, package, virtual):
        _add_gate_args(gated_parser)
    gate_record = subparsers.add_parser("gate-record", help="Append a hash-bound human decision to the G0-G4 workflow ledger")
    gate_record.add_argument("--workflow-ledger", type=Path, required=True)
    gate_record.add_argument("--gate", dest="gate_id", choices=["G0","G1","G2","G3","G4"], required=True)
    gate_record.add_argument("--decision", choices=["APPROVE","REVISE","STOP"], required=True)
    gate_record.add_argument("--reviewer", required=True, help="Human reviewer identifier; not independently authenticated")
    gate_record.add_argument("--rationale", required=True, help="Why this exact gate scope is approved, revised, or stopped")
    gate_record.add_argument("--artifact", dest="artifacts", action="append", default=[],
        help="Hash-bind a reviewed file as ARTIFACT_ID=FILE_PATH; repeat for every required artifact")
    gate_status = subparsers.add_parser("gate-status", help="Verify event history, artifact hashes, and current G0-G4 approval state")
    gate_status.add_argument("--workflow-ledger", type=Path, required=True)

    acceptance = subparsers.add_parser("validate-acceptance", help="Verify V1.0 acceptance semantics, Run binding, hashes, and deterministic JSON assertions")
    acceptance.add_argument("--record", type=Path, required=True, help="V1.0 acceptance record JSON")
    acceptance.add_argument("--run-manifest", type=Path, required=True, help="Exact run_manifest.json referenced by the record")
    acceptance.add_argument("--ledger", type=Path, required=True, help="Append-only acceptance revision ledger JSONL")
    acceptance.add_argument("--out", type=Path, help="Optional validation report JSON")

    acceptance_prepare = subparsers.add_parser(
        "init-acceptance",
        help="Create a post-Run Acceptance draft with exact Run evidence bindings; no scientific statuses are approved",
    )
    acceptance_prepare.add_argument("--manifest", type=Path, required=True, help="Completed Run Manager run_manifest.json")
    acceptance_prepare.add_argument("--out", type=Path, required=True, help="New acceptance_record.json path; existing files are never overwritten")
    acceptance_prepare.add_argument("--source-selection-manifest", type=Path, required=True,
        help="Optional completed post-Run source_selection_manifest.json")
    acceptance_prepare.add_argument("--extraction-review-record", type=Path, required=True,
        help="Optional completed post-Run extraction_review_record.json")
    acceptance_prepare.add_argument("--actor", required=True, help="Operator creating the draft and revision ledger")
    acceptance_prepare.add_argument("--rationale", required=True, help="Reason for initializing the Acceptance draft")

    acceptance_init = subparsers.add_parser("init-acceptance-ledger", help="Create immutable revision history for a new acceptance record")
    acceptance_init.add_argument("--record", type=Path, required=True)
    acceptance_init.add_argument("--ledger", type=Path, required=True)
    acceptance_init.add_argument("--actor", required=True)
    acceptance_init.add_argument("--rationale", required=True)

    acceptance_revision = subparsers.add_parser("record-acceptance-revision", help="Record a reviewed acceptance-record edit; invalidate all downstream stage reviews")
    acceptance_revision.add_argument("--record", type=Path, required=True)
    acceptance_revision.add_argument("--ledger", type=Path, required=True)
    acceptance_revision.add_argument("--actor", required=True)
    acceptance_revision.add_argument("--rationale", required=True)

    acceptance_recover = subparsers.add_parser("recover-acceptance-record", help="Restore the latest committed snapshot after an interrupted ledger update")
    acceptance_recover.add_argument("--record", type=Path, required=True)
    acceptance_recover.add_argument("--ledger", type=Path, required=True)

    acceptance_history = subparsers.add_parser("acceptance-history", help="List verified acceptance revisions, reviewers, stage changes, and invalidations")
    acceptance_history.add_argument("--ledger", type=Path, required=True)
    acceptance_history.add_argument("--out", type=Path, help="Optional path for the history report JSON")

    acceptance_checkpoint = subparsers.add_parser("checkpoint-acceptance", help="Create a detached checkpoint for independent anchoring of the complete acceptance history")
    acceptance_checkpoint.add_argument("--record", type=Path, required=True)
    acceptance_checkpoint.add_argument("--ledger", type=Path, required=True)
    acceptance_checkpoint.add_argument("--out", type=Path, required=True, help="New checkpoint JSON; store it outside the project trust boundary")

    acceptance_checkpoint_verify = subparsers.add_parser("verify-acceptance-checkpoint", help="Verify live acceptance state against a detached checkpoint and its independently retained SHA-256")
    acceptance_checkpoint_verify.add_argument("--record", type=Path, required=True)
    acceptance_checkpoint_verify.add_argument("--ledger", type=Path, required=True)
    acceptance_checkpoint_verify.add_argument("--checkpoint", type=Path, required=True)
    acceptance_checkpoint_verify.add_argument("--expected-sha256", required=True, help="Trusted checkpoint digest obtained from an independent channel")

    execution_contract = subparsers.add_parser("validate-execution-contract", help="Check a supported Run Plan against its machine-readable Runtime/Worker action bindings")
    execution_contract.add_argument("--plan", type=Path, required=True, help="One of the two published generic adapter Run Plan templates, or a configured copy")
    run_init = subparsers.add_parser("run-init", help="Create a new isolated run workspace from an explicit stage/artifact plan")
    run_init.add_argument("--plan", type=Path, required=True)
    run_init.add_argument("--run-root", type=Path, required=True)
    run_init.add_argument("--run-id", type=str, default=None)

    run_status = subparsers.add_parser("run-status", help="Show current project run and stage states")
    run_status.add_argument("--manifest", type=Path, required=True)

    run_verify = subparsers.add_parser("run-verify", help="Verify the run plan, source snapshots, and append-only run event chain")
    run_verify.add_argument("--manifest", type=Path, required=True)

    run_resume = subparsers.add_parser("run-resume-plan", help="Calculate safe artifact reuse and stage rebuild actions without executing them")
    run_resume.add_argument("--manifest", type=Path, required=True)
    run_resume.add_argument("--out", type=Path, default=None)

    run_artifacts = subparsers.add_parser("run-artifacts", help="Generate a regenerable artifact manifest with exact source/output hashes and provenance")
    run_artifacts.add_argument("--manifest", type=Path, required=True)
    run_artifacts.add_argument("--out", type=Path, default=None)

    run_usage = subparsers.add_parser("run-usage", help="Aggregate token usage actually recorded for terminal Run stage attempts")
    run_usage.add_argument("--manifest", type=Path, required=True)
    run_usage.add_argument("--out", type=Path, default=None)

    run_execute = subparsers.add_parser("run-stage-execute", help="Derive argv from Run Artifacts and execute one contract-bound local stage")
    run_execute.add_argument("--manifest", type=Path, required=True)
    run_execute.add_argument("--stage", dest="stage_id", required=True)
    run_execute.add_argument("--args-file", type=Path, default=None, help="Explicit JSON argv override for custom or unbound Run stages only")
    run_execute.add_argument("--timeout-seconds", type=int, default=3600)
    run_execute.add_argument("--dry-run", action="store_true", help="Print the exact argv without changing the Run")

    run_advance = subparsers.add_parser("run-advance", help="Derive argv from Run Artifacts and execute local stages until a human, Worker, Gate, or input boundary")
    run_advance.add_argument("--manifest", type=Path, required=True)
    run_advance.add_argument("--args-dir", type=Path, default=None, help="Explicit per-stage JSON argv overrides for custom or unbound Run stages only")
    run_advance.add_argument("--max-local-stages", type=int, default=10)
    run_advance.add_argument("--timeout-seconds", type=int, default=3600)

    review_packet = subparsers.add_parser("validate-run-review-packet", help="Validate a G0-G2 review packet against the active Run inputs and hashes")
    review_packet.add_argument("--packet", type=Path, required=True)
    review_packet.add_argument("--manifest", type=Path, required=True)
    review_packet.add_argument("--out", type=Path, required=True, help="Declared Run output path for the validation report")

    reviewed_findings = subparsers.add_parser("validate-reviewed-findings", help="Validate human dispositions against the exact Worker result and reviewed Run artifacts")
    reviewed_findings.add_argument("--record", type=Path, required=True)
    reviewed_findings.add_argument("--manifest", type=Path, required=True)
    reviewed_findings.add_argument("--out", type=Path, required=True, help="Declared Run output path for the validation report")

    single_study_scope = subparsers.add_parser(
        "validate-single-study-applicability",
        help="Validate a human-reviewed one-Study NOT_APPLICABLE declaration against the exact Run Bundle/task",
    )
    single_study_scope.add_argument("--record", type=Path, required=True)
    single_study_scope.add_argument("--bundle", type=Path, required=True)
    single_study_scope.add_argument("--task", type=Path, required=True)
    single_study_scope.add_argument("--manifest", type=Path, required=True)
    single_study_scope.add_argument("--workflow-ledger", type=Path, required=True,
        help="G0-G4 approval ledger; G2 must currently approve the exact Bundle/task.")
    single_study_scope.add_argument("--out", type=Path, required=True)

    single_study_na = subparsers.add_parser(
        "prepare-single-study-not-applicable-artifacts",
        help="Prepare explicit NOT_APPLICABLE records without fitting models or generating scientific predictions",
    )
    single_study_na.add_argument("--record", type=Path, required=True)
    single_study_na.add_argument("--validation", type=Path, required=True)
    single_study_na.add_argument("--bundle", type=Path, required=True)
    single_study_na.add_argument("--task", type=Path, required=True)
    single_study_na.add_argument("--manifest", type=Path, required=True)
    single_study_na.add_argument("--workflow-ledger", type=Path, required=True,
        help="G0-G4 approval ledger; G2 must currently approve the exact Bundle/task.")
    single_study_na.add_argument("--out-dir", type=Path, required=True)

    worker_authorize = subparsers.add_parser("run-worker-authorize", help="Record an explicit pre-dispatch Worker authorization and emit its bounded task packet")
    worker_authorize.add_argument("--manifest", type=Path, required=True)
    worker_authorize.add_argument("--stage", dest="stage_id", required=True)
    worker_authorize.add_argument("--role", required=True)
    worker_authorize.add_argument("--provider", required=True)
    worker_authorize.add_argument("--model", required=True)
    worker_authorize.add_argument("--project-root", type=Path, required=True)
    worker_authorize.add_argument("--authorized-by", required=True)
    worker_authorize.add_argument("--rationale", required=True)
    worker_authorize.add_argument("--confirm-abandoned", action="store_true",
        help="Confirm that an earlier RUNNING Worker process has been inspected and is no longer active.")

    stage_record = subparsers.add_parser("run-stage-record", help="Append RUNNING/SUCCEEDED/FAILED metadata for one explicitly declared stage")
    stage_record.add_argument("--manifest", type=Path, required=True)
    stage_record.add_argument("--stage", dest="stage_id", required=True)
    stage_record.add_argument("--status", choices=["RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"], required=True)
    stage_record.add_argument("--producer-kind", choices=["local", "worker", "manual"], required=True)
    stage_record.add_argument("--command", dest="producer_command", default=None)
    stage_record.add_argument("--role", default=None)
    stage_record.add_argument("--provider", default=None)
    stage_record.add_argument("--model", default=None)
    stage_record.add_argument("--project-root", default=None)
    stage_record.add_argument("--job-id", default=None)
    stage_record.add_argument("--session-id", default=None)
    stage_record.add_argument("--task-id", default=None)
    stage_record.add_argument("--input-tokens", type=int, default=None)
    stage_record.add_argument("--output-tokens", type=int, default=None)
    stage_record.add_argument("--reasoning-tokens", type=int, default=None)
    stage_record.add_argument("--cache-read-tokens", type=int, default=None)
    stage_record.add_argument("--cache-write-tokens", type=int, default=None)
    stage_record.add_argument("--reason", default=None)
    stage_record.add_argument("--confirm-abandoned", action="store_true",
        help="Confirm that an earlier RUNNING process has been inspected and is no longer active.")
    return parser

def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate-execution-contract":
            plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
            if not isinstance(plan, dict):
                raise ValueError("Run Plan must be a JSON object.")
            report = inspect_supported_run_plan_execution_contract(plan)
            print(_write_json(None, report), end="")
            return 0
        cohort_review_required_commands = {
            "fit-baselines", "evaluate-reproducibility", "discover-interactions",
            "assess-interaction-robustness", "generate-interaction-surface",
            "build-mechanism-evidence-bridge",
        }
        if args.command in cohort_review_required_commands and args.workflow_ledger is not None:
            if args.run_manifest is None:
                raise ValueError("Modelling commands require --run-manifest so the Cohort approval is bound to the exact active Run.")
            enforce_cohort_review(args.cohort_dir, args.task, args.workflow_ledger, args.run_manifest)
        if args.command == "validate-adapter-package":
            report = validate_adapter_package_files(args.manifest, args.package_root, args.out)
            print(_write_json(None, report), end="")
            return 0 if report["valid"] else 2
        if args.command == "init-acceptance-ledger":
            result = initialize_acceptance_ledger(args.record, args.ledger, args.actor, args.rationale)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "record-acceptance-revision":
            result = record_acceptance_revision(args.record, args.ledger, args.actor, args.rationale)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "recover-acceptance-record":
            result = recover_acceptance_record(args.record, args.ledger)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "acceptance-history":
            result = inspect_acceptance_history(args.ledger)
            print(_write_json(args.out, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "checkpoint-acceptance":
            result = create_acceptance_checkpoint(args.record, args.ledger, args.out)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "verify-acceptance-checkpoint":
            result = verify_acceptance_checkpoint(args.record, args.ledger, args.checkpoint, args.expected_sha256)
            print(_write_json(None, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "validate-acceptance":
            result = validate_acceptance_record(args.record, args.run_manifest, args.ledger)
            print(_write_json(args.out, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "init-acceptance":
            ledger_path = args.out.with_name(args.out.stem + "_acceptance_events.jsonl")
            snapshots_path = ledger_path.with_name(ledger_path.name + ".revisions")
            if ledger_path.is_symlink() or ledger_path.exists() or snapshots_path.is_symlink() or snapshots_path.exists():
                raise FileExistsError(
                    "The derived Acceptance revision ledger or snapshot directory already exists; "
                    "choose a new Acceptance output path rather than reusing or overwriting history."
                )
            result = initialize_acceptance_record(
                args.manifest, args.out,
                source_selection_manifest=args.source_selection_manifest,
                extraction_review_record=args.extraction_review_record,
            )
            record_path = Path(result["record_path"])
            try:
                ledger_report = initialize_acceptance_ledger(
                    record_path, ledger_path, args.actor, args.rationale,
                )
            except BaseException:
                # Remove only the draft created by this invocation and only
                # when no ledger/snapshot history was committed.
                if not ledger_path.exists() and not snapshots_path.exists():
                    record_path.unlink(missing_ok=True)
                raise
            result["acceptance_ledger_path"] = str(ledger_path.resolve(strict=False))
            result["acceptance_ledger_revision"] = ledger_report["revision"]
            result["acceptance_ledger_event_hash"] = ledger_report["event_hash"]
            print(_write_json(None, result), end="")
            return 0
        if args.command == "run-init":
            result = initialize_run(args.plan, args.run_root, args.run_id)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "run-verify":
            result = verify_run(args.manifest)
            print(_write_json(None, result), end="")
            return 0
        if args.command == "run-status":
            result = verify_run(args.manifest)
            print(_write_json(None, {
                "run_id": result["run_id"], "project_id": result["project_id"],
                "source_integrity": result["source_integrity"],
                "event_count": result["event_count"],
                "stages": result["resume_plan"]["stages"],
            }), end="")
            return 0
        if args.command == "run-resume-plan":
            result = build_resume_plan(args.manifest)
            print(_write_json(args.out, result), end="")
            return 0
        if args.command == "run-usage":
            result = build_run_usage_report(args.manifest)
            print(_write_json(args.out, result), end="")
            return 0
        if args.command == "run-stage-execute":
            cli_arguments = None
            if args.args_file is not None:
                try:
                    cli_arguments = json.loads(args.args_file.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Could not read --args-file as a JSON array: {exc}") from exc
                if not isinstance(cli_arguments, list):
                    raise ValueError("--args-file must contain a JSON array of CLI argument strings.")
            result = execute_local_stage(
                args.manifest, args.stage_id, cli_arguments,
                timeout_seconds=args.timeout_seconds, dry_run=args.dry_run,
            )
            print(_write_json(None, result), end="")
            return 0 if result["status"] in {"DRY_RUN", "SUCCEEDED"} else 2
        if args.command == "run-advance":
            result = advance_run(
                args.manifest,
                args.args_dir,
                max_local_stages=args.max_local_stages,
                timeout_seconds=args.timeout_seconds,
            )
            print(_write_json(None, result), end="")
            return 0 if result["status"] in {
                "COMPLETE", "PAUSED_FOR_GATE", "PAUSED_FOR_HUMAN",
                "PAUSED_FOR_WORKER_AUTHORIZATION", "ARGUMENTS_REQUIRED",
                "INPUT_REQUIRED", "YIELDED_AFTER_LOCAL_STAGE_LIMIT",
            } else 2
        if args.command == "run-artifacts":
            result = build_artifact_manifest(args.manifest)
            if args.out is not None:
                output_path = args.out.expanduser().resolve(strict=False)
                declared_paths = {Path(item["path"]).expanduser().resolve(strict=False)
                                  for item in result["artifacts"]}
                source_roots = [Path(item).expanduser().resolve(strict=False) for item in result["source_roots"]]
                protected_control_files = {
                    (Path(result["workspace_root"]) / name).resolve(strict=False)
                    for name in ("run_manifest.json", "run_plan.json", "run_events.jsonl")
                }
                if any(output_path.is_relative_to(source_root) for source_root in source_roots):
                    raise ValueError("Artifact manifest output must remain outside all protected source_roots.")
                if output_path in declared_paths or output_path in protected_control_files:
                    raise ValueError("Artifact manifest output cannot overwrite a declared artifact or Run Manager control file.")
            print(_write_json(args.out, result), end="")
            return 0
        if args.command == "validate-run-review-packet":
            result = validate_run_review_packet_files(args.packet, args.manifest, args.out)
            print(_write_json(args.out, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "validate-reviewed-findings":
            result = validate_reviewed_findings_files(args.record, args.manifest, args.out)
            print(_write_json(args.out, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "validate-single-study-applicability":
            _enforce_gate(args, "G2", {
                "canonical_bundle": args.bundle,
                "modeling_task": args.task,
            })
            result = validate_single_study_applicability_files(
                args.record, args.bundle, args.task, args.manifest, args.out,
            )
            print(_write_json(args.out, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "prepare-single-study-not-applicable-artifacts":
            _enforce_gate(args, "G2", {
                "canonical_bundle": args.bundle,
                "modeling_task": args.task,
            })
            result = prepare_single_study_not_applicable_artifacts_files(
                args.record, args.validation, args.bundle, args.task,
                args.manifest, args.out_dir,
            )
            print(_write_json(None, result), end="")
            return 0 if result["valid"] else 2
        if args.command == "run-worker-authorize":
            result = authorize_worker(
                args.manifest, args.stage_id, args.role, args.provider, args.model,
                args.project_root, args.authorized_by, args.rationale,
                confirm_abandoned=args.confirm_abandoned,
            )
            print(_write_json(None, result), end="")
            return 0
        if args.command == "run-stage-record":
            result = record_stage_status(
                args.manifest, args.stage_id, args.status, args.producer_kind,
                command=args.producer_command,
                role=args.role, provider=args.provider, model=args.model,
                project_root=args.project_root, job_id=args.job_id, session_id=args.session_id,
                task_id=args.task_id, input_tokens=args.input_tokens, output_tokens=args.output_tokens,
                reasoning_tokens=args.reasoning_tokens, cache_read_tokens=args.cache_read_tokens,
                cache_write_tokens=args.cache_write_tokens, reason=args.reason,
                confirm_abandoned=args.confirm_abandoned,
            )
            print(_write_json(None, result), end="")
            return 2 if result.get("automatic_failure") is True else 0
        if args.command == "gate-record":
            result=record_gate_decision(args.workflow_ledger,args.gate_id,args.decision,
                args.reviewer,args.rationale,_parse_artifact_bindings(args.artifacts or []))
            print(_write_json(None,result),end="")
            return 0
        if args.command == "gate-status":
            report=inspect_gate_ledger(args.workflow_ledger)
            print(_write_json(None,report),end="")
            return 0
        if args.command == "prepare-adapter-handoff":
            result = prepare_adapter_handoff_files(
                args.manifest, args.package_root, args.out, args.dataset_manifest_out,
            )
            payload = {**result, "handoff_path": str(args.out.expanduser().resolve())}
            if args.dataset_manifest_out is not None:
                payload["dataset_manifest_path"] = str(args.dataset_manifest_out.expanduser().resolve())
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "materialize-adapter-artifacts":
            result = materialize_adapter_artifacts_files(
                args.adapter_handoff, args.out_dir,
                artifact_ids=args.artifact_id, roles=args.role,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "discover-opportunities":
            bundle_path = args.bundle if args.bundle is not None else canonical_bundle_from_handoff(args.adapter_handoff)
            result = run_canonical_discovery_scan(
                bundle_path, args.out_dir, args.minimum_studies, args.maximum_pairs,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "audit":
            if args.adapter_handoff is not None:
                if args.csv is not None or args.json is not None:
                    raise ValueError("--adapter-handoff cannot be combined with --csv or --json.")
                result = run_audit_from_adapter_handoff(args.adapter_handoff, args.out)
            else:
                result = run_audit(args.csv, args.json, args.out)
            print(json.dumps({"status":"completed","audit_id":result["audit_id"],
                "output_dir":str(args.out.resolve()),"sources":len(result["sources"])},ensure_ascii=False))
            return 0
        if args.command in {"validate-bundle","diagnose-bundle"}:
            with args.input.open("r",encoding="utf-8-sig") as handle:
                bundle=json.load(handle)
            report=validate_canonical_bundle(bundle) if args.command=="validate-bundle" else diagnose_canonical_bundle(bundle)
            print(_write_json(args.out,report),end="")
            return 0 if report.get("valid",report.get("valid_input",False)) else 2
        if args.command == "reconcile-bundle":
            result=reconcile_bundle_file(args.input,args.out_dir)
            report=result["report"]
            print(json.dumps({"status":"completed" if report["valid_bundle"] else "completed_with_integrity_errors",
                "report_path":result["report_path"],"queue_path":result["queue_path"],
                "issue_count":report["issue_count"],"severity_counts":report["severity_counts"]},
                ensure_ascii=False,indent=2))
            return 0 if report["valid_bundle"] else 2
        if args.command == "validate-reconciliation-decisions":
            report=validate_reconciliation_decisions_files(args.decisions,args.report,args.bundle)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "validate-research-scope":
            report=validate_research_scope_files(args.scope,args.discovery_report,args.task)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "validate-mapping":
            report=validate_mapping_files(args.plan,args.inventory)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "validate-cohort-review":
            report=validate_cohort_review_record(args.record,args.cohort_dir,args.task,args.manifest)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "validate-build-spec":
            report=validate_build_spec_files(args.plan,args.inventory,args.spec)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "discover-interactions":
            _enforce_gate(args,"G2",{"modeling_task":args.task})
            result=discover_interactions_files(args.cohort_dir,args.task,args.out_dir,args.folds,args.seed)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "candidate_pair_count":report["candidate_pair_count"],"eligible_pair_count":report["eligible_pair_count"],
                "interaction_candidates":sum(1 for item in report["interaction_catalogue"] if item["interpretation_status"]=="CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE"),
                "claim_scope":"PREDICTIVE_STATISTICAL_INTERACTION_CANDIDATE_NOT_CAUSAL_OR_MECHANISTIC_EVIDENCE"},ensure_ascii=False,indent=2))
            return 0
        if args.command == "assess-interaction-robustness":
            _enforce_gate(args,"G2",{"modeling_task":args.task})
            seeds=[int(value.strip()) for value in args.seeds.split(",") if value.strip()]
            result=assess_interaction_robustness_files(args.cohort_dir,args.task,args.out_dir,seeds,
                args.folds,args.minimum_candidate_run_fraction)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "seed_count":report["seed_count"],
                "seed_stable_candidates":sum(1 for item in report["interaction_catalogue"] if item["robustness_status"]=="SEED_STABLE_PREDICTIVE_INTERACTION_CANDIDATE"),
                "claim_scope":"SEED_SENSITIVITY_NOT_INFERENTIAL_SIGNIFICANCE_CAUSALITY_OR_MECHANISM"},ensure_ascii=False,indent=2))
            return 0
        if args.command == "generate-interaction-surface":
            _enforce_gate(args,"G3",{"interaction_report":args.interaction_dir/"interaction_discovery_report.json"})
            if args.workflow_ledger is not None:
                require_selected_interaction_id(args.workflow_ledger,args.interaction_id)
            result=generate_interaction_surface_files(args.cohort_dir,args.task,args.interaction_dir,
                args.interaction_id,args.out_dir,args.robustness_dir,args.grid_size,args.background_max)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "interaction_id":report["interaction_id"],"grid_point_count":report["grid"]["grid_point_count"],
                "supported_grid_fraction":report["empirical_support"]["supported_grid_fraction"],
                "method":report["method"],"validation_scope":report["validation_scope"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "build-mechanism-evidence-bridge":
            _enforce_gate(args,"G3",{
                "interaction_report":args.interaction_dir/"interaction_discovery_report.json",
                "mechanism_plan":args.plan})
            if args.workflow_ledger is not None:
                require_selected_interaction(args.workflow_ledger,args.plan)
            result=build_mechanism_evidence_bridge_files(args.bundle,args.cohort_dir,args.task,
                args.interaction_dir,args.plan,args.out_dir,args.robustness_dir,args.response_surface_dir)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "mechanism_hypothesis_count":len(report["mechanism_catalogue"]),
                "evidence_review_issue_count":report["review_issue_count"],
                "review_state":report["review_state"],
                "claim_scope":report["claim_scope"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "build-publication-package":
            _enforce_gate(args,"G4",{"publication_plan":args.plan})
            result=build_publication_package_files(args.plan,args.workspace_root,args.out_dir)
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "artifact_count":result["artifact_count"],"copied_artifact_count":result["copied_artifact_count"],
                "completeness":result["manifest"]["completeness"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "audit-publication-package":
            report=audit_publication_package_files(args.package_dir)
            if args.out is not None:
                report_path=args.out.expanduser().resolve()
                package_path=args.package_dir.expanduser().resolve()
                if report_path.is_relative_to(package_path):
                    raise ValueError("Package integrity report must be written outside the package directory.")
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "predict-virtual-condition":
            _enforce_gate(args,"G2")
            result=predict_virtual_condition_files(args.model_run_dir,args.query,args.out)
            report=result["report"]
            print(json.dumps({"status":"completed","output_path":result["output_path"],
                "prediction":report["prediction"],"prediction_status":report["prediction_status"],
                "uncertainty_status":report["uncertainty_status"],"warning_count":len(report["warnings"])},
                ensure_ascii=False,indent=2))
            return 0
        if args.command == "evaluate-reproducibility":
            _enforce_gate(args,"G2",{"modeling_task":args.task})
            result=evaluate_reproducibility_files(args.cohort_dir,args.task,args.out_dir,args.folds,args.seed)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "study_count":report["study_count"],"observation_count":report["observation_count"],
                "fold_count":report["fold_count"],"pooled_out_of_fold_metrics":report["pooled_out_of_fold_metrics"],
                "applicability_domain_counts":report["applicability_domain"]["counts"],
                "uncertainty_status":report["uncertainty"]["status"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "fit-baselines":
            _enforce_gate(args,"G2",{"modeling_task":args.task})
            result=run_baseline_models_files(args.cohort_dir,args.task,args.out_dir)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "selected_model":report["selected_model"],"selected_candidate_id":report["selected_candidate_id"],
                "primary_selection_metric":report["primary_selection_metric"],
                "test_evaluation":report["test_evaluation"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "build-cohort":
            _enforce_gate(args,"G2",{
                "canonical_bundle":args.bundle,
                "modeling_task":args.task})
            result=build_modeling_cohort_files(args.bundle,args.task,args.out_dir)
            report=result["report"]
            print(json.dumps({"status":"completed" if result["valid"] else "failed",
                "output_dir":result["output_dir"],"eligible_observation_count":report.get("eligible_observation_count",0),
                "eligible_study_count":report.get("eligible_study_count",0),
                "split_counts":report.get("split_counts",{}),"errors":report.get("errors",[])},ensure_ascii=False,indent=2))
            return 0 if result["valid"] else 2
        if args.command == "build-canonical":
            _enforce_gate(args,"G1",{
                "mapping_plan":args.plan,
                "source_inventory":args.inventory,
                "build_spec":args.spec})
            output_dir=args.out_dir.expanduser().resolve()
            if output_dir.exists():
                if not output_dir.is_dir():
                    raise NotADirectoryError(f"Output path exists and is not a directory: {output_dir}")
                if any(output_dir.iterdir()):
                    raise FileExistsError(f"Refusing to overwrite a non-empty output directory: {output_dir}")
            source_root=args.source_root.expanduser().resolve()
            bundle, report=build_canonical_files(args.plan,args.inventory,args.spec,source_root)
            output_dir.mkdir(parents=True,exist_ok=True)
            (output_dir/"build_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            if bundle is None:
                print(json.dumps({"status":"failed","output_dir":str(output_dir),"report":report},ensure_ascii=False,indent=2))
                return 2
            (output_dir/"canonical_bundle.json").write_text(json.dumps(bundle,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            print(json.dumps({"status":"completed","output_dir":str(output_dir),
                "entity_counts":report["entity_counts"],
                "duplicate_candidate_count":report["relationship_diagnostics"]["duplicate_candidate_count"]},ensure_ascii=False))
            return 0
    except Exception as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"error":str(exc)}),file=sys.stderr)
        return 2
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
