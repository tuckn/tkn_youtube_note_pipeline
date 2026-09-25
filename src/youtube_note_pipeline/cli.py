"""Console interface for tkn-youtube-note."""

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
from youtube_note_pipeline.contracts import summary_currency
from youtube_note_pipeline.inventory import build_inventory
from youtube_note_pipeline.migration import apply_migration, plan_migration
from youtube_note_pipeline.notes import split_note
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
    parser.add_argument("--provider-timeout-seconds", type=float)
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


def _inventory_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--summary-root", type=Path)
    _verbosity(parser)


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
    parser = argparse.ArgumentParser(prog="tkn-youtube-note")
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
    source_parser.add_argument("--force", "--overwrite", dest="overwrite", action="store_true")
    _common(source_parser)

    summary_parser = subparsers.add_parser("build-summary", help="build a summary note")
    summary_parser.add_argument("source_note", type=Path)
    summary_parser.add_argument("--force", "--overwrite", dest="overwrite", action="store_true")
    _common(summary_parser)

    list_parser = subparsers.add_parser(
        "list",
        help="list acquired transcripts and corresponding notes",
    )
    _inventory_options(list_parser)

    validate_parser = subparsers.add_parser("validate", help="validate an artifact")
    validate_parser.add_argument("path", type=Path)
    _common(validate_parser)

    status_parser = subparsers.add_parser("status", help="check validity and profile currency")
    status_parser.add_argument("path", type=Path)
    _common(status_parser)

    migrate_parser = subparsers.add_parser(
        "migrate-notes",
        help="repair source references and migrate legacy notes with backups",
    )
    migrate_parser.add_argument(
        "--apply-plan", type=Path, help="apply a previously reviewed dry-run JSON plan"
    )
    _common(migrate_parser)

    config_parser = subparsers.add_parser("config", help="configuration operations")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    show = config_subparsers.add_parser("show", help="show resolved non-secret configuration")
    _common(show)
    config_init = config_subparsers.add_parser(
        "init",
        help="create the user-global configuration without overwriting edits",
    )
    _verbosity(config_init)

    for mutating in (
        ingest_parser,
        acquire_parser,
        import_parser,
        source_parser,
        summary_parser,
        migrate_parser,
        config_init,
    ):
        mutating.add_argument(
            "--dry-run",
            action="store_true",
            help="validate and preview without writing files, acquiring data, or invoking AI",
        )

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
            "provider_timeout_seconds",
        )
    }
    return resolve_config(explicit_config=getattr(args, "config", None), overrides=overrides)


def _print_result(path: Path, status: str, report: Path | None = None) -> None:
    payload = {"status": status, "path": str(path)}
    if report:
        payload["report"] = str(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    args = build_parser().parse_args(argv)
    _configure_logging(args)
    logger.debug("Parsed command: %s", args.command)
    config: PipelineConfig | None = None
    try:
        if args.command == "config" and args.config_command == "init":
            logger.info("Initializing user-global configuration")
            path, status = initialize_user_config(dry_run=args.dry_run)
            print(
                json.dumps(
                    {"status": status, "path": str(path)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        resolved = _resolved(args)
        config = resolved.config
        logger.debug("Configuration sources: %s", ", ".join(resolved.sources))
        if args.command == "migrate-notes":
            plan = plan_migration(config.source_root, config.summary_root)
            if args.apply_plan:
                approved = json.loads(args.apply_plan.read_text(encoding="utf-8-sig"))
                if not isinstance(approved, dict):
                    raise ValueError("migration plan must be a JSON object")
                if any(approved.get(key) != plan[key] for key in ("source_root", "summary_root")):
                    raise ValueError("migration plan roots do not match resolved configuration")
                if args.dry_run:
                    raise ValueError("--apply-plan and --dry-run cannot be combined")
                plan = approved
            result = plan if args.dry_run else apply_migration(plan, config.reports_root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["counts"].get("blocked", 0) else 0
        if getattr(args, "dry_run", False):
            if args.command in ("ingest", "acquire"):
                if args.command == "ingest":
                    provider_for_config(config)  # Validate profile resources; do not run preflight.
                stage = run_acquire(args.video_url, config, args.refresh, dry_run=True)
                if args.command == "ingest":
                    stage.details["downstream"] = [
                        {
                            "stage": "build-source",
                            "action": "deferred",
                            "reason": "depends on acquired metadata and captions",
                        },
                        {
                            "stage": "build-summary",
                            "action": "deferred",
                            "reason": "depends on source and selected profile; AI not run",
                        },
                    ]
            elif args.command == "import-raw":
                stage = run_import(
                    args.metadata, args.captions, config, args.language, args.refresh, dry_run=True
                )
            elif args.command == "build-source":
                stage = build_source(
                    args.manifest, config.source_root, args.overwrite, dry_run=True
                )
            elif args.command == "build-summary":
                stage = build_summary(
                    args.source_note,
                    config.summary_root,
                    provider_for_config(config),
                    args.overwrite,
                    dry_run=True,
                )
            else:
                raise ValueError("unsupported dry-run command")
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "status": stage.status,
                        "path": str(stage.path),
                        "details": stage.details,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1 if stage.details.get("action") == "require_force" else 0
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
                None if stage.status != "failed" else str(stage.details.get("error")),
            )
            _print_result(stage.path, stage.status, report)
            return 1 if stage.status == "failed" else 0
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
        if args.command == "list":
            logger.info("Listing acquired transcripts and corresponding notes")
            print(
                json.dumps(
                    build_inventory(
                        config.raw_root,
                        config.source_root,
                        config.summary_root,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command in ("validate", "status"):
            logger.info("Validating artifact: %s", args.path)
            kind, errors = validate_path(args.path, config.source_root)
            payload: dict[str, Any] = {"kind": kind, "valid": not errors, "errors": errors}
            if args.command == "status" and kind == "summary":
                metadata, _ = split_note(args.path.read_text(encoding="utf-8"))
                payload["currency"] = summary_currency(
                    metadata, load_summary_profile(config.summary_profile)
                )
            print(
                json.dumps(
                    payload,
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
        if (
            isinstance(exc, ProviderExecutionError)
            and config is not None
            and not getattr(args, "dry_run", False)
        ):
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
