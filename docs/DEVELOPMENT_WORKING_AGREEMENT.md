# DoR Development Working Agreement

**Status:** Normative project instruction  
**Applies to:** Every DoR development, debugging, research-mining, and local-acceptance session  
**Last updated:** 2026-11-18

This file is the repository's persistent working memory for project goals, role ownership, and the development/test hand-off. Every contributor or AI developer must read it before proposing work, modifying code, directing an Agent, or interpreting a local test.

## 1. Product objective — mine scientific value from imperfect existing data

DoR exists to discover scientific value in the structured research data that already exists, including data that are sparse, incomplete, heterogeneous, noisy, partially extracted, inconsistently normalized, or internally conflicting.

DoR must help surface:
- recurring relationships and trends that are visible in different subsets of the corpus;
- condition/outcome associations and potentially informative co-variation;
- candidate interactions and higher-order combinations when support permits;
- cross-Study consistency, heterogeneity, counterexamples, boundary conditions, and anomalies;
- informative missingness and extraction/reporting patterns;
- hypotheses and follow-up tests that are grounded in the available evidence.

**Do not make a clean, complete, rectangular, machine-learning-ready dataset a prerequisite for discovery.** Requiring the user to fill missing cells, resolve every conflict, standardize every unit, or manually curate a model-ready table defeats DoR's purpose. These imperfections are analysis inputs and must be represented, profiled, and exploited with appropriate uncertainty handling.

The preferred progression is:
1. preserve every existing reported value, candidate value, source quote, locator, unit, review state, and missingness state;
2. analyse the information that is available for each feature pair or scientific question, rather than imposing one global complete-case subset;
3. distinguish primary reported values from unresolved candidate alternatives;
4. run bounded, deterministic sensitivity analyses across candidate-source alternatives without treating alternatives as additional independent observations;
5. use Study-aware aggregation and inference; never inflate sample size by counting rows, candidates, systems, or repeated measurements as independent Studies;
6. report patterns, effect sizes, support, uncertainty, counterevidence, confounding, and limits in scientific language;
7. reserve human review for semantic interpretation and scientific decisions, not routine data cleaning that the Runtime can preserve and analyse.

A structural PASS, a statistically significant p/q value, a large row count, or a synthetic test is not by itself a scientific discovery. Scientific usefulness must be assessed from the actual patterns, the evidence chain, independent support, counterexamples, and plausible alternative explanations.

## 2. Fixed role ownership

### ChatGPT / repository developer
ChatGPT is the **developer and code owner for this collaboration**. It must work directly in the GitHub repository:
- inspect the current repository state, this agreement, active branches/PRs, and relevant code before every development session;
- design and implement reusable architecture, Runtime code, schemas, Skills, tests, and developer documentation;
- run or trigger the available repository-level engineering checks and inspect their actual results;
- commit changes to a dedicated development branch and open/update a Draft PR for review;
- prepare a precise local-test hand-off only after the GitHub implementation is available;
- interpret local Agent feedback, then make code corrections in GitHub.

Do not delegate the primary implementation to the user's local Agent. Do not ask the user to develop, patch, clean, reconcile, or reformat data as a substitute for implementation.

### Local Agent
The local Agent is the **synchronization and acceptance-test executor**, not the primary developer:
- sync the exact branch/commit identified by ChatGPT;
- use the user's existing local data and configuration read-only unless a test explicitly requires a separate derived output directory;
- run the bounded acceptance workflow and provide exact commands, commit hash, input before/after hashes, output inventory, logs, and observed scientific results;
- report bugs and surprising scientific behaviour to ChatGPT.

The Agent must not independently redesign the feature, change the GitHub implementation, rewrite Skills, or silently modify source datasets. Any separate local patch requires an explicit, separate request.

### User
The user sets scientific goals, provides existing project context, judges scientific relevance, and performs final real-workflow acceptance. The user is not the implementation worker and should not be burdened with preparing idealized data for DoR.

## 3. Session-start memory protocol

At the beginning of every DoR-related session, before acting:
1. read this file in full;
2. read the current README and the relevant Runtime/Skill/specification files;
3. inspect the current GitHub default branch, relevant development branch heads, open PRs and their base/head relationships;
4. inspect the latest CI result for the exact commit under discussion;
5. distinguish merged baseline, unmerged Draft PR work, evidence-only branches, and new development work.

This file is the durable project agreement, not a substitute for inspecting the current repository state. Update it through GitHub when the user changes a durable project decision or role boundary. Never assume conversational memory is more authoritative than the latest repository instruction.

## 4. Development and hand-off protocol

1. Make changes in a new, purpose-specific feature branch based on the explicitly inspected baseline.
2. Keep the user's existing local repositories, original datasets, Canonical Bundles, other branches, and open PRs untouched unless specifically authorized.
3. Preserve unmerged PRs as unmerged. Never merge, undraft, retarget, force-push, or overwrite another branch without explicit authorization.
4. Keep test datasets and test-specific scientific values, feature IDs, paper details, and domain assumptions out of production Skills and reusable core instructions. Use synthetic fixtures or separately maintained external project assets.
5. Test the actual behaviour changed. Avoid broad, repetitive diagnostics that consume tokens without testing the scientific capability.
6. After GitHub development and CI, provide the Agent an exact branch and commit to sync. State what the test should prove and what it must not change.
7. The Agent's test is local acceptance evidence, not a request for the Agent to take over development. ChatGPT remains responsible for interpreting and fixing failures in GitHub.
8. Do not declare real-data acceptance from synthetic tests or GitHub CI. Do not claim local tests ran unless their actual output has been returned.

## 5. Scientific-data handling invariants

- Existing inputs are the primary research asset. No user supplementation or manual cleanup is a prerequisite for exploratory mining.
- Keep source files immutable; write derived outputs to a separate run directory.
- Preserve multiple extraction candidates, disagreements, quotes, source locators, units, and review states as separate evidence-bearing records.
- Never silently average, choose the first value, infer a unit, or promote an unresolved candidate to reported truth.
- Candidate alternatives may be explored in separately labelled sensitivity scenarios. They must never be counted as extra observations or independent Studies.
- Keep the canonical/primary result separate from candidate-derived sensitivity results. Do not silently mix their p/q values, effects, or denominators.
- Use pairwise-available or question-specific subsets where scientifically justified; do not force every analysis to use the same complete-case corpus.
- Missingness is not scientific absence. Profile it as a possible property of extraction, reporting, experimental design, or source coverage.
- Do not open or interpret original papers/SI within the DoR core workflow. The existing structured evidence, quotes, locators, and metadata may be analysed under the immutable structured-data-only boundary. Source locators remain opaque unless an independently authorized external workflow handles them.
- Do not use the user's domain/test corpus as a source of production Skill instructions, hardcoded mappings, or embedded domain knowledge.

## 6. Current hand-off state (2026-11-18)

- Repository: `Tuzhidingdong/Datafication-of-Reproducibility`.
- PR #4, **DOR Scientific Opportunity Engine: Study-aware Discovery and evidence ledger**, remains Draft and unmerged. Do not change its state or merge it without authorization.
- PR #4 baseline head remains `f361564edca7bbd68b2cda73b595e8943978f11f`; the evidence-only branch `audit/real-discovery-20261118-01` must not be used as a production-code branch.
- PR #5, **DoR: mine candidate values from existing imperfect structured data**, remains Draft, open, unmerged, and stacked on PR #4. Its exact head is `5f6ca5c229acd77a6ca8784dc8f0a5ce7938279f`. Do not merge, undraft, retarget, or modify PR #5 without explicit authorization.
- PR #5 exact-head CI run [44284961751](https://github.com/Tuzhidingdong/Datafication-of-Reproducibility/actions/runs/44284961751) completed successfully. The workflow reports 546 Runtime tests passed, 1 skipped, schema/contract checks passed, and structured-data application smoke checks passed.
- **Real-data candidate-mining acceptance for PR #5 is complete.** The Local Agent used the exact PR #5 commit in a separate clean detached worktree; original source CSV/JSON/Canonical Bundle hashes were unchanged; the enhanced Bundle retained all original Study/System/Experiment/Observation identities and primary fields with zero differences. Primary Discovery artifacts and scientific fields remained unchanged; only the input-bundle hash differed in the opportunity JSON. Worker A/B candidates, source metadata, quotes and locators were retained and analysed in separately labelled sensitivity scenarios. The test did not produce a new FDR-screen-positive candidate that was independently supported as a new finding; some low-support signals were source-sensitive. This validates the provenance-preserving candidate-mining engineering path, not a new scientific mechanism.
- Local real-data outputs remain in the user's separate run directory `E:\Zinc_batters_datas\chem-literacy\runs\candidate-mining-realdata-20261118`. No source files, production mapping, Skills, gates, Workers, models, or BAT workflows were changed by that test. Do not upload the corpus or row-level research evidence to the repository.
- The next engineering increment is in the separate Draft PR #6 branch `feat/candidate-conflict-reconciliation`, based on PR #5's exact head. It adds pairwise diagnostics for value equality, exact unit labels, explicitly approved unit conversions, incompatible dimensions, unresolved units, and the limits of parent semantic metadata. It must not modify primary Discovery/FDR or candidate-source sensitivity behavior. Pairwise quotes/locators stay in the row-level artifact; only aggregate status counts may enter Scope Agent context.
- Local Agent acceptance for PR #6 must sync its exact latest commit into a new isolated worktree and re-run the existing structured dataset with a new output directory. Original source inputs, prior Discovery outputs and the PR #5 test package remain read-only. The test must verify primary outputs remain byte-identical, no candidate is promoted/averaged/selected, only explicitly approved units are converted diagnostically, and row-level candidate evidence is not included in Scope Agent inputs.
- ChatGPT remains responsible for all GitHub implementation, review, CI, and fixes. The Local Agent only syncs exact commits and executes read-only local acceptance.


## 7. Definition of done for scientific-mining increments

A change is not done merely because the code runs. Its implementation and tests must show:
- the original input bundle is byte-identical before and after;
- existing reported-value analysis remains unchanged when candidate fields are absent;
- candidate values remain traceable to candidate source and opaque source locators;
- multiple conflicting values are preserved and never silently resolved;
- a candidate-source scenario never adds candidate records as independent samples;
- candidate-derived results are explicitly marked as sensitivity-only and remain separate from primary results;
- Studies, Systems, Experiments, Observations, and candidate alternatives are counted in distinct units;
- missingness, unit coverage, candidate coverage, and evidence coverage are visible;
- test fixtures contain no user/test-corpus-specific scientific content;
- repository CI passes on the exact commit before local Agent acceptance is requested.
