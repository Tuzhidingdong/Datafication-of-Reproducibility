# DOR Project Capability Audit

**Audit date:** 2026-11-12  
**Audited branch:** `v0.1-foundation`  
**Audited commit:** `6275727279f680e887cb9672652a52bbc188eae0`  
**Scope:** repository implementation, Skill, contracts, schemas, tests, and the documented workflow. No private research corpus was opened or processed for this audit.

## 1. Executive assessment

DOR is already a substantial research-methodology and deterministic-runtime prototype, not an empty framework. The repository contains 169 tracked files, including 28 Python runtime modules, 22 Python test modules, domain and workflow references, schema contracts, templates, and a provisional zinc-battery profile.

The strongest existing capabilities are:

1. Non-destructive CSV/JSON inspection and source hashing.
2. A reviewed, explicit canonical data-construction process that preserves Study/System/Experiment/Condition/Observation/Evidence distinctions.
3. Evidence-linked reconciliation that surfaces ambiguity and conflict instead of silently resolving them.
4. Endpoint-specific cohorts and Study-grouped baseline/nested evaluation.
5. Carefully bounded predictive-interaction and mechanism-evidence workflows.
6. Explicit human approval, run provenance, and publication-package contracts.

The main gap is not a lack of software modules. It is the absence of evidence that the complete workflow works correctly on a real user-selected research study. The repository's own documentation repeatedly states that the engineering fixtures are synthetic and that real-corpus scientific acceptance remains pending.

**Current overall classification:**

- **Engineering implementation:** broad and substantially developed.
- **Synthetic integration coverage:** broad, including a full synthetic CLI workflow.
- **Real scientific validation:** not demonstrated by the repository.
- **Antigravity/Worker end-to-end operation:** contracts exist; host-side execution is not implemented by the Runtime.
- **External standards interoperability:** not yet implemented; currently a design opportunity.

A passing structural validator, hash check, approval ledger, or synthetic test must not be described as proof of scientific correctness.

## 2. Capability inventory

| Capability | Existing implementation | What it actually does | Evidence status and boundary |
|---|---|---|---|
| Project and Skill entry point | `.agents/skills/datafication-of-reproducibility/SKILL.md`, project config, references | Defines the guided research method, roles, source-preservation policy, approval points, and writing hand-off | Implemented as instructions/contracts; Antigravity GUI behaviour and a complete user session have not been validated here |
| Structural source audit | `audit.py`, `inventory.py`, `structure.py` | Inspects CSV/JSON structure, row shapes, coverage/type hints, bounded JSON paths, source hashes, and unresolved inventory entries | Synthetic tests; not a semantic extraction engine or a general binary-file reader |
| Chem-Literacy adapter | `chem_literacy.py` | Imports the aggregate `papers[].observations[]` JSON or flattened observation CSV; optionally joins the reconciliation CSV only by `paper_id + reconciliation_id`; preserves repeated records and disagreements | Synthetic tests; actual zinc-battery source semantics and mapping remain unverified |
| Condition recovery | `chem_literacy.py`, zinc-battery condition-recovery profile and result/decision schemas | Uses feature-specific search terms against declared preprocessed text files, prepares bounded excerpts and Worker task packets, verifies returned source quotations, and requires human promotion | This is targeted text retrieval plus review plumbing, not native PDF/table/image extraction. It does not establish NOT_REPORTED from a failed search |
| Canonical scientific model | `canonical.py`, `schemas/canonical_bundle.schema.json`, canonical model documentation | Represents Study, System, Condition, Experiment, Observation, Comparison, and Evidence with explicit links and missingness states | Structural and referential checks are implemented; scientific entity identity and mappings still require human review |
| Mapping and construction | `mapping.py`, `builder.py`, `CANONICAL_BUILDER.md` | Binds proposed mappings to an exact inventory; builds entities using declared source selectors, grouping keys, transformations, and joins | Deterministic and conservative. No fuzzy joins, implicit normalization, arbitrary first-value choice, or automatic scientific mapping |
| Diagnostics and reconciliation | `diagnostics.py`, `reconciliation.py` | Reports possible duplicate payloads, unreferenced entities, endpoint variants, observation variation, explicit replicate/sample conflicts, and evidence-locator disagreements | Review queue only; does not decide equivalence, select values, merge observations, or alter canonical records |
| Cohort construction | `cohort.py` | Builds endpoint-specific cohorts using exact task definitions, exact units, explicit Condition links, and Study-level splits | Synthetic tests; real-world task adequacy and hidden Study dependencies remain scientific review questions |
| Baseline modelling | `modeling.py` | Provides mean/Ridge numeric baselines and majority/mixed-Naive-Bayes categorical baselines with validation-only selection and held-out test evaluation | Narrow transparent baselines, not a general model-family recommender or causal engine |
| Cross-Study evaluation | `reproducibility.py` | Performs nested Study-grouped evaluation, per-Study performance summaries, and heuristic feature-space support diagnostics | Requires at least four eligible Studies; uncertainty is explicitly NOT_CALIBRATED; not prospective validation |
| Interaction analysis | `interactions.py`, `robustness.py`, `response_surface.py` | Screens numeric pairwise predictive product terms, repeats the screen across split seeds, and produces descriptive partial-dependence surfaces with projected support diagnostics | Predictive screening only. No inferential p-values/FDR, categorical interaction support, causal interpretation, or proof of physical synergy |
| Mechanism evidence | `mechanism_bridge.py`, mechanism contracts | Packages a user-proposed hypothesis with direct, theoretical, prospective, contextual, and contradictory evidence links | Does not discover mechanisms automatically; generated findings remain candidate hypotheses pending review |
| Virtual scenario estimates | `virtual_reproduction.py` | Applies a selected, hash-verified baseline model to a fully specified condition query and flags marginal range/category warnings | Not an experiment or atomistic simulation; no calibrated uncertainty and no full joint-domain guarantee |
| Scientific approval | `gates.py` | Records G0–G4 decisions as a hash-chained ledger bound to named artifacts | Reviewer identity is self-declared provenance, not authentication or a digital signature |
| Run execution provenance | `run_manager.py` | Validates an explicit DAG, records stage attempts and artifact hashes, authorizes bounded Worker tasks, and plans conservative resume/reuse | It does not execute the DAG, dispatch Workers, supervise processes, or provide cross-machine orchestration |
| Controlled acceptance | `acceptance.py`, `acceptance_ledger.py`, `stage_contracts.py` | Validates an eight-stage V1.0 acceptance record, cross-ledger bindings, stage evidence contracts, and append-only review history | Designed for controlled real-data acceptance, but not yet demonstrated against the user's real study |
| Publication hand-off | `publication.py`, Writing Skill interface, templates | Copies only explicitly declared artifacts, creates a manifest and guide, and audits hashes/path safety/completeness | Package integrity is not scientific completeness or publication readiness |
| External Worker interface | `worker_task.schema.json`, `worker_result.schema.json`, `references/worker-contract.md` | Defines bounded, manager-neutral task/result packets and permissions | Existing external Antigravity-to-OpenCode Worker Manager is not called by the DOR Runtime |

## 3. Important implementation boundaries

### 3.1 Source extraction is not yet a complete document-ingestion engine

The generic audit currently handles CSV and JSON structure. The Chem-Literacy condition-recovery path reads declared preprocessed text files, including `main_analysis.md` and `si_analysis.md`, and can use evidence-file paths already present in the imported records. It searches bounded keyword windows and emits candidate excerpts.

The current Runtime does **not** natively parse raw PDF/DOCX files, extract PDF tables, interpret figure panels, process microscopy/spectroscopy images, or perform OCR. Those operations must be supplied by an upstream extraction process or an explicitly authorized Worker. Their outputs should preserve original source hashes and exact page/table/figure/panel/row/cell locators.

This distinction matters: DOR has condition-recovery orchestration and verification contracts, but it should not be described as having solved full multimodal literature extraction.

### 3.2 The zinc-battery domain adapter remains provisional

The domain profile labels itself `PROVISIONAL_PENDING_SOURCE_AUDIT`. The feature mapping file is still empty and explicitly pending inspection of the actual CSV/JSON. The documented condition-recovery profile covers 23 feature identifiers; `FEAT_MAEID` is intentionally left unmapped pending scientific definition.

Therefore, the presence of a zinc-battery profile is not evidence that the 24-feature corpus has been semantically mapped or accepted. Actual feature meanings, units, endpoint definitions, study identifiers, experiment grain, and Observation linkage remain to be audited against the source files.

### 3.3 Runtime validation is deliberately narrower than a general schema-validation platform

The Runtime has no third-party dependencies and uses the Python standard library. The repository contains many JSON Schemas, but several contracts explicitly state that the corresponding Runtime command performs implementation-owned reference, semantic, or integrity checks rather than invoking a general JSON Schema validation engine.

This is an acceptable lightweight design if documented consistently. The distinction should remain explicit:

- JSON Schema files define exchange/shape contracts.
- Runtime validators enforce the checks actually implemented.
- Human review determines scientific meaning and appropriateness.

Do not assume every schema constraint is automatically enforced merely because a schema file exists.

### 3.4 Run reuse is not a general cross-project cache

The Run Manager can reuse current outputs within a declared run plan when input/output hashes and dependencies remain valid. This is useful stage-level resume behaviour.

The repository does not yet implement a general content-addressed cache with reusable cross-run artifacts keyed by source hashes, configuration, code, environment, dependencies, parameters, and seed. The architecture reference describes a cache policy, and the example project config has a `cache_dir`, but that is not equivalent to a working shared artifact-cache service.

Do not build another cache until the real pilot identifies which expensive operations should be reused and across what scope.

### 3.5 The three ledgers have different purposes, but their lifecycle boundary needs to be made simpler to understand

The current architecture contains three record histories:

1. **Run Event Ledger** — what computation or stage attempt actually ran, with inputs and outputs.
2. **G0–G4 Workflow Gate Ledger** — which scientific approval decision was made for a particular artifact packet.
3. **V1.0 Acceptance Revision Ledger** — the controlled eight-stage acceptance review and final assessment history.

These are not interchangeable. Execution is not approval; a Gate approval is not proof that every acceptance stage is complete; an Acceptance record is not the execution history.

However, they create repeated stage/status/evidence references. The mapping between the eight V1.0 acceptance stages and five G0–G4 decisions must be kept explicit. The current implementation should not add a fourth ledger or more snapshot layers. Later simplification should preserve one authoritative source for each kind of fact.

### 3.6 DOR defines portable Worker contracts but does not own Worker execution

The Skill says that the Supervisor should display role, provider, model, active project, inputs, staging outputs, and constraints before dispatch. The Runtime can create an authorization packet and validate recorded completion. It does not invoke the user's external Worker Manager, verify the host process, or implement a sandbox. The host-side permission boundary remains essential.

## 4. Test and acceptance evidence

The repository has separate test modules for the audit, builder, canonical model, Chem-Literacy adapter, mapping, cohort, modelling, reproducibility, interactions, robustness, response surfaces, mechanism bridge, virtual reproduction, publication package, gates, Run Manager, Acceptance Ledger, and stage contracts. It also has a synthetic end-to-end CLI workflow.

This is meaningful engineering coverage. It demonstrates that known synthetic data contracts can be exercised across modules.

It does **not** demonstrate:

- correctness of a real paper's extracted values or locators;
- correctness of the user's zinc-battery feature mappings;
- correctness of experiment/replicate grain in the actual corpus;
- whether conditions from text, tables, figures, and SI can be reliably linked to individual Observations;
- whether real endpoint definitions are comparable across Studies;
- cross-Study predictive validity on real research data;
- physical or causal validity of an interaction/mechanism interpretation;
- Antigravity GUI behaviour or actual Worker Manager dispatch.

The latest code commits and the prior test history are not a substitute for a fresh successful test run on the audited commit. CI must be reported separately when a workflow has no assigned Runner or no test steps actually execute.

## 5. Priority gap register

| Priority | Gap | Why it matters | Recommended response |
|---|---|---|---|
| P0 | No completed real-data pilot | The central scientific workflow remains unproven | Run one carefully selected paper/SI through the existing pipeline before adding features |
| P0 | Source-to-Observation evidence linkage under real document complexity | Incorrect linkage can corrupt every downstream analysis | Audit a real case with multiple conditions, multiple observations, SI references, and source disagreements |
| P1 | Raw document and multimodal extraction boundary | Current Runtime relies on external/preprocessed text and declared evidence locators | Define a replaceable extraction-adapter contract; do not embed an OCR or PDF platform prematurely |
| P1 | Domain vocabulary and unit interoperability | Current feature map is empty and unit handling is exact-match/explicit-conversion only | Align the domain profile with BattINFO/EMMO and UCUM/QUDT after source audit |
| P1 | Three-ledger lifecycle clarity | Repeated status/evidence references raise workflow complexity | Maintain a lifecycle mapping and test only the critical transitions; do not add new ledgers |
| P1 | Standard research package export | Current publication package is DOR-specific | Add RO-Crate/PROV export after the internal evidence model is proven |
| P2 | Reusable cross-run cache | Current resume/reuse is run-local and plan-bound | Derive a content-addressed cache design from real workloads before implementation |
| P2 | Advanced model/uncertainty methods | Current models and interaction screen are deliberately narrow | Expand only when real endpoint coverage and independent Study counts justify it |
| P2 | Optional tracking/workflow integrations | DataLad, MLflow, and CWL solve adjacent concerns | Defer; evaluate against concrete scale or portability needs |

## 6. Audit conclusion

DOR already has enough implementation to conduct a tightly scoped real-data pilot. The next step is not another subsystem, database, workflow engine, ontology, or model registry.

The correct next milestone is to select one representative zinc-battery paper and SI, then test the current implementation's strongest promise: preserving scientific grain and recovering source-grounded conditions into a traceable canonical representation without fabricating or silently resolving information.

Only failures observed in that real workflow should become the next code changes.

## 7. Repository evidence reviewed

- `README.md`
- `.agents/skills/datafication-of-reproducibility/SKILL.md`
- `references/v0.1-architecture.md`, `references/core-concept.md`, `references/data-model.md`, `references/guided-workflow.md`, `references/worker-contract.md`
- `docs/V0.1_SCOPE.md` through `docs/V1.0_CONTROLLED_ACCEPTANCE.md`, plus canonical, mapping, builder, reconciliation, Chem-Literacy, Run Manager, stage-evidence, and Writing Skill interface documents
- Runtime source modules, test module inventory, schemas, templates, and the zinc-battery domain profile

This audit records repository state at the commit shown above. It is not a real-data scientific acceptance report.
