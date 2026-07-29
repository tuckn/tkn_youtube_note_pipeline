"""Codex structured-output summary provider."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from youtube_note_pipeline.models import SummaryDocument, SummaryRequest
from youtube_note_pipeline.prompting import (
    load_summary_prompt,
    render_summary_prompt,
)
from youtube_note_pipeline.providers.base import ProviderResult

logger = logging.getLogger(__name__)
MODEL_LINE = re.compile(r"(?m)^\s*model:\s*(\S+)\s*$")


def _model_from_execution_log(stderr: str) -> str | None:
    match = MODEL_LINE.search(stderr)
    return match.group(1) if match else None


class CodexProvider:
    def __init__(
        self,
        executable: str = "codex",
        model: str | None = None,
        summary_prompt: Path | None = None,
    ) -> None:
        self.executable = executable
        self.model = model
        self.prompt = load_summary_prompt(summary_prompt)

    def preflight(self) -> str:
        logger.debug("Running Codex preflight: %s --version", self.executable)
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                f"Codex preflight failed: {self.executable!r} could not be executed: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Codex preflight failed with exit {result.returncode}: {detail}")
        version = result.stdout.strip() or result.stderr.strip()
        logger.debug("Codex preflight succeeded: %s", version)
        return version

    def generate(self, request: SummaryRequest) -> ProviderResult:
        prompt = render_summary_prompt(self.prompt, request)
        provider_version = self.preflight()
        schema = SummaryDocument.model_json_schema()
        with tempfile.TemporaryDirectory(prefix="youtube-notes-codex-") as temp:
            schema_path = Path(temp) / "summary.schema.json"
            output_path = Path(temp) / "summary.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
            ]
            if self.model:
                command.extend(["--model", self.model])
            command.append("-")
            logger.debug("Starting Codex structured-output execution")
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"Codex summary generation failed: {exc}") from exc
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(
                    f"Codex summary generation failed with exit {result.returncode}: {detail}"
                )
            try:
                payload = output_path.read_text(encoding="utf-8")
                document = SummaryDocument.model_validate_json(payload)
            except (OSError, UnicodeError, ValueError) as exc:
                raise RuntimeError(f"Codex returned invalid structured output: {exc}") from exc
        effective_model = self.model or _model_from_execution_log(result.stderr)
        generator = f"Codex ({effective_model})" if effective_model else "Codex"
        if effective_model:
            logger.info("Codex model: %s", effective_model)
        else:
            logger.warning("Codex did not report its effective model")
        return ProviderResult(
            document=document,
            provider="codex",
            model=effective_model,
            generator=generator,
            provider_version=provider_version,
            prompt_id=self.prompt.prompt_id,
            prompt_version=self.prompt.version,
            prompt_envelope_version=request.prompt_version,
            prompt_source=self.prompt.source,
            prompt_sha256=self.prompt.sha256,
        )
