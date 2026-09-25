import json
from copy import deepcopy
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("source_kind", ["subtitles", "automatic_captions"])
@pytest.mark.parametrize("separate_original", [False, True])
def test_untranslated_caption_precedes_translation(source_kind, separate_original) -> None:
    translated = {
        "ext": "json3", "url": "https://example.invalid/captions?lang=en-US&tlang=ja",
    }
    original = {"ext": "json3", "url": "https://example.invalid/captions?lang=ja"}
    tracks = (
        {"ja": [translated], "ja-orig": [original]}
        if separate_original else {"ja": [translated, original]}
    )
    info = {"language": "ja", source_kind: tracks}
    before = deepcopy(info)
    selected = select_caption(info, [])
    assert selected is not None
    selection, track = selected
    assert track == original
    assert selection.language == ("ja-orig" if separate_original else "ja")
    assert selection.source_kind == source_kind
    assert info == before


def test_fallback_language_also_prefers_untranslated_caption() -> None:
    translated = {"ext": "json3", "url": "https://example.invalid/captions?lang=ja&tlang=en"}
    original = {"ext": "json3", "url": "https://example.invalid/captions?lang=en-US"}
    info = {
        "language": "ja",
        "automatic_captions": {"en": [translated], "en-US-orig": [original]},
    }
    selected = select_caption(info, ["en"])
    assert selected is not None
    selection, track = selected
    assert track == original
    assert selection.kind == "fallback"
    assert selection.language == "en-US-orig"


@pytest.mark.parametrize("fallback", [False, True])
def test_translation_remains_available_when_no_original_matches(fallback) -> None:
    translated = {"ext": "json3", "url": "https://example.invalid/captions?lang=en&tlang=ja"}
    info = {
        "language": "en" if fallback else "ja",
        "automatic_captions": {"ja": [translated]},
    }
    selected = select_caption(info, ["ja"] if fallback else [])
    assert selected is not None
    selection, track = selected
    assert track == translated
    assert selection.kind == ("fallback" if fallback else "automatic")


def test_original_preference_does_not_select_an_unrequested_language() -> None:
    translated = {"ext": "json3", "url": "https://example.invalid/captions?lang=en&tlang=ja"}
    english = {"ext": "json3", "url": "https://example.invalid/captions?lang=en"}
    info = {
        "language": "ja",
        "automatic_captions": {"en-orig": [english], "ja": [translated]},
    }
    selected = select_caption(info, ["en"])
    assert selected is not None
    assert selected[1] == translated
    assert selected[0].language == "ja"


def test_caption_selection_skips_unusable_original_formats() -> None:
    translated = {"ext": "json3", "url": "https://example.invalid/captions?lang=en&tlang=ja"}
    info = {
        "language": "ja",
        "automatic_captions": {
            "ja": [
                {"ext": "json3"},
                {"ext": "vtt", "url": "https://example.invalid/captions?lang=ja"},
                translated,
            ],
        },
    }
    selected = select_caption(info, [])
    assert selected is not None
    assert selected[1] == translated


def test_equal_priority_captions_keep_source_order() -> None:
    first = {"ext": "json3", "url": "https://example.invalid/captions?lang=ja&track=first"}
    second = {"ext": "json3", "url": "https://example.invalid/captions?lang=ja&track=second"}
    selected = select_caption(
        {"language": "ja", "automatic_captions": {"ja": [first, second]}}, [],
    )
    assert selected is not None
    assert selected[1] == first


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
