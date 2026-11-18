# Scientific Discovery Engine

## Purpose

The Scientific Discovery Engine is a deterministic Runtime capability, not an Agent prompt. Its job is to use the complete, validated Canonical Bundle to find data-supported research opportunities before a narrow endpoint-specific Cohort or Modeling Task is chosen.

It performs full-bundle profiling, Study-aware condition/outcome screening, multiple-testing correction, evidence-ledger construction, and deterministic candidate-question generation. The Agent may challenge the interpretation and help the user review domain meaning, but it must not replace the Runtime calculations, invent candidate evidence, or silently promote candidates to accepted findings.

## Input and protection contract

The preferred input is a Canonical Bundle produced by the reviewed mapping/build workflow or supplied by a validated external adapter package.

    dor discover-opportunities --bundle path/to/canonical_bundle.json --out-dir path/to/new/discovery_run

For a bundle registered by an adapter handoff:

    dor discover-opportunities --adapter-handoff path/to/adapter_handoff.json --out-dir path/to/new/discovery_run

The command validates canonical structure and references, hashes the bundle before and after analysis, reads only the declared Canonical Bundle entities and links, and refuses to overwrite a non-empty output directory. Source data are read-only.

Deep-screen support and candidate-search bounds are explicit CLI controls:
- `--minimum-deep-experiments-per-system`: repeated Experiments required within a Study/System (default 8).
- `--minimum-deep-triplet-experiments-per-system`: repeated Experiments required within a Study/System for three-way screens (default 12).
- `--minimum-deep-between-systems-per-study`: eligible Systems required for between-System nonlinear and two-way screens (default 8); three-way screens require at least 12.
- `--maximum-deep-condition-pairs`, `--maximum-deep-condition-triplets`, and `--maximum-deep-multiobjective-pairs`: per-outcome candidate caps.
- `--minimum-deep-model-improvement`: minimum relative leave-one-out RMSE gain for the positive-gain label; lower-gain candidates remain as counterevidence.

The discovery scan is independent of a selected Modeling Task or Cohort. It must run over the entire supplied Canonical Bundle, not a previously narrowed modeling cohort. A later task-specific Cohort is created only after the user selects a research opportunity and approves the resulting analysis scope.

The Engine does not merge Systems or rewrite Experiment/System relationships to make an analysis eligible. The reviewed Build Spec remains the authority for entity grain. If a bundle contains one Experiment per System, the Engine can still screen cross-sectional associations between Systems within the same Study, while retaining separate within-System analyses for Systems that genuinely contain repeated condition levels. Whether two source records belong to one canonical System remains a mapping decision supported by source evidence, not a statistical convenience.

Original papers, SI, images, and other raw research documents are never opened or parsed by this engine. Source locators remain opaque provenance references.

## Full-dataset profile

The engine reports Study, System, Condition, Experiment, Observation, and target coverage from the complete bundle. It preserves distinct counts, including Studies without any Observation records, instead of treating Observation rows as independent Studies. Reported numeric support is separated by exact target ID, endpoint definition, timepoint, and unit string.

Target IDs, endpoint definitions, and condition labels remain canonical identifiers. The Runtime does not infer a physical meaning from an identifier or guess unit conversions. The optional `semantic_metadata` object on target Observations and Condition records can carry a reviewed concept ID, definition, measurement basis, measurement context (for example, distinct measurement stages or contexts), derivation type/inputs, review status, reviewer and review date. Metadata is used only when consistently present for all records of that canonical attribute and marked `APPROVED`. Same-concept metadata is excluded as a structural self-relation only when both sides also declare the same non-empty `measurement_context`; if the context is missing or different, the candidate is retained and explicitly marked for domain review. A declared dependency is excluded only when its metadata says `derivation_type=CALCULATED` and lists the other attribute in `derived_from`. Missing, partial, conflicting or unapproved metadata never triggers semantic exclusion. When no approved metadata is present, opportunities retain CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW.

## Candidate-value evidence and sensitivity mining

The Canonical Bundle may preserve multiple extraction-source entries on the same Condition or Observation through its optional `value_candidates` array. Each entry has its own candidate ID and stable source ID. It can carry a raw or normalized value/unit, supplied quote, opaque source locators, and scalar source metadata such as extraction review state, review reason, evidence-file reference, or table/page pointer. An entry can also represent an extraction slot for which no value was returned: a blank value is retained with its source-field locator instead of being discarded.

For existing CSV/JSON input, the hash-bound Build Spec supports explicit `value_candidate_bindings`. Each binding selects one candidate source and maps its value field plus optional unit, quote, and metadata fields from the same source file/selected record. This attaches the extraction alternatives to their original canonical Condition/Observation; it does not create new scientific records or ask the user to prepare another table. The binding's source fields must already exist in the source inventory. No semantic meaning is guessed from column names.

This is a parallel evidence path, not a replacement for the primary reported-value path:

- The existing primary scientific screens continue to use only the parent record's `value_state=REPORTED` and its reported value/unit pair. Candidate alternatives do not silently enter the primary estimates, p-values, q-values, or FDR denominators.
- `candidate_value_inventory.csv` retains every candidate entry attached to its original Observation or Condition, including candidate source, value/unit, quote, source metadata, locator, and Study/System/Experiment context.
- `candidate_value_reconciliation.csv` distinguishes value/unit agreement from value conflicts, unit conflicts, value-and-unit conflicts, and records with no usable candidate value. It never averages candidates or chooses a preferred extractor.
- `missingness_opportunity_profile.csv` profiles record states, candidate-entry coverage, extracted-value and numeric-value coverage, unit availability, populated quote/metadata/locator coverage, and Study/System/Experiment support by canonical feature. Missingness is information about extraction and reporting, not silently treated as scientific absence.
- `candidate_sensitivity_opportunities.json` runs one isolated alternative scenario per candidate source on a copy of the bundle. A unique candidate value overlays the same parent record; records without a candidate from that source, with an empty candidate slot, or with unresolved same-source conflicts retain their original primary reported values when available. Conflicts and unusable candidate slots are counted rather than silently resolved.
- `candidate_sensitivity_profile.json` reports each scenario's candidate overlay, primary-value fallback, conflict and unusable-slot counts, plus scenario-specific support and screening results.

Candidate-source scenarios are explicitly labelled `CANDIDATE_SOURCE_SENSITIVITY_ONLY_NOT_PRIMARY`. Their inferential results are calculated within each scenario and are not pooled across candidate sources or combined with the primary FDR family. Candidate alternatives never become extra Observations, replicates, Systems, or independent Studies. A high degree of extraction agreement is not proof that a value is source-accurate, scientifically valid, or semantically comparable. Candidate values with missing units remain in the inventory and reconciliation but cannot enter numeric outcome screens that require an explicit unit. A candidate source with no usable value for a record does not erase an existing primary result in that sensitivity scenario.

This design lets DoR exploit existing incomplete and conflicting structured evidence without asking the user to turn it into a complete machine-learning table first. It does not permit the Runtime to open original papers/SI or dereference source locators.

### Pairwise candidate conflict diagnostics

A separate pairwise reconciliation layer compares candidate entries only when they are attached to the same Canonical Observation or Condition. It does not compare arbitrary rows across different parents and does not create additional experimental records.

The diagnostic distinguishes:

- exact numeric equality using finite `Decimal` values (so numerically equal representations such as `1` and `1.0` are not treated as a numeric disagreement);
- numeric difference under an identical exact unit label;
- units that can be compared through an explicitly approved Semantic Registry v1.1 same-dimension affine conversion;
- unresolved unit-label equivalence, incompatible approved dimensions, and missing/unspecified units;
- non-numeric exact-text matches versus unresolved non-numeric differences.

The unit conversion is used only to show a diagnostic canonical comparison value. Original candidate values, original unit strings, quotes, source metadata, and locators remain in the pairwise report. No rounding tolerance, implicit unit parsing, fuzzy alias resolution, or automatic selection is applied. The primary reported-value path and the candidate-source sensitivity overlays remain unchanged.

The parent Target/Condition semantic definition is also not enough to certify candidate quote equivalence. The output explicitly marks candidate quote scope as unverified because a candidate may refer to another endpoint definition, measurement basis, test stage, protocol, sample, or timepoint even when it is attached to the same canonical parent. A reviewed semantic registry can clarify the parent attribute but cannot retroactively validate every source quotation.

`candidate_pairwise_reconciliation.csv` contains the provenance-bearing pairwise details. `candidate_reconciliation_profile.json` contains bounded status counts and is the only new reconciliation artifact exposed to Scope Review; raw pairwise rows and candidate quotations are not injected into the Scope Agent context. These counts are comparisons, not independent Observations or Studies.

## Pairwise candidate conflict diagnostics

Candidate inventory and source-specific sensitivity are complemented by a separate pairwise diagnostic layer. It compares candidate pairs only when they are attached to the same Canonical Observation or Condition, and labels whether the pair comes from the same extractor source or different sources. It does not compare candidates from unrelated parent records.

The layer reports value comparison, unit comparability, and parent-attribute semantic review as separate dimensions:
- Numeric strings and numeric scalars are compared with exact decimal arithmetic. Values such as `1` and `1.0` are numerically equal; no rounding, tolerance, locale-specific thousands/decimal parsing, or imputation is applied.
- Equal unit labels are compared as supplied. Different labels are only converted when both exact symbols are covered by approved, hash-bound unit definitions in Semantic Registry v1.1 and declare the same dimension. Different approved dimensions are reported as incompatible. Missing definitions or unknown labels remain unresolved.
- Approved unit conversions are diagnostics only. They never alter primary values or the independently generated candidate-source sensitivity scenarios.
- Parent semantic metadata can show that a canonical attribute has an approved definition, but it cannot prove that two candidate quotations refer to the same measurement stage, endpoint, sample, protocol, or context. Candidate quote scope is therefore explicitly left unverified by this layer.

The row-level `candidate_pairwise_reconciliation.csv` retains both candidates' IDs, source IDs, raw/normalized value-unit pair, quotes, source metadata, opaque locators, pair relationship, comparison statuses, and any diagnostic canonical values. Keep this file out of Scope Agent context. `candidate_reconciliation_profile.json` contains only aggregate status counts and the approved unit-registry summary; this aggregate may be provided to scope review.

No pair is automatically accepted, rejected, averaged, corrected, or promoted. The existing candidate reconciliation, primary Discovery, FDR families, and source-specific sensitivity behavior remain separate and unchanged.

## Study-aware statistical screens

### Shared aggregation rules

1. Only observations with value_state=REPORTED, a finite numeric value, and an explicit unit enter numeric outcome screens.
2. A complete normalized value/unit pair is used together; otherwise the raw value/unit pair is retained. No half-normalized value/unit mixtures are created.
3. Outcome groups remain separate by target ID, endpoint definition, timepoint, and exact unit.
4. Multiple Observation rows in one Experiment are reduced to an Experiment median before statistical screening.
5. Condition assignments are linked through the Experiment's declared condition_ids. When one Experiment has conflicting values for the same condition type/unit, that assignment is excluded rather than guessed.
6. Comparisons are stratified by the same Study and canonical System. A Study contributes at most one effect value to a cross-Study test, regardless of how many Observations, Experiments, or Systems it contains.

### Categorical and two-level conditions

For each exact condition type/unit and pair of levels, the engine identifies Studies and Systems that contain both levels. It calculates a median outcome for each level within each shared System, a paired difference for that System, then a median of paired System differences for that Study.

The inferential input is therefore one Study-level difference per independent Study. A System without both levels does not contribute to that contrast. The result retains the per-Study values, counts, System IDs, Experiment IDs, and Observation IDs.

### Numeric conditions

When a condition type/unit has at least three distinct numeric levels across the dataset, it is treated as a quantitative exposure rather than expanded into many arbitrary cut-point pairs.

Two distinct screens are retained:

- **Within-System trend:** Spearman is calculated across Experiment-level condition/outcome pairs inside the same Study/System. A System needs at least four eligible Experiments and three distinct condition values. Multiple System correlations are reduced to one median rho per Study.
- **Between-System, within-Study trend:** when each eligible System contributes only one condition level for that outcome/condition, the engine calculates Spearman across System-level medians inside a Study. At least four distinct Systems and three distinct exposure/outcome values are required. A System with multiple condition levels is excluded from this cross-sectional screen and remains eligible for the within-System screen.

Each Study contributes at most one rho to each analysis family. The between-System result is explicitly cross-sectional: composition, cell design, protocol, and other system-level differences can confound the association. It is not a substitute for a controlled within-System comparison. For numeric between-System trends, the Runtime also screens other structured numeric Condition variables on the same Study/System cohort and flags exact monotonic co-variation as a potential co-exposure/non-identifiability issue. It records complete, incomplete/ambiguous and rank-screen-eligible Study coverage for each recorded covariate, so insufficient data are not silently reported as absence of confounding. This is an unadjusted diagnostic, not a covariate-adjusted model or proof of confounding. Unstructured System descriptions, composition, protocol, laboratory, batch and unmeasured variables remain explicit review risks.

### Categorical conditions across Systems

When condition levels occur on distinct Systems rather than repeatedly inside one System, the engine also performs a separate between-System screen. Within each Study, a System is eligible only if it carries exactly one level for that condition/outcome group. Each level must be represented by at least two distinct Systems. The engine compares the median Experiment/System outcome between levels and retains the System, Experiment, and Observation evidence for both groups. Each Study contributes one between-System difference.

This is an unpaired cross-sectional contrast, not a paired experiment. Material composition, electrode design, electrolyte formulation, protocol, and other System-level differences may confound it. Such candidates are labelled separately from within-System paired contrasts and require stronger domain review.

Nominal string values are not assigned an invented ordinal order. Their signed `level_b - level_a` contrast uses deterministic serialized-label order, explicitly recorded as `SERIALIZED_LABEL_ORDER`. Numeric values use ascending numeric order. A sign is therefore interpretable only together with the recorded orientation and labels.

### Inference and multiplicity

- Exact reciprocal between-System numeric hypotheses are deduplicated before BH-FDR only when both rows have reciprocal canonical target/condition identifiers, cross-matching exact unit strings, identical Study/System/Experiment support, and every System-level condition/outcome value is the exact reverse of its counterpart. The original correlation rows remain in the diagnostic catalogue, with the duplicate explicitly linked to its representative; the duplicate receives no separate q-value and does not enter the BH denominator. A perfect or high Spearman coefficient alone never triggers this merge.
- Each analysis family uses a two-sided exact sign test across independent Study-level effects.
- Within-System paired contrasts, between-System categorical contrasts, within-System numeric trends, and between-System numeric trends are separate multiple-testing families.
- Benjamini-Hochberg q-values are calculated within each family.
- The default q-value screen threshold is 0.10. A screen-positive candidate is a prioritization signal, not proof of a scientific effect.
- Percentile confidence intervals are generated by deterministic bootstrap resampling of Study-level effects. The seed and iteration count are recorded.
- All observed condition levels are written to condition_level_support.csv. To prevent combinatorial explosion, categorical pairwise screens use at most the configured maximum levels per target/endpoint/condition, prioritizing levels with the most independent Study support and breaking ties lexically. Omitted levels remain visible in the support table and are counted in the analysis profile.
- If fewer than the configured minimum number of independent Studies contribute, the inferential test and q-value remain null. The output may still preserve a descriptive candidate with an explicit insufficient-support status.

Defaults are configurable:

    dor discover-opportunities --bundle <canonical_bundle.json> --out-dir <new_directory> --minimum-paired-studies 3 --fdr-alpha 0.10 --bootstrap-iterations 1000 --maximum-opportunities 500 --maximum-levels-per-condition 20 --seed 42

## DOR-generated research opportunities

Each opportunity contains a deterministic ID, a question written from the observed canonical variables, the analysis family, effect estimate, Study-level confidence interval, p-value, q-value, screen status, independent Study count, a structured semantic-review status, a structured confounding-review record, limitations, proposed validation, and direct references to the supporting Study/System/Experiment/Observation records. The confounding review reports exact monotonic co-variation among recorded numeric Conditions when measurable and names important unassessed domains. It does not claim that unmeasured confounding has been ruled out.

The question is deliberately phrased in terms of the declared canonical identifiers. It does not rename a target as capacity, lifetime, efficiency, or another scientific concept unless an approved semantic definition exists outside this scan.

A screen-positive result is labelled FDR_SCREEN_POSITIVE_REQUIRES_DOMAIN_REVIEW. A candidate with insufficient independent Study support is labelled DESCRIPTIVE_CANDIDATE_INSUFFICIENT_INDEPENDENT_STUDY_SUPPORT. Neither status is an accepted scientific finding.


## Deep full-bundle scientific screens

The primary Study-aware screens above remain unchanged. The same Discovery pass also runs a separate, deterministic deep-screen layer over the **complete Canonical Bundle**. This is not a Cohort/modeling-task screen and it does not require a globally complete feature table.

### Pairwise-available response subsets

For each exact outcome key (target ID, endpoint definition, timepoint, and unit), the Runtime links experiment-level outcome medians to each explicitly reported numeric Condition through the Experiment's declared \`condition_ids\`. Every outcome/Condition hypothesis uses only the Experiments where that particular pair is available. A conflicting assignment for one Condition type/unit inside an Experiment is excluded for that feature; other features and that Experiment's other usable outcomes remain eligible.

### Nonlinear and threshold response

Two complementary designs are evaluated separately:
- **Within-System repeated-experiment design:** at least eight pairwise-available Experiments and five distinct exposure levels within a Study/System; leave-one-Experiment-out RMSE.
- **Between-System cross-sectional design:** at least eight eligible Systems within one Study, each with one constant numeric exposure level for that outcome/feature, and at least five distinct System exposure levels; leave-one-System-out RMSE over one median outcome per System.

For both designs the Runtime compares a linear response against a quadratic response and against a continuous one-breakpoint piecewise-linear response. The threshold model chooses its breakpoint from training data within each fold; its reported breakpoint summary is descriptive and is not asserted to be a universal physical threshold. Each eligible System contributes a relative RMSE improvement; multiple System effects within a Study are reduced to one median Study effect. Study—not the Experiment or System—is the independent inferential unit. The two designs use separate analysis families, each with its own exact two-sided Study sign test, deterministic Study bootstrap interval, and BH-FDR family. Cross-sectional between-System results may be confounded by System composition, protocol, source, or other Study-level differences and are explicitly labelled for domain review.

The output retains systems/Studies where the more complex model does not improve prediction. \`BELOW_MINIMUM_PREDICTIVE_GAIN_RETAINED_FOR_COUNTEREVIDENCE\` means the median Study improvement did not reach the configured minimum gain; it is not silently removed from the results or FDR catalogue.

### Two-way and three-way condition interactions

Numeric Condition combinations are screened only where the corresponding two/three Conditions and outcome are jointly available. The two-way model compares additive main effects against main effects plus the product term. The three-way model compares all main effects plus all pairwise product terms against that lower-order model plus the three-way product term.

Both designs are run separately. Within-System repeated-experiment screens use leave-one-Experiment-out RMSE (at least eight Experiments per Study/System for two-way and twelve for three-way). Between-System cross-sectional screens require each selected feature to be constant within a System, then use one median outcome and one condition vector per System with leave-one-System-out RMSE (at least eight Systems per Study for nonlinear/two-way and twelve for three-way by default; the nonlinear/two-way threshold is configurable with `--minimum-deep-between-systems-per-study`). Each Study contributes one median System effect to cross-Study inference. All features require at least three distinct values. The Runtime ranks hypotheses by joint Experiment and Study support and applies explicit per-outcome caps (100 two-way pairs and 40 three-way triplets by default). The best-covered 18 numeric Condition features per outcome bound both pairwise and triplet combinatorics; features outside this bounded set remain visible in the omission count and remain eligible for their separate one-feature nonlinear screen. Screened and omitted hypothesis counts are reported; an omitted combination is not described as a negative result. The candidate limits and support thresholds are configurable through the \`discover-opportunities\` CLI.

These are predictive model-comparison signals, not causal interaction effects, synergy estimates, mechanisms, or proof of generalization to new Systems. Per-Study support, model improvements, and counterexample Studies remain in the opportunity record and evidence ledger.

### Multi-objective co-variation and Pareto frontiers

The Runtime identifies distinct numeric outcome pairs co-recorded in the same Experiment. It separately calculates (1) within-System Spearman co-variation over pairwise-available repeated Experiments and (2) between-System Spearman co-variation within a Study using one median pair of outcomes per System. A Study contributes one median System correlation to each analysis design. Outcome keys retain exact target, endpoint, timepoint, and unit; no unit conversion or cross-endpoint collapsing is inferred.

For every screened pair, Pareto membership is calculated separately for each available within-System Experiment population and between-System population within a Study, under all four direction scenarios: \`MAX_MAX\`, \`MAX_MIN\`, \`MIN_MAX\`, and \`MIN_MIN\`. The Runtime **does not infer whether an outcome should be maximized or minimized**. These frontiers are descriptive candidate operating envelopes, not a recommendation or an optimized experimental recipe. The user must select the intended objective direction and domain meaning before interpreting a frontier.

Multi-objective pairs have their own Study-level sign tests, bootstrap intervals, and BH-FDR family. The aggregate effect direction is labelled positive or negative from the median Study effect; counterexample Study IDs are those whose effect points in the opposite direction, not simply all negative effects. Within a Study, Systems are reduced to one median effect before this comparison. The scope record may select a multi-objective opportunity for a single-target Modeling Task only when that task's target is one of the two declared objective targets; this binds the subsequent analysis to an explicit objective rather than pretending that the pair is one outcome.

### Candidate-source deep sensitivity

The same nonlinear, two-way, three-way, and multi-objective screens run inside each existing candidate-source sensitivity copy. Each source remains isolated; unique candidate values overlay their original parent records, while absent, empty, or conflicting source values follow the existing primary-value fallback/skip rules. The resulting deep reports are nested under that source in \`candidate_sensitivity_opportunities.json\` and marked \`CANDIDATE_SOURCE_SENSITIVITY_ONLY_NOT_PRIMARY\`. Candidate alternatives never create new Observations, Experiments, Systems, or independent Studies, and their p/q values are not pooled with primary results or other source scenarios. The aggregate candidate sensitivity profile exposes only bounded counts/profile fields.

Deep opportunity IDs are exposed through \`discovery_report.json\` as \`deep_discovery_signals\`, bound by the exact report hash and the SHA-256 of \`deep_research_opportunities.json\`. Nonlinear and interaction opportunities declare one \`target_id\`; a multi-objective opportunity declares both \`target_ids\`. The existing Research Scope validator requires a selected Modeling Task target to match the declared target (or one of the two multi-objective targets).

All deep outputs retain canonical Study/System/Experiment/Observation identifiers. They do not dereference source locators, read quotes from raw files, inspect papers/SI, infer semantic meaning, or certify causality. Exact unit strings, endpoint definitions, timepoints, and canonical entity relationships remain authoritative.

## Outputs

- discovery_manifest.json — input/output SHA-256 values, read-only scope, and engine configuration.
- discovery_data_profile.json — full Canonical Bundle entity and numeric target counts.
- target_support.csv — observation and Study support plus descriptive numeric summaries by target/endpoint/timepoint/unit.
- study_coverage.csv — per-Study numeric target summaries.
- condition_support.csv — coverage of explicitly linked, reported Conditions.
- condition_level_support.csv — all observed condition levels and their Study/System/Experiment support, including levels omitted from bounded pairwise screening.
- joint_support.csv — target pairs co-recorded within one canonical Experiment; co-observation is not an interaction.
- condition_outcome_contrasts.csv — within-System paired contrasts and between-System cross-sectional categorical contrasts, separately labelled with their Study-level tests.
- condition_outcome_correlations.csv — within-System and between-System within-Study numeric-condition Spearman screens and cross-Study direction-consistency tests.
- research_opportunities.json — DOR-generated, ranked, structured candidate research questions, explicit self-association exclusions, and proof records for exact mirror duplicates.
- evidence_ledger.jsonl — one record per opportunity/Study with supporting System, Experiment, and Observation IDs.
- scientific_analysis_profile.json — primary-screen algorithm versions, thresholds, test-family descriptions, and limitations.
- deep_research_opportunities.json — nonlinear response, threshold, two-way and three-way interaction, and multi-objective candidate opportunities with Study-level effects, intervals, p/q values, counterexamples, and supporting identifiers.
- deep_scientific_discovery_profile.json — deep-screen algorithms, support thresholds, candidate caps, and omissions.
- deep_condition_response.csv — nonlinear/threshold model comparisons and evidence support.
- deep_interaction_candidates.csv — two-way and three-way model comparisons and evidence support.
- multiobjective_tradeoff_candidates.csv — Study-aware outcome-pair co-variation candidates.
- multiobjective_frontiers.csv — within-System Experiment-level and between-System System-level frontier membership under all four objective-direction scenarios.
- deep_evidence_ledger.jsonl — one record per deep opportunity/Study with System, Experiment, Observation support.
- signal_catalogue.csv and discovery_report.json — aggregate signal catalogue and machine-readable summary.
- candidate_value_inventory.csv — source-specific candidate values, quotes, units, and opaque locators attached to their original Condition/Observation records.
- candidate_value_reconciliation.csv — per-record agreement/conflict status without silent selection or averaging.
- candidate_pairwise_reconciliation.csv — per-parent pairwise candidate comparison retaining both source evidence chains, diagnostic numeric/unit comparison, and unresolved quote-scope status.
- candidate_reconciliation_profile.json — bounded aggregate pairwise status counts and approved unit-registry coverage; only this aggregate profile is exposed to Scope Review.
- candidate_pairwise_reconciliation.csv — row-level pairwise candidate comparison with both provenance chains and diagnostic-only approved unit conversions.
- candidate_reconciliation_profile.json — aggregate pairwise value/unit/semantic-status counts; safe for bounded scope-review context.
- missingness_opportunity_profile.csv — feature/state-specific record and evidence-coverage profile.
- candidate_sensitivity_opportunities.json — separately labelled source-specific sensitivity results; never merged into primary findings.
- candidate_sensitivity_profile.json — bounded aggregate summary of candidate-source overlay coverage and sensitivity results.
- agent_research_brief.md — bounded aggregate summary with DOR-generated candidates; it contains no raw Observation rows, candidate quotes, full papers, or source-document text.

## Research scope and downstream workflow

The user selects or rejects generated primary or deep opportunity IDs. Primary signals remain in `signals`; deep opportunities are exposed in `deep_discovery_signals`. Both are bound to the exact Discovery report hash, and the report also records the SHA-256 of `deep_research_opportunities.json`. The scope validator checks that a selected single-target opportunity matches the Modeling Task target ID. A multi-objective selection is valid only when the task target is one of that opportunity's two declared objective targets.

Only after that human selection and scope review should the formal Run create the endpoint-specific Cohort and Modeling Task, then continue through G0-G4, validation, and publication. The original full-bundle Discovery output remains immutable and is not replaced by a narrow Cohort.

## Interpretation boundaries

- This is observational screening, not causal inference or mechanism discovery.
- Statistical significance is not generated from flattened Observation counts; Study is the independent unit for cross-Study tests.
- Within-System comparisons control the canonical System identity but do not remove all protocol/time effects. Between-System within-Study screens control Study-level context only; differences in material composition, system design, and protocol may still confound them.
- Study bootstrap intervals do not account for every upstream extraction, mapping, and measurement uncertainty.
- The significance screen does not establish endpoint comparability, physical meaning, novelty, or publication-worthiness.
- No implicit unit conversion, timepoint merging, arbitrary numeric binning, missing-value imputation, or conflicting-condition resolution is performed.
- Canonical Study/System/Experiment relationships depend on the quality of the reviewed mapping or adapter input.

The purpose is to let DOR establish, from its complete structured database, what relationships are actually represented, how independently they are supported, where the evidence is weak, and which concrete research questions deserve the user's attention.
