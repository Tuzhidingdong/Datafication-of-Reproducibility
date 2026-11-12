# Mechanism interpretation and evidence

## Purpose

Translate validated statistical interactions into scientifically testable explanations without confusing statistical patterns with physical or causal mechanisms.

## Evidence labels

Use the following evidence labels as a reporting aid, not as a universal hierarchy in which every field must progress in a fixed order:

- E0_STATISTICAL: candidate statistical association/interaction.
- E1_CROSS_STUDY: interaction is robust across independent studies or held-out studies.
- E2_DIRECT_OBSERVATION: relevant process is directly observed/measured experimentally.
- E3_THEORETICAL_SUPPORT: theory, simulation, or mechanistic calculation supports the proposed explanation.
- E4_PROSPECTIVE_VALIDATION: a targeted independent experiment or validation study tests the predicted relation.

An E2 result and E3 result may be obtained in either order. Record the evidence type rather than treating the label as proof by itself.

## Mechanism record contents

- linked interaction and finding IDs;
- exact statistical observation being explained;
- proposed process and causal diagram, if justified;
- spatial/temporal or multiscale considerations;
- supporting evidence and DOI/file/page/figure pointers;
- contradictory evidence and alternative explanations;
- relevant theoretical calculations or direct measurements;
- unresolved variables and assumptions;
- confidence/claim status;
- targeted validation experiment or analysis.

## Mechanism reasoning safeguards

- A model feature importance is not a mechanism.
- A SHAP interaction is not a causal mechanism.
- Correlation between two outcomes does not prove a causal chain.
- Plausibility is not evidence.
- A paper's nominal setpoint is not proof of a spatially uniform realized state.
- Unreported conditions must remain unreported unless separately measured or reliably inferred with explicit uncertainty.
- Report competing explanations when several mechanisms are consistent with the evidence.

## Mechanism wording

Use "the model identified a statistical interaction", "the association was stable across the evaluated studies", "the pattern is consistent with the hypothesis that...", "direct evidence supports...", or "the mechanism remains to be tested".

Reserve definitive mechanistic wording for evidence that genuinely supports it.


## Operational evidence bridge contract

The executable bridge is documented in [V0.4 Mechanism Evidence Bridge](../docs/V0.4_MECHANISM_EVIDENCE_BRIDGE.md).

The bridge does not generate hypotheses from feature IDs. A user, Agent, or Worker must supply an explicit `mechanism_plan.json` containing the proposed process chain, scope, predicted observations, alternative explanations, unresolved variables, and evidence assessments. Each assessment links a canonical `evidence_id`, a relationship (`SUPPORTS`, `CONTRADICTS`, or `CONTEXTUAL`), a declared evidence class, a concise interpretation, and Observation IDs when required.

Evidence rules:
- Only canonical Evidence with `extraction_status = VERIFIED` can contribute to verified evidence summaries.
- `DIRECT_OBSERVATION` must link to at least one canonical Observation whose `evidence_ids` contains that Evidence ID, whose `value_state = REPORTED`, and whose Study matches the Evidence Study.
- `THEORETICAL_SUPPORT` links to a verified canonical Evidence source and is not required to link to a measured Observation.
- `PROSPECTIVE_VALIDATION` must link to REPORTED Observations from a Study not represented in the selected interaction's discovery cohort. Otherwise it is retained but not counted as independent prospective support and is placed in the review queue.
- Contradictory evidence is retained with its locator, Study, and linked Observations. It is never averaged away or omitted from the mechanism record.
- Evidence classes describe the type of support and are not a universal ordinal ranking. No evidence combination automatically establishes a causal mechanism.

Every generated finding remains a candidate mechanism hypothesis until a user reviews the full package.