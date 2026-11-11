# Chem-Literacy adapter and condition recovery

## Purpose and boundary

DOR accepts the Chem-Literacy aggregate JSON (metadata plus papers[].observations[]), a flattened observation/reconciliation CSV, and an optional matching Reconciliation Ledger CSV. The adapter is deterministic Python. It does not rerun extraction, edit Chem-Literacy outputs, infer missing DOI values, resolve conflicting Worker values, or claim that every record is a physical replicate.

The aggregate observation database carries the paper-level index and nested observation records. The Reconciliation Ledger records the two Workers' values, their reconciliation status, review flags, and evidence locators.

When both are supplied, DOR joins them only by the composite key paper_id + reconciliation_id. The JSON is primary. A non-empty field disagreement is reported; it is never silently overwritten. Ledger-only rows are preserved separately and not silently attached to a different observation.

## Command

From the DOR repository root:

~~~bash
python -m dor ingest-chem-literacy \
  --database-json path/to/consolidated_zinc_battery_database.json \
  --reconciliation-csv path/to/reconciliation_ledger.csv \
  --source-root path/to/chem_literacy/preprocessed \
  --out-dir path/to/dor_workspace/runs/zinc_001/00_chem_literacy_import
~~~

If only the flattened observation CSV is available, use --database-csv instead of --database-json. Exactly one primary input is required. --reconciliation-csv is optional when the primary JSON/CSV already contains reconciliation fields.

The command refuses a non-empty output directory. It hashes inputs and any exact paper source files it reads, verifies they remain unchanged, and writes derived artifacts outside the protected source root.

## Outputs

- observations_normalized.csv: one row per imported Chem-Literacy observation. Repeated observations for the same feature/system are preserved; no deduplication or aggregation is performed.
- reconciliation_review_queue.csv: unresolved, single-worker, conflicting, tolerance-pending, or otherwise human-review records.
- numeric_target_candidates.csv: rows with AGREED_MATCH, a finite resolved_value, and a non-empty unit. These are candidate labels only, not a ready-to-train matrix.
- condition_recovery_queue.csv: feature-specific experimental-context fields missing from the structured observation.
- condition_recovery_tasks.json: bounded paper/feature-specific tasks with exact source paths, source hashes, excerpts, and result-contract references.
- data_quality_report.json, source_manifest.json, and import_report.md: aggregate counts, issues, hashes, and interpretation boundaries.

A missing DOI is not reconstructed from a paper ID. In that case, study_group_id falls back to paper_id and study_group_id_source explicitly records the fallback.

## Experimental-condition recovery: the central policy

DOR distinguishes several scientifically different situations:

1. PRESENT_IN_STRUCTURED_DATA: the imported record already carries a structured condition.
2. CANDIDATE_CONTEXT_FOUND_NOT_VERIFIED: local manuscript/SI text contains a candidate excerpt. An Agent or human must verify the value, unit, sample/system link, and source locator.
3. NOT_FOUND_IN_INITIAL_SEARCH / SOURCE_FILES_NOT_AVAILABLE: DOR has not yet found a value. This is NOT evidence that the authors did not report it.
4. NOT_REPORTED: reserved for an explicit human-reviewed decision after the relevant main text and SI have been checked.
5. AMBIGUOUS: the source contains conflicting or unassignable condition statements.

The feature-specific search profile supplies retrieval hints, not universal mandatory fields and not automatic model eligibility rules. The importance of current density, areal capacity, cycle number, temperature, reference electrode, cell configuration, and other fields depends on the exact endpoint and intended scientific question.

### Recovery sequence

1. DOR reads existing structured fields and evidence locators without changing them.
2. Python opens only the declared paper directory and exact referenced evidence files under --source-root; it does not crawl the full workspace. It searches bounded context windows using feature-specific condition hints.
3. DOR emits a task packet for missing fields. The task requests exact values, units, quotations, and page/table/figure locators, while preserving separate observations at different current densities, cycle numbers, capacities, or temperatures.
4. A Worker may inspect the declared local paper/SI files and return a proposal conforming to schemas/condition_recovery_result.schema.json. One condition_type may have multiple condition_instance_id entries: for example, four current densities remain four separate instances linked to the four exact observation IDs. Each requested condition/observation pair must be covered exactly once. The Worker must distinguish FOUND, NOT_FOUND_IN_SEARCH, AMBIGUOUS, and UNABLE_TO_VERIFY. Worker output is a proposal, not an automatic edit.
5. A human reviews the source evidence. Only then can a condition be promoted to REPORTED, marked NOT_REPORTED, or retained as AMBIGUOUS / NOT_ASSESSED in a versioned condition-decision record.

DOR can recover information that exists elsewhere in the paper/SI but was omitted by the first extraction. It cannot reconstruct information the authors never reported. It must not fill such gaps using common practice, another paper, model estimates, or assumptions about the chemistry.

## Modeling boundary

This adapter does not convert the long observation ledger into a wide feature matrix by pivoting on paper_id + target_system. The same feature/system can legitimately contain multiple measurements at different current densities, cycle numbers, capacities, or test protocols. Treating those rows as duplicates or pairing them by row order would corrupt the science.

A direct modeling task must explicitly bind the target feature and endpoint definition/unit; input features and scientific roles; observation identity or exact condition-matching key; accepted reconciliation states and evidence-quality policy; Study grouping key; and endpoint-specific eligibility/exclusions.

Only observations that can be matched to the same explicitly identified experimental context may be combined into one feature vector. If the source lacks that identity, DOR must report the ambiguity rather than invent a join. numeric_target_candidates.csv is therefore a safe label-candidate inventory, not a modeling cohort.

## Integrity note

DOR imports upstream Chem-Literacy status labels as provenance; it does not assume AGREED_MATCH proves semantic equivalence, compatible units, or correct Worker matching. The upstream data and reconciler should be independently tested for repeated measurements and unit compatibility before agreement statistics are interpreted scientifically.
