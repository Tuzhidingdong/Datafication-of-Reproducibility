# External data adapter contract

## Purpose

DoR is a cross-disciplinary Skill. The Runtime must not contain built-in assumptions about a research subject, discipline, material, protocol, target vocabulary, or source-system field names.

An external adapter is responsible for reading a source system and preparing a handoff package. Adapter code, domain vocabularies, semantic mappings, and discipline-specific retrieval rules remain outside the DoR core repository.

DoR validates the package boundary and then uses its existing general-purpose audit, mapping, canonical construction, reconciliation, cohort, modelling, validation, and publication capabilities.

## Package layout

An adapter package contains an adapter_manifest.json, the declared output artifacts, and optionally copies of source inputs. The manifest conforms to schemas/adapter_package.schema.json.

- sources records each input path, format, and exact SHA-256. Absolute source paths are allowed; relative paths resolve from the package root and must remain inside it.
- artifacts records each output artifact using a package-relative path, role, format, and exact SHA-256.
- adapter.adapter_id and adapter.adapter_version identify the external adapter implementation.
- metadata is optional descriptive metadata. It must not be used as a substitute for explicit mappings or review decisions.

Supported artifact roles are standardized_dataset, discovery_dataset, source_inventory, mapping_plan, build_spec, canonical_bundle, domain_profile, evidence_index, and auxiliary. These are handoff labels, not semantic interpretations.

## Current format support

The package validator can verify hashes for all declared formats in the manifest. The current structural source audit and canonical builder directly parse CSV and JSON. For other or proprietary formats, an external adapter must create a structured CSV/JSON handoff suitable for the declared mapping and entity-grain review. Preserve each original source file as an immutable package source and retain the exact source hash plus page, record, object, row, cell, or other stable locator in the evidence/provenance records.

DoR does not claim to parse arbitrary binary documents, images, instrument files, or domain-specific formats. Those conversions and their quality checks belong to the external adapter. The adapter must not discard source records or silently infer semantic mappings while converting formats.

## Validation

Run:

    dor validate-adapter-package --manifest path/to/adapter_manifest.json --package-root path/to/package --out path/to/reports/adapter_validation.json

The validator checks manifest structure, duplicate identifiers, path containment for package artifacts, file availability, and exact source/artifact SHA-256 values. Validation is read-only. It rejects artifact paths that escape the package root.

A passing report confirms delivery integrity only. It does not approve the adapter's extraction, entity grain, scientific semantics, unit compatibility, mappings, or suitability for any analysis.

## Handoff to existing DoR stages

The adapter package is a boundary, not a replacement for DoR's scientific workflow.

1. Register the adapter manifest, source files, and package outputs as explicit source artifacts in the Run Plan.
2. Validate the package and retain its exact validation report and manifest hash.
3. Run the general structural audit on the source or standardized dataset artifacts selected for inspection.
4. Prepare and review the mapping plan and canonical build specification against the exact source inventory. DoR does not infer scientific meanings from labels or filenames.
5. Build and validate the canonical bundle; reconcile unresolved records without automatic selection, merging, or averaging.
6. Build endpoint-specific cohorts and continue through the existing approval-gated analysis stages.
7. Use the same canonical bundle as the common data boundary for exploratory profiling and formal analysis. Exploratory results remain candidates and do not approve a formal task or gate.

An adapter may provide a prebuilt canonical bundle only when its entity identities, relationships, provenance, and mappings are explicitly represented. DoR must still validate it and preserve the external source and adapter hashes.

## Separation rules

- Adapters are independently versioned and replaceable.
- Domain profiles are supplied by the project using DoR; none is bundled as a default.
- Project-specific settings belong in the project workspace, not in the DoR Skill or Runtime.
- DoR schemas define structure and traceability, not the scientific meaning of fields.
- No adapter output is automatically promoted to an accepted scientific result.
