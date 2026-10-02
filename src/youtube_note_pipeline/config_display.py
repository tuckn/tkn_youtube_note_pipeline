"""Copyable, single-line configuration output."""

from __future__ import annotations

import json
from typing import Any


def _single_line(value: str) -> str:
    escapes = {"\n": r"\n", "\r": r"\r", "\t": r"\t"}
    return "".join(
        escapes.get(character, f"\\u{ord(character):04x}")
        if ord(character) < 32 or 127 <= ord(character) <= 159
        or character in ("\u2028", "\u2029") else character
        for character in value
    )


def config_lines(value: Any, prefix: str = "") -> list[str]:
    """Flatten nested data without quoting strings or escaping path separators."""
    if isinstance(value, dict):
        if not value:
            return [f"{_single_line(prefix)}={{}}"]
        return [
            line
            for key, item in value.items()
            for line in config_lines(item, f"{prefix}.{key}" if prefix else str(key))
        ]
    if isinstance(value, list):
        if not value:
            return [f"{_single_line(prefix)}=[]"]
        return [
            line
            for index, item in enumerate(value)
            for line in config_lines(item, f"{prefix}[{index}]")
        ]
    if isinstance(value, str):
        display = _single_line(value)
    else:
        display = json.dumps(value, ensure_ascii=False)
    return [f"{_single_line(prefix)}={display}"]
