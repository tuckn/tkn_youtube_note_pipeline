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


JAPANESE_SECTION_LABELS = {
    "Summary": "要約",
    "Conclusion": "結論",
    "Key points": "要点",
    "Structuring (from abstract to concrete)": "構造（抽象から具体へ）",
    "Technical terms": "専門用語",
}


def japanese_heading(heading: str) -> str:
    """Translate a named numbered section, preserving its position and level."""
    prefix, separator, label = heading.partition(". ")
    return prefix + separator + JAPANESE_SECTION_LABELS.get(label, label)


JAPANESE_CONCLUSION_FIRST_HEADINGS = tuple(
    japanese_heading(heading) for heading in CONCLUSION_FIRST_HEADINGS
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
    if body is None:
        return headings
    layouts = [list(headings)]
    if tuple(headings) == LEGACY_HEADINGS:
        layouts.append(list(CONCLUSION_FIRST_HEADINGS))
    if tuple(headings) in (LEGACY_HEADINGS, CONCLUSION_FIRST_HEADINGS):
        layouts.extend([[japanese_heading(heading) for heading in layout] for layout in layouts[:]])
    actual = [heading for _, _, heading in section_headings(body)]
    for layout in layouts:
        if actual[:len(layout)] == layout:
            return layout
    return headings
