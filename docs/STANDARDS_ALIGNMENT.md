# Standards alignment

## Objective

DoR is a cross-disciplinary workflow Skill. Standards are selected to improve portable data exchange, provenance, semantic interoperability, validation, and reproducible execution without binding the core Runtime to a subject-area ontology or experimental protocol.

DoR schemas remain implementation-owned contracts. External projects and adapters may map their own vocabularies to wider standards where appropriate; the core does not require a particular domain vocabulary.

## General-purpose standards and conventions

| Area | Candidate standard or convention | DoR use | Boundary |
|---|---|---|---|
| Structured data contracts | JSON Schema | Validate package, workflow, task, report, and evidence-record shapes | Schema validity does not establish scientific correctness |
| Tabular data packages | Frictionless Data Package and CSV metadata conventions | Describe tabular files, fields, constraints, and package resources | DoR retains its explicit source inventory and mapping contracts |
| CSV semantics | W3C CSV on the Web (CSVW) | Optional metadata for column descriptions, datatypes, and foreign-key relationships | Use only when it improves interoperability for a project |
| Provenance | W3C PROV model | Map entities, activities, and responsible agents to source and execution lineage | DoR's current manifests and ledgers remain the operational records |
| Research object packaging | RO-Crate | Candidate export format for a portable bundle of data, evidence, software, and workflow metadata | Do not replace the internal canonical model before the real workflow is validated |
| Unit representation | UCUM and QUDT | Optional project-level unit representation and conversion references | Never silently normalize or merge values; every conversion must be explicit and traceable |
| FAIR data principles | FAIR Guiding Principles | Guide findability, accessibility, interoperability, and reuse of released artifacts | FAIR alignment is not a substitute for access control or source permissions |
| Workflow portability | Common Workflow Language (CWL) | Candidate interoperability layer for portable execution descriptions | The current Run Manager is a file-based provenance and recovery layer, not a CWL engine |
| Software/environment provenance | Standard package metadata and reproducible environment records | Record Runtime version, dependencies, configuration, and execution environment | A recorded environment is not proof that external infrastructure is identical |

## Adoption policy

1. Prefer standards that solve an observed interoperability problem over adding standards for completeness.
2. Keep domain vocabularies and discipline-specific schemas in project-owned profiles or external adapters.
3. Preserve original values and units. Any normalization or conversion must have an explicit, versioned rule and source trace.
4. Bind generated artifacts to exact source and configuration hashes.
5. Keep validation layers distinct: schema validation, structural/reference validation, provenance validation, and scientific review answer different questions.
6. Do not claim conformance to a standard unless the relevant serialization, required fields, and validation rules are actually implemented.

## Current implementation boundary

DoR currently implements its own JSON contracts, source inventories, canonical entities, mapping plans, evidence locators, hash-bound Run events, approval ledgers, and publication manifests. These provide stable internal behavior.

The following are future interoperability options, not claims of current conformance:

- export of canonical entities and provenance to RO-Crate and W3C PROV;
- optional CSVW or Frictionless metadata for external tabular exchange;
- explicit UCUM/QUDT unit metadata in project-owned mappings;
- portable workflow export to CWL where an external execution platform requires it.

No subject-specific ontology, source vocabulary, unit catalogue, or protocol is a required DoR dependency.
