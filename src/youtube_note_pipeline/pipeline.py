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
from youtube_note_pipeline.io import atomic_write
from youtube_note_pipeline.models import RawCaptureManifest, SummaryRequest, VideoSource
from youtube_note_pipeline.naming import build_filename
from youtube_note_pipeline.notes import (
    render_source,
    render_summary,
    split_note,
    summary_section,
    transcript_from_source,
    update_source_description,
)
from youtube_note_pipeline.prompting import PROMPT_VERSION
from youtube_note_pipeline.providers import CodexProvider, SummaryProvider
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
            logger.info("Source note is already current: %s", target)
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
    logger.info("Source note %s: %s", status, target)
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


def _sync_source_description(
    source_path: Path,
    summary: str,
    updated: datetime,
) -> str:
    source_text = source_path.read_text(encoding="utf-8")
    revised = update_source_description(source_text, summary, updated)
    status = atomic_write(source_path, revised, overwrite=True)
    errors = validate_source(source_path)
    if errors:
        raise ValueError("source metadata sync failed: " + "; ".join(errors))
    return status


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
    target = summary_root / source_path.parent.name / source_path.name
    if target.exists() and not overwrite:
        metadata, body = split_note(target.read_text(encoding="utf-8"))
        if metadata.get("url") == video.canonical_url:
            summary = summary_section(
                body,
                "## 1. Summary",
                "## 2. Structuring (from abstract to concrete)",
            )
            source_status = _sync_source_description(
                source_path,
                summary,
                datetime.fromisoformat(str(metadata["updated"])),
            )
            if not validate_summary(target):
                logger.info("Summary note is already current: %s", target)
                return StageResult(
                    target,
                    "unchanged",
                    {"validated": True, "source_status": source_status},
                )
        raise FileExistsError(f"summary collision: {target}")
    transcript = transcript_from_source(source_path.read_text(encoding="utf-8"))
    input_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    request = SummaryRequest(
        video=video,
        transcript=transcript,
        prompt_version=PROMPT_VERSION,
        input_hash=input_hash,
    )
    logger.info("Generating structured summary with the configured provider")
    result = provider.generate(request)
    logger.info(
        "Summary generation completed with %s",
        result.generator,
    )
    now = datetime.now().astimezone()
    text = render_summary(
        video,
        source_path,
        result.document,
        now,
        result.generator,
    )
    status = atomic_write(target, text, overwrite=overwrite)
    source_status = _sync_source_description(source_path, result.document.summary, now)
    errors = validate_summary(target)
    if errors:
        raise ValueError("summary validation failed: " + "; ".join(errors))
    logger.info("Summary note %s: %s", status, target)
    logger.info("Source description %s: %s", source_status, source_path)
    return StageResult(
        target,
        status,
        {
            "validated": True,
            "provider": result.provider,
            "model": result.model,
            "provider_version": result.provider_version,
            "prompt_version": result.prompt_version or PROMPT_VERSION,
            "prompt_source": result.prompt_source,
            "prompt_sha256": result.prompt_sha256,
            "input_hash": input_hash,
            "source_status": source_status,
        },
    )


def _provider(config: PipelineConfig) -> SummaryProvider:
    if config.provider != "codex":
        raise ValueError(f"unsupported provider in v1: {config.provider}")
    return CodexProvider(config.codex_executable, config.model, config.summary_prompt)


def write_report(
    config: PipelineConfig, command: str, stages: list[StageResult], error: str | None = None
) -> Path:
    now = datetime.now().astimezone()
    run_id = f"{now.strftime('%Y%m%dT%H%M%S%z')}_{uuid.uuid4().hex[:8]}"
    path = config.reports_root / f"{run_id}.json"
    payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "command": command,
        "started_at": now.isoformat(timespec="seconds"),
        "status": "failure" if error else "success",
        "error": error,
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
        logger.info("Raw capture ready: %s", manifest)
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
    logger.info("Raw import ready: %s", manifest)
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
        report = write_report(config, "ingest", stages, str(exc))
        raise RuntimeError(f"{exc}; report={report}") from exc
    report = write_report(config, "ingest", stages)
    logger.info("Ingest completed successfully")
    logger.info("Run report: %s", report)
    return stages, report


def provider_for_config(config: PipelineConfig) -> SummaryProvider:
    return _provider(config)
