# Datafication-of-Reproducibility

An Antigravity-native research-methodology Skill for learning the reproducible structure of experimental phenomena from scientific data and literature.

The project aims to reconstruct relationships among reported experimental conditions, latent physical states, interacting processes, and observable outcomes. Machine learning is used to predict outcomes and discover candidate interactions; scientific interpretation and independent validation are required before statistical relationships are described as mechanisms.

## Design commitments

- **Platform:** Antigravity Skill, distributed from this repository.
- **Execution:** Hybrid. Python performs deterministic data processing and modelling; Agents handle scientific planning, semantic interpretation, critical review, and mechanism reasoning.
- **Automation:** Guided. The workflow pauses at defined scientific decision gates.
- **Source data:** Preserve. Original input files are read-only; all normalized datasets, derived data, models, and reports are written to separate run directories.
- **Research outputs:** Every completed analysis must produce a traceable scientific record and a paper-oriented deliverables package, including a guide and machine-readable manifest for a downstream writing Skill.

## Repository status

This Draft development branch contains the V0.1 research foundation, V0.2 data-understanding/canonical-construction/reconciliation engine, V0.3 endpoint-specific cohorts, Study-level splits, baseline models and nested evaluation, V0.4 interaction discovery/robustness, response surfaces and mechanism-evidence bridge, and V0.5 publication-package assembly plus virtual condition prediction. V0.6 adds a complete synthetic CLI acceptance path from source audit through package integrity audit. V0.7 adds a hash-bound G0–G4 human approval ledger, fail-closed CLI enforcement, explicit G3 interaction selection, and non-destructive scientific entity-grain diagnostics. V0.8 adds cross-artifact lineage checks at G1–G3 and a full G0–G4 synthetic CLI acceptance run without the legacy bypass. It tests stale upstream re-approval and substituted Canonical Bundle rejection. No real zinc-battery corpus is loaded, and no scientific validity is implied; full scientific acceptance remains reserved for V1.0.

## Planned layout

- `.agents/skills/datafication-of-reproducibility/SKILL.md`: Antigravity Skill entry point.
- `references/`: methodology, data model, modelling, validation, evidence, orchestration, and publication-output specifications.
- `domain_profiles/template/`: reusable domain-adapter templates.
- `domain_profiles/zinc_battery/`: initial adapter scaffold; mappings remain provisional until the actual CSV/JSON are audited.
- `schemas/`: machine-readable contracts for projects, datasets, workflow state, tasks, findings, and publication manifests.
- `runtime/`: deterministic Python engine, including audit, canonical build, reconciliation, modelling cohorts, baseline models, nested cross-study evaluation, pairwise interaction screening, repeated-seed robustness assessment, descriptive response-surface generation, and the evidence-linked mechanism hypothesis bridge.
- `docs/V0.3_MODELING_COHORTS.md`: modelling task, cohort eligibility, split, and output contract.
- `docs/V0.3_BASELINE_MODELS.md`: baseline algorithms, validation-only selection, held-out test evaluation, and model artifact contract.
- `docs/V0.3_REPRODUCIBILITY_EVALUATION.md`: nested Study-level cross-validation, between-Study performance, applicability-domain heuristics, and uncertainty limits.
- `docs/V0.4_INTERACTION_DISCOVERY.md`: pairwise predictive interaction definition, nested validation, joint support, and claim limits.
- `docs/V0.4_INTERACTION_ROBUSTNESS.md`: repeated-seed sensitivity analysis and its interpretation limits.
- `docs/V0.4_INTERACTION_RESPONSE_SURFACE.md`: descriptive partial-dependence surfaces, empirical two-feature support masks, and marginal-effect outputs.
- `docs/V0.4_MECHANISM_EVIDENCE_BRIDGE.md`: source-linked mechanism hypotheses, evidence classification, prospective-independence checks, and contradiction review.
- `docs/V0.5_PUBLICATION_AND_VIRTUAL_REPRODUCTION.md`: explicit publication package plans, SHA-256 integrity audit, serialized-model condition predictions, and applicability-domain boundaries.
- `docs/V0.6_END_TO_END_SYNTHETIC_ACCEPTANCE.md`: cross-module synthetic project acceptance, CLI execution, provenance consistency, tamper detection, and scientific test boundaries.
- `docs/V0.8_APPROVED_WORKFLOW_ACCEPTANCE.md`: full G0–G4 approval-ledger execution, cross-artifact lineage checks, stale/reapproved upstream decisions, and CLI substitution rejection.
- `docs/V0.7_APPROVAL_GATES_AND_SCIENTIFIC_CONTRACTS.md`: append-only hash-bound G0–G4 approval events, CLI enforcement, explicit interaction selection, and Observation/Condition grain diagnostics.
- `templates/`: reusable reports and paper-output templates.
- `tests/`: V0.1 contract and immutability tests.

## Quick start (planned for V0.1)

1. Install the Skill into a workspace under `.agents/skills/` or into the Antigravity global Skill directory.
2. Create a project configuration pointing to the original research data.
3. Run the read-only data audit.
4. Review the audit and analysis scope at the guided approval gate.
5. Continue only after approving the research plan.

Exact installation and runtime instructions will be finalized with the V0.1 implementation.

## Scientific safeguards

- Missing information is not silently imputed as reported fact.
- The reported experimental label is not assumed to fully describe the actual physical state.
- Statistical interaction is not automatically interpreted as physical causation.
- Records from the same study are kept together during study-level validation.
- Every model, figure, table, and scientific finding must be traceable to data, configuration, code version, and evidence.
- Publication prose is generated from structured research records, not from recollection of source code or chat history.

## License and data policy

A project license has not yet been selected. Do not commit private literature databases, full-text papers, credentials, local paths containing personal information, run caches, or derived data that cannot be redistributed.


## V0.9 Run Manager

The Runtime now provides explicit project run workspaces, a hash-chained run event ledger, stage-attempt recording, bounded Worker authorization packets, and dependency-aware resume planning. Run plans are authored up front and name every source/artifact/stage/dependency; no workspace crawling or automatic stage inference is performed. The run manager never launches Workers or creates scientific gate approvals. See docs/V0.9_RUN_MANAGER.md.


V0.9 also provides `dor run-artifacts` to regenerate a hash/provenance inventory from the run plan and event ledger. The artifact manifest is a projection rather than a second mutable source of truth.


The run manager distinguishes a changed protected source (`SOURCE_CHANGED_NEW_RUN_REQUIRED`) from a stale derived artifact (`REBUILD_REQUIRED`). Raw-source changes require a new run; derived-stage rebuilds require archiving prior output paths before a new attempt.
