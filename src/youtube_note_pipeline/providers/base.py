"""Summary provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from youtube_note_pipeline.models import SummaryRequest
from youtube_note_pipeline.summary_resources import SummaryProfile


@dataclass(frozen=True)
class ProviderResult:
    document: dict[str, Any]
    provider: str
    model: str | None
    generator: str
    provider_version: str | None
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_envelope_version: str | None = None
    prompt_source: str | None = None
    prompt_sha256: str | None = None
    output_schema_id: str | None = None
    output_schema_version: str | None = None
    output_schema_sha256: str | None = None
    template_id: str | None = None
    template_version: str | None = None
    template_sha256: str | None = None


class SummaryProvider(Protocol):
    profile: SummaryProfile

    def generate(self, request: SummaryRequest) -> ProviderResult: ...
