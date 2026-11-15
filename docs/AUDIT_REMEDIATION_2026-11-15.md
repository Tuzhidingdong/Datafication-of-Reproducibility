# DoR audit remediation record — 2026-11-15

## Scope and safety boundary

Changes are isolated on \`fix/audit-remediation-20261115\`, based on the audited \`feat/generic-data-adapter-interface-20261114\` line. The existing analysis engine was not rewritten. Changes to scientific logic are restricted to correctness guards for evidence lineage, explicit mapping transformations, Discovery support accounting, and non-converged model fits.

DoR remains discipline-neutral. The core Skill, Runtime, Run Plans, schemas, templates, test fixtures, and documentation contain no discipline-specific example or vocabulary introduced by this remediation. Project-specific scientific semantics remain the responsibility of external Adapters. See [Cross-disciplinary scope and Adapter boundary](CROSS_DISCIPLINARY_SCOPE.md).

## Implemented

### P0 — evidence integrity and CI baseline diagnosis

- Canonical validation now rejects direct Observation-to-Evidence links whose Evidence Study differs from the linked Experiment's Study.
- Canonical Evidence Locator validation now enforces the schema's exact locator-type enumeration, non-empty source file and locator, and a 64-character hexadecimal SHA-256.
- Added adversarial Canonical tests for cross-Study evidence and malformed locators.
- The pre-existing failed CI run and the remediation-branch CI runs were inspected. The latest inspected Job had \`runner_id=0\`, no runner name, no steps, and no downloadable logs (404). This is a pre-step Runner/startup failure, not evidence of a Python test failure. CI remains an external blocker until a Runner is assigned.

### P1 — mapping and unit integrity

- Removed \`CUSTOM\` from the core-approved Mapping transformation registry and JSON Schema. The Builder did not execute it; it now fails during mapping validation rather than after an apparently approved plan proceeds to build.
- \`UNIT_CONVERSION\` now requires an explicit source-unit inventory item, exact source and target unit labels, a numeric factor, and a supported \`normalized_value\` target.
- Mapping validation requires the source-unit item to come from the same source file, format, and exact source snapshot as the numeric value.
- Build-spec validation requires the unit source to resolve in the same entity definition/selected source records.
- Builder checks every source row's observed unit against the declared source unit, writes the target unit to \`normalized_unit\`, and retains source-unit locator provenance.
- Added negative tests for unsupported transformations, missing unit-source items, source-unit mismatch, and normalized-unit provenance.

### P1 — Canonical Discovery support semantics

- A normalized value and normalized unit are treated as a pair; an orphaned normalized value no longer silently inherits an unrelated raw unit.
- Non-reported or value-less observations do not contribute to reported-value, condition-coverage, or co-observation support.
- Target tables distinguish all linked Observation/Study counts from reported Observation/Study support counts.
- Added adversarial tests for unreported observations, value-less conditions, and normalized value/unit mismatch.

### P1 — model convergence and Cohort review

- Baseline Ridge candidates are ineligible for selection when their fit has not converged. Their validation metrics are now null, not calculated from an invalid fit.
- A failed final Ridge refit falls back to the predeclared mean baseline and records the fallback reason.
- Nested Study-group validation excludes non-converged Ridge candidates; a failed outer refit uses an explicitly labelled mean-baseline fallback.
- Interaction/additive candidate selection excludes non-converged fits; failed outer refits are reported as exclusions rather than being used to calculate gains.
- Added a manual \`cohort_review\` Run Plan stage after Cohort build and research-scope selection. Baseline, nested validation, interaction, response-surface, mechanism, independent-review, promotion, and publication stages explicitly depend on its record and validation output.
- Added a hash-bound review schema, neutral template, Runtime validator, CLI command, and adversarial tests. It checks exact Cohort/task hashes, Cohort manifest payload hashes, Observation/Study counts and IDs, Study-to-split assignments, Observation IDs in each split, all reported grain-warning codes, and the explicit human decision.
- Only \`APPROVE_MODELING\` with accepted grain, supported/not-applicable independence, and accepted split validates. The validator report is also bound to the exact review-record SHA-256, so editing the review rationale or decision after validation invalidates the saved report.
- Modelling commands require both the project-level Gate Ledger and the explicit active Run manifest. The paths are distinct in the published templates; the Runtime no longer guesses the manifest from the Gate Ledger's parent directory.

### P1/P2 — execution contract and operator instructions

- Added \`runtime/src/dor/stage_execution_contract.json\` and its schema. It binds 31 unique Stage IDs to the supported CLI/manual/Worker action and both route variants' exact executor, dependency list, inputs, outputs, Gate, and activation condition.
- Run Manager validates the supported route's execution contract during Run initialization. Added \`dor validate-execution-contract --plan <run_plan.json>\` as an explicit preflight.
- The contract is included as Runtime package data.
- The large Skill file was converted into a compact phase router. Its main file shrank from 61,613 to 5,731 characters (about 91%); the original execution detail was moved into six phase references and is loaded only for the current phase.
- Added a discipline-neutral scope clarification: the generic infrastructure is cross-disciplinary, but the current empirical Canonical graph and analysis engine are not a universal ontology or universal method. Unsupported representations must not be forced into the current model.
- Replaced the specific examples identified in the audit with neutral identifiers/wording. A scan of the affected Skill references, Canonical model document, and affected fixtures found none of the flagged discipline-specific terms.

### P2 — token accounting and CI duplication

- Added \`dor run-usage --manifest <run_manifest.json>\`. It aggregates terminal successful/failed attempts by Stage, producer kind, and provider/model; reports input, output, reasoning, cache-read, and cache-write separately; and leaves missing metrics null with explicit missing counts.
- Input-plus-output is only reported when both counters are present for every included attempt. Reasoning/cache counters are not added again. The report explicitly excludes unrecorded Supervisor/external Agent usage.
- Direct Run Manager API validation rejects booleans as token counts.
- CI no longer runs a series of test subsets followed by the entire suite. It preflights both supported Run Plans, executes the complete runtime test suite once, then parses the JSON schemas and packaged contract.
- A temporary \`fix/**\` push trigger was removed after confirming the current GitHub Actions environment fails before runner assignment; the normal pull-request trigger for the target feature branch remains.

## Static consistency checks performed

- Parsed the two Run Plan templates and machine execution contract.
- Compared the ordered Stage IDs and all bound route-specific properties. Result: no contract drift detected.
- Parsed seven related JSON schemas.
- Confirmed the CLI exposes the Cohort-review and execution-contract commands, and Run Manager invokes the execution-contract validator.
- Manually checked that the Cohort Builder's report/manifest fields match the new review validator's expected fields.
- Checked the modified generic Skill/Canonical/test files for the flagged domain-specific vocabulary.

These are static checks only. They are not tests and are not final project acceptance.

## Not verified / outstanding

1. **Python tests not run locally.** The newly added and affected tests are committed but have not been executed.
2. **GitHub Actions not verified.** The inspected Job failed before a Runner was assigned; zero steps ran and no logs were available. CI must run on a working Runner.
3. **No real research corpus, Worker, or full Run workflow was executed.** The user retains final acceptance.
4. **Discovery pair enumeration remains potentially O(n²) in unique pair memory** before the final \`maximum_pairs\` truncation. A bounded exact Top-K implementation needs a separate design so that support ranking semantics are not silently changed.
5. **Independent-review context reduction is instruction-led, not a new deterministic summary builder.** The Worker is instructed to read compact summary/status/count/warning/claim-scope fields first and expand detailed evidence only for a specific finding. A local deterministic pre-summary packet is not implemented.
6. **The pull request is not merged.** The original feature branch remains unchanged by this remediation.

## Final acceptance boundary

The final acceptance remains the user's real workflow on the intended environment. Development-side static checks, CI startup failures, and newly added tests must not be described as a successful end-to-end acceptance.
