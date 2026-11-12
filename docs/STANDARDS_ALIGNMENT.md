# DOR Standards Alignment and Reuse Decisions

**Review date:** 2026-11-12  
**Repository baseline:** `v0.1-foundation`, audited at `6275727279f680e887cb9672652a52bbc188eae0`  
**Purpose:** decide where DOR should reuse existing standards and tools instead of inventing additional formats or infrastructure.

## 1. Decision summary

DOR should keep its domain-aware scientific data model and deterministic Runtime, but stop treating every cross-cutting concern as a reason to invent another internal format.

The strongest target for external research-package interoperability is:

- **RO-Crate 1.3** for packaging research data, software, metadata, and results.
- **Workflow Run RO-Crate 0.6** for describing actual computational tool/workflow executions.
- **W3C PROV-O** as the conceptual provenance vocabulary for entities, activities, and responsible agents.

Scientific metadata should reuse relevant domain standards through mappings:

- **ISA** for investigation/study/assay experimental metadata concepts.
- **EMMO domain-battery / BattINFO** for battery-specific concepts and linked metadata.
- **BDF 1.0** for battery cycler time-series files, not for all literature-derived observations.
- **QUDT and UCUM** for quantity semantics and machine-readable unit codes.
- **Frictionless Data Package / Table Schema** for portable tabular resources.

Specialist tools such as DataLad, MLflow, and CWL should remain optional integration candidates. They should not become mandatory Runtime dependencies before a real workflow demonstrates a need.

## 2. Standards and tool decisions

| Standard/tool | What it already solves | DOR decision | What DOR should not do |
|---|---|---|---|
| RO-Crate 1.3 | Portable research-object package with files and structured metadata | **Adopt as the future external evidence-package target** | Do not replace the internal canonical graph or immediately migrate every internal file |
| Workflow Run RO-Crate 0.6 | Provenance description of process/workflow executions and generated artifacts | **Adopt as an export profile for completed DOR runs** | Do not confuse a run description with execution orchestration or scientific approval |
| W3C PROV-O | Generic Entity–Activity–Agent provenance relations | **Adopt conceptually and map/export** | Do not create a second competing DOR provenance ontology or imply identity authentication |
| ISA Abstract Model / ISA-JSON | Investigation, Study, Assay experimental metadata model and serialization | **Map where useful; provide import/export bridge if needed** | Do not replace DOR's Experiment/Observation/Evidence model with a forced one-to-one ISA translation |
| EMMO domain-battery / BattINFO | Battery materials, cells, methods, properties, data, ontology terms, schemas, mappings and authoring/validation tools | **Use as a domain-vocabulary reference and mapping target; prototype adapter only after source audit** | Do not hard-depend on the currently active-development BattINFO tooling or assume the ontology fully covers literature-level experimental context |
| Battery Data Format (BDF) 1.0 | Per-cell battery cycler time-series data with specified quantity fields and units | **Support as a specific raw-data adapter where such files exist** | Do not treat BDF as the canonical format for literature tables, formulation metadata, images, DFT outputs, or all battery experiments |
| QUDT | Quantity kinds, units, dimensions, systems of units, and semantic relationships | **Use for semantic quantity/unit annotations and dimensional references** | Do not assume a unit code alone defines endpoint equivalence or the scientific basis of a conversion |
| UCUM | Machine-readable codes for units and combinations | **Use for unambiguous unit-code representation alongside raw source units** | Do not overwrite original unit strings or silently convert values |
| Frictionless Data Package 2.0 / Table Schema | Dataset/resource packaging and machine-readable tabular field descriptions | **Use for portable CSV/table sub-packages when useful** | Do not replace RO-Crate for the full research object or DOR's entity graph |
| DataLad | Git/git-annex-based dataset versioning and command-run provenance | **Defer; evaluate for large-data versioning or cross-run command reproducibility** | Do not layer it on top of Run Manager without deciding which system owns dataset state and provenance |
| MLflow Tracking | Model-run parameters, code versions, metrics, datasets, models and artifacts | **Defer; optional integration if model experimentation grows materially** | Do not replace DOR's task/endpoint/Study/evidence contracts with generic ML experiment metadata |
| Common Workflow Language (CWL) 1.2 | Portable descriptions of command-line tools and workflow DAGs | **Defer; consider exporting selected plans if cross-platform execution becomes a real requirement** | Do not introduce a workflow engine now; DOR Run Manager currently records/plans but does not execute workflows |
| Battery Data Commons | Curated catalogue of battery dataset metadata and discovery links | **Use as a discovery/reference resource, not a Runtime dependency** | Do not mistake it for a raw-data repository or a data-processing standard |

## 3. Detailed alignment

### 3.1 Research package and computational provenance

#### RO-Crate 1.3 — adopt for external packaging

RO-Crate describes a research object as a package of data files and structured metadata using JSON-LD. The official specification identifies 1.3 as the current long-term release; 1.2 remains a stable earlier release while the community develops the next major modularized version.

DOR already has a curated publication package with:
- a Writing Skill guide;
- a machine-readable manifest;
- explicitly declared artifact files;
- artifact IDs, paths, status, linked records and hashes;
- package integrity auditing.

That is a useful internal hand-off, but it is DOR-specific. The next interoperability step should be an **additional RO-Crate representation** that indexes the same already-approved artifacts. The existing package builder should remain stable until a real-data package has passed review.

A future crate should expose at least:
- the research project and Study identity;
- primary papers, SI, original datasets, and derived datasets;
- canonical bundle and human review decisions;
- Run Plan, Run Manifest, execution records and software identities;
- model/evaluation/interaction/mechanism artifacts;
- publication guide, outputs, and completeness/limitations metadata.

The crate should not silently copy an entire source corpus. It should package only explicitly selected materials and use references/identifiers where a large or restricted source cannot be redistributed.

Reference: [RO-Crate 1.3 Specification](https://www.researchobject.org/ro-crate/specification).

#### Workflow Run RO-Crate 0.6 — adopt for execution export

The Workflow Run RO-Crate profiles distinguish:
- a software tool or computational workflow;
- the action that executed it;
- its inputs and generated outputs;
- prospective workflow description versus retrospective record of what actually ran.

This fits DOR's Run Manager well. A DOR Run Event is execution provenance; it is not an approval and not the whole scientific history. Workflow Run RO-Crate can make the actual run portable without replacing the internal ledger.

The Process Run profile is suitable for individual tool invocations; the Workflow Run profile is suitable when a workflow engine or orchestrator executed a defined workflow. DOR should not claim full Workflow Run conformance for a manually coordinated process unless it supplies the profile's required workflow description. For the existing manual/implicit stage execution model, Process Run semantics may be the accurate first step.

References:
- [Process Run Crate 0.6](https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/)
- [Workflow Run Crate 0.6](https://www.researchobject.org/workflow-run-crate/profiles/workflow_run_crate/)

#### W3C PROV-O — adopt as the provenance vocabulary

PROV-O provides a small reusable model:

- `prov:Entity`: a data file, dataset, canonical record, report, model, or other thing;
- `prov:Activity`: an audit, extraction, transformation, analysis, model fit, review, or packaging activity;
- `prov:Agent`: a person, software component, or organization associated with an activity.

DOR can map its existing artifacts and events to these concepts. This is a vocabulary alignment, not a reason to replace the current Run Event, Gate, or Acceptance ledgers. PROV-O records provenance relationships; it does not authenticate a declared reviewer or make a hash chain tamper-proof.

Reference: [W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/).

### 3.2 Experimental metadata and scientific entities

#### ISA — map, do not replace

The ISA Abstract Model organizes experimental metadata around Investigation, Study, and Assay. ISA-JSON serializes that model.

This overlaps usefully with DOR's research and assay context, but the concepts are not a direct substitute for the full DOR graph. DOR explicitly distinguishes:
- Study;
- System;
- Condition;
- Experiment;
- Observation;
- Comparison;
- Evidence.

DOR must also preserve the exact source locator and support observations with multiple evidence references, missingness states, and unresolved grain. An ISA bridge should therefore map the concepts that are genuinely equivalent, preserve unmatched DOR concepts as extensions/linked records, and never force an ambiguous one-to-one conversion.

References:
- [ISA Abstract Model](https://isa-specs.readthedocs.io/en/latest/isamodel.html)
- [ISA-JSON Specification](https://github.com/ISA-tools/isa-specs/blob/master/source/isajson.rst)

#### EMMO domain-battery / BattINFO — vocabulary alignment first

The EMMO Battery Domain Ontology provides battery-specific concepts and relationships. BattINFO is an operational implementation layer with JSON Schemas, a Python library, CLI, and curated mappings.

This is directly relevant to the zinc-battery domain profile. DOR should compare its System, material, cell, electrode, electrolyte, test method, measurement, and data concepts with the ontology and reuse stable identifiers/terms where they improve interoperability.

However, BattINFO documentation currently labels the tooling a prototype in active development. The safer decision is:
1. use the ontology and documentation as a semantic reference;
2. create a reviewed mapping table from DOR concepts to EMMO/BattINFO terms;
3. keep the existing DOR profile usable without BattINFO installed;
4. introduce a validator/authoring adapter only after version and migration behaviour are stable.

References:
- [BattINFO documentation](https://www.battinfo.org/docs)
- [EMMO Battery Domain Ontology](https://emmo-repo.github.io/domain-battery/)
- [BattINFO source repository](https://github.com/BIG-MAP/BattINFO)

#### Battery Data Format (BDF) 1.0 — targeted time-series adapter

BDF is a specific machine-readable battery cycler format. Version 1.0 requires test time, voltage, and current, recommends fields such as timestamp/cycle/step/ambient temperature, and supports additional capacity, energy, temperature, resistance, and related fields. The specification defines a single cell per file and a fixed SI unit convention.

DOR should support BDF only when an actual study includes raw cycler time-series files. Those files can become source artifacts and feed a derived observation/analysis path. The canonical bundle must still preserve the test protocol, cell/system identity, conditions, and the relation between time-series observations and the original file.

BDF does not solve literature-level condition extraction, image interpretation, synthesis protocols, XRD/XANES/Raman data semantics, atomistic trajectories, or the full zinc-battery metadata model.

Reference: [Battery Data Alliance — BDF Specification 1.0](https://batterydataalliance.energy/specification).

### 3.3 Units and tabular datasets

#### QUDT + UCUM — complementary, not competing

QUDT models quantity kinds, measurable quantities, units, dimensions, and systems of units. UCUM supplies machine-readable unit codes and combinations intended for unambiguous electronic communication.

DOR should preserve at least three things separately:
1. the exact raw unit string as reported by the source;
2. a normalized value and a machine-readable unit code when explicitly reviewed;
3. the semantic quantity/endpoint definition to which the value belongs.

A UCUM or QUDT mapping does not prove that two endpoints are scientifically comparable. A mathematically possible conversion is not automatically scientifically appropriate. Unit conversion remains an explicit, reviewed transformation with recorded parameters and provenance.

References:
- [QUDT](https://qudt.org/)
- [UCUM](https://ucum.org/)

#### Frictionless Data Package 2.0 / Table Schema — use for tabular resources

Frictionless Data Package describes a package of data resources; Table Schema describes the fields and constraints of tabular resources. The newer Data Package profiles support explicit version declaration through the `$schema` URL.

This is suitable for DOR's CSV artifacts (for example, normalized observations, cohort tables, and review queues) when they need portable field descriptions and independent validation. It should be a subordinate tabular description inside a larger RO-Crate, not a competing full-research-object packaging format.

References:
- [Data Package specifications](https://datapackage.org/)
- [Frictionless Data Package version handling](https://framework.frictionlessdata.io/docs/advanced/datapackage-versions.html)
- [Tabular Data Package](https://specs.frictionlessdata.io/tabular-data-package/)

### 3.4 Specialist execution and experiment tracking tools

#### DataLad — defer

DataLad can record command execution and its effects on a dataset, including input preparation, command metadata, and saved outputs. It is particularly relevant when research files become large, distributed, versioned, or shared across machines.

DOR already has an explicit Run Plan, stage event history, artifact hashes, and resume planning. Introducing DataLad now could create two overlapping authorities for data state and command provenance. Revisit only if the pilot demonstrates a concrete need for dataset versioning, large-file annexing, or reproducible command reruns beyond the current run workspace.

Reference: [DataLad provenance capture](https://docs.datalad.org/en/latest/design/provenance_capture.html).

#### MLflow — defer

MLflow Tracking already records model parameters, code versions, metrics, inputs/datasets, and artifacts, and provides a run-oriented interface for comparing model experiments.

DOR currently has a deliberately small baseline model set and its own task, endpoint, Study-split, feature, model, and evidence contracts. A new tracking server or model registry is not justified yet. If real work later involves many model families, hyperparameter searches, checkpoints, or long-running model experiments, an optional adapter can mirror DOR run metadata into MLflow while keeping DOR authoritative for scientific task identity and evidence.

Reference: [MLflow Tracking](https://mlflow.org/docs/latest/tracking/).

#### Common Workflow Language (CWL) — defer

CWL 1.2 defines portable descriptions of command-line tools and workflow DAGs. DOR's Run Plan also describes explicit stages, dependencies, inputs, outputs, executors, and optional gates, but the current Run Manager is a planning/provenance layer, not a workflow execution engine.

If DOR later needs to execute the same analysis on local Windows, Linux HPC, cloud systems, and institutional workflow platforms, a CWL export could provide portability. Do not introduce CWL or an engine now merely to make the architecture appear more complete.

Reference: [CWL v1.2 Workflow Specification](https://www.commonwl.org/v1.2/Workflow.html).

#### Battery Data Commons — discovery resource

Battery Data Commons is a curated metadata catalogue intended to make public battery datasets discoverable and comparable. It is not a raw data repository and does not perform data processing or enforce experimental standardization. It can help identify relevant public datasets or compare the metadata coverage of DOR's future outputs, but it is not a Runtime dependency.

Reference: [Battery Data Commons — About](https://batterydatacommons.org/about/).

## 4. Proposed DOR interoperability profile

The following is the target relationship, not a claim that these adapters already exist:

| DOR internal object/output | External representation |
|---|---|
| Project, Study, data files, software, analyses, findings, publication package | RO-Crate 1.3 |
| A single command/tool execution and its input/output artifacts | Workflow Run RO-Crate Process Run profile |
| A truly orchestrated computational DAG execution | Workflow Run RO-Crate Workflow Run profile |
| Source entities, transformations, generated artifacts, responsible software/people | PROV-O mapping within the crate |
| Investigation/Study/Assay metadata where equivalent | ISA / ISA-JSON bridge |
| Battery materials, cells, tests, properties, battery-specific terms | EMMO domain-battery / BattINFO mapping |
| Raw battery cycler time-series | BDF 1.0 adapter |
| Quantity kinds and dimensions | QUDT annotations |
| Machine-readable unit expressions | UCUM codes |
| CSV cohort, normalized observations, tabular review artifacts | Frictionless Data Package / Table Schema |

DOR-specific concepts such as evidence recovery state, condition-instance-to-Observation matching, unresolved scientific grain, reconciliation decisions, endpoint-specific cohort eligibility, and the distinction between predictive interaction and mechanism hypothesis should remain explicit even when mapped to external vocabularies.

## 5. Adoption order

1. **Now — no new dependency:** document mappings and stable external identifiers for concepts already present in DOR.
2. **After the real-data pilot — export:** add RO-Crate 1.3 plus appropriate PROV-O relations for the existing publication/analysis package.
3. **After the source audit — domain mapping:** align zinc-battery terms with EMMO/BattINFO and unit representations with QUDT/UCUM.
4. **When actual raw cycler files are in scope:** add BDF 1.0 ingestion as a separate adapter.
5. **Only when scale/portability requires it:** evaluate DataLad, MLflow, and CWL individually against the existing Run Manager and explicit file-based workflow.

## 6. Non-goals for this phase

- No migration of the canonical bundle to RDF/JSON-LD.
- No forced conversion of all internal schemas to ISA.
- No mandatory BattINFO, DataLad, MLflow, CWL, database, or workflow-engine dependency.
- No automatic unit conversion based only on matching strings or unit codes.
- No general-purpose PDF/OCR/image-extraction platform.
- No new provenance ledger or hash-chain implementation.

The purpose of standards alignment is to reduce DOR's maintenance burden and improve interoperability, not to increase the number of technologies in the stack.
