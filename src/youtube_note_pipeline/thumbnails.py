"""Language-independent YouTube thumbnail URLs and availability checks."""

from __future__ import annotations

import logging
from http.client import HTTPException
from urllib.request import urlopen

logger = logging.getLogger(__name__)
THUMBNAIL_NAMES = ("maxresdefault", "sddefault", "hqdefault")


def standard_thumbnail_url(video_id: str, selected_url: str | None = None) -> str:
    """Keep a selected standard JPEG, or use the regular-size offline fallback."""
    candidates = [f"https://i.ytimg.com/vi/{video_id}/{name}.jpg" for name in THUMBNAIL_NAMES]
    return selected_url if selected_url in candidates else candidates[-1]


def resolve_thumbnail_url(video_id: str) -> str:
    """Select the largest accessible standard JPEG during online acquisition."""
    for name in THUMBNAIL_NAMES:
        url = f"https://i.ytimg.com/vi/{video_id}/{name}.jpg"
        try:
            with urlopen(url, timeout=10) as response:
                if (
                    response.status == 200
                    and response.headers.get_content_type() == "image/jpeg"
                    and response.read(3) == b"\xff\xd8\xff"
                ):
                    return url
        except (OSError, HTTPException) as exc:
            logger.debug("Thumbnail unavailable: %s (%s)", url, exc)
    logger.warning("Could not verify a thumbnail for %s; using the regular JPEG URL", video_id)
    return standard_thumbnail_url(video_id)
