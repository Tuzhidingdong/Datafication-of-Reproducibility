# External Semantic Registry

## Purpose and boundary

The Semantic Registry is an independently versioned data asset for reviewed meanings attached to exact Canonical Target, endpoint/timepoint, and Condition identifiers. It does not replace the Canonical Bundle, change its bytes, infer meanings from labels, or decide whether a scientific relationship is causal. `dor init-run-plan` creates `configuration/semantic_registry.json` from the empty template when absent, preserves and validates an existing file, and binds it into every formal Run as a protected source artifact. Populate/review it before `dor run-init`; an empty registry is valid and explicitly records that no semantic metadata was supplied.

Keep this file outside production Skills. Do not put concrete study data, project-specific IDs, experimental values, or paper examples into Skill instructions. A project-specific registry is the correct place to store reviewed project semantics; synthetic examples belong only in test fixtures.

## Record contract

Each record binds an exact Canonical identity and optional measurement scope:

- `TARGET` matches `observations[].target_id` across all endpoint/timepoint contexts.
- `TARGET_ENDPOINT` matches the exact tuple `observations[].target_id`, `endpoint_definition`, and `timepoint`; both context fields are required and preserve their JSON value types.
- `CONDITION` matches `conditions[].condition_type`.

A `TARGET_ENDPOINT` definition overrides the matching fields from a broader `TARGET` definition for that exact scope. It does not leak into other endpoints or timepoints. The Runtime does not normalize identifier case, punctuation, whitespace, endpoint labels, or timepoint types.

Identifiers are matched exactly. Case, punctuation, and whitespace are not normalized. A registry entry that matches no Canonical record is an error. Duplicate entries for the same entity type and identifier are rejected.

Semantic metadata may declare a concept identifier, display name, definition, measurement basis/context, derivation type and exact `derived_from` identifiers. Only consistently supplied metadata with `review_status=APPROVED` can support the existing conservative semantic self-association rules. Matching concepts without a shared, non-empty measurement context remain unresolved. A declared derivation is only considered where `derivation_type=CALCULATED` and the dependency is explicit.

An APPROVED record must include reviewer, review timestamp, rationale, and at least one hash-bound source reference. A source reference contains a stable source ID, SHA-256, and opaque locator. The Runtime does not open, parse, or dereference the source. It verifies the shape and hash syntax only; the human reviewer remains responsible for the provenance decision.

## Validate and use

Validate the independent asset before use:

    dor validate-semantic-registry --registry <semantic_registry.json>

Use it for a standalone exploratory scan:

    dor discover-opportunities --bundle <canonical_bundle.json> --semantic-registry <semantic_registry.json> --out-dir <new_discovery_directory>

The same registry is consumed automatically by the formal Run's `exploratory_discovery` stage through its hash-protected `semantic_registry` source artifact; the Run Plan does not need manual editing. Once `dor run-init` has captured its hash, do not change the file in place. A changed registry is a changed scientific input and requires a new Run.

The Runtime overlays the metadata onto an in-memory copy for the analysis, hashes the registry before and after the run, and records its ID, hash, global Target/endpoint-scoped Target/Condition counts, and application status in the Discovery manifest/report. It does not write metadata back to the Canonical Bundle. If an entry conflicts with inline Canonical metadata, matches no Canonical attribute, or fails validation, the scan stops rather than guessing.

An empty registry, or missing entries for some attributes, does not establish that semantic relationships are absent. Missing, partial, conflicting, or unapproved semantics remain flagged for domain review and are never interpreted as evidence that no semantic relationship exists.
