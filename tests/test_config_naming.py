from pathlib import Path

from youtube_note_pipeline.config import resolve_config
from youtube_note_pipeline.naming import (
    build_filename,
    file_uri_to_path,
    path_to_file_uri,
)


def test_config_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )
    cwd_config = tmp_path / ".tkn" / "config.yaml"
    cwd_config.parent.mkdir()
    cwd_config.write_text("provider: local-placeholder\nraw_root: cwd-raw\n")
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("provider: codex\nsource_root: explicit-source\n")
    resolved = resolve_config(
        cwd=tmp_path,
        explicit_config=explicit,
        overrides={"raw_root": tmp_path / "cli-raw"},
    )
    assert resolved.config.provider == "codex"
    assert resolved.config.raw_root == tmp_path / "cli-raw"
    assert resolved.config.source_root == tmp_path / "explicit-source"
    assert resolved.config.summary_root == tmp_path / "youtube-notes" / "summary"
    assert str(cwd_config) in resolved.sources
    assert resolved.sources[-1] == "CLI options"


def test_filename_is_android_safe() -> None:
    year, filename = build_filename("2026-05-23", "長い日本語タイトル" * 30)
    assert year == "2026"
    assert filename.startswith("20260523_")
    assert len(filename.encode("utf-8")) < 200
    assert not any(character in filename for character in '<>:"/\\|?*')


def test_file_uri_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "source note.md"
    uri = path_to_file_uri(path)
    assert uri == path.absolute().as_uri()
    assert file_uri_to_path(uri).resolve() == path.resolve()


def test_windows_file_uri_parser() -> None:
    parsed = file_uri_to_path("file:///C:/path/to/source%20note.md")
    assert parsed.as_posix() == "C:/path/to/source note.md"
