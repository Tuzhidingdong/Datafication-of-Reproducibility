# Source audit and Canonical data construction

### Stage 1 — Data audit

Read `../../../references/data-model.md` and `../../../references/guided-workflow.md`.

- Inspect CSV and JSON structure, row/system semantics, columns, nested keys, identifiers, and evidence references.
- Measure feature coverage and missingness without silently coercing or imputing values.
- Identify duplicate records, study-level dependencies, conflicting values, and possible join keys.
- Produce a data dictionary and an audit report.
- Do not finalize a domain mapping when the source schema has not been inspected.
- Present the exact adapter handoff, source inventory, and audit/package snapshot to the user. Only after explicit G0 approval, record G0 using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md` (the required source-inventory and dataset-manifest paths differ by adapter route).
- Stop at G0 until the user explicitly approves. Silence or a completed audit is not approval.

### Stage 2 — Canonical representation and analysis plan

After explicit G0 approval:

- Read [the canonical data model](../../../docs/CANONICAL_DATA_MODEL.md), [mapping contract](../../../docs/MAPPING_CONTRACT.md), and [canonical builder contract](../../../docs/CANONICAL_BUILDER.md).
- Define a mapping plan and a separate canonical build specification. The latter must explicitly declare entity grouping keys and same-source-row relationships; never assume one CSV row is one experiment.
- Run `dor validate-mapping` and `dor validate-build-spec` and inspect both reports before asking for G1 approval. Build Spec validation checks its exact mapping/inventory hashes, declared entity sources and formats, grouping selectors, mapping-rule compatibility, and relationship declarations without building or changing data. The G1 packet must include the mapping plan, both validation reports, exact source inventory, build specification, entity-grain choices, and unresolved mapping questions.
- Present the exact Mapping Plan, Mapping Validation, Source Inventory, Build Spec, and Build Spec Validation to the user. Only after explicit G1 approval, record G1 using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`.
- After G1 is approved, follow the selected route binding: STRUCTURED_DATASET runs `canonical_build`; CANONICAL_BUNDLE validates and uses the supplied bundle and must not run `build-canonical`.
- Review the build report where canonical construction applies. Validate the exact route-specific Canonical Bundle using the command and output path in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`. Resolve grouping conflicts rather than selecting or averaging records.
- Run the selected route’s `canonical_reconciliation` stage. Review endpoint-definition gaps/variants, unresolved observation variation, same-record value conflicts, evidence-locator disagreements, verification states, and unreferenced entities.
- Complete `reconciliation_decision_review` by copying `templates/reconciliation_decisions.example.json` to `<run_root>/04_reconciliation/reconciliation_decisions.json`, then recording exactly one explicit human decision for every issue in the exact report. Bind the file to the report SHA-256 and Canonical Bundle hash. Use `REMAINS_UNRESOLVED` rather than inventing a resolution when evidence is insufficient. A `CRITICAL` or `REVIEW_REQUIRED` issue may not remain unresolved at G2: stop before G2 and obtain additional evidence or record a justified explicit exclusion from the approved scope. Then run `dor validate-reconciliation-decisions --decisions <run_root>/04_reconciliation/reconciliation_decisions.json --report <run_root>/04_reconciliation/reconciliation_report.json --bundle <canonical_bundle_path_from_run_artifact_manifest> --out <run_root>/04_reconciliation/reconciliation_decision_validation.json`. Do not merge, discard, relabel, or select conflicting source values automatically; the validation report must be valid before G2.
- Keep study, system, condition, experiment, observation, comparison, and evidence entities distinct.
- Define outcome-specific cohorts; do not force all targets into one complete-case table.
- Quantify joint coverage for each proposed variable pair and target.
- Select the formal scope using the exact Discovery report. Copy `templates/research_scope_record.example.json` to `<run_root>/05_scope/research_scope_record.json`; classify every reported `signal_id` exactly once as selected or not selected, bind the exact Discovery report SHA-256, and record the scope rationale, limitations, reviewer, timestamp, and task/target identity.
- Propose endpoint-specific prediction tasks based on actual data support. Each task must specify an exact target_id and endpoint_definition, outcome field and unit, explicit feature bindings to canonical condition_type values, eligibility rules, and a study-level split design. Do not map feature names automatically.
- Write and validate the exact `modeling_task.json` before G2; it is an approval artifact, not something to create after approval. Run `dor validate-research-scope --scope <run_root>/05_scope/research_scope_record.json --discovery-report <run_root>/04_discovery/discovery_report.json --task <run_root>/05_scope/modeling_task.json`. G2 independently recomputes this validation against the exact bound files. An empty selected-signal list or incomplete/overlapping signal classification blocks G2.
- Present candidate model families, validation splits, assumptions, exclusion rules, and compute costs.
- After reconciliation-decision validation, Discovery, scope selection, and task preparation, ask the user to approve the exact Canonical Bundle, canonical validation, reconciliation report and decisions, selected scope, and modeling task at G2. Record G2 only after explicit approval using the route-specific command in `docs/RUN_PLAN_EXECUTION_BINDINGS.md`; the Gate validator independently recomputes decision validity against the bound decision/report/bundle files.
- Do not create a modelling cohort or fit a model before G2 approval.
