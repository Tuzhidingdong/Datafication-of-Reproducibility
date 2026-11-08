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
- G1 binds approved mapping_plan, source_inventory, and build_spec.
- G2 binds canonical_bundle, reconciliation_report, and modeling_task.
- G3 binds interaction_report and a complete interaction_selection record; at most one interaction may be selected per packet. A selected interaction also requires the matching mechanism_plan.
- G4 binds publication_plan and at least one reviewed scientific result artifact.

The Supervisor must present the exact artifacts, unresolved issues, proposed decision, and consequences. It must wait for an explicit user decision before running dor gate-record. It must not create APPROVE events on the user's behalf. REVISE and STOP are decisions, not failures to be silently overwritten.

Use dor gate-status before resuming. The runtime checks file hashes and upstream decision hashes; any stale artifact or changed upstream approval blocks dependent gates. The reviewer string is provenance metadata and is not independently authenticated.
