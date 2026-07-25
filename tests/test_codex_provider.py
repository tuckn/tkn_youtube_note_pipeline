import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from youtube_note_pipeline.models import SummaryRequest, VideoSource
from youtube_note_pipeline.providers.codex import CodexProvider


def request() -> SummaryRequest:
    return SummaryRequest(
        video=VideoSource(
            video_id="TESTVID0001",
            canonical_url="https://www.youtube.com/watch?v=TESTVID0001",
            title="Fixture",
            published="2026-05-23",
        ),
        transcript="**0:00** · 内容です。",
        prompt_version="test-v1",
        input_hash="0" * 64,
    )


def result_json() -> str:
    return json.dumps(
        {
            "description": "説明",
            "summary": "要約",
            "structuring": [{"heading": "構造", "details": ["詳細"]}],
            "key_points": [{"text": "要点", "timestamp_seconds": 0}],
            "technical_terms": [],
            "conclusion": "結論",
        },
        ensure_ascii=False,
    )


def test_codex_structured_output(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return Mock(returncode=0, stdout="codex-cli 1.0", stderr="")
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(result_json(), encoding="utf-8")
        assert kwargs["input"].endswith("**0:00** · 内容です。\n")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = CodexProvider(model="gpt-test").generate(request())
    assert result.generator == "Codex (gpt-test)"
    assert result.document.summary == "要約"


def test_codex_schema_requires_nullable_and_empty_list_fields(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return Mock(returncode=0, stdout="codex-cli 1.0", stderr="")
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
        assert set(schema["required"]) == set(schema["properties"])
        key_point = schema["$defs"]["KeyPoint"]
        assert set(key_point["required"]) == set(key_point["properties"])
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(result_json(), encoding="utf-8")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    CodexProvider().generate(request())


def test_codex_detects_effective_model_from_execution_log(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return Mock(returncode=0, stdout="codex-cli 1.0", stderr="")
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(result_json(), encoding="utf-8")
        return Mock(
            returncode=0,
            stdout="",
            stderr="OpenAI Codex\n--------\nmodel: gpt-5.6-sol\nsandbox: read-only\n",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    result = CodexProvider().generate(request())
    assert result.model == "gpt-5.6-sol"
    assert result.generator == "Codex (gpt-5.6-sol)"


def test_codex_preflight_failure() -> None:
    with patch("subprocess.run", side_effect=OSError("access denied")):
        with pytest.raises(RuntimeError, match="preflight"):
            CodexProvider().generate(request())
