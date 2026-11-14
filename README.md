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

1. Install the Skill into a workspace under .agents/skills/ or the Antigravity global Skill directory.
2. Select or develop an external adapter for the project's source format.
3. Prepare an adapter package and validate its manifest and exact hashes.
4. Audit source structure and review the generated inventory.
5. Supply project-owned semantic mappings and explicit entity-grain decisions.
6. Continue through the approval-gated canonical and analysis workflow.

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
