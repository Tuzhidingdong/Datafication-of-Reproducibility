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
- PR #4, **DOR Scientific Opportunity Engine: Study-aware discovery and evidence ledger**, remains Draft and unmerged. Do not change its state or merge it without authorization.
- PR #4 exact current head: `f361564edca7bbd68b2cda73b595e8943978f11f`.
- The real-data evidence branch `audit/real-discovery-20261118-01` is evidence-only and descends from that head at commit `15cf1b41c2ab3420f6cb3c64f862b3d31c8a652b`. Do not use it as a production-code branch.
- The current development branch for the existing-data scientific-mining increment is `feat/existing-data-scientific-mining`, created from the PR #4 head above.
- First implementation target: formally represent and preserve multiple candidate values attached to an existing Condition or Observation, inventory candidate disagreement/missingness/evidence coverage, and evaluate candidate-source alternatives as clearly separated sensitivity scenarios using the existing Study-aware Runtime. The primary discovery path and its inferential denominator must remain unchanged.
- Do not re-run the user's real Discovery automatically. Local real-data testing is a separate Agent hand-off after the GitHub implementation is committed.

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
