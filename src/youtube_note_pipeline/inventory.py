"""Read-only inventory of acquired transcripts and derived notes."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from youtube_note_pipeline.models import RawCaptureManifest
from youtube_note_pipeline.notes import split_note

SUMMARY_NOTE_TYPES = {"summary", "webClip"}


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    rendered = str(value)
    return rendered or None


def _note_indexes(
    source_root: Path,
    summary_root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    summaries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    warnings: list[dict[str, str]] = []

    for root, expected_types, target, is_summary in (
        (source_root, {"transcript"}, sources, False),
        (summary_root, SUMMARY_NOTE_TYPES, summaries, True),
    ):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                metadata, _ = split_note(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                warnings.append({"path": str(path), "error": f"cannot read note: {exc}"})
                continue
            if metadata.get("type") not in expected_types:
                continue
            url = _text(metadata.get("url"))
            if not url:
                warnings.append({"path": str(path), "error": "note has no url"})
                continue
            note: dict[str, Any] = {
                "path": str(path),
                "title": _text(metadata.get("title")),
                "schema_version": _text(metadata.get("schemaVersion")),
                "note_id": _text(metadata.get("noteId")),
                "updated": _text(metadata.get("updated")),
            }
            if is_summary:
                note.update(
                    {
                        "prompt_id": _text(metadata.get("promptId")),
                        "prompt_version": _text(metadata.get("promptVersion")),
                        "review_status": _text(metadata.get("reviewStatus")),
                    }
                )
            target[url].append(note)

    return dict(sources), dict(summaries), warnings


def _captured_timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def build_inventory(
    raw_root: Path,
    source_root: Path,
    summary_root: Path,
) -> dict[str, Any]:
    """Return one item per video, using its latest successful transcript capture."""

    sources, summaries, warnings = _note_indexes(source_root, summary_root)
    captures: dict[str, list[tuple[RawCaptureManifest, Path]]] = defaultdict(list)
    if raw_root.is_dir():
        for path in sorted(raw_root.rglob("manifest.json")):
            try:
                manifest = RawCaptureManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, ValueError) as exc:
                warnings.append({"path": str(path), "error": f"cannot read manifest: {exc}"})
                continue
            if manifest.status != "success" or "captions" not in manifest.artifacts:
                continue
            captures[manifest.video.video_id].append((manifest, path))

    item_rows: list[tuple[float, dict[str, Any]]] = []
    for video_id, video_captures in captures.items():
        ordered = sorted(
            video_captures,
            key=lambda value: (_captured_timestamp(value[0].captured_at), str(value[1])),
            reverse=True,
        )
        manifest, manifest_path = ordered[0]
        caption = manifest.artifacts["captions"]
        caption_path = manifest_path.parent / caption.filename
        url = manifest.video.canonical_url
        item_rows.append(
            (
                _captured_timestamp(manifest.captured_at),
                {
                "video_id": video_id,
                "title": manifest.video.title,
                "url": url,
                "published": manifest.video.published,
                "capture": {
                    "captured_at": manifest.captured_at.isoformat(),
                    "capture_count": len(ordered),
                    "language": manifest.caption.language if manifest.caption else None,
                    "manifest_path": str(manifest_path),
                    "captions_path": str(caption_path),
                    "captions_available": caption_path.is_file(),
                },
                "source_notes": sources.get(url, []),
                "summary_notes": summaries.get(url, []),
                },
            )
        )

    item_rows.sort(key=lambda row: (row[0], str(row[1]["video_id"])), reverse=True)
    warnings.sort(key=lambda warning: (warning["path"], warning["error"]))
    return {
        "schema_version": "1.0",
        "count": len(item_rows),
        "items": [item for _, item in item_rows],
        "warnings": warnings,
    }
