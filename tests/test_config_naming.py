from pathlib import Path

import pytest

from youtube_note_pipeline.config import (
    global_config_path,
    resolve_config,
    user_cache_root,
    user_data_root,
    user_prompts_root,
    user_root,
    user_state_root,
)
from youtube_note_pipeline.naming import (
    build_filename,
    file_uri_to_path,
    path_to_file_uri,
)


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
    explicit.write_text(
        "provider: codex\nsource_root: explicit-source\nsummary_prompt: explicit.md\n"
    )
    resolved = resolve_config(
        cwd=tmp_path,
        explicit_config=explicit,
        overrides={
            "raw_root": tmp_path / "cli-raw",
            "summary_prompt": tmp_path / "cli-summary.md",
        },
    )
    assert resolved.config.provider == "codex"
    assert resolved.config.raw_root == tmp_path / "cli-raw"
    assert resolved.config.source_root == tmp_path / "explicit-source"
    assert resolved.config.summary_root == configured_root / "data" / "summary"
    assert resolved.config.reports_root == configured_root / "state" / "reports"
    assert resolved.config.summary_prompt == tmp_path / "cli-summary.md"
    assert str(cwd_config) in resolved.sources
    assert resolved.sources[-1] == "CLI options"


def test_user_directory_layout(tmp_path: Path, monkeypatch) -> None:
    configured_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: configured_home)

    assert user_root() == configured_home / ".tkn" / "youtube_note_pipeline"
    assert global_config_path() == user_root() / "config.yaml"
    assert user_data_root() == user_root() / "data"
    assert user_state_root() == user_root() / "state"
    assert user_prompts_root() == user_root() / "prompts"
    assert user_cache_root() == configured_home / ".cache" / "youtube_note_pipeline"


def test_summary_prompt_filename_resolves_in_user_prompts_directory(
    tmp_path: Path, monkeypatch
) -> None:
    configured_root = tmp_path / "user-root"
    monkeypatch.setattr("youtube_note_pipeline.config.user_root", lambda: configured_root)
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    resolved = resolve_config(
        cwd=tmp_path,
        overrides={"summary_prompt": Path("my-summary.md")},
    )

    assert resolved.config.summary_prompt == configured_root / "prompts" / "my-summary.md"


def test_summary_prompt_follows_all_configuration_precedence_levels(
    tmp_path: Path, monkeypatch
) -> None:
    configured_root = tmp_path / "user-root"
    monkeypatch.setattr("youtube_note_pipeline.config.user_root", lambda: configured_root)
    global_config = tmp_path / "global.yaml"
    global_config.write_text("summary_prompt: global.md\n", encoding="utf-8")
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: global_config,
    )

    assert resolve_config(cwd=tmp_path).config.summary_prompt == (
        configured_root / "prompts" / "global.md"
    )

    cwd_config = tmp_path / ".tkn" / "config.yaml"
    cwd_config.parent.mkdir()
    cwd_config.write_text("summary_prompt: cwd.md\n", encoding="utf-8")
    assert resolve_config(cwd=tmp_path).config.summary_prompt == (
        configured_root / "prompts" / "cwd.md"
    )

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("summary_prompt: explicit.md\n", encoding="utf-8")
    assert resolve_config(cwd=tmp_path, explicit_config=explicit).config.summary_prompt == (
        configured_root / "prompts" / "explicit.md"
    )

    resolved = resolve_config(
        cwd=tmp_path,
        explicit_config=explicit,
        overrides={"summary_prompt": Path("cli.md")},
    )
    assert resolved.config.summary_prompt == configured_root / "prompts" / "cli.md"


def test_summary_prompt_accepts_expanded_home_and_rejects_nested_relative_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    resolved = resolve_config(
        cwd=tmp_path,
        overrides={"summary_prompt": Path("~/elsewhere/my-summary.md")},
    )
    assert resolved.config.summary_prompt == Path("~/elsewhere/my-summary.md").expanduser()

    with pytest.raises(ValueError, match="filename.*absolute path"):
        resolve_config(
            cwd=tmp_path,
            overrides={"summary_prompt": Path("folder/my-summary.md")},
        )


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
