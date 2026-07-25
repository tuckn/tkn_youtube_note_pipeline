from pathlib import Path

import pytest

from youtube_note_pipeline.io import atomic_write
from youtube_note_pipeline.raw import canonical_video_url, import_raw

FIXTURES = Path(__file__).parent / "fixtures"


def test_import_reuses_identical_capture(tmp_path: Path) -> None:
    first = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path,
    )
    second = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path,
    )
    assert first == second
    refreshed = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path,
        refresh=True,
    )
    assert refreshed != first


def test_atomic_write_unchanged_and_collision(tmp_path: Path) -> None:
    path = tmp_path / "artifact.txt"
    assert atomic_write(path, "same") == "created"
    assert atomic_write(path, "same") == "unchanged"
    with pytest.raises(FileExistsError):
        atomic_write(path, "different")
    assert atomic_write(path, "different", overwrite=True) == "updated"


def test_rejects_playlist_url() -> None:
    with pytest.raises(ValueError, match="playlist"):
        canonical_video_url("https://www.youtube.com/watch?v=TESTVID0001&list=PL000000000000000")
