"""Command-line interface for the DOR runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from dor.audit import run_audit
from dor.cohort import build_modeling_cohort_files
from dor.builder import build_canonical_files
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

def _write_json(path: Path | None, report: dict) -> str:
    rendered=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    if path:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(rendered,encoding="utf-8")
    return rendered

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dor", description="Datafication of Reproducibility runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="Perform a read-only structural audit of CSV/JSON inputs")
    audit.add_argument("--csv", type=Path, help="Path to a source CSV file")
    audit.add_argument("--json", type=Path, help="Path to a source JSON file")
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
    mapping = subparsers.add_parser("validate-mapping", help="Validate mapping references, provenance, and approval gates")
    mapping.add_argument("--plan", type=Path, required=True, help="Mapping plan JSON")
    mapping.add_argument("--inventory", type=Path, required=True, help="Exact source_inventory.json used by the plan")
    mapping.add_argument("--out", type=Path, help="Optional path for a validation report JSON")
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
    return parser

def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
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
        if args.command == "validate-mapping":
            report=validate_mapping_files(args.plan,args.inventory)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
        if args.command == "discover-interactions":
            result=discover_interactions_files(args.cohort_dir,args.task,args.out_dir,args.folds,args.seed)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "candidate_pair_count":report["candidate_pair_count"],"eligible_pair_count":report["eligible_pair_count"],
                "interaction_candidates":sum(1 for item in report["interaction_catalogue"] if item["interpretation_status"]=="CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE"),
                "claim_scope":"PREDICTIVE_STATISTICAL_INTERACTION_CANDIDATE_NOT_CAUSAL_OR_MECHANISTIC_EVIDENCE"},ensure_ascii=False,indent=2))
            return 0
        if args.command == "assess-interaction-robustness":
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
            result=generate_interaction_surface_files(args.cohort_dir,args.task,args.interaction_dir,
                args.interaction_id,args.out_dir,args.robustness_dir,args.grid_size,args.background_max)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "interaction_id":report["interaction_id"],"grid_point_count":report["grid"]["grid_point_count"],
                "supported_grid_fraction":report["empirical_support"]["supported_grid_fraction"],
                "method":report["method"],"validation_scope":report["validation_scope"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "build-mechanism-evidence-bridge":
            result=build_mechanism_evidence_bridge_files(args.bundle,args.cohort_dir,args.task,
                args.interaction_dir,args.plan,args.out_dir,args.robustness_dir,args.response_surface_dir)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "mechanism_hypothesis_count":len(report["mechanism_catalogue"]),
                "evidence_review_issue_count":report["review_issue_count"],
                "review_state":report["review_state"],
                "claim_scope":report["claim_scope"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "evaluate-reproducibility":
            result=evaluate_reproducibility_files(args.cohort_dir,args.task,args.out_dir,args.folds,args.seed)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "study_count":report["study_count"],"observation_count":report["observation_count"],
                "fold_count":report["fold_count"],"pooled_out_of_fold_metrics":report["pooled_out_of_fold_metrics"],
                "applicability_domain_counts":report["applicability_domain"]["counts"],
                "uncertainty_status":report["uncertainty"]["status"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "fit-baselines":
            result=run_baseline_models_files(args.cohort_dir,args.task,args.out_dir)
            report=result["report"]
            print(json.dumps({"status":"completed","output_dir":result["output_dir"],
                "selected_model":report["selected_model"],"selected_candidate_id":report["selected_candidate_id"],
                "primary_selection_metric":report["primary_selection_metric"],
                "test_evaluation":report["test_evaluation"]},ensure_ascii=False,indent=2))
            return 0
        if args.command == "build-cohort":
            result=build_modeling_cohort_files(args.bundle,args.task,args.out_dir)
            report=result["report"]
            print(json.dumps({"status":"completed" if result["valid"] else "failed",
                "output_dir":result["output_dir"],"eligible_observation_count":report.get("eligible_observation_count",0),
                "eligible_study_count":report.get("eligible_study_count",0),
                "split_counts":report.get("split_counts",{}),"errors":report.get("errors",[])},ensure_ascii=False,indent=2))
            return 0 if result["valid"] else 2
        if args.command == "build-canonical":
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
