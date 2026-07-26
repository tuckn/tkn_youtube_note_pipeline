"""Configuration discovery and precedence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

APP_DIRECTORY = "youtube_note_pipeline"


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_root: Path
    source_root: Path
    summary_root: Path
    reports_root: Path
    provider: str = "codex"
    model: str | None = None
    fallback_languages: list[str] = Field(default_factory=list)
    codex_executable: str = "codex"


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
        "fallback_languages": [],
        "codex_executable": "codex",
    }


def global_config_path() -> Path:
    return user_root() / "config.yaml"


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
        "fallback_languages": config.fallback_languages,
        "codex_executable": config.codex_executable,
    }
