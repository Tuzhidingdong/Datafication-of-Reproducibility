"""Deterministic, endpoint-specific modelling cohort construction and study-level splits."""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
from typing import Any
from dor.canonical import validate_canonical_bundle
from dor.mapping import sha256_file

OUTCOME_FIELDS = {"raw_value", "normalized_value"}
RESERVED_FEATURE_IDS = {"cohort_row_id", "study_id", "system_id", "experiment_id", "observation_id", "target_id", "endpoint_definition", "outcome_value", "outcome_unit", "split"}

def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def _row_id(task_id: str, observation_id: str) -> str:
    return "COH_" + hashlib.sha256((task_id + "|" + observation_id).encode("utf-8")).hexdigest()[:20].upper()

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

def _validate_task(task: Any) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(task, dict):
        return [{"code":"TASK_NOT_OBJECT","path":"$","message":"Modeling task must be an object."}]
    if task.get("schema_version") != "1.0":
        errors.append({"code":"UNSUPPORTED_TASK_SCHEMA","path":"schema_version","message":"Expected modeling task schema_version 1.0."})
    for field in ("task_id", "target_id", "endpoint_definition"):
        value = task.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append({"code":"TASK_FIELD_REQUIRED","path":field,"message":field + " must be a non-empty string."})
    if task.get("outcome_type") not in {"NUMERIC","CATEGORICAL"}:
        errors.append({"code":"INVALID_OUTCOME_TYPE","path":"outcome_type","message":"outcome_type must be NUMERIC or CATEGORICAL."})
    if task.get("outcome_value_field") not in OUTCOME_FIELDS:
        errors.append({"code":"INVALID_OUTCOME_VALUE_FIELD","path":"outcome_value_field","message":"outcome_value_field must be raw_value or normalized_value."})
    if "outcome_unit" not in task or (task.get("outcome_unit") is not None and not isinstance(task.get("outcome_unit"), str)):
        errors.append({"code":"INVALID_OUTCOME_UNIT","path":"outcome_unit","message":"outcome_unit must be an exact string or null."})
    bindings = task.get("feature_bindings")
    if not isinstance(bindings, list) or not bindings:
        errors.append({"code":"FEATURE_BINDINGS_REQUIRED","path":"feature_bindings","message":"At least one explicit feature binding is required."})
        bindings = []
    seen: set[str] = set()
    for index, binding in enumerate(bindings):
        path = "feature_bindings[" + str(index) + "]"
        if not isinstance(binding, dict):
            errors.append({"code":"FEATURE_BINDING_NOT_OBJECT","path":path,"message":"Feature binding must be an object."})
            continue
        fid = binding.get("feature_id")
        if not isinstance(fid, str) or not fid.strip():
            errors.append({"code":"FEATURE_ID_REQUIRED","path":path+".feature_id","message":"feature_id must be a non-empty string."})
        elif fid in seen or fid in RESERVED_FEATURE_IDS:
            errors.append({"code":"FEATURE_ID_DUPLICATE_OR_RESERVED","path":path+".feature_id","message":"feature_id must be unique and must not collide with a cohort metadata column."})
        else:
            seen.add(fid)
        if not isinstance(binding.get("condition_type"), str) or not binding["condition_type"].strip():
            errors.append({"code":"FEATURE_BINDING_FIELD_REQUIRED","path":path+".condition_type","message":"condition_type must be a non-empty exact-match string."})
        if binding.get("value_field") not in OUTCOME_FIELDS:
            errors.append({"code":"INVALID_FEATURE_VALUE_FIELD","path":path+".value_field","message":"value_field must be raw_value or normalized_value."})
        if binding.get("value_type") not in {"NUMERIC","CATEGORICAL"}:
            errors.append({"code":"INVALID_FEATURE_VALUE_TYPE","path":path+".value_type","message":"value_type must be NUMERIC or CATEGORICAL."})
        if "expected_unit" not in binding or (binding.get("expected_unit") is not None and not isinstance(binding.get("expected_unit"), str)):
            errors.append({"code":"INVALID_FEATURE_UNIT","path":path+".expected_unit","message":"expected_unit must be an exact string or null."})
    split = task.get("split")
    if not isinstance(split, dict):
        errors.append({"code":"SPLIT_SPEC_REQUIRED","path":"split","message":"An explicit study-level split specification is required."})
    else:
        strategy = split.get("strategy")
        if strategy not in {"GROUPED_HOLDOUT","EXPLICIT_STUDIES"}:
            errors.append({"code":"INVALID_SPLIT_STRATEGY","path":"split.strategy","message":"strategy must be GROUPED_HOLDOUT or EXPLICIT_STUDIES."})
        seed = split.get("seed", 42)
        if not isinstance(seed, int) or isinstance(seed, bool):
            errors.append({"code":"INVALID_SPLIT_SEED","path":"split.seed","message":"seed must be an integer."})
        if strategy == "GROUPED_HOLDOUT":
            fractions = split.get("fractions")
            if not isinstance(fractions, dict):
                errors.append({"code":"SPLIT_FRACTIONS_REQUIRED","path":"split.fractions","message":"GROUPED_HOLDOUT requires train, validation, and test fractions."})
            else:
                values = [fractions.get(k) for k in ("train","validation","test")]
                if any(not _is_number(v) or float(v) <= 0 or float(v) >= 1 for v in values) or abs(sum(float(v) for v in values if _is_number(v))-1.0) > 1e-9:
                    errors.append({"code":"INVALID_SPLIT_FRACTIONS","path":"split.fractions","message":"train, validation, and test fractions must be positive and sum to 1."})
        if strategy == "EXPLICIT_STUDIES":
            for field in ("validation_study_ids","test_study_ids"):
                values = split.get(field)
                if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() for v in values) or len(set(values)) != len(values):
                    errors.append({"code":"INVALID_EXPLICIT_STUDY_IDS","path":"split."+field,"message":field+" must be a non-empty list of unique non-empty study IDs."})
    return errors

def _split_studies(study_ids: list[str], split_spec: dict[str, Any]) -> tuple[dict[str,str] | None,list[dict[str,str]]]:
    errors: list[dict[str,str]] = []
    unique_ids = sorted(set(study_ids))
    assignment: dict[str,str] = {}
    strategy = split_spec.get("strategy")
    if strategy == "EXPLICIT_STUDIES":
        validation, test = split_spec.get("validation_study_ids",[]), split_spec.get("test_study_ids",[])
        if set(validation).intersection(test):
            errors.append({"code":"STUDY_SPLIT_OVERLAP","path":"split","message":"A study cannot appear in both validation and test sets."})
        unknown = sorted((set(validation)|set(test))-set(unique_ids))
        if unknown:
            errors.append({"code":"UNKNOWN_OR_INELIGIBLE_STUDY_ID","path":"split","message":"Explicit study IDs are not present in the eligible cohort: "+", ".join(unknown)})
        if errors:
            return None, errors
        for sid in unique_ids:
            assignment[sid] = "test" if sid in test else ("validation" if sid in validation else "train")
    elif strategy == "GROUPED_HOLDOUT":
        if len(unique_ids) < 3:
            return None,[{"code":"INSUFFICIENT_STUDIES_FOR_THREE_WAY_SPLIT","path":"split","message":"At least three eligible studies are required for train/validation/test study-level holdout."}]
        fractions=split_spec["fractions"]
        names=("train","validation","test")
        raw={name:len(unique_ids)*float(fractions[name]) for name in names}
        counts={name:int(math.floor(raw[name])) for name in names}
        remainder_order=sorted(names,key=lambda name:(-(raw[name]-counts[name]),names.index(name)))
        for name in remainder_order[:len(unique_ids)-sum(counts.values())]:
            counts[name]+=1
        for name in names:
            if counts[name]==0:
                donor=max(names,key=lambda candidate:counts[candidate])
                if counts[donor]<=1:
                    return None,[{"code":"INVALID_GROUP_SPLIT_COUNTS","path":"split.fractions","message":"Fractions cannot allocate at least one study to each partition."}]
                counts[donor]-=1
                counts[name]+=1
        seed=split_spec.get("seed",42)
        ordered=sorted(unique_ids,key=lambda sid:hashlib.sha256((str(seed)+":"+sid).encode("utf-8")).hexdigest())
        cursor=0
        for name in names:
            for sid in ordered[cursor:cursor+counts[name]]:
                assignment[sid]=name
            cursor+=counts[name]
    else:
        return None,[{"code":"INVALID_SPLIT_STRATEGY","path":"split.strategy","message":"Unsupported study-level split strategy."}]
    if not {"train","validation","test"}.issubset(set(assignment.values())):
        return None,[{"code":"EMPTY_SPLIT","path":"split","message":"Each train, validation, and test partition must contain at least one eligible study."}]
    return assignment,[]

def build_modeling_cohort(bundle: Any, task: Any, bundle_sha256: str | None = None,
                          task_sha256: str | None = None) -> tuple[list[dict[str,Any]] | None,dict[str,Any],dict[str,Any] | None]:
    """Build one exact-endpoint cohort; no implicit mapping, unit conversion, imputation, or aggregation."""
    task_errors=_validate_task(task)
    if task_errors:
        return None,{"valid":False,"errors":task_errors,"validation_scope":"TASK_CONTRACT_VALIDATION"},None
    integrity=validate_canonical_bundle(bundle)
    if not integrity.get("valid"):
        return None,{"valid":False,"errors":integrity.get("errors",[]),"validation_scope":"CANONICAL_INTEGRITY_REQUIRED"},None
    experiments={item["experiment_id"]:item for item in bundle["experiments"]}
    conditions={item["condition_id"]:item for item in bundle["conditions"]}
    task_id,target_id,endpoint=task["task_id"],task["target_id"],task["endpoint_definition"]
    outcome_field=task["outcome_value_field"]
    outcome_unit=task["outcome_unit"]
    unit_field="raw_unit" if outcome_field=="raw_value" else "normalized_unit"
    excluded: list[dict[str,str]]=[]
    selected: list[dict[str,Any]]=[]
    def exclude(oid: str,code: str,detail: str) -> None:
        excluded.append({"observation_id":oid,"reason":code,"detail":detail})
    target_observations=[item for item in bundle["observations"] if item.get("target_id")==target_id]
    for observation in target_observations:
        oid=observation["observation_id"]
        if observation.get("endpoint_definition") != endpoint:
            exclude(oid,"ENDPOINT_DEFINITION_NOT_EXACT_MATCH","Observation endpoint_definition does not exactly match the task.")
            continue
        if observation.get("value_state") != "REPORTED":
            exclude(oid,"OUTCOME_NOT_REPORTED","Only REPORTED observations are eligible; no imputation is performed.")
            continue
        value=observation.get(outcome_field)
        if task["outcome_type"]=="NUMERIC" and not _is_number(value):
            exclude(oid,"OUTCOME_NOT_VALID_NUMERIC","The selected outcome field is not a finite numeric value.")
            continue
        if task["outcome_type"]=="CATEGORICAL" and (value is None or isinstance(value,(dict,list))):
            exclude(oid,"OUTCOME_NOT_VALID_CATEGORICAL","The selected outcome field must be a non-null scalar.")
            continue
        if observation.get(unit_field) != outcome_unit:
            exclude(oid,"OUTCOME_UNIT_NOT_EXACT_MATCH","Outcome unit does not exactly match the task; no implicit conversion is performed.")
            continue
        experiment=experiments[observation["experiment_id"]]
        feature_values: dict[str,Any]={}
        feature_error: tuple[str,str] | None=None
        for binding in task["feature_bindings"]:
            fid=binding["feature_id"]
            matches=[conditions[cid] for cid in experiment.get("condition_ids",[]) if conditions[cid].get("condition_type")==binding["condition_type"]]
            if len(matches)==0:
                feature_error=("FEATURE_CONDITION_NOT_FOUND","No linked condition has exact condition_type "+binding["condition_type"]+".")
                break
            if len(matches)>1:
                feature_error=("FEATURE_CONDITION_MULTIPLE","More than one linked condition has condition_type "+binding["condition_type"]+"; explicit resolution is required.")
                break
            condition=matches[0]
            if condition.get("value_state")!="REPORTED":
                feature_error=("FEATURE_VALUE_NOT_REPORTED","Linked feature condition is not in REPORTED state.")
                break
            field=binding["value_field"]
            expected_unit=binding["expected_unit"]
            feature_value=condition.get(field)
            if binding["value_type"]=="NUMERIC" and not _is_number(feature_value):
                feature_error=("FEATURE_VALUE_NOT_VALID_NUMERIC","Feature "+fid+" is not a finite numeric value.")
                break
            if binding["value_type"]=="CATEGORICAL" and (feature_value is None or isinstance(feature_value,(dict,list))):
                feature_error=("FEATURE_VALUE_NOT_VALID_CATEGORICAL","Feature "+fid+" must be a non-null scalar.")
                break
            feature_unit_key="raw_unit" if field=="raw_value" else "normalized_unit"
            if condition.get(feature_unit_key)!=expected_unit:
                feature_error=("FEATURE_UNIT_NOT_EXACT_MATCH","Feature "+fid+" unit does not exactly match expected_unit.")
                break
            feature_values[fid]=feature_value
        if feature_error:
            exclude(oid,feature_error[0],feature_error[1])
            continue
        selected.append({
            "cohort_row_id":_row_id(task_id,oid),"study_id":experiment["study_id"],
            "system_id":experiment["system_id"],"experiment_id":experiment["experiment_id"],
            "observation_id":oid,"target_id":target_id,"endpoint_definition":endpoint,
            "outcome_value":value,"outcome_unit":outcome_unit,"feature_values":feature_values
        })
    selected.sort(key=lambda row:(row["study_id"],row["experiment_id"],row["observation_id"]))
    if not selected:
        return None,{"valid":False,"errors":[{"code":"EMPTY_ELIGIBLE_COHORT","path":"observations","message":"No observations satisfy the exact task, endpoint, outcome, unit, and feature-binding rules."}],
            "excluded_count":len(excluded),"excluded":excluded,"validation_scope":"NO_MODELING_COHORT_CREATED"},None
    assignment,split_errors=_split_studies([row["study_id"] for row in selected],task["split"])
    if split_errors:
        return None,{"valid":False,"errors":split_errors,"excluded_count":len(excluded),"excluded":excluded,
            "eligible_observation_count":len(selected),"eligible_study_count":len({row["study_id"] for row in selected}),
            "validation_scope":"NO_MODELING_COHORT_CREATED"},None
    for row in selected:
        row["split"]=assignment[row["study_id"]]
    split_manifest={
        "schema_version":"1.0","task_id":task_id,"study_group_field":"study_id",
        "strategy":task["split"]["strategy"],"seed":task["split"].get("seed",42),
        "study_to_split":dict(sorted(assignment.items())),
        "observation_ids_by_split":{name:[row["observation_id"] for row in selected if row["split"]==name] for name in ("train","validation","test")},
        "leakage_check":{"valid":True,"study_overlap_count":0,
            "study_ids_by_split":{name:sorted(sid for sid,partition in assignment.items() if partition==name) for name in ("train","validation","test")}},
        "validation_scope":"DETERMINISTIC_GROUPED_STUDY_SPLIT_NOT_SCIENTIFIC_VALIDATION"
    }
    report={
        "valid":True,"task_id":task_id,"target_id":target_id,"endpoint_definition":endpoint,
        "outcome_type":task["outcome_type"],"outcome_value_field":outcome_field,"outcome_unit":outcome_unit,
        "feature_count":len(task["feature_bindings"]),
        "feature_coverage":{b["feature_id"]:{"eligible_observation_count":len(selected),"missing_count":0,
            "condition_type":b["condition_type"],"value_field":b["value_field"],"expected_unit":b["expected_unit"]} for b in task["feature_bindings"]},
        "eligible_observation_count":len(selected),"eligible_study_count":len(assignment),
        "excluded_count":len(excluded),
        "excluded_by_reason":{reason:sum(1 for item in excluded if item["reason"]==reason) for reason in sorted({item["reason"] for item in excluded})},
        "excluded":excluded,
        "split_counts":{name:{"study_count":len(split_manifest["leakage_check"]["study_ids_by_split"][name]),
            "observation_count":len(split_manifest["observation_ids_by_split"][name])} for name in ("train","validation","test")},
        "bundle_sha256":bundle_sha256,"task_sha256":task_sha256,
        "validation_scope":"EXACT_ENDPOINT_COHORT_AND_DETERMINISTIC_STUDY_LEVEL_SPLIT_NOT_MODEL_FIT_OR_SCIENTIFIC_VALIDATION"
    }
    return selected,report,split_manifest

def build_modeling_cohort_files(bundle_path: Path,task_path: Path,output_dir: Path) -> dict[str,Any]:
    """Read exact inputs, verify they remain unchanged, then write a new derived cohort package."""
    output_dir=output_dir.expanduser().resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError("Output path exists and is not a directory: "+str(output_dir))
        if any(output_dir.iterdir()):
            raise FileExistsError("Refusing to overwrite a non-empty output directory: "+str(output_dir))
    bundle_path=bundle_path.expanduser().resolve()
    task_path=task_path.expanduser().resolve()
    bundle_hash=sha256_file(bundle_path)
    task_hash=sha256_file(task_path)
    with bundle_path.open("r",encoding="utf-8-sig") as handle:
        bundle=json.load(handle)
    with task_path.open("r",encoding="utf-8-sig") as handle:
        task=json.load(handle)
    if sha256_file(bundle_path)!=bundle_hash or sha256_file(task_path)!=task_hash:
        raise RuntimeError("An input file changed while it was being read; refusing to build a cohort.")
    rows,report,split_manifest=build_modeling_cohort(bundle,task,bundle_hash,task_hash)
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/"cohort_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    if rows is None or split_manifest is None:
        return {"valid":False,"report":report,"output_dir":str(output_dir)}
    feature_ids=[binding["feature_id"] for binding in task["feature_bindings"]]
    columns=["cohort_row_id","study_id","system_id","experiment_id","observation_id","target_id",
        "endpoint_definition","outcome_value","outcome_unit","split"]+feature_ids
    with (output_dir/"modeling_cohort.csv").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=columns)
        writer.writeheader()
        for row in rows:
            output={key:row[key] for key in columns if key in row}
            output.update(row["feature_values"])
            writer.writerow(output)
    (output_dir/"split_manifest.json").write_text(json.dumps(split_manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    manifest={"schema_version":"1.0","task_id":task["task_id"],"bundle_sha256":bundle_hash,"task_sha256":task_hash,
        "artifacts":["modeling_cohort.csv","cohort_report.json","split_manifest.json"],
        "eligible_observation_count":len(rows),"eligible_study_count":report["eligible_study_count"],
        "source_policy":"READ_ONLY_INPUTS_NO_IMPLICIT_MAPPING_CONVERSION_IMPUTATION_OR_AGGREGATION"}
    (output_dir/"modeling_cohort_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return {"valid":True,"report":report,"manifest":manifest,"output_dir":str(output_dir)}
