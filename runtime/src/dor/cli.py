"""Command-line interface for the DOR runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from dor.audit import run_audit
from dor.canonical import validate_canonical_bundle
from dor.mapping import validate_mapping_files

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
    mapping = subparsers.add_parser("validate-mapping", help="Validate mapping references, provenance, and approval gates")
    mapping.add_argument("--plan", type=Path, required=True, help="Mapping plan JSON")
    mapping.add_argument("--inventory", type=Path, required=True, help="Exact source_inventory.json used by the plan")
    mapping.add_argument("--out", type=Path, help="Optional path for a validation report JSON")
    return parser

def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
            result = run_audit(args.csv, args.json, args.out)
            print(json.dumps({"status":"completed","audit_id":result["audit_id"],
                "output_dir":str(args.out.resolve()),"sources":len(result["sources"])},ensure_ascii=False))
            return 0
        if args.command == "validate-bundle":
            with args.input.open("r",encoding="utf-8-sig") as handle:
                bundle=json.load(handle)
            report=validate_canonical_bundle(bundle)
        elif args.command == "validate-mapping":
            report=validate_mapping_files(args.plan,args.inventory)
        else:
            return 1
        rendered=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
        if args.out:
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(rendered,encoding="utf-8")
        print(rendered,end="")
        return 0 if report["valid"] else 2
    except Exception as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"error":str(exc)}),file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
