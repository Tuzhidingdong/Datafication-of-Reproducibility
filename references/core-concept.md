# Core concept: Datafication of Reproducibility

## Purpose

Datafication of Reproducibility is a reusable research methodology for learning how experimental conditions and their interactions relate to observable outcomes. It begins from a philosophical and methodological premise: experimental phenomena exhibit reproducibility under sufficiently specified conditions because the processes that generate them have regularities. Scientific papers report finite labels and measurements for those conditions; they do not necessarily report the complete physical state or every interaction occurring during the experiment.

The goal is to turn the reproducible structure of experimental phenomena into computable, testable representations.

## Three distinct layers

1. **Reported conditions:** the operational labels, setpoints, compositions, protocols, materials, and apparatus details stated in a paper.
2. **Realized experimental state and processes:** spatially and temporally varying states and interactions that may include unreported or indirectly represented quantities.
3. **Observable outcomes:** measurements, distributions, time traces, classifications, or other reported results.

Do not equate a reported condition with a complete description of the realized state. For example, a nominal temperature or applied current does not prove that local temperature, concentration, field, or reaction rate remained spatially uniform.

## Reproducibility as a learnable relation

A useful abstraction is:

    reported conditions + context -> realized processes -> observable outcomes

The mapping may be nonlinear, path-dependent, multiscale, and interactive. It may contain latent state variables and feedback. Machine learning can estimate predictive relationships and identify candidate interactions, but the statistical representation is not itself the physical mechanism.

The framework therefore has two linked objectives:

- **Predictive objective:** estimate outcomes for supported combinations of conditions, with uncertainty and an explicit applicability domain.
- **Scientific objective:** discover robust interactions among conditions and explain them through domain-specific physical, chemical, biological, or other mechanisms.

## What the framework does not assume

- It does not assume that every paper reports all relevant conditions.
- It does not assume that all variables are independently controlled.
- It does not assume that a reported setpoint equals every local state.
- It does not assume that identical names always denote identical experimental systems.
- It does not assume that every statistical interaction is causal.
- It does not assume that all experimental results can be collapsed into one universal target.
- It does not assume that extrapolation to unstudied condition combinations is reliable.

## Scientific reasoning ladder

Keep these claim types separate:

1. Descriptive observation in a source.
2. Statistical association in the assembled data.
3. Interaction detected by a specified model/statistic.
4. Interaction that is stable across independent studies.
5. Mechanistic hypothesis explaining the interaction.
6. Mechanism supported by direct experimental or theoretical evidence.
7. Mechanism and prediction confirmed prospectively.

The wording of reports and manuscripts must match the achieved level.

## Domain independence

The methodology is domain-general, while scientific meanings are domain-specific. A domain profile defines entities, condition families, outcome types, units, identifiers, experimental protocols, and mechanism vocabulary. The generic engine must not hard-code zinc-battery concepts.

The same workflow can be adapted to catalysis, DNA experiments, materials synthesis, or other experimental fields, but domain-specific representations and validations must be supplied for each field.
