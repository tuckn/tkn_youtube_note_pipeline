import json
import logging
from pathlib import Path

import pytest

from youtube_note_pipeline.cli import _configure_logging, build_parser, main


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


@pytest.mark.parametrize("option", ["--force", "--overwrite"])
def test_ingest_accepts_overwrite_aliases(option: str) -> None:
    args = build_parser().parse_args(
        ["ingest", "https://www.youtube.com/watch?v=abcdefghijk", option]
    )
    assert args.overwrite is True


def test_summary_prompt_cli_option() -> None:
    args = build_parser().parse_args(
        [
            "build-summary",
            "source.md",
            "--summary-prompt",
            "custom.md",
        ]
    )
    assert args.summary_prompt == Path("custom.md")


def test_prompt_init_command(tmp_path: Path, monkeypatch, capsys) -> None:
    prompt_root = tmp_path / "prompts"
    monkeypatch.setattr(
        "youtube_note_pipeline.prompting.user_prompts_root",
        lambda: prompt_root,
    )

    assert main(["prompt", "init", "my-summary.md", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    target = prompt_root / "my-summary.md"
    assert payload == {"status": "created", "path": str(target)}
    assert target.read_text(encoding="utf-8").startswith("# Default YouTube summary instructions")

    assert main(["prompt", "init", "my-summary.md", "--quiet"]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_config_show_reports_prompt_provenance(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    custom = tmp_path / "custom.md"
    custom.write_text("# Custom\nSummarize decisions.", encoding="utf-8")
    monkeypatch.setattr(
        "youtube_note_pipeline.config.global_config_path",
        lambda: tmp_path / "missing-global.yaml",
    )

    assert (
        main(
            [
                "config",
                "show",
                "--summary-prompt",
                str(custom),
                "--quiet",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    prompt = payload["values"]["summary_prompt"]
    assert prompt["configured"] == str(custom)
    assert prompt["mode"] == "custom"
    assert prompt["source"] == str(custom)
    assert len(prompt["sha256"]) == 64


@pytest.mark.parametrize("name", ["nested/prompt.md", r"nested\prompt.md", "prompt.txt"])
def test_prompt_init_rejects_invalid_name(name: str, capsys) -> None:
    assert main(["prompt", "init", name, "--quiet"]) == 1
    assert "must be a .md filename" in capsys.readouterr().err
