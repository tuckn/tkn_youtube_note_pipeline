import json
from pathlib import Path

from youtube_note_pipeline.captions import (
    MAX_PARAGRAPH_CHARS,
    TRANSCRIPT_LINE,
    normalized_stream,
    parse_json3,
    render_transcript,
    select_caption,
    validate_transcript,
)
from youtube_note_pipeline.models import TranscriptSegment

FIXTURES = Path(__file__).parent / "fixtures"


def test_caption_selection_order() -> None:
    track = [{"ext": "json3", "url": "https://example.invalid/captions"}]
    info = {
        "language": "ja",
        "subtitles": {"ja": track, "en": track},
        "automatic_captions": {"ja": track},
    }
    selection, _ = select_caption(info, ["en"]) or (None, None)
    assert selection is not None
    assert selection.language == "ja"
    assert selection.kind == "manual"


def test_automatic_original_precedes_fallback() -> None:
    track = [{"ext": "json3", "url": "https://example.invalid/captions"}]
    info = {
        "language": "ja",
        "subtitles": {"en": track},
        "automatic_captions": {"ja-orig": track},
    }
    selection, _ = select_caption(info, ["en"]) or (None, None)
    assert selection is not None
    assert selection.language == "ja-orig"
    assert selection.kind == "automatic"


def test_transcript_full_text_matches_json3() -> None:
    segments = parse_json3((FIXTURES / "captions.ja.json3").read_bytes())
    transcript = render_transcript(segments)
    assert validate_transcript(transcript, segments, 12.0) == []
    assert "最初の論点です。" in transcript
    assert "最後に結論を示します。" in transcript


def test_english_automatic_captions_are_split_into_valid_paragraphs() -> None:
    segments = [
        TranscriptSegment(
            start_ms=0,
            end_ms=40_000,
            text=(
                "A medallion architecture has three layers. "
                "The bronze layer stores raw data. "
                "The silver layer cleans and augments it. "
                "The gold layer presents business-level aggregates. "
            ),
        ),
        TranscriptSegment(
            start_ms=40_000,
            end_ms=80_000,
            text="A long explanation without punctuation " + "repeats useful context " * 20,
        ),
    ]

    transcript = render_transcript(segments)
    lines = [line for line in transcript.splitlines() if line]
    texts = [match.group("text") for line in lines if (match := TRANSCRIPT_LINE.fullmatch(line))]

    assert len(texts) == len(lines)
    assert normalized_stream(texts) == normalized_stream(segment.text for segment in segments)
    assert max(len("".join(text.split())) for text in texts) <= MAX_PARAGRAPH_CHARS
    assert validate_transcript(transcript, segments, 80.0) == []


def test_json3_rejects_empty_events() -> None:
    empty = json.dumps({"events": [{"tStartMs": 0, "segs": []}]})
    try:
        parse_json3(empty)
    except ValueError as exc:
        assert "no text segments" in str(exc)
    else:
        raise AssertionError("empty JSON3 must be rejected")
