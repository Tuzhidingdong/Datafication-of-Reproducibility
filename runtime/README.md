# Local Python runtime

The runtime executes deterministic, file-based operations. It does not orchestrate Workers and does not make scientific decisions on behalf of the Supervisor.

## Current implementation

The runtime provides:
- read-only CSV/JSON structural audit, source hashing, and coverage reports;
- bounded nested JSON profiling and a stable source inventory;
- canonical research bundle structural and referential-integrity validation;
- mapping-plan reference, provenance, transformation-specification, and approval-gate validation;
- deterministic canonical construction from approved CSV and JSON mappings, explicit entity grouping, and declared row-overlap or field-equality relationships;
- non-destructive diagnostics for exact-payload duplicate candidates and unreferenced entities;
- evidence-linked reconciliation review queues for endpoint variants, missing endpoint definitions, observation value variation, same-replicate conflicts, evidence locator disagreements, and explicitly ambiguous/conflicting values;
- report-hash and bundle-hash-bound human reconciliation decision validation.

The canonical bundle schema is in ../schemas/canonical_bundle.schema.json. The mapping plan schema is in ../schemas/mapping_plan.schema.json. The build specification schema is in ../schemas/canonical_build_spec.schema.json. Reconciliation report and human decision schemas are in ../schemas/reconciliation_report.schema.json and ../schemas/reconciliation_decisions.schema.json. See ../docs/CANONICAL_DATA_MODEL.md, ../docs/MAPPING_CONTRACT.md, ../docs/CANONICAL_BUILDER.md, and ../docs/RECONCILIATION.md.

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
- the canonical entity type and source file for each entity definition;
- the source format (csv or json);
- whether entity instances are one-per-source-record or grouped by declared source key fields;
- which approved mapping rules populate the entity fields;
- how child-parent relationships are established.

### CSV selectors

CSV entity definitions use declared column inventory IDs for grouping and approved mappings. A row is not automatically an experiment; entity grain is a reviewed build-spec decision.

### JSON selectors

A JSON entity definition must set source_format to json and an explicit record_selector using an RFC 6901 JSON Pointer with * as an array wildcard. Example:

    /papers/*/experiments/*

The selector must resolve to objects. A JSON field mapping refers to the audit inventory's structural path pattern, such as $['papers'][]['experiments'][]['temperature']. The builder resolves that pattern relative to each selected object and records the concrete JSON Pointer for each value. If one mapped path resolves to multiple values inside a selected object, the build fails; select a deeper record level rather than arbitrarily choosing or aggregating values.

### Relationships

ROW_OVERLAP links records that share the same source data row (CSV) or selected JSON object pointer. It requires the same source file and format.

FIELD_EQUALITY links entities using two explicitly mapped canonical fields: child_key_field and parent_key_field. This supports cross-file CSV/JSON joins. Matching is exact and type-sensitive after the declared field transformations; no implicit trimming, case folding, unit conversion, DOI normalization, fuzzy matching, or null-to-null matching is performed. Scalar relationships require exactly one parent match; zero or multiple matches fail the build. Many-valued relationships retain every exact match.

The builder never assumes that a CSV row or JSON object is an experiment. Grouped fields must be consistent within a group; conflicts fail the build and require a finer grouping or a reviewed mapping change. Blank grouping/join keys fail rather than creating unstable identities. IDs are deterministic within the source hashes, selected record locators, and build-definition IDs.

The builder executes IDENTITY, NUMERIC_PARSE, UNIT_CONVERSION, LOOKUP, and SPLIT transformations. CUSTOM transformations are not executable. Raw source values and per-value provenance are retained, including concrete CSV row/column or JSON Pointer locators. Each entity retains its definition ID, mapping version, source hash, mapping-plan hash, and source-inventory hash. Bundle-level build_provenance records the mapping-plan, inventory, and build-spec hashes.

The build report is always written. canonical_bundle.json is written only after structural and referential validation passes. The report also includes relationship diagnostics; duplicate and unreferenced findings are review-only and do not modify or merge records.

## Diagnose a canonical bundle

    dor diagnose-bundle --input canonical_bundle.json --out relationship_diagnostics.json

Diagnostics report exact-payload duplicate candidates and several classes of unused/unreferenced entities. They do not determine that two records are scientifically equivalent, and they never merge, delete, or rewrite entities.

## Reconcile canonical data

    dor reconcile-bundle --input canonical_bundle.json --out-dir path/to/new/derived/run/03_reconciliation

The command writes reconciliation_report.json and reconciliation_review_queue.csv. It detects:
- missing endpoint definitions and multiple endpoint definitions under the same target label;
- different reported values within the same experiment/target/endpoint/timepoint context;
- possible same-replicate/sample value conflicts when an explicit replicate_id or sample_id is present;
- multiple evidence extractions at the same exact source locator, including disagreements in quoted text or verification status;
- evidence records marked REVIEW_REQUIRED, CONFLICTING, or UNVERIFIED;
- canonical integrity errors, potential exact-payload duplicates, and unreferenced entities.

Differences without an explicit replicate/sample identity are labelled unresolved observation variation, not a confirmed conflict. Multiple endpoint definitions are kept separate. The engine creates review candidates only; it never chooses a source value, changes value_state, merges records, or updates modelling eligibility.

## Validate human decisions

    dor validate-reconciliation-decisions --decisions reconciliation_decisions.json --report reconciliation_report.json --bundle canonical_bundle.json --out decision_validation.json

The decision file must bind to the exact report SHA-256, and the report must reference the exact canonical bundle SHA-256. Every decision must identify an issue, reviewer, timestamp, rationale, and an allowed decision status. RESOLVED_WITH_EVIDENCE requires evidence IDs already present in the canonical bundle. Validation does not apply decisions or mutate canonical data.

## Source preservation

All commands read original sources. Audit and build outputs go to separate derived directories. The builder verifies source hashes before and after reading and refuses non-empty output directories. It never edits source CSV/JSON files.

## Interpretation boundary

A nested path or column is only a structural observation. It does not establish that a value is an experimental setpoint, measured local state, or valid model feature. Domain mapping, grouping, and relationship rules remain explicit scientific review decisions.


## V0.5 publication package and virtual condition operations

### Assemble an explicit Writing Skill package

Prepare a run-specific plan from ../templates/publication_package_plan.example.json, then run from the repository root:

    dor build-publication-package --plan publication_package_plan.json --workspace-root . --out-dir 06_publication/package

The builder copies only declared files. Complete/partial entries must point to existing source files under the workspace root; not-generated/not-applicable entries remain manifest-only. Review-required entries may be included with a source file or retained as unresolved. The output must be new or empty.

Audit the package with the integrity report outside the package:

    dor audit-publication-package --package-dir 06_publication/package --out 06_publication/package_integrity_report.json

A passing audit verifies hashes and package structure only; it does not certify scientific completeness or publication readiness.

### Predict a specified condition set

Prepare a query from ../templates/virtual_reproduction_query.example.json and use the exact output directory from dor fit-baselines:

    dor predict-virtual-condition --model-run-dir 04_modeling/baseline_run --query virtual_reproduction_query.json --out 06_publication/virtual_prediction.json

The query must match the model artifact's task/target/endpoint, feature IDs, and exact expected units. Numeric values must be finite JSON numbers. No implicit unit conversion, feature omission, or retraining is performed.

New model artifacts record feature ranges/category sets from train plus validation only; the held-out test set is excluded. Values outside numeric ranges and unknown categories are flagged, but the model may still return a mathematical estimate. Every report marks uncertainty NOT_CALIBRATED, checks only marginal feature domains, and explicitly states that a virtual prediction is not a physical experiment or atomistic simulation. Keep all warnings when transferring the report to the publication package.
