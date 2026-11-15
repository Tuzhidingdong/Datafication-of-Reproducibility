# External data adapter contract

## Immutable cross-disciplinary boundary

DoR core is a cross-disciplinary Skill and Runtime. Its schemas, examples, Run Plans, fixtures, and documentation may define only general data-integrity, provenance, workflow, validation, and review contracts. They must not contain discipline-specific scientific knowledge, terminology, entity taxonomies, field names, dataset examples, or research assumptions.

Domain-specific retrieval, vocabulary, parsing, normalization, mappings, and project assumptions belong in independently maintained external adapters and user-owned project configuration. An adapter may produce a package that satisfies this generic contract, but it must not cause domain-specific logic to be copied into DoR core. This is a hard architectural boundary, not an optional convention.

## Purpose

DoR is a cross-disciplinary Skill. The Runtime must not contain built-in assumptions about a research subject, discipline, material, protocol, target vocabulary, or source-system field names.

An external adapter prepares a handoff package from already structured source-system outputs, declared metadata, and project-owned configuration. Adapter code, domain vocabularies, semantic mappings, and discipline-specific retrieval rules remain outside the DoR core repository. Reading and extracting original research literature is an upstream datafication activity, not a DoR stage or a DoR adapter-handoff operation.

DoR validates the package boundary and then uses its existing general-purpose audit, mapping, canonical construction, reconciliation, cohort, modelling, validation, and publication capabilities.

## Structured-data-only boundary

DoR operates on structured datasets (CSV/JSON), supplied data dictionaries/configuration, structured evidence indexes, and validated Canonical Bundles. Original papers, SI, images, and other raw research documents may be listed as immutable provenance sources, but DoR must not open, parse, render, OCR, index, search, summarize, embed, or pass their contents to any LLM/Worker. For such source assets, DoR may check path existence, filesystem metadata, and compute SHA-256 from the byte stream only. A hash check is not a content review or extraction-quality verification. Source locators supplied in structured data are opaque metadata and must not be dereferenced. If required information is absent from the structured handoff, DoR records the gap and requests an upstream structured-data correction; it must not read the original to fill it.

An adapter package may retain original source files or references for provenance, but only its declared structured artifacts are analysis inputs. Literature extraction, OCR, table/figure reading, and semantic extraction must occur outside DoR before the handoff and must be represented in the supplied structured data/evidence metadata. DoR does not independently certify that upstream extraction faithfully matches the source document.

## Package layout

An adapter package contains an adapter_manifest.json, the declared output artifacts, and optionally copies of source inputs. The manifest conforms to schemas/adapter_package.schema.json.

- sources records each input path, format, and exact SHA-256. Absolute source paths are allowed; relative paths resolve from the package root and must remain inside it.
- artifacts records each output artifact using a package-relative path, role, format, and exact SHA-256.
- adapter.adapter_id and adapter.adapter_version identify the external adapter implementation.
- metadata is optional descriptive metadata. It must not be used as a substitute for explicit mappings or review decisions.

Supported artifact roles are standardized_dataset, discovery_dataset, source_inventory, mapping_plan, build_spec, canonical_bundle, domain_profile, evidence_index, and auxiliary. These are handoff labels, not semantic interpretations.

## Current format support

The package validator can verify hashes for all declared formats in the manifest. The current structural source audit and canonical builder directly parse CSV and JSON. For other or proprietary formats, an external adapter must create a structured CSV/JSON handoff suitable for the declared mapping and entity-grain review. Preserve each original source file as an immutable provenance asset and retain the exact source hash plus the upstream-supplied page, record, object, row, cell, or other stable locator in the evidence/provenance records. DoR validates the presence and structural binding of these locator values only; it does not open the original source to verify their content.

DoR does not parse arbitrary binary documents, images, papers, SI, instrument files, or domain-specific formats. Any required upstream conversion must be completed before the DoR Run and delivered as explicit structured CSV/JSON or a valid Canonical Bundle. DoR must not invoke converters, OCR, PDF/table/figure extraction, or document-reading routines as a Run stage. Upstream preparation must not discard source records or silently infer semantic mappings.

## Validation

Prepare the DoR routing handoff:

    dor prepare-adapter-handoff --manifest path/to/adapter_manifest.json --package-root path/to/package --out path/to/derived/adapter_handoff.json

The command validates manifest structure, duplicate identifiers, package-relative artifact paths, file availability, and exact source/artifact SHA-256 values. It also selects one of two generic routes:

- STRUCTURED_DATASET: one or more `standardized_dataset` artifacts in CSV or JSON format. DoR's structural audit processes all declared supported datasets and preserves each artifact ID and package-relative path.
- CANONICAL_BUNDLE: exactly one JSON `canonical_bundle` artifact. DoR runs its canonical structural/reference validator and Discovery can consume the bundle directly through `--adapter-handoff`.

The handoff is read-only and does not parse unsupported source formats. An external adapter must convert other source formats into an explicit CSV/JSON handoff or a valid Canonical Bundle. DoR rechecks the manifest and all declared source/artifact hashes whenever it consumes a handoff.

A passing handoff confirms delivery integrity and, for a Canonical Bundle, structural/reference validity only. It does not approve upstream extraction fidelity, source-content correspondence, entity grain, scientific semantics, mappings, unit compatibility, or suitability for any analysis.

For a formal Run using a prebuilt Canonical Bundle, create the package snapshot alongside the handoff:

    dor prepare-adapter-handoff --manifest path/to/adapter_manifest.json --package-root path/to/package --out path/to/run/00_adapter/adapter_handoff.json --dataset-manifest-out path/to/run/00_adapter/dataset_manifest.json

Materialize the four generic provenance artifacts into the Run workspace:

    dor materialize-adapter-artifacts --adapter-handoff path/to/run/00_adapter/adapter_handoff.json --role source_inventory --role mapping_plan --role build_spec --role canonical_bundle --out-dir path/to/run/00_adapter/materialized

Role-based materialization requires exactly one artifact for each requested role. It preserves each external artifact ID in the materialization manifest, copies the file without transforming it, and verifies source and copied-file hashes. When a `source_inventory` is materialized, DoR also checks every inventory item's `source_file`, `source_sha256`, and `source_format` against an exact source or artifact declared by the Adapter Manifest. Source references must use the declared package-relative path (or the exact absolute path for an external source). An undeclared path, mismatched hash, or mismatched format blocks materialization. The resulting filenames use the generic role names with JSON extensions for the canonical workflow roles.

Use `templates/run_plan.canonical_adapter.example.json` for this route. The package must provide exactly one artifact for each of `source_inventory`, `mapping_plan`, `build_spec`, and `canonical_bundle`. After G0 approval, DoR re-runs mapping validation and Build Spec validation against the supplied mapping plan, inventory, and build specification. G1 approval binds the exact mapping plan, both validation reports, inventory, and build specification. The G2 gate then verifies that the supplied Canonical Bundle's build-provenance hashes match those exact G1-approved artifacts. A prebuilt bundle therefore cannot bypass G0, G1, or G2.

## Handoff to existing DoR stages

The adapter package is a boundary, not a replacement for DoR's scientific workflow.

1. Register the adapter manifest and its package root as protected source inputs in the Run Plan.
2. Run `dor prepare-adapter-handoff` in the adapter validation stage. The generated `adapter_handoff.json` is the single routing artifact consumed by subsequent stages.
3. For a STRUCTURED_DATASET route, run `dor audit --adapter-handoff <adapter_handoff.json> --out <new_audit_directory>`. This parses and audits only the declared standardized CSV/JSON artifacts in one pass. Original-document sources are recorded as provenance assets and are not content-audited. Review the resulting structured-data inventory before defining mappings.
4. For a CANONICAL_BUNDLE route, use `dor discover-opportunities --adapter-handoff <adapter_handoff.json>` for optional pre-Run exploration. This does not authorize formal analysis.
5. For formal analysis of a prebuilt Canonical Bundle, require the package to provide `source_inventory`, `mapping_plan`, `build_spec`, and `canonical_bundle`; use the canonical-adapter Run Plan template and materialize these artifacts into the Run workspace by generic role.
6. Follow the existing G0 and G1 approval gates. Revalidate the supplied mapping plan against the exact source inventory, bind the supplied build specification, and verify the Canonical Bundle's provenance before G2. Do not rebuild, merge, or automatically revise the supplied records.
7. For a STRUCTURED_DATASET route, prepare and review the mapping plan and canonical build specification against the exact source inventory. DoR does not infer scientific meanings from labels or filenames or from original-document contents. Build and validate the Canonical Bundle only after G1 approval.
8. Reconcile unresolved records without automatic selection, merging, or averaging. Run exploratory profiling on the validated Canonical Bundle, then continue through user scope selection, G2, endpoint-specific cohorts, and the existing approval-gated analysis stages. Exploratory results remain candidates and do not approve a formal task or gate.

An adapter may provide a prebuilt canonical bundle only when its entity identities, relationships, provenance, and mappings are explicitly represented. DoR validates structural/reference integrity and preserves external source and adapter hashes; this validation is not a semantic or scientific approval.

## Separation rules

- Adapters are independently versioned and replaceable.
- Domain profiles are supplied by the project using DoR; none is bundled as a default.
- Project-specific settings belong in the project workspace, not in the DoR Skill or Runtime.
- DoR schemas define structure and traceability, not the scientific meaning of fields.
- No adapter output is automatically promoted to an accepted scientific result.
