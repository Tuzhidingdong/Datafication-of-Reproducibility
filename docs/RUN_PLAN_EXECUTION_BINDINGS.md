# Run Plan execution bindings

This document is the command-level contract between the DoR Skill, the two generic adapter Run Plans, and the Runtime CLI. It defines execution wiring only; it does not define discipline-specific mappings, vocabularies, targets, or analysis assumptions.

All paths below are relative to the active Run workspace unless explicitly labelled as protected package or configuration paths. Resolve them from the current project configuration. Never substitute a hard-coded project path.

## Route selection

Select exactly one template from the validated adapter handoff:

- `STRUCTURED_DATASET`: `templates/run_plan.example.json`
- `CANONICAL_BUNDLE`: `templates/run_plan.canonical_adapter.example.json`

A valid handoff proves package integrity and route eligibility only. It never approves scientific mappings or a workflow gate.

## STRUCTURED_DATASET route

| Run Plan stage | Runtime command / action | Output contract |
|---|---|---|
| `adapter_package_validation` | `dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <run_root>/00_adapter/adapter_handoff.json` | `adapter_handoff` |
| `source_audit` | `dor audit --adapter-handoff <run_root>/00_adapter/adapter_handoff.json --out <run_root>/01_audit` | `dataset_manifest`, `source_inventory`, audit report, coverage/profile files, mapping review queue |
| `g0_review_packet` | Manual review of the exact package handoff and audit artifacts; record G0 only after explicit approval | `g0_review_packet` |
| `mapping_preparation` | Manual preparation of a mapping plan and separate build specification using the exact inventory hash | `mapping_plan`, `build_spec` |
| `mapping_validation` | `dor validate-mapping --plan <run_root>/02_mapping/mapping_plan.json --inventory <run_root>/01_audit/source_inventory.json --out <run_root>/02_mapping/mapping_validation.json` | `mapping_validation` |
| `g1_review_packet` | Manual review of approved mapping rules, grouping grain, relationship rules, transformations, and unresolved mappings; record G1 only after explicit approval | `g1_review_packet` |
| `canonical_build` | `dor build-canonical --plan <run_root>/02_mapping/mapping_plan.json --inventory <run_root>/01_audit/source_inventory.json --spec <run_root>/02_mapping/canonical_build_spec.json --source-root <package_root> --out-dir <run_root>/03_canonical --workflow-ledger <workflow_gate_ledger.jsonl>` | `canonical_bundle`, `canonical_build_report` |
| `canonical_bundle_validation` | `dor validate-bundle --input <run_root>/03_canonical/canonical_bundle.json --out <run_root>/03_canonical/canonical_validation_report.json` | `canonical_validation_report` |
| `canonical_reconciliation` | `dor reconcile-bundle --input <run_root>/03_canonical/canonical_bundle.json --out-dir <run_root>/04_reconciliation` | `reconciliation_report`, `reconciliation_review_queue` |
| `exploratory_discovery` | `dor discover-opportunities --bundle <run_root>/03_canonical/canonical_bundle.json --out-dir <run_root>/04_discovery` | Discovery manifest, report, brief, and aggregate support tables |

## CANONICAL_BUNDLE route

The package must supply exactly one JSON artifact for each generic role: `source_inventory`, `mapping_plan`, `build_spec`, and `canonical_bundle`. The bundle provenance must bind to the exact inventory, mapping plan, and build specification hashes.

| Run Plan stage | Runtime command / action | Output contract |
|---|---|---|
| `adapter_package_validation` | `dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <run_root>/00_adapter/adapter_handoff.json --dataset-manifest-out <run_root>/00_adapter/dataset_manifest.json` | `adapter_handoff`, package snapshot `dataset_manifest` |
| `adapter_artifact_materialization` | `dor materialize-adapter-artifacts --adapter-handoff <run_root>/00_adapter/adapter_handoff.json --role source_inventory --role mapping_plan --role build_spec --role canonical_bundle --out-dir <run_root>/00_adapter/materialized` | Role-named JSON artifacts and `materialization_manifest` |
| `g0_review_packet` | Manual review of package snapshot, exact source inventory, handoff, and materialization manifest; record G0 only after explicit approval | `g0_review_packet` |
| `mapping_validation` | `dor validate-mapping --plan <run_root>/00_adapter/materialized/mapping_plan.json --inventory <run_root>/00_adapter/materialized/source_inventory.json --out <run_root>/02_mapping/mapping_validation.json` | `mapping_validation` |
| `g1_review_packet` | Manual review of the exact mapping plan, recomputed validation, inventory, and build specification; record G1 only after explicit approval | `g1_review_packet` |
| `canonical_bundle_validation` | `dor validate-bundle --input <run_root>/00_adapter/materialized/canonical_bundle.json --out <run_root>/03_canonical/canonical_validation_report.json` | `canonical_validation_report` |
| `canonical_reconciliation` | `dor reconcile-bundle --input <run_root>/00_adapter/materialized/canonical_bundle.json --out-dir <run_root>/04_reconciliation` | `reconciliation_report`, `reconciliation_review_queue` |
| `exploratory_discovery` | `dor discover-opportunities --bundle <run_root>/00_adapter/materialized/canonical_bundle.json --out-dir <run_root>/04_discovery` | Same Discovery outputs as the structured-data route |

The materialization command copies files only. It does not parse, repair, re-map, or rewrite the externally supplied Canonical Bundle. G1 recomputes mapping validation against the exact materialized mapping plan and inventory. G2 checks the bundle's build-provenance hashes against the exact G1-approved artifacts. A package that lacks any of the four roles is not eligible for this formal template; use the structured-data route or ask the external adapter to complete its package.

## Shared downstream stages

| Run Plan stage | Runtime command / action |
|---|---|
| `research_scope_selection` | Manual selection of the formal analysis scope and task based on Discovery; it does not itself approve G2 |
| `g2_review_packet` | Manual review binding the exact Canonical Bundle, canonical validation, reconciliation report, selected scope, and task; record G2 only after explicit approval |
| `cohort_build` | `dor build-cohort --bundle <canonical_bundle.json> --task <modeling_task.json> --out-dir <run_root>/05_modeling/cohort --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `baseline_model_fit` | `dor fit-baselines --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/baseline --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `nested_reproducibility_evaluation` | `dor evaluate-reproducibility --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/reproducibility --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `interaction_discovery` | `dor discover-interactions --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/interactions --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `interaction_robustness` | `dor assess-interaction-robustness --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/interaction_robustness --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `g3_selection_packet` | Manual classification of every reported candidate as selected or not selected; record G3 only after explicit approval |
| `virtual_condition_prediction` | `dor predict-virtual-condition --model-run-dir <run_root>/06_modeling/baseline --query <configuration_root>/virtual_reproduction_query.json --out <run_root>/08_virtual_reproduction/virtual_prediction.json --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `independent_result_review` | First authorize the declared Worker with `dor run-worker-authorize --manifest <run_root>/run_manifest.json --stage independent_result_review --role <role> --provider <provider> --model <model> --project-root <project_root> --authorized-by <reviewer> --rationale <reason>`. Dispatch only the returned bounded task packet. The Worker cannot approve gates or alter analysis artifacts. |
| `human_review_and_promotion` | Manual review and explicit promotion decision; Worker output is not automatically accepted |

## Stage status and artifact recording

Run Manager execution records are separate from the G0-G4 approval ledger. They do not create scientific approvals.

- Before a command starts, record the stage as RUNNING with `dor run-stage-record --manifest <run_root>/run_manifest.json --stage <stage_id> --status RUNNING --producer-kind local --command "<exact CLI command>"`.
- After checking all declared outputs and their hashes, record SUCCEEDED with the same stage ID and producer metadata. Record FAILED when the command or its output validation fails; never record success for a partial output set.
- For a Worker stage, include the exact role/provider/model and returned job/session/task identifiers plus available usage fields in the RUNNING/SUCCEEDED records. For a manual stage, use `--producer-kind manual` and record the reviewer context in the rationale/command metadata.
- Run `dor run-verify --manifest <run_root>/run_manifest.json` after a stage boundary that changes artifact lineage. Use `dor run-resume-plan --manifest <run_root>/run_manifest.json` after interruption; do not rerun successful unaffected stages.
| `publication_package_assembly` | `dor build-publication-package --plan <configuration_root>/publication_package_plan.json --workspace-root <run_root> --out-dir <run_root>/10_publication/package --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `publication_package_audit` | `dor audit-publication-package --package-dir <run_root>/10_publication/package --out <run_root>/10_publication/package_integrity_report.json` |

## Execution and approval rules

1. The Skill resolves paths from the active project and Run configuration; it does not copy paths from this document literally.
2. Before each stage, confirm that declared inputs exist, hash-match the Run artifact manifest, and all direct dependencies have succeeded.
3. Execute only the command bound to that stage. Do not substitute a different command because two outputs have similar names.
4. After command success, verify every declared output exists and record its exact hash and stage status with Run Manager.
5. Manual stages remain manual. A completed command, valid package, valid bundle, or generated review packet is not an approval.
6. Gated commands receive the active workflow ledger. Do not use a legacy bypass.
7. When an upstream input hash changes, follow Run Manager's resume plan and repeat only the invalidated downstream stages.
8. The current Run Plan templates do not schedule the optional response-surface and mechanism-evidence-bridge path. Those remain explicit follow-on operations after a G3 selection, not implicit stages in the main DAG. A later increment may add a conditional-stage contract without weakening the existing G3 controls.
