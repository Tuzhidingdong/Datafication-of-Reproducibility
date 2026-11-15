# Run Manager, recovery, controlled real-data acceptance and revision ledger

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


Generate an explicit artifact view with `dor run-artifacts --manifest run_manifest.json --out artifact_manifest.json`. This report is regenerated from the Run Plan and hash-chained execution events; it is not the source of truth. Inspect statuses and hashes before reusing any output. Generate a token usage view with `dor run-usage --manifest run_manifest.json` after metered stages or at Run completion. It includes only usage recorded on terminal attempts, groups by Stage and provider/model, keeps reasoning/cache counters separate, and preserves missing usage as null rather than zero. When a stage becomes REBUILD_REQUIRED, archive/move its old declared outputs away before retry; the Runtime refuses to overwrite existing outputs. A changed G0-G4 approval event also invalidates stages that were executed against the previous approval hash.

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
