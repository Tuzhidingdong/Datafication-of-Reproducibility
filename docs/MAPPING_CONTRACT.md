# Mapping Contract

## Purpose and boundary

A mapping plan records explicit decisions that connect structural source items to fields in the canonical research model. It is a reviewable scientific contract, not a semantic inference engine. Column names, JSON paths, observed value types, and coverage statistics may help a reviewer inspect a source, but none proves what a field means.

The plan is validated against the exact `source_inventory.json` file from which it was prepared. Only rules in `APPROVED` status that pass every validation gate are eligible for a later canonical builder. This validator does not execute conversions or certify scientific correctness.

## Rule structure

Every rule contains:

- `mapping_rule_id`: stable identifier for this decision.
- `source_item_id`: exact `inventory_id` in the source inventory.
- `target_entity` and `target_field_id`: canonical destination, entered by the reviewer.
- `status`: `PROPOSED`, `REVIEWED`, `APPROVED`, `REJECTED`, or `UNRESOLVED`.
- `transformation`: explicit operation and parameters. No implicit unit conversion or parsing is permitted.
- `review`: reviewer, review timestamp, and decision note for approved rules.

A source item may have multiple rules when it legitimately maps to different canonical fields. The same source item cannot have two approved rules targeting the same canonical entity and field; resolve that conflict explicitly instead of letting the builder choose.

## Transformation types

- `IDENTITY`: preserve the source value; parameters must be empty.
- `NUMERIC_PARSE`: parse a numeric representation with explicit decimal/thousands separators.
- `UNIT_CONVERSION`: requires source unit, target unit, and finite multiplicative factor; offset defaults to zero and is recorded when used.
- `LOOKUP`, `SPLIT`, `CUSTOM`: require non-empty explicit parameters or a versioned specification reference.

The validator checks basic completeness and type safety. It does not independently verify dimensional consistency, conversion-factor correctness, lookup-table contents, custom code, or the scientific appropriateness of a transformation. Those remain review responsibilities and later execution contracts.

## Source identity

The plan's `source_inventory_sha256` must equal the SHA-256 hash of the exact inventory file supplied to `dor validate-mapping`. Regenerating or editing the inventory invalidates the plan's source identity and requires review/reconciliation. Each referenced item must also carry source file, source hash, locator type, and locator.

## Fail-closed approval rules

An APPROVED rule must have:
1. an inventory item that exists in the supplied inventory;
2. a supported canonical entity and non-empty canonical field ID;
3. a supported transformation specification;
4. reviewer, timestamp, and decision note;
5. complete source locator/hash provenance.

Unknown references, duplicate IDs, duplicate approved targets, stale inventory hashes, or invalid transformations make the plan invalid. If the plan has any validation error, the validator returns an empty `approved_rule_ids` list. Non-approved rules are reported as excluded and are never eligible.

## CLI

    dor validate-mapping --plan mapping_plan.json --inventory source_inventory.json --out mapping_validation.json

The plan schema is `schemas/mapping_plan.schema.json`. A schema is provided for interchange validation; the runtime command currently performs deterministic reference and approval-gate checks, not full JSON Schema validation.
