"""Bounded, evidence-backed feature semantic review queue.

This module selects a few DOI-distinct source excerpts per feature/unit so a domain
reviewer can establish what a feature identifier measures. It never creates or
approves feature mappings.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

_EXCLUDED_BATCHES = {
    "BATCH_20261106_LIMITS_PROBE",
    "BATCH_20261106_SMOKE_NR_94908118",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clip(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    suffix = " …[TRUNCATED]"
    prefix_limit = max(0, limit - len(suffix))
    return value[:prefix_limit].rstrip() + suffix, True


def _evidence(record: dict[str, Any], side: str, max_quote_chars: int) -> dict[str, Any]:
    raw = record.get(f"worker_{side.lower()}_evidence")
    item = raw if isinstance(raw, dict) else {}
    quote = _text(item.get("quote"))
    quote_kind = "VERBATIM_QUOTE"
    if not quote and _text(item.get("cell_value")):
        quote = _text(item.get("cell_value"))
        quote_kind = "TABLE_CELL_VALUE"
    clipped, was_truncated = _clip(quote, max_quote_chars)
    return {
        "text": clipped,
        "text_kind": quote_kind if quote else "NO_QUOTE_OR_CELL_VALUE",
        "truncated": was_truncated,
        "file": _text(item.get("file")),
        "location": _text(item.get("location")),
        "table_reference": _text(item.get("table_reference")),
        "row_header": _text(item.get("row_header")),
        "col_header": _text(item.get("col_header")),
        "footnote": _text(item.get("footnote")),
        "file_id": _text(item.get("file_id")),
    }


def _score(record: dict[str, Any], evidence_a: dict[str, Any], evidence_b: dict[str, Any]) -> tuple[int, ...]:
    agreed = _text(record.get("status")).upper() == "AGREED_MATCH"
    no_review = not bool(record.get("requires_human_review"))
    has_a = bool(evidence_a["text"])
    has_b = bool(evidence_b["text"])
    has_locator = bool(
        (evidence_a["file"] or evidence_a["location"] or evidence_a["table_reference"])
        and (evidence_b["file"] or evidence_b["location"] or evidence_b["table_reference"])
    )
    has_table_context = any(
        item["row_header"] or item["col_header"] for item in (evidence_a, evidence_b)
    )
    primary_source = _text(record.get("source_origin")).upper() not in {
        "RECONCILIATION_CSV_ONLY", "RECONCILIATION_CSV_AMBIGUOUS"
    }
    return (
        int(agreed),
        int(no_review),
        int(has_a and has_b),
        int(has_locator),
        int(has_table_context),
        int(primary_source),
        int(has_a or has_b),
    )


def build_feature_semantics_review_queue(
    observations: list[dict[str, Any]],
    output_dir: Path,
    *,
    max_examples_per_feature_unit: int = 3,
    max_quote_chars: int = 360,
) -> dict[str, Any]:
    """Write <=N DOI-distinct evidence examples per feature/unit."""
    if max_examples_per_feature_unit < 1 or max_quote_chars < 80:
        raise ValueError("Example cap must be positive and quote cap must be at least 80 characters.")

    candidates: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    excluded_test = 0
    excluded_no_doi = 0
    excluded_no_feature = 0
    excluded_no_evidence = 0
    input_count = len(observations)

    for record in observations:
        if _text(record.get("batch_id")) in _EXCLUDED_BATCHES:
            excluded_test += 1
            continue
        doi = _text(record.get("doi"))
        if not doi:
            excluded_no_doi += 1
            continue
        feature = _text(record.get("feature_id"))
        if not feature:
            excluded_no_feature += 1
            continue
        unit = _text(record.get("resolved_unit")) or "UNSPECIFIED_UNIT"
        evidence_a = _evidence(record, "A", max_quote_chars)
        evidence_b = _evidence(record, "B", max_quote_chars)
        if not (evidence_a["text"] or evidence_b["text"]):
            excluded_no_evidence += 1
            continue
        candidates[(feature, unit)][doi.casefold()].append({
            "record": record,
            "doi": doi,
            "evidence_a": evidence_a,
            "evidence_b": evidence_b,
            "score": _score(record, evidence_a, evidence_b),
        })

    rows: list[dict[str, Any]] = []
    feature_unit_summary: list[dict[str, Any]] = []
    for (feature, unit), by_doi in sorted(candidates.items()):
        selected: list[dict[str, Any]] = []
        for doi_key, options in sorted(by_doi.items()):
            # Each DOI can contribute only one representative observation for a
            # feature/unit; prefer an agreed, well-grounded record deterministically.
            options.sort(
                key=lambda item: (
                    tuple(-value for value in item["score"]),
                    _text(item["record"].get("observation_id")),
                )
            )
            selected.append(options[0])
        selected.sort(key=lambda item: (-sum(item["score"]), item["doi"].casefold()))
        selected = selected[:max_examples_per_feature_unit]
        feature_unit_summary.append({
            "feature_id": feature,
            "resolved_unit": unit,
            "doi_candidate_count": len(by_doi),
            "representative_examples_written": len(selected),
            "review_status": "PENDING_HUMAN_SEMANTIC_MAPPING",
        })
        for rank, item in enumerate(selected, start=1):
            record = item["record"]
            a, b = item["evidence_a"], item["evidence_b"]
            target_system, target_system_truncated = _clip(
                _text(record.get("target_system")), max_quote_chars
            )
            review_reason, review_reason_truncated = _clip(
                _text(record.get("review_reason")), max_quote_chars
            )
            rows.append({
                "feature_id": feature,
                "resolved_unit": unit,
                "example_rank": rank,
                "observation_id": _text(record.get("observation_id")),
                "paper_id": _text(record.get("paper_id")),
                "doi": item["doi"],
                "status": _text(record.get("status")),
                "requires_human_review": bool(record.get("requires_human_review")),
                "review_reason": review_reason,
                "review_reason_truncated": review_reason_truncated,
                "source_origin": _text(record.get("source_origin")),
                "resolved_value": _text(record.get("resolved_value")),
                "target_system": target_system,
                "target_system_truncated": target_system_truncated,
                "worker_a_evidence_text": a["text"],
                "worker_a_evidence_text_kind": a["text_kind"],
                "worker_a_quote_truncated": a["truncated"],
                "worker_a_source_file": a["file"],
                "worker_a_source_location": a["location"],
                "worker_a_table_reference": a["table_reference"],
                "worker_a_row_header": a["row_header"],
                "worker_a_col_header": a["col_header"],
                "worker_a_footnote": a["footnote"],
                "worker_a_file_id": a["file_id"],
                "worker_b_evidence_text": b["text"],
                "worker_b_evidence_text_kind": b["text_kind"],
                "worker_b_quote_truncated": b["truncated"],
                "worker_b_source_file": b["file"],
                "worker_b_source_location": b["location"],
                "worker_b_table_reference": b["table_reference"],
                "worker_b_row_header": b["row_header"],
                "worker_b_col_header": b["col_header"],
                "worker_b_footnote": b["footnote"],
                "worker_b_file_id": b["file_id"],
                "review_status": "PENDING_HUMAN_SEMANTIC_MAPPING",
                "mapping_must_not_be_auto_approved": True,
            })

    fields = [
        "feature_id", "resolved_unit", "example_rank", "observation_id", "paper_id", "doi",
        "status", "requires_human_review", "review_reason", "review_reason_truncated",
        "source_origin", "resolved_value", "target_system", "target_system_truncated",
        "worker_a_evidence_text", "worker_a_evidence_text_kind", "worker_a_quote_truncated",
        "worker_a_source_file", "worker_a_source_location", "worker_a_table_reference",
        "worker_a_row_header", "worker_a_col_header", "worker_a_footnote", "worker_a_file_id",
        "worker_b_evidence_text", "worker_b_evidence_text_kind", "worker_b_quote_truncated",
        "worker_b_source_file", "worker_b_source_location", "worker_b_table_reference",
        "worker_b_row_header", "worker_b_col_header", "worker_b_footnote", "worker_b_file_id",
        "review_status", "mapping_must_not_be_auto_approved",
    ]
    output_path = output_dir / "feature_semantics_review_queue.csv"
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "schema_version": "1.0",
        "mapping_status": "PENDING_HUMAN_SEMANTIC_MAPPING",
        "input_observation_count": input_count,
        "feature_unit_group_count": len(feature_unit_summary),
        "representative_evidence_row_count": len(rows),
        "max_examples_per_feature_unit": max_examples_per_feature_unit,
        "max_quote_chars_per_worker": max_quote_chars,
        "excluded_test_batch_observation_count": excluded_test,
        "excluded_without_doi_count": excluded_no_doi,
        "excluded_without_feature_id_count": excluded_no_feature,
        "excluded_without_evidence_quote_or_cell_count": excluded_no_evidence,
        "feature_unit_summary": feature_unit_summary,
        "files": ["feature_semantics_review_queue.csv", "feature_semantics_review_summary.json"],
        "interpretation_limits": [
            "The queue contains at most the configured number of DOI-distinct examples per feature/unit.",
            "Evidence excerpts are clipped and are not complete paper context.",
            "The presence of an extraction quote does not establish the scientific meaning of a feature ID.",
            "Feature mappings require explicit human/domain approval and are never written by this queue.",
            "DOI-less records and the two explicitly identified probe/smoke batches are not selected.",
        ],
    }
    (output_dir / "feature_semantics_review_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
