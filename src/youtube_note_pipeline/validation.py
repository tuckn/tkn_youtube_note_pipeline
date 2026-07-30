"""Manifest and Markdown artifact validation."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from youtube_note_pipeline.captions import parse_json3, validate_transcript
from youtube_note_pipeline.io import sha256_file
from youtube_note_pipeline.models import RawCaptureManifest
from youtube_note_pipeline.naming import (
    build_filename,
    file_uri_to_path,
)
from youtube_note_pipeline.notes import (
    SOURCE_NOTE_SCHEMA_VERSION,
    SUMMARY_NOTE_SCHEMA_VERSION,
    compact_description,
    split_note,
    summary_section,
    transcript_from_source,
)

SOURCE_FRONTMATTER_ORDER = [
    "type",
    "schemaVersion",
    "title",
    "description",
    "cover",
    "url",
    "linkStatus",
    "domain",
    "favicon",
    "author",
    "published",
    "generator",
    "date",
    "updated",
    "noteId",
]

SUMMARY_FRONTMATTER_ORDER_V1 = [
    "type",
    "schemaVersion",
    "title",
    "description",
    "cover",
    "nouns",
    "url",
    "cliptool",
    "source",
    "generator",
    "reviewStatus",
    "date",
    "updated",
    "noteId",
]

SUMMARY_FRONTMATTER_ORDER_V2 = [
    "type",
    "schemaVersion",
    "title",
    "description",
    "cover",
    "nouns",
    "url",
    "cliptool",
    "source",
    "generator",
    "promptId",
    "promptVersion",
    "reviewStatus",
    "date",
    "updated",
    "noteId",
]

SUMMARY_FRONTMATTER_ORDER = [
    "type",
    "schemaVersion",
    "title",
    "description",
    "cover",
    "url",
    "cliptool",
    "source",
    "generator",
    "promptId",
    "promptVersion",
    "reviewStatus",
    "date",
    "updated",
    "noteId",
]

SUMMARY_REVIEW_STATUSES = (
    "unreviewed",
    "pending",
    "reviewing",
    "accepted",
    "needs-revision",
    "rejected",
)


def _frontmatter_keys(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    end = normalized.find("\n---\n", 4)
    if not normalized.startswith("---\n") or end < 0:
        return []
    keys: list[str] = []
    for line in normalized[4:end].splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9]*):", line)
        if match:
            keys.append(match.group(1))
    return keys


def _validate_frontmatter_order(text: str, expected: list[str], kind: str) -> list[str]:
    keys = _frontmatter_keys(text)
    canonical = [key for key in keys if key in expected]
    errors = []
    if canonical != expected:
        errors.append(f"{kind} frontmatter fields are out of order")
    if keys[-3:] != ["date", "updated", "noteId"]:
        errors.append(f"{kind} date, updated, and noteId must be the final fields")
    return errors


def validate_manifest(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = RawCaptureManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"invalid manifest: {exc}"]
    for name, artifact in manifest.artifacts.items():
        artifact_path = path.parent / artifact.filename
        if not artifact_path.exists():
            errors.append(f"missing {name} artifact: {artifact.filename}")
            continue
        if artifact_path.stat().st_size != artifact.bytes:
            errors.append(f"size mismatch: {artifact.filename}")
        if sha256_file(artifact_path) != artifact.sha256:
            errors.append(f"SHA-256 mismatch: {artifact.filename}")
    if manifest.status == "success":
        if not manifest.caption or "captions" not in manifest.artifacts:
            errors.append("successful manifest must contain a caption artifact")
        else:
            caption_path = path.parent / manifest.artifacts["captions"].filename
            try:
                parse_json3(caption_path.read_bytes())
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    return errors


def validate_source(path: Path, require_transcript: bool = True) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        metadata, body = split_note(text)
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)]
    if metadata.get("type") != "transcript":
        errors.append("type must be 'transcript'")
    if str(metadata.get("schemaVersion")) != SOURCE_NOTE_SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SOURCE_NOTE_SCHEMA_VERSION}")
    if "description" not in metadata:
        errors.append("description must be present")
    for key in (
        "title",
        "cover",
        "url",
        "linkStatus",
        "domain",
        "published",
        "generator",
        "date",
        "updated",
        "noteId",
    ):
        if not metadata.get(key):
            errors.append(f"{key} must be non-empty")
    for key in ("summary", "medium", "site", "reviewStatus"):
        if key in metadata:
            errors.append(f"{key} must not be stored on the source note")
    errors.extend(_validate_frontmatter_order(text, SOURCE_FRONTMATTER_ORDER, "source"))
    url = str(metadata.get("url") or "")
    title = str(metadata.get("title") or "")
    if f"# {title}" not in body:
        errors.append("source body must contain the title heading")
    if f"![]({url})" not in body:
        errors.append("source body must contain the YouTube embed")
    try:
        transcript_from_source(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        if require_transcript:
            errors.append(str(exc))
    try:
        year, filename = build_filename(str(metadata.get("published") or ""), title)
        if path.parent.name != year or path.name != filename:
            errors.append(f"source must be located at {year}/{filename}")
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_source_against_manifest(source: Path, manifest_path: Path) -> list[str]:
    errors = validate_source(source)
    try:
        manifest = RawCaptureManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        caption = manifest.artifacts["captions"]
        expected = parse_json3((manifest_path.parent / caption.filename).read_bytes())
        transcript = transcript_from_source(source.read_text(encoding="utf-8"))
        errors.extend(validate_transcript(transcript, expected, manifest.video.duration_seconds))
    except (OSError, UnicodeError, KeyError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def validate_summary(path: Path, source_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        metadata, body = split_note(text)
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)]
    schema_version = str(metadata.get("schemaVersion"))
    supported_schema_versions = ("1.0", "2.0", SUMMARY_NOTE_SCHEMA_VERSION)
    if schema_version not in supported_schema_versions:
        allowed = ", ".join(supported_schema_versions)
        errors.append(f"schemaVersion must be one of: {allowed}")
    is_v1 = schema_version == "1.0"
    is_prior_schema = schema_version in ("1.0", "2.0")
    expected_type = "webClip" if is_prior_schema else "summary"
    if metadata.get("type") != expected_type:
        errors.append(f"type must be '{expected_type}' for schemaVersion {schema_version}")
    if metadata.get("reviewStatus") not in SUMMARY_REVIEW_STATUSES:
        allowed = ", ".join(SUMMARY_REVIEW_STATUSES)
        errors.append(f"reviewStatus must be one of: {allowed}")
    if metadata.get("cliptool") != "Codex":
        errors.append("cliptool must be 'Codex'")
    for key in (
        "title",
        "description",
        "cover",
        "url",
        "source",
        "generator",
        "date",
        "updated",
        "noteId",
    ):
        if not metadata.get(key):
            errors.append(f"{key} must be non-empty")
    if is_v1:
        if "promptId" in metadata or "promptVersion" in metadata:
            errors.append("schemaVersion 1.0 must not contain prompt provenance")
    else:
        try:
            normalized_prompt_id = str(uuid.UUID(str(metadata.get("promptId"))))
            if str(metadata.get("promptId")) != normalized_prompt_id:
                errors.append("promptId must use canonical lowercase UUID form")
        except (ValueError, AttributeError):
            errors.append("promptId must be a UUID")
        if not isinstance(metadata.get("promptVersion"), str) or not str(
            metadata.get("promptVersion")
        ).strip():
            errors.append("promptVersion must be a non-empty string")
    for key in (
        "linkStatus",
        "medium",
        "site",
        "domain",
        "favicon",
        "author",
        "published",
        "transcript",
    ):
        if key in metadata:
            errors.append(f"{key} belongs on the source note, not the summary")
    if is_prior_schema:
        if metadata.get("nouns") != []:
            errors.append("nouns must default to [] for schemaVersion 1.0 or 2.0")
    if is_v1:
        expected_order = SUMMARY_FRONTMATTER_ORDER_V1
    elif schema_version == "2.0":
        expected_order = SUMMARY_FRONTMATTER_ORDER_V2
    else:
        expected_order = SUMMARY_FRONTMATTER_ORDER
    errors.extend(_validate_frontmatter_order(text, expected_order, "summary"))
    if re.search(r"(?m)^## Transcript\s*$", body):
        errors.append("summary must not contain a Transcript section")
    headings = [
        "## 1. Summary",
        "## 2. Structuring (from abstract to concrete)",
        "## 3. Key points",
        "## 4. Technical terms",
        "## 5. Conclusion",
    ]
    positions = [body.find(heading) for heading in headings]
    if any(position < 0 for position in positions):
        errors.append("summary headings are incomplete")
    elif positions != sorted(positions):
        errors.append("summary headings are out of order")
    summary_value = ""
    try:
        summary_value = summary_section(
            body,
            "## 1. Summary",
            "## 2. Structuring (from abstract to concrete)",
        )
        conclusion_value = summary_section(body, "## 5. Conclusion")
        if metadata.get("description") != compact_description(conclusion_value):
            errors.append("summary description must match the compacted Conclusion")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        source_path = file_uri_to_path(str(metadata.get("source") or ""))
        if source_root:
            source_path.resolve(strict=True).relative_to(source_root.resolve(strict=True))
        if source_path.parent.name != path.parent.name:
            errors.append("source and summary must use the same year folder")
        if is_v1:
            if source_path.name != path.name:
                errors.append("legacy source and summary must use the same filename")
        source_metadata, _ = split_note(source_path.read_text(encoding="utf-8"))
        if source_metadata.get("summary") is not None:
            errors.append("source note must not contain reverse summary provenance")
        if is_v1 and source_metadata.get("description") != compact_description(
            summary_value
        ):
            errors.append("source description must match the compacted Summary")
        if source_metadata.get("cover") != metadata.get("cover"):
            errors.append("source and summary cover must match")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot validate source reference: {exc}")
    return errors


def validate_path(path: Path, source_root: Path | None = None) -> tuple[str, list[str]]:
    if path.name == "manifest.json" or path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "manifest", validate_manifest(path)
        if isinstance(payload, dict) and "schema_version" in payload:
            return "manifest", validate_manifest(path)
    if path.suffix.lower() == ".md":
        try:
            metadata, _ = split_note(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            return "note", [str(exc)]
        if metadata.get("type") == "transcript":
            return "source", validate_source(path)
        if metadata.get("type") in ("webClip", "summary"):
            return "summary", validate_summary(path, source_root)
    return "unknown", ["cannot determine artifact type"]
