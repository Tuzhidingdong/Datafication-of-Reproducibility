# Canonical research data model (V0.2)

## Design objective

The canonical model represents relationships needed for reproducibility analysis without assuming a particular discipline, paper structure, source-file format, or experimental workflow. It is a reviewed analytical representation, not a replacement for the original source database.

## Entities

| Entity | Meaning | Important boundary |
|---|---|---|
| Study | A publication, report, registered study, or other traceable research source | One study may describe multiple systems and experiments |
| System | A project-defined entity being investigated or analysed | A system may recur across studies; retain all source study links |
| Condition | A reported or explicitly unreported condition associated with a system | A reported setpoint is not proof of the local physical state |
| Experiment | A defined experimental execution or protocol instance | Do not equate a source-table row with an experiment without evidence |
| Observation | A measured, derived, or reported result for a defined target and endpoint | Keep distinct endpoints, timepoints, and measurement contexts separate |
| Comparison | An explicit relation between two or more observations | Do not infer equivalence merely because values share a feature name |
| Evidence | A traceable source passage, table cell, figure panel, method statement, or metadata item | Evidence provenance must point back to a versioned source file and locator |

The model permits one-to-many and many-to-many relationships where scientifically justified. One study may report several systems; one system may be studied under multiple conditions; one experiment may yield multiple observations; and a comparison may connect observations from different studies.

## Relationship rules

- A System links to one or more Studies.
- A Condition links to the System or Systems to which it applies.
- An Experiment links to one Study, one System, and zero or more Conditions.
- An Observation links to one Experiment and one target definition, and may cite multiple Evidence records.
- A Comparison links to at least two Observations.
- An Evidence record links to its originating Study and a source locator.

Cross-study reuse of a System is allowed, but each Experiment must link to a Study that is among the linked Studies for that System. Conditions used by an Experiment must be linked to that Experiment's System.

## Observation identity and endpoint separation

An Observation is not identified only by a feature name. Its interpretation may depend on target definition, endpoint, protocol, timepoint, system, and evidence. Two measurements with similar labels may still represent different endpoints when their operational definitions or measurement contexts differ. They must not be merged merely because their labels or units look similar.

Replicates must be represented only when the source supports replicate identity. Repeated measurements, multiple cells, figure points, or table rows must not automatically be called independent replicates.

## Conditions and missingness

The allowed value states are REPORTED, NOT_REPORTED, NOT_APPLICABLE, AMBIGUOUS, CONFLICTING, and NOT_ASSESSED. Raw reported values and units are retained. Normalized values and units are additional fields and require an approved conversion rule. Never replace an absent condition with zero, a literature convention, or an assumed default.

A Condition or Observation may also carry an optional `value_candidates` array. Each candidate has its own stable candidate ID, candidate-source ID, raw and/or normalized value/unit pair, optional quoted excerpt, and opaque source locators. This is how multiple extraction outputs, unresolved values, and disagreements remain attached to the same scientific record without creating duplicate Observations. Candidate alternatives do not change the parent record's `value_state` and are not primary reported values. Never average candidates, select the first candidate, or treat candidate rows as independent measurements. Discovery inventories and reconciles them separately, then may run one explicitly labelled sensitivity scenario per candidate source. A scenario does not approve that source's values; source-specific conflicts remain in the inventory and are skipped from that scenario's overlay.

## Provenance

Each source locator records the source file, its SHA-256, locator type, and locator value. Evidence records retain a source-study link and evidence type. Extraction confidence or verification state is recorded separately from scientific validity.

Stable canonical IDs are assigned by the mapping process and must remain stable within a mapping version. Re-mapping is versioned; it must not silently rewrite original source records.

## Validation

Run:

    dor validate-bundle --input canonical_bundle.json --out validation_report.json

The runtime checks required entity fields, duplicate IDs, referential integrity, selected relationship consistency, missingness-state vocabulary, comparison size, and evidence locator presence. It does not decide whether the scientific mapping is correct, whether an experiment is independent, whether a target is equivalent across studies, or whether a mechanism is causal.

The JSON Schema at schemas/canonical_bundle.schema.json defines the bundle's machine-readable structure. Runtime validation currently adds selected cross-record integrity checks; it is not a full JSON Schema engine.

## Mapping approval boundary

Source inventory items begin as UNRESOLVED. A mapping proposal must be reviewed and approved before it is used to create canonical entities or enter a modelling cohort. Preserve the original source and the exact source locator for every mapped field. Ambiguous and conflicting evidence must remain visible rather than being silently reconciled.
