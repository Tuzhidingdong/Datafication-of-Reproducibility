"""Command-line interface for the DOR runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dor.audit import run_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dor", description="Datafication of Reproducibility runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Perform a read-only structural audit of CSV/JSON inputs")
    audit.add_argument("--csv", type=Path, help="Path to a source CSV file")
    audit.add_argument("--json", type=Path, help="Path to a source JSON file")
    audit.add_argument("--out", type=Path, required=True, help="Separate output directory for derived audit artifacts")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
            result = run_audit(args.csv, args.json, args.out)
            print(json.dumps({
                "status": "completed",
                "audit_id": result["audit_id"],
                "output_dir": str(args.out.resolve()),
                "sources": len(result["sources"]),
            }, ensure_ascii=False))
            return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}), file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
