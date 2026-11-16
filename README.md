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
3. Resolve the route before creating a Run:

       dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <project_root>/run_control/adapter_route_preflight.json

   Use the handoff's `route` field, then select the execution profile. For a multi-Study analysis with sufficient independent Studies, use `templates/run_plan.example.json` (`STRUCTURED_DATASET`) or `templates/run_plan.canonical_adapter.example.json` (`CANONICAL_BUNDLE`). For a controlled one-Study pilot, use `templates/run_plan.single_study.example.json` or `templates/run_plan.canonical_adapter.single_study.example.json`; these preserve G0-G4 and Worker review while recording cross-Study modelling/interaction as explicit `NOT_APPLICABLE`, never as fabricated results.
4. Configure the selected template from the active project. Set its `source_roots`, `workflow_ledger_path`, and exact absolute paths for `adapter_package_manifest`, `virtual_query_input`, and `publication_plan`. Do not reuse a prior Run workspace.
5. Preflight and initialize a new Run:

       dor validate-execution-contract --plan <configured_run_plan.json>
       dor run-init --plan <configured_run_plan.json> --run-root <new_run_root>
       dor run-verify --manifest <new_run_root>/run_manifest.json
       dor run-resume-plan --manifest <new_run_root>/run_manifest.json

6. Use `dor run-advance --manifest <run_root>/run_manifest.json --args-dir <run_control>/stage_arguments` to execute configured local stages in dependency order. The Skill prepares one JSON argv array per local stage from the Run Manager action bindings. The runner records stage outcomes automatically and pauses at human review, Worker authorization, unapproved Gate, or missing stage arguments. Complete the requested human/Worker action, record its outcome, then run `run-advance` again. Never bypass G0-G4 or auto-dispatch a Worker. See [Run Plan execution bindings](docs/RUN_PLAN_EXECUTION_BINDINGS.md).
7. At completion, generate the artifact and usage reports:

       dor run-artifacts --manifest <run_root>/run_manifest.json --out <run_root>/artifact_manifest.json
       dor run-usage --manifest <run_root>/run_manifest.json --out <run_root>/run_usage_report.json

For a controlled one-Study pilot, also choose the matching Publication Plan template: `templates/publication_package_plan.single_study.example.json` for Structured Dataset or `templates/publication_package_plan.canonical_adapter.single_study.example.json` for Canonical Bundle. Bind the active Run/Project IDs and exact selected-source hashes before Run initialization.

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

The domain-neutral discovery entry point accepts a validated Canonical Bundle:

    dor discover-opportunities --bundle path/to/canonical_bundle.json --out-dir path/to/new/discovery_run

It produces aggregate-only profiles and candidate signals. The same canonical data artifact can be registered in a formal Run Plan and passed into downstream reconciliation, cohort construction, modelling, validation, and publication. Exploratory results do not approve a formal analysis task or cross G0-G4 gates. See docs/SCIENTIFIC_DISCOVERY_ENGINE.md.

## Run Manager

The Runtime provides explicit project run workspaces, a hash-chained run event ledger, stage-attempt recording, bounded Worker authorization packets, dependency-aware resume planning, condition-driven stages with hash-bound SKIPPED events, and regenerable artifact inventories. Run plans declare every source, artifact, stage, dependency, and activation input. The Run Manager does not crawl workspaces, execute stages, dispatch Workers, or create scientific approvals. See docs/V0.9_RUN_MANAGER.md and docs/RUN_PLAN_EXECUTION_BINDINGS.md.

## Controlled acceptance

The V1.0 controlled acceptance protocol defines a fixed evidence-backed review sequence, a machine-readable acceptance record, and deterministic validation. A controlled pilot validates only its declared scope; it does not establish broader cross-Study validity without enough independent Studies. See docs/V1.0_CONTROLLED_ACCEPTANCE.md.

## Architecture and standards review

The implementation inventory, standards alignment, capability boundaries, and target architecture are documented in:

- docs/PROJECT_CAPABILITY_AUDIT.md
- docs/STANDARDS_ALIGNMENT.md
- docs/TARGET_ARCHITECTURE.md

DoR's core remains domain-neutral. Concrete adapters, project configurations, and domain profiles must be maintained outside this repository.
