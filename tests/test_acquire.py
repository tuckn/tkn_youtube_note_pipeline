import json
from copy import deepcopy
from pathlib import Path

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

from youtube_note_pipeline.raw import acquire

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.youtube.com/watch?v=TESTVID0001"


@pytest.fixture
def downloader(monkeypatch):
    info = json.loads((FIXTURES / "metadata.info.json").read_text(encoding="utf-8"))
    info["http_headers"] = {"User-Agent": "extractor-agent", "Referer": URL}
    info["subtitles"] = {}
    info["automatic_captions"] = {
        "ja": [{"ext": "json3", "url": "https://example.com/captions", "impersonate": True}]
    }
    info["language"] = "ja"

    class Downloader:
        active = False
        metadata_error = None
        download_error = None
        success = True
        body = (FIXTURES / "captions.ja.json3").read_bytes()

        def __init__(self):
            self.info = info
            self.calls = []

        def __enter__(self):
            self.active = True
            return self

        def __exit__(self, *args):
            self.active = False

        def extract_info(self, url, download):
            assert url == URL
            assert download is False
            if self.metadata_error:
                raise self.metadata_error
            return deepcopy(self.info)

        def sanitize_info(self, extracted):
            return extracted

        def dl(self, filename, info, subtitle):
            assert self.active, "caption download must use the open extraction session"
            assert subtitle is True
            self.calls.append((Path(filename), deepcopy(info)))
            if self.download_error:
                raise self.download_error
            Path(filename).write_bytes(self.body)
            return self.success, True

    instance = Downloader()
    monkeypatch.setattr(yt_dlp, "YoutubeDL", lambda options: instance)
    return instance


@pytest.mark.parametrize("track_headers", [None, {"User-Agent": "track-agent"}])
def test_acquire_keeps_session_and_caption_download_options(tmp_path, downloader, track_headers):
    track = downloader.info["automatic_captions"]["ja"][0]
    if track_headers is not None:
        track["http_headers"] = track_headers
    original = deepcopy(downloader.info)

    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["caption"]["language"] == "ja"
    assert (manifest_path.parent / "captions.ja.json3").read_bytes() == downloader.body
    assert downloader.info == original
    assert len(downloader.calls) == 1
    temporary, requested = downloader.calls[0]
    assert requested["impersonate"] is True
    assert requested["http_headers"] == (track_headers or original["http_headers"])
    assert not temporary.parent.exists()
    assert not downloader.active


def test_acquire_downloads_original_instead_of_translated_caption(tmp_path, downloader):
    original = downloader.info["automatic_captions"]["ja"][0]
    original["url"] = "https://example.com/captions?lang=ja"
    translated = {**original, "url": "https://example.com/captions?lang=en-US&tlang=ja"}
    downloader.info["automatic_captions"]["ja"].insert(0, translated)
    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert len(downloader.calls) == 1
    assert downloader.calls[0][1]["url"] == original["url"]


def test_caption_429_preserves_metadata_without_retries(tmp_path, downloader):
    downloader.download_error = DownloadError("HTTP Error 429: Too Many Requests")
    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failure"
    assert manifest["video"]["title"] == downloader.info["title"]
    assert manifest["caption"]["language"] == "ja"
    assert set(manifest["artifacts"]) == {"metadata"}
    metadata = json.loads((manifest_path.parent / "metadata.info.json").read_text(encoding="utf-8"))
    assert metadata == downloader.info
    assert "captions acquisition failed" in manifest["error"]
    assert "429" in manifest["error"]
    assert "Wait before retrying" in manifest["error"]
    assert "--force does not remove this limit" in manifest["error"]
    assert len(downloader.calls) == 1
    assert not downloader.calls[0][0].parent.exists()
    assert not downloader.active


@pytest.mark.parametrize("failure", ["metadata", "wrong_video", "missing_date"])
def test_metadata_failure_does_not_download_captions(tmp_path, downloader, failure):
    if failure == "metadata":
        downloader.metadata_error = DownloadError("HTTP Error 429: Too Many Requests")
    elif failure == "wrong_video":
        downloader.info["id"] = "OTHERID0001"
    else:
        downloader.info.pop("upload_date", None)
        downloader.info.pop("release_timestamp", None)
    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failure"
    assert manifest["video"]["video_id"] == "TESTVID0001"
    assert manifest["caption"] is None
    assert "metadata acquisition failed" in manifest["error"]
    assert not downloader.calls


@pytest.mark.parametrize("failure", ["invalid_json", "empty_segments", "download_failed"])
def test_bad_caption_is_not_saved_as_success(tmp_path, downloader, failure):
    if failure == "download_failed":
        downloader.success = False
    else:
        downloader.body = (
            b"<html>blocked</html>" if failure == "invalid_json" else b'{"events": []}'
        )
    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failure"
    assert set(manifest["artifacts"]) == {"metadata"}
    assert not (manifest_path.parent / "captions.ja.json3").exists()
    assert not downloader.calls[0][0].parent.exists()


def test_no_allowed_caption_does_not_download(tmp_path, downloader):
    downloader.info["automatic_captions"] = {}
    manifest_path = acquire(URL, tmp_path, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failure"
    assert manifest["error"] == "No allowed complete caption track was available"
    assert manifest["video"]["title"] == downloader.info["title"]
    assert not downloader.calls
