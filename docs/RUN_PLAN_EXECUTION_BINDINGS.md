# Run Plan execution bindings

This document is the command-level contract between the DoR Skill, the two generic adapter Run Plans, and the Runtime CLI. It defines execution wiring only; it does not define discipline-specific mappings, vocabularies, targets, or analysis assumptions.

All paths below are relative to the active Run workspace unless explicitly labelled as protected package or configuration paths. Resolve them from the current project configuration. Never substitute a hard-coded project path.

## Route preflight and Run initialization

Before choosing the formal Run Plan, determine the adapter route without auditing or modifying any source data:

    dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <project_root>/run_control/adapter_route_preflight.json

Keep this preflight file outside the protected adapter package and outside all declared source/artifact files. A preflight result is only a package-integrity and route-selection result. For a STRUCTURED_DATASET route, do not run source audit before formal Run initialization. For a CANONICAL_BUNDLE route, the optional pre-Run Discovery scan is permitted but remains exploratory and does not approve G0-G2.

Select the matching Run Plan template, set its source roots, source artifact paths, workflow ledger path, and project/configuration paths from the active project configuration, then initialize a new isolated Run:

    dor run-init --plan <selected_run_plan.json> --run-root <new_run_root>

Run Manager validates the declared source roots/artifacts and dependency graph, creates the Run workspace and `run_manifest.json`, and snapshots the exact plan/source inputs. Do not reuse an old Run root for a new plan. Verify initialization before stage execution:

    dor run-verify --manifest <run_root>/run_manifest.json

The first formal stage regenerates the handoff into the Run workspace. Do not use the preflight handoff as a Run output or copy it into the protected adapter package.

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
| `build_spec_validation` | `dor validate-build-spec --plan <run_root>/02_mapping/mapping_plan.json --inventory <run_root>/01_audit/source_inventory.json --spec <run_root>/02_mapping/canonical_build_spec.json --out <run_root>/02_mapping/build_spec_validation.json` | `build_spec_validation` |
| `g1_review_packet` | Manual review of approved mapping rules, grouping grain, relationship rules, transformations, and unresolved mappings; record G1 only after explicit approval | `g1_review_packet` |
| `canonical_build` | `dor build-canonical --plan <run_root>/02_mapping/mapping_plan.json --inventory <run_root>/01_audit/source_inventory.json --spec <run_root>/02_mapping/canonical_build_spec.json --source-root <package_root> --out-dir <run_root>/03_canonical --workflow-ledger <workflow_gate_ledger.jsonl>` | `canonical_bundle`, `canonical_build_report` |
| `canonical_bundle_validation` | `dor validate-bundle --input <run_root>/03_canonical/canonical_bundle.json --out <run_root>/03_canonical/canonical_validation_report.json` | `canonical_validation_report` |
| `canonical_reconciliation` | `dor reconcile-bundle --input <run_root>/03_canonical/canonical_bundle.json --out-dir <run_root>/04_reconciliation` | `reconciliation_report`, `reconciliation_review_queue` |
| `reconciliation_decision_review` | Manual review of every issue in the exact report/queue; record exactly one explicit decision for every issue in `04_reconciliation/reconciliation_decisions.json`, including reviewer, timestamp, rationale, and evidence references where applicable; the Runtime rejects missing, duplicate, or unknown issue IDs | `reconciliation_decisions` |
| `reconciliation_decision_validation` | `dor validate-reconciliation-decisions --decisions <run_root>/04_reconciliation/reconciliation_decisions.json --report <run_root>/04_reconciliation/reconciliation_report.json --bundle <run_root>/03_canonical/canonical_bundle.json --out <run_root>/04_reconciliation/reconciliation_decision_validation.json` | `reconciliation_decision_validation` |
| `exploratory_discovery` | `dor discover-opportunities --bundle <run_root>/03_canonical/canonical_bundle.json --out-dir <run_root>/04_discovery` | Discovery manifest, report, brief, and aggregate support tables |

## CANONICAL_BUNDLE route

The package must supply exactly one JSON artifact for each generic role: `source_inventory`, `mapping_plan`, `build_spec`, and `canonical_bundle`. The bundle provenance must bind to the exact inventory, mapping plan, and build specification hashes.

| Run Plan stage | Runtime command / action | Output contract |
|---|---|---|
| `adapter_package_validation` | `dor prepare-adapter-handoff --manifest <package_root>/adapter_manifest.json --package-root <package_root> --out <run_root>/00_adapter/adapter_handoff.json --dataset-manifest-out <run_root>/00_adapter/dataset_manifest.json` | `adapter_handoff`, package snapshot `dataset_manifest` |
| `adapter_artifact_materialization` | `dor materialize-adapter-artifacts --adapter-handoff <run_root>/00_adapter/adapter_handoff.json --role source_inventory --role mapping_plan --role build_spec --role canonical_bundle --out-dir <run_root>/00_adapter/materialized` | Role-named JSON artifacts and `materialization_manifest`; each source inventory row is checked against declared source/artifact paths, hashes, and formats |
| `g0_review_packet` | Manual review of package snapshot, exact source inventory, handoff, and materialization manifest; record G0 only after explicit approval | `g0_review_packet` |
| `mapping_validation` | `dor validate-mapping --plan <run_root>/00_adapter/materialized/mapping_plan.json --inventory <run_root>/00_adapter/materialized/source_inventory.json --out <run_root>/02_mapping/mapping_validation.json` | `mapping_validation` |
| `build_spec_validation` | `dor validate-build-spec --plan <run_root>/00_adapter/materialized/mapping_plan.json --inventory <run_root>/00_adapter/materialized/source_inventory.json --spec <run_root>/00_adapter/materialized/build_spec.json --out <run_root>/02_mapping/build_spec_validation.json` | `build_spec_validation` |
| `g1_review_packet` | Manual review of the exact mapping plan, recomputed validation, inventory, and build specification; record G1 only after explicit approval | `g1_review_packet` |
| `canonical_bundle_validation` | `dor validate-bundle --input <run_root>/00_adapter/materialized/canonical_bundle.json --out <run_root>/03_canonical/canonical_validation_report.json` | `canonical_validation_report` |
| `canonical_reconciliation` | `dor reconcile-bundle --input <run_root>/00_adapter/materialized/canonical_bundle.json --out-dir <run_root>/04_reconciliation` | `reconciliation_report`, `reconciliation_review_queue` |
| `reconciliation_decision_review` | Manual review of every issue in the exact report/queue; record exactly one explicit decision for every issue in `04_reconciliation/reconciliation_decisions.json`, including reviewer, timestamp, rationale, and evidence references where applicable; the Runtime rejects missing, duplicate, or unknown issue IDs | `reconciliation_decisions` |
| `reconciliation_decision_validation` | `dor validate-reconciliation-decisions --decisions <run_root>/04_reconciliation/reconciliation_decisions.json --report <run_root>/04_reconciliation/reconciliation_report.json --bundle <run_root>/00_adapter/materialized/canonical_bundle.json --out <run_root>/04_reconciliation/reconciliation_decision_validation.json` | `reconciliation_decision_validation` |
| `exploratory_discovery` | `dor discover-opportunities --bundle <run_root>/00_adapter/materialized/canonical_bundle.json --out-dir <run_root>/04_discovery` | Same Discovery outputs as the structured-data route |

The materialization command copies files only. It does not parse, repair, re-map, or rewrite the externally supplied Canonical Bundle. G1 recomputes mapping validation against the exact materialized mapping plan and inventory. G2 checks the bundle's build-provenance hashes against the exact G1-approved artifacts. A package that lacks any of the four roles is not eligible for this formal template; use the structured-data route or ask the external adapter to complete its package.

## Shared downstream stages

| Run Plan stage | Runtime command / action |
|---|---|
| `research_scope_selection` | Manual selection of the formal analysis scope and task based on Discovery; it does not itself approve G2 |
| `g2_review_packet` | Manual review binding the exact Canonical Bundle, canonical validation, reconciliation report, validated reconciliation decisions, selected scope, and task; record G2 only after explicit approval using the route-specific command below |
| `cohort_build` | `dor build-cohort --bundle <canonical_bundle.json> --task <modeling_task.json> --out-dir <run_root>/05_modeling/cohort --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `baseline_model_fit` | `dor fit-baselines --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/baseline --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `nested_reproducibility_evaluation` | `dor evaluate-reproducibility --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/reproducibility --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `interaction_discovery` | `dor discover-interactions --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/interactions --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `interaction_robustness` | `dor assess-interaction-robustness --cohort-dir <run_root>/05_modeling/cohort --task <modeling_task.json> --out-dir <run_root>/06_modeling/interaction_robustness --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `g3_selection_packet` | Manual classification of every reported candidate as selected or not selected; prepare the exact selection record before requesting G3 |
| `mechanism_plan_preparation` | When `selected_interaction_ids` is non-empty, manually prepare `07_review/mechanism_plan.json` from the generic template; include the exact plan in the G3 approval packet. If the selection is empty, Run Manager records this stage as `SKIPPED` |
| `response_surface_generation` | When one candidate is selected and the exact current G3 approval is valid: `dor generate-interaction-surface --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --interaction-dir <run_root>/06_modeling/interactions --interaction-id <the_single_ID_in_07_review/interaction_selection.json> --out-dir <run_root>/07_response_surface --robustness-dir <run_root>/06_modeling/interaction_robustness --workflow-ledger <run_root>/workflow_gate_ledger.jsonl>` |
| `mechanism_evidence_bridge` | When one candidate is selected and the exact current G3 approval is valid: `dor build-mechanism-evidence-bridge --bundle <canonical_bundle_path_from_run_artifact_manifest> --cohort-dir <run_root>/05_modeling/cohort --task <run_root>/05_scope/modeling_task.json --interaction-dir <run_root>/06_modeling/interactions --plan <run_root>/07_review/mechanism_plan.json --out-dir <run_root>/07_mechanism_bridge --robustness-dir <run_root>/06_modeling/interaction_robustness --response-surface-dir <run_root>/07_response_surface --workflow-ledger <run_root>/workflow_gate_ledger.jsonl>` |
| `virtual_condition_prediction` | `dor predict-virtual-condition --model-run-dir <run_root>/06_modeling/baseline --query <configuration_root>/virtual_reproduction_query.json --out <run_root>/08_virtual_reproduction/virtual_prediction.json --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `independent_result_review` | First authorize the declared Worker with `dor run-worker-authorize --manifest <run_root>/run_manifest.json --stage independent_result_review --role <role> --provider <provider> --model <model> --project-root <project_root> --authorized-by <reviewer> --rationale <reason>`. Dispatch only the returned bounded task packet. The Worker cannot approve gates or alter analysis artifacts. |
| `human_review_and_promotion` | Manual review and explicit promotion decision; Worker output is not automatically accepted |
| `publication_package_assembly` | `dor build-publication-package --plan <configuration_root>/publication_package_plan.json --workspace-root <run_root> --out-dir <run_root>/10_publication/package --workflow-ledger <workflow_gate_ledger.jsonl>` |
| `publication_package_audit` | `dor audit-publication-package --package-dir <run_root>/10_publication/package --out <run_root>/10_publication/package_integrity_report.json` |

## Exact G0-G4 approval artifact bindings

Use the exact Run-relative file paths below. These commands bind the approval to the same artifacts produced by the active Run. Do not use project-global or preflight copies.

### STRUCTURED_DATASET route

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G0 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact dataset_manifest=<run_root>/01_audit/dataset_manifest.json --artifact source_inventory=<run_root>/01_audit/source_inventory.json

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G1 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact mapping_plan=<run_root>/02_mapping/mapping_plan.json --artifact mapping_validation=<run_root>/02_mapping/mapping_validation.json --artifact source_inventory=<run_root>/01_audit/source_inventory.json --artifact build_spec=<run_root>/02_mapping/canonical_build_spec.json --artifact build_spec_validation=<run_root>/02_mapping/build_spec_validation.json

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G2 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact canonical_bundle=<run_root>/03_canonical/canonical_bundle.json --artifact canonical_validation_report=<run_root>/03_canonical/canonical_validation_report.json --artifact reconciliation_report=<run_root>/04_reconciliation/reconciliation_report.json --artifact reconciliation_decisions=<run_root>/04_reconciliation/reconciliation_decisions.json --artifact modeling_task=<run_root>/05_scope/modeling_task.json

### CANONICAL_BUNDLE route

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G0 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact dataset_manifest=<run_root>/00_adapter/dataset_manifest.json --artifact source_inventory=<run_root>/00_adapter/materialized/source_inventory.json

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G1 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact mapping_plan=<run_root>/00_adapter/materialized/mapping_plan.json --artifact mapping_validation=<run_root>/02_mapping/mapping_validation.json --artifact source_inventory=<run_root>/00_adapter/materialized/source_inventory.json --artifact build_spec=<run_root>/00_adapter/materialized/build_spec.json --artifact build_spec_validation=<run_root>/02_mapping/build_spec_validation.json

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G2 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact canonical_bundle=<run_root>/00_adapter/materialized/canonical_bundle.json --artifact canonical_validation_report=<run_root>/03_canonical/canonical_validation_report.json --artifact reconciliation_report=<run_root>/04_reconciliation/reconciliation_report.json --artifact reconciliation_decisions=<run_root>/04_reconciliation/reconciliation_decisions.json --artifact modeling_task=<run_root>/05_scope/modeling_task.json

### Shared G3 and G4 gates

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G3 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact interaction_report=<run_root>/06_modeling/interactions/interaction_discovery_report.json --artifact interaction_manifest=<run_root>/06_modeling/interactions/interaction_discovery_manifest.json --artifact robustness_report=<run_root>/06_modeling/interaction_robustness/interaction_robustness_report.json --artifact robustness_manifest=<run_root>/06_modeling/interaction_robustness/interaction_robustness_manifest.json --artifact interaction_selection=<run_root>/07_review/interaction_selection.json [--artifact mechanism_plan=<run_root>/07_review/mechanism_plan.json when one candidate is selected]

    dor gate-record --workflow-ledger <run_root>/workflow_gate_ledger.jsonl --gate G4 --decision APPROVE --reviewer "<reviewer>" --rationale "<rationale>" --artifact publication_plan=<configuration_root>/publication_package_plan.json --artifact model_report=<run_root>/06_modeling/baseline/model_report.json

For G2, the Gate validator recomputes the reconciliation-decision validation directly from the exact bound decision file, report, and Canonical Bundle. The Run Plan's separate `reconciliation_decision_validation` stage remains a human-readable, hash-recorded output for the review packet; the G2 event need not trust or bind a self-reported `valid=true` result. The G3 `mechanism_plan` artifact is required by the G3 validator only when the selection contains one candidate; omit it for an empty selection.

## Stage status and artifact recording

Run Manager execution records are separate from the G0-G4 approval ledger. They do not create scientific approvals.

- Before a command starts, record the stage as RUNNING with `dor run-stage-record --manifest <run_root>/run_manifest.json --stage <stage_id> --status RUNNING --producer-kind <local|worker|manual> --command "<exact CLI command>"`.
- After checking all declared outputs and their hashes, record SUCCEEDED with the same stage ID and producer metadata. Record FAILED when the command or its output validation fails; never record success for a partial output set.
- For a conditional stage, consult `dor run-resume-plan`. Record `SKIPPED` only when its action is exactly `SKIP_REQUIRED`, using the stage's declared executor as `--producer-kind`. A skipped stage writes no outputs, creates no approval, and is reusable only while its declared activation input remains unchanged and the condition remains false.
- For a Worker stage, include the exact role/provider/model and returned job/session/task identifiers plus available usage fields in the RUNNING/SUCCEEDED records. For a manual stage, use `--producer-kind manual` and record the reviewer context in the rationale/command metadata.
- Run `dor run-verify --manifest <run_root>/run_manifest.json` after a stage boundary that changes artifact lineage. Use `dor run-resume-plan --manifest <run_root>/run_manifest.json` after interruption; do not rerun successful unaffected stages.
- Conditional activation is declared on a stage as `activation: {artifact_id, json_pointer, operator, value?}`. The activation artifact must also be an explicit stage input. Supported operators are `exists`, `not_exists`, `array_non_empty`, `array_empty`, `boolean_true`, `boolean_false`, `equals`, and `not_equals`. JSON Pointer evaluation occurs only after the activation artifact's producer is currently reusable. The scheduler does not infer or rewrite activation data.

The Canonical Bundle path is route-dependent: resolve the `canonical_bundle` artifact by ID from `dor run-artifacts` rather than hard-coding one template's directory. In the structured route it is produced by `canonical_build`; in the canonical-adapter route it is the verified materialized bundle. The modeling-task, cohort, interaction, robustness, response-surface, and mechanism-plan paths above are the Run-relative paths declared by both templates. Resolve them from the active `run_root`, not from a prior Run or project-global working directory.

## Execution and approval rules

1. The Skill resolves paths from the active project and Run configuration; it does not copy paths from this document literally.
2. Before an active stage runs, confirm that all declared inputs exist, hash-match the Run artifact manifest, all direct dependencies are reusable, and its required gate is currently approved. A condition-false stage may be recorded as SKIPPED once its activation input is current; it does not need unrelated active-stage inputs or outputs.
3. Execute only the command bound to that stage. Do not substitute a different command because two outputs have similar names.
4. After command success, verify every declared output exists and record its exact hash and stage status with Run Manager.
5. Manual stages remain manual. A completed command, valid package, valid bundle, or generated review packet is not an approval.
6. Gated commands receive the active workflow ledger. Do not use a legacy bypass.
7. When an upstream input hash changes, follow Run Manager's resume plan and repeat only the invalidated downstream stages.
8. The two Run Plan templates declare the post-selection stages explicitly. If `selected_interaction_ids` is empty, the mechanism-plan preparation, response-surface, and mechanism-evidence-bridge stages are recorded as `SKIPPED`; no G3 mechanism-plan binding or optional analysis output is fabricated. If exactly one candidate is selected, prepare the mechanism plan before G3, bind it in the user's G3 approval, then execute the two analysis stages only under that exact current G3 approval. A condition skip never satisfies an input-artifact dependency and never creates a gate decision.
