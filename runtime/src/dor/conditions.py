"""Deterministic extraction of condition metadata from normalized observations.

The extractor is deliberately conservative: it preserves source text, records the
field and locator that support every candidate, and never promotes abbreviations
or unspecified percentage bases into inferred chemistry.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dor.mapping import sha256_file

CONDITION_RULE_VERSION = "zn-battery-condition-rules/0.1.0"
EXCLUDED_TEST_BATCH_IDS = frozenset({
    "BATCH_20261106_LIMITS_PROBE",
    "BATCH_20261106_SMOKE_NR_94908118",
})
MAX_REVIEW_QUEUE_ROWS = 2000

# Keep formulas explicit and conservative. Unknown salts remain in the source text
# and can be reviewed; this list is not intended to be a complete chemistry ontology.
_SALTS = (
    "Zn(CF3SO3)2", "Zn(OTf)2", "Zn(TFSI)2", "Zn(ClO4)2", "Zn(BF4)2",
    "Zn(NO3)2", "Zn(OAc)2", "ZnSO4", "ZnCl2", "ZnBr2", "ZnI2",
    "MnSO4", "Li2SO4", "Na2SO4", "K2SO4", "H2SO4",
)
_SALT_PATTERN = "|".join(re.escape(item) for item in sorted(_SALTS, key=len, reverse=True))
_CONCENTRATION_BEFORE_SALT = re.compile(
    rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>M|mol\s*/\s*L(?:-1|−1)?|mol\s+L(?:-1|−1)?)\s*"
    rf"(?P<salt>{_SALT_PATTERN})\b",
    re.IGNORECASE,
)
_SALT_WITHOUT_CONCENTRATION = re.compile(rf"(?<![A-Za-z0-9])(?P<salt>{_SALT_PATTERN})(?![A-Za-z0-9])", re.IGNORECASE)
_PERCENT_MODIFIER = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*%\s*(?P<name>[A-Za-z][A-Za-z0-9_+]{0,20})"
)
_CELL_CHEMISTRY = re.compile(r"\bZn\s*[-–]\s*MnO2\b", re.IGNORECASE)
_CELL_PAIR = re.compile(
    r"(?<![A-Za-z0-9])(?P<left>Zn|Cu|Ti|MnO2|I2|V2O5|S|C)\s*(?P<separator>\|\||//)\s*"
    r"(?P<right>Zn|Cu|Ti|MnO2|I2|V2O5|S|C)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_MATERIAL_PATTERNS = (
    re.compile(r"\bbare\s+Zn(?:\s+(?:foil|electrode|anode))?\b", re.IGNORECASE),
    re.compile(r"\bZn\s+(?:foil|electrode|anode|substrate)\b", re.IGNORECASE),
    re.compile(r"\bZn@[A-Za-z][A-Za-z0-9_-]*\b", re.IGNORECASE),
    re.compile(r"\bzinc\s+(?:foil|electrode|anode|substrate)\b", re.IGNORECASE),
)
_MISSING = {"", "n/a", "na", "n.a.", "not reported", "not specified", "unknown", "-"}


def is_excluded_test_record(record: dict[str, Any]) -> bool:
    """Return True only for the two explicitly identified diagnostic batches."""
    return str(record.get("batch_id") or "").strip() in EXCLUDED_TEST_BATCH_IDS


def _canonical_material(value: str) -> str:
    return {"zn": "Zn", "cu": "Cu", "ti": "Ti", "mno2": "MnO2", "i2": "I2", "v2o5": "V2O5", "s": "S", "c": "C"}.get(value.casefold(), value)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _record(
    observation: dict[str, Any],
    condition_type: str,
    raw_value: str,
    normalized_value: str,
    source_field: str,
    extraction_method: str,
    confidence: str,
    *,
    numeric_value: float | None = None,
    numeric_unit: str | None = None,
    unit_basis: str | None = None,
    evidence: dict[str, Any] | None = None,
    review_status: str = "CANDIDATE_NOT_HUMAN_ACCEPTED",
) -> dict[str, Any]:
    evidence = evidence or {}
    return {
        "observation_id": _clean(observation.get("observation_id")),
        "paper_id": _clean(observation.get("paper_id")),
        "doi": _clean(observation.get("doi")),
        "reconciliation_id": _clean(observation.get("reconciliation_id")),
        "feature_id": _clean(observation.get("feature_id")),
        "batch_id": _clean(observation.get("batch_id")),
        "data_eligibility": "EXCLUDED_TEST_DATA" if is_excluded_test_record(observation) else "ELIGIBLE_FOR_EXPLORATORY_ANALYSIS",
        "condition_type": condition_type,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "numeric_value": numeric_value,
        "numeric_unit": numeric_unit,
        "unit_basis": unit_basis,
        "source_field": source_field,
        "source_file": _clean(evidence.get("file")),
        "source_location": _clean(evidence.get("location")),
        "table_id": _clean(evidence.get("table_reference")),
        "row_header": _clean(evidence.get("row_header")),
        "col_header": _clean(evidence.get("col_header")),
        "verbatim_quote": _clean(evidence.get("quote")),
        "footnote": _clean(evidence.get("footnote")),
        "source_file_id": _clean(evidence.get("file_id")),
        "extraction_method": extraction_method,
        "rule_version": CONDITION_RULE_VERSION,
        "confidence": confidence,
        "review_status": review_status,
    }


def _parse_target_system(observation: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _clean(observation.get("target_system"))
    if not raw or raw.casefold() in _MISSING:
        return []

    found: list[dict[str, Any]] = []

    def add(condition_type: str, raw_value: str, normalized: str, method: str,
            confidence: str = "HIGH", numeric: float | None = None,
            unit: str | None = None, basis: str | None = None) -> None:
        found.append(_record(
            observation, condition_type, raw_value, normalized, "target_system",
            method, confidence, numeric_value=numeric, numeric_unit=unit, unit_basis=basis,
        ))

    chemistry_match = _CELL_CHEMISTRY.search(raw)
    if chemistry_match:
        add("cell_chemistry", chemistry_match.group(0), "Zn-MnO2", "RULE_CELL_CHEMISTRY", "MEDIUM")

    for match in _CELL_PAIR.finditer(raw):
        left, separator, right = match.group("left", "separator", "right")
        normalized = f"{_canonical_material(left)}{separator}{_canonical_material(right)}"
        add("cell_configuration", match.group(0), normalized, "RULE_CELL_PAIR")
    if re.search(r"\b(full\s+cell|coin\s+cell|pouch\s+cell)\b", raw, re.IGNORECASE):
        match = re.search(r"\b(full\s+cell|coin\s+cell|pouch\s+cell)\b", raw, re.IGNORECASE)
        if match:
            add("cell_configuration_class", match.group(0), match.group(1).upper().replace(" ", "_"),
                "RULE_CELL_CLASS")
    elif re.search(r"\basymmetric\s+cell\b", raw, re.IGNORECASE):
        add("cell_configuration_class", "asymmetric cell", "ASYMMETRIC_CELL", "RULE_CELL_CLASS")
    elif re.search(r"\bsymmetric\s+cell\b", raw, re.IGNORECASE):
        add("cell_configuration_class", "symmetric cell", "SYMMETRIC_CELL", "RULE_CELL_CLASS")

    for match in _CONCENTRATION_BEFORE_SALT.finditer(raw):
        value = float(match.group("value"))
        unit = re.sub(r"\s+", "", match.group("unit"))
        salt = match.group("salt")
        add("salt_concentration", match.group(0), f"{salt}|{match.group('value')} {unit}",
            "RULE_CONCENTRATION_SALT", numeric=value, unit=unit,
            basis="MOLARITY" if unit.casefold() == "m" else "MOLAR_CONCENTRATION")
        add("electrolyte_component", salt, salt, "RULE_KNOWN_SALT_WITH_CONCENTRATION")

    # A salt formula without a concentration is a component candidate, not a
    # concentration. The context is retained so downstream users can distinguish it.
    for match in _SALT_WITHOUT_CONCENTRATION.finditer(raw):
        salt = match.group("salt")
        if any(item["condition_type"] == "electrolyte_component"
               and item["normalized_value"].casefold() == salt.casefold() for item in found):
            continue
        add("electrolyte_component", salt, salt, "RULE_KNOWN_SALT_NO_CONCENTRATION", "MEDIUM")

    for match in _PERCENT_MODIFIER.finditer(raw):
        value = float(match.group("value"))
        name = match.group("name")
        add("percentage_modifier", match.group(0), f"{value:g}% {name}",
            "RULE_PERCENT_MODIFIER", numeric=value, unit="%", basis="UNSPECIFIED_PERCENT_BASIS")

    for pattern in _MATERIAL_PATTERNS:
        for match in pattern.finditer(raw):
            material = re.sub(r"\s+", " ", match.group(0)).strip()
            add("electrode_or_substrate_material", material, material, "RULE_MATERIAL_TOKEN", "MEDIUM")

    if re.search(r"\b(DFT|DFTB|AIMD|ab\s+initio|molecular\s+dynamics)\b", raw, re.IGNORECASE):
        add("system_domain", raw, "COMPUTATIONAL_MODEL", "RULE_COMPUTATIONAL_CONTEXT", "MEDIUM")
    elif re.search(r"\b(contact\s+angle|water\s+droplet|substrate)\b", raw, re.IGNORECASE):
        add("system_domain", raw, "SURFACE_OR_WETTING_TEST", "RULE_SURFACE_CONTEXT", "MEDIUM")
    elif found:
        add("system_domain", raw, "ELECTROCHEMICAL_OR_MATERIAL_SYSTEM",
            "RULE_CONTEXT_FROM_PARSED_SYSTEM", "LOW")

    return found


def _structured_conditions(observation: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = observation.get("measurement_conditions")
    if not isinstance(conditions, dict):
        return []
    output: list[dict[str, Any]] = []
    for key, value in conditions.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            val = value.get("value", value.get("raw_value", value))
            unit = _clean(value.get("unit")) if isinstance(value, dict) else ""
            if isinstance(val, (dict, list)):
                raw = json.dumps(val, ensure_ascii=False, sort_keys=True)
            else:
                raw = _clean(val)
            normalized = raw + (f" {unit}" if unit else "")
            numeric = None
            try:
                numeric = float(val) if val is not None and not isinstance(val, bool) else None
            except (TypeError, ValueError):
                pass
        else:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else _clean(value)
            normalized, unit, numeric = raw, "", None
        output.append(_record(
            observation, str(key), raw, normalized, "measurement_conditions",
            "SOURCE_STRUCTURED_FIELD", "HIGH", numeric_value=numeric,
            numeric_unit=unit or None, evidence=None,
        ))
    return output


def _table_condition_type(header_text: str) -> str | None:
    text = header_text.casefold()
    if "current density" in text or "current-density" in text:
        return "current_density"
    if "areal capacity" in text or "capacity per cycle" in text:
        return "areal_capacity"
    if "temperature" in text:
        return "measurement_temperature"
    if "electrolyte" in text or "concentration" in text or "molarity" in text:
        return "electrolyte_or_concentration"
    if "voltage window" in text or "cutoff voltage" in text:
        return "voltage_window"
    if "scan rate" in text:
        return "scan_rate"
    if "cycle number" in text or "number of cycles" in text:
        return "cycle_number"
    if "additive" in text or "tac content" in text:
        return "additive_loading"
    return None


def _evidence_candidates(observation: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for worker_name in ("worker_a_evidence", "worker_b_evidence"):
        evidence = observation.get(worker_name)
        if not isinstance(evidence, dict):
            continue
        source_field = worker_name
        source_meta = {
            "file": evidence.get("file"),
            "location": evidence.get("location"),
            "quote": evidence.get("quote"),
            "table_reference": evidence.get("table_reference"),
            "row_header": evidence.get("row_header"),
            "col_header": evidence.get("col_header"),
            "footnote": evidence.get("footnote"),
            "file_id": evidence.get("file_id"),
        }
        cell_value = _clean(evidence.get("cell_value"))
        header = " ".join(filter(None, (_clean(evidence.get("row_header")), _clean(evidence.get("col_header")))))
        table_type = _table_condition_type(header)
        if cell_value and table_type:
            output.append(_record(
                observation, table_type, cell_value, cell_value, source_field + ".cell_value",
                "RULE_TABLE_HEADER_VALUE", "HIGH", evidence=source_meta,
                review_status="CANDIDATE_REQUIRES_CONTEXT_REVIEW",
            ))

        quote = _clean(evidence.get("quote"))
        if not quote:
            continue
        # Only extract value/unit pairs attached to an explicit condition label.
        quote_patterns = (
            ("current_density", re.compile(
                r"current\s+density(?:\s+of|\s+was|\s+is|\s*[:=])?\s*"
                r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mA\s*cm(?:-2|−2)|A\s*cm(?:-2|−2)|A\s*g(?:-1|−1)|C)\b",
                re.IGNORECASE)),
            ("areal_capacity", re.compile(
                r"(?:areal\s+capacity|capacity\s+per\s+cycle)(?:\s+of|\s+was|\s*[:=])?\s*"
                r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mAh\s*cm(?:-2|−2))\b",
                re.IGNORECASE)),
            ("measurement_temperature", re.compile(
                r"(?:temperature\s+(?:of|was|is|=|:)\s*|at\s+a\s+temperature\s+of\s*)"
                r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>°C|K)\b",
                re.IGNORECASE)),
        )
        for condition_type, pattern in quote_patterns:
            match = pattern.search(quote)
            if not match:
                continue
            value = float(match.group("value"))
            unit = re.sub(r"\s+", " ", match.group("unit")).strip()
            output.append(_record(
                observation, condition_type, match.group(0), f"{value:g} {unit}",
                source_field + ".quote", "RULE_EXPLICIT_CONDITION_PHRASE", "HIGH",
                numeric_value=value, numeric_unit=unit, evidence=source_meta,
            ))

        # Reuse the target-system parser only for explicit electrolyte/additive mentions
        # in a source quote. Do not treat performance-only sentences as conditions.
        if re.search(r"\b(electrolyte|aqueous\s+solution|additive|wt\s*%|vol\s*%)\b", quote, re.IGNORECASE):
            pseudo = dict(observation)
            pseudo["target_system"] = quote
            for candidate in _parse_target_system(pseudo):
                if candidate["condition_type"] in {
                    "salt_concentration", "electrolyte_component", "percentage_modifier"
                }:
                    candidate["source_field"] = source_field + ".quote"
                    candidate["extraction_method"] = "RULE_EVIDENCE_CONTEXT"
                    candidate["confidence"] = "MEDIUM"
                    candidate.update({
                        "source_file": _clean(source_meta.get("file")),
                        "source_location": _clean(source_meta.get("location")),
                        "table_id": _clean(source_meta.get("table_reference")),
                        "row_header": _clean(source_meta.get("row_header")),
                        "col_header": _clean(source_meta.get("col_header")),
                        "verbatim_quote": quote,
                        "footnote": _clean(source_meta.get("footnote")),
                        "source_file_id": _clean(source_meta.get("file_id")),
                    })
                    output.append(candidate)
    return output


def extract_observation_conditions(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract conservative condition candidates for one normalized observation."""
    candidates = (
        _structured_conditions(observation)
        + _parse_target_system(observation)
        + _evidence_candidates(observation)
    )
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in candidates:
        key = (
            item["condition_type"], item["normalized_value"],
            item["source_field"], item["extraction_method"],
        )
        unique.setdefault(key, item)
    return list(unique.values())


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple)) else value
                for key, value in row.items()
            })


def write_condition_outputs(
    observations: list[dict[str, Any]],
    output_dir: Path,
    input_hashes: dict[str, str],
) -> dict[str, Any]:
    """Write condition records, eligible coverage, bounded review queue, and manifest."""
    all_records: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    review_queue_total = 0
    by_coverage: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    target_system_present_count = 0
    target_system_unparsed_count = 0
    target_system_extracted_observation_ids: set[str] = set()
    target_system_missing_count = 0
    for observation in observations:
        target_value = _clean(observation.get("target_system"))
        target_is_reported = bool(target_value) and target_value.casefold() not in _MISSING
        excluded = is_excluded_test_record(observation)
        if not excluded:
            if target_is_reported:
                target_system_present_count += 1
            else:
                target_system_missing_count += 1
        target_candidates = _parse_target_system(observation)
        if target_candidates and not excluded:
            target_system_extracted_observation_ids.add(_clean(observation.get("observation_id")))
        elif target_is_reported and not excluded:
            target_system_unparsed_count += 1
        candidates = extract_observation_conditions(observation)
        if target_is_reported and not target_candidates and not excluded:
            review_queue_total += 1
            if len(review_queue) < MAX_REVIEW_QUEUE_ROWS:
                review_queue.append({
                    "observation_id": _clean(observation.get("observation_id")),
                    "paper_id": _clean(observation.get("paper_id")),
                    "doi": _clean(observation.get("doi")),
                    "reconciliation_id": _clean(observation.get("reconciliation_id")),
                    "feature_id": _clean(observation.get("feature_id")),
                    "batch_id": _clean(observation.get("batch_id")),
                    "data_eligibility": "EXCLUDED_TEST_DATA" if excluded else "ELIGIBLE_FOR_EXPLORATORY_ANALYSIS",
                    "target_system": _clean(observation.get("target_system"))[:500],
                    "review_reason": "NO_DETERMINISTIC_RULE_MATCH",
                })
        for candidate in candidates:
            all_records.append(candidate)
            if candidate["data_eligibility"] == "EXCLUDED_TEST_DATA":
                continue
            key = (
                candidate["feature_id"], candidate["condition_type"], candidate["source_field"],
            )
            by_coverage[key].append(candidate)

    coverage_rows: list[dict[str, Any]] = []
    for (feature, condition_type, source_field), items in sorted(by_coverage.items()):
        coverage_rows.append({
            "feature_id": feature,
            "condition_type": condition_type,
            "data_source": source_field,
            "condition_record_count": len(items),
            "observation_count": len({x["observation_id"] for x in items}),
            "paper_count": len({x["paper_id"] for x in items}),
            "doi_study_count": len({x["doi"].casefold() for x in items if x["doi"]}),
            "high_confidence_count": sum(x["confidence"] == "HIGH" for x in items),
            "medium_confidence_count": sum(x["confidence"] == "MEDIUM" for x in items),
        })

    eligible_observations = [x for x in observations if not is_excluded_test_record(x)]
    excluded_observations = len(observations) - len(eligible_observations)
    eligible_papers = {_clean(x.get("paper_id")) for x in eligible_observations}
    doi_studies = {_clean(x.get("doi")).casefold() for x in eligible_observations if _clean(x.get("doi"))}
    type_counts = Counter(x["condition_type"] for x in all_records if x["data_eligibility"] != "EXCLUDED_TEST_DATA")
    source_counts = Counter(x["source_field"] for x in all_records if x["data_eligibility"] != "EXCLUDED_TEST_DATA")
    confidence_counts = Counter(x["confidence"] for x in all_records if x["data_eligibility"] != "EXCLUDED_TEST_DATA")
    summary = {
        "schema_version": "1.0",
        "rule_version": CONDITION_RULE_VERSION,
        "scope": "DETERMINISTIC_CANDIDATE_EXTRACTION_NOT_HUMAN_ACCEPTANCE",
        "input_observation_count": len(observations),
        "eligible_observation_count": len(eligible_observations),
        "excluded_test_observation_count": excluded_observations,
        "eligible_paper_count": len(eligible_papers),
        "eligible_doi_study_count": len(doi_studies),
        "target_system_reported_observation_count": target_system_present_count,
        "target_system_missing_or_not_reported_observation_count": target_system_missing_count,
        "target_system_parsed_observation_count": len(target_system_extracted_observation_ids),
        "target_system_unparsed_reported_observation_count": target_system_unparsed_count,
        "condition_record_count_including_excluded": len(all_records),
        "condition_record_count_eligible": sum(x["data_eligibility"] != "EXCLUDED_TEST_DATA" for x in all_records),
        "condition_type_counts_eligible": dict(sorted(type_counts.items())),
        "source_field_counts_eligible": dict(sorted(source_counts.items())),
        "confidence_counts_eligible": dict(sorted(confidence_counts.items())),
        "coverage_row_count": len(coverage_rows),
        "review_queue_row_count_written": len(review_queue),
        "review_queue_total_count": review_queue_total,
        "review_queue_truncated": review_queue_total > len(review_queue),
        "excluded_batch_ids": sorted(EXCLUDED_TEST_BATCH_IDS),
        "interpretation": [
            "All extracted values are candidates; deterministic extraction is not human acceptance.",
            "Chemical abbreviations are preserved verbatim and are not expanded.",
            "A percentage basis is not inferred unless explicitly stated in the source.",
            "Evidence table values remain bound to their row/column headers and source locator.",
            "Unknown target_system strings are sent to a bounded review queue, not guessed.",
            "The explicitly identified probe/smoke batches are retained and tagged but excluded from eligible coverage.",
        ],
    }
    condition_fields = [
        "observation_id", "paper_id", "doi", "reconciliation_id", "feature_id", "batch_id",
        "data_eligibility", "condition_type", "raw_value", "normalized_value", "numeric_value",
        "numeric_unit", "unit_basis", "source_field", "source_file", "source_location",
        "table_id", "row_header", "col_header", "verbatim_quote", "footnote", "source_file_id",
        "extraction_method", "rule_version", "confidence", "review_status",
    ]
    coverage_fields = [
        "feature_id", "condition_type", "data_source", "condition_record_count",
        "observation_count", "paper_count", "doi_study_count",
        "high_confidence_count", "medium_confidence_count",
    ]
    review_fields = [
        "observation_id", "paper_id", "doi", "reconciliation_id", "feature_id",
        "batch_id", "data_eligibility", "target_system", "review_reason",
    ]
    _write_csv(output_dir / "condition_records.csv", condition_fields, all_records)
    _write_csv(output_dir / "condition_coverage.csv", coverage_fields, coverage_rows)
    _write_csv(output_dir / "condition_review_queue.csv", review_fields, review_queue)
    summary_path = output_dir / "condition_extraction_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs = {
        path.name: sha256_file(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name.startswith("condition_")
        and path.name != "condition_manifest.json"
    }
    manifest = {
        "schema_version": "1.0",
        "operation": "dor discover-opportunities condition extraction",
        "rule_version": CONDITION_RULE_VERSION,
        "scope": "READ_ONLY_DETERMINISTIC_CONDITION_EXTRACTION",
        "inputs": [{"path": path, "sha256": digest} for path, digest in sorted(input_hashes.items())],
        "code_sha256": sha256_file(Path(__file__)),
        "input_observation_count": len(observations),
        "excluded_test_batch_ids": sorted(EXCLUDED_TEST_BATCH_IDS),
        "outputs": outputs,
        "source_files_modified": False,
        "llm_calls": 0,
    }
    (output_dir / "condition_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
