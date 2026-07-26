import logging

import pytest

from youtube_note_pipeline.cli import _configure_logging, build_parser


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
