# Guided workflow and approval gates

## Operating mode

The workflow is guided. Deterministic actions inside an approved phase can run automatically, but the Supervisor must not cross a scientific decision gate without user approval.

## Gates

### G0 — Research definition

Present domain and scope, target phenomena/outcomes, source files and locations, intended prediction/interaction questions, known constraints, and exclusions.

Required user decision: approve or revise the research scope.

### G1 — Data audit and feasibility

Present file integrity and source hashes; entity/row semantics; study/system/experiment/observation relationships; data dictionary and unit semantics; feature/outcome coverage and joint coverage; missingness states; duplicates, conflicts, and likely leakage groups; candidate research questions supported by the data; unresolved issues.

Required user decision: approve the canonical representation and feasible analysis scope.

### G2 — Analysis plan

Present target definitions and analysis cohorts; inclusion/exclusion rules; features and transformations; model candidates and baselines; interaction-screening plan; validation split and metrics; uncertainty/applicability-domain plan; compute and Agent-call budget.

Required user decision: approve the analysis plan before substantial model execution.

### G3 — Candidate discoveries

Present only candidate interactions that passed predeclared support and robustness checks, with counterexamples and caveats. Recommend which findings justify mechanism investigation.

Required user decision: select findings for deeper scientific analysis.

### G4 — Validation and finalization

Present prospective validation options, if appropriate; validation status; remaining limitations; deliverables to be finalized; and unverified claims.

Required user decision: approve validation work or approve finalization with limitations retained.

## Within-phase autonomy

Once a gate is approved, the Supervisor may run approved deterministic checks and scripts without asking the user for each command. It must stop if the source schema changes, an unexpected destructive action is proposed, a critical ambiguity invalidates the approved plan, or compute scope materially increases.

## Revisions and resumption

Every run has a phase state. On resume, inspect the last completed phase, artifacts, hashes, approvals, and pending blockers. Reuse valid artifacts; do not repeat completed work without a documented invalidation reason.

A revised scientific plan should create a new plan version. Preserve previous results and decision history.

## User-facing approval packet

Every gate packet should contain a concise decision summary, evidence/artifact paths, unresolved questions, options and consequences, recommended next step, and exact actions that will occur after approval.

A gate is not approved by silence.


## Runtime approval ledger (V0.7)

The user-facing meanings of G0–G4 remain unchanged. The runtime records the user's explicit decision as a hash-bound JSONL event:

- G0 binds the research-scope decision to dataset_manifest and source_inventory.
- G1 binds mapping_plan, mapping_validation, source_inventory, and build_spec; Runtime recomputes the mapping validation and verifies inventory/plan/spec hash links.
- G2 binds canonical_bundle, canonical_validation_report, reconciliation_report, and modeling_task; Runtime verifies the reconciliation-to-bundle hash and canonical build provenance against G1.
- G3 binds interaction_report and interaction_manifest, robustness_report and robustness_manifest, and a schema 1.1 interaction_selection record. Both manifests must derive from the exact G2 task and identical cohort/split artifacts; at most one interaction may be selected per packet. A selected interaction also requires the matching mechanism_plan.
- G4 binds publication_plan and at least one reviewed scientific result artifact.

The Supervisor must present the exact artifacts, unresolved issues, proposed decision, and consequences. It must wait for an explicit user decision before running dor gate-record. It must not create APPROVE events on the user's behalf. REVISE and STOP are decisions, not failures to be silently overwritten.

Use dor gate-status before resuming. The runtime checks file hashes and upstream decision hashes; any stale artifact or changed upstream approval blocks dependent gates. The reviewer string is provenance metadata and is not independently authenticated.


## V0.8 cross-artifact approval invariants

The user-facing G0–G4 decisions are unchanged, but their approval packets are now semantically checked as linked artefacts:

- G1 binds a deterministic mapping-validation result. The G1 inventory must be the same path/hash as G0, and the plan/build-spec hashes and mapping version must agree.
- G2 binds a canonical-validation report. The reconciliation report must reference the exact bundle hash, and bundle build provenance must match the current G1-approved mapping plan, inventory, and build specification.
- G3 binds both the interaction and repeated-seed robustness report/manifest pairs. Their manifests must use the exact G2-approved task hash and the same cohort/split hashes. The schema 1.1 selection record binds both report hashes.
- Gated CLI operations are exercised through the full synthetic workflow without the legacy bypass. A revised upstream decision must invalidate existing later approvals.

Do not record an approval if any file-to-file relationship is inconsistent, even when every file individually parses and has a valid hash.


## V0.9 Run Manager and resumption

Every managed project run must begin from an explicit run plan that decomposes the complete intended workflow into stages before any expensive execution. Declare source artifacts, direct dependencies, stage inputs/outputs, executor types, and required gates. Do not let the Agent invent coarse stage boundaries during execution.

Create the independent workspace using dor run-init. Record RUNNING/SUCCEEDED/FAILED attempts with dor run-stage-record. The separate run event ledger records execution lineage; the existing workflow gate ledger remains the only source of G0-G4 scientific approval.

For Worker stages, display role/provider/model/project and the exact bounded task packet before asking for user authorization. After explicit approval, record authorization with dor run-worker-authorize, then invoke the already configured external Worker Manager. The CLI never dispatches a Worker. Workers may write only to their declared worker_staging/<stage_id>/ locations; use a separate human review/promotion stage for accepted results.

On resume, call dor run-verify, dor run-status, and dor run-resume-plan. Reuse only current stages marked REUSE. Rebuild stale upstream stages and their declared downstream dependents, while retaining independent reusable results. A RUNNING state requires inspection of the actual external process; do not assume it ended. A changed protected source means a new run, not an in-place continuation. Recovery planning never executes a stage or creates an approval.


## Run plan granularity

Define stages at the level of independent Runtime operations and artifact reuse boundaries before execution. Do not merge audit, mapping, canonical construction, reconciliation, cohort construction, baseline fitting, nested validation, interaction discovery, robustness, virtual prediction, or publication assembly into oversized stages. Stage dependencies must be explicit and derived only from actual artifact flow.

Mechanism bridge work is conditional on G3 selection. Do not guess or pre-create a mechanism plan before the interaction has been selected. When the branch cannot be represented honestly in the initial plan, end the current run at G3 and initialize a separate follow-on analysis run. Declare the approved G3 selection, exact mechanism plan, and parent-run artifacts as immutable source inputs; record the parent run_id and manifest hash in the project-level run index. V0.9 does not automate parent/child run links.

A changed protected source input produces `SOURCE_CHANGED_NEW_RUN_REQUIRED`. Do not use `REBUILD_REQUIRED` to rebase raw data inside the same Run; create a new Run for the changed source snapshot.


The first run_events.jsonl event is RUN_INITIALIZED and binds the run manifest's exact source hashes, plan hash, stage order, and workspace. Do not edit run_manifest.json or run_events.jsonl; manifest tampering is detected against the first event.
