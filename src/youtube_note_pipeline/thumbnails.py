"""Language-independent YouTube thumbnail URLs."""


def standard_thumbnail_url(video_id: str) -> str:
    """Return the regular maximum-resolution JPEG URL for a video."""
    return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
