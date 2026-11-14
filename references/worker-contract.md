# OpenCode Worker task and result contract

## Purpose

This document defines portable contracts between the Antigravity Supervisor and OpenCode Workers. It does not define or replace the user's existing Worker Manager or MCP API.

## Worker roles

Roles are logical, not mandatory fixed processes:

- data_scientist: data semantics, audit interpretation, statistical design, modelling review.
- scientific_analyst: interpretation of validated interactions and domain mechanisms.
- independent_auditor: challenge data leakage, validation design, or consequential findings.

Use the smallest number of Workers needed. Python handles deterministic numerical work. Do not send multiple Workers to repeat the same model run.

## Task packet

A task packet should identify task and project/run IDs; phase and role; one bounded objective; input artifact paths and hashes; a short context summary; permitted and prohibited actions; expected output paths and schemas; token/context constraints; and completion and escalation criteria.

The full raw dataset should not be placed in the prompt. Workers should read selected local artifacts when the environment permits, or receive a bounded summary/evidence subset.

## Result packet

A Worker result must include task status, concise findings, paths to generated artifacts, sources and evidence pointers, assumptions and unresolved issues, warnings, and recommended next action. For a DoR formal review stage, write the result at the exact declared staging path and conform to `schemas/worker_result.schema.json`; use `templates/worker_result.example.json` as the neutral format reference. Every finding must have a stable `finding_id`, concise summary, one or more supporting input artifact IDs, and exact locators within those inputs. The `task_id` must be the actual task ID returned by the host Worker Manager, not an invented identifier.

Numerical claims must cite the Python-generated artifact from which they were read. Worker prose is not an authoritative substitute for deterministic output.

## Permissions

Default permissions are read source/derived inputs and write only to the task's assigned output directory. A Worker must not modify/delete original source data, overwrite another task's artifacts, fabricate missing values or source evidence, execute broad expensive modelling outside its task, claim causality from observational associations, or create unsupported manuscript claims.

## Idempotency and token control

- Assign stable task IDs.
- Include input hashes and configuration versions.
- Reuse existing valid outputs.
- Return structured summaries instead of full logs.
- Do not ask Workers to re-read whole papers if a precise evidence excerpt is sufficient.
- Escalate schema ambiguity rather than guessing.
- Avoid redundant cross-worker replication; use an independent audit only for selected high-value findings.
