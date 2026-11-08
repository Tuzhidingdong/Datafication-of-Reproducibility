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
- Present the research scope and source inventory to the user. Only after the user explicitly approves G0, record the exact audit artifacts:
  `dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G0 --decision APPROVE --reviewer "..." --rationale "..." --artifact dataset_manifest=01_audit/dataset_manifest.json --artifact source_inventory=01_audit/source_inventory.json`.
- Stop at G0 until the user explicitly approves. Silence or a completed audit is not approval.

### Stage 2 — Canonical representation and analysis plan

After G1 approval:

- Read [the canonical data model](../../../docs/CANONICAL_DATA_MODEL.md), [mapping contract](../../../docs/MAPPING_CONTRACT.md), and [canonical builder contract](../../../docs/CANONICAL_BUILDER.md).
- Define a mapping plan and a separate canonical build specification. The latter must explicitly declare entity grouping keys and same-source-row relationships; never assume one CSV row is one experiment.
- Run `dor validate-mapping` and inspect its report before asking for G1 approval. The G1 packet must include the mapping plan, exact source inventory, build specification, entity-grain choices, and unresolved mapping questions.
- Only after explicit user approval, record G1:
  `dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G1 --decision APPROVE --reviewer "..." --rationale "..." --artifact mapping_plan=mapping_plan.json --artifact mapping_validation=mapping_validation.json --artifact source_inventory=01_audit/source_inventory.json --artifact build_spec=canonical_build_spec.json`.
- Then run `dor build-canonical --plan mapping_plan.json --inventory 01_audit/source_inventory.json --spec canonical_build_spec.json --source-root path/to/source/files --out-dir 02_canonical --workflow-ledger workflow_gate_ledger.jsonl`.
- Review the build report and canonical bundle integrity output. Save an exact validation report with `dor validate-bundle --input 02_canonical/canonical_bundle.json --out 02_canonical/canonical_validation_report.json`. Resolve grouping conflicts rather than selecting or averaging records.
- Run `dor reconcile-bundle` on the resulting canonical bundle. Review endpoint-definition gaps/variants, unresolved observation variation, same-replicate value conflicts, evidence locator disagreements, verification states, and unreferenced entities.
- Keep all reconciliation findings in the review queue. Do not merge, discard, relabel, or select conflicting source values automatically. Human decisions must be recorded in a separate decision file bound to exact report and bundle hashes, then validated with `dor validate-reconciliation-decisions`.
- Keep study, system, condition, experiment, observation, comparison, and evidence entities distinct.
- Define outcome-specific cohorts; do not force all targets into one complete-case table.
- Quantify joint coverage for each proposed variable pair and target.
- Propose endpoint-specific prediction tasks based on actual data support. Each task must specify an exact target_id and endpoint_definition, outcome field and unit, explicit feature bindings to canonical condition_type values, eligibility rules, and a study-level split design. Do not map feature names automatically.
- Write and validate the exact `modeling_task.json` before G2; it is an approval artifact, not something to create after approval.
- Present candidate model families, validation splits, assumptions, exclusion rules, and compute costs.
- After reconciliation review and task preparation, ask the user to approve the exact canonical bundle, reconciliation report, and modeling task at G2. Record G2 only after explicit approval:
  `dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G2 --decision APPROVE --reviewer "..." --rationale "..." --artifact canonical_bundle=02_canonical/canonical_bundle.json --artifact canonical_validation_report=02_canonical/canonical_validation_report.json --artifact reconciliation_report=03_reconciliation/reconciliation_report.json --artifact modeling_task=modeling_task.json`.
- Do not create a modelling cohort or fit a model before G2 approval.

### Stage 3 — Baseline modelling and prediction

After G2 approval:

- Use the exact `modeling_task.json` already approved at G2. Do not edit it after approval; a change makes the G2 decision stale.
- Build the endpoint-specific cohort with `dor build-cohort --bundle canonical_bundle.json --task modeling_task.json --out-dir 04_modeling/cohort --workflow-ledger workflow_gate_ledger.jsonl`.
- Inspect `cohort_report.json`, `modeling_cohort.csv`, `split_manifest.json`, and `modeling_cohort_manifest.json`. Confirm exclusion reasons, feature coverage, group assignments, and zero study overlap before fitting any model.
- A cohort is not a model result. Do not infer performance, causal effects, or scientific validity from cohort construction.
- Run `dor fit-baselines --cohort-dir 04_modeling/cohort --task modeling_task.json --out-dir 04_modeling/baseline_run --workflow-ledger workflow_gate_ledger.jsonl` only after reviewing the cohort report and split manifest.
- The baseline engine selects candidates on validation only, refits the selected model on train plus validation, and uses test only for final evaluation. Never select or retune a model based on test metrics.
- Inspect `model_report.json`, `model_artifact.json`, `validation_model_comparison.csv`, `test_predictions.csv`, and `modeling_run_manifest.json`. Confirm that input/output hashes and Study/Observation IDs are consistent.
- Run nested cross-study evaluation with `dor evaluate-reproducibility --cohort-dir 04_modeling/cohort --task modeling_task.json --out-dir 04_modeling/reproducibility_evaluation --workflow-ledger workflow_gate_ledger.jsonl`. This uses an outer Study-grouped K-fold and an inner Study-level validation split for candidate selection; each Study is held out once.
- Review pooled out-of-fold and per-Study metrics, fold-specific model selection, between-Study error/bias dispersion, and every applicability-domain warning. Do not summarize only a pooled metric when Study-level performance is heterogeneous.
- Treat nearest-neighbour support flags as heuristic diagnostics, not physical boundaries or calibrated probabilities. Prediction uncertainty remains explicitly NOT_CALIBRATED in this increment; do not report descriptive error quantiles as prediction intervals.
- Supported transparent baselines: mean versus Ridge for numeric outcomes; majority class versus mixed Naive Bayes for categorical outcomes. These are reference models, not a universal model-family recommendation or evidence of causal mechanism.
- Use deterministic Python execution for further preprocessing, fitting, hyperparameter search, validation, and metrics.
- Select models based on sample size, target type, feature types, study heterogeneity, and extrapolation requirements.
- Compare against meaningful baselines.
- Keep study-level groups intact across train/validation/test splits.
- Record exact feature lists, row IDs, group IDs, data transformations, software versions, seeds, hyperparameters, fitted artifacts, metrics, predictions, and applicability limitations.
- Do not claim a model is accurate outside its supported data domain.

### Stage 4 — Interaction discovery

- Read the V0.4 interaction discovery contract at ../../../docs/V0.4_INTERACTION_DISCOVERY.md and the interaction methodology at ../../../references/interaction-discovery.md.
- Define candidate feature pairs from the approved feature bindings. Prefer scientifically justified pairs with adequate joint Observation and Study coverage; do not screen an unbounded Cartesian product.
- For numeric endpoints, run: dor discover-interactions --cohort-dir 04_modeling/cohort --task modeling_task.json --out-dir 04_modeling/interactions --workflow-ledger workflow_gate_ledger.jsonl after G2 approval.
- Review the interaction catalogue, fold-level RMSE improvements, per-Study MAE improvements, joint coverage, exclusions, and held-out predictions. Keep pairs that fail to improve as null/negative findings; retain counterexamples where the interaction worsens prediction.
- Repeat the nested interaction screen across at least three distinct seeds with `dor assess-interaction-robustness --cohort-dir 04_modeling/cohort --task modeling_task.json --out-dir 04_modeling/interaction_robustness --workflow-ledger workflow_gate_ledger.jsonl`. Inspect candidate-run frequency and the range of predictive improvements. Treat this as split-randomness sensitivity only, not proof of external reproducibility or a probability of truth.
- The initial engine evaluates one encoded feature pair at a time by comparing additive Ridge with Ridge plus that pair's encoded product terms. It is a predictive bilinear screen for numeric endpoints, not a universal test of all nonlinear interactions. Categorical endpoints are not supported by this initial method.
- Treat a cross-Study predictive interaction label as a statistical/predictive candidate only. It is not a p-value, FDR-controlled discovery, causal estimate, synergy claim, or mechanism.
- Check whether pair combinations are confounded by Study, protocol, material family, or laboratory and whether joint coverage actually overlaps across Studies.
- Present the exact interaction report and catalogue to the user, including support, robustness, Study coverage, exclusions, and counterexamples.
- Prepare an interaction selection record conforming to `schemas/interaction_selection.schema.json`. Its `interaction_report_sha256` and `robustness_report_sha256` must equal the SHA-256 hashes of the exact interaction and repeated-seed robustness reports. Selected and not-selected IDs must be disjoint and together classify every interaction exactly once. The G3 packet also binds the interaction and robustness manifests; both must derive from the exact G2-approved task and the same cohort/split hashes. The mechanism-plan contract supports selecting zero or one candidate per G3 packet.
- If one candidate is selected, prepare the exact `mechanism_plan.json` from `templates/mechanism_plan.example.json` before G3. Its `task_id` and `interaction_id` must match the approved task and selected candidate; every Evidence/Observation reference must be explicit and checked. Present this plan with the interaction selection as part of the G3 approval packet.
- Ask the user to approve the candidate selection at G3. Only after explicit approval, append the G3 decision binding the exact report and selection file. When one candidate is selected for mechanism investigation, also bind the matching reviewed `mechanism_plan.json`:
  `dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G3 --decision APPROVE --reviewer "..." --rationale "..." --artifact interaction_report=04_modeling/interactions/interaction_discovery_report.json --artifact interaction_manifest=04_modeling/interactions/interaction_discovery_manifest.json --artifact robustness_report=04_modeling/interaction_robustness/interaction_robustness_report.json --artifact robustness_manifest=04_modeling/interaction_robustness/interaction_robustness_manifest.json --artifact interaction_selection=interaction_selection.json --artifact mechanism_plan=mechanism_plan.json`.
  If no candidate is selected, omit the mechanism_plan artifact; G3 can still be approved for finalization with no mechanism investigation.
- Only after G3 selection, generate the selected response surface with the exact G3-selected interaction ID:
  `dor generate-interaction-surface --cohort-dir 04_modeling/cohort --task modeling_task.json --interaction-dir 04_modeling/interactions --interaction-id INT_SELECTED_FROM_G3 --out-dir 04_modeling/response_surface --workflow-ledger workflow_gate_ledger.jsonl`. The runtime rejects any interaction ID not selected in G3. The full-cohort refit is descriptive only and must not be used as independent validation.

### Stage 5 — Mechanism interpretation

Read `../../../references/mechanism-evidence.md` and `../../../docs/V0.4_MECHANISM_EVIDENCE_BRIDGE.md`.

- Interpret only the single interaction selected in the current approved G3 packet. If no interaction was selected, do not run mechanism interpretation. A predictive interaction is a motivation for a testable hypothesis, not a mechanism claim.
- Trace each interpretation to source evidence, experimental observations, and relevant theory/calculation.
- Label statements as statistical observation, cross-study replication, mechanism hypothesis, direct experimental support, theoretical support, or prospective validation.
- Record contradictory evidence.
- Use only the exact `mechanism_plan.json` already bound to the current G3 approval. If it needs revision, create a revised plan, obtain the user's renewed G3 decision, and record a new gate event before running the mechanism bridge.
- Run the bridge with the exact approved inputs:
  `dor build-mechanism-evidence-bridge --bundle 02_canonical/canonical_bundle.json --cohort-dir 04_modeling/cohort --task modeling_task.json --interaction-dir 04_modeling/interactions --plan mechanism_plan.json --out-dir 05_mechanism/bridge --workflow-ledger workflow_gate_ledger.jsonl`.
  The runtime rejects a mechanism plan whose task/interaction was not selected in the exact G3 decision packet. Optional robustness and response-surface packages must match the same task and interaction.
- Review `mechanism_evidence_bridge_report.json`, `mechanism_evidence_ledger.csv`, `mechanism_review_queue.csv`, and `mechanism_findings.json`. Keep contradictory evidence, unverified extraction, and non-independent prospective evidence visible.
- The generated Research Finding remains `claim_type = mechanism_hypothesis`, `status = candidate`, and `mechanism_status = hypothesis`. The report remains `PENDING_USER_MECHANISM_REVIEW`; no automated evidence count upgrades a mechanism to established or validated.
- Never upgrade a hypothesis into an established mechanism merely because it is scientifically plausible.

### Stage 6 — Independent validation and virtual reproduction

- Define the intended use, approved target/endpoint, and applicability domain. Review nested Study-level validation before offering a virtual estimate.
- Prepare a query from templates/virtual_reproduction_query.example.json. Include every feature_id in the exact modelling task, the exact target_id/endpoint_definition/task_id, and each exact expected_unit. Do not perform unit conversion, fill missing conditions, or infer a feature mapping.
- Run dor predict-virtual-condition --model-run-dir 04_modeling/baseline_run --query virtual_reproduction_query.json --out 06_publication/virtual_prediction.json --workflow-ledger workflow_gate_ledger.jsonl.
- The runtime must use the serialized selected baseline model and verify its hashes; it must not retrain on the query or use held-out test observations for fitting or selection.
- Inspect each per-feature support state. Values outside the train+validation feature range and unseen categories must be explicitly labelled; a mathematical output may still be returned, but it is not a supported interpolation.
- V0.5 checks marginal ranges/categories only. It does not calculate nearest-neighbour distance or establish joint multivariable support. Keep NOT_CALIBRATED uncertainty explicit; do not report confidence/prediction intervals or calibrated probabilities.
- State explicitly that a virtual prediction is a model-based scenario estimate, not a completed physical experiment, atomistic simulation, causal effect, or mechanism validation.

### Stage 7 — Publication package

Read ../../../references/publication-package.md and ../../../docs/V0.5_PUBLICATION_AND_VIRTUAL_REPRODUCTION.md.

- Prepare a run-specific publication_package_plan.json from templates/publication_package_plan.example.json. Declare each source file explicitly; do not let the runtime crawl the workspace or infer scientific roles from file names.
- Only mark an artifact complete when the actual output exists and has been reviewed. Use partial, requires_review, not_generated, or not_applicable honestly. Never create placeholder result files to satisfy the plan.
- Include the model report/artifact, task and split records, validation and applicability-domain outputs, interaction and mechanism packages when present, figure source data, table source data, limitations, and virtual prediction reports where applicable.
- Review the exact publication plan and at least one scientific result artifact. After the user explicitly approves the finalization scope, record G4 (bind the publication plan and one or more reviewed result artifacts):
  `dor gate-record --workflow-ledger workflow_gate_ledger.jsonl --gate G4 --decision APPROVE --reviewer "..." --rationale "..." --artifact publication_plan=publication_package_plan.json --artifact model_report=04_modeling/baseline_run/model_report.json`.
- Run dor build-publication-package --plan publication_package_plan.json --workspace-root . --out-dir 06_publication/package --workflow-ledger workflow_gate_ledger.jsonl.
- Run dor audit-publication-package --package-dir 06_publication/package --out 06_publication/package_integrity_report.json. Keep the audit report outside the package directory.
- Inspect completeness and all requires_review/partial/not_generated items. A valid hash audit is not scientific approval and does not make the package publication-ready.
- The Writing Skill must first read README_FOR_WRITING_SKILL.md and package_manifest.json, then retrieve only the files needed for its current writing task. Never invent missing scientific claims, methods, figures, tables, or references.

## Approval gates

- G0: user confirms research domain, scientific scope, target outcomes, and source files; the ledger binds dataset_manifest and source_inventory.
- G1: user approves the mapping plan, source-to-canonical semantics, entity grain, and build specification; the ledger binds mapping_plan, source_inventory, and build_spec.
- G2: user approves the exact canonical bundle, reconciliation report, endpoint-specific modeling task, feature bindings, and Study split design; the ledger binds canonical_bundle, reconciliation_report, and modeling_task.
- G3: user selects zero or one interaction candidate for deeper mechanism investigation; the ledger binds the exact interaction report and complete selection record, plus the matching mechanism plan when a candidate is selected.
- G4: user approves the exact publication/deliverables plan and reviewed scientific-result scope; the ledger binds publication_plan and at least one reviewed result artifact.

Before recording any approval, present the exact artifact paths/hashes, findings, unresolved issues, recommended decision, and consequences. Only the user's explicit decision may trigger `dor gate-record`. Inspect the ledger with `dor gate-status` on resume. A hash mismatch or changed upstream approval invalidates dependent approvals.

Inside a currently approved stage, deterministic checks and pre-authorized scripts may run without asking the user for each command. Do not cross a gate without explicit user approval. Never use `--allow-untracked-legacy` in an actual research workflow.

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


## V0.9 project Run Manager (mandatory for managed runs)

Before the first scientific operation, decompose the intended workflow into a complete explicit stage DAG. Do this up front; do not let the Agent opportunistically decide coarse or convenient stage boundaries during execution. The run plan must declare every source artifact, stage dependency, exact input artifact ID, output artifact ID/path, executor, and required approval gate. Use schemas/run_plan.schema.json and templates/run_plan.example.json. Never crawl a workspace to populate this plan.

Initialize a new independent run workspace with:

    dor run-init --plan run_plan.json --run-root path/to/new/run

Keep the original plan and raw sources unchanged. The runtime creates run_manifest.json and run_events.jsonl and binds the run to the exact plan and source hashes. Never reuse a run after a source file changes; create a new run.

Record each explicitly planned stage with dor run-stage-record:
- Record RUNNING immediately before starting the local/manual operation, or after the user-authorized Worker packet is created and before dispatch.
- Record SUCCEEDED only when every declared output exists and the exact inputs remain unchanged.
- Record FAILED with a concrete reason on failure.
- Include Worker job/session IDs and token counts only when returned by the existing Worker Manager. Unknown usage stays unknown.

For a Worker stage, first present role, provider, model, active project root, task inputs/hashes, staging outputs, and restrictions to the user. Wait for explicit authorization, then run dor run-worker-authorize. This command emits a bounded task packet and records the authorization; it does not dispatch a Worker. Invoke the existing Worker Manager only after that authorization. Never silently choose or start a Worker. Workers may write only new files under worker_staging/<stage_id>/; they cannot write into protected sources, ledgers, manifests, or approved artifacts. A human review/promotion stage must separately approve and materialize accepted outputs.

On every resume, run:

    dor run-verify --manifest run_manifest.json
    dor run-status --manifest run_manifest.json
    dor run-resume-plan --manifest run_manifest.json --out resume_plan.json

Reuse only stages explicitly marked REUSE. Rebuild only the stale stage and its declared downstream dependents; keep independent reusable stages. Do not interpret RUNNING as stopped: inspect the external process first, and only then use --confirm-abandoned to create a replacement attempt. A changed source requires a new run. Resume planning does not execute commands, dispatch Workers, or record G0-G4 decisions.

The run event ledger is execution provenance only. It does not approve scientific scope, mapping, canonical data, interactions, or publication. G0-G4 remain the only scientific approval gates. See ../../../docs/V0.9_RUN_MANAGER.md.

For Worker stages, treat the task packet as a strict file-access boundary, but do not describe it as an OS sandbox. Configure the external Worker Manager with guarded permissions and a bounded workdir; include every protected scientific input in the explicit stage input list so the Runtime can verify its hashes after completion. Do not give a Worker broad workspace access when a small staging workdir and declared input copies are sufficient.


Generate an explicit artifact view with `dor run-artifacts --manifest run_manifest.json --out artifact_manifest.json`. This report is regenerated from the Run Plan and hash-chained execution events; it is not the source of truth. Inspect statuses and hashes before reusing any output. When a stage becomes REBUILD_REQUIRED, archive/move its old declared outputs away before retry; the Runtime refuses to overwrite existing outputs. A changed G0-G4 approval event also invalidates stages that were executed against the previous approval hash.

V0.9 does not yet implement automatic parent/child run orchestration. For an optional analysis branch that is not declared in the immutable parent plan, create a separate follow-on run with the exact parent-run outputs, G3-approved selection, and mechanism plan declared as immutable source_artifacts. Record the parent run_id and manifest SHA-256 in the project-level run index; never alter the parent run plan.

A stage whose declared source input differs from the run-init SHA-256 is reported as `SOURCE_CHANGED_NEW_RUN_REQUIRED`; do not retry that stage inside the old Run. Initialize a new Run from the revised source snapshot.


The Run Manager initializes run_events.jsonl with an immutable RUN_INITIALIZED record binding the manifest's project/run scope, exact plan hash, source roots and source hashes, workflow-ledger path, and stage order. Runtime compares this record to run_manifest.json on every operation. Do not edit either control file by hand.
