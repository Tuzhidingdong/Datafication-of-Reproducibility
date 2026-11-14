"""Read-only exploratory profiling for discovery-first DoR workflows."""
from __future__ import annotations
import csv, itertools, json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from dor.chem_literacy import _load_csv_observations, _load_json_observations, _merge_ledger
from dor.mapping import sha256_file
from dor.conditions import EXCLUDED_TEST_BATCH_IDS, is_excluded_test_record, write_condition_outputs

def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None: return None
    try: result = float(str(value).strip())
    except (TypeError, ValueError): return None
    return result if math.isfinite(result) else None

def _text(value: Any, default: str = "") -> str:
    value = "" if value is None else str(value).strip()
    return value or default

def _study(record: dict[str, Any]) -> tuple[str, str]:
    doi = _text(record.get("doi"))
    if doi: return "DOI:" + doi.casefold(), "DOI"
    return "PAPER_ID:" + _text(record.get("paper_id"), "UNKNOWN"), "PAPER_ID_FALLBACK_UNVERIFIED"

def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None

def _mad(values: list[float]) -> float | None:
    centre = _median(values)
    return _median([abs(value-centre) for value in values]) if centre is not None else None

def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True)
                             if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()})

def summarize_observations(records: list[dict[str, Any]], minimum_studies: int = 3,
                           maximum_feature_pairs: int = 250) -> dict[str, Any]:
    """Return aggregate-only profiles and cautious exploratory signals."""
    if minimum_studies < 2 or maximum_feature_pairs < 1:
        raise ValueError("minimum_studies must be >= 2 and maximum_feature_pairs positive.")
    statuses: Counter[str] = Counter()
    papers: set[str] = set()
    verified_studies: set[str] = set()
    fallback_papers: set[str] = set()
    by_feature: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_study: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_condition: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    scope_features: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    paper_to_doi: dict[str, str] = {}
    for record in records:
        paper = _text(record.get("paper_id"), "UNKNOWN_PAPER")
        papers.add(paper)
        study_id, study_source = _study(record)
        if study_source == "DOI":
            verified_studies.add(study_id)
            paper_to_doi[paper] = study_id
        else:
            fallback_papers.add(paper)
        feature = _text(record.get("feature_id"), "UNKNOWN_FEATURE")
        unit = _text(record.get("resolved_unit"), "UNSPECIFIED_UNIT")
        status = _text(record.get("status"), "UNKNOWN_STATUS").upper()
        statuses[status] += 1
        by_feature[(feature, unit)].append(record)
        target_system = _text(record.get("target_system"), "UNKNOWN_SYSTEM")
        by_study[(feature, unit, study_id, target_system)].append(record)
        scope = (paper, _text(record.get("target_system"), "UNKNOWN_SYSTEM"),
                 _text(record.get("batch_id"), "NO_BATCH_ID"))
        scope_features[scope].add(feature)
        conditions = record.get("measurement_conditions")
        if isinstance(conditions, dict):
            for name, value in conditions.items():
                if value not in (None, "", [], {}): by_condition[(feature, _text(name))].append(record)

    feature_rows, study_rows, condition_rows, signals = [], [], [], []
    study_medians: dict[tuple[str, str, str], list[tuple[str, float, int]]] = defaultdict(list)
    for (feature, unit), items in sorted(by_feature.items()):
        nums = [n for item in items if (n := _number(item.get("resolved_value"))) is not None]
        eligible = [item for item in items
            if _text(item.get("status")).upper() == "AGREED_MATCH"
            and not item.get("requires_human_review")
            and _number(item.get("resolved_value")) is not None
            and _text(item.get("resolved_unit"))
            and item.get("source_origin") not in {"RECONCILIATION_CSV_ONLY", "RECONCILIATION_CSV_AMBIGUOUS"}]
        doi_ids = {_study(item)[0] for item in items if _study(item)[1] == "DOI"}
        feature_rows.append({
            "feature_id": feature, "unit": unit, "observation_count": len(items),
            "paper_count": len({_text(item.get("paper_id")) for item in items}),
            "verified_doi_study_count": len(doi_ids), "numeric_value_count": len(nums),
            "agreed_numeric_candidate_count": len(eligible),
            "human_review_count": sum(bool(x.get("requires_human_review")) for x in items),
            "status_counts": dict(sorted(Counter(_text(x.get("status"), "UNKNOWN").upper() for x in items).items())),
            "numeric_min": min(nums) if nums else None, "numeric_median": _median(nums),
            "numeric_max": max(nums) if nums else None})
    for (feature, unit, study_id, target_system), items in sorted(by_study.items()):
        vals = [n for item in items
            if _study(item)[1] == "DOI"
            and _text(item.get("status")).upper() == "AGREED_MATCH"
            and not item.get("requires_human_review")
            and _text(item.get("resolved_unit"))
            and _text(item.get("resolved_unit")) == unit
            and item.get("source_origin") not in {"RECONCILIATION_CSV_ONLY", "RECONCILIATION_CSV_AMBIGUOUS"}
            and (n := _number(item.get("resolved_value"))) is not None]
        study_rows.append({
            "feature_id": feature, "unit": unit, "study_group_id": study_id,
            "target_system": target_system,
            "study_identity_source": "DOI" if study_id.startswith("DOI:") else "PAPER_ID_FALLBACK_UNVERIFIED",
            "observation_count": len(items), "agreed_numeric_candidate_count": len(vals),
            "study_median": _median(vals)})
        if study_id.startswith("DOI:") and vals:
            study_medians[(feature, unit, target_system)].append((study_id, float(statistics.median(vals)), len(vals)))
    for (feature, condition), items in sorted(by_condition.items()):
        doi_ids = sorted({_study(x)[0] for x in items if _study(x)[1] == "DOI"})
        condition_rows.append({"feature_id": feature, "condition_type": condition,
            "observation_count_with_condition": len(items), "verified_doi_study_count": len(doi_ids),
            "paper_count": len({_text(x.get("paper_id")) for x in items})})
        if len(doi_ids) >= minimum_studies:
            signals.append({"signal_id": "COND-" + str(len(signals)+1).zfill(4),
                "signal_type": "CONDITION_COVERAGE_OPPORTUNITY", "feature_id": feature,
                "condition_type": condition, "supporting_observation_count": len(items),
                "supporting_study_count": len(doi_ids), "supporting_studies": doi_ids,
                "screening_status": "COVERAGE_ONLY_NO_EFFECT_ESTIMATED"})
    for (feature, unit, target_system), entries in sorted(study_medians.items()):
        if len(entries) < minimum_studies: continue
        vals = [x[1] for x in entries]
        signals.append({"signal_id": "HET-" + str(len(signals)+1).zfill(4),
            "signal_type": "CROSS_STUDY_DESCRIPTIVE_HETEROGENEITY", "feature_id": feature,
            "unit": unit, "target_system": target_system,
            "supporting_study_count": len(entries),
            "supporting_observation_count": sum(x[2] for x in entries),
            "study_median_min": min(vals), "study_median_median": _median(vals),
            "study_median_max": max(vals), "between_study_median_mad": _mad(vals),
            "supporting_studies": [x[0] for x in sorted(entries)],
            "screening_status": "DESCRIPTIVE_ONLY_ENDPOINT_COMPARABILITY_REVIEW_REQUIRED"})
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for (paper, _system, _batch), features in sorted(scope_features.items()):
        for left, right in itertools.combinations(sorted(features), 2):
            item = pairs.setdefault((left, right), {"studies": set(), "papers": set(), "scopes": 0})
            item["papers"].add(paper); item["scopes"] += 1
            if paper in paper_to_doi: item["studies"].add(paper_to_doi[paper])
    joint_rows = []
    for (left, right), item in sorted(pairs.items(),
        key=lambda pair: (-len(pair[1]["studies"]), -pair[1]["scopes"], pair[0]))[:maximum_feature_pairs]:
        studies = sorted(item["studies"])
        joint_rows.append({"feature_a": left, "feature_b": right,
            "verified_doi_study_count": len(studies), "paper_count": len(item["papers"]),
            "paper_system_batch_scope_count": item["scopes"], "supporting_studies": studies,
            "linkage_status": "CO_OCCURRENCE_ONLY_EXPERIMENTAL_LINKAGE_UNVERIFIED"})
        if len(studies) >= minimum_studies:
            signals.append({"signal_id": "PAIR-" + str(len(signals)+1).zfill(4),
                "signal_type": "CO_OBSERVED_FEATURE_PAIR_OPPORTUNITY", "feature_a": left,
                "feature_b": right, "supporting_study_count": len(studies),
                "paper_system_batch_scope_count": item["scopes"], "supporting_studies": studies,
                "screening_status": "CO_OCCURRENCE_ONLY_NOT_AN_INTERACTION"})
    signals.sort(key=lambda x: (-int(x.get("supporting_study_count", 0)),
                                x.get("signal_type", ""), x.get("feature_id", x.get("feature_a", ""))))
    profile = {"schema_version": "1.0", "profile_scope": "FULL_INPUT_DETERMINISTIC_EXPLORATORY_PROFILE",
        "observation_count": len(records), "unique_paper_count": len(papers),
        "verified_doi_study_count": len(verified_studies), "paper_id_fallback_count": len(fallback_papers),
        "feature_count": len({_text(x.get("feature_id"), "UNKNOWN_FEATURE") for x in records}),
        "status_counts": dict(sorted(statuses.items())), "feature_support_row_count": len(feature_rows),
        "condition_support_row_count": len(condition_rows), "joint_support_pair_count": len(joint_rows),
        "signals_count": len(signals), "minimum_studies_threshold": minimum_studies,
        "semantic_mapping_status": "PENDING_INSPECTION_OF_ACTUAL_CSV_AND_JSON"}
    limitations = [
        "Exploratory signals are not accepted scientific findings.",
        "DOI defines verified Study support; paper-ID fallbacks are unverified and excluded from cross-Study thresholds.",
        "Paper/system/batch co-occurrence does not prove experiment, specimen, or replicate linkage.",
        "Feature endpoint definitions and unit comparability require domain mapping review.",
        "No causal effects, p-values, FDR claims, or physical mechanisms are estimated.",
        "Novelty requires targeted literature review.",
        "The Agent brief contains aggregate summaries, not raw observations or paper text.",
        "Condition-performance contrasts are descriptive Study-level associations, not causal effects or inferential tests.",
        "Feature semantics remain unmapped; no feature identifier may be interpreted as a scientific endpoint until reviewed."]
    return {"profile": profile, "feature_rows": feature_rows, "study_rows": study_rows,
        "condition_rows": condition_rows, "joint_rows": joint_rows, "signals": signals,
        "limitations": limitations}

def run_discovery_scan(database_json: Path, reconciliation_csv: Path | None, output_dir: Path,
                       minimum_studies: int = 3, maximum_feature_pairs: int = 250) -> dict[str, Any]:
    """Run a read-only full-corpus scan, with JSON primary and optional reconciliation CSV."""
    database_json = database_json.expanduser().resolve()
    reconciliation_csv = reconciliation_csv.expanduser().resolve() if reconciliation_csv else None
    output_dir = output_dir.expanduser().resolve()
    inputs = [database_json] + ([reconciliation_csv] if reconciliation_csv else [])
    for source in inputs:
        if not source.is_file(): raise FileNotFoundError("Discovery input does not exist: " + str(source))
        if output_dir == source or source.is_relative_to(output_dir):
            raise ValueError("Discovery output directory cannot contain or replace an input.")
    if any(output_dir == source.parent for source in inputs):
        raise ValueError("Discovery output directory must be separate from source directories.")
    if output_dir.exists():
        if not output_dir.is_dir(): raise NotADirectoryError("Discovery output path is not a directory.")
        if any(output_dir.iterdir()): raise FileExistsError("Refusing to overwrite a non-empty discovery output directory.")
    source_hashes = {str(p): sha256_file(p) for p in inputs}
    _metadata, records = _load_json_observations(database_json)
    merge_issues = []
    if reconciliation_csv:
        records, merge_issues = _merge_ledger(records, _load_csv_observations(reconciliation_csv, "RECONCILIATION_CSV"))
    if not records: raise ValueError("The primary Chem-Literacy JSON contains no observations.")
    eligible_records = [record for record in records if not is_excluded_test_record(record)]
    excluded_test_observation_count = len(records) - len(eligible_records)
    summary = summarize_observations(eligible_records, minimum_studies, maximum_feature_pairs)
    summary["profile"]["input_observation_count"] = len(records)
    summary["profile"]["eligible_observation_count"] = len(eligible_records)
    summary["profile"]["excluded_test_observation_count"] = excluded_test_observation_count
    summary["profile"]["excluded_test_batch_ids"] = sorted(EXCLUDED_TEST_BATCH_IDS)
    for path, expected in source_hashes.items():
        if sha256_file(Path(path)) != expected: raise RuntimeError("Protected input changed during discovery scan: " + path)
    output_dir.mkdir(parents=True, exist_ok=True)
    condition_summary = write_condition_outputs(records, output_dir, source_hashes, minimum_studies=minimum_studies)
    (output_dir / "discovery_data_profile.json").write_text(
        json.dumps(summary["profile"], indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(output_dir / "feature_support.csv", [
        "feature_id","unit","observation_count","paper_count","verified_doi_study_count",
        "numeric_value_count","agreed_numeric_candidate_count","human_review_count","status_counts",
        "numeric_min","numeric_median","numeric_max"], summary["feature_rows"])
    _write_csv(output_dir / "study_coverage.csv", [
        "feature_id","unit","study_group_id","target_system","study_identity_source","observation_count",
        "agreed_numeric_candidate_count","study_median"], summary["study_rows"])
    _write_csv(output_dir / "condition_support.csv", [
        "feature_id","condition_type","observation_count_with_condition",
        "verified_doi_study_count","paper_count"], summary["condition_rows"])
    _write_csv(output_dir / "joint_support.csv", [
        "feature_a","feature_b","verified_doi_study_count","paper_count",
        "paper_system_batch_scope_count","supporting_studies","linkage_status"], summary["joint_rows"])
    _write_csv(output_dir / "signal_catalogue.csv", [
        "signal_id","signal_type","feature_id","unit","target_system","condition_type","feature_a","feature_b",
        "supporting_observation_count","supporting_study_count","study_median_min","study_median_median",
        "study_median_max","between_study_median_mad","paper_system_batch_scope_count",
        "screening_status","supporting_studies"], summary["signals"])
    merge_issue_counts = dict(sorted(Counter(
        _text(item.get("issue_code"), "UNKNOWN_ISSUE") for item in merge_issues
    ).items()))
    # The machine report stays aggregate-only: do not expose per-record JSON/CSV values
    # or thousands of Study identifiers to the Agent context.
    compact_signals = [
        {key: value for key, value in signal.items() if key != "supporting_studies"}
        for signal in summary["signals"]
    ]
    report = {"schema_version":"1.0",
        "discovery_status":"EXPLORATORY_SIGNALS_ONLY_NOT_ACCEPTED_SCIENTIFIC_FINDINGS",
        "research_opportunity_synthesis":"REQUIRES_AGENT_SCIENTIFIC_REVIEW",
        "novelty_assessment":"REQUIRES_TARGETED_LITERATURE_REVIEW",
        "profile":summary["profile"],"signals":compact_signals,
        "condition_extraction_summary":{
            key:value for key,value in condition_summary.items()
            if key != "condition_performance_analysis"
        },
        "condition_performance_analysis":condition_summary["condition_performance_analysis"],
        "source_merge_issue_count":len(merge_issues),"source_merge_issue_counts":merge_issue_counts,
        "limitations":summary["limitations"],"agent_brief_file":"agent_research_brief.md"}
    (output_dir / "discovery_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    brief = ["# DoR Scientific Discovery Brief", "",
        "> Aggregate-only Agent input. This is not an accepted scientific finding.", "",
        "## Dataset profile", "",
        f"- Eligible observations: {summary['profile']['observation_count']}",
        f"- Input observations before explicit test-batch exclusion: {summary['profile']['input_observation_count']}",
        f"- Excluded test observations: {summary['profile']['excluded_test_observation_count']}",
        f"- Papers: {summary['profile']['unique_paper_count']}",
        f"- DOI-verified Studies: {summary['profile']['verified_doi_study_count']}",
        f"- Unverified paper-ID fallbacks: {summary['profile']['paper_id_fallback_count']}",
        f"- Feature identifiers: {summary['profile']['feature_count']}",
        f"- Status distribution: {json.dumps(summary['profile']['status_counts'], ensure_ascii=False, sort_keys=True)}",
        f"- Semantic mapping: {summary['profile']['semantic_mapping_status']}", "",
        "## Feature support", "",
        "| Feature | Unit | Observations | DOI Studies | Agreed numeric candidates |",
        "|---|---|---:|---:|---:|"]
    for row in summary["feature_rows"][:100]:
        brief.append(f"| {row['feature_id']} | {row['unit']} | {row['observation_count']} | {row['verified_doi_study_count']} | {row['agreed_numeric_candidate_count']} |")
    brief.extend(["", "## Condition extraction overview", "",
        f"- Deterministic condition candidates (eligible data): {condition_summary['condition_record_count_eligible']}",
        f"- Eligible observations with reported target_system: {condition_summary['target_system_reported_observation_count']}",
        f"- target_system observations parsed by current rules: {condition_summary['target_system_parsed_observation_count']}",
        f"- Reported target_system values not matched by rules: {condition_summary['target_system_unparsed_reported_observation_count']}",
        f"- Bounded review queue rows written: {condition_summary['review_queue_row_count_written']} / {condition_summary['review_queue_total_count']}",
        "",
        "| Condition type | Candidate records |",
        "|---|---:|"])
    for condition_type, count in sorted(condition_summary["condition_type_counts_eligible"].items()):
        brief.append(f"| {condition_type} | {count} |")
    brief.extend(["", "Use condition_coverage.csv and condition_records.csv for aggregate coverage and source-level provenance. "
        "These are deterministic candidates, not human-accepted conditions.", ""])
    performance = condition_summary["condition_performance_analysis"]
    brief.extend(["", "## Condition-performance association screen", "",
        f"- Eligible numeric outcome observations: {performance['numeric_outcome_observation_count']}",
        f"- Outcome observations linked to candidate conditions: {performance['numeric_outcome_observations_linked_to_conditions']}",
        f"- DOI-level condition strata: {performance['condition_stratum_row_count']}",
        f"- Supported condition strata (minimum {minimum_studies} DOI Studies): {performance['supported_condition_stratum_count']}",
        f"- Descriptive contrasts: {performance['descriptive_contrast_count']}",
        f"- Hypothesis candidates requiring domain review: {performance['hypothesis_candidate_count']}",
        f"- Supported two-condition combinations: {performance['supported_joint_condition_combination_count']}",
        f"- Two-condition combination contrasts: {performance['joint_condition_combination_contrast_count']}",
        f"- Two-condition hypothesis candidates requiring review: {performance['joint_condition_hypothesis_candidate_count']}",
        "- Endpoint semantics: UNMAPPED_FEATURE_SEMANTICS; FEAT identifiers are not interpreted.",
        "- Contrasts are differences between Study-level medians, not p-values, causal effects, or evidence of mechanism.",
        "", "Files: condition_outcome_links.csv, condition_performance_study_strata.csv, "
        "condition_performance_strata.csv, condition_performance_contrasts.csv, and condition_hypothesis_candidates.csv.",
        "Joint condition files: condition_combination_performance.csv, condition_combination_contrasts.csv, "
        "and condition_combination_hypothesis_candidates.csv.",
        "- Two-condition combinations are only linked when both candidates appear on the same observation; do not describe them as synergy or fitted interactions.",
        "", "| Feature ID | Unit | Condition dimension | Supported levels | Study support | Median spread |",
        "|---|---|---|---:|---:|---:|"])
    for candidate in performance["hypothesis_candidates_preview"]:
        brief.append(f"| {candidate['feature_id']} | {candidate['outcome_unit']} | {candidate['condition_dimension']} | "
            f"{candidate['supported_condition_level_count']} | {candidate['total_doi_study_support_across_levels']} | "
            f"{candidate['observed_between_level_median_spread']} |")
    brief.extend(["", "## Condition linkage coverage by feature/unit", "",
        "| Feature ID | Unit | Eligible numeric observations | Linked observations | Linkage coverage | DOI Studies | Linked DOI Studies |",
        "|---|---|---:|---:|---:|---:|---:|"])
    for coverage in performance["feature_coverage_preview"]:
        brief.append(f"| {coverage['feature_id']} | {coverage['outcome_unit']} | "
            f"{coverage['eligible_numeric_outcome_observation_count']} | {coverage['condition_linked_observation_count']} | "
            f"{coverage['condition_linkage_coverage_fraction']:.1%} | {coverage['doi_study_count']} | "
            f"{coverage['condition_linked_doi_study_count']} |")
    brief.extend(["", "## Candidate signals", "", "| Signal | Type | Feature(s) | DOI Studies | Status |",
        "|---|---|---|---:|---|"])
    for signal in summary["signals"][:100]:
        feature = signal.get("feature_id") or (str(signal.get("feature_a", "")) + " x " + str(signal.get("feature_b", "")))
        if signal.get("condition_type"): feature += " / " + signal["condition_type"]
        brief.append(f"| {signal['signal_id']} | {signal['signal_type']} | {feature} | {signal.get('supporting_study_count', 0)} | {signal.get('screening_status', '')} |")
    brief.extend(["", "## Agent instructions", "",
        "1. Do not infer scientific meaning from FEAT identifiers alone; inspect the domain profile and flag unmapped fields.",
        "2. Treat descriptive spread as a candidate question, not a formal heterogeneity test.",
        "3. Treat feature-pair co-occurrence as a data-linkage opportunity, never as an interaction.",
        "4. Propose testable questions with Study support, confounders, counterexamples, and validation needs.",
        "5. Assess novelty only after targeted literature review.",
        "6. Recommend a direction based on scientific value and identifiability, not record count alone.",
        "7. Treat condition_records.csv values as deterministic candidates, not human-accepted facts; follow the evidence locator and confidence.",
        "8. Use condition_outcome_links.csv to trace each association back to observation IDs and condition_records.csv.",
        "9. Prioritize contrasts with within-DOI paired support, inspect paired direction/counterexample counts, and do not infer causal effects.",
        "10. Do not interpret percentage modifiers as dose levels unless the percentage basis is explicitly verified.", "",
        "## Limitations", ""])
    brief.extend("- " + item for item in summary["limitations"])
    (output_dir / "agent_research_brief.md").write_text("\n".join(brief) + "\n", encoding="utf-8")
    output_hashes = {p.name: sha256_file(p) for p in sorted(output_dir.iterdir()) if p.is_file()}
    manifest = {"schema_version":"1.0","operation":"dor discover-opportunities",
        "scope":"READ_ONLY_FULL_CORPUS_EXPLORATORY_SCAN",
        "inputs":[{"path":str(p),"sha256":source_hashes[str(p)]} for p in inputs],
        "observation_count":len(eligible_records),"input_observation_count":len(records),
        "excluded_test_observation_count":excluded_test_observation_count,
        "excluded_test_batch_ids":sorted(EXCLUDED_TEST_BATCH_IDS),"minimum_studies":minimum_studies,
        "maximum_feature_pairs":maximum_feature_pairs,"outputs":output_hashes,
        "source_files_modified":False,"raw_observations_in_agent_brief":False}
    (output_dir / "discovery_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status":report["discovery_status"],"output_dir":str(output_dir),
        "observation_count":len(eligible_records),"input_observation_count":len(records),
        "excluded_test_observation_count":excluded_test_observation_count,
        "condition_record_count":condition_summary["condition_record_count_eligible"],
        "condition_summary":str(output_dir / "condition_extraction_summary.json"),
        "condition_performance_analysis":condition_summary["condition_performance_analysis"],
        "paper_count":summary["profile"]["unique_paper_count"],
        "verified_doi_study_count":summary["profile"]["verified_doi_study_count"],
        "feature_count":summary["profile"]["feature_count"],"signal_count":len(summary["signals"]),
        "agent_brief":str(output_dir / "agent_research_brief.md"),
        "manifest":str(output_dir / "discovery_manifest.json")}
