"""Console interface for tkn-youtube-note."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NoReturn

import yaml
from pydantic import ValidationError

from youtube_note_pipeline import __version__
from youtube_note_pipeline import config as configuration
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
from youtube_note_pipeline.output import emit, public_result
from youtube_note_pipeline.pipeline import (
    StageResult,
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


class ArgumentFailure(SystemExit):
    """Keep argparse's exit code while letting main render a structured result."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message


class Parser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        raise ArgumentFailure(message)


def _result_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print one machine-readable JSON result instead of key=value lines",
    )
    parser.add_argument(
        "--full-output", action="store_true", default=argparse.SUPPRESS,
        help="include unchanged/skipped migration rows in either output format",
    )
    _verbosity(parser)


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
    parser.add_argument("--profile", help="select a name in generation.profiles")
    parser.add_argument("--bridge-profile", help="override the selected shared Bridge profile")
    parser.add_argument("--model", help="override the model in the selected Bridge profile")
    parser.add_argument(
        "--provider-timeout-seconds", type=float,
        help="override the Bridge timeout (seconds, greater than 0 and at most 86400)",
    )
    parser.add_argument("--summary-profile", choices=BUILT_IN_SUMMARY_PROFILES)
    _result_options(parser)


def _verbosity(parser: argparse.ArgumentParser) -> None:
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="suppress progress logs; errors are still shown",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show detailed diagnostic logs",
    )


def _inventory_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--summary-root", type=Path)
    _result_options(parser)


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
    parser = Parser(
        prog="tkn-youtube-note",
        description="Results: key=value by default, --json for automation. Logs go to stderr.",
        epilog=(
            "Exit codes: 0 success; 1 processing/validation failure; 2 arguments; 130 interrupted."
        ),
    )
    _result_options(parser)
    parser.set_defaults(json=False, full_output=False, quiet=False, verbose=False)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
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
    migrate_parser.add_argument(
        "--authors-only", action="store_true",
        help="copy missing author metadata from matching sources; preserve text and provenance",
    )
    migrate_parser.add_argument(
        "--backup-root", type=Path, help="store original notes separately from migration reports",
    )
    _common(migrate_parser)

    config_parser = subparsers.add_parser("config", help="configuration operations")
    _result_options(config_parser)
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    listing = config_subparsers.add_parser(
        "list",
        help="list resolved non-secret settings and sources as key=value (read-only)",
        description="Read settings without writing files or invoking AI; print key=value lines.",
    )
    _common(listing)
    config_init = config_subparsers.add_parser(
        "init",
        help="create the user-global configuration without overwriting edits",
    )
    _result_options(config_init)

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
            "bridge_profile",
            "profile",
            "model",
            "summary_profile",
            "provider_timeout_seconds",
        )
    }
    return resolve_config(explicit_config=getattr(args, "config", None), overrides=overrides)


def _result(args: argparse.Namespace, payload: dict[str, Any], exit_code: int = 0) -> int:
    command = args.command or "arguments"
    if command == "config":
        command += " " + str(getattr(args, "config_command", ""))
    emit(
        public_result(
            payload, command=command, exit_code=exit_code, full_output=args.full_output,
        ),
        json_output=args.json,
    )
    return exit_code


def _stage_result(
    args: argparse.Namespace, stages: list[StageResult], report: Path, exit_code: int = 0,
) -> int:
    return _result(args, {
        "status": stages[-1].status, "path": str(stages[-1].path), "report": str(report),
        "stages": [
            {"path": str(stage.path), "status": stage.status, "details": stage.details}
            for stage in stages
        ],
    }, exit_code)


def _targets(args: argparse.Namespace, config: PipelineConfig | None) -> dict[str, str]:
    targets = {
        name: str(value)
        for name in (
            "path", "source_note", "manifest", "metadata", "captions", "apply_plan",
            "backup_root", "config",
        )
        if (value := getattr(args, name, None)) is not None
    }
    if args.command == "config" and getattr(args, "config_command", "") == "init":
        targets["config"] = str(configuration.global_config_path())
    if config is not None:
        for name in ("raw_root", "source_root", "summary_root", "reports_root"):
            targets[name] = str(getattr(config, name))
    else:
        targets.setdefault("user_config", str(configuration.global_config_path()))
        targets["cwd_config"] = str(Path.cwd() / ".tkn" / "config.yaml")
    return targets


def _error_message(exc: Exception) -> str:
    cause: BaseException | None = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, ValidationError):
            return "; ".join(
                f"{'.'.join(str(part) for part in row['loc'])}: {row['msg']}"
                for row in cause.errors(
                    include_input=False, include_context=False, include_url=False,
                )
            )
        if isinstance(cause, yaml.YAMLError):
            mark = getattr(cause, "problem_mark", None)
            location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            return "invalid YAML configuration" + location
        cause = cause.__cause__
    return str(exc)


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    tokens = list(sys.argv[1:] if argv is None else argv)
    options = tokens[:tokens.index("--")] if "--" in tokens else tokens
    args = argparse.Namespace(
        command=None, json="--json" in options, full_output="--full-output" in options,
        quiet="--quiet" in options or "-q" in options,
        verbose="--verbose" in options or "-v" in options,
    )
    _configure_logging(args)
    config: PipelineConfig | None = None
    try:
        args = build_parser().parse_args(tokens)
        if args.quiet and args.verbose:
            raise ArgumentFailure("--quiet and --verbose cannot be combined")
        _configure_logging(args)
        logger.debug("Parsed command: %s", args.command)
        if args.command == "config" and args.config_command == "init":
            logger.info("Initializing user-global configuration")
            path, status = initialize_user_config(dry_run=args.dry_run)
            return _result(args, {"status": status, "path": str(path)})
        resolved = _resolved(args)
        config = resolved.config
        logger.debug("Configuration sources: %s", ", ".join(resolved.sources))
        if args.command == "migrate-notes":
            plan = plan_migration(
                config.source_root, config.summary_root, authors_only=args.authors_only
            )
            if args.apply_plan:
                approved = json.loads(args.apply_plan.read_text(encoding="utf-8-sig"))
                if not isinstance(approved, dict):
                    raise ValueError("migration plan must be a JSON object")
                if any(approved.get(key) != plan[key] for key in ("source_root", "summary_root")):
                    raise ValueError("migration plan roots do not match resolved configuration")
                if approved.get("scope", "references") != plan["scope"]:
                    raise ValueError("migration plan scope does not match --authors-only")
                if args.dry_run:
                    raise ValueError("--apply-plan and --dry-run cannot be combined")
                plan = approved
            result = plan if args.dry_run else apply_migration(
                plan, config.reports_root, backup_root=args.backup_root
            )
            if not args.dry_run:
                # apply_migration's persisted report remains unchanged; expose blocked targets here.
                result = dict(result)
                result["attention"] = [row for row in plan["items"] if row["status"] == "blocked"]
                result["warnings"] = plan["warnings"]
            return _result(args, result, 1 if result["counts"].get("blocked", 0) else 0)
        if getattr(args, "dry_run", False):
            if args.command in ("ingest", "acquire"):
                if args.command == "ingest":
                    bridge_plan = provider_for_config(config).plan()
                stage = run_acquire(args.video_url, config, args.refresh, dry_run=True)
                if args.command == "ingest":
                    stage.details["bridge_plan"] = bridge_plan
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
            exit_code = 1 if stage.details.get("action") == "require_force" else 0
            return _result(args, {
                "dry_run": True, "status": stage.status, "path": str(stage.path),
                "details": stage.details,
                "counts": {"require_force" if exit_code else stage.status: 1},
            }, exit_code)
        if args.command == "config":
            logger.info("Showing resolved configuration")
            profile = load_summary_profile(config.summary_profile)
            prompt = profile.prompt
            values = public_config(config)
            generation_resolved = provider_for_config(config).plan() | {
                "active_profile": config.generation.active_profile,
                "summary_profile": config.summary_profile,
            }
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
            config_payload = {
                "sources": resolved.sources,
                "values": values,
                "generationResolved": generation_resolved,
                "winning_sources": resolved.winning_sources,
                "source_schema_versions": resolved.source_schema_versions,
                "effective_schema_version": config.schema_version,
            }
            return _result(args, config_payload)
        if args.command == "ingest":
            stages, report = ingest(
                args.video_url,
                config,
                refresh=args.refresh,
                overwrite=args.overwrite,
            )
            return _stage_result(args, stages, report)
        if args.command == "acquire":
            stage = run_acquire(args.video_url, config, args.refresh)
            report = write_report(
                config,
                "acquire",
                [stage],
                None if stage.status != "failed" else str(stage.details.get("error")),
            )
            return _stage_result(args, [stage], report, 1 if stage.status == "failed" else 0)
        if args.command == "import-raw":
            stage = run_import(args.metadata, args.captions, config, args.language, args.refresh)
            report = write_report(config, "import-raw", [stage])
            return _stage_result(args, [stage], report)
        if args.command == "build-source":
            stage = build_source(args.manifest, config.source_root, args.overwrite)
            report = write_report(config, "build-source", [stage])
            return _stage_result(args, [stage], report)
        if args.command == "build-summary":
            stage = build_summary(
                args.source_note, config.summary_root, provider_for_config(config), args.overwrite
            )
            report = write_report(config, "build-summary", [stage])
            return _stage_result(args, [stage], report)
        if args.command == "list":
            logger.info("Listing acquired transcripts and corresponding notes")
            return _result(args, build_inventory(
                config.raw_root, config.source_root, config.summary_root,
            ))
        if args.command in ("validate", "status"):
            logger.info("Validating artifact: %s", args.path)
            kind, errors = validate_path(args.path, config.source_root)
            payload: dict[str, Any] = {
                "kind": kind, "valid": not errors, "errors": errors, "path": str(args.path),
            }
            if args.command == "status" and kind == "summary":
                metadata, _ = split_note(args.path.read_text(encoding="utf-8"))
                payload["currency"] = summary_currency(
                    metadata, load_summary_profile(config.summary_profile)
                )
            if errors:
                logger.error("Validation failed for %s (%s)", args.path, kind)
            else:
                log_success(logger, "Validation succeeded for %s (%s)", args.path, kind)
            return _result(args, payload, 1 if errors else 0)
    except ArgumentFailure as exc:
        logger.error("%s", exc.message)
        return _result(args, {
            "status": "failed", "error_type": "argument_error", "error": exc.message,
            "counts": {"failed": 1},
        }, 2)
    except BrokenPipeError:
        # The consumer closed stdout; no second result can be delivered.
        return 1
    except KeyboardInterrupt:
        logger.error("Interrupted; inspect existing outputs before retrying")
        return _result(args, {
            "status": "interrupted", "error": "interrupted", "targets": _targets(args, config),
            "counts": {"interrupted": 1},
        }, 130)
    except Exception as exc:
        message = _error_message(exc)
        failure: dict[str, Any] = {
            "status": "failed", "error_type": type(exc).__name__, "error": message,
            "targets": _targets(args, config), "counts": {"failed": 1},
        }
        if isinstance(exc, OSError) and exc.filename:
            failure["path"] = str(exc.filename)
            if exc.filename2:
                failure["path2"] = str(exc.filename2)
        if args.command == "ingest" and "; report=" in message:
            failure["error"], failure["report"] = message.rsplit("; report=", 1)
            try:
                saved = json.loads(Path(failure["report"]).read_text(encoding="utf-8"))
                failure["stages"] = saved["stages"]
                failure["counts"].update(Counter(row["status"] for row in saved["stages"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if (
            isinstance(exc, ProviderExecutionError)
            and config is not None
            and args.command in ("ingest", "build-summary")
            and not getattr(args, "dry_run", False)
        ):
            try:
                failure["report"] = str(write_report(
                    config, args.command, [], str(exc),
                    diagnostic_output=exc.diagnostic_output, provider_error=exc.error_details,
                ))
            except Exception as report_exc:
                failure["report_error"] = _error_message(report_exc)
        logger.error("%s", failure["error"])
        return _result(args, failure, 1)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
