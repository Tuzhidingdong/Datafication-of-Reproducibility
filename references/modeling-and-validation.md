# Modelling and validation strategy

## Do not preselect one universal model

The engine selects candidate models after data profiling. The choice depends on independent studies and systems, target type and endpoint definition, feature types and joint coverage, missingness pattern, study-level heterogeneity, nonlinearities and plausible interactions, intended interpolation/extrapolation, and compute/interpretability constraints.

## Baselines first

For appropriate numeric outcomes, consider a transparent baseline such as a mean/median predictor and regularized linear regression. Consider GAMs for smooth nonlinear effects. Tree ensembles such as CatBoost, Random Forest, or ExtraTrees may be suitable for mixed tabular features. EBM can provide interpretable main effects and selected interactions. Hierarchical Bayesian models may be useful when study-level structure is substantial. Gaussian processes are generally more suitable for smaller, carefully represented datasets. GNNs or deep learning are optional and require a clear structural representation and adequate independent data.

These are candidates, not mandatory dependencies or a fixed ranking.

## Outcome-specific cohorts

Do not force unrelated outcomes into one target column. Define a separate cohort and endpoint specification for each target. Preserve distinct test methods and endpoints even if source labels look similar.

Multi-task learning is considered only when targets have sufficient aligned observations and scientifically meaningful relationships. Sparse overlap may make separate models more defensible.

## Validation design

At minimum, evaluate whether a split should group by DOI/study. Consider grouped holdout by study, grouped cross-validation, temporal holdout when publication dates support the question, scaffold or structural split for molecular generalization, and external validation with independent experimental data.

Random row splitting is not an acceptable sole validation strategy when multiple rows from the same study are dependent.

All preprocessing that learns from data must be fitted within training folds. Feature selection, imputation, scaling, and hyperparameter selection must not leak test information.

## Metrics

Choose metrics based on outcome meaning and distribution. Report more than one appropriate metric where useful. Distinguish percentage points from relative percentages. Include intervals or resampling uncertainty where feasible. Always report cohort size and group count with metrics.

For censored or interval-valued outcomes, do not treat bounds as exact observations. Use an appropriate survival/interval-censoring method only if the data semantics and sample size support it.

## Applicability domain and uncertainty

For each prediction, report whether conditions lie within training support. Identify missing critical inputs and combinations with weak joint coverage. Consider calibrated prediction intervals or conformal methods when assumptions are defensible. Do not present an extrapolated point prediction as reliable merely because software returns a number.

## Model selection record

The model card must record task/target definition and endpoint; included study/system/observation IDs; features and units; preprocessing; algorithm and exact software version; hyperparameters and search space; random seed; split/group definitions; metrics by fold and final test; predictions and residuals; fitted model artifact where feasible; applicability domain and limitations.

A publication-ready methods description must be generated from this record.
