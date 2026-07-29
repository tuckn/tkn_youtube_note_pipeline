"""Summary provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from youtube_note_pipeline.models import SummaryDocument, SummaryRequest
from youtube_note_pipeline.prompting import SummaryPrompt


@dataclass(frozen=True)
class ProviderResult:
    document: SummaryDocument
    provider: str
    model: str | None
    generator: str
    provider_version: str | None
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_envelope_version: str | None = None
    prompt_source: str | None = None
    prompt_sha256: str | None = None


class SummaryProvider(Protocol):
    prompt: SummaryPrompt

    def generate(self, request: SummaryRequest) -> ProviderResult: ...
