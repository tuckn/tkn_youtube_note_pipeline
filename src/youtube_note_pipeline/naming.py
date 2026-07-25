"""Portable note naming and file URI helpers."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

INVALID = str.maketrans(
    {
        "<": "＜",
        ">": "＞",
        ":": "：",
        '"': "＂",
        "/": "／",
        "\\": "＼",
        "|": "｜",
        "?": "？",
        "*": "＊",
    }
)


def sanitize_title(title: str) -> str:
    title = "".join(character for character in title if ord(character) >= 32)
    return re.sub(r"\s+", " ", title.translate(INVALID)).strip(" .")


def parse_published(value: str) -> tuple[date, datetime | None]:
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw), None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(normalized)
    return parsed.date(), parsed if "T" in raw else None


def build_filename(published: str, title: str, limit: int = 200) -> tuple[str, str]:
    published_date, published_datetime = parse_published(published)
    if published_datetime is None:
        prefix = published_date.strftime("%Y%m%d")
    else:
        suffix = published_datetime.strftime("%z") if published_datetime.tzinfo else ""
        prefix = published_datetime.strftime("%Y%m%dT%H%M%S") + suffix
    safe = sanitize_title(title)
    if not safe:
        raise ValueError("title is empty after sanitization")
    budget = limit - len(f"{prefix}_.md".encode())
    shortened = ""
    for character in safe[:80]:
        if len((shortened + character).encode("utf-8")) > budget:
            break
        shortened += character
    shortened = shortened.rstrip(" .")
    filename = f"{prefix}_{shortened}.md"
    if not shortened or len(filename.encode("utf-8")) >= limit:
        raise ValueError(f"filename must remain below {limit} UTF-8 bytes")
    return str(published_date.year), filename


def path_to_file_uri(path: Path) -> str:
    return path.absolute().as_uri()


def file_uri_to_path(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme != "file":
        raise ValueError("source must be a file URI")
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)
