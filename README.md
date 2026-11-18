# Datafication-of-Reproducibility

An Antigravity-native, cross-disciplinary Skill for building traceable and reproducible analysis workflows from structured research data and source evidence.

DoR separates source-specific ingestion and domain semantics from the reusable scientific workflow. External adapters prepare data packages; project-provided profiles and reviewed mappings supply domain meaning; the DoR Runtime validates provenance and executes general-purpose data construction, analysis, validation, and publication operations.

## Non-negotiable architecture boundaries

- **Cross-disciplinary core:** no built-in subject-area vocabulary, material system, protocol, target definitions, domain mappings, or discipline-specific retrieval rules.
- **External adapters:** source-system readers and format converters are independently maintained and versioned outside the DoR core.
- **External domain profiles:** projects supply their own semantic definitions, mappings, and configuration. DoR does not bundle a default domain profile.
- **Deterministic execution:** Python performs structural validation, data construction, modelling, metrics, and artifact verification.
- **Guided scientific decisions:** Agents support planning and critical review; human approval remains required at declared decision gates.
- **Source preservation:** original files are read-only. Derived datasets, models, and reports are written to separate run workspaces.
- **Traceability:** every accepted result must link to exact source evidence, data, configuration, code version, and validation artifacts.

## Repository layout

- .agents/skills/datafication-of-reproducibility/SKILL.md — Antigravity Skill entry point.
- references/ — general methodology, data model, modelling, validation, evidence, orchestration, and publication specifications.
- schemas/ — machine-readable contracts, including the external adapter package contract.
- runtime/ — deterministic general-purpose Python engine.
- docs/ — implementation and workflow contracts.
- templates/ — generic project, workflow, and acceptance templates.

No project-specific source adapter or domain vocabulary is part of the supported core interface.

## Quick start

### Install the Runtime CLI

Requirements: Python 3.10 or newer. From the repository root, install the Runtime into the same Python environment that the active Antigravity terminal/Skill execution uses:

    python -m pip install -e ./runtime
    dor --help

The installation is editable, so Runtime source changes in this checkout are picked up without reinstalling. Ensure the Python environment's scripts directory is available on the shell PATH; otherwise the `dor` command will not be discoverable.

The supported workflow starts from an external Adapter Package. DoR does not ingest raw papers/SI or infer domain semantics; the package must contain already-prepared structured data or a complete, provenance-bound Canonical Bundle.

1. Install this Skill in the active Antigravity project under `.agents/skills/datafication-of-reproducibility/` (or the Antigravity global Skill directory).
2. Prepare the Adapter Package using [the Adapter Contract](docs/ADAPTER_CONTRACT.md). Keep package sources read-only.

   When the structured CSV/JSON outputs and provenance files already exist but no adapter manifest has been created, initialize a manifest from only the explicitly selected files:

       dor init-adapter-package --package-root <package_root> --adapter-id <preparation_process_id> --adapter-version <version> --source <source_id>=<source_file> --artifact <artifact_id>=standardized_dataset=<package_relative_csv_or_json>

   Repeat `--source` and `--artifact` for each selected file. The package directory and files must already exist. Relative paths for sources, artifacts, and `--out` resolve from the package root; use an absolute path for an external provenance source. Artifact paths must resolve inside the package root. The manifest itself must be a direct child of the package root (a custom `--out` may change its filename, not its directory), because the formal Run binds the package root from the manifest's parent. This command records file identities and hashes only; it does not scan directories, convert files, infer field meanings, or read original-document contents. Then continue with `dor prepare-adapter-handoff` below.
3. Resolve the route before creating a Run:

       dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <project_root>/run_control/adapter_route_preflight.json

   Inspect the handoff's `route` field. The next command selects the matching official template automatically; do not copy or manually edit the stage graph. The default controlled one-Study profile preserves G0-G4 and Worker review while recording unsupported cross-Study modelling/interaction as explicit `NOT_APPLICABLE`, never as fabricated results.
4. Generate a project-specific Run Plan from the validated handoff instead of editing the 22–31-stage template manually. The default is the conservative `CONTROLLED_SINGLE_STUDY` profile:

       dor init-run-plan --adapter-handoff <project_root>/run_control/adapter_route_preflight.json --project-root <project_root> --run-root <new_run_root>

   This selects the correct Structured Dataset or Canonical Bundle template, copies its matching Publication Plan blueprint into project configuration, creates an empty `configuration/semantic_registry.json` only when none exists, validates and preserves existing Registry content, binds the Registry as a hash-protected source input to Discovery, sets exact source roots and manifest paths, and validates the result with the Runtime's own Run Plan validator. Populate the Registry with reviewed metadata before `dor run-init`; the empty Registry is valid and means semantic review data have not been supplied. It does not approve scientific scope or create Gate decisions. For a multi-Study analysis whose independent Study structure is already established, explicitly choose `FULL_ANALYSIS` and provide the existing virtual query:

       dor init-run-plan --adapter-handoff <project_root>/run_control/adapter_route_preflight.json --project-root <project_root> --run-root <new_run_root> --profile FULL_ANALYSIS --virtual-query-input <project_root>/configuration/virtual_reproduction_query.json

   For V1.0 Acceptance, supply each provenance-only source explicitly with repeated `--acceptance-source SOURCE_ID=ROLE=FILE_PATH` arguments; roles are `PRIMARY_PAPER`, `SUPPLEMENTARY_INFORMATION`, `STRUCTURED_DATA`, or `OTHER`. The files are hash-snapshotted only; their contents are never opened by DoR or passed to a Worker. A project-owned Publication Plan blueprint can be supplied with `--publication-plan-template`. The Run Plan is never overwritten; use a new output path for a new configuration. The Run workspace must remain outside all protected source roots.
5. Preflight and initialize the generated Run Plan:

       dor validate-execution-contract --plan <configured_run_plan.json>
       dor run-init --plan <configured_run_plan.json> --run-root <new_run_root>
       dor run-verify --manifest <new_run_root>/run_manifest.json
       dor run-resume-plan --manifest <new_run_root>/run_manifest.json

6. Use `dor run-advance --manifest <run_root>/run_manifest.json` to execute configured local stages in dependency order. The Runtime derives CLI arguments directly from the machine-readable execution contract and active Run Artifact paths; supported routes do not require per-stage argument files. It records stage outcomes automatically and pauses at human review, Worker authorization, unapproved Gate, or an unresolved user choice. Complete the requested human/Worker action, record its outcome, then run `run-advance` again. After Worker review and human disposition, the `publication_plan_preparation` stage asks you to copy the selected blueprint to `<run_root>/10_publication/publication_package_plan.json`, bind each included file to its exact Run Artifact ID/path, and validate it with `dor validate-publication-plan`; G4 then approves that exact plan and its source set before package assembly. Never bypass G0-G4 or auto-dispatch a Worker. See [Run Plan execution bindings](docs/RUN_PLAN_EXECUTION_BINDINGS.md).
7. At completion, generate the artifact and usage reports:

       dor run-artifacts --manifest <run_root>/run_manifest.json --out <run_root>/artifact_manifest.json
       dor run-usage --manifest <run_root>/run_manifest.json --out <run_root>/run_usage_report.json

8. After all Run stages are current or explicitly SKIPPED, prepare the V1.0 source-selection and structured extraction-review records from the exact Run source snapshot, then initialize the separate Acceptance record and revision ledger:

       dor init-acceptance --manifest <run_root>/run_manifest.json --out <acceptance_root>/acceptance_record.json --source-selection-manifest <acceptance_root>/source_selection_manifest.json --extraction-review-record <acceptance_root>/extraction_review_record.json --actor "<reviewer>" --rationale "Initialize acceptance for the completed Run"
       dor validate-acceptance --record <acceptance_root>/acceptance_record.json --run-manifest <run_root>/run_manifest.json --ledger <acceptance_root>/acceptance_record_acceptance_events.jsonl --out <acceptance_root>/acceptance_validation_report.json

The initializer derives Study IDs from the Run Canonical Bundle, binds the final Run Event and G0-G4 Gate ledgers, validates the two post-Run evidence files against the immutable provenance-only source snapshot, and leaves all scientific Acceptance stages NOT_STARTED. Human review, revision registration, final decision, and detached checkpoint remain required. See [V1.0 Controlled Acceptance](docs/V1.0_CONTROLLED_ACCEPTANCE.md).

The selected Publication Plan blueprint is recorded as the immutable `publication_plan_template` input. The final `publication_plan` is a separate Run Artifact created after Worker/human review, so optional G3 outputs are represented honestly as either current files or `not_generated` entries before G4.

The detailed stage commands, review packet formats, Worker hand-off, recovery, and publication package audit are specified in the operator guide and the Skill's phase references.

## Scientific safeguards

- Missing information is not silently imputed as reported fact.
- Source labels are not assumed to fully describe the underlying system or state.
- Statistical associations and predictive interactions are not automatically interpreted as causation or mechanism.
- Records from the same Study remain together during Study-level validation unless a justified alternative is documented.
- The Runtime does not infer semantic mappings from identifiers, filenames, or sampled values.
- Publication prose is generated from structured research records, not from recollection of source code or chat history.
- A passing structural validator, hash check, or synthetic test is not proof of scientific validity.

## External adapter interface

The adapter package contract is defined in schemas/adapter_package.schema.json and docs/ADAPTER_CONTRACT.md.

Validate an adapter package with:

    dor validate-adapter-package --manifest path/to/adapter_manifest.json --package-root path/to/package --out path/to/reports/adapter_validation.json

The validator checks package structure, path safety, file availability, and exact hashes. It does not interpret research semantics or approve mappings.

## Exploratory discovery

The domain-neutral discovery entry point accepts a validated Canonical Bundle and an optional independent Semantic Registry:

    dor validate-semantic-registry --registry path/to/semantic_registry.json
    dor discover-opportunities --bundle path/to/canonical_bundle.json --semantic-registry path/to/semantic_registry.json --out-dir path/to/new/discovery_run

Formal Runs consume their hash-protected `semantic_registry` source artifact automatically.

DOR itself profiles the full Canonical Bundle and generates Study-aware condition/outcome contrasts, within-Study/System numeric trends, exact Study-level sign tests, Benjamini-Hochberg q-values, Study-bootstrap intervals, ranked research opportunities, and an Observation-to-Study evidence ledger. It does not rely on an Agent to calculate or invent research questions. Before inferential testing and FDR correction, the Runtime excludes explicit target/condition identity and exact same-unit value identity as structural self-associations; these exclusions are retained in `research_opportunities.json` with reason codes and coverage counts. A perfect rank correlation alone is not sufficient for exclusion. Broader deterministic derivations require explicit provenance metadata and domain review. Canonical IDs are compared exactly; case, punctuation, and whitespace are not normalized for identity decisions. Exact reciprocal patterns across different endpoint/timepoint contexts are reported in `related_opportunity_groups` for review while preserving both hypotheses and their separate inferential results. An external Semantic Registry is applied to an in-memory Bundle copy, hash-recorded, and never written back to the Canonical Bundle. The Agent reviews and challenges these Runtime-generated candidates; the user selects a direction before a Modeling Task and endpoint-specific Cohort are initialized. Exploratory outputs do not approve a formal analysis task or cross G0-G4 gates. See docs/SCIENTIFIC_DISCOVERY_ENGINE.md.

## Run Manager

The Runtime provides explicit project Run workspaces, immutable plan/source snapshots, a hash-chained Run Event Ledger, contract-bound local Stage execution via `dor run-advance`, bounded Worker authorization packets, dependency-aware resume planning, condition-driven stages with hash-bound SKIPPED events, and regenerable artifact inventories. Supported local commands and argv are taken only from the route/profile execution contract; the Runner never invokes a shell. Manual stages remain human-operated, and Worker execution remains an explicit host Worker Manager action after authorization. The Run Manager does not crawl workspaces or create scientific approvals. Optional provenance-only `acceptance_source_artifacts` are separately hash-bound for post-Run Acceptance and are never computational Stage inputs. See docs/V0.9_RUN_MANAGER.md and docs/RUN_PLAN_EXECUTION_BINDINGS.md.

## Controlled acceptance

The V1.0 controlled acceptance protocol defines a fixed evidence-backed review sequence, a machine-readable acceptance record, and deterministic validation. A controlled pilot validates only its declared scope; it does not establish broader cross-Study validity without enough independent Studies. See docs/V1.0_CONTROLLED_ACCEPTANCE.md.

## Architecture and standards review

The implementation inventory, standards alignment, capability boundaries, and target architecture are documented in:

- docs/PROJECT_CAPABILITY_AUDIT.md
- docs/STANDARDS_ALIGNMENT.md
- docs/TARGET_ARCHITECTURE.md

DoR's core remains domain-neutral. Concrete adapters, project configurations, and domain profiles must be maintained outside this repository.
