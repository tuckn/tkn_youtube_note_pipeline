from pathlib import Path

import pytest

from youtube_note_pipeline.config import (
    global_config_path,
    resolve_config,
    user_cache_root,
    user_data_root,
    user_root,
    user_state_root,
)
from youtube_note_pipeline.naming import (
    build_filename,
    build_summary_filename,
    file_uri_to_path,
    path_to_file_uri,
)
from youtube_note_pipeline.pipeline import provider_for_config


def test_config_precedence(tmp_path: Path, monkeypatch) -> None:
    configured_root = tmp_path / "user-root"
    monkeypatch.setattr("youtube_note_pipeline.config.user_root", lambda: configured_root)
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
    assert resolved.config.summary_root == configured_root / "data" / "summary"
    assert resolved.config.reports_root == configured_root / "state" / "reports"
    assert str(cwd_config) in resolved.sources
    assert resolved.sources[-1] == "CLI options"


def test_user_directory_layout(tmp_path: Path, monkeypatch) -> None:
    configured_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: configured_home)

    assert user_root() == configured_home / ".tkn" / "youtube_note_pipeline"
    assert global_config_path() == user_root() / "config.yaml"
    assert user_data_root() == user_root() / "data"
    assert user_state_root() == user_root() / "state"
    assert user_cache_root() == configured_home / ".cache" / "youtube_note_pipeline"


def test_removed_summary_prompt_config_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("summary_prompt: custom.md\n", encoding="utf-8")

    with pytest.raises(ValueError, match="summary_prompt"):
        resolve_config(cwd=tmp_path, explicit_config=explicit)


def test_summary_profile_can_be_selected_from_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("summary_profile: default-en\n", encoding="utf-8")

    resolved = resolve_config(cwd=tmp_path, explicit_config=explicit)

    assert resolved.config.summary_profile == "default-en"
    assert provider_for_config(resolved.config).profile.name == "default-en"


def test_unknown_summary_profile_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("summary_profile: custom\n", encoding="utf-8")

    with pytest.raises(ValueError, match="summary_profile must be one of"):
        resolve_config(cwd=tmp_path, explicit_config=explicit)


def test_filename_is_android_safe() -> None:
    year, filename = build_filename("2026-05-23", "長い日本語タイトル" * 30)
    assert year == "2026"
    assert filename.startswith("20260523_")
    assert len(filename.encode("utf-8")) < 200
    assert not any(character in filename for character in '<>:"/\\|?*')


def test_summary_filename_contains_short_prompt_id_and_stays_android_safe() -> None:
    prompt_id = "00000000-0000-4000-8000-000000000010"
    source_filename = "20260523_" + ("長い日本語タイトル" * 20) + ".md"

    filename = build_summary_filename(source_filename, prompt_id)

    assert filename.endswith("_00000000.md")
    assert len(filename.encode("utf-8")) < 200
    assert not any(character in filename for character in '<>:"/\\|?*')


def test_summary_filename_can_extend_prompt_id_prefix() -> None:
    filename = build_summary_filename(
        "20260523_Title.md",
        "70a1a332-fa68-4a6d-9499-d703a17ced3e",
        prompt_id_prefix_length=12,
    )

    assert filename == "20260523_Title_70a1a332fa68.md"


def test_file_uri_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "source note.md"
    uri = path_to_file_uri(path)
    assert uri == path.absolute().as_uri()
    assert file_uri_to_path(uri).resolve() == path.resolve()


def test_windows_file_uri_parser() -> None:
    parsed = file_uri_to_path("file:///C:/path/to/source%20note.md")
    assert parsed.as_posix() == "C:/path/to/source note.md"
