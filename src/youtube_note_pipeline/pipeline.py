"""Pipeline stage orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from youtube_note_pipeline.captions import parse_json3, render_transcript, validate_transcript
from youtube_note_pipeline.config import PipelineConfig
from youtube_note_pipeline.console_logging import log_success
from youtube_note_pipeline.io import atomic_write
from youtube_note_pipeline.models import RawCaptureManifest, SummaryRequest, VideoSource
from youtube_note_pipeline.naming import (
    PROMPT_ID_FILENAME_PREFIX_LENGTHS,
    build_filename,
    build_summary_filename,
)
from youtube_note_pipeline.notes import (
    render_source,
    render_summary,
    split_note,
    transcript_from_source,
)
from youtube_note_pipeline.prompting import PROMPT_ENVELOPE_VERSION
from youtube_note_pipeline.providers import CodexProvider, ProviderExecutionError, SummaryProvider
from youtube_note_pipeline.raw import acquire, import_raw
from youtube_note_pipeline.validation import (
    validate_manifest,
    validate_source,
    validate_source_against_manifest,
    validate_summary,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageResult:
    path: Path
    status: str
    details: dict[str, Any]


def _load_manifest(path: Path) -> RawCaptureManifest:
    errors = validate_manifest(path)
    if errors:
        raise ValueError("manifest validation failed: " + "; ".join(errors))
    manifest = RawCaptureManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.status != "success":
        raise ValueError(f"cannot build derived artifacts from failed capture: {manifest.error}")
    return manifest


def build_source(
    manifest_path: Path,
    source_root: Path,
    overwrite: bool = False,
) -> StageResult:
    logger.info("Building source note from manifest: %s", manifest_path)
    manifest = _load_manifest(manifest_path)
    year, filename = build_filename(manifest.video.published, manifest.video.title)
    target = source_root / year / filename
    if target.exists() and not overwrite:
        metadata, _ = split_note(target.read_text(encoding="utf-8"))
        if metadata.get(
            "url"
        ) == manifest.video.canonical_url and not validate_source_against_manifest(
            target, manifest_path
        ):
            log_success(logger, "Source note is already current: %s", target)
            return StageResult(target, "unchanged", {"validated": True})
        raise FileExistsError(f"source collision: {target}")
    caption = manifest.artifacts["captions"]
    segments = parse_json3((manifest_path.parent / caption.filename).read_bytes())
    transcript_errors = validate_transcript(
        render_transcript(segments),
        segments,
        manifest.video.duration_seconds,
    )
    if transcript_errors:
        raise ValueError("source validation failed: " + "; ".join(transcript_errors))
    text = render_source(manifest, segments, datetime.now().astimezone())
    status = atomic_write(target, text, overwrite=overwrite)
    errors = validate_source_against_manifest(target, manifest_path)
    if errors:
        raise ValueError("source validation failed: " + "; ".join(errors))
    log_success(logger, "Source note %s: %s", status, target)
    return StageResult(target, status, {"segments": len(segments), "validated": True})


def _video_from_source(path: Path) -> VideoSource:
    metadata, _ = split_note(path.read_text(encoding="utf-8"))
    return VideoSource(
        video_id=str(metadata.get("url", "")).split("v=")[-1][:11],
        canonical_url=str(metadata.get("url") or ""),
        title=str(metadata.get("title") or ""),
        author=metadata.get("author"),
        published=str(metadata.get("published") or ""),
        thumbnail=str(metadata.get("cover") or "") or None,
    )


def _frontmatter_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _summary_target(
    source_path: Path,
    summary_root: Path,
    canonical_url: str,
    prompt_id: str,
) -> Path:
    summary_directory = summary_root / source_path.parent.name
    matches: list[Path] = []
    if summary_directory.is_dir():
        for candidate in sorted(summary_directory.iterdir()):
            if not candidate.is_file() or candidate.suffix.lower() != ".md":
                continue
            try:
                metadata, _ = split_note(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                logger.debug(
                    "Skipping summary candidate with unreadable Frontmatter: %s",
                    candidate,
                )
                continue
            if (
                metadata.get("url") == canonical_url
                and str(metadata.get("promptId") or "") == prompt_id
            ):
                matches.append(candidate)
    if len(matches) > 1:
        paths = ", ".join(str(path) for path in matches)
        raise FileExistsError(
            "multiple summary notes share the same url and promptId: " + paths
        )
    if matches:
        return matches[0]

    for prefix_length in PROMPT_ID_FILENAME_PREFIX_LENGTHS:
        candidate = summary_directory / build_summary_filename(
            source_path.name,
            prompt_id,
            prompt_id_prefix_length=prefix_length,
        )
        if not candidate.exists():
            return candidate
    raise FileExistsError(
        "summary filename collision: all supported prompt ID prefixes are in use"
    )


def _summary_resource_provenance_matches(
    metadata: dict[str, Any],
    provider: SummaryProvider,
) -> bool:
    profile = provider.profile
    prompt = profile.prompt
    expected = {
        "promptSha256": prompt.sha256,
        "outputSchemaId": profile.output_schema.resource_id,
        "outputSchemaVersion": profile.output_schema.version,
        "outputSchemaSha256": profile.output_schema.sha256,
        "templateId": profile.template.resource_id,
        "templateVersion": profile.template.version,
        "templateSha256": profile.template.sha256,
    }
    return all(str(metadata.get(key) or "") == value for key, value in expected.items())


def build_summary(
    source_path: Path,
    summary_root: Path,
    provider: SummaryProvider,
    overwrite: bool = False,
) -> StageResult:
    logger.info("Building summary note from source: %s", source_path)
    source_errors = validate_source(source_path)
    if source_errors:
        raise ValueError("source validation failed: " + "; ".join(source_errors))
    video = _video_from_source(source_path)
    profile = provider.profile
    prompt = profile.prompt
    target = _summary_target(
        source_path,
        summary_root,
        video.canonical_url,
        prompt.prompt_id,
    )
    existing_metadata: dict[str, Any] | None = None
    previous_prompt_version: str | None = None
    version_changed = False
    resources_changed = False
    if target.exists():
        existing_metadata, _ = split_note(target.read_text(encoding="utf-8"))
        if (
            existing_metadata.get("url") != video.canonical_url
            or str(existing_metadata.get("promptId")) != prompt.prompt_id
        ):
            raise FileExistsError(f"summary collision: {target}")
        else:
            previous_prompt_version = str(existing_metadata.get("promptVersion") or "")
            version_changed = previous_prompt_version != prompt.version
            uses_resource_provenance = any(
                key in existing_metadata
                for key in ("promptSha256", "outputSchemaId", "templateId")
            )
            resources_changed = uses_resource_provenance and not (
                _summary_resource_provenance_matches(existing_metadata, provider)
            )
            if not overwrite and not version_changed:
                if resources_changed:
                    raise FileExistsError(
                        "summary generation resources changed; use --force to regenerate "
                        f"and replace {target}"
                    )
                if not validate_summary(target):
                    log_success(logger, "Summary note is already current: %s", target)
                    return StageResult(
                        target,
                        "unchanged",
                        {
                            "validated": True,
                            "summary_profile": profile.name,
                            "summary_profile_source": profile.source,
                            "summary_profile_sha256": profile.sha256,
                            "prompt_id": prompt.prompt_id,
                            "prompt_version": prompt.version,
                            "prompt_sha256": prompt.sha256,
                            "output_schema_id": profile.output_schema.resource_id,
                            "output_schema_version": profile.output_schema.version,
                            "output_schema_sha256": profile.output_schema.sha256,
                            "template_id": profile.template.resource_id,
                            "template_version": profile.template.version,
                            "template_sha256": profile.template.sha256,
                        },
                    )
                raise FileExistsError(f"summary collision: {target}")
            if version_changed:
                logger.info(
                    "Summary prompt version changed from %s to %s; updating %s",
                    previous_prompt_version or "<missing>",
                    prompt.version,
                    target,
                )
            elif resources_changed:
                logger.info("Summary generation resources changed; updating %s", target)
    transcript = transcript_from_source(source_path.read_text(encoding="utf-8"))
    input_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    request = SummaryRequest(
        video=video,
        transcript=transcript,
        prompt_version=PROMPT_ENVELOPE_VERSION,
        input_hash=input_hash,
    )
    logger.info("Generating structured summary with the configured provider")
    result = provider.generate(request)
    expected_result_provenance = {
        "prompt_id": prompt.prompt_id,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "output_schema_id": profile.output_schema.resource_id,
        "output_schema_version": profile.output_schema.version,
        "output_schema_sha256": profile.output_schema.sha256,
        "template_id": profile.template.resource_id,
        "template_version": profile.template.version,
        "template_sha256": profile.template.sha256,
    }
    if any(
        getattr(result, field) != expected
        for field, expected in expected_result_provenance.items()
    ):
        raise RuntimeError(
            "provider returned generation provenance that does not match the request"
        )
    logger.info(
        "Summary generation completed with %s",
        result.generator,
    )
    now = datetime.now().astimezone()
    existing_note_id = (
        str(existing_metadata.get("noteId")) if existing_metadata else None
    )
    existing_date = (
        _frontmatter_datetime(existing_metadata["date"])
        if existing_metadata and existing_metadata.get("date")
        else None
    )
    text = render_summary(
        video,
        source_path,
        result.document,
        now,
        result.generator,
        profile,
        note_id=existing_note_id,
        created_at=existing_date,
    )
    status = atomic_write(target, text, overwrite=overwrite or version_changed)
    errors = validate_summary(target)
    if errors:
        raise ValueError("summary validation failed: " + "; ".join(errors))
    log_success(logger, "Summary note %s: %s", status, target)
    return StageResult(
        target,
        status,
        {
            "validated": True,
            "summary_profile": profile.name,
            "summary_profile_source": profile.source,
            "summary_profile_sha256": profile.sha256,
            "provider": result.provider,
            "model": result.model,
            "provider_version": result.provider_version,
            "prompt_id": result.prompt_id,
            "prompt_version": result.prompt_version,
            "prompt_envelope_version": result.prompt_envelope_version,
            "prompt_source": result.prompt_source,
            "prompt_sha256": result.prompt_sha256,
            "output_schema_id": result.output_schema_id,
            "output_schema_version": result.output_schema_version,
            "output_schema_sha256": result.output_schema_sha256,
            "template_id": result.template_id,
            "template_version": result.template_version,
            "template_sha256": result.template_sha256,
            "previous_prompt_version": previous_prompt_version,
            "input_hash": input_hash,
        },
    )


def _provider(config: PipelineConfig) -> SummaryProvider:
    if config.provider != "codex":
        raise ValueError(f"unsupported provider in v1: {config.provider}")
    return CodexProvider(config.codex_executable, config.model, config.summary_profile)


def write_report(
    config: PipelineConfig,
    command: str,
    stages: list[StageResult],
    error: str | None = None,
    *,
    diagnostic_output: str | None = None,
) -> Path:
    now = datetime.now().astimezone()
    run_id = f"{now.strftime('%Y%m%dT%H%M%S%z')}_{uuid.uuid4().hex[:8]}"
    path = config.reports_root / f"{run_id}.json"
    diagnostic_path = None
    if diagnostic_output:
        diagnostic_path = config.reports_root / f"{run_id}.provider.log"
        atomic_write(diagnostic_path, diagnostic_output)
        logger.debug("Provider diagnostic log written: %s", diagnostic_path)
    payload = {
        "schema_version": "1.1",
        "run_id": run_id,
        "command": command,
        "started_at": now.isoformat(timespec="seconds"),
        "status": "failure" if error else "success",
        "error": error,
        "diagnostic_log": str(diagnostic_path) if diagnostic_path else None,
        "stages": [
            {"path": str(stage.path), "status": stage.status, "details": stage.details}
            for stage in stages
        ],
    }
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    logger.debug("Run report written: %s", path)
    return path


def run_acquire(url: str, config: PipelineConfig, refresh: bool = False) -> StageResult:
    logger.info("Acquiring YouTube metadata and captions: %s", url)
    manifest = acquire(url, config.raw_root, config.fallback_languages, refresh)
    parsed = RawCaptureManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    status = "failure" if parsed.status == "failure" else "created"
    if status == "failure":
        logger.error("Raw capture failed: %s", parsed.error)
    else:
        log_success(logger, "Raw capture ready: %s", manifest)
    return StageResult(manifest, status, {"capture_status": parsed.status, "error": parsed.error})


def run_import(
    metadata: Path,
    captions: Path,
    config: PipelineConfig,
    language: str | None = None,
    refresh: bool = False,
) -> StageResult:
    logger.info("Importing external metadata and captions")
    manifest = import_raw(metadata, captions, config.raw_root, language, refresh)
    log_success(logger, "Raw import ready: %s", manifest)
    return StageResult(manifest, "created", {"capture_status": "success"})


def ingest(
    url: str,
    config: PipelineConfig,
    refresh: bool = False,
    overwrite: bool = False,
) -> tuple[list[StageResult], Path]:
    stages: list[StageResult] = []
    logger.info("Starting ingest: %s", url)
    try:
        raw_stage = run_acquire(url, config, refresh)
        stages.append(raw_stage)
        if raw_stage.details["capture_status"] != "success":
            raise RuntimeError(str(raw_stage.details.get("error") or "caption acquisition failed"))
        source_stage = build_source(
            raw_stage.path,
            config.source_root,
            overwrite=overwrite,
        )
        stages.append(source_stage)
        summary_stage = build_summary(
            source_stage.path,
            config.summary_root,
            _provider(config),
            overwrite=overwrite,
        )
        stages.append(summary_stage)
    except Exception as exc:
        diagnostic_output = (
            exc.diagnostic_output if isinstance(exc, ProviderExecutionError) else None
        )
        report = write_report(
            config,
            "ingest",
            stages,
            str(exc),
            diagnostic_output=diagnostic_output,
        )
        raise RuntimeError(f"{exc}; report={report}") from exc
    report = write_report(config, "ingest", stages)
    log_success(logger, "Ingest completed successfully")
    logger.info("Run report: %s", report)
    return stages, report


def provider_for_config(config: PipelineConfig) -> SummaryProvider:
    return _provider(config)
