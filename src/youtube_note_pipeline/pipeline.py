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
from youtube_note_pipeline.providers import BridgeProvider, ProviderExecutionError, SummaryProvider
from youtube_note_pipeline.raw import acquire, canonical_video_url, import_raw
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


def _video_identity(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return canonical_video_url(value)
    except ValueError:
        return None


def _source_target(manifest: RawCaptureManifest, source_root: Path) -> Path:
    matches: list[Path] = []
    if source_root.is_dir():
        for candidate in sorted(source_root.rglob("*.md")):
            try:
                metadata, _ = split_note(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                logger.debug(
                    "Skipping source candidate with unreadable Frontmatter: %s",
                    candidate,
                )
                continue
            identity = _video_identity(metadata.get("url"))
            if identity is not None and identity[0] == manifest.video.video_id:
                matches.append(candidate)
    if len(matches) > 1:
        paths = ", ".join(str(path) for path in matches)
        raise FileExistsError(
            "multiple source notes share the same YouTube video ID "
            f"{manifest.video.video_id}: {paths}"
        )
    if matches:
        return matches[0]
    year, filename = build_filename(manifest.video.published, manifest.video.title)
    return source_root / year / filename


def _frontmatter_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def build_source(
    manifest_path: Path,
    source_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> StageResult:
    logger.info("Building source note from manifest: %s", manifest_path)
    manifest = _load_manifest(manifest_path)
    target = _source_target(manifest, source_root)
    existing_metadata: dict[str, Any] | None = None
    if target.exists():
        try:
            existing_metadata, _ = split_note(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise FileExistsError(f"source collision: {target}") from exc
        existing_identity = _video_identity(existing_metadata.get("url"))
        if existing_identity is None or existing_identity[0] != manifest.video.video_id:
            raise FileExistsError(f"source collision: {target}")
        if not overwrite:
            errors = validate_source_against_manifest(target, manifest_path)
            if not errors:
                log_success(logger, "Source note is already current: %s", target)
                return StageResult(target, "unchanged", {"validated": True})
            if dry_run:
                return StageResult(
                    target,
                    "planned",
                    {
                        "action": "require_force",
                        "reason": "source content or contract differs",
                        "errors": errors,
                    },
                )
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
    if dry_run:
        if existing_metadata and existing_metadata.get("date") is not None:
            _frontmatter_datetime(existing_metadata["date"])
        return StageResult(
            target,
            "planned",
            {
                "action": "update" if target.exists() else "create",
                "validated": True,
                "reason": "explicit overwrite" if target.exists() else "source does not exist",
            },
        )
    now = datetime.now().astimezone()
    existing_note_id = None
    existing_date = None
    if existing_metadata is not None:
        existing_note_id = str(existing_metadata.get("noteId") or "") or None
        if existing_metadata.get("date") is not None:
            existing_date = _frontmatter_datetime(existing_metadata["date"])
    text = render_source(
        manifest,
        segments,
        now,
        note_id=existing_note_id,
        created_at=existing_date,
    )
    status = atomic_write(target, text, overwrite=overwrite)
    errors = validate_source_against_manifest(target, manifest_path)
    if errors:
        raise ValueError("source validation failed: " + "; ".join(errors))
    log_success(logger, "Source note %s: %s", status, target)
    return StageResult(target, status, {"segments": len(segments), "validated": True})


def _video_from_source(path: Path) -> VideoSource:
    metadata, _ = split_note(path.read_text(encoding="utf-8"))
    video_id, canonical_url = canonical_video_url(str(metadata.get("url") or ""))
    return VideoSource(
        video_id=video_id,
        canonical_url=canonical_url,
        title=str(metadata.get("title") or ""),
        author=metadata.get("author"),
        published=str(metadata.get("published") or ""),
        thumbnail=str(metadata.get("cover") or "") or None,
    )


def _summary_target(
    source_path: Path,
    summary_root: Path,
    canonical_url: str,
    prompt_id: str,
) -> Path:
    summary_directory = summary_root / source_path.parent.name
    matches: list[Path] = []
    if summary_root.is_dir():
        for candidate in sorted(summary_root.rglob("*.md")):
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
                _video_identity(metadata.get("url")) == _video_identity(canonical_url)
                and str(metadata.get("promptId") or "") == prompt_id
            ):
                matches.append(candidate)
    if len(matches) > 1:
        paths = ", ".join(str(path) for path in matches)
        raise FileExistsError("multiple summary notes share the same url and promptId: " + paths)
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
    raise FileExistsError("summary filename collision: all supported prompt ID prefixes are in use")


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


def decide_summary_action(
    metadata: dict[str, Any] | None,
    provider: SummaryProvider,
    overwrite: bool,
) -> tuple[str, str]:
    """Shared, side-effect-free execution and preview policy."""
    if metadata is None:
        return "create", "summary does not exist"
    if overwrite:
        return "update", "explicit overwrite"
    profile = provider.profile
    # A new output contract must not automatically replace reviewed content,
    # even if the accompanying prompt version was incremented.
    resource_values = {
        "outputSchemaId": profile.output_schema.resource_id,
        "outputSchemaVersion": profile.output_schema.version,
        "outputSchemaSha256": profile.output_schema.sha256,
        "templateId": profile.template.resource_id,
        "templateVersion": profile.template.version,
        "templateSha256": profile.template.sha256,
    }
    if any(key in metadata for key in resource_values) and any(
        str(metadata.get(key)) != value for key, value in resource_values.items()
    ):
        return "require_force", "output schema or template resources changed"
    if str(metadata.get("promptVersion") or "") != profile.prompt.version:
        return "update", "prompt version changed"
    if metadata.get("promptSha256") and not _summary_resource_provenance_matches(
        metadata, provider
    ):
        return "require_force", "prompt resources changed without a version change"
    return "reuse", "generation resources are unchanged"


def build_summary(
    source_path: Path,
    summary_root: Path,
    provider: SummaryProvider,
    overwrite: bool = False,
    dry_run: bool = False,
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
            _video_identity(existing_metadata.get("url")) != _video_identity(video.canonical_url)
            or str(existing_metadata.get("promptId")) != prompt.prompt_id
        ):
            raise FileExistsError(f"summary collision: {target}")
        else:
            previous_prompt_version = str(existing_metadata.get("promptVersion") or "")
            version_changed = previous_prompt_version != prompt.version
            uses_resource_provenance = any(
                key in existing_metadata for key in ("promptSha256", "outputSchemaId", "templateId")
            )
            resources_changed = uses_resource_provenance and not (
                _summary_resource_provenance_matches(existing_metadata, provider)
            )
            action, reason = decide_summary_action(existing_metadata, provider, overwrite)
            if action == "require_force":
                if dry_run:
                    return StageResult(target, "planned", {"action": action, "reason": reason})
                raise FileExistsError(
                    f"summary generation resources changed; use --force to regenerate {target}"
                )
            if action == "reuse":
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
    if dry_run:
        if existing_metadata and existing_metadata.get("date"):
            _frontmatter_datetime(existing_metadata["date"])
        action, reason = decide_summary_action(existing_metadata, provider, overwrite)
        return StageResult(
            target,
            "planned",
            {
                "action": action,
                "reason": reason,
                "input_hash": input_hash,
                "ai_execution": "not_run",
                "summary_profile": profile.name,
                "bridge_plan": provider.plan(request),
            },
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
        getattr(result, field) != expected for field, expected in expected_result_provenance.items()
    ):
        raise RuntimeError(
            "provider returned generation provenance that does not match the request"
        )
    logger.info(
        "Summary generation completed with %s",
        result.generator,
    )
    now = datetime.now().astimezone()
    existing_note_id = str(existing_metadata.get("noteId")) if existing_metadata else None
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
    errors = validate_summary(target, text=text)
    if errors:
        raise ValueError("summary validation failed: " + "; ".join(errors))
    status = atomic_write(target, text, overwrite=overwrite or version_changed)
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
            "generation_record": result.generation_record,
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
    selected = config.generation.selected
    return BridgeProvider(
        selected.bridge_profile,
        config.summary_profile,
        overrides=selected.overrides,
        legacy_provider=selected.legacy_provider,
    )


def write_report(
    config: PipelineConfig,
    command: str,
    stages: list[StageResult],
    error: str | None = None,
    *,
    diagnostic_output: str | None = None,
    provider_error: dict[str, Any] | None = None,
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
        "schema_version": "1.2",
        "run_id": run_id,
        "command": command,
        "started_at": now.isoformat(timespec="seconds"),
        "status": "failure" if error else "success",
        "error": error,
        "provider_error": provider_error,
        "diagnostic_log": str(diagnostic_path) if diagnostic_path else None,
        "stages": [
            {"path": str(stage.path), "status": stage.status, "details": stage.details}
            for stage in stages
        ],
    }
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    logger.debug("Run report written: %s", path)
    return path


def run_acquire(
    url: str,
    config: PipelineConfig,
    refresh: bool = False,
    dry_run: bool = False,
) -> StageResult:
    logger.info("Acquiring YouTube metadata and captions: %s", url)
    video_id, canonical_url = canonical_video_url(url)
    if dry_run:
        return StageResult(
            config.raw_root / video_id,
            "planned",
            {
                "action": "acquire",
                "url": canonical_url,
                "refresh": refresh,
                "network": "not_run",
                "exact_capture_path": None,
                "reason": "caption availability and content require acquisition",
            },
        )
    previous = set((config.raw_root / video_id).glob("*/manifest.json"))
    manifest = acquire(url, config.raw_root, config.fallback_languages, refresh)
    parsed = RawCaptureManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    status = (
        "failed"
        if parsed.status == "failure"
        else ("unchanged" if manifest in previous else "created")
    )
    if status == "failed":
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
    dry_run: bool = False,
) -> StageResult:
    logger.info("Importing external metadata and captions")
    previous = set(config.raw_root.glob("*/*/manifest.json"))
    manifest = import_raw(metadata, captions, config.raw_root, language, refresh, dry_run=dry_run)
    if dry_run:
        return StageResult(
            manifest,
            "planned",
            {
                "action": "reuse" if manifest in previous else "create",
                "validated": True,
            },
        )
    log_success(logger, "Raw import ready: %s", manifest)
    return StageResult(
        manifest, "unchanged" if manifest in previous else "created", {"capture_status": "success"}
    )


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
            provider_error=exc.error_details if isinstance(exc, ProviderExecutionError) else None,
        )
        raise RuntimeError(f"{exc}; report={report}") from exc
    report = write_report(config, "ingest", stages)
    log_success(logger, "Ingest completed successfully")
    logger.info("Run report: %s", report)
    return stages, report


def provider_for_config(config: PipelineConfig) -> SummaryProvider:
    return _provider(config)
