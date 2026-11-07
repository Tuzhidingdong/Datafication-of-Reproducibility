# Local Python runtime

The runtime executes deterministic, file-based operations. It does not orchestrate Workers and does not make scientific decisions on behalf of the Supervisor.

## Current implementation

The runtime provides a read-only structural audit:
- source existence, readability, file size, and SHA-256;
- CSV headers, row count, short/long row counts, non-empty coverage, and coarse sampled type hints;
- JSON parse validation, top-level shape, and a bounded nested path/type profile;
- a machine-readable dataset manifest and Markdown audit report;
- column-coverage CSV and JSON-structure-path CSV;
- source_inventory.json and mapping_review_queue.csv, containing neutral source locators with unresolved mapping status.

The JSON profile records structural paths, observed JSON value types, and list-length ranges. It deliberately does not copy source text values into the profile or assign domain meaning to any path. The inventory is a review queue, not an automatically inferred semantic mapping.

The audit does not infer domain semantics, normalize values, impute missing conditions, merge systems, train models, or modify source files.

## Setup

From the repository root:

    python -m venv .venv
    # Activate the environment using your operating system's normal command.
    python -m pip install -e ./runtime

The current audit uses the Python standard library only.

## Run an audit

    dor audit --csv path/to/input.csv --json path/to/input.json --out path/to/separate/run/01_audit

Either input may be omitted, but at least one must be supplied. Output must be a separate derived-data directory. The audit produces dataset_manifest.json, data_audit_report.md, source_inventory.json, and mapping_review_queue.csv, plus the CSV/JSON-specific profile files when those sources are supplied.

## Source preservation

The command reads inputs and writes only to --out. It records input hashes before and after inspection and fails if an input changed during the audit. It refuses a non-empty output directory and refuses an output path that is an existing file. Keep source data outside the Git repository unless redistribution is explicitly permitted.

## Interpretation boundary

A nested path is only a structural observation. It does not establish that a value is an experimental setpoint, measured local state, or valid model feature. Domain mapping remains a separately reviewed scientific task.
