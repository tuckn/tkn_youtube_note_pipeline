"""Console interface for youtube-notes."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from youtube_note_pipeline.config import (
    PipelineConfig,
    initialize_user_config,
    public_config,
    resolve_config,
)
from youtube_note_pipeline.console_logging import ColorFormatter, log_success, supports_color
from youtube_note_pipeline.pipeline import (
    build_source,
    build_summary,
    ingest,
    provider_for_config,
    run_acquire,
    run_import,
    write_report,
)
from youtube_note_pipeline.providers import ProviderExecutionError
from youtube_note_pipeline.summary_resources import (
    BUILT_IN_SUMMARY_PROFILES,
    load_summary_profile,
)
from youtube_note_pipeline.validation import validate_path

logger = logging.getLogger(__name__)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--summary-root", type=Path)
    parser.add_argument("--reports-root", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--summary-profile", choices=BUILT_IN_SUMMARY_PROFILES)
    _verbosity(parser)


def _verbosity(parser: argparse.ArgumentParser) -> None:
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress progress logs; errors are still shown",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show detailed diagnostic logs",
    )


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.DEBUG if args.verbose else logging.ERROR if args.quiet else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        ColorFormatter(
            "[%(levelname)s] %(message)s",
            use_color=supports_color(sys.stderr),
        )
    )
    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtube-notes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest", help="run raw, source, and summary stages")
    ingest_parser.add_argument("video_url")
    ingest_parser.add_argument("--refresh", action="store_true")
    ingest_parser.add_argument(
        "--force",
        "--overwrite",
        dest="overwrite",
        action="store_true",
        help="overwrite existing source and summary notes with regenerated content",
    )
    _common(ingest_parser)

    acquire_parser = subparsers.add_parser("acquire", help="capture metadata and captions")
    acquire_parser.add_argument("video_url")
    acquire_parser.add_argument("--refresh", action="store_true")
    _common(acquire_parser)

    import_parser = subparsers.add_parser("import-raw", help="import external acquisition JSON")
    import_parser.add_argument("--metadata", type=Path, required=True)
    import_parser.add_argument("--captions", type=Path, required=True)
    import_parser.add_argument("--language")
    import_parser.add_argument("--refresh", action="store_true")
    _common(import_parser)

    source_parser = subparsers.add_parser("build-source", help="build a source note")
    source_parser.add_argument("manifest", type=Path)
    source_parser.add_argument("--overwrite", action="store_true")
    _common(source_parser)

    summary_parser = subparsers.add_parser("build-summary", help="build a summary note")
    summary_parser.add_argument("source_note", type=Path)
    summary_parser.add_argument("--overwrite", action="store_true")
    _common(summary_parser)

    validate_parser = subparsers.add_parser("validate", help="validate an artifact")
    validate_parser.add_argument("path", type=Path)
    _common(validate_parser)

    config_parser = subparsers.add_parser("config", help="configuration operations")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    show = config_subparsers.add_parser("show", help="show resolved non-secret configuration")
    _common(show)
    config_init = config_subparsers.add_parser(
        "init",
        help="create the user-global configuration without overwriting edits",
    )
    _verbosity(config_init)

    return parser


def _resolved(args: argparse.Namespace) -> Any:
    overrides = {
        key: getattr(args, key, None)
        for key in (
            "raw_root",
            "source_root",
            "summary_root",
            "reports_root",
            "model",
            "summary_profile",
        )
    }
    return resolve_config(explicit_config=getattr(args, "config", None), overrides=overrides)


def _print_result(path: Path, status: str, report: Path | None = None) -> None:
    payload = {"status": status, "path": str(path)}
    if report:
        payload["report"] = str(report)
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    args = build_parser().parse_args(argv)
    _configure_logging(args)
    logger.debug("Parsed command: %s", args.command)
    config: PipelineConfig | None = None
    try:
        if args.command == "config" and args.config_command == "init":
            logger.info("Initializing user-global configuration")
            path, status = initialize_user_config()
            print(json.dumps({"status": status, "path": str(path)}, ensure_ascii=False))
            return 0
        resolved = _resolved(args)
        config = resolved.config
        logger.debug("Configuration sources: %s", ", ".join(resolved.sources))
        if args.command == "config":
            logger.info("Showing resolved configuration")
            profile = load_summary_profile(config.summary_profile)
            prompt = profile.prompt
            values = public_config(config)
            values["summary_profile_details"] = {
                "name": profile.name,
                "source": profile.source,
                "sha256": profile.sha256,
                "prompt": {
                    "source": prompt.source,
                    "id": prompt.prompt_id,
                    "version": prompt.version,
                    "sha256": prompt.sha256,
                },
                "output_schema": {
                    "source": profile.output_schema.source,
                    "id": profile.output_schema.resource_id,
                    "version": profile.output_schema.version,
                    "sha256": profile.output_schema.sha256,
                },
                "template": {
                    "source": profile.template.source,
                    "id": profile.template.resource_id,
                    "version": profile.template.version,
                    "sha256": profile.template.sha256,
                    "note_schema_version": profile.template.note_schema_version,
                },
            }
            print(
                json.dumps(
                    {"sources": resolved.sources, "values": values},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "ingest":
            stages, report = ingest(
                args.video_url,
                config,
                refresh=args.refresh,
                overwrite=args.overwrite,
            )
            _print_result(stages[-1].path, stages[-1].status, report)
            return 0
        if args.command == "acquire":
            stage = run_acquire(args.video_url, config, args.refresh)
            report = write_report(
                config,
                "acquire",
                [stage],
                None if stage.status != "failure" else str(stage.details.get("error")),
            )
            _print_result(stage.path, stage.status, report)
            return 1 if stage.status == "failure" else 0
        if args.command == "import-raw":
            stage = run_import(args.metadata, args.captions, config, args.language, args.refresh)
            report = write_report(config, "import-raw", [stage])
            _print_result(stage.path, stage.status, report)
            return 0
        if args.command == "build-source":
            stage = build_source(args.manifest, config.source_root, args.overwrite)
            report = write_report(config, "build-source", [stage])
            _print_result(stage.path, stage.status, report)
            return 0
        if args.command == "build-summary":
            stage = build_summary(
                args.source_note, config.summary_root, provider_for_config(config), args.overwrite
            )
            report = write_report(config, "build-summary", [stage])
            _print_result(stage.path, stage.status, report)
            return 0
        if args.command == "validate":
            logger.info("Validating artifact: %s", args.path)
            kind, errors = validate_path(args.path, config.source_root)
            print(
                json.dumps(
                    {"kind": kind, "valid": not errors, "errors": errors},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if errors:
                logger.error("Validation failed for %s (%s)", args.path, kind)
            else:
                log_success(logger, "Validation succeeded for %s (%s)", args.path, kind)
            return 1 if errors else 0
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, ProviderExecutionError) and config is not None:
            report = write_report(
                config,
                args.command,
                [],
                str(exc),
                diagnostic_output=exc.diagnostic_output,
            )
            logger.error("%s; report=%s", exc, report)
        else:
            logger.error("%s", exc)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
