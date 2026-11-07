# Local Python runtime

The runtime executes deterministic, file-based operations. It does not orchestrate Workers and does not make scientific decisions on behalf of the Supervisor.

## V0.1 scope

The initial runtime provides a read-only CSV/JSON audit:
- source existence and readability;
- file size and SHA-256;
- CSV headers, row count, basic non-empty coverage, and coarse sampled type hints;
- JSON parse validation and top-level shape summary;
- machine-readable dataset manifest;
- Markdown audit report;
- column-coverage CSV.

The audit does not infer domain semantics, normalize values, impute missing conditions, merge systems, train models, or modify source files.

## Setup

From the repository root:

    python -m venv .venv
    # Activate the environment using your operating system's normal command.
    python -m pip install -e ./runtime

V0.1 uses the Python standard library only.

## Run an audit

    dor audit --csv path/to/input.csv --json path/to/input.json --out path/to/separate/run/01_audit

Either input may be omitted, but at least one must be supplied. Output must be a separate derived-data directory. The audit produces dataset_manifest.json, data_audit_report.md, and column_coverage.csv when a CSV is supplied.

## Source preservation

The command reads inputs and writes only to --out. It records input hashes before and after inspection and fails if an input changed during the audit. Do not point --out at a source file. Keep source data outside the Git repository unless redistribution is explicitly permitted.

## Future runtime modules

Canonicalization, outcome-specific cohorts, model selection, interaction analysis, validation, and publication-package generation will be added only after the real domain schema and data feasibility have been audited.
