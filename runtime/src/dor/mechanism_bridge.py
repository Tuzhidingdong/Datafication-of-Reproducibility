"""Evidence-linked mechanism hypothesis bridge for selected predictive interactions.

This module packages proposed explanations and validates source-evidence links. It never
infers a mechanism from a predictive interaction or upgrades a hypothesis into a conclusion.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from dor.canonical import validate_canonical_bundle
from dor.mapping import sha256_file
from dor.modeling import _load_cohort

ENGINE_VERSION = "dor-runtime/0.1.0"
PLAN_ORIGINS = {"USER_DRAFT", "AGENT_DRAFT", "WORKER_DRAFT"}
RELATIONSHIPS = {"SUPPORTS", "CONTRADICTS", "CONTEXTUAL"}
EVIDENCE_CLASSES = {
    "DIRECT_OBSERVATION", "THEORETICAL_SUPPORT", "PROSPECTIVE_VALIDATION",
    "METHOD_CONTEXT", "OTHER"
}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError("Required " + label + " file is missing: " + str(path))
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(label + " must be a JSON object.")
    return value


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(path + " must be a non-empty string.")
    return value.strip()


def _read_manifest_pair(directory: Path, report_name: str, manifest_name: str) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    report_path = directory / report_name
    manifest_path = directory / manifest_name
    report = _read_object(report_path, report_name)
    manifest = _read_object(manifest_path, manifest_name)
    expected = manifest.get("output_hashes", {}).get(report_name)
    actual = sha256_file(report_path)
    if not isinstance(expected, str) or expected != actual:
        raise ValueError(report_name + " hash does not match its manifest.")
    return report, manifest, report_path, manifest_path


def _check_input_hashes(manifest: dict[str, Any], expected: dict[str, str], label: str) -> None:
    inputs = manifest.get("input_hashes")
    if not isinstance(inputs, dict):
        raise ValueError(label + " manifest has no input_hashes object.")
    for key, value in expected.items():
        if inputs.get(key) != value:
            raise ValueError(label + " manifest input hash mismatch: " + key)


def _stable_id(prefix: str, *parts: str) -> str:
    joined = "|".join(parts)
    return prefix + "_" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20].upper()


def _validate_plan(plan: dict[str, Any], task: dict[str, Any], interaction_id: str) -> list[dict[str, Any]]:
    allowed = {
        "schema_version", "plan_id", "task_id", "target_id", "endpoint_definition",
        "interaction_id", "prepared_by", "proposal_origin", "mechanism_hypotheses", "notes"
    }
    unknown = sorted(set(plan) - allowed)
    if unknown:
        raise ValueError("Unsupported mechanism plan fields: " + ", ".join(unknown))
    if plan.get("schema_version") != "1.0":
        raise ValueError("mechanism_plan.schema_version must be 1.0.")
    for key in ("plan_id", "task_id", "target_id", "endpoint_definition", "interaction_id", "prepared_by"):
        _required_text(plan.get(key), "mechanism_plan." + key)
    if plan["task_id"] != task.get("task_id"):
        raise ValueError("Mechanism plan task_id does not match the modeling task.")
    if plan["target_id"] != task.get("target_id") or plan["endpoint_definition"] != task.get("endpoint_definition"):
        raise ValueError("Mechanism plan target/endpoint does not exactly match the modeling task.")
    if plan["interaction_id"] != interaction_id:
        raise ValueError("Mechanism plan interaction_id does not match the selected interaction.")
    if plan.get("proposal_origin") not in PLAN_ORIGINS:
        raise ValueError("proposal_origin must be USER_DRAFT, AGENT_DRAFT, or WORKER_DRAFT.")
    hypotheses = plan.get("mechanism_hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("mechanism_hypotheses must be a non-empty array.")
    seen: set[str] = set()
    for index, hypothesis in enumerate(hypotheses):
        prefix = "mechanism_hypotheses[" + str(index) + "]"
        if not isinstance(hypothesis, dict):
            raise ValueError(prefix + " must be an object.")
        permitted = {
            "hypothesis_id", "title", "hypothesis_statement", "proposed_process_chain",
            "scope_statement", "predicted_observations", "alternative_explanations",
            "unresolved_variables", "evidence_assessments"
        }
        extra = sorted(set(hypothesis) - permitted)
        if extra:
            raise ValueError(prefix + " contains unsupported fields: " + ", ".join(extra))
        hid = _required_text(hypothesis.get("hypothesis_id"), prefix + ".hypothesis_id")
        if hid in seen:
            raise ValueError("Duplicate hypothesis_id: " + hid)
        seen.add(hid)
        for key in ("title", "hypothesis_statement", "scope_statement"):
            _required_text(hypothesis.get(key), prefix + "." + key)
        for key in ("proposed_process_chain", "predicted_observations",
                    "alternative_explanations", "unresolved_variables"):
            items = hypothesis.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(prefix + "." + key + " must be an array of non-empty strings.")
        assessments = hypothesis.get("evidence_assessments", [])
        if not isinstance(assessments, list):
            raise ValueError(prefix + ".evidence_assessments must be an array.")
        evidence_seen: set[str] = set()
        for e_index, assessment in enumerate(assessments):
            epath = prefix + ".evidence_assessments[" + str(e_index) + "]"
            if not isinstance(assessment, dict):
                raise ValueError(epath + " must be an object.")
            if set(assessment) - {"evidence_id", "relationship", "evidence_class",
                                  "interpretation_summary", "observation_ids"}:
                raise ValueError(epath + " contains unsupported fields.")
            evidence_id = _required_text(assessment.get("evidence_id"), epath + ".evidence_id")
            if evidence_id in evidence_seen:
                raise ValueError(epath + " repeats an evidence_id within the same hypothesis.")
            evidence_seen.add(evidence_id)
            if assessment.get("relationship") not in RELATIONSHIPS:
                raise ValueError(epath + ".relationship is invalid.")
            if assessment.get("evidence_class") not in EVIDENCE_CLASSES:
                raise ValueError(epath + ".evidence_class is invalid.")
            _required_text(assessment.get("interpretation_summary"), epath + ".interpretation_summary")
            obs_ids = assessment.get("observation_ids", [])
            if not isinstance(obs_ids, list) or any(not isinstance(value, str) or not value.strip() for value in obs_ids):
                raise ValueError(epath + ".observation_ids must be an array of non-empty IDs.")
            if len(set(obs_ids)) != len(obs_ids):
                raise ValueError(epath + ".observation_ids must not contain duplicates.")
    return hypotheses


def _study_for_observation(observation: dict[str, Any], experiments: dict[str, dict[str, Any]]) -> str | None:
    experiment = experiments.get(observation.get("experiment_id"))
    value = experiment.get("study_id") if isinstance(experiment, dict) else None
    return value if isinstance(value, str) else None


def _assess_evidence(
    assessment: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    experiments: dict[str, dict[str, Any]],
    studies: dict[str, dict[str, Any]],
    discovery_study_ids: set[str],
    hypothesis_path: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    evidence_id = assessment["evidence_id"]
    source = evidence.get(evidence_id)
    if source is None:
        raise ValueError(hypothesis_path + " references unknown canonical Evidence ID " + evidence_id + ".")
    source_study_id = source.get("study_id")
    if not isinstance(source_study_id, str) or source_study_id not in studies:
        raise ValueError("Evidence " + evidence_id + " has no valid canonical Study reference.")
    locator = source.get("source_locator")
    if not isinstance(locator, dict) or not locator.get("source_file") or not locator.get("locator"):
        raise ValueError("Evidence " + evidence_id + " has no usable source locator.")

    obs_ids = assessment.get("observation_ids", [])
    linked_observations = []
    for observation_id in obs_ids:
        observation = observations.get(observation_id)
        if observation is None:
            raise ValueError("Evidence assessment references unknown Observation ID " + observation_id + ".")
        if evidence_id not in observation.get("evidence_ids", []):
            raise ValueError("Observation " + observation_id + " does not reference Evidence " + evidence_id + ".")
        observation_study = _study_for_observation(observation, experiments)
        if observation_study != source_study_id:
            raise ValueError("Evidence " + evidence_id + " and linked Observation " + observation_id + " belong to different Studies.")
        linked_observations.append({
            "observation_id": observation_id,
            "target_id": observation.get("target_id"),
            "endpoint_definition": observation.get("endpoint_definition"),
            "value_state": observation.get("value_state"),
            "study_id": observation_study
        })

    evidence_class = assessment["evidence_class"]
    relationship = assessment["relationship"]
    if evidence_class in {"DIRECT_OBSERVATION", "PROSPECTIVE_VALIDATION"}:
        if not obs_ids:
            raise ValueError(hypothesis_path + " must provide observation_ids for " + evidence_class + ".")
        if any(item["value_state"] != "REPORTED" for item in linked_observations):
            raise ValueError("Direct/prospective evidence must link only to REPORTED canonical observations.")

    extraction_status = source.get("extraction_status", "NOT_RECORDED")
    if extraction_status == "VERIFIED":
        verification = "VERIFIED"
    else:
        verification = "PENDING_SOURCE_VERIFICATION"
    independent = source_study_id not in discovery_study_ids
    counted = verification == "VERIFIED" and relationship in {"SUPPORTS", "CONTRADICTS"}
    not_counted_reason = None
    effective_class = evidence_class
    if verification != "VERIFIED":
        counted = False
        not_counted_reason = "CANONICAL_EVIDENCE_NOT_VERIFIED"
    elif evidence_class == "PROSPECTIVE_VALIDATION" and not independent:
        counted = False
        not_counted_reason = "PROSPECTIVE_SOURCE_STUDY_OVERLAPS_INTERACTION_DISCOVERY_COHORT"
        errors.append({
            "code": "PROSPECTIVE_EVIDENCE_NOT_INDEPENDENT",
            "evidence_id": evidence_id,
            "message": "Evidence is labelled prospective but its Study is part of the interaction-discovery cohort."
        })
    elif relationship == "CONTEXTUAL" or evidence_class in {"METHOD_CONTEXT", "OTHER"}:
        counted = False
        not_counted_reason = "CONTEXTUAL_OR_UNCLASSIFIED_EVIDENCE_NOT_COUNTED_AS_MECHANISM_SUPPORT"
    if relationship == "CONTEXTUAL" or evidence_class in {"METHOD_CONTEXT", "OTHER"}:
        effective_class = "CONTEXT_ONLY"
    elif evidence_class == "PROSPECTIVE_VALIDATION" and not independent:
        effective_class = "NOT_INDEPENDENT_PROSPECTIVE"
    elif verification != "VERIFIED":
        effective_class = "UNVERIFIED"

    study = studies[source_study_id]
    return {
        "evidence_id": evidence_id,
        "relationship": relationship,
        "evidence_class": evidence_class,
        "effective_class": effective_class,
        "interpretation_summary": assessment["interpretation_summary"],
        "study_id": source_study_id,
        "doi": study.get("doi"),
        "study_title": study.get("title"),
        "year": study.get("year"),
        "source_locator": locator,
        "canonical_evidence_type": source.get("evidence_type"),
        "quoted_text": source.get("quoted_text"),
        "extraction_status": extraction_status,
        "verification_status": verification,
        "independent_of_interaction_cohort": independent,
        "linked_observations": linked_observations,
        "counted_for_evidence_summary": counted,
        "not_counted_reason": not_counted_reason
    }, errors


def _evidence_status(assessments: list[dict[str, Any]]) -> tuple[str, dict[str, int], list[str], list[str]]:
    usable = [item for item in assessments if item["counted_for_evidence_summary"]]
    supporting = [item for item in usable if item["relationship"] == "SUPPORTS"]
    contradicting = [item for item in usable if item["relationship"] == "CONTRADICTS"]
    support_classes = {item["effective_class"] for item in supporting}
    counts = {
        "supporting_verified_evidence": len(supporting),
        "contradicting_verified_evidence": len(contradicting),
        "direct_observation_support": sum(1 for item in supporting if item["effective_class"] == "DIRECT_OBSERVATION"),
        "theoretical_support": sum(1 for item in supporting if item["effective_class"] == "THEORETICAL_SUPPORT"),
        "independent_prospective_support": sum(1 for item in supporting if item["effective_class"] == "PROSPECTIVE_VALIDATION"),
        "pending_source_verification": sum(1 for item in assessments if item["verification_status"] != "VERIFIED"),
        "contextual_or_unclassified": sum(1 for item in assessments if not item["counted_for_evidence_summary"])
    }
    if supporting and contradicting:
        status = "SUPPORT_AND_CONTRADICTION_RECORDED"
    elif contradicting:
        status = "CONTRADICTION_RECORDED"
    elif "PROSPECTIVE_VALIDATION" in support_classes:
        status = "INDEPENDENT_PROSPECTIVE_SUPPORT_RECORDED"
    elif "DIRECT_OBSERVATION" in support_classes and "THEORETICAL_SUPPORT" in support_classes:
        status = "DIRECT_AND_THEORETICAL_SUPPORT_RECORDED"
    elif "DIRECT_OBSERVATION" in support_classes:
        status = "DIRECT_OBSERVATION_SUPPORT_RECORDED"
    elif "THEORETICAL_SUPPORT" in support_classes:
        status = "THEORETICAL_SUPPORT_RECORDED"
    elif any(item["verification_status"] != "VERIFIED" for item in assessments):
        status = "EVIDENCE_REVIEW_REQUIRED"
    elif assessments:
        status = "NO_CLASSIFIED_MECHANISM_SUPPORT"
    else:
        status = "HYPOTHESIS_ONLY"
    support_studies = sorted({item["study_id"] for item in supporting})
    contradicting_ids = sorted({item["evidence_id"] for item in contradicting})
    return status, counts, support_studies, contradicting_ids


def build_mechanism_evidence_bridge_files(
    bundle_path: Path,
    cohort_dir: Path,
    task_path: Path,
    interaction_dir: Path,
    mechanism_plan_path: Path,
    output_dir: Path,
    robustness_dir: Path | None = None,
    response_surface_dir: Path | None = None,
) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve()
    cohort_dir = cohort_dir.expanduser().resolve()
    task_path = task_path.expanduser().resolve()
    interaction_dir = interaction_dir.expanduser().resolve()
    mechanism_plan_path = mechanism_plan_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    robustness_dir = robustness_dir.expanduser().resolve() if robustness_dir else None
    response_surface_dir = response_surface_dir.expanduser().resolve() if response_surface_dir else None

    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: " + str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty mechanism bridge output directory: " + str(output_dir))

    _rows_raw, task, _split_manifest, cohort_manifest = _load_cohort(cohort_dir, task_path)
    if task.get("outcome_type") != "NUMERIC":
        raise ValueError("The initial mechanism bridge requires a numeric-endpoint interaction catalogue.")
    bundle_hash = sha256_file(bundle_path)
    if cohort_manifest.get("bundle_sha256") != bundle_hash:
        raise ValueError("Canonical bundle hash does not match the bundle used to build the modeling cohort.")
    bundle = _read_object(bundle_path, "canonical bundle")
    integrity = validate_canonical_bundle(bundle)
    if not integrity.get("valid"):
        raise ValueError("Canonical bundle failed structural/reference validation: " +
                         "; ".join(item["code"] for item in integrity.get("errors", [])[:10]))

    interaction_report, interaction_manifest, interaction_report_path, interaction_manifest_path = _read_manifest_pair(
        interaction_dir, "interaction_discovery_report.json", "interaction_discovery_manifest.json")
    _check_input_hashes(interaction_manifest, {
        "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
        "task_sha256": sha256_file(task_path)
    }, "Interaction discovery")
    if interaction_report.get("target_id") != task.get("target_id") or interaction_report.get("endpoint_definition") != task.get("endpoint_definition") or interaction_report.get("task_id") != task.get("task_id"):
        raise ValueError("Interaction discovery report target/endpoint/task differs from current task.")
    plan = _read_object(mechanism_plan_path, "mechanism plan")
    interaction_id = _required_text(plan.get("interaction_id"), "mechanism_plan.interaction_id")
    selected = [item for item in interaction_report.get("interaction_catalogue", [])
                if item.get("interaction_id") == interaction_id]
    if len(selected) != 1:
        raise ValueError("Mechanism plan interaction_id does not identify exactly one interaction catalogue record.")
    interaction = selected[0]
    if interaction.get("interpretation_status") != "CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE":
        raise ValueError("Mechanism bridge only accepts an interaction labelled CROSS_STUDY_PREDICTIVE_INTERACTION_CANDIDATE.")
    task_feature_map = {item["feature_id"]: item for item in task["feature_bindings"]}
    for fid in (interaction.get("feature_a"), interaction.get("feature_b")):
        if fid not in task_feature_map:
            raise ValueError("Selected interaction references a feature not present in the exact modeling task.")
    hypotheses = _validate_plan(plan, task, interaction_id)
    discovery_study_ids = set(interaction.get("joint_coverage", {}).get("study_ids", []))
    if not discovery_study_ids:
        raise ValueError("Interaction catalogue does not contain joint-coverage Study IDs.")

    robustness_report = None
    robustness_manifest = None
    robustness_report_path = None
    robustness_manifest_path = None
    robustness_status = "NOT_SUPPLIED"
    if robustness_dir:
        robustness_report, robustness_manifest, robustness_report_path, robustness_manifest_path = _read_manifest_pair(
            robustness_dir, "interaction_robustness_report.json", "interaction_robustness_manifest.json")
        _check_input_hashes(robustness_manifest, {
            "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
            "task_sha256": sha256_file(task_path)
        }, "Interaction robustness")
        matches = [item for item in robustness_report.get("interaction_catalogue", [])
                   if item.get("interaction_id") == interaction_id]
        if len(matches) != 1:
            raise ValueError("Robustness report does not contain the selected interaction_id.")
        robustness_status = matches[0].get("robustness_status", "NOT_REPORTED")

    surface_report = None
    surface_manifest = None
    surface_report_path = None
    surface_manifest_path = None
    surface_status = "NOT_SUPPLIED"
    if response_surface_dir:
        surface_report, surface_manifest, surface_report_path, surface_manifest_path = _read_manifest_pair(
            response_surface_dir, "interaction_response_surface_report.json", "interaction_response_surface_manifest.json")
        _check_input_hashes(surface_manifest, {
            "cohort_sha256": sha256_file(cohort_dir / "modeling_cohort.csv"),
            "task_sha256": sha256_file(task_path),
            "interaction_discovery_report_sha256": sha256_file(interaction_report_path)
        }, "Interaction response surface")
        if surface_report.get("interaction_id") != interaction_id or surface_report.get("target_id") != task.get("target_id") or surface_report.get("endpoint_definition") != task.get("endpoint_definition"):
            raise ValueError("Response surface report does not match selected interaction and endpoint.")
        surface_status = surface_report.get("validation_scope", "DESCRIPTIVE_ONLY")

    studies = {item["study_id"]: item for item in bundle["studies"]}
    evidence = {item["evidence_id"]: item for item in bundle["evidence"]}
    observations = {item["observation_id"]: item for item in bundle["observations"]}
    experiments = {item["experiment_id"]: item for item in bundle["experiments"]}

    hypotheses_out = []
    findings_out = []
    ledger_rows = []
    review_rows = []
    for hypothesis in hypotheses:
        enriched = []
        for assessment in hypothesis.get("evidence_assessments", []):
            item, issues = _assess_evidence(assessment, evidence, observations, experiments, studies,
                                            discovery_study_ids, hypothesis["hypothesis_id"])
            item["hypothesis_id"] = hypothesis["hypothesis_id"]
            enriched.append(item)
            for issue in issues:
                review_rows.append({
                    "hypothesis_id": hypothesis["hypothesis_id"], "issue_code": issue["code"],
                    "evidence_id": issue["evidence_id"], "review_action": "VERIFY_INDEPENDENCE_OR_RECLASSIFY",
                    "detail": issue["message"]
                })
            if item["verification_status"] != "VERIFIED":
                review_rows.append({
                    "hypothesis_id": hypothesis["hypothesis_id"], "issue_code": "EVIDENCE_NOT_VERIFIED",
                    "evidence_id": item["evidence_id"], "review_action": "CHECK_ORIGINAL_SOURCE_AND_UPDATE_CANONICAL_EVIDENCE",
                    "detail": "Canonical extraction_status is " + str(item["extraction_status"]) + "; this item is not counted as verified mechanism evidence."
                })
            ledger_rows.append({
                "hypothesis_id": hypothesis["hypothesis_id"], "evidence_id": item["evidence_id"],
                "relationship": item["relationship"], "evidence_class": item["evidence_class"],
                "effective_class": item["effective_class"], "study_id": item["study_id"],
                "doi": item["doi"], "source_file": item["source_locator"].get("source_file"),
                "locator_type": item["source_locator"].get("locator_type"),
                "locator": item["source_locator"].get("locator"),
                "extraction_status": item["extraction_status"], "verification_status": item["verification_status"],
                "independent_of_interaction_cohort": item["independent_of_interaction_cohort"],
                "counted_for_evidence_summary": item["counted_for_evidence_summary"],
                "not_counted_reason": item["not_counted_reason"],
                "interpretation_summary": item["interpretation_summary"]
            })
        status, counts, supporting_studies, contradicting_ids = _evidence_status(enriched)
        mechanism_id = _stable_id("MEC", plan["plan_id"], hypothesis["hypothesis_id"], interaction_id)
        finding_id = _stable_id("FND", mechanism_id)
        limitations = [
            "This record is a proposed mechanism hypothesis linked to a predictive statistical interaction; the interaction does not establish causality or a physical mechanism.",
            "All-cohort response surfaces, when supplied, are descriptive refits and are not independent validation evidence.",
            "Evidence status reflects the explicit classifications and canonical extraction-verification states supplied for review; it is not an automatic truth ranking.",
            "Study-grouped validation and repeated split seeds do not remove hidden dependence or confounding between distinct Studies."
        ] + list(hypothesis.get("unresolved_variables", []))
        manuscript_wording = (
            "The predictive interaction between " + interaction["feature_a"] + " and " + interaction["feature_b"] +
            " motivates the testable hypothesis that " + hypothesis["hypothesis_statement"] +
            " This remains a mechanism hypothesis and should not be interpreted as an established causal explanation."
        )
        finding = {
            "schema_version": "1.0", "finding_id": finding_id,
            "claim_type": "mechanism_hypothesis", "claim": hypothesis["hypothesis_statement"],
            "status": "candidate", "target_id": task["target_id"],
            "interaction_ids": [interaction_id], "model_ids": [],
            "supporting_artifacts": [
                "interaction_discovery_report.json#interaction_catalogue/" + interaction_id
            ] + ["canonical_bundle.json#evidence/" + item["evidence_id"] for item in enriched
                 if item["relationship"] == "SUPPORTS" and item["counted_for_evidence_summary"]],
            "supporting_studies": supporting_studies,
            "contradicting_evidence": contradicting_ids,
            "mechanism_status": "hypothesis",
            "limitations": limitations,
            "manuscript_wording": manuscript_wording
        }
        findings_out.append(finding)
        hypotheses_out.append({
            "mechanism_id": mechanism_id, "finding_id": finding_id,
            "hypothesis_id": hypothesis["hypothesis_id"], "title": hypothesis["title"],
            "hypothesis_statement": hypothesis["hypothesis_statement"],
            "proposed_process_chain": hypothesis.get("proposed_process_chain", []),
            "scope_statement": hypothesis["scope_statement"],
            "predicted_observations": hypothesis.get("predicted_observations", []),
            "alternative_explanations": hypothesis.get("alternative_explanations", []),
            "unresolved_variables": hypothesis.get("unresolved_variables", []),
            "evidence_status": status, "evidence_counts": counts,
            "supporting_study_ids": supporting_studies,
            "contradicting_evidence_ids": contradicting_ids,
            "evidence_assessments": enriched,
            "review_state": "PENDING_G3_USER_REVIEW",
            "manuscript_wording": manuscript_wording,
            "limitations": limitations
        })

    report = {
        "schema_version": "1.0", "plan_id": plan["plan_id"], "prepared_by": plan["prepared_by"],
        "proposal_origin": plan["proposal_origin"], "task_id": task["task_id"],
        "target_id": task["target_id"], "endpoint_definition": task["endpoint_definition"],
        "interaction_id": interaction_id,
        "interaction": {
            "feature_a": interaction["feature_a"], "feature_b": interaction["feature_b"],
            "interpretation_status": interaction["interpretation_status"],
            "mean_fold_rmse_improvement": interaction.get("mean_fold_rmse_improvement"),
            "positive_improvement_fold_fraction": interaction.get("positive_improvement_fold_fraction"),
            "discovery_study_ids": sorted(discovery_study_ids)
        },
        "robustness_status": robustness_status,
        "response_surface_scope": surface_status,
        "evidence_label_contract": {
            "E0_STATISTICAL": "Predictive statistical interaction candidate from the interaction-discovery report.",
            "E1_CROSS_STUDY": "Split-seed and Study-held-out predictive stability indicators; not independent causal evidence.",
            "E2_DIRECT_OBSERVATION": "Verified canonical Evidence linked to REPORTED Observation records and explicitly classified as direct observation.",
            "E3_THEORETICAL_SUPPORT": "Verified canonical Evidence explicitly classified as theoretical, simulation, or mechanistic calculation support.",
            "E4_PROSPECTIVE_VALIDATION": "Verified prospective Evidence from a Study outside the interaction-discovery cohort, linked to REPORTED observation records."
        },
        "mechanism_catalogue": hypotheses_out,
        "review_queue": review_rows,
        "review_issue_count": len(review_rows),
        "claim_scope": "EXPLICIT_EVIDENCE_LINKED_MECHANISM_HYPOTHESES_PENDING_G3_REVIEW_NOT_AUTOMATIC_MECHANISM_DISCOVERY",
        "review_state": "PENDING_G3_USER_REVIEW",
        "interpretation_limits": [
            "The engine does not generate mechanism hypotheses; it packages explicitly supplied hypotheses and evidence assessments.",
            "A predictive interaction or seed-stable label is not a causal effect, physical synergy, or mechanism.",
            "Evidence classes are descriptive categories, not a universal ordinal evidence hierarchy.",
            "Direct observation support is counted only when VERIFIED canonical Evidence is linked to REPORTED Observation records.",
            "Prospective support is counted only when the evidence Study is outside the interaction-discovery Study cohort and has linked REPORTED observations.",
            "Unverified, conflicting, or unrecorded extraction status is retained for review and never counted as verified support.",
            "Contradictory evidence remains visible and is never averaged away or silently discarded.",
            "A response surface is descriptive model output and cannot be used as direct or theoretical mechanism evidence."
        ],
        "validation_scope": "STRUCTURAL_EVIDENCE_LINK_VALIDATION_AND_HYPOTHESIS_PACKAGING_NOT_CAUSAL_OR_MECHANISM_VERIFICATION"
    }

    findings_package = {
        "schema_version": "1.0", "task_id": task["task_id"], "interaction_id": interaction_id,
        "finding_count": len(findings_out), "findings": findings_out,
        "claim_scope": "ALL_FINDINGS_REMAIN_MECHANISM_HYPOTHESES_PENDING_G3_USER_REVIEW"
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "mechanism_evidence_bridge_report.json"
    findings_path = output_dir / "mechanism_findings.json"
    ledger_path = output_dir / "mechanism_evidence_ledger.csv"
    review_path = output_dir / "mechanism_review_queue.csv"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    findings_path.write_text(json.dumps(findings_package, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    ledger_fields = [
        "hypothesis_id", "evidence_id", "relationship", "evidence_class", "effective_class",
        "study_id", "doi", "source_file", "locator_type", "locator", "extraction_status",
        "verification_status", "independent_of_interaction_cohort", "counted_for_evidence_summary",
        "not_counted_reason", "interpretation_summary"
    ]
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ledger_fields)
        writer.writeheader()
        writer.writerows(ledger_rows)
    review_fields = ["hypothesis_id", "issue_code", "evidence_id", "review_action", "detail"]
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        writer.writerows(review_rows)

    input_paths = {
        "canonical_bundle_sha256": bundle_path,
        "task_sha256": task_path,
        "mechanism_plan_sha256": mechanism_plan_path,
        "cohort_sha256": cohort_dir / "modeling_cohort.csv",
        "cohort_report_sha256": cohort_dir / "cohort_report.json",
        "split_manifest_sha256": cohort_dir / "split_manifest.json",
        "cohort_manifest_sha256": cohort_dir / "modeling_cohort_manifest.json",
        "interaction_report_sha256": interaction_report_path,
        "interaction_manifest_sha256": interaction_manifest_path
    }
    if robustness_report_path and robustness_manifest_path:
        input_paths["robustness_report_sha256"] = robustness_report_path
        input_paths["robustness_manifest_sha256"] = robustness_manifest_path
    if surface_report_path and surface_manifest_path:
        input_paths["response_surface_report_sha256"] = surface_report_path
        input_paths["response_surface_manifest_sha256"] = surface_manifest_path
    input_hashes = {key: sha256_file(path) for key, path in input_paths.items()}
    output_names = [report_path.name, findings_path.name, ledger_path.name, review_path.name]
    output_hashes = {name: sha256_file(output_dir / name) for name in output_names}
    manifest = {
        "schema_version": "1.0", "engine_version": ENGINE_VERSION,
        "plan_id": plan["plan_id"], "task_id": task["task_id"], "interaction_id": interaction_id,
        "input_hashes": input_hashes, "output_hashes": output_hashes,
        "mechanism_hypothesis_count": len(hypotheses_out),
        "evidence_assessment_count": len(ledger_rows),
        "review_issue_count": len(review_rows),
        "claim_scope": report["claim_scope"],
        "source_policy": "CANONICAL_BUNDLE_COHORT_TASK_INTERACTION_PLAN_AND_OPTIONAL_ANALYSIS_PACKAGES_READ_ONLY"
    }
    manifest_path = output_dir / "mechanism_evidence_bridge_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    for key, path in input_paths.items():
        if sha256_file(path) != input_hashes[key]:
            raise RuntimeError("An input changed during mechanism bridge construction: " + key)

    return {"valid": True, "report": report, "findings": findings_package,
            "manifest": manifest, "output_dir": str(output_dir)}
