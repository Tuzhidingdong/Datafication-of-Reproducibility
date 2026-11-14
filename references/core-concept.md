# Core concept: Datafication of Reproducibility

## Purpose

Datafication of Reproducibility is a reusable research methodology for learning how declared conditions, context, and interacting processes relate to observable outcomes. Scientific sources report finite labels, configurations, and measurements; they do not necessarily describe the complete underlying state or every process that contributes to an outcome.

The goal is to turn the reproducible structure of research observations into computable, testable representations while preserving source evidence and uncertainty.

## Three distinct layers

1. **Reported conditions:** the operational labels, setpoints, compositions, protocols, materials, and apparatus details stated in a source.
2. **Realized state and processes:** spatially and temporally varying states and interactions that may include unreported or indirectly represented quantities.
3. **Observable outcomes:** measurements, distributions, time traces, classifications, or other reported results.

Do not equate a reported condition with a complete description of the realized state. A reported setting or nominal value does not prove that every local state variable remained uniform or was directly measured.

## Reproducibility as a learnable relation

A useful abstraction is:

    reported conditions + context -> realized processes -> observable outcomes

The mapping may be nonlinear, path-dependent, multiscale, and interactive. It may contain latent state variables and feedback. Machine learning can estimate predictive relationships and identify candidate interactions, but the statistical representation is not itself a physical mechanism.

The framework therefore has two linked objectives:

- **Predictive objective:** estimate outcomes for supported combinations of explicitly represented inputs, with uncertainty and an explicit applicability domain.
- **Scientific objective:** identify robust relationships and formulate explanations that can be assessed using independently supplied evidence and domain expertise.

## What the framework does not assume

- It does not assume that every source reports all relevant conditions.
- It does not assume that all variables are independently controlled.
- It does not assume that a reported setting equals every local state.
- It does not assume that identical names always denote identical systems or procedures.
- It does not assume that every statistical interaction is causal.
- It does not assume that all results can be collapsed into one universal target.
- It does not assume that extrapolation to unstudied input combinations is reliable.

## Scientific reasoning ladder

Keep these claim types separate:

1. Descriptive observation in a source.
2. Statistical association in the assembled data.
3. Interaction detected by a specified model/statistic.
4. Interaction that is stable across independent Studies.
5. Explanatory hypothesis proposed to account for an observed relationship.
6. Explanation supported by direct evidence or independently validated theory.
7. Explanation and prediction confirmed prospectively.

The wording of reports and manuscripts must match the achieved level.

## Domain independence

The methodology and Runtime are domain-general. Research-specific meanings, vocabularies, entity extensions, unit policies, extraction rules, and validation criteria are supplied by independently maintained adapters and project-owned profiles. The DoR core defines the handoff and provenance contracts but must not hard-code any subject-area concepts.

The same workflow can be applied to different research areas without changing the DoR core. Each project supplies the mappings and scientific review criteria needed for its own data.
