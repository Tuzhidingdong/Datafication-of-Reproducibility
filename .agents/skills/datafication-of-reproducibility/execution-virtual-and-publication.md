# Virtual scenarios and publication hand-off

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

- Use `templates/publication_package_plan.example.json` as the immutable `publication_plan_template` selected before Run initialization. Do not create the final `publication_plan` in the project configuration directory and do not edit the source template.
- After `independent_result_review` and `human_review_and_promotion` are complete, the Run pauses at the MANUAL `publication_plan_preparation` stage under the current G3 approval. Record this stage `RUNNING` before copying or editing the template. Copy the exact Run-bound `publication_plan_template` input to `<run_root>/10_publication/publication_package_plan.json`; set the active Run/Project IDs, package version, source hashes, and each real package file's exact `source_artifact_id` and Run-relative `source_path` using `dor run-artifacts --manifest <run_root>/run_manifest.json`. Do not let the Runtime crawl the workspace or infer artifact identities from file names.
- Only mark an artifact complete when its exact Run Artifact is current. Use `partial`, `requires_review`, `not_generated`, or `not_applicable` honestly. For the full-analysis profile, include the model report/artifact, reproducibility evaluation, interaction and robustness reports, interaction selection, virtual prediction, Cohort review record/validation, Worker output, human disposition, and its validation report. When G3 selected one interaction, the mechanism-plan, response-surface, and mechanism-evidence stages must be `REUSE`; include every corresponding output as a sourced package entry. When the selection is empty, all three stages must have valid `SKIPPED` events and all associated package entries remain `not_generated` without a source. Never create placeholder result files. The raw Worker result is retained for audit; only the human disposition record defines which findings are eligible for promotion.
- For a controlled single-Study profile, use the route-matching immutable blueprint described below. Retain the applicability record as `requires_review`; include the exact Bundle, reconciliation, scope/task, applicability record/validation, all N/A reports/manifests, interaction selection, Worker output, human disposition, and validation report. Do not fabricate model scores or cross-Study findings.
- Validate the final plan while the manual stage remains `RUNNING`:
  ```bash
  dor validate-publication-plan --plan <run_root>/10_publication/publication_package_plan.json --manifest <run_root>/run_manifest.json --out <run_root>/10_publication/publication_plan_validation.json
  ```
  Proceed only when the report says `valid=true`; then record `publication_plan_preparation` as `SUCCEEDED`. A failed validation is a failed manual stage, not permission to approve G4.
- After reviewing the exact final plan and at least one scientific result artifact, record G4 against the Run-bound plan and validation report. Bind the complete Worker review input set and **every** source Artifact listed in `publication_plan_validation.source_artifacts`, using its exact Artifact ID/path. This includes optional mechanism/response-surface outputs when present; do not bind `not_generated` entries.
- Only after G4 approves that exact set, Run Manager executes:
  ```bash
  dor build-publication-package --plan <run_root>/10_publication/publication_package_plan.json --validation <run_root>/10_publication/publication_plan_validation.json --workspace-root <run_root> --out-dir <run_root>/10_publication/package --workflow-ledger <run_root>/workflow_gate_ledger.jsonl
  dor audit-publication-package --package-dir <run_root>/10_publication/package --out <run_root>/10_publication/package_integrity_report.json
  ```
  The package builder rechecks the validation report's plan hash and all source hashes. Keep the audit report outside the package directory.
- The Writing Skill must first read README_FOR_WRITING_SKILL.md and package_manifest.json, then retrieve only the files needed for its current writing task. Never invent missing scientific claims, methods, figures, tables, or references.


### Controlled single-Study publication hand-off

Select `templates/publication_package_plan.single_study.example.json` (Structured Dataset) or `templates/publication_package_plan.canonical_adapter.single_study.example.json` (Canonical Bundle) as the immutable `publication_plan_template` before Run initialization. The final Run-bound copy is created only in the `publication_plan_preparation` stage after Worker/human review. Bind every source item to its exact Run Artifact ID/path. Retain the applicability record with a visible review status, and include the N/A report/manifest files as copied evidence records whose descriptions clearly state that no model, cross-Study reproducibility, interaction, or virtual-prediction result was generated. Do not convert N/A entries into zero scores or empty scientific findings. Leave uncreated figures/tables as `not_generated`. G4 must approve the final plan, its validation report, and all package source bindings. The final audit must be run outside the package directory; the downstream Writing Skill must state the limited scope and limitations explicitly.
