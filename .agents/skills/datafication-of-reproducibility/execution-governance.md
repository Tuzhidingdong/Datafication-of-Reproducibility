# Approval gates, Worker orchestration, records, missing information and stop conditions

## Approval gates

- G0: user confirms research scope, target outcomes, and source files; the Gate binds dataset_manifest, source_inventory, every additional input declared by the active G0 Run stage, plus g0_review_packet and its validation report. Gate rechecks the packet's exact input set and hashes; the preflight report alone is not trusted.
- G1: user approves the mapping plan, source-to-canonical semantics, entity grain, and build specification; the Gate binds mapping_plan, mapping_validation, source_inventory, build_spec, build_spec_validation, g1_review_packet, and its validation report. Gate rechecks packet coverage and hashes.
- G2: user approves the exact Canonical Bundle, canonical validation, reconciliation report and complete decision record, Discovery report, selected scope, and modeling task; the Gate binds every input declared by the active G2 Run stage, plus g2_review_packet and its validation report. Gate recomputes reconciliation/scope validity and independently rechecks the packet's exact input coverage and hashes.
- G3: user selects zero or one interaction candidate for deeper mechanism investigation; the ledger binds the exact interaction report and complete selection record, plus the matching mechanism plan when a candidate is selected.
- G4: user approves the exact publication/deliverables plan and reviewed-result scope; the Gate Ledger binds the publication plan, Worker output, human disposition record, and every exact reviewed artifact listed in that record. Runtime independently checks one-to-one Worker finding dispositions and the promotion-decision relationship.

Before recording G0, G1, or G2 approval, first mark the matching manual review-packet stage RUNNING, create the packet using every input declared by that stage, run `dor validate-run-review-packet` to its declared validation output, and record the stage SUCCEEDED. The Gate repeats the packet/input checks; it does not trust a copied validation status. Before any approval, present the exact artifact paths/hashes, findings, unresolved issues, recommended decision, and consequences. Only the user's explicit decision may trigger `dor gate-record`. Inspect the ledger with `dor gate-status` on resume. A hash mismatch or changed upstream approval invalidates dependent approvals.

Inside a currently approved stage, deterministic checks and pre-authorized scripts may run without asking the user for each command. Do not cross a gate without explicit user approval. Never use `--allow-untracked-legacy` in an actual research workflow.

## Worker orchestration

Use the user's existing Antigravity-to-OpenCode Worker Manager. Do not invent or replace its MCP interface.

- Dispatch only bounded tasks with explicit inputs, permitted actions, expected artifacts, and token/context limits.
- For independent-result review, start with compact summaries and status/count/warning/claim-scope fields from every declared input. Do not read the full modelling cohort, prediction tables, fold-level arrays, or other bulk rows into Worker context. Open only the detailed sections needed to verify a specific potential finding, cite exact artifact locations, and retain the source report hashes in the review record.
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

Stop and report the blocker if a declared structured dataset cannot be parsed, identifiers cannot be reconciled safely from structured fields, target semantics are ambiguous, leakage cannot be controlled, no supported validation design exists, or requested predictions are outside the model's applicability domain. Do not resolve any such blocker by opening original papers/SI or other raw research documents; request corrected structured data or explicit metadata instead. Original-source assets are subject only to path/metadata/hash checks.

Do not fabricate sample counts, feature mappings, model metrics, paper citations, experimental conditions, or mechanism evidence.
