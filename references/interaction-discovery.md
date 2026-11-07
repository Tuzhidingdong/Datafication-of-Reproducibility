# Interaction discovery

## Research objective

Discover condition interactions that help explain and predict observable outcomes. The object of interest is not merely a model importance ranking, but a relationship whose support, domain, stability, and scientific interpretation can be examined.

## Separate four questions

1. Is there a nonlinear main effect?
2. Is there a statistical interaction between conditions?
3. Does the interaction improve prediction beyond a defensible baseline?
4. Is there evidence that the interaction corresponds to a real domain mechanism?

These questions require separate evidence.

## Candidate generation

Generate candidates from domain-informed hypotheses, coverage and joint-support analysis, model-derived interaction screening, and exploratory pairwise association analysis.

Do not test every possible pair indiscriminately. Prioritize pairs with adequate joint support and scientific plausibility. Higher-order interactions require stronger justification.

## Methods

Depending on data and model:
- generalized additive models and tensor-product smooths;
- Explainable Boosting Machine interaction terms;
- SHAP interaction values;
- Friedman H-statistic;
- sparse interaction regression;
- hierarchical interaction models;
- conditional response surfaces and partial-dependence/ICE analyses where assumptions are appropriate.

No single statistic is universally suitable. Record the exact definition and implementation used. Do not compare unlike interaction-strength statistics as if they had the same scale.

## Confounding and study effects

An apparent interaction may arise because combinations of conditions are concentrated in particular studies, laboratories, materials, or protocols. Check joint feature coverage, study/DOI composition, study-level random effects or stratification, leave-study-out stability, sensitivity to influential studies, alternative feature coding, counterexamples, and null results.

If the data contain no overlap between important condition groups, the interaction is not identifiable from the assembled observational evidence.

## Interaction record

Each candidate interaction should store stable ID; variable names, units, encodings, and roles; target and endpoint; discovery method and statistic definition; effective sample size and independent study count; joint support and observed range; effect/response surfaces and source data; uncertainty and robustness tests; predictive contribution, if assessed; counterexamples and null evidence; interpretation status and evidence links.

## Language discipline

Use "candidate interaction", "statistical interaction", or "cross-study association" unless stronger evidence exists. Do not use "synergy", "mechanism", or causal language solely because an interaction statistic is non-zero.
