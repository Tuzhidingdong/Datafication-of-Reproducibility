# Scientific Discovery Engine

## Purpose

The Scientific Discovery Engine is DoR's domain-neutral exploratory entry point. It profiles a validated Canonical Bundle, summarizes the support and distribution of declared targets across Studies, reports coverage of linked conditions, and identifies target pairs recorded within the same canonical experiment.

It produces aggregate-only outputs for agent-led question formation. It does not establish accepted findings, novelty, causality, mechanisms, or statistical significance.

## Input contract

The preferred input is a Canonical Bundle created by the reviewed mapping/build workflow or supplied by a validated external adapter package.

    dor discover-opportunities --bundle path/to/canonical_bundle.json --out-dir path/to/new/discovery_run

The command first checks canonical structure and referential integrity. It then reads only the declared entities and links in the bundle. The input is hash-checked before and after processing. The command refuses to overwrite a non-empty output directory.

The same Canonical Bundle can be registered as a source artifact in a formal Run Plan and used by downstream reconciliation, cohort construction, modelling, validation, and publication stages. The exploratory scan does not create a formal Run, approve a mapping, select a target, or cross a G0-G4 gate.

## Outputs

- discovery_manifest.json — input and output hashes and read-only execution scope.
- discovery_data_profile.json — counts of Studies, Systems, Conditions, Experiments, Observations, and declared targets.
- target_support.csv — observation and Study counts plus descriptive numeric summaries by exact target/unit.
- study_coverage.csv — per-Study numeric summaries using the declared Study and Observation links.
- condition_support.csv — coverage of explicitly linked, reported Conditions.
- joint_support.csv — target pairs co-recorded within one canonical Experiment.
- signal_catalogue.csv — bounded descriptive signals with interpretation limits.
- discovery_report.json — machine-readable profile, signals, and limitations.
- agent_research_brief.md — bounded aggregate-only reasoning input.

## Interpretation boundaries

- The scan does not infer target or condition semantics from identifiers or labels.
- Units are kept as exact strings. No implicit conversion is performed.
- Study-level summaries are descriptive, not inferential heterogeneity tests.
- Condition coverage does not estimate a condition effect.
- Co-observation within a canonical Experiment is not evidence of causal interaction or mechanism.
- No p-values, multiple-testing correction, causal effects, novelty determinations, or mechanism claims are generated.
- The accuracy of Study, System, Experiment, Condition, Observation, and Evidence links remains dependent on the upstream adapter and reviewed mapping.

## Next step

An Agent may use the aggregate brief and report to propose a small set of testable research opportunities. Each proposal must identify supporting signal IDs, Study support, feasibility, identifiability, confounding risks, counterexamples, validation requirements, and novelty-review status.

The user selects or revises a research direction before a formal analysis task and Run are initialized. Exploratory outputs remain candidates and never substitute for the canonical reconciliation, endpoint-specific cohort, Study-level validation, interaction robustness, mechanism-evidence review, or publication workflow.
