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

This Draft development branch contains V0.1–V0.9: canonical scientific data contracts, deterministic construction/reconciliation, Study-level cohort and validation, predictive interaction screening/robustness, mechanism-evidence packaging, publication outputs, G0–G4 approval gates, and the hash-bound Run Manager. Engineering acceptance has used synthetic fixtures only. V1.0 introduces a controlled real-data acceptance protocol; it does not authorize bulk corpus processing or imply scientific validity before a user-selected pilot is reviewed.

## Planned layout

- `.agents/skills/datafication-of-reproducibility/SKILL.md`: Antigravity Skill entry point.
- `references/`: methodology, data model, modelling, validation, evidence, orchestration, and publication-output specifications.
- `domain_profiles/template/`: reusable domain-adapter templates.
- `domain_profiles/zinc_battery/`: initial adapter scaffold; mappings remain provisional until actual source files are audited.
- `schemas/`: machine-readable contracts for projects, datasets, workflow state, tasks, findings, publication manifests, and V1.0 acceptance records.
- `runtime/`: deterministic Python engine for audit, canonical construction, reconciliation, modelling, validation, interaction analysis, publication assembly, and run management.
- `docs/V0.9_RUN_MANAGER.md`: explicit stage DAG, artifact lineage, Worker authorization, and safe recovery.
- `docs/V1.0_CONTROLLED_ACCEPTANCE.md`: real-data pilot scope, fixed acceptance stages, evidence requirements, and scientific limits.
- `templates/v1_acceptance_record.example.json`: machine-readable V1.0 acceptance-record starting point.

## Quick start

1. Install the Skill into a workspace under `.agents/skills/` or into the Antigravity global Skill directory.
2. Create a project configuration pointing to the original research data.
3. Audit and hash source inputs without modifying them.
4. Review the source inventory and research scope at G0.
5. Continue only after explicit approval at each applicable gate.

## Scientific safeguards

- Missing information is not silently imputed as reported fact.
- The reported experimental label is not assumed to fully describe the actual physical state.
- Statistical interaction is not automatically interpreted as physical causation.
- Records from the same Study are kept together during Study-level validation.
- Every model, figure, table, and scientific finding must be traceable to data, configuration, code version, and evidence.
- Publication prose is generated from structured research records, not from recollection of source code or chat history.
- One paper/Study is not enough to claim cross-Study reproducibility or support Study-held-out model validation.

## License and data policy

A project license has not yet been selected. Do not commit private literature databases, full-text papers, credentials, local paths containing personal information, run caches, or derived data that cannot be redistributed.

## V0.9 Run Manager

The Runtime provides explicit project run workspaces, a hash-chained run event ledger, stage-attempt recording, bounded Worker authorization packets, dependency-aware resume planning, and regenerable artifact inventories. Run plans are authored up front and name every source/artifact/stage/dependency; no workspace crawling or automatic stage inference is performed. The Run Manager never launches Workers or creates scientific gate approvals. See `docs/V0.9_RUN_MANAGER.md`.

## V1.0 controlled acceptance

The first formal V1.0 scientific acceptance remains limited to one user-selected primary paper and its SI. This acceptance protocol is distinct from the read-only exploratory full-corpus scan provided by Scientific Discovery Engine. The fixed eight-stage protocol, machine-readable record, and deterministic `dor validate-acceptance` validator are defined in `docs/V1.0_CONTROLLED_ACCEPTANCE.md`, `schemas/v1_acceptance_record.schema.json`, and `templates/v1_acceptance_record.example.json`. A one-Study pilot may validate ingestion, provenance, mapping, canonical construction, and reconciliation, but cannot validate cross-Study modelling.


## Scientific Discovery Engine

The discovery-first entry point is `dor discover-opportunities`. It performs a read-only full-corpus exploratory scan using the Chem-Literacy aggregate JSON as the primary input and an optional reconciliation CSV. It writes aggregate-only evidence tables and an Agent research brief; it does not generate accepted scientific findings, automatically establish novelty, or launch formal modelling. See [Scientific Discovery Engine](docs/SCIENTIFIC_DISCOVERY_ENGINE.md).

The formal V1.0 controlled acceptance remains a one-paper/SI scientific validation protocol. It does not block an earlier read-only exploratory scan of the structured corpus.

## Chem-Literacy integration

The v0.1-foundation branch adds dor ingest-chem-literacy for the aggregate papers[].observations[] JSON and optional Reconciliation Ledger CSV. The adapter preserves repeated measurements, links the two exports only by paper_id + reconciliation_id, reports source disagreements, and writes evidence-aware condition-recovery packets. numeric_target_candidates.csv is a candidate-label inventory, not a ready-to-train feature matrix. See docs/CHEM_LITERACY_INTEGRATION.md.

A condition missing from the extraction is not automatically considered absent from the paper. DOR searches the declared local main text/SI, prepares bounded Worker tasks, verifies proposed quotations against exact source files, and leaves every promotion pending human review.


The Chem-Literacy integration also defines a human decision step for recovered experimental conditions. A Worker proposal can be marked REPORTED only after its exact quotation passes source verification and a reviewer accepts it. NOT_REPORTED requires a human-reviewed main text and all available SI with exact source hashes; it cannot be inferred from a missing extraction or failed search. See docs/CHEM_LITERACY_INTEGRATION.md.

## Architecture and standards review

The current implementation inventory, real-data validation gaps, standards reuse decisions, and target module boundaries are documented in:

- [Project Capability Audit](docs/PROJECT_CAPABILITY_AUDIT.md)
- [Standards Alignment](docs/STANDARDS_ALIGNMENT.md)
- [Target Architecture](docs/TARGET_ARCHITECTURE.md)

These documents define an architecture-convergence phase before additional Runtime feature development. The next scientific acceptance target remains one user-selected real paper/SI pilot; synthetic engineering fixtures do not establish real-corpus validity.
