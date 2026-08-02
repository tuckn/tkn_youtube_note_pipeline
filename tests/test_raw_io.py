from pathlib import Path

import pytest

from youtube_note_pipeline.io import atomic_write
from youtube_note_pipeline.raw import _youtube_dl_options, canonical_video_url, import_raw

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


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=BZYwXkWURIQ&t=53s",
        "https://www.youtube.com/watch?v=BZYwXkWURIQ&list=LL&index=5&t=53s&pp=iAQBsAgC",
    ],
)
def test_ignores_watch_url_parameters_after_video_id(url: str) -> None:
    assert canonical_video_url(url) == (
        "BZYwXkWURIQ",
        "https://www.youtube.com/watch?v=BZYwXkWURIQ",
    )


def test_youtube_dl_cache_uses_user_cache_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("youtube_note_pipeline.raw.user_cache_root", lambda: tmp_path)
    assert _youtube_dl_options()["cachedir"] == str(tmp_path / "yt-dlp")
