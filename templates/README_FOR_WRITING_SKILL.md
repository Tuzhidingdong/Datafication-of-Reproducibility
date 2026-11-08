# Guide for the downstream Writing Skill

## Mandatory first step

Before drafting any manuscript text, read these two files in this order:

1. README_FOR_WRITING_SKILL.md (this guide).
2. package_manifest.json (the machine-readable navigation index).

Do not scan the entire package. Use the manifest to locate only the artifacts needed for the requested manuscript section.

## Source-of-truth hierarchy

When sources disagree, use this order and report the conflict:

1. Structured scientific records and executed analysis artifacts.
2. Verified source evidence and provenance records.
3. Generated Methods/Results narrative drafts.
4. Planning notes and exploratory outputs.

Never use source code or old chat history as the authority for an executed parameter or numerical result.

## Where to look

| Writing task | Read these package locations |
|---|---|
| Dataset description and sample selection | data/, methods/data_processing.md, results/dataset_characteristics.md, supporting_information/ |
| Feature definitions and units | data/data_dictionary.csv, feature mapping and endpoint definitions |
| Methods: preprocessing | methods/data_processing.md, preprocessing configuration, exclusion log |
| Methods: machine learning | methods/machine_learning.md, model cards, hyperparameters, split definitions |
| Methods: interaction analysis | methods/interaction_analysis.md, interaction method records |
| Results: model performance | results/prediction_performance.md, model metrics, predictions, validation records |
| Results: virtual condition estimates | the exact virtual prediction report path in package_manifest.json; preserve prediction_status, marginal support warnings, and NOT_CALIBRATED |
| Results: interaction discoveries | results/interaction_discovery.md, interaction records and robustness outputs |
| Discussion: mechanisms | mechanisms/mechanism_evidence_bridge_report.json, mechanisms/mechanism_evidence_ledger.csv, mechanisms/mechanism_review_queue.csv, findings/mechanism_findings.json |
| Figures and captions | figures/figure_manifest.json, figure files, source data, plotting configuration |
| Tables | tables/, table manifest and source data |
| Supporting Information | supporting_information/ |
| Limitations | limitations/, validation reports, applicability-domain records |
| Claim verification | findings/, evidence links, source DOI/page/figure pointers |

Paths above are logical conventions. The exact paths for this run are given in package_manifest.json.

## Writing constraints

- Use only numbers and claims present in the structured records or verified evidence.
- Preserve units, qualifiers, denominators, endpoint definitions, and significant figures.
- Do not call a candidate statistical interaction a mechanism.
- Keep generated mechanism findings at hypothesis/candidate status while the bridge report says `PENDING_USER_MECHANISM_REVIEW`. Do not promote them to established mechanisms without a separate explicit human review record.
- Preserve contradictory source evidence and non-independent prospective evidence exactly as reported in the mechanism evidence ledger and review queue.
- Do not imply causal relationships from observational associations alone.
- Distinguish reported experimental setpoints from measured local/realized states.
- Do not convert unreported conditions into assumed defaults.
- Do not invent references or model parameters, sample counts, conditions, or results.
- If an essential item is missing or ambiguous, add an explicit author query rather than guessing.
- Every manuscript claim should be traceable to one or more finding IDs, model IDs, figure/table IDs, or original-source evidence pointers.

## Paper section workflow

### Methods

Use executed records, not generic descriptions. Extract actual cohort definitions, data processing, transformations, software/library versions, hyperparameters, random seeds, data splits, group IDs, metrics, interaction statistics, and uncertainty procedures.

### Results

Use the final analysis outputs. State the number of independent studies and systems only as recorded. Report test-set performance separately from training and cross-validation performance. Describe interactions with their supported data range, DOI coverage, uncertainty, and robustness.

### Discussion

Separate the observed statistical result from the proposed scientific explanation. Include contradictory evidence, alternative explanations, limitations, and the current mechanism evidence status.

### Figures and tables

Use the supplied source data and plotting configuration. Do not digitize or manually re-create values when exact generated source data exists. Preserve figure/table IDs so claims remain traceable.

## Package completeness

Check package_manifest.json for artifact status. partial, not_generated, not_applicable, and requires_review must not be represented as completed results. If the package is incomplete, tell the author what is missing before drafting claims that depend on it.

## Output expected from the Writing Skill

When drafting, maintain a claim-to-evidence map containing:
- manuscript section and paragraph;
- claim text;
- supporting finding/model/interaction IDs;
- figure/table IDs;
- original DOI and evidence pointers;
- any author query or unresolved limitation.


## Package integrity and virtual prediction boundaries

When a package_integrity_report.json is supplied outside the package, inspect it before relying on copied files. A valid integrity audit verifies package consistency only; it does not certify scientific completeness.

A virtual condition result is a model-based scenario estimate, not an experimental observation. Preserve its exact endpoint, units, prediction_status, NOT_CALIBRATED uncertainty status, and warnings. Marginal training ranges do not prove joint support. Never convert a scenario prediction into a measured result or a causal/mechanistic claim.
