---
name: datafication-of-reproducibility
description: Reconstructs reproducible relationships between experimental conditions, interacting processes, and observable outcomes from scientific datasets and literature. Use when auditing research data, planning condition-to-outcome modelling, discovering robust interactions, interpreting mechanisms, validating predictions, or preparing a traceable publication package.
---

# Datafication of Reproducibility

You are operating a guided scientific research workflow. The purpose is not merely to maximize predictive accuracy. It is to learn the reproducible structure of experimental phenomena: how reported conditions, incompletely observed physical states, and interacting processes jointly relate to observable outcomes.

## Non-negotiable project decisions

- Platform: Antigravity Workspace Skill.
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

## Progressive workflow

### Stage 0 — Initialize

- Read the project configuration.
- Resolve source paths and output workspace.
- Verify that source inputs exist and are readable.
- Record source file names, sizes, and SHA-256 hashes.
- Confirm that output paths do not overwrite or reside inside protected source files.
- Create a new run directory; never overwrite an earlier run by default.

### Stage 1 — Data audit

Read `../../../references/data-model.md` and `../../../references/guided-workflow.md`.

- Inspect CSV and JSON structure, row/system semantics, columns, nested keys, identifiers, and evidence references.
- Measure feature coverage and missingness without silently coercing or imputing values.
- Identify duplicate records, study-level dependencies, conflicting values, and possible join keys.
- Produce a data dictionary and an audit report.
- Do not finalize a domain mapping when the source schema has not been inspected.
- Stop at Gate G1. Present the audit, unresolved schema questions, and feasible research questions to the user.

### Stage 2 — Canonical representation and analysis plan

After G1 approval:

- Read [the canonical data model](../../../docs/CANONICAL_DATA_MODEL.md), [mapping contract](../../../docs/MAPPING_CONTRACT.md), and [canonical builder contract](../../../docs/CANONICAL_BUILDER.md).
- Define and obtain approval for a mapping plan and a separate canonical build specification. The latter must explicitly declare entity grouping keys and same-source-row relationships; never assume one CSV row is one experiment.
- Use `dor validate-mapping` before construction, then `dor build-canonical` with exact inventory/plan hashes and a new derived output directory.
- Review the build report and canonical bundle integrity output at G1/G2. Resolve grouping conflicts rather than selecting or averaging records.
- Keep study, system, condition, experiment, observation, comparison, and evidence entities distinct.
- Define outcome-specific cohorts; do not force all targets into one complete-case table.
- Quantify joint coverage for each proposed variable pair and target.
- Propose candidate prediction and interaction tasks based on actual data support.
- Present model families, validation splits, assumptions, exclusion rules, and compute costs.
- Stop at Gate G2 for approval.

### Stage 3 — Baseline modelling and prediction

After G2 approval:

- Use deterministic Python execution for preprocessing, fitting, hyperparameter search, validation, and metrics.
- Select models based on sample size, target type, feature types, study heterogeneity, and extrapolation requirements.
- Compare against meaningful baselines.
- Keep study-level groups intact across train/validation/test splits.
- Record exact feature lists, row IDs, group IDs, data transformations, software versions, seeds, hyperparameters, fitted artifacts, metrics, predictions, and applicability limitations.
- Do not claim a model is accurate outside its supported data domain.

### Stage 4 — Interaction discovery

- Screen candidate interactions only where joint data coverage is adequate.
- Prefer interpretable second-order interactions first. Higher-order interactions require explicit rationale and sufficient support.
- Separate main effects, statistical interactions, predictive contribution, and causal interpretation.
- Test interaction stability across study-level resampling, alternative specifications, and held-out studies.
- Retain counterexamples and null findings.
- Produce an Interaction Catalogue with supporting data and plots.

### Stage 5 — Mechanism interpretation

Read `../../../references/mechanism-evidence.md`.

- Interpret only interactions that pass the agreed statistical and robustness checks.
- Trace each interpretation to source evidence, experimental observations, and relevant theory/calculation.
- Label statements as statistical observation, cross-study replication, mechanism hypothesis, direct experimental support, theoretical support, or prospective validation.
- Record contradictory evidence.
- Never upgrade a hypothesis into an established mechanism merely because it is scientifically plausible.

### Stage 6 — Independent validation and virtual reproduction

- Define the intended use and applicability domain.
- Evaluate predictions with held-out studies or independent experimental data where available.
- For a requested condition set, report predicted outcome, uncertainty, nearest supported data region, missing critical variables, and extrapolation warnings.
- State explicitly that a virtual prediction is not a completed physical experiment.

### Stage 7 — Publication package

Read `../../../references/publication-package.md`.

Generate the publication package with, at minimum:

- `README_FOR_WRITING_SKILL.md`
- `package_manifest.json`
- structured data/method/model/result/finding records
- source data for every figure and table
- Methods and Results drafts generated from structured facts
- limitations and evidence-status records
- a computational reproduction package or an explicit statement of what is not yet executable

The Writing Skill must first read the guide and manifest, then retrieve only the files needed for its current writing task.

## Approval gates

- G0: user confirms research domain, scientific scope, target outcomes, and source files.
- G1: user approves the data audit, entity relationships, unresolved ambiguities, and feasible analysis scope.
- G2: user approves the analysis plan, candidate models, interaction plan, validation strategy, and compute budget.
- G3: user selects candidate scientific findings for deeper mechanism investigation.
- G4: user approves prospective validation work or finalization without new experiments.

Inside an approved stage, deterministic checks and pre-authorized scripts may run without asking the user for each command. Do not cross a gate without explicit user approval.

## Worker orchestration

Use the user's existing Antigravity-to-OpenCode Worker Manager. Do not invent or replace its MCP interface.

- Dispatch only bounded tasks with explicit inputs, permitted actions, expected artifacts, and token/context limits.
- Do not give Workers the full nested database when a generated summary or selected evidence subset is sufficient.
- Do not ask multiple Workers to repeat the same model training.
- Use a data/statistics role for semantic audit and analysis design, a scientific-analysis role for interpretation, and an independent-audit role only for consequential findings.
- Require structured result files conforming to `schemas/worker_result.schema.json`.
- Local Python is authoritative for deterministic numerical results; Worker prose cannot override computed artifacts.

## Required records and outputs

For every run, record the project/run IDs, source hashes, domain-profile version, configuration, scripts/commit version, environment, random seeds, approvals, stage status, and generated artifact hashes.

For every model, record the task definition, target, cohort IDs, features, transformations, hyperparameters, training protocol, validation protocol, predictions, metrics, fitted artifact, and applicability domain.

For every interaction, record its variables, target, method/statistic, joint support, DOI coverage, robustness, counterexamples, plots/source data, and interpretation status.

For every finding, record supporting and contradicting evidence, linked model/interaction IDs, and claim strength.

## When information is missing

Do not guess. Record the missing field and its status, identify whether it is critical for the proposed analysis, and either:
- continue with an explicitly narrower analysis;
- use a documented method for missing data where scientifically justified; or
- ask the user at the relevant approval gate.

## Stop conditions

Stop and report the blocker if source files cannot be read, identifiers cannot be reconciled safely, target semantics are ambiguous, leakage cannot be controlled, no supported validation design exists, or requested predictions are outside the model's applicability domain.

Do not fabricate sample counts, feature mappings, model metrics, paper citations, experimental conditions, or mechanism evidence.
