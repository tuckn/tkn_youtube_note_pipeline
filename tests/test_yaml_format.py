import json

import pytest
import yaml

from youtube_note_pipeline.notes import split_note
from youtube_note_pipeline.yaml_format import normalize_note, normalize_yaml, yaml_quote


@pytest.mark.parametrize("value", [
    "2026-10-07", "2026-10-07T01:02:03Z", "2026-10-07T01:02:03.123456789+09:00",
    "2026-10-07T01:02:03-05:30",
])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_dates_preserve_spelling_and_become_strings(value, quote):
    source = f"custom: {quote}{value}{quote} # keep\nitems: [{quote}{value}{quote}]\n"
    result = normalize_yaml(source)
    assert f'custom: "{value}" # keep' in result
    assert yaml.safe_load(result) == {"custom": value, "items": [value]}
    assert normalize_yaml(result) == result


@pytest.mark.parametrize("path", [
    r"C:\path\to\notes", "C:/path/to/notes", r"\\server\share\notes",
    r".\notes", r"notes\file.md", r"C:\path\user's notes",
])
def test_windows_paths(path):
    result = normalize_yaml("path: " + json.dumps(path) + "\n")
    assert result.startswith("path: '")
    assert yaml.safe_load(result)["path"] == path
    assert yaml_quote(path) == "'" + path.replace("'", "''") + "'"


def test_note_preserves_body_comments_bom_newlines_and_empty_values():
    source = (
        b'\xef\xbb\xbf---\r\n# comment\r\ndate: 2026-10-07T01:02:03.123456789Z # born\r\n'
        b'updated: "2026-10-07"\r\nempty: ""\r\nnull_value: null\r\nitems: []\r\n'
        b'url: file:///C:/path/2026-10-07.md\r\nnoteId: test\r\n---\r\n\r\n'
        b'# Body\r\ndate: 2000-01-01\r\n'
    )
    expected = source.replace(
        b'date: 2026-10-07T01:02:03.123456789Z',
        b'created: "2026-10-07T01:02:03.123456789Z"',
    )
    assert normalize_note(source) == expected
    assert normalize_note(expected) == expected


def test_legacy_reader_does_not_round_fractional_seconds():
    metadata, _ = split_note("---\ndate: 2026-10-07T01:02:03.123456789Z\n---\n")
    assert metadata["created"] == "2026-10-07T01:02:03.123456789Z"


@pytest.mark.parametrize("text", [
    "date: 2026-01-01\ncreated: 2026-01-02\n", "date: a\ndate: b\n",
])
def test_ambiguous_metadata_is_rejected(text):
    with pytest.raises(ValueError):
        normalize_yaml(text, rename_date=True)


def test_dates_in_prose_and_urls_are_not_reinterpreted():
    text = 'title: 2026-10-07 release notes\nurl: https://example.com/2026-10-07\n'
    assert normalize_yaml(text) == text
