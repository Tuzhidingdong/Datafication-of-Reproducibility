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

The discovery scan is independent of a selected Modeling Task or Cohort. It must run over the entire supplied Canonical Bundle, not a previously narrowed modeling cohort. A later task-specific Cohort is created only after the user selects a research opportunity and approves the resulting analysis scope.

The Engine does not merge Systems or rewrite Experiment/System relationships to make an analysis eligible. The reviewed Build Spec remains the authority for entity grain. If a bundle contains one Experiment per System, the Engine can still screen cross-sectional associations between Systems within the same Study, while retaining separate within-System analyses for Systems that genuinely contain repeated condition levels. Whether two source records belong to one canonical System remains a mapping decision supported by source evidence, not a statistical convenience.

Original papers, SI, images, and other raw research documents are never opened or parsed by this engine. Source locators remain opaque provenance references.

## Full-dataset profile

The engine reports Study, System, Condition, Experiment, Observation, and target coverage from the complete bundle. It preserves distinct counts, including Studies without any Observation records, instead of treating Observation rows as independent Studies. Reported numeric support is separated by exact target ID, endpoint definition, timepoint, and unit string.

Target IDs, endpoint definitions, and condition labels remain canonical identifiers. The Runtime does not infer a physical meaning from an identifier or guess unit conversions. The optional `semantic_metadata` object on target Observations and Condition records can carry a reviewed concept ID, definition, measurement basis, measurement context (for example, distinct measurement stages or contexts), derivation type/inputs, review status, reviewer and review date. Metadata is used only when consistently present for all records of that canonical attribute and marked `APPROVED`. Same-concept metadata is excluded as a structural self-relation only when both sides also declare the same non-empty `measurement_context`; if the context is missing or different, the candidate is retained and explicitly marked for domain review. A declared dependency is excluded only when its metadata says `derivation_type=CALCULATED` and lists the other attribute in `derived_from`. Missing, partial, conflicting or unapproved metadata never triggers semantic exclusion. When no approved metadata is present, opportunities retain CANONICAL_IDENTIFIERS_ONLY_REQUIRES_DOMAIN_SEMANTIC_REVIEW.

## Candidate-value evidence and sensitivity mining

The Canonical Bundle may preserve multiple extraction alternatives on the same Condition or Observation through its optional `value_candidates` array. Each candidate is separately identified by candidate ID and candidate-source ID and may carry its own raw/normalized value and unit, a short supplied quotation, opaque source locators, and scalar source-extraction metadata (for example review states and reasons). A candidate slot with no numeric value is still retained when its source locator or other provenance is present; it contributes to coverage/missingness analysis but is excluded from numeric sensitivity overlays.

This is a parallel evidence path, not a replacement for the primary reported-value path:

- The existing primary scientific screens continue to use only the parent record's `value_state=REPORTED` and its complete value/unit pair. Candidate alternatives do not silently enter the primary estimates, p-values, q-values, or FDR denominators.
- `candidate_value_inventory.csv` keeps every supplied candidate attached to its original Observation or Condition, with Study/System/Experiment context, quoted excerpt, and source locators.
- `candidate_value_reconciliation.csv` distinguishes exact value/unit agreement from value conflicts, unit conflicts, and records without a usable numeric candidate. It also retains the candidate sources and the metadata keys/values supplied by those extraction sources. It never averages candidates or chooses a preferred extractor.
- `missingness_opportunity_profile.csv` profiles record states, candidate coverage, value/unit availability, quotes, and locator coverage by canonical feature. Missingness is reported as data about the corpus, not silently treated as scientific absence.
- `candidate_sensitivity_opportunities.json` runs one isolated alternative scenario per candidate source. Only one source's candidates are overlaid into a copy of the bundle at a time; same-source conflicts on one parent record are retained in the inventory and excluded from that scenario.
- `candidate_sensitivity_profile.json` reports overlay coverage and scenario-specific support and screening results.

Candidate-source scenarios are explicitly labelled `CANDIDATE_SOURCE_SENSITIVITY_ONLY_NOT_PRIMARY`. Their p/q values are calculated within each scenario and are not pooled across candidate sources or combined with the primary FDR family. Candidate alternatives never become extra Observations, replicates, Systems, or independent Studies. Conflicting alternatives from one source on the same parent record are reported and skipped; missing-value candidates are counted separately from value conflicts. A high degree of extraction agreement is not proof that a value is source-accurate, scientifically valid, or semantically comparable. Candidate values with missing units remain available for inventory and reconciliation but cannot enter numeric screens that require an explicit unit.

This design lets DoR exploit existing incomplete and conflicting structured evidence without asking the user to first turn it into a complete machine-learning table. It does not permit the Runtime to open original papers/SI or dereference source locators.

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
- scientific_analysis_profile.json — algorithm versions, thresholds, test-family descriptions, and limitations.
- signal_catalogue.csv and discovery_report.json — aggregate signal catalogue and machine-readable summary.
- candidate_value_inventory.csv — source-specific candidate values, quotes, units, and opaque locators attached to their original Condition/Observation records.
- candidate_value_reconciliation.csv — per-record agreement/conflict status without silent selection or averaging.
- missingness_opportunity_profile.csv — feature/state-specific record and evidence-coverage profile.
- candidate_sensitivity_opportunities.json — separately labelled source-specific sensitivity results; never merged into primary findings.
- candidate_sensitivity_profile.json — bounded aggregate summary of candidate-source overlay coverage and sensitivity results.
- agent_research_brief.md — bounded aggregate summary with DOR-generated candidates; it contains no raw Observation rows, candidate quotes, full papers, or source-document text.

## Research scope and downstream workflow

The user selects or rejects the generated opportunity IDs. An opportunity is also exposed as a Discovery signal, so the existing research_scope_record.selected_signal_ids contract can bind it to the exact Discovery report hash. The scope validator checks that a selected opportunity's target ID matches the Modeling Task target ID.

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
