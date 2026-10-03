import logging
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from youtube_note_pipeline import thumbnails

VIDEO_ID = "TESTVID0001"
BASE = f"https://i.ytimg.com/vi/{VIDEO_ID}/"


class Response:
    def __init__(self, status=200, content_type="image/jpeg", data=b"\xff\xd8\xff"):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.data = data
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        return self.data[:size]


@pytest.mark.parametrize("available", ["maxresdefault", "sddefault", "hqdefault"])
def test_selects_first_available_jpeg(monkeypatch, available):
    requested = []
    response = Response()

    def open_url(url, timeout):
        assert timeout == 10
        requested.append(url)
        if url != BASE + available + ".jpg":
            raise HTTPError(url, 404, "Not Found", None, None)
        return response

    monkeypatch.setattr(thumbnails, "urlopen", open_url)
    assert thumbnails.resolve_thumbnail_url(VIDEO_ID) == BASE + available + ".jpg"
    assert requested == [
        BASE + name + ".jpg"
        for name in thumbnails.THUMBNAIL_NAMES[:thumbnails.THUMBNAIL_NAMES.index(available) + 1]
    ]
    assert response.closed


@pytest.mark.parametrize("bad_response", [
    Response(status=404),
    Response(content_type="text/html", data=b"<html>"),
    Response(data=b"<html>"),
])
def test_rejects_error_or_non_image_response(monkeypatch, bad_response):
    good_response = Response()

    def open_url(url, timeout):
        return bad_response if url.endswith("maxresdefault.jpg") else good_response

    monkeypatch.setattr(thumbnails, "urlopen", open_url)
    assert thumbnails.resolve_thumbnail_url(VIDEO_ID) == BASE + "sddefault.jpg"
    assert bad_response.closed
    assert good_response.closed


@pytest.mark.parametrize("error", [URLError("unavailable"), TimeoutError("timeout")])
def test_network_failure_warns_and_uses_offline_fallback(monkeypatch, caplog, error):
    caplog.set_level(logging.WARNING)
    requested = []

    def open_url(url, timeout):
        requested.append(url)
        raise error

    monkeypatch.setattr(thumbnails, "urlopen", open_url)
    assert thumbnails.resolve_thumbnail_url(VIDEO_ID) == BASE + "hqdefault.jpg"
    assert len(requested) == 3
    assert "Could not verify a thumbnail" in caplog.text


@pytest.mark.parametrize("selected", [None,
    "https://i.ytimg.com/vi_lc/TESTVID0001/maxresdefault_en-US.jpg",
    "https://i.ytimg.com/vi_webp/TESTVID0001/maxresdefault.webp",
    "https://i.ytimg.com/vi/OTHERID0001/sddefault.jpg",
])
def test_offline_fallback_does_not_use_localized_or_other_video_image(selected):
    assert thumbnails.standard_thumbnail_url(VIDEO_ID, selected) == BASE + "hqdefault.jpg"
