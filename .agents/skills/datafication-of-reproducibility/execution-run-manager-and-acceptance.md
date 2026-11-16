# Run Manager, recovery, controlled real-data acceptance and revision ledger

## V0.9 project Run Manager (mandatory for managed runs)

Before the first scientific operation, decompose the intended workflow into a complete explicit stage DAG. Do this up front; do not let the Agent opportunistically decide coarse or convenient stage boundaries during execution. The run plan must declare every source artifact, stage dependency, exact input artifact ID, output artifact ID/path, executor, and required approval gate. Use schemas/run_plan.schema.json and templates/run_plan.example.json. Never crawl a workspace to populate this plan.

Initialize a new independent run workspace with:

    dor run-init --plan run_plan.json --run-root path/to/new/run

Keep the original plan and raw sources unchanged. The runtime creates run_manifest.json and run_events.jsonl and binds the run to the exact plan and source hashes. Never reuse a run after a source file changes; create a new run.

### Contract-bound local stage execution (mandatory for supported adapter Runs)

For a supported Structured Dataset or Canonical Bundle Run, do not manually wrap local CLI commands with separate `run-stage-record` calls. Use the contract-bound runner so the exact permitted subcommand and Run lifecycle are connected:

1. Read `dor run-resume-plan --manifest run_manifest.json`; select the first actionable stage in dependency order and inspect its `action_binding` input/output paths.
2. The Runtime builds the local command's argv automatically from the route/profile-specific `argv_template` in `runtime/src/dor/stage_execution_contract.json`. Artifact paths, output directories, the Run root, and explicitly declared JSON fields are resolved from the active Run; do not create per-stage argument JSON files for supported adapter Runs.
3. Preview one stage without mutation when useful:

       dor run-stage-execute --manifest run_manifest.json --stage <stage_id> --dry-run

4. Advance the Run:

       dor run-advance --manifest run_manifest.json --max-local-stages 10

The runner executes ready local stages in dependency order and pauses at the first MANUAL stage, Worker authorization boundary, unapproved Gate, unresolved user-choice value, or failure. Its report includes the generated argv for completed local stages, the next stage, and the bound evidence paths. After completing and recording a human/Worker operation, invoke `run-advance` again. Inactive conditional stages are recorded as SKIPPED by the Runtime. Each call is limited to ten local stages by default.

The contract binding language is deliberately small and non-executable: it can resolve an Artifact path, an Artifact's parent directory, the active Run root, a scalar at a declared JSON pointer, or exactly one item from a selected-value array. If a required user choice is absent or ambiguous (for example, zero or multiple selected interaction IDs where one response surface is required), the runner returns `INPUT_REQUIRED` and does not launch the command. For custom, unbound Run Plans only, `--args-file` or `--args-dir` remains available as an explicit argv override.

The Runtime runner obtains the CLI subcommand only from `stage_execution_contract.json`, never invokes a shell, records RUNNING before launch, and records SUCCEEDED only when every declared output exists and can be hashed. It records FAILED on non-zero exit, timeout, launch error, or missing output. Partial outputs are preserved under `.dor_attempt_archive/<stage_id>/`; they are not silently deleted. Re-read `run-resume-plan` after every stage because the next action may have changed. The runner injects the immutable Run's workflow-ledger and manifest arguments for commands that require them; do not pass or override those arguments.

Use `run-stage-record` only for MANUAL/WORKER stage lifecycle events, never as a substitute for executing a local CLI stage. For every MANUAL stage, record `RUNNING` with `--producer-kind manual` immediately after it becomes the next human action and **before** creating/editing declared outputs or invoking its validator. Then complete the human operation and run the action binding's validator where specified; record `SUCCEEDED` only after validation succeeds and all declared outputs exist, or `FAILED` with a concrete reason when the operation is rejected or cannot be completed. This order is mandatory: the review-packet and reviewed-findings validators reject calls unless their manual stage already has a `RUNNING` event. Worker stages likewise record `RUNNING` before dispatch and a terminal result afterward; they still require `run-worker-authorize`, an explicit host Worker Manager dispatch, returned job/session/usage data, and a separate human review/promotion stage. Before a formal `worker_review_output` can be recorded SUCCEEDED, the Runtime validates the Worker Result structure, finding IDs, allowed input artifact references, and exact evidence locators. It requires the result's `task_id` to match the deterministic task ID in the exact DoR authorization packet; the host Worker Manager task ID remains a separate producer metadata field and is recorded only when returned. A valid `partial` result remains reviewable with explicit limitations; a `blocked`/`failed` result or invalid/missing output is recorded as FAILED, and every present staging file is moved to a per-attempt archive with a hash-bound manifest so a fresh authorization can retry without overwriting. The human promotion validator still independently rechecks the result and requires a one-to-one disposition for every finding. `dor run-artifacts` exposes failed Worker attempts separately as hash-verified archives, never as reusable scientific outputs. Include Worker token counts only when returned by the existing Worker Manager; unknown usage stays unknown.

For a Worker stage, first present role, provider, model, active project root, task inputs/hashes, staging outputs, and restrictions to the user. Wait for explicit authorization, then run dor run-worker-authorize. The returned packet must conform to `schemas/run_worker_task_packet.schema.json`; preserve its `task_id`, `attempt`, `authorization_event_hash`, and `task_packet_sha256` with the host job metadata when supported. The task ID is deterministically bound into the immutable Run Event for that Stage/Attempt, and the Worker Result must return that exact ID. The command records authorization; it does not dispatch a Worker. Invoke the existing Worker Manager only after that authorization. Never silently choose or start a Worker. Workers may write only new files under worker_staging/<stage_id>/; they cannot write into protected sources, ledgers, manifests, or approved artifacts. A human review/promotion stage must separately approve and materialize accepted outputs.

On every resume, run:

    dor run-verify --manifest run_manifest.json
    dor run-status --manifest run_manifest.json
    dor run-resume-plan --manifest run_manifest.json --out resume_plan.json

Reuse only stages explicitly marked REUSE. Rebuild only the stale stage and its declared downstream dependents; keep independent reusable stages. Do not interpret RUNNING as stopped: inspect the external process first, and only then use --confirm-abandoned to create a replacement attempt. A changed source requires a new run. Resume planning does not execute commands, dispatch Workers, or record G0-G4 decisions.

The run event ledger is execution provenance only. It does not approve scientific scope, mapping, canonical data, interactions, or publication. G0-G4 remain the only scientific approval gates. See ../../../docs/V0.9_RUN_MANAGER.md.

For Worker stages, treat the task packet as a strict file-access boundary, but do not describe it as an OS sandbox. Configure the external Worker Manager with guarded permissions and a bounded workdir; include every protected scientific input in the explicit stage input list so the Runtime can verify its hashes after completion. Do not give a Worker broad workspace access when a small staging workdir and declared input copies are sufficient.


Generate an explicit artifact view with `dor run-artifacts --manifest run_manifest.json --out artifact_manifest.json`. This report is regenerated from the Run Plan and hash-chained execution events; it is not the source of truth. Inspect statuses and hashes before reusing any output. Generate a token usage view with `dor run-usage --manifest run_manifest.json` after metered stages or at Run completion. It includes only usage recorded on terminal attempts, groups by Stage, Worker role, and provider/model, keeps reasoning/cache counters separate, and preserves missing usage as null rather than zero. When a stage becomes REBUILD_REQUIRED, archive/move its old declared outputs away before retry; the Runtime refuses to overwrite existing outputs. A changed G0-G4 approval event also invalidates stages that were executed against the previous approval hash.

V0.9 does not yet implement automatic parent/child Run orchestration. The two formal adapter Run Plans now declare the post-G3 response-surface and mechanism-evidence-bridge path as conditional stages, so this path remains inside the same immutable Run. Only for a genuinely new optional branch that is not declared in the parent plan, create a separate follow-on Run with the exact parent outputs and required approvals declared as immutable source_artifacts. Record the parent run_id and manifest SHA-256 in the project-level Run index; never alter the parent Run plan.

A stage whose declared source input differs from the run-init SHA-256 is reported as `SOURCE_CHANGED_NEW_RUN_REQUIRED`; do not retry that stage inside the old Run. Initialize a new Run from the revised source snapshot.


The Run Manager initializes run_events.jsonl with an immutable RUN_INITIALIZED record binding the manifest's project/run scope, exact plan hash, source roots and source hashes, workflow-ledger path, and stage order. Runtime compares this record to run_manifest.json on every operation. Do not edit either control file by hand.


## Controlled single-Study Run profile

When the declared analysis scope contains exactly one independent Study, use the route-matching `CONTROLLED_SINGLE_STUDY` Run Plan template rather than the full-analysis template. Preserve G0-G4 and the explicit Worker authorization/review sequence. After G2, create and validate the human applicability record, then use the deterministic NOT_APPLICABLE artifact command. Do not run modelling or interaction commands, fabricate empty model scores, split observations into pseudo-Studies, or report virtual predictions. G3 must explicitly approve a NOT_APPLICABLE interaction selection; the Worker reviews the provenance and scope limitations; G4 binds those exact records before publication assembly.

For the post-Run Acceptance Record, mark only `cohort_feasibility` and `modeling_validation` as NOT_APPLICABLE, cite the same applicability record/validation report plus exact Canonical Bundle and Modeling Task in each stage's evidence, and conclude CONDITIONAL_PASS only after every other stage has passed. Follow the exact operator commands and schemas in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`.

## Post-Run Acceptance initialization (mandatory for V1.0)

Before `run-init`, add the V1.0 provenance-only source list to the Run Plan's top-level `acceptance_source_artifacts` property. It is separate from operational `source_artifacts`: only explicit source ID, role, absolute path, and hash are retained. All listed paths must be under declared source roots. A controlled single-Study Run must include both `PRIMARY_PAPER` and `SUPPLEMENTARY_INFORMATION`; add linked structured inputs as `STRUCTURED_DATA`. These files are never Stage inputs, are never sent to a Worker, and their contents must never be opened or interpreted by DoR. The Run Manager only snapshots and verifies their byte-level SHA-256.

After every Run stage is current or explicitly SKIPPED, prepare:
- `templates/v1_source_selection_manifest.example.json` using the exact Acceptance source IDs, roles, paths, hashes, and sorted Study IDs in the completed Run.
- `templates/v1_extraction_review_record.example.json` using the exact hashes for selected sources only; excluded sources stay in the full source-selection partition with their exclusion reason and do not enter extraction review. Review the delivered structured CSV/JSON records and opaque upstream locators only. Use `UPSTREAM_EXTRACTION_UNVERIFIED` when upstream extraction fidelity cannot be verified within DoR; never dereference a paper/SI locator. Unresolved `REVIEW_REQUIRED` items block a PASS.

Create the separate Acceptance draft and revision history with:

    dor init-acceptance --manifest <run_root>/run_manifest.json --out <acceptance_root>/acceptance_record.json --source-selection-manifest <acceptance_root>/source_selection_manifest.json --extraction-review-record <acceptance_root>/extraction_review_record.json --actor "<reviewer>" --rationale "Initialize acceptance for the completed Run"

The initializer verifies the completed Run, validates the source partition and structured extraction review against the immutable provenance snapshot, derives exact Study IDs from the Canonical Bundle, binds the final Run Event and G0-G4 Gate ledgers, and creates all eight Acceptance stages as `NOT_STARTED`. It also creates the sibling `acceptance_record_acceptance_events.jsonl` revision ledger. It does not issue approvals or scientific PASS decisions. Complete reviews in fixed order, register each edit with `dor record-acceptance-revision`, then run `dor validate-acceptance` and retain a detached checkpoint. Never place Acceptance inside the Run DAG: the final Run Event Ledger must remain unchanged after the Acceptance record binds it.

## V1.0 controlled real-data acceptance (mandatory)

V1.0 is a controlled acceptance, not a bulk-corpus run. The Agent selects one pilot source candidate from declared structured-input metadata under docs/V1.0_CONTROLLED_ACCEPTANCE.md; the user approves scope at the required gate. Before Run initialization, declare all provenance-only paper/SI/structured sources in the Run Plan's separate `acceptance_source_artifacts` list. Do not read, parse, render, OCR, or send original paper/SI contents to an LLM/Worker. Original documents are provenance-only; review only the delivered structured records and metadata. After the Run completes G0-G4, Worker review, and Publication, prepare the two post-Run source-review records and use `dor init-acceptance` to create the Run-bound record and revision ledger; do not manually seed it from the example template. The initializer derives `source_snapshot.study_ids` from the exact explicit Study IDs present in the Run Canonical Bundle; never derive them from row counts, filenames, or a guessed paper-to-study mapping. `study_count` must equal the number of unique listed IDs. Every stage marked PASS must also include at least one `checks[]` assertion against a JSON artifact already listed in that same stage's evidence; use an RFC 6901 json_pointer and a supported operator so the Runtime computes the result from the artifact rather than accepting a self-reported check status.

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

The validator reads the exact hash-matched JSON evidence. It checks selected and excluded sources as a complete disjoint partition of the initialized source snapshot, requires explicit exclusion reasons, and limits source inventory entries to selected files. It checks source-hash bindings and structured-record locator metadata in extraction review, mapping-plan/source-inventory linkage, canonical graph integrity and Study membership, reconciliation-to-bundle hash linkage, the Cohort's explicit `eligible_study_ids`, and exact split coverage. It does not inspect original source content or verify upstream extraction fidelity. For a multi-Study PASS, the model report, serialized model, and run manifest must agree; nested evaluation must hold every eligible Study out exactly once, keep inner and outer Study groups disjoint, and match the evaluation manifest and its hashes. At least four eligible Studies are required for the nested evaluation contract. These checks do not impose a model performance threshold or turn descriptive errors into calibrated uncertainty.

The acceptance record is a review ledger, not an automatic scientific truth score. A schema-valid record still requires human inspection of the cited evidence. Do not mark full PASS unless all eight stages pass; a one-Study pilot should normally conclude CONDITIONAL_PASS with its limitations stated. See ../../../docs/V1.0_CONTROLLED_ACCEPTANCE.md.

### Acceptance revision ledger — mandatory operational procedure

The acceptance JSON is the current review state; the append-only Acceptance Ledger and its immutable revision snapshots are the review history. Keep the ledger and its sibling `acceptance_events.jsonl.revisions/` directory beside the acceptance record (or at another explicitly declared, stable path). Do not treat the Run execution ledger or the G0-G4 workflow approval ledger as a substitute: they record different events.

1. **Initialize the Run-bound Acceptance draft and revision ledger together, exactly once.** First prepare the two post-Run evidence files from the exact immutable `acceptance_source_artifacts` snapshot: `source_selection_manifest.json` and `extraction_review_record.json`. Do not manually create or pre-populate `acceptance_record.json` from the template. Then run:
   ```bash
   dor init-acceptance --manifest <run_root>/run_manifest.json --out <acceptance_root>/acceptance_record.json --source-selection-manifest <acceptance_root>/source_selection_manifest.json --extraction-review-record <acceptance_root>/extraction_review_record.json --actor "USER_CONFIRMED_REVIEWER_LABEL" --rationale "Initialize acceptance for the completed Run"
   ```
   This single command verifies that the Run is complete and current, validates both post-Run evidence files, derives the immutable Run/Study identity, creates all eight Acceptance stages as `NOT_STARTED`, and initializes the sibling `acceptance_record_acceptance_events.jsonl` ledger and revision snapshots. It does not approve a scientific stage or decide the final outcome. Do not run `init-acceptance-ledger` for this record. Use only a reviewer/actor label the user has supplied or explicitly authorized; the string is provenance metadata, not identity authentication. If the operation fails, correct the reported precondition and retry only after confirming that no record or ledger was committed; never overwrite or silently replace an existing history.

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
