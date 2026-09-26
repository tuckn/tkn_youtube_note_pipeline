"""Reorder existing summaries without AI calls or changes to their metadata."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from youtube_note_pipeline.io import atomic_write, sha256_bytes
from youtube_note_pipeline.migration import _metadata
from youtube_note_pipeline.sections import (
    CONCLUSION_FIRST_HEADINGS,
    LEGACY_HEADINGS,
    section_headings,
)


class UnsupportedLayout(ValueError):
    """The note lacks the five sections; reordering would require authoring content."""


def reorder_sections(payload: bytes) -> bytes:
    """Preserve Frontmatter, section content, appendix, BOM and boundary newlines."""
    metadata = _metadata(payload)
    if metadata.get("type") not in ("summary", "webClip"):
        raise UnsupportedLayout("not a summary note")
    text = payload.decode("utf-8-sig")
    boundary = re.match(r"\A---\r?\n.*?\r?\n---\r?\n", text, re.S)
    if boundary is None:
        raise ValueError("missing Frontmatter delimiter")
    prefix, body = text[: boundary.end()], text[boundary.end() :]
    spans = section_headings(body)
    actual = [heading for _, _, heading in spans]
    names = [re.sub(r"^## \d+\. ", "", heading) for heading in actual]
    required = [heading.split(". ", 1)[1] for heading in LEGACY_HEADINGS]
    if any(names.count(name) > 1 for name in required):
        raise ValueError("duplicate summary section")
    if not all(name in names for name in required):
        raise UnsupportedLayout("the five standard sections are not all present")
    if tuple(actual[:5]) == CONCLUSION_FIRST_HEADINGS:
        return payload
    if tuple(actual[:5]) != LEGACY_HEADINGS:
        raise ValueError("mixed or interleaved summary section layout")
    suffix_start = spans[5][0] if len(spans) > 5 else len(body)
    blocks = []
    gaps = []
    for index, (_, end, _) in enumerate(spans[:5]):
        stop = spans[index + 1][0] if index < 4 else suffix_start
        content = body[end:stop]
        value = content.rstrip("\r\n")
        if not value.strip():
            raise ValueError("empty summary section")
        blocks.append(value)
        gaps.append(content[len(value) :])
    # Move only the section payload. Separators remain at the original positions,
    # including an absent final newline and any trailing user-written appendix.
    reordered = (
        body[: spans[0][0]]
        + "".join(
            heading + blocks[old_index] + gaps[new_index]
            for new_index, (heading, old_index) in enumerate(
                zip(CONCLUSION_FIRST_HEADINGS, (0, 4, 2, 1, 3), strict=True)
            )
        )
        + body[suffix_start:]
    )
    bom = b"\xef\xbb\xbf" if payload.startswith(b"\xef\xbb\xbf") else b""
    return bom + (prefix + reordered).encode("utf-8")


def plan_section_order(summary_root: Path) -> dict[str, Any]:
    summary_root = summary_root.absolute()
    if not summary_root.is_dir():
        raise ValueError("summary_root must be an existing directory")
    items = []
    for path in sorted(summary_root.rglob("*.md")):
        item: dict[str, Any] = {"path": str(path)}
        items.append(item)
        try:
            path.resolve().relative_to(summary_root.resolve())
            payload = path.read_bytes()
            item["before_sha256"] = sha256_bytes(payload)
            updated = reorder_sections(payload)
            item.update(
                status="unchanged" if payload == updated else "planned",
                after_sha256=sha256_bytes(updated),
            )
        except UnsupportedLayout as exc:
            item.update(status="skipped", reason=str(exc))
        except (OSError, UnicodeError, ValueError) as exc:
            item.update(status="blocked", reason=str(exc))
    return {
        "schema_version": "1.0",
        "operation": "reorder-summary-sections",
        "summary_root": str(summary_root),
        "counts": dict(Counter(item["status"] for item in items)),
        "items": items,
    }


def apply_section_order(plan: dict[str, Any], reports_root: Path) -> dict[str, Any]:
    """Recheck all bytes, back up every original, then atomically replace each note."""
    if not isinstance(plan.get("summary_root"), str):
        raise ValueError("invalid section-order plan")
    summary_root = Path(plan["summary_root"])
    fresh = plan_section_order(summary_root)
    if fresh != plan:
        raise ValueError("section-order plan is stale or modified")
    if fresh["counts"].get("blocked"):
        raise ValueError("section-order plan contains blocked notes; no files changed")
    selected = [item for item in fresh["items"] if item["status"] == "planned"]
    if not selected:
        return {"status": "unchanged", "updated": 0, "counts": fresh["counts"]}
    try:
        reports_root.resolve().relative_to(summary_root.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("reports_root must be outside summary_root")
    run_root = (
        reports_root
        / "section-order"
        / (datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "_" + uuid.uuid4().hex[:8])
    )
    result: dict[str, Any] = {
        "status": "backing_up",
        "updated": 0,
        "counts": fresh["counts"],
        "backup_root": str(run_root),
        "files": [],
    }
    atomic_write(run_root / "plan.json", json.dumps(fresh, ensure_ascii=False, indent=2) + "\n")
    prepared = []
    try:
        for index, item in enumerate(selected):
            path = Path(item["path"])
            payload = path.read_bytes()
            if sha256_bytes(payload) != item["before_sha256"]:
                raise ValueError("note changed before backup")
            updated = reorder_sections(payload)
            if sha256_bytes(updated) != item["after_sha256"]:
                raise ValueError("section-order output differs from plan")
            backup = run_root / "backups" / f"{index:04d}.md"
            atomic_write(backup, payload)
            prepared.append((path, payload, updated))
            result["files"].append(
                {
                    "path": str(path),
                    "backup": str(backup),
                    "status": "backed_up",
                    "before_sha256": item["before_sha256"],
                    "after_sha256": item["after_sha256"],
                }
            )
        atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n")
        for record, (path, payload, updated) in zip(result["files"], prepared, strict=True):
            if path.read_bytes() != payload:
                raise ValueError("note changed during section reorder")
            atomic_write(path, updated, overwrite=True)
            record["status"] = "updated"
            result["updated"] += 1
            if path.read_bytes() != updated:
                raise ValueError("section-order write verification failed")
            atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n", True)
        result["status"] = "updated"
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n", True)
        raise RuntimeError(
            f"section reorder stopped; recovery report: {run_root / 'result.json'}"
        ) from exc
    atomic_write(run_root / "result.json", json.dumps(result, indent=2) + "\n", True)
    return result
