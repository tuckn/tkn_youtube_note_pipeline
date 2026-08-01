"""Markdown parsing and rendering."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from youtube_note_pipeline.captions import render_transcript
from youtube_note_pipeline.models import (
    RawCaptureManifest,
    SummaryDocument,
    TranscriptSegment,
    VideoSource,
)
from youtube_note_pipeline.naming import path_to_file_uri

SOURCE_NOTE_SCHEMA_VERSION = "1.0"
SUMMARY_NOTE_SCHEMA_VERSION = "4.0"
DESCRIPTION_MAX_CHARS = 240


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def compact_description(value: str, max_chars: int = DESCRIPTION_MAX_CHARS) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    boundary = max(normalized.rfind(mark, 0, max_chars) for mark in "。！？.!?")
    if boundary >= max_chars // 2:
        return normalized[: boundary + 1]
    return normalized[: max_chars - 1].rstrip() + "…"


def split_note(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("note must start with YAML frontmatter")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter closing delimiter is missing")
    try:
        metadata = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a mapping")
    return dict(metadata), normalized[end + 5 :]


def transcript_from_source(text: str) -> str:
    _, body = split_note(text)
    match = re.search(r"(?m)^## Transcript\s*$", body)
    if not match:
        raise ValueError("source note has no Transcript heading")
    transcript = body[match.end() :].strip()
    if not transcript:
        raise ValueError("source note Transcript is empty")
    return transcript


def summary_section(body: str, heading: str, next_heading: str | None = None) -> str:
    start_match = re.search(rf"(?m)^{re.escape(heading)}\s*$", body)
    if not start_match:
        raise ValueError(f"summary note has no {heading} heading")
    start = start_match.end()
    end = len(body)
    if next_heading:
        end_match = re.search(rf"(?m)^{re.escape(next_heading)}\s*$", body[start:])
        if not end_match:
            raise ValueError(f"summary note has no {next_heading} heading")
        end = start + end_match.start()
    value = body[start:end].strip()
    if not value:
        raise ValueError(f"{heading} section is empty")
    return value


def update_source_description(text: str, description: str, updated: datetime) -> str:
    normalized = text.replace("\r\n", "\n")
    end = normalized.find("\n---\n", 4)
    if not normalized.startswith("---\n") or end < 0:
        raise ValueError("source note has invalid YAML frontmatter")
    lines = normalized[:end].splitlines()
    replacements = {
        "description": f"description: {yaml_quote(compact_description(description))}",
        "updated": f"updated: {updated.isoformat(timespec='seconds')}",
    }
    replaced: set[str] = set()
    for index, line in enumerate(lines):
        key = line.partition(":")[0]
        if key in replacements:
            lines[index] = replacements[key]
            replaced.add(key)
    missing = set(replacements) - replaced
    if missing:
        raise ValueError(f"source frontmatter is missing: {', '.join(sorted(missing))}")
    return "\n".join(lines) + normalized[end:]


def _cover_url(video: VideoSource) -> str:
    return video.thumbnail or f"https://i.ytimg.com/vi/{video.video_id}/maxresdefault.jpg"


def render_source(
    manifest: RawCaptureManifest,
    segments: list[TranscriptSegment],
    now: datetime,
    note_id: str | None = None,
) -> str:
    video = manifest.video
    author_lines = ["author:"]
    if isinstance(video.author, str):
        author_lines = [f"author: {yaml_quote(video.author)}"]
    elif video.author:
        author_lines = ["author:", *(f"  - {yaml_quote(item)}" for item in video.author)]
    frontmatter = [
        "---",
        "type: transcript",
        f"schemaVersion: {yaml_quote(SOURCE_NOTE_SCHEMA_VERSION)}",
        f"title: {yaml_quote(video.title)}",
        'description: ""',
        f"cover: {_cover_url(video)}",
        f"url: {video.canonical_url}",
        "linkStatus: active",
        "domain: youtube.com",
        "favicon: https://www.youtube.com/favicon.ico",
        *author_lines,
        f"published: {video.published}",
        "generator: youtube-note-pipeline",
        f"date: {now.isoformat(timespec='seconds')}",
        f"updated: {now.isoformat(timespec='seconds')}",
        f"noteId: {note_id or uuid.uuid4()}",
        "---",
        "",
        f"# {video.title}",
        "",
        f"![]({video.canonical_url})",
        "",
        "---",
        "",
        "## Transcript",
        "",
        render_transcript(segments),
        "",
    ]
    return "\n".join(frontmatter)


def _timestamp_url(video: VideoSource, seconds: int) -> str:
    return f"{video.canonical_url}&t={seconds}s"


def render_summary(
    video: VideoSource,
    source_path: Path,
    document: SummaryDocument,
    now: datetime,
    generator: str,
    prompt_id: str,
    prompt_version: str,
    note_id: str | None = None,
    created_at: datetime | None = None,
) -> str:
    created = created_at or now
    lines = [
        "---",
        "type: summary",
        f"schemaVersion: {yaml_quote(SUMMARY_NOTE_SCHEMA_VERSION)}",
        f"title: {yaml_quote(video.title)}",
        f"description: {yaml_quote(compact_description(document.conclusion))}",
        f"cover: {_cover_url(video)}",
        f"url: {video.canonical_url}",
        "cliptool: Codex",
        f"source: {yaml_quote(path_to_file_uri(source_path))}",
        f"generator: {yaml_quote(generator)}",
        f"promptId: {prompt_id}",
        f"promptVersion: {yaml_quote(prompt_version)}",
        "reviewStatus: unreviewed",
        f"date: {created.isoformat(timespec='seconds')}",
        f"updated: {now.isoformat(timespec='seconds')}",
        f"noteId: {note_id or uuid.uuid4()}",
        "---",
        "",
        f"# {video.title}",
        "",
        f"![]({video.canonical_url})",
        "",
        "## 1. Summary",
        "",
        document.summary,
        "",
        "## 2. Structuring (from abstract to concrete)",
        "",
    ]
    for section in document.structuring:
        lines.extend([f"### {section.heading}", ""])
        lines.extend(f"- {item}" for item in section.details)
        if section.details:
            lines.append("")
        for subsection in section.subsections:
            lines.extend(
                [
                    f"#### {subsection.heading}",
                    "",
                    *(f"- {item}" for item in subsection.details),
                    "",
                ]
            )
    lines.extend(["## 3. Key points", ""])
    for point in document.key_points:
        if point.timestamp_seconds is None:
            lines.append(f"- {point.text}")
        else:
            url = _timestamp_url(video, point.timestamp_seconds)
            minute = point.timestamp_seconds // 60
            second = point.timestamp_seconds % 60
            lines.append(f"- [{minute}:{second:02d}]({url}) {point.text}")
    lines.extend(["", "## 4. Technical terms", ""])
    lines.extend(f"- {term}" for term in document.technical_terms)
    lines.extend(["", "## 5. Conclusion", "", document.conclusion, ""])
    return "\n".join(lines)
