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

## External adapter packages

DoR consumes packages prepared by independently maintained adapters. The package contract is in ../schemas/adapter_package.schema.json and ../docs/ADAPTER_CONTRACT.md.

    dor prepare-adapter-handoff --manifest path/to/adapter_manifest.json --package-root path/to/package --out path/to/run/00_adapter/adapter_handoff.json

This validates the external package, verifies exact source/artifact SHA-256 hashes, and selects one generic route:
- `STRUCTURED_DATASET`: one or more declared CSV/JSON `standardized_dataset` artifacts. The audit entry processes all of them in one run.
- `CANONICAL_BUNDLE`: exactly one JSON `canonical_bundle` artifact. The Canonical Bundle receives structural/reference validation and can be sent directly to Discovery.

The handoff is a data-routing and integrity result only. It does not interpret scientific semantics or approve mappings.

## Exploratory discovery

Use a validated Canonical Bundle as the shared input to exploratory profiling and the formal analysis workflow:

    dor discover-opportunities --bundle path/to/canonical_bundle.json --out-dir path/to/new/discovery_run

For a Canonical Bundle supplied inside an external adapter package, use the hash-rechecking handoff:

    dor discover-opportunities --adapter-handoff path/to/run/00_adapter/adapter_handoff.json --out-dir path/to/new/discovery_run

The scan validates canonical structure and references, hashes the input before and after processing, writes aggregate-only profiles and a bounded Agent brief, and refuses to overwrite a non-empty output directory. It does not create a formal Run or cross G0-G4 approval gates.

## Run Manager and conditional stage execution

Declare the complete Run DAG in a Run Plan and initialize a new isolated workspace:

    dor run-init --plan run_plan.json --run-root path/to/new/run
    dor run-verify --manifest path/to/new/run/run_manifest.json

The Run Manager binds the immutable plan and protected source hashes to an append-only, hash-chained `run_events.jsonl`. Use `dor run-stage-record` to record each declared stage as RUNNING, SUCCEEDED, FAILED, or—only for a conditional stage whose activation evaluates false—SKIPPED. Successful stage records bind exact input and output hashes. A skipped stage has no outputs and does not satisfy artifact dependencies or create an approval.

A stage may declare a generic activation condition:

    "activation": {
      "artifact_id": "review_decision",
      "json_pointer": "/selected_ids",
      "operator": "array_non_empty"
    }

The activation artifact must also appear in that stage's declared inputs and must already have a currently reusable producer. Supported operators are `exists`, `not_exists`, `array_non_empty`, `array_empty`, `boolean_true`, `boolean_false`, `equals`, and `not_equals`. JSON Pointer lookup and the observed activation-value digest are recorded. Run Manager does not create or edit the condition input.

On resume, use:

    dor run-status --manifest path/to/run/run_manifest.json
    dor run-resume-plan --manifest path/to/run/run_manifest.json
    dor run-artifacts --manifest path/to/run/run_manifest.json --out path/to/run/artifact_manifest.json

The resume plan distinguishes waiting for activation input, SKIP_REQUIRED, SKIPPED, gate-blocked, ready, reusable, and rebuild states. Record SKIPPED only when the calculated action is SKIP_REQUIRED:

    dor run-stage-record --manifest path/to/run/run_manifest.json --stage optional_stage --status SKIPPED --producer-kind local --reason "Declared activation condition evaluated false."

For manual conditional stages, use `--producer-kind manual`. A SKIPPED event remains terminal only while the activation input hash and false condition remain unchanged. If the condition becomes true later, the resume plan makes the stage READY_TO_RUN after its dependencies and required gate are satisfied.

Worker stages still require a separate explicit `dor run-worker-authorize` action and write only into their declared `worker_staging/<stage_id>/` paths. Run Manager records execution provenance; it does not start Workers, execute arbitrary commands, or create G0-G4 decisions.

The two formal adapter templates include the conditional post-selection stages. An empty candidate-selection array skips them; a non-empty array activates preparation and, after explicit G3 approval, the declared follow-on analysis stages. See ../docs/RUN_PLAN_EXECUTION_BINDINGS.md for the exact stage-to-command contract.

## Setup

From the repository root:

    python -m venv .venv
    # Activate the environment using your operating system's normal command.
    python -m pip install -e ./runtime

The current runtime uses the Python standard library only.

## Run a read-only audit

    dor audit --csv path/to/input.csv --json path/to/input.json --out path/to/separate/run/01_audit

Either input may be omitted, but at least one must be supplied. Output must be a separate derived-data directory. The audit produces dataset_manifest.json, data_audit_report.md, source_inventory.json, and mapping_review_queue.csv, plus the CSV/JSON-specific profile files when those sources are supplied.

To audit every supported `standardized_dataset` artifact declared by an adapter package:

    dor audit --adapter-handoff path/to/adapter_handoff.json --out path/to/separate/run/01_audit

This route rechecks the handoff, source and artifact hashes, audits all declared CSV/JSON standardized datasets, and keeps their artifact IDs and package-relative paths in the source inventory.

For an external package that already provides a Canonical Bundle and the matching provenance artifacts, materialize selected artifacts into a new Run workspace:

    dor materialize-adapter-artifacts --adapter-handoff path/to/adapter_handoff.json --role source_inventory --role mapping_plan --role build_spec --role canonical_bundle --out-dir path/to/run/00_adapter/materialized

Each requested role must resolve to exactly one JSON artifact. Files are copied without transformation and each copied file is verified against the package SHA-256. Every row in the imported Source Inventory is also matched to a declared Adapter Manifest source/artifact by exact path, file SHA-256, and format. Use `templates/run_plan.canonical_adapter.example.json` for this formal, approval-gated route; it retains G0/G1/G2 and checks the bundle's provenance against the exact G1-approved inventory, mapping plan, and build specification.

## Validate a canonical bundle

    dor validate-bundle --input canonical_bundle.json --out validation_report.json

This checks required entity fields, duplicate IDs, broken references, selected relationship inconsistencies, missingness states, comparison size, and evidence locator presence. It is structural/referential validation, not scientific validation or full JSON Schema validation.

## Validate a mapping plan

    dor validate-mapping --plan mapping_plan.json --inventory source_inventory.json --out mapping_validation.json

The plan must contain the SHA-256 digest of the exact inventory file. Regenerating or editing that inventory invalidates the plan's digest. Only approved rules with valid references, targets, explicit transformations, and review metadata are eligible. Any error fails closed and produces no eligible rule IDs.

## Validate a canonical Build Spec

    dor validate-build-spec --plan mapping_plan.json --inventory source_inventory.json --spec canonical_build_spec.json --out build_spec_validation.json

This checks the exact mapping-plan and inventory hashes, entity source declarations, CSV/JSON selectors, grouping keys, mapping-rule compatibility, and relationship declarations. It does not read source datasets or create a canonical bundle. The G1 gate recomputes this report against the exact bound artifacts and refuses stale or non-deterministic reports.

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


## V0.6 end-to-end synthetic acceptance

The development test suite contains a complete temporary-project workflow that executes the dor CLI commands from CSV/JSON audit through explicit mapping, canonical construction, reconciliation, Study-level cohort/model evaluation, interaction discovery, robustness, response surface, mechanism evidence, virtual prediction, and publication-package integrity audit.

The fixture uses eight synthetic discovery Studies and one separate probe Study. Its CSV and JSON sources, mapping plan, build specification, task, mechanism plan, and query are generated under a temporary directory. It checks exact cross-file keys, canonical reference integrity, Study leakage boundaries, Evidence links, provenance hash rejection, source-file immutability, package tamper detection, and CLI command registration.

Run only as a development/CI acceptance test:

    python -m unittest discover -s runtime/tests -p 'test_end_to_end_synthetic_project.py' -v

Run the complete runtime suite:

    python -m unittest discover -s runtime/tests -v

The fixture is artificial and is not a substitute for scientific review or V1.0 acceptance on the real literature corpus. It does not test Antigravity GUI interaction or Worker orchestration.


## V0.7 hash-bound human approval gates

Maintain one ledger per project run (outside raw-source directories). After explicit user approval of scope and audit artifacts, record G0:

    dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G0 --decision APPROVE --reviewer "human-reviewer" --rationale "Reviewed scope and source inventory." --artifact dataset_manifest=01_audit/dataset_manifest.json --artifact source_inventory=01_audit/source_inventory.json

Exact artifact requirements and additional commands are documented in ../docs/V0.7_APPROVAL_GATES_AND_SCIENTIFIC_CONTRACTS.md. Each event records absolute artifact paths and SHA-256 hashes, the reviewer/rationale/timestamp, an upstream decision dependency, and a ledger-wide hash-chain link. Inspect status with:

    dor gate-status --workflow-ledger workflow_gate_ledger.jsonl

Gated CLI operations fail closed unless a current approval exists. A modified or missing artifact makes its approval stale; a changed upstream decision blocks downstream approvals. The reviewer field is self-declared, not authenticated. This is an integrity/provenance record, not a cryptographic signature system.

`--allow-untracked-legacy` exists only for archived pre-V0.7 scripts and compatibility tests. Do not use it in a research run. The Antigravity Skill must obtain explicit user decisions before executing `gate-record`; an Agent, Worker, completed command, or silence cannot approve a gate.

Cohort reports include non-destructive Observation/Condition grain diagnostics. Repeated records remain separate; explicit identifiers are reported but do not establish replication or independence.


## V0.8 cross-artifact approval checks

Approval events now verify the relationships between the bound files, not only their individual hashes. G1 re-runs mapping validation and verifies mapping-plan/inventory/build-spec hash links. G2 verifies that reconciliation refers to the exact canonical bundle and that canonical build provenance matches G1. G3 binds interaction and repeated-seed robustness reports plus manifests, then verifies both derive from the G2-approved task and the same cohort/split artifacts. The selection record uses schema version 1.1 and binds both report hashes.

The full synthetic CLI acceptance path now records G0–G4 and invokes gated commands with the real ledger; it does not use \`--allow-untracked-legacy\`. See ../docs/V0.8_APPROVED_WORKFLOW_ACCEPTANCE.md.


## V0.9 project Run Manager

Create a fully explicit run plan before execution, then initialize a separate run workspace:

    dor run-init --plan run_plan.json --run-root path/to/new/run

The plan declares protected source roots/files, the complete stage DAG, direct dependencies, exact artifact IDs, output paths, executor types, and optional G0-G4 requirements. The Runtime does not infer stage boundaries or discover files by crawling directories.

For each stage, use dor run-stage-record to record RUNNING, SUCCEEDED, or FAILED. Successful completion hashes every declared input and output. The append-only run_events.jsonl ledger records attempts separately from the G0-G4 scientific approval ledger.

For a Worker stage, first display and obtain explicit user authorization for the role, provider, model, project root, exact inputs, and staging outputs. Then use dor run-worker-authorize to create a bounded task packet. This command records authorization but does not start a Worker. Worker writes are confined to new files under worker_staging/<stage_id>/. A separate manual stage must review and promote accepted outputs.

On resume, run dor run-verify, dor run-status, and dor run-resume-plan. Reuse only stages marked REUSE. Rebuild stale stages and their declared downstream dependents; independent stages remain reusable. RUNNING attempts require external process inspection before --confirm-abandoned is used. Changed source files require a new run.

See ../docs/V0.9_RUN_MANAGER.md and ../schemas/run_plan.schema.json.


Generate the current declared artifact inventory with:

    dor run-artifacts --manifest run_manifest.json --out artifact_manifest.json

It lists source and derived artifacts by ID/path/producer, expected and actual SHA-256, and current/missing/stale/unrecorded status. It is a regenerable projection of the immutable plan and run event ledger. A stage marked REBUILD_REQUIRED must have its existing declared outputs archived/moved before a new attempt; the Runtime never overwrites an existing output. Stage attempts are also bound to the exact required G0-G4 approval event hash, so a later reapproval forces re-execution.

The resume planner reports `SOURCE_CHANGED_NEW_RUN_REQUIRED` when a declared source input no longer matches its run-init snapshot. Do not rebuild against changed source data inside the same run; initialize a new Run.


The first run event is RUN_INITIALIZED. It hash-binds the Run Manifest's source snapshot, plan hash, workspace, workflow-ledger path, and stage order. Every Runtime operation compares the manifest against this event before trusting any stage status.\n