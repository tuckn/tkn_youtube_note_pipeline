"""Summary provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from youtube_note_pipeline.models import SummaryDocument, SummaryRequest


@dataclass(frozen=True)
class ProviderResult:
    document: SummaryDocument
    provider: str
    model: str | None
    generator: str
    provider_version: str | None


class SummaryProvider(Protocol):
    def generate(self, request: SummaryRequest) -> ProviderResult: ...
