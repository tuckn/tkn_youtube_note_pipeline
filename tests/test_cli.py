import json
import logging
from pathlib import Path

import pytest

from youtube_note_pipeline.cli import _configure_logging, build_parser, main
from youtube_note_pipeline.console_logging import SUCCESS, ColorFormatter


def test_logging_defaults_to_info() -> None:
    args = build_parser().parse_args(["config", "show"])
    _configure_logging(args)
    assert logging.getLogger().level == logging.INFO


def test_quiet_and_verbose_logging_levels() -> None:
    quiet = build_parser().parse_args(["config", "show", "--quiet"])
    _configure_logging(quiet)
    assert logging.getLogger().level == logging.ERROR

    verbose = build_parser().parse_args(["config", "show", "--verbose"])
    _configure_logging(verbose)
    assert logging.getLogger().level == logging.DEBUG


def test_quiet_and_verbose_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["config", "show", "--quiet", "--verbose"])


@pytest.mark.parametrize(
    ("level", "name", "color"),
    [
        (SUCCESS, "SUCCESS", "\x1b[32m"),
        (logging.ERROR, "ERROR", "\x1b[31m"),
    ],
)
def test_console_formatter_colors_success_and_error(
    level: int, name: str, color: str
) -> None:
    formatter = ColorFormatter("[%(levelname)s] %(message)s", use_color=True)
    record = logging.LogRecord("test", level, __file__, 1, "message", (), None)

    assert formatter.format(record) == f"{color}[{name}] message\x1b[0m"


def test_console_formatter_keeps_redirected_output_plain() -> None:
    formatter = ColorFormatter("[%(levelname)s] %(message)s", use_color=False)
    record = logging.LogRecord("test", SUCCESS, __file__, 1, "message", (), None)

    assert formatter.format(record) == "[SUCCESS] message"


@pytest.mark.parametrize("option", ["--force", "--overwrite"])
def test_ingest_accepts_overwrite_aliases(option: str) -> None:
    args = build_parser().parse_args(
        ["ingest", "https://www.youtube.com/watch?v=abcdefghijk", option]
    )
    assert args.overwrite is True


def test_config_show_reports_prompt_provenance(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    assert main(["config", "show", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["values"]["summary_profile"] == "default-ja"
    profile = payload["values"]["summary_profile_details"]
    assert profile["name"] == "default-ja"
    assert profile["source"].endswith("summary_profiles/default-ja")
    assert len(profile["sha256"]) == 64
    prompt = profile["prompt"]
    assert prompt["source"].endswith("summary_profiles/default-ja/prompt.md")
    assert prompt["id"] == "70a1a332-fa68-4a6d-9499-d703a17ced3e"
    assert prompt["version"] == "2.0"
    assert len(prompt["sha256"]) == 64
    assert profile["output_schema"]["id"] == "8135b54f-cc2e-484d-8616-f07e1ee376da"
    assert profile["output_schema"]["source"].endswith(
        "summary_profiles/default-ja/output.schema.json"
    )
    assert profile["template"]["id"] == "682b27ed-e542-4795-b295-107dbebe82f4"
    assert profile["template"]["source"].endswith(
        "summary_profiles/default-ja/template.md"
    )
    assert profile["template"]["note_schema_version"] == "5.0"


def test_config_show_uses_summary_profile_cli_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    assert main(["config", "show", "--summary-profile", "default-en", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["values"]["summary_profile"] == "default-en"
    assert payload["values"]["summary_profile_details"]["name"] == "default-en"


def test_config_init_is_idempotent_and_refuses_edited_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target = tmp_path / "user" / "config.yaml"
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: target,
    )

    assert main(["config", "init", "--quiet"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created == {"status": "created", "path": str(target)}
    assert "provider: codex" in target.read_text(encoding="utf-8")
    assert "summary_profile: default-ja" in target.read_text(encoding="utf-8")

    assert main(["config", "show", "--quiet"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["values"]["provider"] == "codex"
    assert shown["values"]["fallback_languages"] == ["en"]

    assert main(["config", "init", "--quiet"]) == 0
    unchanged = json.loads(capsys.readouterr().out)
    assert unchanged == {"status": "unchanged", "path": str(target)}

    target.write_text("provider: edited\n", encoding="utf-8")
    assert main(["config", "init", "--quiet"]) == 1
    assert "refusing to overwrite existing configuration" in capsys.readouterr().err
