"""Safe resolvers for structural JSON profile paths and explicit JSON Pointer selectors."""
from __future__ import annotations

import ast
from typing import Any


def parse_profile_path(pattern: str) -> tuple[str, ...]:
    """Parse the audit profiler's $['key'][] notation into key and wildcard tokens."""
    if not isinstance(pattern, str) or not pattern.startswith("$"):
        raise ValueError("A JSON structural path must start with '$'.")
    tokens: list[str] = []
    index = 1
    while index < len(pattern):
        if pattern.startswith("[]", index):
            tokens.append("*")
            index += 2
            continue
        if pattern[index] != "[":
            raise ValueError(f"Unsupported structural path syntax at offset {index}.")
        end = index + 1
        quote = None
        escaped = False
        while end < len(pattern):
            char = pattern[end]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "]":
                break
            end += 1
        if end >= len(pattern) or quote is not None:
            raise ValueError("Unterminated key in JSON structural path.")
        literal = pattern[index + 1:end]
        try:
            key = ast.literal_eval(literal)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"Invalid key literal in structural path: {literal!r}.") from exc
        if not isinstance(key, str):
            raise ValueError("JSON structural path keys must be strings.")
        tokens.append(key)
        index = end + 1
    return tuple(tokens)


def parse_json_pointer(pointer: str) -> tuple[str, ...]:
    """Parse an RFC 6901 pointer with '*' reserved as an explicit array wildcard."""
    if pointer == "":
        return ()
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("JSON record_selector must be an RFC 6901 pointer beginning with '/'.")
    tokens = []
    for segment in pointer[1:].split("/"):
        index = 0
        decoded = ""
        while index < len(segment):
            if segment[index] == "~":
                if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
                    raise ValueError(f"Invalid RFC 6901 escape in segment {segment!r}.")
                decoded += "~" if segment[index + 1] == "0" else "/"
                index += 2
            else:
                decoded += segment[index]
                index += 1
        tokens.append(decoded)
    return tuple(tokens)


def render_json_pointer(tokens: tuple[str, ...] | list[str]) -> str:
    if not tokens:
        return ""
    escaped = [str(token).replace("~", "~0").replace("/", "~1") for token in tokens]
    return "/" + "/".join(escaped)


def resolve_tokens(root: Any, tokens: tuple[str, ...]) -> list[tuple[Any, tuple[str, ...]]]:
    """Resolve exact keys/indices and '*' array fan-out, returning concrete paths."""
    current: list[tuple[Any, tuple[str, ...]]] = [(root, ())]
    for token in tokens:
        next_items: list[tuple[Any, tuple[str, ...]]] = []
        for value, concrete in current:
            if token == "*":
                if isinstance(value, list):
                    next_items.extend((child, concrete + (str(i),)) for i, child in enumerate(value))
                else:
                    raise ValueError(f"Wildcard selector expected an array at {render_json_pointer(concrete)}.")
            elif isinstance(value, dict):
                if token in value:
                    next_items.append((value[token], concrete + (token,)))
            elif isinstance(value, list) and token.isdigit():
                idx = int(token)
                if idx < len(value):
                    next_items.append((value[idx], concrete + (token,)))
        current = next_items
        if not current:
            break
    return current


def selector_prefix_matches(pattern: tuple[str, ...], selector: tuple[str, ...]) -> bool:
    if len(pattern) < len(selector):
        return False
    return all(expected == actual for expected, actual in zip(pattern, selector))


def select_records(payload: Any, selector: str) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
    """Select object records; selector should explicitly fan out via '*'."""
    tokens = parse_json_pointer(selector)
    if "*" not in tokens:
        raise ValueError("JSON record_selector must contain at least one '*' array wildcard.")
    matches = resolve_tokens(payload, tokens)
    records = []
    for value, concrete in matches:
        if not isinstance(value, dict):
            raise ValueError(f"JSON record selector resolved a non-object at {render_json_pointer(concrete)}.")
        records.append((value, concrete))
    return records
