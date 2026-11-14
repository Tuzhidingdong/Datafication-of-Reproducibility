# Scientific Discovery Engine

## Purpose

The Scientific Discovery Engine is DoR's discovery-first research entry point. It profiles the complete structured corpus locally, surfaces bounded and explicitly qualified data signals, and creates a compact evidence brief for Agent-led scientific synthesis.

It does not automatically establish scientific findings, causal mechanisms, novelty, or experiment-level relationships.

## Initial implementation

The dor discover-opportunities command:

1. Reads the Chem-Literacy aggregate JSON as the primary source.
2. Optionally reconciles the auxiliary CSV using the existing paper_id + reconciliation_id adapter contract.
3. Reuses the normalized observation adapter; it does not duplicate source parsing rules.
4. Computes feature/unit coverage, DOI-based Study support, condition-field coverage, descriptive per-Study medians, and paper/system/batch feature co-occurrence.
5. Writes aggregate tables and a bounded Agent brief. It never puts full observations or paper bodies into the brief.
6. Hashes source files before and after processing and refuses to overwrite a non-empty output directory.

## Outputs

- discovery_manifest.json — source/output hashes and read-only execution scope.
- discovery_data_profile.json — corpus-level counts and data quality context.
- feature_semantics_review_queue.csv — at most three DOI-distinct clipped evidence excerpts per feature/unit, with exact Worker source locators, for explicit human/domain mapping review.
- feature_semantics_review_summary.json — mapping-review scope, example caps, and exclusions; the queue never edits or approves feature_mapping.yaml.
- feature_support.csv — feature/unit coverage and reconciliation status counts.
- study_coverage.csv — per-Study feature support and eligible numeric medians.
- condition_support.csv — coverage of pre-existing structured measurement-condition fields.
- condition_records.csv — deterministic condition candidates from structured fields, target_system, and evidence, with observation IDs and provenance.
- condition_coverage.csv — eligible observation, paper, and DOI-Study coverage by feature, condition type, and source.
- condition_review_queue.csv — bounded queue of target_system values not matched by deterministic rules.
- condition_extraction_summary.json — extraction coverage, confidence, and explicit test-data exclusion counts.
- condition_manifest.json — rule/code versions plus input/output SHA256 hashes, including the condition-performance outputs.
- condition_performance_feature_coverage.csv — eligible numeric outcome denominators and condition-linkage coverage by feature/unit.
- condition_outcome_links.csv — observation-level links between eligible numeric outcomes and condition candidates, with stable observation IDs, deterministic condition_record_ids, and extraction provenance fields; each condition_record_id joins exactly to condition_records.csv.
- condition_performance_study_strata.csv — within-DOI aggregation (one median per feature/unit/condition level/Study), with observation counts and target-system context.
- condition_performance_strata.csv — cross-Study descriptive summaries for each condition level (Study count, median of Study medians, MAD, and IQR).
- condition_performance_contrasts.csv — pairwise descriptive differences between supported condition levels, including within-DOI paired medians, direction consistency/counterexample counts, and same-system overlap.
- condition_hypothesis_candidates.csv — bounded candidate questions that require feature mapping, domain review, and confounder assessment.
- condition_performance_analysis_summary.json — aggregate counts, thresholds, mapping state, and interpretation boundaries for the association screen.
- condition_combination_performance_study_strata.csv — DOI-level medians for pairs of condition levels that co-occur on the same observation.
- condition_combination_performance.csv — cross-Study support and descriptive numeric outcome summaries for each observed two-condition combination.
- condition_combination_contrasts.csv — descriptive differences between supported combinations, including shared-DOI counterexamples.
- condition_combination_hypothesis_candidates.csv — candidate two-condition questions requiring endpoint mapping and domain/confounder review.
- joint_support.csv — cross-feature co-occurrence support and explicit linkage warning.
- signal_catalogue.csv — qualified descriptive signals for follow-up.
- discovery_report.json — machine-readable aggregate report and limitations.
- agent_research_brief.md — bounded aggregate-only scientific reasoning input.

## Condition Extraction Engine

The discovery scan also runs a deterministic, local condition extractor. It combines:
1. Explicit structured measurement_conditions already present in normalized observations.
2. Literal patterns in target_system (cell configuration, named salts and stated molarity, percentage modifiers, material tokens, and computational/surface-test context).
3. Evidence-backed condition phrases and table cells only when a condition label is explicit. Table cell values remain linked to their row/column headers and source locator.

Every candidate retains paper_id, reconciliation_id, feature_id, batch_id, observation_id, source field, extraction rule, confidence, and provenance. Chemical abbreviations are not expanded and percentage bases are not inferred. Extracted candidates are not automatically accepted scientific facts; they remain reviewable against their source.

The exact diagnostic batches BATCH_20261106_LIMITS_PROBE and BATCH_20261106_SMOKE_NR_94908118 are retained in condition_records.csv with EXCLUDED_TEST_DATA status but excluded from scientific coverage summaries and discovery statistics. Missing DOI alone and other BATCH_REC_* identifiers do not trigger exclusion.

The review queue is capped at 2,000 rows and contains only target_system values with no deterministic match. The extractor makes no LLM calls and never modifies source files.

## Scientific interpretation boundaries

- DOI is the preferred Study key. Paper-ID fallback is recorded as unverified and is not counted toward verified cross-Study thresholds.
- Numeric summaries are separated by exact unit strings. No implicit conversion occurs.
- Descriptive per-Study medians are not inferential heterogeneity tests.
- Co-occurrence within paper/system/batch is not proof of shared experiment, sample, or replicate.
- Condition-field coverage alone does not estimate a condition effect. The added association screen links eligible numeric observations to deterministic condition candidates, aggregates observations within DOI, and compares exact feature-ID/unit strata across condition levels.
- Condition-performance contrasts are descriptive differences of Study-level medians. They are not inferential tests, p-values, confidence intervals, causal effects, or mechanism evidence. Same-DOI direction summaries mean both condition levels were represented in that DOI; they do not establish matched experiments, specimens, or replicates.
- Only DOI-identified, AGREED_MATCH numeric outcomes with exact non-empty feature IDs and unit strings enter the association screen. Paper-ID fallbacks, unresolved values, and test batches do not contribute.
- Conflicting candidate values for the same condition dimension on one observation are excluded from that dimension; unit-incompatible condition variables are kept separate. Table values requiring context review are not promoted into comparisons. Multi-component electrolyte presence is not treated as mutually exclusive; salt-specific concentration records are screened separately.
- The current zinc-battery feature_mapping.yaml remains empty/PENDING_INSPECTION. All association rows therefore carry UNMAPPED_FEATURE_SEMANTICS; no FEAT identifier is interpreted and no endpoint is labelled as capacity, lifetime, efficiency, etc. The feature_semantics_review_queue.csv provides no more than three DOI-distinct short evidence excerpts per feature/unit so a reviewer can establish meanings without giving an Agent the full 66k-observation corpus; mappings remain pending until explicitly approved.
- Candidate questions are intended to direct expert review, not to assert which condition improves performance. Different condition levels may also differ in cell design, protocol, laboratory, or other confounders.
- Two-condition combination outputs require both condition candidates to be linked to the same normalized observation. Their support and outcome distributions are joint descriptive evidence, not fitted interaction terms, synergy, or causal modification.
- No p-values, FDR correction, causal effects, or mechanism claims are generated by this scan.
- Novelty must be assessed by targeted literature review after candidate questions are formed.
- The existing zinc-battery feature_mapping.yaml remains authoritative. Unmapped FEAT identifiers must not be interpreted from their names alone.
- Condition extraction is candidate generation only: check confidence and source provenance before using extracted values for cross-paper comparisons.

## Next scientific step

The Skill reads agent_research_brief.md, discovery_report.json, and the domain profile, identifies what is and is not semantically mapped, then synthesizes a small set of testable research opportunities. It should use condition_hypothesis_candidates.csv and condition_performance_contrasts.csv to prioritize review, while withholding scientific interpretation until feature/outcome semantics and condition evidence are approved. Each opportunity is represented by schemas/research_opportunity.schema.json. The user selects a direction before a formal G0-G4 analysis run is initialized.

This exploratory scan is not a replacement for the canonical model, reconciliation, Study-held-out modelling, interaction robustness, or mechanism-evidence review.
