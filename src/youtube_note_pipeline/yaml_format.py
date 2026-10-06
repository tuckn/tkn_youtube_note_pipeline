"""Lossless YAML scalar formatting and legacy note metadata conversion."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


class StringTimestampLoader(yaml.SafeLoader):
    """Keep original timestamp spelling, offset and fractional precision."""


StringTimestampLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", lambda loader, node: node.value
)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=StringTimestampLoader)


def yaml_quote(value: str) -> str:
    if is_windows_path(value):
        return "'" + value.replace("'", "''") + "'"
    return json.dumps(value, ensure_ascii=False)


def is_windows_path(value: str) -> bool:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]+:", value):
        return False
    return bool(re.match(r"^(?:[A-Za-z]:|\\|[^\s\\/:]+\\)", value))


def normalize_yaml(text: str, *, rename_date: bool = False) -> str:
    """Patch scalar spans only, retaining comments, whitespace and all other text."""
    root = yaml.compose(text)
    edits: dict[tuple[int, int], str] = {}
    visited: set[int] = set()

    def replace(node: ScalarNode, value: str) -> None:
        edits[node.start_mark.index, node.end_mark.index] = value

    def visit(node: Node) -> None:
        if id(node) in visited:
            return
        visited.add(id(node))
        if isinstance(node, MappingNode):
            keys = [key.value for key, _ in node.value if isinstance(key, ScalarNode)]
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate YAML keys")
            if node is root and rename_date and "date" in keys and "created" in keys:
                raise ValueError("both date and created exist")
            for key, value in node.value:
                if node is root and rename_date and isinstance(key, ScalarNode):
                    if key.value == "date":
                        replace(key, "created")
                visit(value)
        elif isinstance(node, SequenceNode):
            for item in node.value:
                visit(item)
        elif isinstance(node, ScalarNode):
            if node.style in ("|", ">"):
                return
            date_pattern = (
                r"\d{4}-\d{2}-\d{2}"
                r"(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
            )
            if re.fullmatch(date_pattern, node.value):
                replace(node, json.dumps(node.value, ensure_ascii=False))
            elif node.tag == "tag:yaml.org,2002:str" and is_windows_path(node.value):
                replace(node, yaml_quote(node.value))

    if root is not None:
        visit(root)
    result = text
    for (start, end), value in sorted(edits.items(), reverse=True):
        result = result[:start] + value + result[end:]
    expected = load_yaml(text)
    if rename_date and isinstance(expected, dict) and "date" in expected:
        expected["created"] = expected.pop("date")
    if load_yaml(result) != expected:
        raise ValueError("YAML formatting changed values")
    return result


def normalize_note(payload: bytes) -> bytes:
    text = payload.decode("utf-8-sig")
    match = re.match(r"\A---\r?\n(.*?)^---(?:\r?\n|$)", text, re.M | re.S)
    if match is None:
        return payload
    formatted = normalize_yaml(match[1], rename_date=True)
    text = text[:match.start(1)] + formatted + text[match.end(1):]
    bom = b"\xef\xbb\xbf" if payload.startswith(b"\xef\xbb\xbf") else b""
    return bom + text.encode("utf-8")
