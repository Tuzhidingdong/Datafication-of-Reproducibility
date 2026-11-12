# Data model and source-data policy

## Source data is immutable

CSV, JSON, full-text papers, supplementary files, and other original evidence are read-only. Do not clean in place, normalize in place, or overwrite. Hash each source before analysis and record its identity in the run manifest. Derived tables belong in the run workspace.

## Distinguish entities

The canonical representation must not assume a one-to-one relationship between input rows, experiments, and outcomes.

| Entity | Meaning |
|---|---|
| Study | A publication or independently identified research source; DOI is a common identifier but not always sufficient |
| System | A material, formulation, device, specimen, or experimental system described in the source |
| Condition | A preparation, environmental, operating, or protocol condition applied to a system |
| Experiment | A specific procedure or test performed on a system under conditions |
| Observation | A measured or reported outcome from an experiment |
| Comparison | A scientifically justified relation between two or more experiments, such as a matched control/additive comparison |
| Evidence | The source passage, table, figure, supplementary data, or file supporting a record |

A system can have multiple experiments. An experiment can produce multiple observations. A study can contain multiple systems and conditions. An observation must retain links to its study, system, experiment, condition, and evidence where known.

## Missingness vocabulary

Use explicit states rather than a single ambiguous null:

- REPORTED: explicitly present in the source.
- NOT_REPORTED: source was checked and does not report the value.
- NOT_APPLICABLE: the variable does not apply to this system or procedure.
- AMBIGUOUS: source wording or mapping is unclear.
- CONFLICTING: multiple source locations report incompatible values.
- NOT_ASSESSED: the field has not yet been checked.

A missing value is not zero. Do not fill missing conditions with common defaults unless the source explicitly reports them or a separately approved, scientifically justified imputation procedure is used and documented.

## Preserve raw and normalized representations

For every mapped field, preserve source field/path, raw text or raw value, normalized value, normalized unit, transformation and conversion, missingness/qualifier status, evidence pointer, and mapping version.

Never discard precision, inequality qualifiers, ranges, approximation markers, or test-endpoint semantics. For example, "more than 700 h" must not silently become an exact failure time of 700 h.

## Units and outcomes

A unit conversion must be explicit and reversible where possible. Do not compare outcomes with different definitions merely because their names are similar. Define target semantics including cell configuration, measurement method, endpoint, loading/current conditions, time/cycle basis, and qualifiers where available.

## Study dependence and leakage

Records from the same DOI or study may share materials, instruments, authors, protocols, and reporting choices. Group dependent records during train/test splitting. If a paper reports multiple related observations, they are not automatically independent samples.

## Comparison construction

Create a matched comparison only when the source supports the relationship and the relevant system/test definitions are sufficiently compatible. Similar values or similar system names alone are not enough. Record the matching rationale and unresolved condition differences.

## Input formats

The framework may accept wide CSV, nested JSON, relational tables, spreadsheets, or other structured sources through adapters. The generic core should not assume a specific JSON nesting shape or hard-code a particular set of 24 features.
