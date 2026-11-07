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

This repository is being initialized as the **V0.1 foundation**. V0.1 focuses on the Antigravity Skill entry point, project and domain configuration, data audit contracts, workflow state, Agent task/result protocols, immutable-source safeguards, and publication-package navigation. It does not yet claim to implement a complete modelling or interaction-discovery engine.

## Planned layout

- `.agents/skills/datafication-of-reproducibility/SKILL.md`: Antigravity Skill entry point.
- `references/`: methodology, data model, modelling, validation, evidence, orchestration, and publication-output specifications.
- `domain_profiles/template/`: reusable domain-adapter templates.
- `domain_profiles/zinc_battery/`: initial adapter scaffold; mappings remain provisional until the actual CSV/JSON are audited.
- `schemas/`: machine-readable contracts for projects, datasets, workflow state, tasks, findings, and publication manifests.
- `runtime/`: deterministic Python engine scaffold.
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
