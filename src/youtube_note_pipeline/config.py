"""Configuration discovery and precedence."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from youtube_note_pipeline.summary_resources import (
    BUILT_IN_SUMMARY_PROFILES,
    DEFAULT_SUMMARY_PROFILE,
)

APP_DIRECTORY = "youtube_note_pipeline"
DEFAULT_CONFIG_RESOURCE = "resources/config.example.yaml"


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_root: Path
    source_root: Path
    summary_root: Path
    reports_root: Path
    provider: str = "codex"
    model: str | None = None
    summary_profile: str = DEFAULT_SUMMARY_PROFILE
    fallback_languages: list[str] = Field(default_factory=list)
    codex_executable: str = "codex"

    @field_validator("summary_profile")
    @classmethod
    def validate_summary_profile(cls, value: str) -> str:
        if value not in BUILT_IN_SUMMARY_PROFILES:
            allowed = ", ".join(BUILT_IN_SUMMARY_PROFILES)
            raise ValueError(f"summary_profile must be one of: {allowed}")
        return value


class ResolvedConfig(BaseModel):
    config: PipelineConfig
    sources: list[str]


def user_root() -> Path:
    return Path.home() / ".tkn" / APP_DIRECTORY


def user_data_root() -> Path:
    return user_root() / "data"


def user_state_root() -> Path:
    return user_root() / "state"


def user_cache_root() -> Path:
    return Path.home() / ".cache" / APP_DIRECTORY


def default_values() -> dict[str, Any]:
    data = user_data_root()
    return {
        "raw_root": data / "raw",
        "source_root": data / "source",
        "summary_root": data / "summary",
        "reports_root": user_state_root() / "reports",
        "provider": "codex",
        "model": None,
        "summary_profile": DEFAULT_SUMMARY_PROFILE,
        "fallback_languages": [],
        "codex_executable": "codex",
    }


def global_config_path() -> Path:
    return user_root() / "config.yaml"


def initialize_user_config() -> tuple[Path, str]:
    resource = files("youtube_note_pipeline").joinpath(DEFAULT_CONFIG_RESOURCE)
    try:
        payload = resource.read_bytes()
    except (OSError, FileNotFoundError) as exc:
        raise RuntimeError(
            f"built-in configuration template is unavailable: {DEFAULT_CONFIG_RESOURCE}: {exc}"
        ) from exc
    target = global_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        try:
            existing = target.read_bytes()
        except OSError as read_exc:
            raise OSError(f"cannot read existing configuration {target}: {read_exc}") from read_exc
        if existing == payload:
            return target, "unchanged"
        raise FileExistsError(
            f"refusing to overwrite existing configuration: {target}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, "created"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read config {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return dict(value)


def _resolve_paths(values: dict[str, Any], cwd: Path) -> dict[str, Any]:
    result = dict(values)
    for key in ("raw_root", "source_root", "summary_root", "reports_root"):
        path = Path(result[key]).expanduser()
        result[key] = path if path.is_absolute() else (cwd / path).resolve()
    return result


def resolve_config(
    cwd: Path | None = None,
    explicit_config: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> ResolvedConfig:
    current = (cwd or Path.cwd()).resolve()
    values = default_values()
    sources = ["built-in defaults"]
    candidates = [global_config_path(), current / ".tkn" / "config.yaml"]
    if explicit_config:
        candidates.append(explicit_config.expanduser().resolve())
    for path in candidates:
        if path.exists():
            values.update(_load_yaml(path))
            sources.append(str(path))
    effective_overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    if effective_overrides:
        values.update(effective_overrides)
        sources.append("CLI options")
    try:
        config = PipelineConfig.model_validate(_resolve_paths(values, current))
    except Exception as exc:
        raise ValueError(f"invalid configuration: {exc}") from exc
    return ResolvedConfig(config=config, sources=sources)


def public_config(config: PipelineConfig) -> dict[str, Any]:
    return {
        "raw_root": str(config.raw_root),
        "source_root": str(config.source_root),
        "summary_root": str(config.summary_root),
        "reports_root": str(config.reports_root),
        "provider": config.provider,
        "model": config.model,
        "summary_profile": config.summary_profile,
        "fallback_languages": config.fallback_languages,
        "codex_executable": config.codex_executable,
    }
