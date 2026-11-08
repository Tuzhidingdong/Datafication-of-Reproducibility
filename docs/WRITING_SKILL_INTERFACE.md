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


## Mechanism evidence hand-off

When a run includes the V0.4 Mechanism Evidence Bridge, the Writing Skill should retrieve:

- `mechanisms/mechanism_evidence_bridge_report.json` for hypothesis scope, evidence status, contradictions, and pending review;
- `mechanisms/mechanism_evidence_ledger.csv` for exact Evidence IDs, Study/DOI, source file and locator, extraction state, Observation links, and whether the record was counted;
- `mechanisms/mechanism_review_queue.csv` for unresolved source verification, non-independent prospective labels, and contradictory evidence;
- `findings/mechanism_findings.json` for structured Research Finding records.

Every generated mechanism finding remains a candidate hypothesis until the report's `PENDING_USER_MECHANISM_REVIEW` state is resolved by an explicit human review process. Do not rewrite `mechanism_hypothesis` as an established mechanism. Direct observation, theoretical support, and prospective validation are different evidence types, not steps on an automatic confidence ladder. Contradictory evidence must remain visible in the claim map and manuscript discussion.