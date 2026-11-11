"""Chem-Literacy ingestion, reconciliation import, and condition-recovery preparation.

This module is deterministic. It never calls an LLM, edits source files, decides that
an unobserved condition is NOT_REPORTED, or silently promotes a candidate value.
"""
from __future__ import annotations
import csv, hashlib, json, math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from dor.mapping import sha256_file

DEFAULT_CONDITION_PROFILE_VERSION = "zn-battery-context-hints/1.0"
DEFAULT_CONDITION_PROFILE: dict[str, list[dict[str, Any]]] = {
    "FEAT_CE": [
        {"condition_type":"cell_configuration","search_terms":["Zn||Cu","Zn-Cu","asymmetric cell","substrate"]},
        {"condition_type":"current_density","search_terms":["current density","mA cm","A g","C rate"]},
        {"condition_type":"areal_capacity","search_terms":["areal capacity","mAh cm","capacity per cycle"]},
        {"condition_type":"cycle_range","search_terms":["cycle","cycles","average","coulombic efficiency"]},
        {"condition_type":"test_protocol","search_terms":["cutoff","voltage limit","plating","stripping"]},
    ],
    "FEAT_LIFE_SYM": [
        {"condition_type":"cell_configuration","search_terms":["Zn||Zn","symmetric cell"]},
        {"condition_type":"current_density","search_terms":["current density","mA cm","A g","C rate"]},
        {"condition_type":"areal_capacity","search_terms":["areal capacity","mAh cm","capacity per cycle"]},
        {"condition_type":"failure_criterion","search_terms":["short circuit","voltage failure","failure","lifespan"]},
        {"condition_type":"cycling_protocol","search_terms":["plating","stripping","cycling","cycle"]},
    ],
    "FEAT_CAP_RET": [
        {"condition_type":"cell_configuration","search_terms":["full cell","cathode","anode","Zn||"]},
        {"condition_type":"current_density","search_terms":["current density","C rate","mA g","A g"]},
        {"condition_type":"cycle_number","search_terms":["cycles","cycle number","after"]},
        {"condition_type":"capacity_basis","search_terms":["initial capacity","specific capacity","mAh g","mAh cm"]},
        {"condition_type":"voltage_window","search_terms":["voltage window","cutoff voltage","V"]},
    ],
    "FEAT_OVERPOT_PLAT": [
        {"condition_type":"cell_configuration","search_terms":["Zn||Zn","symmetric cell"]},
        {"condition_type":"current_density","search_terms":["current density","mA cm","A g"]},
        {"condition_type":"areal_capacity","search_terms":["areal capacity","mAh cm"]},
        {"condition_type":"cycle_number","search_terms":["cycle","cycles","100th","200th"]},
    ],
    "FEAT_OVERPOT_NUC": [
        {"condition_type":"cell_configuration","search_terms":["Zn||Cu","Zn||Ti","substrate"]},
        {"condition_type":"current_density","search_terms":["current density","mA cm","A g"]},
        {"condition_type":"areal_capacity","search_terms":["areal capacity","mAh cm"]},
        {"condition_type":"measurement_protocol","search_terms":["nucleation","plating","voltage dip","galvanostatic"]},
    ],
    "FEAT_IONIC_COND": [
        {"condition_type":"measurement_temperature","search_terms":["temperature","°C","K"]},
        {"condition_type":"measurement_method","search_terms":["EIS","impedance","conductivity cell"]},
        {"condition_type":"sample_state","search_terms":["electrolyte","gel","hydrogel","separator"]},
    ],
    "FEAT_ICORR": [
        {"condition_type":"electrolyte_composition","search_terms":["electrolyte","ZnSO4","mol L","M Zn"]},
        {"condition_type":"measurement_temperature","search_terms":["temperature","°C","K"]},
        {"condition_type":"reference_electrode","search_terms":["reference electrode","Ag/AgCl","vs. Zn","SCE"]},
        {"condition_type":"measurement_method","search_terms":["Tafel","polarization","LSV"]},
        {"condition_type":"area_basis","search_terms":["geometric area","ECSA","surface area"]},
    ],
    "FEAT_ECORR": [
        {"condition_type":"reference_electrode","search_terms":["reference electrode","Ag/AgCl","vs. Zn","SCE"]},
        {"condition_type":"measurement_temperature","search_terms":["temperature","°C","K"]},
        {"condition_type":"electrolyte_composition","search_terms":["electrolyte","ZnSO4","mol L"]},
        {"condition_type":"measurement_method","search_terms":["open circuit","Tafel","polarization"]},
    ],
    "FEAT_E_ADS": [
        {"condition_type":"surface_facet","search_terms":["(002)","(100)","(101)","facet","surface"]},
        {"condition_type":"calculation_method","search_terms":["DFT","functional","PBE","dispersion","basis set"]},
        {"condition_type":"adsorbate_model","search_terms":["adsorbate","slab","adsorption configuration"]},
    ],
    "FEAT_EA": [
        {"condition_type":"measurement_method","search_terms":["Arrhenius","EIS","impedance"]},
        {"condition_type":"temperature_range","search_terms":["temperature","°C","K"]},
        {"condition_type":"cell_configuration","search_terms":["symmetric cell","Zn||Zn"]},
    ],
}


def _stable_id(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20].upper()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().casefold()
    if token in {"true", "1", "yes", "y"}:
        return True
    if token in {"false", "0", "no", "n", ""}:
        return False
    return default


def _evidence(record: dict[str, Any], side: str) -> dict[str, Any]:
    nested = record.get("worker_" + side.lower() + "_evidence")
    if isinstance(nested, dict):
        return {
            "file": _first(nested, "file_path", "source_file"),
            "location": _first(nested, "section_or_page", "location", "page"),
            "quote": _first(nested, "verbatim_quote", "quote"),
            "table_reference": _first(nested, "table_id", "table_reference"),
        }
    return {
        "file": _first(record, "evidence_file_" + side.lower()),
        "location": _first(record, "location_" + side.lower()),
        "quote": _first(record, "verbatim_quote_" + side.lower()),
        "table_reference": _first(record, "table_reference_" + side.lower()),
    }


def _normalize_observation(record: dict[str, Any], origin: str, ordinal: int) -> dict[str, Any]:
    paper_id = _text(_first(record, "paper_id", "study_id")) or "UNKNOWN_PAPER_" + str(ordinal)
    rec_id = _text(_first(record, "reconciliation_id", "record_id")) or "ROW_" + str(ordinal)
    feature_id = _text(_first(record, "feature_id", "canonical_feature_id"))
    status = _text(record.get("status")).upper() or "UNKNOWN_STATUS"
    conditions = record.get("measurement_conditions")
    if not isinstance(conditions, dict):
        conditions = record.get("experimental_context")
    if not isinstance(conditions, dict):
        conditions = {}
    return {
        "observation_id": _stable_id("DOROBS_", paper_id + "|" + rec_id),
        "source_record_key": paper_id + "|" + rec_id,
        "paper_id": paper_id,
        "doi": _text(record.get("doi")) or None,
        "study_group_id": _text(record.get("doi")) or paper_id,
        "study_group_id_source": "DOI" if _text(record.get("doi")) else "PAPER_ID_FALLBACK_NOT_VERIFIED_DOI",
        "title": _text(record.get("title")) or None,
        "batch_id": _text(record.get("batch_id")) or None,
        "reconciliation_id": rec_id,
        "feature_id": feature_id or None,
        "target_system": _text(record.get("target_system")) or None,
        "status": status,
        "resolved_value": record.get("resolved_value"),
        "resolved_unit": _text(record.get("resolved_unit")) or None,
        "worker_a_value": record.get("worker_a_value"),
        "worker_a_unit": _text(record.get("worker_a_unit")) or None,
        "worker_b_value": record.get("worker_b_value"),
        "worker_b_unit": _text(record.get("worker_b_unit")) or None,
        "relative_difference": record.get("relative_difference"),
        "requires_human_review": _as_bool(record.get("requires_human_review"), status != "AGREED_MATCH"),
        "review_reason": _text(record.get("review_reason")) or None,
        "worker_a_evidence": _evidence(record, "A"),
        "worker_b_evidence": _evidence(record, "B"),
        "worker_a_grounding_type": _text(_first(record, "worker_a_grounding_type", "grounding_type_a")) or None,
        "worker_b_grounding_type": _text(_first(record, "worker_b_grounding_type", "grounding_type_b")) or None,
        "measurement_conditions": conditions,
        "source_origin": origin,
        "source_row_ordinal": ordinal,
    }


def _load_json_observations(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("papers"), list):
        raise ValueError("Chem-Literacy database JSON must be an object containing a papers array.")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    records: list[dict[str, Any]] = []
    ordinal = 0
    for paper in payload["papers"]:
        if not isinstance(paper, dict) or not isinstance(paper.get("observations"), list):
            continue
        for observation in paper["observations"]:
            if not isinstance(observation, dict):
                continue
            ordinal += 1
            combined = {
                "paper_id": paper.get("paper_id"), "doi": paper.get("doi"),
                "title": paper.get("title"), "batch_id": paper.get("batch_id"),
                **observation,
            }
            records.append(_normalize_observation(combined, "AGGREGATED_JSON", ordinal))
    return metadata, records


def _load_csv_observations(path: Path, origin: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"paper_id", "reconciliation_id", "feature_id", "status"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Chem-Literacy observation CSV is missing required columns: " + ", ".join(sorted(required - set(reader.fieldnames or []))))
        for ordinal, row in enumerate(reader, start=1):
            records.append(_normalize_observation(row, origin, ordinal))
    return records


def _merge_ledger(primary: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(primary):
        by_key[record["source_record_key"]].append(index)
    issues: list[dict[str, Any]] = []
    merged = [dict(record) for record in primary]
    compare_fields = ("feature_id", "target_system", "status", "resolved_value", "resolved_unit",
                      "worker_a_value", "worker_b_value", "worker_a_unit", "worker_b_unit")
    for ledger_record in ledger:
        key = ledger_record["source_record_key"]
        matches = by_key.get(key, [])
        if len(matches) != 1:
            issues.append({
                "issue_code": "LEDGER_KEY_NOT_UNIQUE_OR_NOT_FOUND",
                "source_record_key": key,
                "match_count": len(matches),
                "action": "PRESERVED_WITHOUT_OVERWRITE",
            })
            continue
        index = matches[0]
        primary_record = merged[index]
        for field in compare_fields:
            left, right = primary_record.get(field), ledger_record.get(field)
            if left not in (None, "") and right not in (None, "") and str(left) != str(right):
                issues.append({
                    "issue_code": "JSON_CSV_FIELD_DISAGREEMENT",
                    "source_record_key": key,
                    "field": field,
                    "json_value": left,
                    "csv_value": right,
                    "action": "JSON_PRIMARY_RETAINED; REVIEW_REQUIRED",
                })
        for field in ("worker_a_evidence", "worker_b_evidence"):
            existing, incoming = primary_record.get(field) or {}, ledger_record.get(field) or {}
            primary_record[field] = {
                name: existing.get(name) if existing.get(name) not in (None, "") else incoming.get(name)
                for name in ("file", "location", "quote", "table_reference")
            }
    for ledger_record in ledger:
        if ledger_record["source_record_key"] not in by_key:
            extra = dict(ledger_record)
            extra["source_origin"] = "RECONCILIATION_CSV_ONLY"
            merged.append(extra)
    return merged, issues


def _safe_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resolve_paper_files(source_root: Path, paper_id: str, records: list[dict[str, Any]]) -> list[Path]:
    candidates: list[Path] = []
    paper_dir = source_root / paper_id
    for relative in ("main_analysis.md", "si_analysis.md"):
        candidates.extend((paper_dir / relative, paper_dir / "01_preprocessing" / relative,
                           paper_dir / "preprocessed" / relative))
    for record in records:
        for evidence_field in ("worker_a_evidence", "worker_b_evidence"):
            evidence_file = (record.get(evidence_field) or {}).get("file")
            if evidence_file:
                relative = Path(str(evidence_file))
                if not relative.is_absolute() and ".." not in relative.parts:
                    candidates.extend((paper_dir / relative, paper_dir / "01_preprocessing" / relative,
                                       paper_dir / "preprocessed" / relative, source_root / relative))
    resolved: list[Path] = []
    seen: set[Path] = set()
    root = source_root.resolve()
    for candidate in candidates:
        path = candidate.resolve(strict=False)
        if path in seen or not path.is_file() or not path.is_relative_to(root):
            continue
        seen.add(path)
        resolved.append(path)
    return resolved


def _excerpt_windows(text: str, terms: list[str], max_windows: int = 2, window: int = 520) -> list[dict[str, Any]]:
    hits: list[tuple[int, str]] = []
    lower = text.casefold()
    for term in terms:
        needle = term.casefold()
        if not needle:
            continue
        start = 0
        while len(hits) < max_windows * 4:
            index = lower.find(needle, start)
            if index < 0:
                break
            hits.append((index, term))
            start = index + max(1, len(needle))
    hits.sort()
    windows: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for index, term in hits:
        left, right = max(0, index - window), min(len(text), index + window)
        if any(left < old_right and right > old_left for old_left, old_right in occupied):
            continue
        windows.append({"matched_term": term, "start_char": left, "end_char": right, "excerpt": text[left:right]})
        occupied.append((left, right))
        if len(windows) >= max_windows:
            break
    return windows


def _condition_profile(path: Path | None) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    if path is None:
        return DEFAULT_CONDITION_PROFILE_VERSION, DEFAULT_CONDITION_PROFILE
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), dict):
        raise ValueError("Condition profile must contain a features object.")
    return str(payload.get("profile_version", "user-condition-profile")), payload["features"]


def ingest_chem_literacy_files(
    database_json: Path | None, database_csv: Path | None,
    reconciliation_csv: Path | None, source_root: Path | None,
    output_dir: Path, condition_profile_path: Path | None = None,
) -> dict[str, Any]:
    if (database_json is None) == (database_csv is None):
        raise ValueError("Provide exactly one of --database-json or --database-csv.")
    inputs = [path.expanduser().resolve() for path in (database_json, database_csv, reconciliation_csv) if path is not None]
    if source_root is not None:
        source_root = source_root.expanduser().resolve()
        if not source_root.is_dir():
            raise FileNotFoundError("Source root does not exist or is not a directory: " + str(source_root))
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite non-empty output directory: " + str(output_dir))
    if source_root is not None and output_dir.is_relative_to(source_root):
        raise ValueError("DOR output directory must not be inside the protected Chem-Literacy source root.")
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError("Input file does not exist: " + str(path))
        if output_dir == path:
            raise ValueError("Output directory cannot replace an input file.")
    before_hashes = {str(path): sha256_file(path) for path in inputs}
    if database_json is not None:
        metadata, observations = _load_json_observations(database_json.expanduser().resolve())
        primary_origin = "AGGREGATED_JSON"
    else:
        metadata, observations = {}, _load_csv_observations(database_csv.expanduser().resolve(), "OBSERVATION_CSV")
        primary_origin = "OBSERVATION_CSV"
    merge_issues: list[dict[str, Any]] = []
    if reconciliation_csv is not None:
        ledger = _load_csv_observations(reconciliation_csv.expanduser().resolve(), "RECONCILIATION_CSV")
        observations, merge_issues = _merge_ledger(observations, ledger)
    if not observations:
        raise ValueError("No observation records were found in the supplied Chem-Literacy source.")
    key_counts = Counter(item["source_record_key"] for item in observations)
    duplicate_keys = [{"source_record_key": key, "count": count}
                      for key, count in sorted(key_counts.items()) if count > 1]
    profile_version, profile = _condition_profile(condition_profile_path)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        grouped[(item["paper_id"], item.get("feature_id") or "UNKNOWN_FEATURE",
                 item.get("target_system") or "UNKNOWN_SYSTEM")].append(item)

    source_hashes: dict[str, str] = {}
    condition_queue: list[dict[str, Any]] = []
    recovery_tasks: list[dict[str, Any]] = []
    for (paper_id, feature_id, target_system), group_records in sorted(grouped.items()):
        expected = profile.get(feature_id, [])
        if not isinstance(expected, list):
            continue
        available_files = _resolve_paper_files(source_root, paper_id, group_records) if source_root else []
        loaded_files: list[tuple[Path, str]] = []
        for path in available_files:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
            digest = sha256_file(path)
            source_hashes[str(path)] = digest
            loaded_files.append((path, content))
        task_id = _stable_id("DORCR_", paper_id + "|" + feature_id + "|" + target_system)
        requested_fields: list[dict[str, Any]] = []
        for requirement in expected:
            condition_type = str(requirement.get("condition_type", "")).strip()
            if not condition_type:
                continue
            present_values = [
                (record.get("measurement_conditions") or {}).get(condition_type)
                for record in group_records
                if (record.get("measurement_conditions") or {}).get(condition_type) not in (None, "")
            ]
            excerpts: list[dict[str, Any]] = []
            if present_values:
                retrieval_status = "PRESENT_IN_STRUCTURED_DATA"
            elif not loaded_files:
                retrieval_status = "SOURCE_FILES_NOT_AVAILABLE"
            else:
                terms = [str(value) for value in requirement.get("search_terms", [])]
                for path, content in loaded_files:
                    for window in _excerpt_windows(content, terms):
                        excerpts.append({"source_file": str(path), "source_sha256": source_hashes[str(path)], **window})
                retrieval_status = "CANDIDATE_CONTEXT_FOUND_NOT_VERIFIED" if excerpts else "NOT_FOUND_IN_INITIAL_SEARCH"
            condition_queue.append({
                "task_id": task_id, "paper_id": paper_id, "feature_id": feature_id,
                "target_system": target_system, "condition_type": condition_type,
                "record_count": len(group_records),
                "observation_ids": ";".join(item["observation_id"] for item in group_records),
                "retrieval_status": retrieval_status, "condition_decision": "UNRESOLVED",
                "candidate_excerpt_count": len(excerpts),
                "important_boundary": "NOT_FOUND_IN_INITIAL_SEARCH_DOES_NOT_MEAN_NOT_REPORTED",
            })
            requested_fields.append({
                "condition_type": condition_type,
                "search_terms": [str(value) for value in requirement.get("search_terms", [])],
                "retrieval_status": retrieval_status,
                "candidate_excerpts": excerpts,
            })
        if requested_fields:
            recovery_tasks.append({
                "schema_version": "1.0", "task_id": task_id, "paper_id": paper_id,
                "feature_id": feature_id, "target_system": target_system,
                "observation_ids": [item["observation_id"] for item in group_records],
                "source_files": [{"path": str(path), "sha256": source_hashes[str(path)]} for path, _ in loaded_files],
                "source_evidence_anchors": [
                    {"observation_id": item["observation_id"],
                     "worker_a_evidence": item.get("worker_a_evidence"),
                     "worker_b_evidence": item.get("worker_b_evidence")}
                    for item in group_records
                ],
                "requested_conditions": requested_fields,
                "worker_instructions": [
                    "Search only the declared source paper and SI files for each requested condition.",
                    "Return FOUND only with an explicit value, unit, exact quotation, and page/table/figure locator.",
                    "Use AMBIGUOUS when multiple values or unclear sample-to-condition links exist.",
                    "Use NOT_FOUND_IN_SEARCH when no value was verified; this is not the same as NOT_REPORTED.",
                    "Never infer a missing value from common practice, another paper, or target_system text.",
                    "Keep different current densities, cycle numbers, capacities, temperatures, and cell configurations as separate observations.",
                    "Do not edit original source files or normalized observations.",
                ],
                "result_contract": "schemas/condition_recovery_result.schema.json",
                "human_review_required_before_promotion": True,
            })

    for path, expected_hash in before_hashes.items():
        if sha256_file(Path(path)) != expected_hash:
            raise RuntimeError("An input source changed during ingestion: " + path)
    for path, expected_hash in source_hashes.items():
        if sha256_file(Path(path)) != expected_hash:
            raise RuntimeError("A preprocessed source file changed during condition search: " + path)

    status_counts = Counter(item["status"] for item in observations)
    by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        by_feature[item.get("feature_id") or "UNKNOWN_FEATURE"].append(item)
    feature_summary: dict[str, Any] = {}
    for feature_id, items in sorted(by_feature.items()):
        feature_summary[feature_id] = {
            "observation_count": len(items),
            "paper_count": len({item["paper_id"] for item in items}),
            "doi_count": len({item["doi"] for item in items if item.get("doi")}),
            "paper_id_fallback_count": sum(1 for item in items if not item.get("doi")),
            "status_counts": dict(sorted(Counter(item["status"] for item in items).items())),
            "numeric_resolved_count": sum(1 for item in items if _safe_number(item.get("resolved_value")) is not None),
            "agreed_numeric_candidate_count": sum(
                1 for item in items if item["status"] == "AGREED_MATCH"
                and _safe_number(item.get("resolved_value")) is not None and item.get("resolved_unit")
            ),
            "single_worker_count": sum(1 for item in items if item["status"] in {"PASS_A_ONLY", "PASS_B_ONLY"}),
            "conflict_count": sum(1 for item in items if item["status"] == "VALUE_CONFLICT"),
            "human_review_count": sum(1 for item in items if item.get("requires_human_review")),
        }
    review_queue = [item for item in observations if item["status"] != "AGREED_MATCH"
                    or item.get("requires_human_review") or item.get("resolved_value") is None]
    target_candidates = [item for item in observations if item["status"] == "AGREED_MATCH"
                         and _safe_number(item.get("resolved_value")) is not None and bool(item.get("resolved_unit"))]
    report = {
        "schema_version": "1.0", "valid": True,
        "validation_scope": "CHEM_LITERACY_IMPORT_AND_STRUCTURAL_QUALITY_AUDIT_NOT_SCIENTIFIC_ACCEPTANCE",
        "source_metadata": metadata, "primary_source_type": primary_origin,
        "observation_count": len(observations),
        "unique_paper_id_count": len({item["paper_id"] for item in observations}),
        "unique_doi_count": len({item["doi"] for item in observations if item.get("doi")}),
        "paper_id_fallback_count": sum(1 for item in observations if not item.get("doi")),
        "feature_count": len(by_feature), "status_counts": dict(sorted(status_counts.items())),
        "feature_summary": feature_summary, "review_queue_count": len(review_queue),
        "numeric_target_candidate_count": len(target_candidates),
        "condition_recovery_task_count": len(recovery_tasks),
        "condition_recovery_queue_count": len(condition_queue),
        "source_merge_issue_count": len(merge_issues), "source_merge_issues": merge_issues,
        "duplicate_source_record_keys": duplicate_keys,
        "condition_profile_version": profile_version,
        "condition_status_policy": {
            "PRESENT_IN_STRUCTURED_DATA": "Structured field exists; semantic correctness still needs review.",
            "CANDIDATE_CONTEXT_FOUND_NOT_VERIFIED": "A local excerpt contains a search term; an Agent/human must verify value, unit, sample, and locator.",
            "NOT_FOUND_IN_INITIAL_SEARCH": "Bounded keyword search found no excerpt; this is not evidence that the paper omitted the condition.",
            "SOURCE_FILES_NOT_AVAILABLE": "No declared local source file was available for targeted recovery.",
            "NOT_REPORTED": "Reserved for explicit human-reviewed decision after relevant main text and SI are checked.",
            "AMBIGUOUS": "Use when source statements conflict or cannot be assigned to a specific observation.",
        },
        "modeling_boundary": "numeric_target_candidates.csv contains candidate labels only. It is not a feature matrix or validated modeling cohort.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_columns = [
        "observation_id","source_record_key","paper_id","doi","study_group_id","study_group_id_source",
        "title","batch_id","reconciliation_id","feature_id","target_system","status","resolved_value","resolved_unit",
        "worker_a_value","worker_a_unit","worker_b_value","worker_b_unit","relative_difference",
        "requires_human_review","review_reason","worker_a_evidence","worker_b_evidence",
        "worker_a_grounding_type","worker_b_grounding_type","measurement_conditions","source_origin","source_row_ordinal",
    ]
    def write_observation_csv(path: Path, records: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=normalized_columns)
            writer.writeheader()
            for item in records:
                row = dict(item)
                for field in ("worker_a_evidence","worker_b_evidence","measurement_conditions"):
                    row[field] = json.dumps(row.get(field) or {}, ensure_ascii=False, sort_keys=True)
                writer.writerow(row)
    write_observation_csv(output_dir / "observations_normalized.csv", observations)
    write_observation_csv(output_dir / "reconciliation_review_queue.csv", review_queue)
    candidate_columns = ["observation_id","paper_id","doi","study_group_id","feature_id","target_system",
                         "resolved_value","resolved_unit","reconciliation_id","worker_a_evidence","worker_b_evidence"]
    with (output_dir / "numeric_target_candidates.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=candidate_columns)
        writer.writeheader()
        for item in target_candidates:
            row = {key: item.get(key) for key in candidate_columns}
            for field in ("worker_a_evidence","worker_b_evidence"):
                row[field] = json.dumps(row.get(field) or {}, ensure_ascii=False)
            writer.writerow(row)
    queue_columns = ["task_id","paper_id","feature_id","target_system","condition_type","record_count",
                     "observation_ids","retrieval_status","condition_decision","candidate_excerpt_count","important_boundary"]
    with (output_dir / "condition_recovery_queue.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=queue_columns)
        writer.writeheader()
        writer.writerows(condition_queue)
    (output_dir / "condition_recovery_tasks.json").write_text(
        json.dumps({"schema_version":"1.0","tasks":recovery_tasks}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "data_quality_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    source_manifest = {
        "schema_version":"1.0",
        "source_files":[{"path":str(path),"sha256":digest,"role":"INPUT"} for path,digest in before_hashes.items()],
        "recovery_source_files":[{"path":path,"sha256":digest,"role":"READ_ONLY_CONTEXT"} for path,digest in sorted(source_hashes.items())],
        "source_policy":"READ_ONLY; NO_SOURCE_EDIT; NO_IMPLICIT_DOI_OR_CONDITION_INFERENCE",
        "observation_count":len(observations),
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_md = [
        "# Chem-Literacy import report", "",
        f"- Observations: {len(observations)}",
        f"- Paper IDs: {report['unique_paper_id_count']}",
        f"- DOI-backed studies: {report['unique_doi_count']}",
        f"- Paper-ID fallback groups (DOI missing): {report['paper_id_fallback_count']}",
        f"- Features: {report['feature_count']}",
        f"- Reconciliation review queue: {len(review_queue)}",
        f"- Numeric agreed label candidates: {len(target_candidates)}",
        f"- Condition-recovery tasks: {len(recovery_tasks)}", "",
        "## Interpretation boundary", "",
        "This is an import and structural quality audit, not scientific acceptance. AGREED_MATCH is a priority status, not proof of correctness. Single-worker and conflicting records are retained in the review queue. Numeric target candidates are labels only, not a ready-to-train feature matrix.", "",
        "A condition not found by the initial keyword search remains NOT_ASSESSED. DOR must not convert search failure into NOT_REPORTED. NOT_REPORTED requires explicit review of relevant main text and SI.", "",
    ]
    (output_dir / "import_report.md").write_text("\n".join(report_md), encoding="utf-8")
    return {
        "valid": True, "output_dir": str(output_dir), "observation_count": len(observations),
        "review_queue_count": len(review_queue), "numeric_target_candidate_count": len(target_candidates),
        "condition_recovery_task_count": len(recovery_tasks), "source_merge_issue_count": len(merge_issues),
    }
