# Read-only data audit

- Audit ID: AUDIT_20261118T071229_170966Z
- Created (UTC): 2026-11-18T07:12:29.172125+00:00
- Scope: read-only structural inspection; no semantic mapping or imputation.

## Sources

### consolidated_zinc_battery_database.csv
- Format: csv
- Size: 32123467 bytes
- SHA-256: 232d7f44f853ca9488a6a118b2b0ccd5d7f76e29a0d96a5f40dbcabd3a64a0a5
- Rows: 66405
- Columns: 27
- Short rows: 0
- Long rows: 0

| Column | Non-empty | Blank/missing | Coverage | Sampled type hint |
|---|---:|---:|---:|---|
| paper_id | 66405 | 0 | 1.0000 | string_or_mixed |
| doi | 66187 | 218 | 0.9967 | string_or_mixed |
| title | 66187 | 218 | 0.9967 | string_or_mixed |
| batch_id | 66405 | 0 | 1.0000 | string_or_mixed |
| reconciliation_id | 66405 | 0 | 1.0000 | string_or_mixed |
| feature_id | 66405 | 0 | 1.0000 | string_or_mixed |
| target_system | 66405 | 0 | 1.0000 | string_or_mixed |
| status | 66405 | 0 | 1.0000 | string_or_mixed |
| resolved_value | 7102 | 59303 | 0.1069 | numeric |
| resolved_unit | 8969 | 57436 | 0.1351 | string_or_mixed |
| worker_a_value | 40045 | 26360 | 0.6030 | numeric |
| worker_a_unit | 40924 | 25481 | 0.6163 | string_or_mixed |
| worker_b_value | 33184 | 33221 | 0.4997 | numeric |
| worker_b_unit | 34240 | 32165 | 0.5156 | string_or_mixed |
| relative_difference | 8880 | 57525 | 0.1337 | numeric |
| requires_human_review | 66405 | 0 | 1.0000 | string_or_mixed |
| review_reason | 59191 | 7214 | 0.8914 | string_or_mixed |
| evidence_file_a | 37075 | 29330 | 0.5583 | string_or_mixed |
| location_a | 36961 | 29444 | 0.5566 | string_or_mixed |
| verbatim_quote_a | 36934 | 29471 | 0.5562 | string_or_mixed |
| table_reference_a | 3104 | 63301 | 0.0467 | string_or_mixed |
| grounding_type_a | 41044 | 25361 | 0.6181 | string_or_mixed |
| evidence_file_b | 30649 | 35756 | 0.4615 | string_or_mixed |
| location_b | 30545 | 35860 | 0.4600 | string_or_mixed |
| verbatim_quote_b | 30545 | 35860 | 0.4600 | string_or_mixed |
| table_reference_b | 2682 | 63723 | 0.0404 | string_or_mixed |
| grounding_type_b | 34353 | 32052 | 0.5173 | string_or_mixed |

### consolidated_zinc_battery_database.json
- Format: json
- Size: 68284939 bytes
- SHA-256: 187853dd43e3299f21f544ce10ca6cef7aa6d159a3ee55ebbd1d6e14ed1a94d6
- Top-level type: dict
- Top-level length: 2
- Top-level keys (first 200): metadata, papers
- Nested structural paths: 42
- Depth truncations: 0
- Nested semantic mapping: not performed.

## Warnings

- Column names and sampled type hints do not establish scientific meaning.
- Nested JSON paths and value types are structural observations, not semantic mappings.
- A CSV row is not assumed to be an independent experimental replicate.
- Short and long CSV rows are counted; extra cell contents are not interpreted.
- No missing-value imputation or source-data modification was performed.
- Original research documents and locator targets were not opened or verified; only declared structured inputs and provenance metadata were inspected.

## Next step

Review this report and the bounded structural profile. Review only supplied structured evidence records and opaque locator metadata; never open original papers/SI or dereference locators. Define explicit mappings from structured fields only. If required meaning or a relationship is absent, keep it unresolved and request upstream structured-data correction. Do not infer scientific meanings from identifiers, filenames, or sampled values alone.
