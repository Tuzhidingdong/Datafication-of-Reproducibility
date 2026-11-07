# Local Python runtime

The runtime executes deterministic, file-based operations. It does not orchestrate Workers and does not make scientific decisions on behalf of the Supervisor.

## Current implementation

The runtime provides:
- read-only CSV/JSON structural audit, source hashing, and coverage reports;
- bounded nested JSON structure profiling;
- stable source inventory and unresolved mapping review queue;
- canonical research bundle structural and referential-integrity validation;
- mapping-plan reference, provenance, transformation-specification, and approval-gate validation.

The canonical bundle schema is in ../schemas/canonical_bundle.schema.json. The mapping plan schema is in ../schemas/mapping_plan.schema.json. See ../docs/CANONICAL_DATA_MODEL.md and ../docs/MAPPING_CONTRACT.md for the entity and mapping contracts.

## Setup

From the repository root:

    python -m venv .venv
    # Activate the environment using your operating system's normal command.
    python -m pip install -e ./runtime

The current runtime uses the Python standard library only.

## Run a read-only audit

    dor audit --csv path/to/input.csv --json path/to/input.json --out path/to/separate/run/01_audit

Either input may be omitted, but at least one must be supplied. Output must be a separate derived-data directory. The audit produces dataset_manifest.json, data_audit_report.md, source_inventory.json, and mapping_review_queue.csv, plus the CSV/JSON-specific profile files when those sources are supplied.

## Validate a canonical bundle

    dor validate-bundle --input canonical_bundle.json --out validation_report.json

The command reports missing required fields, duplicate IDs, broken references, selected relationship inconsistencies, invalid missingness states, and malformed evidence locators. It returns exit code 0 when valid and 2 when validation errors are found. The report states its scope and does not certify scientific correctness.

## Validate a mapping plan

    dor validate-mapping --plan mapping_plan.json --inventory source_inventory.json --out mapping_validation.json

The plan must contain the SHA-256 digest of the exact inventory file. Calculate it after the inventory is final; editing or regenerating that inventory invalidates the plan's digest. Only rules with APPROVED status, a valid source reference, a supported canonical target, explicit transformation specification, and reviewer metadata are eligible. Any validation error fails closed and produces no eligible rule IDs.

This command validates eligibility; it does not execute conversions, create canonical entities, or decide whether a scientific mapping is correct. Transformation execution and canonical construction are separate future components.

## Source preservation

The audit reads inputs and writes only to --out. It records input hashes before and after inspection and fails if an input changed during the audit. It refuses a non-empty output directory and refuses an output path that is an existing file. The validators read their inputs and write only to the optional report path.

## Interpretation boundary

A nested path is only a structural observation. It does not establish that a value is an experimental setpoint, measured local state, or valid model feature. Domain mapping remains a separately reviewed scientific task.
