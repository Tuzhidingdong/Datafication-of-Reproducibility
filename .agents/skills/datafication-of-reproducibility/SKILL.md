---
name: datafication-of-reproducibility
description: Reconstructs reproducible relationships between experimental conditions, interacting processes, and observable outcomes from scientific datasets and literature. Use when auditing research data, planning condition-to-outcome modelling, discovering robust interactions, interpreting mechanisms, validating predictions, or preparing a traceable publication package.
---

# Datafication of Reproducibility

You are operating a guided scientific research workflow. The purpose is not merely to maximize predictive accuracy. It is to learn the reproducible structure of experimental phenomena: how reported conditions, incompletely observed physical states, and interacting processes jointly relate to observable outcomes.

## Non-negotiable project decisions

- Platform: Antigravity Workspace Skill.
- Cross-disciplinary boundary (immutable): DoR core Skill, Runtime, schemas, Run Plans, fixtures, and documentation may contain only discipline-neutral workflow, provenance, data-integrity, analysis-validation, and review contracts. Never embed field-specific scientific knowledge, vocabulary, entity taxonomies, field names, dataset examples, or research assumptions. Keep all such knowledge in user-owned project configuration/profiles or independently maintained external adapters. This boundary must not be weakened by feature work.
- Execution: hybrid. Deterministic data work and model computation are performed by local Python. Agents are used for scientific planning, semantic interpretation, critical review, and mechanism reasoning.
- Automation: guided. Stop at the approval gates defined in the workflow reference.
- Source data: preserve. Original CSV, JSON, paper files, and evidence packages are read-only. All derived data and outputs go to a separate run directory.
- Publication output: every completed analysis must produce a traceable scientific record and a publication package with both a human-readable writing guide and a machine-readable manifest for a downstream Writing Skill.

## Operating rules

1. Start by identifying the project configuration and the selected domain profile. Do not assume a scientific domain from filenames alone.
2. Read only the references needed for the current stage. Keep the active context small.
3. Inspect source files before proposing transformations. Do not infer unseen schemas or invent field mappings.
4. Preserve original values, units, qualifiers, evidence links, and missingness states. Never silently convert an unreported value into an estimated fact.
5. Distinguish Study, System, Experimental Condition, and Observation. One row in an input table is not automatically an independent experimental replicate.
6. Distinguish reported experimental labels from the complete real physical state. A reported setpoint is not proof that every local state variable was directly controlled or measured.
7. A statistical interaction is a candidate relationship, not automatically a causal mechanism.
8. Keep all records from the same study/DOI together during study-level validation unless a scientifically justified alternative is documented.
9. Do not run expensive or broad modelling before the data audit and analysis-plan gates are approved.
10. Do not send complete CSV/JSON datasets or large source files into an LLM context. Use Python to compute summaries and pass small, task-specific evidence packets to Workers.
11. Every scientific finding must link to supporting data, analysis configuration, code/runtime version, validation results, and source evidence.
12. Generate Methods/Results text from recorded facts and outputs, never from memory of source code or chat history.
13. A downstream Writing Skill must be able to use the publication package without reading this Skill's source code or recovering prior conversations.


## Stage execution reference routing

The core Skill contains the immutable decisions and operating rules. Load only the phase reference needed for the current action; do not load every execution reference at the start of a Run. Each reference preserves the detailed approval, evidence, provenance, and failure-handling requirements.

- Before a Run, for pre-Run Discovery, adapter handoff, route selection, review packet preparation, or Run initialization: read [Execution entry and Adapter routing](execution-entry-and-adapter.md).
- For source audit, mapping, Canonical construction, and reconciliation: read [Data audit and Canonical workflow](execution-data-and-canonical.md).
- For Cohort review, modelling, cross-Study validation, Interaction analysis, and mechanism evidence: read [Modelling and scientific interpretation](execution-modeling-and-interactions.md).
- For virtual condition scenarios and publication hand-off: read [Virtual and publication workflow](execution-virtual-and-publication.md).
- When recording approvals, dispatching a Worker, dealing with missing information, or deciding whether to stop: read [Approval and governance rules](execution-governance.md).
- For recovery, final project acceptance, or acceptance-record revisions: read [Run Manager and controlled acceptance](execution-run-manager-and-acceptance.md).

The machine-checked stage-to-action contract is `runtime/src/dor/stage_execution_contract.json`; `dor run-init` validates it before initializing either supported adapter route. For a template preflight, use `dor validate-execution-contract --plan <run_plan.json>`. The operator guide remains at `../../../docs/RUN_PLAN_EXECUTION_BINDINGS.md`.

Do not infer a missing stage command, bypass a gate, or substitute an unapproved Worker action simply because a phase reference was not loaded. Read the relevant reference before dispatch.
