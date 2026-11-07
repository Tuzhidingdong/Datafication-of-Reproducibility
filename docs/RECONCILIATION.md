# Reconciliation Contract

## Purpose and boundary

The reconciliation engine identifies data-quality and evidence-consistency cases that need human review. It does not perform scientific adjudication. It never edits, merges, deletes, selects, averages, normalizes, or changes the value state of canonical records.

The engine consumes a canonical bundle after construction and produces:
- reconciliation_report.json: machine-readable issues with stable IDs, categories, severities, entity references, evidence references, and review questions;
- reconciliation_review_queue.csv: a tabular review queue suitable for manual triage.

## Review categories

### Canonical integrity errors

Broken references, malformed relationships, missing required fields, duplicate canonical IDs, and other structural errors are included as CRITICAL review issues. Repair the mapping or build specification and rebuild; do not patch a generated bundle without provenance.

### Potential duplicate entity payloads

Two entities with identical non-provenance payloads are reported as POTENTIAL_DUPLICATE_ENTITY. This does not prove that they are the same physical experiment, replicate, specimen, or source statement. Keep both records until provenance and scientific grain are reviewed.

### Endpoint definition gaps and variants

An Observation without endpoint_definition receives ENDPOINT_DEFINITION_MISSING. Multiple explicit endpoint definitions under the same experiment and target_id receive ENDPOINT_DEFINITION_VARIANTS. The latter is a warning to preserve separate endpoint cohorts, not an assertion that one endpoint is wrong. Target labels and units alone are not sufficient to establish endpoint equivalence.

### Observation value variation

Reported observations sharing experiment, target, explicit endpoint, and timepoint are compared on raw/normalized values and units.

- If values differ and the source provides the same explicit replicate_id or sample_id, report VALUE_CONFLICT_SAME_REPLICATE_OR_SAMPLE for review.
- If values differ but no replicate/sample identity is recorded, report OBSERVATION_VARIATION_GRAIN_UNRESOLVED. This may represent genuine repeats or independent replicates; it is not labelled a confirmed conflict.

The engine does not calculate a mean, choose a preferred value, or infer replicate identity.

### Evidence locator disagreements

Evidence records at the same study and exact source locator are compared on evidence type, quoted text, and extraction status. Different extractions create EVIDENCE_EXTRACTION_DISAGREEMENT; identical extraction payloads create DUPLICATE_EVIDENCE_LOCATOR. Both remain review-only. Evidence with REVIEW_REQUIRED, CONFLICTING, or UNVERIFIED status receives EVIDENCE_VERIFICATION_REQUIRED.

### Explicit ambiguous/conflicting source states

Condition and Observation records already marked AMBIGUOUS or CONFLICTING receive a review issue. The engine does not promote them to REPORTED.

### Unreferenced entities

Studies, Systems, Conditions, Experiments, or Evidence not used in selected canonical relationships are surfaced individually. An entity may legitimately be standalone or outside the current scope, so this is not an automatic exclusion.

## Stable issue identity

Each issue_id is a deterministic hash of its category, entity references, evidence references, and context. Re-running reconciliation on the same bundle produces the same IDs and ordering. A changed canonical bundle is identified by a new SHA-256 and must be reconciled again.

## Human decision file

A separate reconciliation_decisions.json records a review outcome:

- CONFIRMED_DISTINCT
- CONFIRMED_CONFLICT
- RESOLVED_WITH_EVIDENCE
- EXCLUDE_FROM_ANALYSIS
- REMAINS_UNRESOLVED

Every decision requires issue_id, reviewer, reviewed_at, and rationale. RESOLVED_WITH_EVIDENCE additionally requires one or more evidence IDs already present in the canonical bundle.

The decision file includes reconciliation_report_sha256. The report itself includes bundle_sha256. The validation command checks both exact hashes and all issue/evidence references:

    dor validate-reconciliation-decisions --decisions reconciliation_decisions.json --report reconciliation_report.json --bundle canonical_bundle.json --out decision_validation.json

Validation confirms only the structural and provenance integrity of the human review record. It does not apply a decision, change canonical records, or certify the scientific correctness of the rationale.

## CLI

    dor reconcile-bundle --input canonical_bundle.json --out-dir path/to/new/derived/run/03_reconciliation

The output directory must be new or empty. The canonical bundle is read-only. The command writes a JSON report and a CSV queue.

## Modelling boundary

A reconciliation issue is not automatically a modelling exclusion. Before model-cohort construction, the analysis plan must state which unresolved categories are excluded, retained as separate strata, or included with explicit uncertainty. Human decisions and cohort policies must be recorded separately from source observations.
