"""Bounded, domain-neutral profiling of nested JSON structure."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any

def _kind(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "number"
    if isinstance(value, str): return "string"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    return type(value).__name__

def profile_json_structure(payload: Any, *, max_depth: int = 12, max_paths: int = 5000) -> dict[str, Any]:
    path_types: dict[str, Counter[str]] = defaultdict(Counter)
    list_lengths: dict[str, list[int]] = defaultdict(list)
    truncated_depth = 0
    truncated_paths = False
    stack = [(payload, "$", 0)]
    while stack:
        value, path, depth = stack.pop()
        if path not in path_types and len(path_types) >= max_paths:
            truncated_paths = True
            continue
        path_types[path][_kind(value)] += 1
        if isinstance(value, dict):
            if depth >= max_depth:
                if value: truncated_depth += 1
                continue
            for key, child in value.items():
                stack.append((child, f"{path}[{key!r}]", depth + 1))
        elif isinstance(value, list):
            list_lengths[path].append(len(value))
            if depth >= max_depth:
                if value: truncated_depth += 1
                continue
            for child in value:
                stack.append((child, f"{path}[]", depth + 1))
    paths = []
    for path in sorted(path_types):
        counts = path_types[path]
        lengths = list_lengths.get(path, [])
        paths.append({"path": path, "occurrences": sum(counts.values()),
            "value_types": dict(sorted(counts.items())),
            "list_length_min": min(lengths) if lengths else None,
            "list_length_max": max(lengths) if lengths else None})
    return {"path_count": len(paths), "max_depth": max_depth, "max_paths": max_paths,
        "truncated_depth_occurrences": truncated_depth, "truncated_paths": truncated_paths,
        "paths": paths, "interpretation": "STRUCTURAL_ONLY_NO_DOMAIN_SEMANTICS"}
