# Local Python runtime

The runtime executes deterministic, file-based operations. It does not orchestrate Workers and does not make scientific decisions on behalf of the Supervisor.

## Current implementation

The runtime provides:
- read-only CSV/JSON structural audit, source hashing, and coverage reports;
- bounded nested JSON structure profiling;
- stable source inventory and unresolved mapping review queue;
- canonical research bundle structural and referential-integrity validation;
- mapping-plan reference, provenance, transformation-specification, and approval-gate validation;
- deterministic canonical construction from approved mappings, explicit entity grouping, and explicit row-overlap relationships for CSV sources.

The canonical bundle schema is in ../schemas/canonical_bundle.schema.json. The mapping plan schema is in ../schemas/mapping_plan.schema.json. The build specification schema is in ../schemas/canonical_build_spec.schema.json. See ../docs/CANONICAL_DATA_MODEL.md, ../docs/MAPPING_CONTRACT.md, and ../docs/CANONICAL_BUILDER.md.

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

This checks required entity fields, duplicate IDs, broken references, selected relationship inconsistencies, missingness states, comparison size, and evidence locator presence. It is structural/referential validation, not scientific validation or full JSON Schema validation.

## Validate a mapping plan

    dor validate-mapping --plan mapping_plan.json --inventory source_inventory.json --out mapping_validation.json

The plan must contain the SHA-256 digest of the exact inventory file. Regenerating or editing that inventory invalidates the plan's digest. Only approved rules with valid references, targets, explicit transformations, and review metadata are eligible. Any error fails closed and produces no eligible rule IDs.

## Build a canonical bundle

    dor build-canonical --plan mapping_plan.json --inventory source_inventory.json --spec canonical_build_spec.json --source-root path/to/source/files --out-dir path/to/new/derived/run/02_canonical

The build specification is bound to the exact mapping-plan and source-inventory file hashes. It explicitly defines:
- each canonical entity definition and the source CSV it reads;
- whether instances are one-per-source-row or grouped by declared source key columns;
- which approved mapping rules populate the entity's fields;
- which child-to-parent relationships are created from shared source-row overlap.

The builder never assumes that a CSV row is an experiment. Grouped fields must be consistent within a group; conflicting values fail the build and require a finer grouping or a reviewed mapping change. Blank grouping keys fail rather than creating unstable identities. IDs are deterministic within the input hashes and build-definition IDs.

V0.2 construction currently supports CSV columns only. JSON paths are inventoried but are not yet executable selectors; a build definition referencing a JSON path is rejected. Relationships are supported only when child and parent definitions refer to the same source CSV and the declared relationship is evidenced by shared source rows. Cross-file joins require a future explicit join-key contract.

The builder executes IDENTITY, NUMERIC_PARSE, UNIT_CONVERSION, LOOKUP, and SPLIT transformations. CUSTOM transformations are not executable. Raw source values and per-cell provenance are retained in each entity's field_provenance; source row/hash and mapping version are recorded in _provenance. The build report is always written; canonical_bundle.json is written only after structural and referential validation passes. A successful build is not proof that the scientific mappings or entity groupings are correct.

## Source preservation

All commands read original sources. Audit and build outputs go to separate derived directories. The builder verifies source hashes before and after reading and refuses non-empty output directories. It never edits source CSV/JSON files.

## Interpretation boundary

A nested path or column is only a structural observation. It does not establish that a value is an experimental setpoint, measured local state, or valid model feature. Domain mapping, grouping, and relationship rules remain explicit scientific review decisions.
