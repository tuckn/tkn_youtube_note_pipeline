"""Configuration discovery and precedence."""

from __future__ import annotations

import os
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from youtube_note_pipeline.summary_resources import (
    BUILT_IN_SUMMARY_PROFILES,
    DEFAULT_SUMMARY_PROFILE,
)

APP_DIRECTORY = "youtube_note_pipeline"
DEFAULT_CONFIG_RESOURCE = "resources/config.example.yaml"
CONFIG_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


def _merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in layer.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _normalize_layer(layer: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Translate old flat AI settings before merging, preserving layer priority."""
    result = deepcopy(layer)
    legacy_keys = {
        "summary_profile", "bridge_profile", "model", "provider_timeout_seconds",
        "provider", "codex_executable",
    }
    legacy = {key: result.pop(key) for key in legacy_keys if key in result}
    if not legacy:
        return result
    if "generation" in result:
        raise ValueError("do not mix generation with legacy top-level AI settings in one config")
    generation: dict[str, Any] = {}
    if "summary_profile" in legacy:
        generation["summary_profile"] = legacy["summary_profile"]
    connection: dict[str, Any] = {}
    if "bridge_profile" in legacy:
        connection["bridge_profile"] = legacy["bridge_profile"]
    if legacy.get("provider") is not None:
        connection["legacy_provider"] = legacy["provider"]
    overrides: dict[str, Any] = {}
    for old, new in (("model", "model"), ("provider_timeout_seconds", "timeout_seconds")):
        if old in legacy and legacy[old] is not None:
            overrides[new] = legacy[old]
    if legacy.get("codex_executable") is not None:
        overrides["cli"] = {"executable": legacy["codex_executable"]}
        connection.setdefault("legacy_provider", "codex")
    if overrides:
        connection["overrides"] = overrides
    if connection:
        active, previous = _selected_values(base, allow_missing=True)
        connection.setdefault("bridge_profile", previous.get("bridge_profile", "codex-default"))
        generation["profiles"] = {active: connection}
    result["generation"] = generation
    return result


def _selected_values(
    values: dict[str, Any], *, allow_missing: bool = False,
) -> tuple[str, dict[str, Any]]:
    generation = values.get("generation", {})
    if not isinstance(generation, dict):
        raise ValueError("generation must be a mapping")
    active = generation.get("active_profile", "codex")
    profiles = generation.get("profiles", {})
    if not isinstance(active, str) or not isinstance(profiles, dict):
        raise ValueError("generation requires an active_profile name and profiles mapping")
    if active not in profiles and not allow_missing:
        raise ValueError("generation.active_profile must name an entry in generation.profiles")
    selected = profiles.get(active, {})
    if not isinstance(selected, dict) or not isinstance(selected.get("overrides", {}), dict):
        raise ValueError("generation profile and overrides must be mappings")
    return active, selected


class GenerationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bridge_profile: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    # Only populated by the legacy reader; keep the old Codex-only restriction.
    legacy_provider: str | None = None

    @field_validator("bridge_profile")
    @classmethod
    def validate_bridge_profile(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("bridge_profile must not be blank")
        return value


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_profile: str = DEFAULT_SUMMARY_PROFILE
    active_profile: str = Field(default="codex", min_length=1)
    profiles: dict[str, GenerationProfile] = Field(
        default_factory=lambda: {"codex": GenerationProfile(bridge_profile="codex-default")}
    )

    @field_validator("summary_profile")
    @classmethod
    def validate_summary_profile(cls, value: str) -> str:
        if value not in BUILT_IN_SUMMARY_PROFILES:
            allowed = ", ".join(BUILT_IN_SUMMARY_PROFILES)
            raise ValueError(f"summary_profile must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def validate_active_profile(self) -> Self:
        if any(not name.strip() for name in self.profiles):
            raise ValueError("generation profile names must not be blank")
        if self.active_profile not in self.profiles:
            raise ValueError("generation.active_profile must name an entry in generation.profiles")
        return self

    @property
    def selected(self) -> GenerationProfile:
        return self.profiles[self.active_profile]


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = CONFIG_SCHEMA_VERSION
    raw_root: Path
    source_root: Path
    summary_root: Path
    reports_root: Path
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    fallback_languages: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy(cls, value: Any) -> Any:
        return _normalize_layer(value, {}) if isinstance(value, dict) else value

    @property
    def summary_profile(self) -> str:
        return self.generation.summary_profile


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
        "schema_version": CONFIG_SCHEMA_VERSION,
        "generation": GenerationConfig().model_dump(),
        "fallback_languages": [],
    }


def global_config_path() -> Path:
    return user_root() / "config.yaml"


def initialize_user_config(dry_run: bool = False) -> tuple[Path, str]:
    resource = files("youtube_note_pipeline").joinpath(DEFAULT_CONFIG_RESOURCE)
    try:
        payload = resource.read_bytes()
    except (OSError, FileNotFoundError) as exc:
        raise RuntimeError(
            f"built-in configuration template is unavailable: {DEFAULT_CONFIG_RESOURCE}: {exc}"
        ) from exc
    target = global_config_path()
    if dry_run:
        if target.exists():
            if target.read_bytes() == payload:
                return target, "unchanged"
            raise FileExistsError(f"refusing to overwrite existing configuration: {target}")
        return target, "planned"
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
        raise FileExistsError(f"refusing to overwrite existing configuration: {target}") from exc
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
            layer = _load_yaml(path)
            normalized = _normalize_layer(layer, values)
            # In the old format null meant inherit Bridge, clearing an earlier override.
            if "generation" not in layer:
                for old, new in (
                    ("model", "model"), ("provider_timeout_seconds", "timeout_seconds"),
                ):
                    if old in layer and layer[old] is None:
                        _, current_profile = _selected_values(values, allow_missing=True)
                        current_profile.get("overrides", {}).pop(new, None)
            values = _merge(values, normalized)
            sources.append(str(path))
    effective_overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    if effective_overrides:
        generation = values["generation"]
        if not isinstance(generation, dict) or not isinstance(generation.get("profiles"), dict):
            raise ValueError("generation and generation.profiles must be mappings")
        if "profile" in effective_overrides:
            generation["active_profile"] = effective_overrides.pop("profile")
        if "summary_profile" in effective_overrides:
            generation["summary_profile"] = effective_overrides.pop("summary_profile")
        _, selected = _selected_values(values)
        if "bridge_profile" in effective_overrides:
            selected["bridge_profile"] = effective_overrides.pop("bridge_profile")
        for cli_key, bridge_key in (
            ("model", "model"), ("provider_timeout_seconds", "timeout_seconds"),
        ):
            if cli_key in effective_overrides:
                selected.setdefault("overrides", {})[bridge_key] = effective_overrides.pop(cli_key)
        values.update(effective_overrides)
        sources.append("CLI options")
    try:
        config = PipelineConfig.model_validate(_resolve_paths(values, current))
    except Exception as exc:
        raise ValueError(f"invalid configuration: {exc}") from exc
    return ResolvedConfig(config=config, sources=sources)


def public_config(config: PipelineConfig) -> dict[str, Any]:
    return config.model_dump(mode="json", exclude_none=True)
