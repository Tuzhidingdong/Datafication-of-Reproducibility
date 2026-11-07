"""Command-line interface for the DOR runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from dor.audit import run_audit
from dor.builder import build_canonical_files
from dor.canonical import validate_canonical_bundle
from dor.diagnostics import diagnose_canonical_bundle
from dor.mapping import validate_mapping_files

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
        if args.command == "validate-mapping":
            report=validate_mapping_files(args.plan,args.inventory)
            print(_write_json(args.out,report),end="")
            return 0 if report["valid"] else 2
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
