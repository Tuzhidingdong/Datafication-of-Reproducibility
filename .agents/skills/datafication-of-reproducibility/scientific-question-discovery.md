# Scientific question discovery methodology

## Purpose and boundary

This reference defines how the DoR Skill turns imperfect structured research data into a broad, disciplined portfolio of scientific questions. It complements the deterministic Runtime; it does not replace, reinterpret, or silently expand Runtime calculations.

The objective is not to maximize significant associations. It is to discover which scientifically meaningful questions are answerable, partially answerable, contradicted, or not yet testable from the evidence already available.

The method is discipline-neutral. It must not encode a subject-area ontology, variable list, preferred mechanism, default unit, experimental protocol, or test-corpus example. Scientific meaning comes only from approved project semantics and user-supplied context. Without those, formulate questions using neutral canonical identifiers and state that interpretation is unresolved.

DoR's structured-data-only rule remains absolute: use declared CSV/JSON data, the Canonical Bundle, supplied data dictionaries, approved semantic metadata, and already-generated structured evidence/locators. Never open or retrieve original papers, SI, PDFs, images, or other raw research documents. An opaque locator is not permission to dereference it.

## Epistemic layers: never collapse these states

Every output must distinguish:

1. **Data fact** — a value, relationship, state, or provenance item explicitly present in the declared structured inputs.
2. **Observed pattern** — a descriptive regularity in a stated subset, without implying an explanation.
3. **Statistical signal** — a pattern that survives a named analysis and its stated uncertainty/multiplicity procedure.
4. **Research question** — a precise, answerable question motivated by the pattern or an evidence gap.
5. **Candidate explanation** — one possible account among competing explanations; not a mechanism finding.
6. **Testable hypothesis** — an explanation translated into predictions that distinguish it from alternatives.
7. **Validated finding** — a result that has passed the relevant independent, prospective, or external validation design.

A p-value, q-value, high correlation, large row count, model improvement, Pareto membership, or LLM-generated explanation does not move a candidate automatically to a higher layer. "Not detected", "not tested", "not identifiable", "not represented", and "evidence against" are different outcomes.

## Discovery is an iterative loop, not a fixed list of filters

Use the following loop. Repeat only when a new result changes the question, evidence, or best next test.

### D0 — Frame the search without prematurely narrowing it

Identify the user's goal, project scope, declared data boundary, prior decisions, forbidden operations, and current approval gate.

If the user has not supplied a narrow target, do not force one. Begin with all represented entities, outcomes, conditions, contexts, comparisons, and explicit relationships. The selected Modeling Task comes later, after the user chooses a question.

Record what counts as useful: explanation, boundary condition, predictive relation, design rule, anomaly resolution, measurement comparison, reproducibility result, or data-quality question. Do not assume every project seeks prediction or optimization.

### D1 — Build a data-capability atlas before choosing methods

Profile the data at their actual grain. Use the declared schema and reviewed mapping; never infer row grain from file shape.

For each entity, variable, relationship, and evidence class, characterize only what is supported:

- role and identity: target/outcome, condition/exposure, system descriptor, protocol/context, time/index, comparison, derived quantity, or unknown;
- measurement type: continuous, discrete, nominal categorical, ordinal, binary, count, interval/range, censored/qualified, temporal, compositional, or structured relation;
- coverage: total records, independent Studies, Systems, Experiments, Observations, comparisons, evidence coverage, and missingness states;
- variation: overall, between-Study, between-System within Study, and within-System across Experiments;
- joint support: pairwise and higher-order co-availability for each exact outcome/variable definition;
- design: matched/paired structure, repeated measures, longitudinal order, factorial crossings, dose levels, nested groups, and repeated conditions;
- comparability: exact endpoint, timepoint, measurement context, unit, qualifier, and semantic-review status;
- provenance quality: reported versus candidate-derived values, review state, evidence links, source conflicts, and unresolved assignments;
- dependence: shared Studies, repeated measurements, derived quantities, duplicate/mirrored records, and possible leakage paths.

Do not reduce this atlas to a single completeness percentage. A feature can have low global coverage but useful support for one question. High coverage may contain no within-group variation and provide no leverage for a response or interaction analysis.

For every candidate design, state its eligible subset, independent inferential units, and exclusions. Use question-specific/pairwise subsets when justified; do not impose a global complete-case cohort. Check whether pairwise availability changes the composition of Studies or Systems being compared, because pairwise selection can itself bias a result.

Use four distinct feasibility labels:

- **ELIGIBLE_FOR_NAMED_DESIGN** — records satisfy the stated design requirements.
- **DESCRIPTIVE_ONLY_OR_UNDERPOWERED** — a pattern can be described, but intended inference is unsupported.
- **NOT_IDENTIFIABLE_FROM_CURRENT_STRUCTURE** — the needed contrast, time order, independent unit, or variable meaning cannot be distinguished.
- **NOT_REPRESENTED_OR_NOT_ASSESSED** — required information is absent or has not been assessed.

Never turn these into a binary usable/unusable verdict. Feasibility is a pre-analysis design assessment; it is not an analysis result. Its relationship to result states is governed by the mapping rules below.

### D2 — Generate questions from multiple independent discovery paths

Do not let the Runtime's current algorithm catalogue define the universe of possible questions. Use these families only where the data structure supports them:

1. **Recurring relationships and contrasts** — Which variables or levels differ together? Do patterns recur within a System, between comparable Systems in a Study, or across independent Studies? What matched or unpaired design is represented?
2. **Response shape and operating regimes** — Is a response monotonic, saturating, threshold-like, non-monotonic, discontinuous, or scale-dependent? Are turning points stable or driven by range restriction?
3. **Effect modification and mixed interactions** — Does a relationship vary with another numeric, nominal, ordinal, or contextual variable? Consider numeric × numeric, numeric × categorical, categorical × categorical, and context × treatment when semantics and crossing support exist. Do not limit the search to products of numeric columns.
4. **Temporal and dynamic behaviour** — Where time order and comparable sampling are explicit, do rates, delays, induction, decay, lagged responses, transitions, hysteresis, or time-varying relationships appear? Do not invent temporal order from record order.
5. **Heterogeneity and boundary conditions** — Why do comparable Studies or Systems show different effects? Which context, protocol, subgroup, or range may delimit where a relation holds? Separate within-Study and between-Study explanations.
6. **Coupled outcomes and trade-offs** — Which outcomes co-vary, decouple, or exhibit conditional relationships? A negative association is not automatically a physical trade-off. Pareto analysis requires user-declared objective directions or clearly labelled mathematical scenarios without recommendation.
7. **Unexpected cases and residual structure** — Which records or Studies depart from the prevailing pattern? Are there clusters, regime changes, exceptions, or reproducible outliers? Preserve them; do not delete them to improve fit.
8. **Replication, contradiction, and reversals** — Which relations replicate, weaken, reverse, or disappear across independent Studies, Systems, conditions, or measurement contexts? Examine aggregation reversals and Simpson's-paradox-like patterns.
9. **Missingness and reporting behaviour** — Which variables, outcomes, conditions, or evidence types are systematically unreported, ambiguous, conflicting, or unavailable in particular contexts? Could the observation process select what becomes visible? Missingness is not zero or proof of physical absence.
10. **Measurement, representation, and mathematical coupling** — Could a relationship arise because one quantity is calculated from another, shares a denominator, uses the same measurement channel, is a proxy, or is transformed from common inputs? Check explicit derivation metadata and algebraic dependencies.
11. **Scaling, normalization, and invariants** — Are relationships more coherent under a dimensionally valid scale, ratio, normalized quantity, or conserved relation? Use only explicit definitions and approved unit/semantic rules; never invent a dimensionless group or conversion.
12. **Relational and network structure** — Do explicit entity links, comparisons, shared dependencies, or sequences reveal informative pathways, repeated motifs, or isolated components? Graph paths are structural evidence, not causal paths unless causal semantics and assumptions are supplied.

For each path, record either a candidate question with an evidence anchor or why it is not applicable/not testable. Do not manufacture a question just to fill every category.

### D3 — Select analysis designs to answer questions, not the reverse

First state the scientific question and required estimand/descriptive quantity. Then choose a method whose assumptions match the represented design. Method classes include:

- paired/matched contrasts for explicitly linked comparisons;
- within-System repeated-measure or dose-response analysis when exposure varies within that System;
- between-System contrasts within the same Study when exposure is constant within System, with explicit composition/protocol confounding warnings;
- cross-Study synthesis when comparable independent Study-level effects exist;
- mixed-effects or hierarchical models when nested dependence and sufficient independent groups can be represented;
- robust regression, rank methods, splines, smooth response curves, segmented models, or change-point analysis when shape and support justify them;
- factorial/hierarchical interaction models for mixed categorical/continuous factors with actual crossing/overlap;
- longitudinal/event-time methods only when time, sampling, censoring, and event definitions support them;
- multivariate, partial-association, or compositional methods only when measurement assumptions and joint support are explicit;
- anomaly/residual and influence diagnostics that identify—not erase—exceptional records;
- missingness/reporting models that treat missingness as a data-collection process, not an imputed scientific value;
- graph-based exploration over explicit canonical relations, retaining edge provenance.

No method is universally suitable. Before fitting, check design rank/identifiability, effective independent sample size, parameters relative to support, range/overlap, missingness selection, and sensitivity to influential units. If a method is not implemented by the current Runtime, list it as an analysis capability gap with a specific implementation/external-analysis requirement. Do not pretend it ran, change thresholds silently, write an untracked one-off script as a production method, or replace Runtime outputs.

The deterministic Runtime is one computational layer, not the boundary of scientific reasoning. Its opportunity catalogue is a seed and evidence index. The Skill must still formulate additional question candidates from the capability atlas, heterogeneity, counterexamples, data-collection patterns, and untested method families. Label them **AGENT_FORMULATED_NOT_RUNTIME_TESTED** until a named analysis is actually executed and recorded.

### D4 — Form competing explanations, not just a preferred story

For each high-priority pattern, formulate at least two materially different explanations when evidence permits. Include a null/no-effect or data-artifact explanation where appropriate.

Challenge every candidate against:

- confounding and co-exposure;
- reverse causation and ambiguous temporal order;
- selection, collider, and survivorship effects;
- Study/System aggregation, ecological inference, and Simpson's paradox;
- batch, protocol, instrument, site, operator, and source differences;
- measurement error, endpoint mismatch, unit mismatch, qualifiers, and range restriction;
- shared denominators, common inputs, algebraic coupling, and derived-variable leakage;
- duplicate records, non-independent replicates, repeated measurements, and train/test leakage;
- influential Studies/Systems, outliers, sparse strata, and unstable subgroup definitions;
- informative missingness, selective reporting, extraction coverage, and unresolved candidate sources.

List evidence supporting and evidence against separately. If the data cannot distinguish explanations, say so and design a test that can.

### D5 — Evaluate robustness without confusing exploration and confirmation

Study remains the independent inferential unit for cross-Study claims; Systems and Experiments are nested support unless an explicitly justified alternative is approved. Do not inflate n with rows, repeated measurements, candidate values, or multiple screens.

Where appropriate, examine:

- leave-one-Study-out and leave-one-System-out stability;
- Study-level direction consistency and counterexamples;
- within-System versus between-System agreement;
- alternative reasonable model families and effect scales;
- subgroup/range sensitivity without post hoc cherry-picking;
- negative-control/placebo relations, if explicitly available and meaningful;
- pairwise-subset composition and missingness sensitivity;
- exact endpoint/timepoint/unit compatibility;
- primary reported values versus each isolated candidate-source scenario;
- multiplicity across the actual family of hypotheses searched.

Do not call a signal robust just because q is below a threshold. Do not call a signal absent because one fixed model did not select it. Separate exploratory discovery from later confirmation; after selection, freeze the confirmatory estimand, subset, model, exclusions, and validation set before examining its results.

### D6 — Prioritize a portfolio, not one opaque score

Use a transparent profile rather than an unexplained weighted total. Assess separately:

- potential scientific importance if resolved;
- strength and consistency of observed evidence;
- independent Study support and diversity of contexts;
- semantic/measurement comparability;
- robustness to alternative explanations and analytic choices;
- feasibility with existing data;
- ability of a new analysis/experiment to distinguish alternatives;
- resource/time cost and expected information gain.

Keep three lanes:

- **Act now** — a useful question can be tested with existing structured data and a valid design.
- **Design next** — important, but a targeted experiment/calculation or structured-data addition is needed.
- **Hold / unresolved** — present data cannot distinguish alternatives or mapping/design is not identifiable.

Do not rank solely by significance, novelty claims, row counts, model fit, or apparent mechanistic sophistication.

### D7 — Turn each selected question into a discriminating test

A test plan states:

1. exact question and competing explanations;
2. predicted observable pattern under each explanation;
3. required data/experiment/calculation and correct independent unit;
4. controls, matched groups, ranges, timepoints, and protocol elements;
5. primary endpoint/estimand, analysis design, uncertainty, and multiplicity plan;
6. what would support, weaken, or falsify each explanation;
7. a feasible minimal test and a stronger follow-up;
8. what existing evidence is sufficient and what is genuinely missing;
9. the exact stable GAP ID(s) from analysis_gap_register.md for each unmet method/data/semantic requirement, or NONE when no gap applies. Do not create a test plan that refers to an unregistered or vaguely described gap.

Prefer the smallest test that can discriminate between explanations. GAP references are traceability requirements, not proof that a gap has been resolved.

### D8 — Feed results back into the question portfolio

After a selected test/analysis, append a versioned feedback event and update the current question record to the next version. Never overwrite or silently rewrite a prior feedback event. A failed test is evidence: it may eliminate an explanation, expose an invalid assumption, identify a boundary condition, or show that a question is not identifiable. If no test/analysis was executed in the current run, record D8 as NOT_EXECUTED with the reason; do not create a synthetic feedback event or increment the question version.

The append-only `discovery_reasoning/question_feedback_log.jsonl` uses one JSON object per actual D8 update with these required fields:

- `feedback_event_id` — stable unique event ID;
- `question_id`, `previous_question_record_version`, and `new_question_record_version` — the new version must equal the previous version plus one;
- `recorded_at` — actual timezone-aware timestamp, never a fabricated or approximate date;
- `run_id`, input Bundle/dataset SHA-256, Skill version, Runtime version, and exact analysis/test ID;
- `execution_status` and `result_status_before` / `result_status_after`;
- `observed_result_summary` and exact evidence/output IDs or hashes;
- `explanations_supported`, `explanations_weakened_or_falsified`, and `unresolved_alternatives`;
- `assumptions_or_design_limits_exposed`, `gap_ids_opened_or_closed`, and `priority_or_next_action_change`;
- `review_state` — distinguish machine-recorded feedback from any human-approved interpretation.

The current question portfolio may summarize the latest version, but the log preserves every prior version and its evidence bindings. Do not infer a feedback update from a planned test, an unexecuted analysis, or a changed narrative alone.

## Hypothesis record: required structure

Each candidate question records the following; unknowns remain unknown:

- question_id — stable, deterministic or run-local ID;
- question_record_version — monotonically increasing integer, starting at 1 for the first recorded version;
- question — one neutral, testable scientific question;
- discovery_origin — Runtime signal, recurring pattern, heterogeneity, anomaly, missingness, contradiction, relational structure, or Agent-formulated;
- epistemic_layer — data fact, observed pattern, statistical signal, research question, candidate explanation, testable hypothesis, or validated finding;
- variables_and_entities — exact canonical IDs and roles; endpoint, timepoint, unit, and context remain separate;
- observed_pattern — what is seen, in which subset, and in what direction/shape;
- eligible_subset — exact Study/System/Experiment/Observation support and selection rule;
- independent_support — independent Study count and nested support counts separately;
- evidence_for and evidence_against — linked to structured evidence and analysis rows;
- competing_explanations — alternatives including data/measurement artefacts;
- confounding_and_identifiability — assessed, unassessed, and unresolved domains;
- method_and_assumptions — named analysis and why assumptions fit;
- uncertainty_and_robustness — effect, interval, p/q when actually computed, sensitivity, and counterexamples;
- semantic_status and measurement_status — approved, partial, unresolved, or conflicting;
- candidate_source_status — primary or separately labelled source-specific sensitivity;
- novelty_status — NOT_ASSESSED_WITHIN_STRUCTURED_DATA_ONLY_WORKFLOW unless separately authorized external novelty review exists;
- falsifying_observation — what would count against the candidate;
- discriminating_test — smallest feasible next test;
- capability_gap_ids — zero or more stable IDs from the run's analysis-gap register; use an empty list only when no capability gap applies. Every D7 test plan must cite the exact applicable GAP ID(s), or explicitly state NONE;
- priority_profile — separate D6 dimensions with rationale;
- feasibility_status — exactly one D1 feasibility label; do not infer it from a p-value or result;
- question_generation_status — RUNTIME_GENERATED, AGENT_FORMULATED_NOT_RUNTIME_TESTED, or AGENT_FORMULATED_TESTED_BY_NAMED_METHOD;
- analysis_execution_status — NOT_RUN, RUN_SUCCEEDED, RUN_FAILED, or BLOCKED_BY_CAPABILITY_GAP; include the named method/run reference when execution was attempted;
- result_status — one value from the result-status vocabulary below. Keep this separate from feasibility_status and question_generation_status.

An Agent-generated question may not fabricate statistics or present an unexecuted analysis as evidence. It must use AGENT_FORMULATED_NOT_RUNTIME_TESTED until tested by a named method.

## Result-status vocabulary and interpretation

Use explicit states:

- NOT_SCREENED — no analysis was attempted.
- SCREENED_NO_SIGNAL — a named analysis ran but did not produce a candidate under its declared decision rule.
- INELIGIBLE_FOR_DESIGN — records failed a named design requirement; include the exact reason.
- NOT_IDENTIFIABLE — competing quantities/effects cannot be separated with current structure.
- DESCRIPTIVE_ONLY — a pattern is visible but inferential claims are unsupported.
- EXPLORATORY_SIGNAL — a candidate pattern passed the named exploratory screen.
- UNSTABLE_OR_CONTRADICTED — direction/conclusion changes materially across independent units or reasonable sensitivity scenarios.
- ANALYSIS_CAPABILITY_GAP — relevant question family has no implemented/approved analysis path.
- VALIDATION_PENDING — a test plan exists but has not been run.
- VALIDATED_FOR_DECLARED_SCOPE — predeclared validation completed for the named scope; do not generalize beyond it.

Every zero count must say what it means. Zero opportunities may mean no eligible design, failed model fits, insufficient independent Studies, no improvement, multiplicity correction, candidate cap truncation, no data variation, no matching endpoint, or simply no pattern. Do not use "no scientific relationship exists" as a generic zero-result conclusion.

### Mapping feasibility, execution, and result states

These are separate axes and must be recorded separately:

- `feasibility_status` answers whether the currently represented subset can support a named design before execution.
- `question_generation_status` records whether the question came from Runtime or was formulated by the Agent and whether that Agent-formulated question has actually been tested by a named method.
- `analysis_execution_status` records whether the named analysis was run, failed, or was blocked.
- `result_status` records what the executed analysis or current evidence supports.

Use this mapping without collapsing the axes:

| D1 feasibility status | Required interpretation before execution | Permitted result-status handling |
|---|---|---|
| `ELIGIBLE_FOR_NAMED_DESIGN` | Design requirements appear satisfied; no result is implied. | Keep `NOT_SCREENED` until a named analysis runs; after execution use the observed result, such as `EXPLORATORY_SIGNAL`, `SCREENED_NO_SIGNAL`, or `UNSTABLE_OR_CONTRADICTED`. |
| `DESCRIPTIVE_ONLY_OR_UNDERPOWERED` | The available subset supports description but not the intended inference. | Use `DESCRIPTIVE_ONLY` when a pattern is actually observed; otherwise retain `NOT_SCREENED` or the specific executed result. |
| `NOT_IDENTIFIABLE_FROM_CURRENT_STRUCTURE` | The required contrast/estimand cannot be distinguished using the current structure. | Use `NOT_IDENTIFIABLE` and state the exact identifiability failure. |
| `NOT_REPRESENTED_OR_NOT_ASSESSED` | The required element is absent or has not yet been assessed. | Use `NOT_SCREENED` when assessment has not occurred; use `ANALYSIS_CAPABILITY_GAP` only when the needed method is unavailable despite a sufficiently represented question. Explain which case applies. |

A design can be eligible and still return no signal; an ineligible design is not a negative scientific result. A capability gap is not the same as absent data, and neither is the same as a failed test. The status vocabulary must be applied only to the matching axis.

### Interpreting the native deep Runtime profile

When a native deep Discovery output is present, read its `deep_scientific_discovery_profile.json` (and the `profile` object in `deep_research_opportunities.json`) as the authoritative Runtime summary. Preserve native values; do not reconstruct or rename fields in a way that changes their meaning. Interpret the fields in these groups:

- **Input/support context:** `outcome_group_count`, `experiment_count_with_numeric_outcomes`, `condition_feature_count_with_numeric_reported_values`, `ambiguous_condition_assignments_excluded`, and `outcome_condition_hypothesis_count` describe the numeric outcome/Condition surface and ambiguity exclusions. They are not independent sample sizes.
- **Hypothesis enumeration and truncation:** `nonlinear_hypotheses_screened` with `nonlinear_hypotheses_omitted_by_limit`; `two_way_hypotheses_screened` with `two_way_hypotheses_omitted_by_limit`; `three_way_hypotheses_screened` with `three_way_hypotheses_omitted_by_limit`; and `multiobjective_pairs_screened` with `multiobjective_pairs_omitted_by_limit` report eligible hypothesis combinations retained for screening and those excluded by explicit caps. `condition_features_omitted_from_pair_and_triplet_combinatorics` reports additional feature truncation. These counts are **not** fitted-model counts, statistically supported opportunity counts, or independent Studies.
- **Model-evaluation coverage:** `eligible_model_evaluations` counts eligible per-System model-evaluation rows returned by the deep screen functions across the declared designs. It is not the number of unique hypotheses, Studies, or final opportunities. Check the corresponding CSV and opportunity records to understand which design/feature combinations produced evidence rows.
- **Final candidate portfolio:** `opportunity_count`, `within_system_opportunity_count`, and `between_system_cross_sectional_opportunity_count` summarize final retained opportunities and their design split; `fdr_screen_positive_count` counts those passing the declared FDR screen, not validated findings.
- **Analysis contract/configuration:** `analysis_unit`, `data_subset_policy`, and `primary_value_policy` state the inferential unit, availability policy, and primary/candidate-source separation. `minimum_studies`, `minimum_experiments_per_system`, `minimum_triplet_experiments_per_system`, `minimum_between_systems_per_study`, `minimum_model_improvement`, `fdr_alpha`, `bootstrap_iterations`, and `seed` record the configuration used. `schema_version`, `engine_version`, and top-level `status` identify the output contract and execution result.

A zero in one profile field is local to that field. For example, zero final opportunities alongside nonzero screened-hypothesis and model-evaluation counts means the Runtime did evaluate some eligible model rows but retained no final candidates under its declared summary/screening rules; it does not show that every possible design was tested or that the scientific relation is absent. Nonzero omitted counts mean the catalogue was bounded and some hypotheses were not screened. Conversely, zero model-evaluation rows with nonzero hypothesis counts indicates that eligible combinations were enumerated but yielded no qualifying per-System evaluation rows; inspect support thresholds, design-specific outputs, and the omission counts before interpreting the cause. Always reconcile profile counts with `deep_condition_response.csv`, `deep_interaction_candidates.csv`, `multiobjective_tradeoff_candidates.csv`, `deep_research_opportunities.json`, and `deep_evidence_ledger.jsonl`.

The configured `minimum_model_improvement` and the per-opportunity `model_improvement_threshold_met` flag must not be described as a universal pre-fit filter unless the active Runtime implementation explicitly uses it to exclude model evaluations. In the current deep-screen implementation, the improvement threshold is recorded on the retained opportunity after the per-System model comparisons are generated; interpret the actual output fields and code version rather than assuming every zero occurred because candidates failed a pre-fit cutoff.

## Discovery report and hand-off

Preserve native Runtime outputs unchanged. Write supplementary reasoning artifacts only inside the declared new run directory, clearly separated from Runtime outputs:

- discovery_reasoning/capability_atlas.md — what structured data can and cannot answer;
- discovery_reasoning/question_portfolio.md — question origin, evidence, competing explanations, and priority profile;
- discovery_reasoning/analysis_gap_register.md — attractive but untested questions, exact method/data-structure gap, and requirements;
- discovery_reasoning/discriminating_test_plans.md — selected questions and tests that distinguish alternatives;
- discovery_reasoning/question_feedback_log.jsonl — append-only, versioned D8 events when an actual test/analysis result updates a question; omit the file when no D8 event has occurred and state D8=NOT_EXECUTED in the report.

Each artifact binds the input Bundle/dataset hash, adapter/mapping version, Runtime/Skill version, run ID, and native output IDs/hashes it references. Keep row-level evidence in the protected run workspace; LLM context receives only bounded question-specific summaries and evidence identifiers.

If a supplementary analysis is executed, record its code/version, exact input subset, assumptions, independent units, and output hash. Keep its results separate from native Runtime results until formally integrated through a reviewed generic Runtime extension. Never overwrite native opportunity catalogues, p/q values, evidence ledgers, or profiles.

Present the user with a concise portfolio of questions, evidence strength, competing explanations, and discriminating tests. User approval selects direction; it does not turn an exploratory candidate into a confirmed finding.

## Non-negotiable safeguards

- Preserve source data, primary reported values, missingness, candidates, conflicts, quotes, and opaque locators exactly.
- Never average, select, or promote unresolved candidate alternatives. Analyse each source independently as a sensitivity scenario; never pool scenarios or increase n.
- Never compare endpoints, timepoints, conditions, or units merely because labels look similar. Require approved semantics and conversion rules.
- Never imply causality, mechanism, novelty, or optimization direction without corresponding evidence and review.
- Never force globally complete data, impute missing values silently, or treat missingness as absence.
- Never count Observation, Experiment, System, or candidate rows as independent Studies.
- Never turn an omitted/capped/unsupported hypothesis into a negative result.
- Never lower thresholds, alter subsets, or change methods after seeing results without labelling the work exploratory and preserving the original analysis.
- Never add project/test scientific content to the production Skill, Runtime, schemas, fixtures, or generic documentation.

## Methodological design references

These references inform workflow architecture, not domain-specific scientific claims:

- EXHYTE frames AI-assisted discovery as an iterative connection among exploration, hypothesis generation, and testing, and identifies executable testing/feedback as a central integration gap: https://doi.org/10.1016/j.patter.2026.101660
- ResearchLink illustrates domain-independent hypothesis generation over structured knowledge graphs, while graph-based link prediction remains a hypothesis generator requiring expert validation: https://doi.org/10.1016/j.knosys.2025.113280
- Exploratory and confirmatory analyses have different aims; data-derived hypotheses require separate independent confirmation when inferential claims are intended: https://pmc.ncbi.nlm.nih.gov/articles/PMC10186672/
