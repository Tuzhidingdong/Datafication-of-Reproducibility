# Cross-disciplinary scope and adapter boundary

## What cross-disciplinary means

DoR's core Runtime, Skill, Run Plans, schemas, templates, and test fixtures are discipline-neutral. They define evidence traceability, source integrity, canonical relationships, explicit mapping approval, run provenance, analysis validation, human review, and publication hand-off. They must not embed discipline-specific vocabularies, field taxonomies, default values, units, or scientific assumptions.

Discipline-neutral infrastructure does not mean that the current analysis engine implements every research method or that every research dataset can be represented without loss in the current Canonical model.

## Current Canonical representation

The current Canonical model is a general-purpose empirical relationship graph with these generic entities:

- Study: a traceable research source or study record.
- System: a project-defined investigated or analysed entity.
- Condition: a reported or explicitly unreported attribute linked to a System and used by an Experiment.
- Experiment: an execution, protocol instance, or explicitly defined unit linked to a Study and System.
- Observation: a reported result linked to an Experiment and an explicit target definition.
- Comparison: an explicit relation among Observations.
- Evidence: a traceable source passage, data location, or metadata item linked to its Study.

This graph supports many empirical research workflows, but it is not a universal ontology. A project must not force its data into these entities when doing so would change the meaning, grain, dependency structure, or evidence lineage of the source.

## Current analysis-engine scope

The current modelling path requires an explicit target/endpoint, explicit feature bindings to linked Conditions, reported values with exact declared units, and an eligible Observation-to-Study relationship. The baseline engine supports a limited set of deterministic numeric and categorical baselines. Reproducibility evaluation uses Study-grouped splits. The interaction engine screens numeric pairwise predictive terms; it does not provide general causal inference, inferential significance testing, or a discipline-specific mechanistic model.

These are current engine boundaries, not recommended scientific defaults for all disciplines. A successful Runtime validation does not establish that the chosen representation, target, split, or analysis is scientifically appropriate.

## Adapter responsibilities

A project-specific external Adapter may:

1. interpret its source formats and project-specific semantics;
2. propose mappings into the generic Canonical entities only when those mappings preserve the source meaning and record grain;
3. retain unsupported or ambiguous source structures as explicit source artifacts and report them as unsupported, unresolved, or requiring external analysis;
4. produce a valid generic Canonical Bundle only when provenance, identity, and relationship requirements can be met; and
5. document any external analysis performed outside the current DoR analysis engine.

An Adapter must not fabricate missing Conditions, Experiments, independent Studies, target definitions, units, sample identifiers, or evidence links merely to satisfy the Runtime schema. A project may use the DoR evidence and workflow infrastructure without invoking the modelling and interaction stages.

## Extension rule

If a workflow cannot be represented faithfully by the current Canonical graph or analysis engine, keep its scientific logic in a separately maintained Adapter or project-owned extension. Extend the generic core only for a genuinely reusable, discipline-neutral contract. Do not add a discipline-specific parser, ontology, default, example, or test fixture to the core.
