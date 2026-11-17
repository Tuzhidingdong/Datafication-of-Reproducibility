---
name: datafication-of-reproducibility
description: Provides a discipline-neutral workflow for traceable research data, evidence, canonical representation, analysis planning, validation, reproducibility assessment, human review, and publication hand-off. Use for empirical research workflows that can be represented faithfully by the current generic Study/System/Condition/Experiment/Observation model; keep project-specific scientific semantics in external Adapters.
---

# Datafication of Reproducibility

You are operating a guided, evidence-centred research workflow. The purpose is to preserve traceable sources, explicit relationships, reported context, and outcome definitions so that scientific claims can be reviewed and reproduced. Predictive analysis is optional and must only run when the current generic representation and explicit task contract are scientifically appropriate.

## Non-negotiable project decisions

- Platform: Antigravity Workspace Skill.
- Cross-disciplinary boundary (immutable): DoR core Skill, Runtime, schemas, Run Plans, fixtures, and documentation may contain only discipline-neutral workflow, provenance, data-integrity, analysis-validation, and review contracts. Never embed field-specific scientific knowledge, vocabulary, entity taxonomies, field names, dataset examples, or research assumptions. Keep all such knowledge in user-owned project configuration/profiles or independently maintained external adapters. This boundary must not be weakened by feature work.
- Execution: hybrid. Deterministic data work and model computation are performed by local Python. Agents are used for scientific planning, semantic interpretation, critical review, and mechanism reasoning.
- Automation: guided. Stop at the approval gates defined in the workflow reference.
- Source data: preserve. Original CSV, JSON, paper files, SI, images, and evidence packages are read-only. All derived data and outputs go to a separate run directory.
- **Structured-data-only boundary (immutable):** DoR consumes already prepared structured datasets (such as CSV/JSON), declared schemas/data dictionaries, project configuration, and supplied structured evidence/locator metadata. DoR must never open, parse, render, OCR, index, search, summarize, or send original papers, SI, or other raw research documents to an LLM or Worker. Such files may be registered as provenance assets; permitted handling is limited to filesystem metadata, existence checks, and byte-level SHA-256 calculation. Locators are opaque references and must never trigger dereferencing. Missing or ambiguous information is reported for upstream structured-data preparation; it is never repaired by reading the original.
- Publication output: every completed analysis must produce a traceable scientific record and a publication package with both a human-readable writing guide and a machine-readable manifest for a downstream Writing Skill.

## Operating rules

1. Start by identifying the project configuration and the selected domain profile. Do not assume a scientific domain from filenames alone.
2. Read only the references needed for the current stage. Keep the active context small.
3. Inspect only declared structured data artifacts, their schemas/data dictionaries, project configuration, and supplied structured evidence before proposing transformations. Do not infer unseen schemas or invent field mappings. Original papers, SI, images, and other raw research documents are provenance-only assets: never open, parse, render, OCR, index, search, summarize, or pass their contents to an LLM/Worker.
4. For a bounded real-data pilot, reuse source identifiers, explicit original-source location and asset-role fields, declared SI associations, and structured record links already present in declared inputs/configuration. Select one candidate automatically using explicit metadata relationships and linked structured-record coverage. A generic evidence filename, path/basename, extension, or derivative/preprocessed analysis artifact does not establish that an original primary paper or SI is registered; when original-source roles/paths cannot be distinguished in structured metadata, report the association as UNRESOLVED. Apply the deterministic tie-break using normalized source identifier and then normalized original-source path. For original paper/SI assets, check only the registered path, filesystem metadata, and byte-level SHA-256; never test content readability by opening/parsing the document or infer authenticity from its contents. Mark identifier-derived paths as derived, not source-provided. Do not ask the user to repeat existing metadata. Keep selection bounded and report exclusions; it does not approve scientific scope or bypass human gates.
5. Preserve original values, units, qualifiers, evidence links, and missingness states. Never silently convert an unreported value into an estimated fact.
6. Distinguish Study, System, Experimental Condition, and Observation. One row in an input table is not automatically an independent experimental replicate.
7. Distinguish reported descriptors from inferred or unobserved states. A reported value or label is not proof that every relevant state variable was directly controlled or measured.
8. A statistical interaction is a candidate relationship, not automatically a causal mechanism.
9. Keep all records from the same study/DOI together during study-level validation unless a scientifically justified alternative is documented.
10. Do not run expensive or broad modelling before the data audit and analysis-plan gates are approved.
11. Do not send complete CSV/JSON datasets or large structured evidence collections into an LLM context. Use deterministic local processing to compute summaries and pass only small, task-specific structured evidence packets to Agents/Workers. Never send original paper/SI or other raw research-document bytes, extracted full-text dumps, page images, or OCR output to an LLM/Worker as part of a DoR stage.
12. Every scientific finding must link to supporting data, analysis configuration, code/runtime version, validation results, and source evidence.
13. Generate Methods/Results text from recorded facts and outputs, never from memory of source code or chat history.
14. A downstream Writing Skill must be able to use the publication package without reading this Skill's source code or recovering prior conversations.

## Stage execution reference routing

The core Skill contains the immutable decisions and operating rules. Load only the phase reference needed for the current action; do not load every execution reference at the start of a Run. Each reference preserves the detailed approval, evidence, provenance, and failure-handling requirements.

- Before a Run, for pre-Run Discovery, adapter handoff, route selection, review packet preparation, or Run initialization: read [Execution entry and Adapter routing](execution-entry-and-adapter.md).
- For source audit, mapping, Canonical construction, and reconciliation: read [Data audit and Canonical workflow](execution-data-and-canonical.md).
- For Cohort review, modelling, cross-Study validation, Interaction analysis, and mechanism evidence: read [Modelling and scientific interpretation](execution-modeling-and-interactions.md).
- For virtual condition scenarios and publication hand-off (including the FULL_ANALYSIS Virtual Query dual-path decision, G2 Query Review Ready vs G3/G4 Prediction Consumer Ready, formal SKIPPED evidence, and Worker/Review/Publication conditional inputs): read [Virtual and publication workflow](execution-virtual-and-publication.md).
- When recording approvals, dispatching a Worker, dealing with missing information, or deciding whether to stop: read [Approval and governance rules](execution-governance.md).
- For recovery, final project acceptance, or acceptance-record revisions: read [Run Manager and controlled acceptance](execution-run-manager-and-acceptance.md).

The current Canonical and analysis-engine boundaries are described in [Cross-disciplinary scope and Adapter boundary](../../../docs/CROSS_DISCIPLINARY_SCOPE.md); do not force unsupported research structures into the model. The machine-checked stage-to-action contract is `runtime/src/dor/stage_execution_contract.json`; `dor run-init` validates it before initializing either supported adapter route. For a template preflight, use `dor validate-execution-contract --plan <run_plan.json>`. The operator guide remains at `../../../docs/RUN_PLAN_EXECUTION_BINDINGS.md`.

Do not infer a missing stage command, bypass a gate, or substitute an unapproved Worker action simply because a phase reference was not loaded. Read the relevant reference before dispatch.
