"""Immutable raw capture acquisition and import."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from youtube_note_pipeline import __version__
from youtube_note_pipeline.captions import parse_json3, select_caption
from youtube_note_pipeline.config import user_cache_root
from youtube_note_pipeline.io import sha256_bytes
from youtube_note_pipeline.models import (
    ArtifactDigest,
    CaptionSelection,
    RawCaptureManifest,
    VideoSource,
)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _youtube_dl_options() -> dict[str, Any]:
    return {
        "cachedir": str(user_cache_root() / "yt-dlp"),
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }


def canonical_video_url(url: str) -> tuple[str, str]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "m.youtube.com"} and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    else:
        raise ValueError("v1 accepts a single YouTube watch or youtu.be URL")
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("URL does not contain one valid YouTube video ID")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def _published(info: dict[str, Any]) -> str:
    upload_date = str(info.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    timestamp = info.get("release_timestamp")
    if timestamp:
        return datetime.fromtimestamp(float(timestamp), tz=UTC).isoformat()
    raise ValueError("YouTube metadata does not contain a publication date")


def video_source(info: dict[str, Any], canonical_url: str) -> VideoSource:
    author = info.get("uploader") or info.get("channel")
    return VideoSource(
        video_id=str(info.get("id") or canonical_video_url(canonical_url)[0]),
        canonical_url=canonical_url,
        title=str(info.get("title") or "").strip(),
        description=str(info.get("description") or ""),
        author=str(author) if author else None,
        author_url=info.get("uploader_url") or info.get("channel_url"),
        published=_published(info),
        duration_seconds=float(info["duration"]) if info.get("duration") is not None else None,
        thumbnail=info.get("thumbnail"),
        original_language=info.get("language") or info.get("original_language"),
    )


def _capture_name(captured_at: datetime) -> str:
    return captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _artifact(filename: str, data: bytes) -> ArtifactDigest:
    return ArtifactDigest(filename=filename, sha256=sha256_bytes(data), bytes=len(data))


def _write_capture(
    raw_root: Path,
    info: dict[str, Any],
    canonical_url: str,
    caption_data: bytes | None,
    selection: CaptionSelection | None,
    error: str | None,
    captured_at: datetime,
    refresh: bool,
) -> Path:
    source = video_source(info, canonical_url)
    metadata_data = json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    artifacts = {"metadata": _artifact("metadata.info.json", metadata_data)}
    if caption_data is not None and selection is not None:
        parse_json3(caption_data)
        caption_name = f"captions.{selection.language}.json3"
        artifacts["captions"] = _artifact(caption_name, caption_data)
    manifest = RawCaptureManifest(
        status="failure" if error else "success",
        captured_at=captured_at,
        tool_version=__version__,
        video=source,
        caption=selection,
        artifacts=artifacts,
        acquisition_result="failed" if error else "captured",
        error=error,
    )
    video_root = raw_root / source.video_id
    if not refresh and not error and video_root.exists():
        expected = {key: value.sha256 for key, value in artifacts.items()}
        for existing in sorted(video_root.glob("*/manifest.json"), reverse=True):
            try:
                previous = RawCaptureManifest.model_validate_json(
                    existing.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            hashes = {key: value.sha256 for key, value in previous.artifacts.items()}
            if previous.status == "success" and hashes == expected:
                return existing
    target = video_root / _capture_name(captured_at)
    suffix = 1
    while target.exists():
        target = video_root / f"{_capture_name(captured_at)}-{suffix}"
        suffix += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".capture-", dir=target.parent))
    try:
        (temporary / "metadata.info.json").write_bytes(metadata_data)
        if caption_data is not None and selection is not None:
            (temporary / f"captions.{selection.language}.json3").write_bytes(caption_data)
        (temporary / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n"
        )
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target / "manifest.json"


def acquire(
    url: str,
    raw_root: Path,
    fallback_languages: list[str],
    refresh: bool = False,
) -> Path:
    video_id, canonical_url = canonical_video_url(url)
    captured_at = datetime.now().astimezone()
    try:
        import yt_dlp  # type: ignore[import-untyped]

        with yt_dlp.YoutubeDL(_youtube_dl_options()) as ydl:
            extracted = ydl.extract_info(canonical_url, download=False)
            info = ydl.sanitize_info(extracted)
        if str(info.get("id")) != video_id:
            raise ValueError("yt-dlp returned a different video")
        selected = select_caption(info, fallback_languages)
        if selected is None:
            return _write_capture(
                raw_root,
                info,
                canonical_url,
                None,
                None,
                "No allowed complete caption track was available",
                captured_at,
                refresh,
            )
        selection, track = selected
        request = Request(str(track["url"]), headers={"User-Agent": "youtube-note-pipeline"})
        with urlopen(request, timeout=60) as response:
            caption_data = response.read()
        return _write_capture(
            raw_root, info, canonical_url, caption_data, selection, None, captured_at, refresh
        )
    except Exception as exc:
        minimal = {
            "id": video_id,
            "title": video_id,
            "description": "",
            "upload_date": captured_at.strftime("%Y%m%d"),
        }
        return _write_capture(
            raw_root, minimal, canonical_url, None, None, str(exc), captured_at, refresh
        )


def import_raw(
    metadata_path: Path,
    captions_path: Path,
    raw_root: Path,
    language: str | None = None,
    refresh: bool = False,
) -> Path:
    try:
        info = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read metadata JSON: {exc}") from exc
    if not isinstance(info, dict):
        raise ValueError("metadata JSON must be an object")
    caption_data = captions_path.read_bytes()
    parse_json3(caption_data)
    video_id = str(info.get("id") or "")
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("metadata JSON must contain a valid id")
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    selected_language = language or captions_path.name.removeprefix("captions.").removesuffix(
        ".json3"
    )
    if not selected_language or selected_language == captions_path.name:
        selected_language = str(info.get("language") or "und")
    selection = CaptionSelection(
        language=selected_language,
        kind="manual",
        source_kind="import",
    )
    return _write_capture(
        raw_root,
        info,
        canonical_url,
        caption_data,
        selection,
        None,
        datetime.now().astimezone(),
        refresh,
    )
