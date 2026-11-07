# Writing Skill interface

This document defines the hand-off contract from Datafication-of-Reproducibility to a separate manuscript-writing Skill.

## Required entry files

Every publication package must contain:
- README_FOR_WRITING_SKILL.md
- package_manifest.json

The Writing Skill reads the guide first and the manifest second. It does not infer file locations from naming conventions when the manifest provides an exact path.

## Required manifest behavior

The manifest lists each generated artifact with:
- stable artifact ID;
- package-relative path;
- artifact type;
- description;
- status;
- SHA-256;
- linked record IDs;
- intended manuscript sections.

Only actual generated files are listed as complete. Missing outputs are represented with a status and explanation, not fabricated placeholder data.

## Claim traceability

The Writing Skill should create a claim map:

| Claim ID | Manuscript section | Claim | Finding/model/interaction ID | Figure/table ID | Source evidence |
|---|---|---|---|---|---|

Every quantitative claim and mechanistic statement should map to the corresponding scientific record and, where applicable, original DOI/page/figure/table evidence.

## Stable interface

The file paths and schema version are part of the interface. Breaking changes require a schema-version increment and migration note. Additional files may be added compatibly when the manifest is updated.

## No source-code dependency

The downstream Writing Skill must not need to inspect the Python implementation, model source, or old Agent conversations to retrieve executed scientific facts.
