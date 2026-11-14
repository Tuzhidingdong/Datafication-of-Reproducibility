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

## Discovery-first research entry

DoR never assumes a particular source system or research domain. When a project has an external adapter that can provide a validated Canonical Bundle, use the same bundle for exploratory profiling and the subsequent formal workflow.

### Stage -1 — Exploratory discovery when a Canonical Bundle already exists

- Read the external adapter package contract at ../../../docs/ADAPTER_CONTRACT.md.
- Create a DoR handoff with dor prepare-adapter-handoff --manifest <adapter_manifest.json> --package-root <package_root> --out <adapter_handoff.json>. The output is a hash-bound routing record; it does not approve scientific semantics.
- This pre-Run stage is available only when the handoff route is CANONICAL_BUNDLE. Run dor discover-opportunities --adapter-handoff <adapter_handoff.json> --out-dir <new_discovery_directory>.
- Read agent_research_brief.md and discovery_report.json. Use aggregate CSV outputs only when a specific signal needs inspection.
- Do not load complete source datasets or large evidence collections into an LLM context. Use deterministic local processing and pass only bounded summaries or task-specific evidence packets to Agents.
- Treat every signal as exploratory. Do not infer domain meanings from identifiers, filenames, or unreviewed labels.
- Synthesize a small set of testable research opportunities. Each must cite supporting signal IDs, independent Study support, data limitations, identifiability, confounding risks, counterexamples, proposed validation, and novelty-review status.
- The user selects or revises a research direction before a formal analysis task and Run are initialized.

If the handoff route is STRUCTURED_DATASET, do not run this stage outside the formal workflow. Initialize the guided Run, validate the handoff, audit all declared supported datasets, complete G0/G1 review and canonical construction, then use the Run Plan's exploratory_discovery stage on the resulting canonical bundle before G2. This avoids bypassing source and mapping approvals.

A pre-Run Canonical Bundle scan does not create a formal Run, approve mappings, initialize acceptance, record G0-G4, or launch modelling. If the same external bundle is later used for formal analysis, its matching source_inventory, mapping_plan, and build_spec must be supplied and pass the existing G1/G2 provenance checks. Exploratory results never replace the approval-gated workflow.

## Progressive workflow

Before executing any Run Plan, read [the command-level stage bindings](../../../docs/RUN_PLAN_EXECUTION_BINDINGS.md). Treat that file as the single source of truth for Run Plan stage-to-CLI mapping. If a stage has no declared command or action, do not invent one; report it as an integration gap.

### Stage 0 — Initialize

- Read the project configuration.
- Resolve source paths and output workspace.
- Verify that source inputs exist and are readable.
- Record source file names, sizes, and SHA-256 hashes.
- Confirm that output paths do not overwrite or reside inside protected source files.
- Create a new run directory; never overwrite an earlier run by default.
- For adapter-backed projects, first create a route-preflight handoff outside the protected package using `dor prepare-adapter-handoff`. Use its route to select the appropriate Run Plan template. Initialize the formal Run with `dor run-init --plan <selected_run_plan.json> --run-root <new_run_root>`, then verify it with `dor run-verify --manifest <run_root>/run_manifest.json`. The formal adapter validation stage must regenerate the handoff inside the Run workspace; the preflight file is not a Run artifact.

### Run Manager execution loop

The Run Manager is the execution ledger and safety controller for the immutable Run Plan; it does not automatically execute arbitrary commands or launch Workers. The Skill is responsible for dispatching the exact stage action after consulting the current Run state.

- Before each stage, run `dor run-resume-plan --manifest <run_root>/run_manifest.json`. Execute a stage only when its action is `READY_TO_RUN`, `RETRY_REQUIRED`, or `REBUILD_REQUIRED`. Recheck the exact inputs and active approval gate before dispatch.
- For a local stage, record RUNNING with `dor run-stage-record --manifest <run_root>/run_manifest.json --stage <stage_id> --status RUNNING --producer-kind local --command "<exact CLI command>"`. Execute only the command bound to that stage. Verify every declared output before recording SUCCEEDED. Record FAILED with a non-empty reason if execution or output inspection fails.
- For a manual stage, record RUNNING with `--producer-kind manual` before the review/preparation action and SUCCEEDED only after every declared output has been created and checked. A reviewer's decision is recorded separately in the G0-G4 approval ledger.
- For a Worker stage, first present the exact role, provider, model, project root, inputs, permitted outputs and task limits. Obtain the user's explicit authorization, record it with `dor run-worker-authorize`, and dispatch only the returned packet. Record the returned job/session/task identifiers and usage only when actually reported.
- If the resume action is `SKIP_REQUIRED`, record `SKIPPED` with the executor declared in the plan. Do not create placeholder output files. A skip is not an approval and cannot satisfy another stage's declared artifact input.
- Do not dispatch a stage in `WAITING_FOR_DEPENDENCIES`, `WAITING_FOR_ACTIVATION_INPUT`, or `BLOCKED_GATE`. Present the missing dependency/approval packet instead. For `RUNNING_NEEDS_RECONCILIATION`, inspect the prior external process before considering `--confirm-abandoned`. For `SOURCE_CHANGED_NEW_RUN_REQUIRED`, initialize a new Run from the revised source snapshot.
- For `REBUILD_REQUIRED`, archive the previous attempt's output files outside their declared output locations before retrying; Run Manager refuses to overwrite existing files. After each stage boundary, use `dor run-verify` and refresh `dor run-artifacts` when artifact lineage changes. On interruption, trust the newly computed resume plan rather than conversational history.

### External adapter handoff

Use an independently maintained adapter to read source-system files and prepare an adapter package conforming to schemas/adapter_package.schema.json. Adapter code and domain-specific retrieval or vocabulary rules must remain outside the DoR core repository.

- Register the adapter manifest and its protected package root in the Run Plan. The generic Run Plan template declares the manifest once; its adapter_package_validation stage creates the run-bound adapter_handoff artifact.
- In that stage, run dor prepare-adapter-handoff --manifest <adapter_manifest.json> --package-root <package_root> --out <run_root>/00_adapter/adapter_handoff.json. Do not write the handoff inside the source package.
- Treat a valid handoff as an integrity and routing result only. It does not approve extraction quality, semantic mappings, entity grain, unit compatibility, or scientific suitability.
- For a STRUCTURED_DATASET route, the next source_audit stage runs dor audit --adapter-handoff <adapter_handoff.json> --out <run_root>/01_audit. This audits every supported standardized_dataset CSV/JSON artifact declared in the package and preserves its package-relative path and artifact identity in the source inventory.
- For a CANONICAL_BUNDLE route, the handoff command also runs DoR's structural/reference validator. Use discovery through --adapter-handoff so the manifest, sources, and canonical artifact hashes are rechecked before use. A direct pre-Run discovery scan is not a replacement for G0/G1/G2 approval.
- Review the source inventory before defining mappings. Use the adapter package's declared source_inventory, mapping_plan, and build_spec as review candidates only; they must be bound to the exact package hashes and pass the usual mapping/G1 checks before formal analysis.
- Use project-owned domain profiles and human-reviewed mapping/build specifications. Do not infer scientific meanings from identifiers or filenames.
- If an adapter supplies a Canonical Bundle, validate it and preserve its exact source/adapter provenance before using it for discovery or formal analysis.
- Never silently merge conflicting source values, remove repeated records, or convert missing information into reported facts.

### Select the formal Run Plan by adapter route

- Use `templates/run_plan.example.json` for a STRUCTURED_DATASET handoff. The formal Run performs source audit, G0/G1 review, canonical construction, then Discovery and the downstream workflow.
- Use `templates/run_plan.canonical_adapter.example.json` for a CANONICAL_BUNDLE handoff only when the package declares exactly one artifact for each generic role: `source_inventory`, `mapping_plan`, `build_spec`, and `canonical_bundle`. The latter three provenance hashes in the bundle must agree with the supplied mapping plan, inventory, and build specification.
- In the canonical-adapter template's adapter validation stage, run `dor prepare-adapter-handoff --manifest <adapter_manifest.json> --package-root <package_root> --out <run_root>/00_adapter/adapter_handoff.json --dataset-manifest-out <run_root>/00_adapter/dataset_manifest.json`.
- In its materialization stage, run `dor materialize-adapter-artifacts --adapter-handoff <adapter_handoff.json> --role source_inventory --role mapping_plan --role build_spec --role canonical_bundle --out-dir <run_root>/00_adapter/materialized`. The role selector must resolve to exactly one declared artifact per role. Materialization copies verified files and does not rewrite their contents. It also checks every Source Inventory row against the Adapter Manifest's exact declared source/artifact path, hash, and format; unresolved or conflicting provenance blocks import.
- Present the package snapshot, exact source inventory, handoff, and materialization manifest for G0. Do not infer approval from a valid package or valid Canonical Bundle.
- After explicit G0 approval, run `dor validate-mapping` and `dor validate-build-spec` against the materialized mapping plan, source inventory, and build specification. Present both validation reports, the supplied Build Spec, and its provenance for G1. The G1 gate must bind those exact files and recompute both deterministic validations.
- Only after explicit G1 approval, validate the supplied Canonical Bundle. Do not rebuild it or bypass G1. Continue with reconciliation, Discovery, user research-scope selection, and G2 exactly as in the standard route.
- If any required artifact or provenance link is missing or inconsistent, do not use the canonical-adapter template. Return to the structured-data route or ask the external adapter owner to produce a complete, traceable package.

### Stage 1 — Data audit

Read `../../../references/data-model.md` and `../../../references/guided-workflow.md`.

- Inspect CSV and JSON structure, row/system semantics, columns, nested keys, identifiers, and evidence references.
- Measure feature coverage and missingness without silently coercing or imputing values.
- Identify duplicate records, study-level dependencies, conflicting values, and possible join keys.
- Produce a data dictionary and an audit report.
- Do not finalize a domain mapping when the source schema has not been inspected.
- Present the exact adapter handoff, source inventory, and audit/package snapshot to the user. Only after explicit G0 approval, record G0 using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md` (the required source-inventory and dataset-manifest paths differ by adapter route).
- Stop at G0 until the user explicitly approves. Silence or a completed audit is not approval.

### Stage 2 — Canonical representation and analysis plan

After explicit G0 approval:

- Read [the canonical data model](../../../docs/CANONICAL_DATA_MODEL.md), [mapping contract](../../../docs/MAPPING_CONTRACT.md), and [canonical builder contract](../../../docs/CANONICAL_BUILDER.md).
- Define a mapping plan and a separate canonical build specification. The latter must explicitly declare entity grouping keys and same-source-row relationships; never assume one CSV row is one experiment.
- Run `dor validate-mapping` and `dor validate-build-spec` and inspect both reports before asking for G1 approval. Build Spec validation checks its exact mapping/inventory hashes, declared entity sources and formats, grouping selectors, mapping-rule compatibility, and relationship declarations without building or changing data. The G1 packet must include the mapping plan, both validation reports, exact source inventory, build specification, entity-grain choices, and unresolved mapping questions.
- Present the exact Mapping Plan, Mapping Validation, Source Inventory, Build Spec, and Build Spec Validation to the user. Only after explicit G1 approval, record G1 using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`.
- After G1 is approved, follow the selected route binding: STRUCTURED_DATASET runs `canonical_build`; CANONICAL_BUNDLE validates and uses the supplied bundle and must not run `build-canonical`.
- Review the build report where canonical construction applies. Validate the exact route-specific Canonical Bundle using the command and output path in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`. Resolve grouping conflicts rather than selecting or averaging records.
- Run the selected route’s `canonical_reconciliation` stage. Review endpoint-definition gaps/variants, unresolved observation variation, same-record value conflicts, evidence-locator disagreements, verification states, and unreferenced entities.
- Complete `reconciliation_decision_review` by copying `templates/reconciliation_decisions.example.json` to `<run_root>/04_reconciliation/reconciliation_decisions.json`, then recording exactly one explicit human decision for every issue in the exact report. Bind the file to the report SHA-256 and Canonical Bundle hash. Use `REMAINS_UNRESOLVED` rather than inventing a resolution when evidence is insufficient. A `CRITICAL` or `REVIEW_REQUIRED` issue may not remain unresolved at G2: stop before G2 and obtain additional evidence or record a justified explicit exclusion from the approved scope. Then run `dor validate-reconciliation-decisions --decisions <run_root>/04_reconciliation/reconciliation_decisions.json --report <run_root>/04_reconciliation/reconciliation_report.json --bundle <canonical_bundle_path_from_run_artifact_manifest> --out <run_root>/04_reconciliation/reconciliation_decision_validation.json`. Do not merge, discard, relabel, or select conflicting source values automatically; the validation report must be valid before G2.
- Keep study, system, condition, experiment, observation, comparison, and evidence entities distinct.
- Define outcome-specific cohorts; do not force all targets into one complete-case table.
- Quantify joint coverage for each proposed variable pair and target.
- Propose endpoint-specific prediction tasks based on actual data support. Each task must specify an exact target_id and endpoint_definition, outcome field and unit, explicit feature bindings to canonical condition_type values, eligibility rules, and a study-level split design. Do not map feature names automatically.
- Write and validate the exact `modeling_task.json` before G2; it is an approval artifact, not something to create after approval.
- Present candidate model families, validation splits, assumptions, exclusion rules, and compute costs.
- After reconciliation-decision validation, Discovery, scope selection, and task preparation, ask the user to approve the exact Canonical Bundle, canonical validation, reconciliation report and decisions, selected scope, and modeling task at G2. Record G2 only after explicit approval using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`; the Gate validator independently recomputes decision validity against the bound decision/report/bundle files.
- Do not create a modelling cohort or fit a model before G2 approval.

### Stage 3 — Baseline modelling and prediction

After G2 approval:

- Use the exact `modeling_task.json` already approved at G2. Do not edit it after approval; a change makes the G2 decision stale.
- Build the endpoint-specific cohort with `dor build-cohort --bundle <canonical_bundle_path_from_run_artifact_manifest> --task <run_root>/05_scope/modeling_task.json --out-dir <run_root>/05_modeling/cohort --workflow-ledger <run_root>/workflow_gate_ledger.jsonl`.
- Inspect `cohort_report.json`, `modeling_cohort.csv`, `split_manifest.json`, and `modeling_cohort_manifest.json`. Confirm exclusion reasons, feature coverage, group assignments, and zero study overlap before fitting any model.
- A cohort is not a model result. Do not infer performance, causal effects, or scientific validity from cohort construction.
- Run `dor fit-baselines --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --out-dir <run_root>/06_modeling/baseline --workflow-ledger <run_root>/workflow_gate_ledger.jsonl` only after reviewing the cohort report and split manifest.
- The baseline engine selects candidates on validation only, refits the selected model on train plus validation, and uses test only for final evaluation. Never select or retune a model based on test metrics.
- Inspect `model_report.json`, `model_artifact.json`, `validation_model_comparison.csv`, `test_predictions.csv`, and `modeling_run_manifest.json`. Confirm that input/output hashes and Study/Observation IDs are consistent.
- Run nested cross-study evaluation with `dor evaluate-reproducibility --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --out-dir <run_root>/06_modeling/reproducibility --workflow-ledger <run_root>/workflow_gate_ledger.jsonl`. This uses an outer Study-grouped K-fold and an inner Study-level validation split for candidate selection; each Study is held out once.
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
- For numeric endpoints, run: dor discover-interactions --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --out-dir <run_root>/06_modeling/interactions --workflow-ledger <run_root>/workflow_gate_ledger.jsonl after G2 approval.
- Review the interaction catalogue, fold-level RMSE improvements, per-Study MAE improvements, joint coverage, exclusions, and held-out predictions. Keep pairs that fail to improve as null/negative findings; retain counterexamples where the interaction worsens prediction.
- Repeat the nested interaction screen across at least three distinct seeds with `dor assess-interaction-robustness --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --out-dir <run_root>/06_modeling/interaction_robustness --workflow-ledger <run_root>/workflow_gate_ledger.jsonl`. Inspect candidate-run frequency and the range of predictive improvements. Treat this as split-randomness sensitivity only, not proof of external reproducibility or a probability of truth.
- The initial engine evaluates one encoded feature pair at a time by comparing additive Ridge with Ridge plus that pair's encoded product terms. It is a predictive bilinear screen for numeric endpoints, not a universal test of all nonlinear interactions. Categorical endpoints are not supported by this initial method.
- Treat a cross-Study predictive interaction label as a statistical/predictive candidate only. It is not a p-value, FDR-controlled discovery, causal estimate, synergy claim, or mechanism.
- Check whether pair combinations are confounded by Study, protocol, material family, or laboratory and whether joint coverage actually overlaps across Studies.
- Present the exact interaction report and catalogue to the user, including support, robustness, Study coverage, exclusions, and counterexamples.
- Prepare an interaction selection record conforming to `schemas/interaction_selection.schema.json`. Its `interaction_report_sha256` and `robustness_report_sha256` must equal the SHA-256 hashes of the exact interaction and repeated-seed robustness reports. Selected and not-selected IDs must be disjoint and together classify every interaction exactly once. The G3 packet also binds the interaction and robustness manifests; both must derive from the exact G2-approved task and the same cohort/split hashes. The mechanism-plan contract supports selecting zero or one candidate per G3 packet.
- If one candidate is selected, the formal Run Plan's conditional `mechanism_plan_preparation` stage becomes active. Prepare `07_review/mechanism_plan.json` from `templates/mechanism_plan.example.json` and record the manual stage as RUNNING/SUCCEEDED. Its `task_id` and `interaction_id` must match the approved task and selected candidate; every Evidence/Observation reference must be explicit and checked. Present this exact plan with the interaction selection as part of the G3 approval packet.
- Ask the user to approve the candidate selection at G3. Only after explicit approval, append the G3 decision binding the exact interaction report, discovery manifest, robustness report, robustness manifest, and selection file. When one candidate is selected, also bind the exact Run artifact `mechanism_plan`:
  `dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G3 --decision APPROVE --reviewer "..." --rationale "..." --artifact interaction_report=<run_root>/06_modeling/interactions/interaction_discovery_report.json --artifact interaction_manifest=<run_root>/06_modeling/interactions/interaction_discovery_manifest.json --artifact robustness_report=<run_root>/06_modeling/interaction_robustness/interaction_robustness_report.json --artifact robustness_manifest=<run_root>/06_modeling/interaction_robustness/interaction_robustness_manifest.json --artifact interaction_selection=<run_root>/07_review/interaction_selection.json --artifact mechanism_plan=<run_root>/07_review/mechanism_plan.json`.
- After G3 approval, the conditional `response_surface_generation` stage runs with the single ID in `selected_interaction_ids`:
  `dor generate-interaction-surface --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --interaction-dir <run_root>/06_modeling/interactions --interaction-id <the_exact_selected_interaction_id> --out-dir <run_root>/07_response_surface --robustness-dir <run_root>/06_modeling/interaction_robustness --workflow-ledger <run_root>/workflow_gate_ledger.jsonl`. The runtime rejects an interaction ID not selected in the exact G3 decision. The full-cohort refit is descriptive only and must not be used as independent validation.
- Then execute the conditional `mechanism_evidence_bridge` stage:
  `dor build-mechanism-evidence-bridge --bundle <canonical_bundle_path_from_run_artifact_manifest> --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --interaction-dir <run_root>/06_modeling/interactions --plan <run_root>/07_review/mechanism_plan.json --out-dir <run_root>/07_mechanism_bridge --robustness-dir <run_root>/06_modeling/interaction_robustness --response-surface-dir <run_root>/07_response_surface --workflow-ledger <run_root>/workflow_gate_ledger.jsonl`.
- If zero candidates are selected, do not create a mechanism plan and do not invoke either optional analysis command. After G3 selection record, consult `dor run-resume-plan`; for each of the three conditional stages whose action is `SKIP_REQUIRED`, record `SKIPPED` with its declared executor (`manual` for plan preparation, `local` for the two analysis stages). A skip produces no output and never counts as a G3 approval or scientific result. If an upstream selection later changes, use the new resume plan and the hash-bound approval process rather than editing the old Run.

### Stage 5 — Mechanism interpretation

Read `../../../references/mechanism-evidence.md` and `../../../docs/V0.4_MECHANISM_EVIDENCE_BRIDGE.md`.

- Interpret only the single interaction selected in the current approved G3 packet. If no interaction was selected, do not run mechanism interpretation. A predictive interaction is a motivation for a testable hypothesis, not a mechanism claim.
- Trace each interpretation to source evidence, experimental observations, and relevant theory/calculation.
- Label statements as statistical observation, cross-study replication, mechanism hypothesis, direct experimental support, theoretical support, or prospective validation.
- Record contradictory evidence.
- Use only the exact `mechanism_plan.json` already bound to the current G3 approval. If it needs revision, create a revised plan, obtain the user's renewed G3 decision, and record a new gate event before running the mechanism bridge.
- Run the bridge only through the declared `mechanism_evidence_bridge` Run Plan stage and pass the exact Run-bound Canonical Bundle, cohort, task, interaction output, approved mechanism plan, robustness output, and response-surface output. The runtime rejects a mechanism plan whose task/interaction was not selected in the exact G3 decision packet. Optional robustness and response-surface packages must match the same task and interaction.
- Review `mechanism_evidence_bridge_report.json`, `mechanism_evidence_ledger.csv`, `mechanism_review_queue.csv`, and `mechanism_findings.json`. Keep contradictory evidence, unverified extraction, and non-independent prospective evidence visible.
- The generated Research Finding remains `claim_type = mechanism_hypothesis`, `status = candidate`, and `mechanism_status = hypothesis`. The report remains `PENDING_USER_MECHANISM_REVIEW`; no automated evidence count upgrades a mechanism to established or validated.
- Never upgrade a hypothesis into an established mechanism merely because it is scientifically plausible.

### Stage 6 — Independent validation and virtual reproduction

- Define the intended use, approved target/endpoint, and applicability domain. Review nested Study-level validation before offering a virtual estimate.
- Prepare a query from templates/virtual_reproduction_query.example.json. Include every feature_id in the exact modelling task, the exact target_id/endpoint_definition/task_id, and each exact expected_unit. Do not perform unit conversion, fill missing conditions, or infer a feature mapping.
- Run dor predict-virtual-condition --model-run-dir <run_root>/06_modeling/baseline --query <configuration_root>/virtual_reproduction_query.json --out <run_root>/08_virtual_reproduction/virtual_prediction.json --workflow-ledger <run_root>/workflow_gate_ledger.jsonl.
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
  `dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G4 --decision APPROVE --reviewer "..." --rationale "..." --artifact publication_plan=<configuration_root>/publication_package_plan.json --artifact model_report=<run_root>/06_modeling/baseline/model_report.json`.
- Run dor build-publication-package --plan <configuration_root>/publication_package_plan.json --workspace-root <run_root> --out-dir <run_root>/10_publication/package --workflow-ledger <run_root>/workflow_gate_ledger.jsonl.
- Run dor audit-publication-package --package-dir <run_root>/10_publication/package --out <run_root>/10_publication/package_integrity_report.json. Keep the audit report outside the package directory.
- Inspect completeness and all requires_review/partial/not_generated items. A valid hash audit is not scientific approval and does not make the package publication-ready.
- The Writing Skill must first read README_FOR_WRITING_SKILL.md and package_manifest.json, then retrieve only the files needed for its current writing task. Never invent missing scientific claims, methods, figures, tables, or references.

## Approval gates

- G0: user confirms research domain, scientific scope, target outcomes, and source files; the ledger binds dataset_manifest and source_inventory.
- G1: user approves the mapping plan, source-to-canonical semantics, entity grain, and build specification; the ledger binds mapping_plan, source_inventory, and build_spec.
- G2: user approves the exact Canonical Bundle, canonical validation, reconciliation report, complete human decision record, endpoint-specific modeling task, feature bindings, selected scope, and split design; the ledger binds `canonical_bundle`, `reconciliation_report`, `reconciliation_decisions`, and `modeling_task`. The Gate validator independently rechecks every issue decision against the exact report and bundle hashes.
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

V0.9 does not yet implement automatic parent/child Run orchestration. The two formal adapter Run Plans now declare the post-G3 response-surface and mechanism-evidence-bridge path as conditional stages, so this path remains inside the same immutable Run. Only for a genuinely new optional branch that is not declared in the parent plan, create a separate follow-on Run with the exact parent outputs and required approvals declared as immutable source_artifacts. Record the parent run_id and manifest SHA-256 in the project-level Run index; never alter the parent Run plan.

A stage whose declared source input differs from the run-init SHA-256 is reported as `SOURCE_CHANGED_NEW_RUN_REQUIRED`; do not retry that stage inside the old Run. Initialize a new Run from the revised source snapshot.


The Run Manager initializes run_events.jsonl with an immutable RUN_INITIALIZED record binding the manifest's project/run scope, exact plan hash, source roots and source hashes, workflow-ledger path, and stage order. Runtime compares this record to run_manifest.json on every operation. Do not edit either control file by hand.


## V1.0 controlled real-data acceptance (mandatory)

V1.0 is a controlled acceptance, not a bulk-corpus run. Use only a user-selected primary paper and its SI for the first pilot. Do not select the paper or start real-data processing on the user's behalf. Before execution, read ../../../docs/V1.0_CONTROLLED_ACCEPTANCE.md and create an acceptance record from ../../../templates/v1_acceptance_record.example.json conforming to ../../../schemas/v1_acceptance_record.schema.json. Populate source_snapshot.study_ids with the exact explicit Study IDs present in the reviewed canonical bundle; never derive them from row counts, filenames, or a guessed paper-to-study mapping. study_count must equal the number of unique listed IDs. Every stage marked PASS must also include at least one checks[] assertion against a JSON artifact already listed in that same stage's evidence; use an RFC 6901 json_pointer and a supported operator so the Runtime computes the result from the artifact rather than accepting a self-reported check status.

The eight acceptance stages are fixed and ordered: source_selection, source_integrity, extraction_review, semantic_mapping, canonical_reconciliation, cohort_feasibility, modeling_validation, publication_handoff. Do not combine or omit stages. Record exact evidence paths and SHA-256 hashes for every PASS. NOT_APPLICABLE requires a scientific reason; FAIL/BLOCKED requires a concrete blocker. A successful CLI exit is not by itself scientific acceptance.

A single Study cannot support Study-held-out evaluation. For a one-paper pilot, cohort_feasibility and modeling_validation may be NOT_APPLICABLE with an explicit reason; do not split rows and call them independent Studies. A multi-Study modelling pilot is a separate scope requiring adequate independent Studies and explicit G2 approval.

For source selection, use `schemas/v1_source_selection_manifest.schema.json` and its template. `selected_sources` and `excluded_sources` must partition the exact Run source snapshot without overlap or omissions. Each excluded source must repeat its source ID, role, path, hash, and a human-readable reason. Do not classify excluded sources as selected or include their extracted records in `source_inventory`.

For every stage evidence entry, include `artifact_type` in addition to the exact Run-bound `artifact_id`, `path`, and `sha256`. The implementation-owned evidence contract is authoritative; the acceptance author cannot substitute weaker JSON Pointer checks for required artifacts. The required type set is:

- `source_selection`: `source_selection_manifest`, `source_inventory`
- `source_integrity`: `run_manifest`
- `extraction_review`: `extraction_review_record`
- `semantic_mapping`: `mapping_plan`
- `canonical_reconciliation`: `canonical_bundle`, `reconciliation_report`, `reconciliation_decisions`
- `cohort_feasibility`: `modeling_task`, `cohort_report`, `split_manifest`, `modeling_cohort_manifest`, `modeling_cohort_csv`
- `modeling_validation`: `model_report`, `model_artifact`, `modeling_run_manifest`, `reproducibility_evaluation`, `reproducibility_evaluation_manifest`
- `publication_handoff`: `publication_package_manifest`, `publication_integrity_report`

The validator reads the exact hash-matched JSON evidence. It checks selected and excluded sources as a complete disjoint partition of the initialized source snapshot, requires explicit exclusion reasons, and limits source inventory entries to selected files. It checks source hashes in extraction review, mapping-plan/source-inventory linkage, canonical graph integrity and Study membership, reconciliation-to-bundle hash linkage, the Cohort's explicit `eligible_study_ids`, and exact split coverage. For a multi-Study PASS, the model report, serialized model, and run manifest must agree; nested evaluation must hold every eligible Study out exactly once, keep inner and outer Study groups disjoint, and match the evaluation manifest and its hashes. At least four eligible Studies are required for the nested evaluation contract. These checks do not impose a model performance threshold or turn descriptive errors into calibrated uncertainty.

The acceptance record is a review ledger, not an automatic scientific truth score. A schema-valid record still requires human inspection of the cited evidence. Do not mark full PASS unless all eight stages pass; a one-Study pilot should normally conclude CONDITIONAL_PASS with its limitations stated. See ../../../docs/V1.0_CONTROLLED_ACCEPTANCE.md.

### Acceptance revision ledger — mandatory operational procedure

The acceptance JSON is the current review state; the append-only Acceptance Ledger and its immutable revision snapshots are the review history. Keep the ledger and its sibling `acceptance_events.jsonl.revisions/` directory beside the acceptance record (or at another explicitly declared, stable path). Do not treat the Run execution ledger or the G0-G4 workflow approval ledger as a substitute: they record different events.

1. **Create the initial record, then initialize its history exactly once.** Complete its immutable identity, Run binding, source snapshot, fixed stage list, and initial `NOT_ASSESSED` final assessment. Then run:
   ```bash
   dor init-acceptance-ledger --record acceptance_record.json --ledger acceptance_events.jsonl --actor "USER_CONFIRMED_REVIEWER_LABEL" --rationale "Created the controlled acceptance record."
   ```
   Use only a reviewer/actor label the user has supplied or explicitly authorized. The string is provenance metadata, not identity authentication.

2. **Review one stage at a time, strictly in the fixed stage order.** Inspect the exact required evidence and deterministic checks before deciding its status. For a terminal status (`PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE`), write fresh `reviewed_by`, timezone-aware `reviewed_at`, and `review_rationale` fields into that stage. `PASS` must also contain exact Run-bound evidence and passing `checks[]`; `FAIL`/`BLOCKED` needs a concrete blocker; `NOT_APPLICABLE` needs a scientific rationale. Record the edit immediately:
   ```bash
   dor record-acceptance-revision --record acceptance_record.json --ledger acceptance_events.jsonl --actor "USER_CONFIRMED_REVIEWER_LABEL" --rationale "Reviewed <stage_id> against its exact evidence and declared acceptance criteria."
   ```
   Do not batch-edit later stages before recording the current stage. The command captures an immutable snapshot and automatically clears every downstream stage's stale status, evidence, checks, limitations, and reviewer metadata. It also resets the final assessment to `NOT_ASSESSED`. Re-read the record after each command and proceed only from the resulting state.

3. **Record the final human decision separately.** Only after all stages have been reviewed and the exact current evidence validates, update `final_assessment` with the authorized `assessed_by` label, a timezone-aware `assessed_at`, rationale, and decision. Then run `dor record-acceptance-revision` again. A changed final decision without fresh assessor metadata is rejected. Do not infer or generate a PASS merely from a green validator report.

4. **Inspect history and validate the current record.** Run both commands:
   ```bash
   dor acceptance-history --ledger acceptance_events.jsonl
   dor validate-acceptance --record acceptance_record.json --run-manifest run_manifest.json --ledger acceptance_events.jsonl --out acceptance_validation_report.json
   ```
   Confirm the history is valid, the latest revision matches the current record, reviewer labels/timestamps/rationales are present, all expected stage invalidations are visible, and the validator reports no issues. The validator's `acceptance_ledger` section must be valid. Include the record, ledger, snapshot directory, history report, and validation report in the final handoff; never hide a prior failed or superseded review.

5. **Handle immutable-scope changes by creating a new Run and Acceptance Record.** Never revise `acceptance_id`, project/run identity, scope, Run Manifest hash, or source snapshot in place. An unregistered direct edit fails validation; do not repair history by deleting or rewriting old events/snapshots. Preserve the previous record and ledger unchanged.

The Acceptance Ledger records review history only. It does not replace G0-G4 approval, grant authorization, authenticate the reviewer, or establish scientific truth. It must never cause the Skill to create a human approval on the user's behalf.




Validate a completed acceptance record with the deterministic Runtime validator:

    dor validate-acceptance --record acceptance_record.json --run-manifest run_manifest.json --ledger acceptance_events.jsonl --out acceptance_validation_report.json

This checks the fixed stage order, stage/decision semantics, exact Run Manifest binding, and current SHA-256 hashes of every cited source/evidence file. A valid report confirms structural and file-integrity conditions only; the human scientific review remains mandatory.


Reconciliation PASS is blocked until all CRITICAL and REVIEW_REQUIRED queue items have explicit human decisions, bound to the exact report and canonical bundle hashes; an item cannot remain REMAINS_UNRESOLVED. Cohort PASS must bind the modeling task to the canonical bundle, report, split manifest, Cohort manifest, and actual hash-verified CSV file. The Cohort report's `eligible_study_ids` (not all source Studies) defines split coverage; explicit validation/test IDs must be eligible. The Cohort manifest must repeat exact hashes for CSV, report, and split. Model run and nested evaluation manifests must in turn bind the exact task, CSV, Cohort manifest, report, and split hashes.


For `publication_handoff`, the evidence descriptor for `publication_package_manifest` must point to the package-root `package_manifest.json`; the `publication_integrity_report` must be stored outside that package directory. The acceptance validator independently executes the existing package auditor on the exact package directory and compares the fresh result with the stored report: guide hash, every indexed artifact hash, missing/extra files, path containment, artifact status, and completeness. A report that merely says `valid=true` cannot pass if the package has changed. Manifest completeness and unresolved_items are also recomputed from artifact statuses.


When an external process proposes recovered source information, keep the proposal separate from accepted data. Verify exact source hashes, locators, quotations, and links to the affected canonical records. Require an explicit human decision before promoting any proposal. A failed search or missing extraction is not evidence that information was never reported.
