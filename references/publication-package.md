# Publication package specification

## Purpose

Every completed research run must create a self-contained, traceable package for a downstream Writing Skill. The package must let a writing agent locate verified facts, methods, models, figures, tables, mechanisms, limitations, and supporting evidence without reading source code or prior chat history.

## Required root files

- §README_FOR_WRITING_SKILL.md§: human-readable navigation and usage guide.
- §package_manifest.json§: machine-readable index of package files and their roles.

The Writing Skill must read these two files first. It should then retrieve only the files required for the section currently being written.

## Recommended package layout

    manuscript_package/
      README_FOR_WRITING_SKILL.md
      package_manifest.json
      manuscript_outline.md
      data/
      methods/
      results/
      figures/
      tables/
      supporting_information/
      models/
      interactions/
      mechanisms/
      references/
      findings/
      limitations/
      computational_reproduction/

Exact subdirectories may be omitted when no corresponding artifact exists, but the manifest must state their status. Never create empty or fabricated scientific results merely to satisfy a template.

## Contents

### Data records
- dataset manifest and source hashes;
- data dictionary with units and semantic definitions;
- analysis cohort and inclusion/exclusion log;
- missingness and coverage report;
- lineage from derived rows to source records/evidence.

### Methods records
- study/data acquisition and processing facts;
- inclusion/exclusion rules;
- outcome and feature definitions;
- transformations and missing-data handling;
- algorithms, software versions, hyperparameters;
- train/validation/test strategy and group IDs;
- metrics and statistical tests;
- interaction statistics and robustness procedures.

### Model records
For each model, record task/target, cohort IDs, feature list, preprocessing, package versions, hyperparameters, seeds, split IDs, fitted artifact location, predictions, metrics, applicability domain, and limitations.

### Results records
Store machine-readable values alongside narrative drafts. Every reported number must be traceable to a result artifact. Preserve units, significant figures, qualifiers, and denominators.

### Figures and tables
For every figure/table include rendered file, source data file, plotting/generation configuration, caption, and provenance links to models, interactions, or observations.

### Interaction and mechanism records
Include interaction definitions, method/statistic, joint support, independent Study coverage, robustness results, response-surface scope, counterexamples, and source-linked mechanism evidence. When present, include the Mechanism Evidence Bridge report, evidence ledger, review queue, and structured mechanism Findings. Preserve the explicit pending-review state and do not promote candidate hypotheses into established mechanisms.

### Limitations
Record limitations in data coverage, missing variables, selection/reporting bias, study heterogeneity, measurement incompatibility, leakage risk, external validity, extrapolation, and unverified mechanisms.

## Writing Skill rules

1. Read the guide and manifest first.
2. Use the manifest to locate the correct artifact for each manuscript section.
3. Use structured records as the source of truth; narrative drafts are aids, not authority when they conflict with structured records.
4. Never infer an unreported model parameter, sample count, condition, or result.
5. Do not convert candidate mechanisms into established mechanisms. A generated mechanism Finding with `claim_type = mechanism_hypothesis`, `status = candidate`, or report state `PENDING_USER_MECHANISM_REVIEW` must remain a hypothesis unless a separate explicit human review record authorizes stronger wording.
6. Cite original papers using the supplied DOI and evidence pointers; verify bibliographic details before submission.
7. Do not invent references or cite the data package itself as the primary source for a scientific claim.
8. If a required fact is absent or ambiguous, create a concise author query rather than guessing.
9. Keep a traceable mapping from manuscript claims to finding IDs, figure/table IDs, and evidence.
10. Generated Methods/Results text must reflect the actual executed configuration, not a generic template.

## Package manifest

The manifest should include schema version, project/run IDs, package creation time, source dataset hashes, domain profile and version, analysis plan version, artifacts grouped by manuscript section and type, each artifact's package-relative path, format, description, status, hash, linked record IDs, and unresolved items.

Statuses should distinguish complete, partial, not_generated, not_applicable, and requires_review.

## Package integrity

The package must not depend on absolute local paths for navigation. Use package-relative paths. Private source locations may be recorded in local run manifests, but must not be copied into public manuscript packages unless explicitly approved.

A package is not publication-ready merely because drafts exist. It must disclose unverified claims, missing data, and unresolved validation.


## V0.5 deterministic package assembly

The runtime accepts an explicit publication package plan (see schemas/publication_package_plan.schema.json and templates/publication_package_plan.example.json). Each entry identifies one existing source file, its package-relative destination, artifact type, description, completeness status, linked record IDs, and manuscript sections.

The builder never crawls the workspace or classifies files by name. Complete/partial artifacts require an existing workspace-relative file. Paths that are absolute, traverse outside the workspace, or resolve through an escaping symlink are rejected. Not-generated/not-applicable items are represented in the manifest without creating empty placeholder files. Requires-review items may be included with their hash or remain an explicitly unresolved planned path.

Build with:

~~~bash
dor build-publication-package --plan publication_package_plan.json --workspace-root . --out-dir 06_publication/package
dor audit-publication-package --package-dir 06_publication/package --out 06_publication/package_integrity_report.json
~~~

The manifest includes the guide checksum and SHA-256 for every copied artifact. The audit checks missing/extra files, duplicate IDs/paths, artifact states, and hashes. Store the audit report outside the package so it does not become an unindexed package file. A passing audit verifies internal package integrity only; it does not establish scientific validity or publication readiness.

## V0.5 virtual prediction records

A prediction query is tied to one exact modelling task and endpoint and supplies every task feature ID with an explicit value and exact unit. The runtime uses the selected serialized mean, Ridge, majority, or mixed Naive Bayes model and verifies the model artifact/report hashes against modeling_run_manifest.json. It does not retrain or use test observations.

New model artifacts record feature-level marginal domains from train plus validation only: numeric minimum/maximum and categorical vocabulary. Test observations remain excluded. Predictions outside those ranges or using unseen categories are returned only with explicit extrapolation/unknown-category status. Marginal ranges do not establish joint multivariable support.

The virtual report must retain NOT_CALIBRATED, the exact endpoint and units, the fitting/test ID provenance, and the interpretation boundary that this is a model-based scenario estimate rather than a physical experiment. V0.5 does not calculate calibrated intervals, probabilities, or nearest-neighbour support.
