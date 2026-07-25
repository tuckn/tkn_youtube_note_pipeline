"""Safe file IO helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: str | bytes, overwrite: bool = False) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    existed = path.exists()
    if existed:
        current = path.read_bytes()
        if current == payload:
            return "unchanged"
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite different content: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "updated" if existed else "created"
