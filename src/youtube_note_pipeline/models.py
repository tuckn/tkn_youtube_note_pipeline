"""Canonical pipeline data models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoSource(StrictModel):
    video_id: str
    canonical_url: str
    title: str
    description: str = ""
    author: str | list[str] | None = None
    author_url: str | None = None
    published: str
    duration_seconds: float | None = None
    thumbnail: str | None = None
    original_language: str | None = None


class CaptionSelection(StrictModel):
    language: str
    kind: Literal["manual", "automatic", "fallback"]
    source_kind: Literal["subtitles", "automatic_captions", "import"]
    ext: str = "json3"


class ArtifactDigest(StrictModel):
    filename: str
    sha256: str
    bytes: int


class RawCaptureManifest(StrictModel):
    schema_version: str = "1.0"
    status: Literal["success", "failure"]
    captured_at: datetime
    tool_version: str
    video: VideoSource
    caption: CaptionSelection | None = None
    artifacts: dict[str, ArtifactDigest] = Field(default_factory=dict)
    acquisition_result: str
    error: str | None = None


class TranscriptSegment(StrictModel):
    start_ms: int
    end_ms: int
    text: str


class TranscriptDocument(StrictModel):
    video: VideoSource
    captured_at: datetime
    segments: list[TranscriptSegment]
    normalized_text_hash: str


class SummaryRequest(StrictModel):
    video: VideoSource
    transcript: str
    prompt_version: str
    input_hash: str
