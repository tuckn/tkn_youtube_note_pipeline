"""Caption selection, JSON3 normalization, and transcript validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from youtube_note_pipeline.models import CaptionSelection, TranscriptSegment

SENTENCE_ENDINGS = frozenset("。！？!?.")
SENTENCE_CLOSERS = frozenset("」』）)]\"'")
TARGET_CHARS = 140
MAX_SPAN_SECONDS = 35
MAX_PARAGRAPH_CHARS = 220
TRANSCRIPT_LINE = re.compile(
    r"(?m)^\*\*(?P<timestamp>(?:\d+:)?\d{1,2}:\d{2})\*\* · (?P<text>\S.*)$"
)


def _language_match(candidate: str, preferred: str) -> bool:
    return candidate == preferred or candidate.split("-")[0] == preferred.split("-")[0]


def select_caption(
    info: dict[str, Any], fallback_languages: list[str]
) -> tuple[CaptionSelection, dict[str, Any]] | None:
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    original = str(info.get("language") or info.get("original_language") or "").strip()

    def find(
        tracks: dict[str, Any],
        language: str,
        source_kind: str,
        selection_kind: str,
    ) -> tuple[CaptionSelection, dict[str, Any]] | None:
        for code, formats in tracks.items():
            if not _language_match(str(code), language):
                continue
            candidates = list(formats or [])
            selected = next((item for item in candidates if item.get("ext") == "json3"), None)
            if selected and selected.get("url"):
                selection = CaptionSelection(
                    language=str(code),
                    kind=selection_kind,  # type: ignore[arg-type]
                    source_kind=source_kind,  # type: ignore[arg-type]
                )
                return selection, dict(selected)
        return None

    if original:
        result = find(manual, original, "subtitles", "manual")
        if result:
            return result
        result = find(automatic, original, "automatic_captions", "automatic")
        if result:
            return result
    for language in fallback_languages:
        result = find(manual, language, "subtitles", "fallback")
        if result:
            return result
        result = find(automatic, language, "automatic_captions", "fallback")
        if result:
            return result
    return None


def parse_json3(data: bytes | str) -> list[TranscriptSegment]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"invalid captions JSON3: {exc}") from exc
    segments: list[TranscriptSegment] = []
    for event in payload.get("events", []):
        text = re.sub(
            r"\s+",
            " ",
            "".join(str(segment.get("utf8", "")) for segment in event.get("segs", [])),
        ).strip()
        if not text:
            continue
        try:
            start_ms = int(event["tStartMs"])
            end_ms = start_ms + max(0, int(event.get("dDurationMs", 0)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("text event has invalid timing") from exc
        segments.append(TranscriptSegment(start_ms=start_ms, end_ms=end_ms, text=text))
    if not segments:
        raise ValueError("captions JSON3 contains no text segments")
    if any(
        current.start_ms < previous.start_ms
        for previous, current in zip(segments, segments[1:], strict=False)
    ):
        raise ValueError("captions JSON3 timestamps are not chronological")
    return segments


def normalized_stream(texts: Iterable[str]) -> str:
    return re.sub(r"\s+", "", "".join(texts))


def transcript_hash(segments: list[TranscriptSegment]) -> str:
    return hashlib.sha256(normalized_stream(item.text for item in segments).encode()).hexdigest()


def _join(left: str, right: str) -> str:
    separator = " " if re.search(r"[A-Za-z0-9]$", left) and re.match(r"[A-Za-z0-9]", right) else ""
    return f"{left}{separator}{right}"


def _sentences(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    result: list[TranscriptSegment] = []
    buffer = ""
    start: int | None = None
    end = 0
    pending_end = False

    def flush() -> None:
        nonlocal buffer, start, end, pending_end
        text = buffer.strip()
        if text and start is not None:
            result.append(TranscriptSegment(start_ms=start, end_ms=end, text=text))
        buffer, start, end, pending_end = "", None, 0, False

    for segment in segments:
        if buffer and re.search(r"[A-Za-z0-9]$", buffer) and re.match(r"[A-Za-z0-9]", segment.text):
            buffer += " "
        for character in segment.text:
            if pending_end and character not in SENTENCE_CLOSERS:
                flush()
            if start is None:
                start = segment.start_ms
            end = max(end, segment.end_ms)
            buffer += character
            if character in SENTENCE_ENDINGS:
                pending_end = True
    flush()
    return result


def _split_long_segment(segment: TranscriptSegment) -> list[TranscriptSegment]:
    text = segment.text.strip()
    if len(text) <= TARGET_CHARS:
        return [segment.model_copy(update={"text": text})]

    chunks: list[tuple[int, int, str]] = []
    offset = 0
    while offset < len(text):
        limit = min(offset + TARGET_CHARS, len(text))
        end = limit
        if limit < len(text):
            boundary = text.rfind(" ", offset, limit + 1)
            if boundary > offset:
                end = boundary
        chunk = text[offset:end].strip()
        if chunk:
            chunks.append((offset, end, chunk))
        offset = end
        while offset < len(text) and text[offset].isspace():
            offset += 1

    duration = max(0, segment.end_ms - segment.start_ms)
    text_length = len(text)
    return [
        TranscriptSegment(
            start_ms=segment.start_ms + round(duration * start / text_length),
            end_ms=segment.start_ms + round(duration * end / text_length),
            text=chunk,
        )
        for start, end, chunk in chunks
    ]


def group_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    grouped: list[TranscriptSegment] = []
    current: TranscriptSegment | None = None
    sentences = (
        chunk for sentence in _sentences(segments) for chunk in _split_long_segment(sentence)
    )
    for sentence in sentences:
        if current:
            candidate = _join(current.text, sentence.text)
            span = (max(current.end_ms, sentence.end_ms) - current.start_ms) / 1000
            if len(candidate) > TARGET_CHARS or span > MAX_SPAN_SECONDS:
                grouped.append(current)
                current = None
        if current is None:
            current = sentence
        else:
            current = TranscriptSegment(
                start_ms=current.start_ms,
                end_ms=max(current.end_ms, sentence.end_ms),
                text=_join(current.text, sentence.text),
            )
    if current:
        grouped.append(current)
    return grouped


def timestamp(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def render_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n\n".join(
        f"**{timestamp(item.start_ms)}** · {item.text}" for item in group_segments(segments)
    )


def validate_transcript(
    transcript: str,
    expected: list[TranscriptSegment],
    duration_seconds: float | None = None,
    max_tail_gap_seconds: float = 120,
) -> list[str]:
    errors: list[str] = []
    matches = list(TRANSCRIPT_LINE.finditer(transcript))
    invalid = [
        line
        for line in transcript.splitlines()
        if line.strip() and not TRANSCRIPT_LINE.fullmatch(line)
    ]
    if not matches:
        return ["Transcript has no timestamped segments"]
    if invalid:
        errors.append(f"Transcript contains {len(invalid)} non-segment line(s)")
    actual = [match.group("text") for match in matches]
    if normalized_stream(actual) != normalized_stream(item.text for item in expected):
        errors.append("Transcript text does not completely match captions JSON3")
    if max(len(re.sub(r"\s+", "", text)) for text in actual) > MAX_PARAGRAPH_CHARS:
        errors.append(f"Transcript paragraphs must be at most {MAX_PARAGRAPH_CHARS} characters")
    if duration_seconds is not None:
        tail_gap = duration_seconds - expected[-1].end_ms / 1000
        if tail_gap > max_tail_gap_seconds:
            errors.append(f"captions end too far before video end (gap={tail_gap:.1f}s)")
    return errors
