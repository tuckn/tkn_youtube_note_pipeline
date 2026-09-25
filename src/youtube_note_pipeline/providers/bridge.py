"""Adapt application summary resources to the shared generation runtime."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from tkn_genai_bridge import (
    GenAIError,
    GenerationRequest,
    Profile,
    ProviderError,
    Runtime,
    load_profile,
)
from tkn_genai_bridge.models import PROVIDER_NAMES

from youtube_note_pipeline.models import SummaryRequest
from youtube_note_pipeline.prompting import render_summary_prompt
from youtube_note_pipeline.providers.base import ProviderExecutionError, ProviderResult
from youtube_note_pipeline.summary_resources import (
    DEFAULT_SUMMARY_PROFILE,
    load_summary_profile,
    validate_summary_document,
)

logger = logging.getLogger(__name__)


def _execution_error(exc: GenAIError) -> ProviderExecutionError:
    details: dict[str, Any] = {
        "code": exc.code,
        "generation_record": exc.record.model_dump(mode="json") if exc.record else None,
    }
    if isinstance(exc, ProviderError):
        details.update(
            http_status=exc.http_status,
            retry_after_seconds=exc.retry_after_seconds,
            retryable=exc.retryable,
            submission_unknown=exc.submission_unknown,
        )
    return ProviderExecutionError(
        f"Summary generation failed ({exc.code}): {exc}", error_details=details
    )


class BridgeProvider:
    def __init__(
        self,
        bridge_profile: str = "codex-default",
        summary_profile: str = DEFAULT_SUMMARY_PROFILE,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
        legacy_provider: str | None = None,
        codex_executable: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.profile = load_summary_profile(summary_profile)
        self.bridge_profile = bridge_profile
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.legacy_provider = legacy_provider
        self.codex_executable = codex_executable
        self.overrides = deepcopy(overrides or {})

    def _connection(self) -> Profile:
        # Resolve lazily: an unchanged note needs no provider configuration or runtime.
        overrides = deepcopy(self.overrides)
        if self.model is not None:
            overrides["model"] = self.model
        if self.timeout_seconds is not None:
            overrides["timeout_seconds"] = self.timeout_seconds
        profile = load_profile(self.bridge_profile, overrides=overrides)
        if self.legacy_provider is not None or self.codex_executable is not None:
            if self.legacy_provider not in (None, "codex") or profile.provider != "codex":
                raise ValueError(
                    "legacy provider/codex_executable settings require a Codex Bridge profile; "
                    "remove these settings and select the connection with bridge_profile"
                )
            if self.codex_executable is not None:
                overrides["cli"] = {"executable": self.codex_executable}
                profile = load_profile(self.bridge_profile, overrides=overrides)
        return profile

    def _request(self, request: SummaryRequest | None) -> GenerationRequest:
        return GenerationRequest(
            prompt=(
                render_summary_prompt(self.profile.prompt, request)
                if request is not None else self.profile.prompt.instructions
            ),
            output_schema=self.profile.output_schema.schema,
            schema_name="youtube_summary",
        )

    def plan(self, request: SummaryRequest | None = None) -> dict[str, Any]:
        try:
            connection = self._connection()
            with Runtime(connection) as runtime:
                plan = runtime.plan(self._request(request)).model_dump(mode="json")
        except GenAIError as exc:
            raise _execution_error(exc) from exc
        if request is None:
            # Ingest has not acquired the transcript yet; do not estimate a partial input.
            return {
                key: plan[key] for key in (
                    "provider", "model", "profile_name", "bridge_version",
                    "generation_settings_sha256", "timeout_seconds", "will_call_provider",
                    "local_only",
                )
            } | {
                "reasoning_effort": connection.reasoning_effort,
                "max_output_tokens": connection.max_output_tokens,
            }
        return plan

    def generate(self, request: SummaryRequest) -> ProviderResult:
        try:
            with Runtime(self._connection()) as runtime:
                result = runtime.generate(self._request(request))
        except GenAIError as exc:
            raise _execution_error(exc) from exc
        record = result.record.model_dump(mode="json")
        try:
            document = validate_summary_document(result.data, self.profile.output_schema)
        except ValueError as exc:
            # The domain validator may include output values; keep diagnostics content-free.
            raise ProviderExecutionError(
                "Generated summary failed the application's summary contract",
                error_details={"code": "summary_validation", "generation_record": record},
            ) from exc
        model = result.record.response_model or result.record.requested_model
        name = PROVIDER_NAMES[result.record.provider]
        generator = f"{name} ({model})" if model else name
        logger.info("Summary generator: %s", generator)
        return ProviderResult(
            document=document,
            provider=result.record.provider,
            model=model,
            generator=generator,
            provider_version=None,
            prompt_id=self.profile.prompt.prompt_id,
            prompt_version=self.profile.prompt.version,
            prompt_envelope_version=request.prompt_version,
            prompt_source=self.profile.prompt.source,
            prompt_sha256=self.profile.prompt.sha256,
            output_schema_id=self.profile.output_schema.resource_id,
            output_schema_version=self.profile.output_schema.version,
            output_schema_sha256=self.profile.output_schema.sha256,
            template_id=self.profile.template.resource_id,
            template_version=self.profile.template.version,
            template_sha256=self.profile.template.sha256,
            generation_record=record,
        )
