from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dor.semantic_registry import (
    overlay_semantic_registry,
    validate_semantic_registry_data,
    validate_semantic_registry_file,
)


def _metadata(**overrides):
    payload = {
        "canonical_concept_id": "concept:generic-1",
        "display_name": "Generic measured attribute",
        "definition": "Definition supplied by a reviewer.",
        "measurement_basis": "Declared measurement basis.",
        "measurement_context": "context:one",
        "derivation_type": "MEASURED",
        "derived_from": [],
        "review_status": "APPROVED",
        "reviewer": "reviewer-label",
        "reviewed_at": "2026-11-18T00:00:00Z",
        "review_rationale": "Reviewed against the cited source.",
        "source_refs": [{
            "source_id": "source:one",
            "source_sha256": "a" * 64,
            "locator": "opaque:record/1",
        }],
    }
    payload.update(overrides)
    return payload


def _registry(identifier="Target-A", entity_type="TARGET", metadata=None):
    return {
        "schema_version": "1.0",
        "registry_id": "registry:test",
        "records": [{
            "entity_type": entity_type,
            "canonical_identifier": identifier,
            "semantic_metadata": metadata or _metadata(),
        }],
    }


class SemanticRegistryTests(unittest.TestCase):
    def test_approved_registry_requires_reviewer_and_hash_bound_source_reference(self):
        registry = _registry(metadata=_metadata(source_refs=[]))
        report = validate_semantic_registry_data(registry)
        self.assertFalse(report["valid"])
        self.assertTrue(any("source_refs" in error for error in report["errors"]))

    def test_empty_registry_is_valid_and_does_not_claim_approved_metadata(self):
        registry = {"schema_version": "1.0", "registry_id": "registry:empty", "records": []}
        report = validate_semantic_registry_data(registry)
        self.assertTrue(report["valid"])
        self.assertEqual(report["approved_record_count"], 0)

    def test_overlay_is_exact_and_does_not_mutate_canonical_bundle(self):
        bundle = {
            "observations": [{"target_id": "Target-A"}],
            "conditions": [{"condition_type": "Condition-A"}],
        }
        registry = {
            "schema_version": "1.0",
            "registry_id": "registry:exact",
            "records": [
                {
                    "entity_type": "TARGET",
                    "canonical_identifier": "Target-A",
                    "semantic_metadata": _metadata(),
                },
                {
                    "entity_type": "CONDITION",
                    "canonical_identifier": "Condition-A",
                    "semantic_metadata": _metadata(canonical_concept_id="concept:generic-2"),
                },
            ],
        }
        overlaid, report = overlay_semantic_registry(bundle, registry)
        self.assertNotIn("semantic_metadata", bundle["observations"][0])
        self.assertEqual(overlaid["observations"][0]["semantic_metadata"]["review_status"], "APPROVED")
        self.assertEqual(overlaid["conditions"][0]["semantic_metadata"]["canonical_concept_id"], "concept:generic-2")
        self.assertEqual(report["status"], "VALIDATED_AND_APPLIED_IN_MEMORY")
        self.assertFalse(report["bundle_modified"])
        self.assertFalse(report["source_locators_dereferenced"])


    def test_endpoint_scoped_registry_metadata_does_not_leak_across_contexts(self):
        bundle = {
            "observations": [
                {"target_id": "Target-A", "endpoint_definition": "endpoint-a", "timepoint": "initial"},
                {"target_id": "Target-A", "endpoint_definition": "endpoint-b", "timepoint": "final"},
            ],
            "conditions": [],
        }
        registry = {
            "schema_version": "1.0",
            "registry_id": "registry:endpoint-scoped",
            "records": [
                {
                    "entity_type": "TARGET_ENDPOINT",
                    "canonical_identifier": "Target-A",
                    "endpoint_definition": "endpoint-a",
                    "timepoint": "initial",
                    "semantic_metadata": _metadata(canonical_concept_id="concept:initial"),
                },
                {
                    "entity_type": "TARGET_ENDPOINT",
                    "canonical_identifier": "Target-A",
                    "endpoint_definition": "endpoint-b",
                    "timepoint": "final",
                    "semantic_metadata": _metadata(canonical_concept_id="concept:final"),
                },
            ],
        }
        overlaid, report = overlay_semantic_registry(bundle, registry)
        self.assertEqual(
            overlaid["observations"][0]["semantic_metadata"]["canonical_concept_id"],
            "concept:initial",
        )
        self.assertEqual(
            overlaid["observations"][1]["semantic_metadata"]["canonical_concept_id"],
            "concept:final",
        )
        self.assertEqual(report["target_endpoint_record_count"], 2)
        self.assertFalse(report["bundle_modified"])

    def test_endpoint_scoped_registry_requires_exact_endpoint_and_timepoint(self):
        bundle = {
            "observations": [
                {"target_id": "Target-A", "endpoint_definition": "endpoint-a", "timepoint": "initial"}
            ],
            "conditions": [],
        }
        registry = {
            "schema_version": "1.0",
            "registry_id": "registry:wrong-context",
            "records": [{
                "entity_type": "TARGET_ENDPOINT",
                "canonical_identifier": "Target-A",
                "endpoint_definition": "endpoint-a",
                "timepoint": "final",
                "semantic_metadata": _metadata(),
            }],
        }
        with self.assertRaisesRegex(ValueError, "do not match any Canonical records"):
            overlay_semantic_registry(bundle, registry)

    def test_overlay_does_not_normalize_identifier_case_or_punctuation(self):
        bundle = {"observations": [{"target_id": "Target-A"}], "conditions": []}
        registry = _registry(identifier="targeta")
        with self.assertRaisesRegex(ValueError, "does not match any Canonical record"):
            overlay_semantic_registry(bundle, registry)

    def test_inline_metadata_conflict_fails_closed(self):
        bundle = {
            "observations": [{
                "target_id": "Target-A",
                "semantic_metadata": {"canonical_concept_id": "concept:different"},
            }],
            "conditions": [],
        }
        with self.assertRaisesRegex(ValueError, "conflicts with inline Canonical metadata"):
            overlay_semantic_registry(bundle, _registry())

    def test_file_validator_reports_malformed_and_valid_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text("{not-json", encoding="utf-8")
            self.assertFalse(validate_semantic_registry_file(path)["valid"])
            path.write_text(json.dumps(_registry()), encoding="utf-8")
            report = validate_semantic_registry_file(path)
            self.assertTrue(report["valid"])
            self.assertEqual(report["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
