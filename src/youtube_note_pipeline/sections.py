"""Maintained section layouts and Markdown heading boundaries."""

from __future__ import annotations

import re

LEGACY_HEADINGS = (
    "## 1. Summary",
    "## 2. Structuring (from abstract to concrete)",
    "## 3. Key points",
    "## 4. Technical terms",
    "## 5. Conclusion",
)
CONCLUSION_FIRST_HEADINGS = (
    "## 1. Summary",
    "## 2. Conclusion",
    "## 3. Key points",
    "## 4. Structuring (from abstract to concrete)",
    "## 5. Technical terms",
)


def section_headings(text: str) -> list[tuple[int, int, str]]:
    """Return H2 spans outside fenced code; end offsets exclude the newline."""
    result = []
    offset = 0
    fence = ""
    for line in text.splitlines(keepends=True):
        value = line.rstrip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", value)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                if not marker[2].strip():
                    fence = ""
        elif marker:
            fence = marker[1]
        elif value.startswith("## "):
            result.append((offset, offset + len(value), value.rstrip()))
        offset += len(line)
    return result


def historical_layout(headings: list[str], body: str | None) -> list[str]:
    """Permit the explicit presentation-only migration without rewriting provenance."""
    if tuple(headings) == LEGACY_HEADINGS and body is not None:
        actual = [heading for _, _, heading in section_headings(body)]
        if actual[:5] == list(CONCLUSION_FIRST_HEADINGS):
            return list(CONCLUSION_FIRST_HEADINGS)
    return headings
