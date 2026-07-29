import json
from datetime import datetime
from pathlib import Path

import pytest

from youtube_note_pipeline import pipeline
from youtube_note_pipeline.models import (
    KeyPoint,
    SummaryDocument,
    SummarySection,
)
from youtube_note_pipeline.notes import (
    compact_description,
    split_note,
    update_source_description,
)
from youtube_note_pipeline.pipeline import build_source, build_summary
from youtube_note_pipeline.prompting import SummaryPrompt
from youtube_note_pipeline.providers.base import ProviderResult
from youtube_note_pipeline.raw import import_raw
from youtube_note_pipeline.validation import validate_source, validate_summary

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT_TEST_PROMPT_ID = "00000000-0000-4000-8000-000000000010"


class FakeProvider:
    def __init__(
        self,
        prompt_id: str = DEFAULT_TEST_PROMPT_ID,
        prompt_version: str = "1.0",
        summary: str = "動画は論点、具体例、結論の順に説明する。",
    ) -> None:
        self.prompt = SummaryPrompt(
            prompt_id=prompt_id,
            version=prompt_version,
            instructions="Test instructions.",
            mode="custom",
            source="test:fixture.md",
            sha256="1" * 64,
        )
        self.summary = summary

    def generate(self, request):
        assert "最初の論点" in request.transcript
        return ProviderResult(
            document=SummaryDocument(
                description="動画の論点を短く説明する。",
                summary=self.summary,
                structuring=[
                    SummarySection(
                        heading="中心となる考え",
                        details=["最初に論点を提示する。", "次に具体例で説明する。"],
                    )
                ],
                key_points=[KeyPoint(text="最初の論点", timestamp_seconds=0)],
                technical_terms=[
                    "**pipeline**: 動画では、処理を複数の段階に分ける方法を指す。"
                ],
                conclusion="論点から結論までを段階的に整理する。",
            ),
            provider="fake",
            model="fixture",
            generator="Fake (fixture)",
            provider_version="test",
            prompt_id=self.prompt.prompt_id,
            prompt_version=self.prompt.version,
            prompt_envelope_version=request.prompt_version,
            prompt_source="test:fixture.md",
            prompt_sha256="1" * 64,
        )


def test_full_synthetic_pipeline_and_idempotency(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    assert source.status == "created"
    assert validate_source(source.path) == []
    initial_source_metadata, _ = split_note(source.path.read_text(encoding="utf-8"))
    assert initial_source_metadata["schemaVersion"] == "1.0"
    assert initial_source_metadata["description"] == ""
    assert initial_source_metadata["cover"].endswith("/maxresdefault.jpg")
    assert build_source(manifest, tmp_path / "source").status == "unchanged"

    summary = build_summary(source.path, tmp_path / "summary", FakeProvider())
    assert summary.status == "created"
    assert summary.details["prompt_id"] == DEFAULT_TEST_PROMPT_ID
    assert summary.details["prompt_version"] == "1.0"
    assert summary.details["prompt_envelope_version"] == "youtube-summary-envelope-v1"
    assert summary.details["prompt_source"] == "test:fixture.md"
    assert summary.details["prompt_sha256"] == "1" * 64
    assert validate_summary(summary.path, tmp_path / "source") == []
    assert build_summary(source.path, tmp_path / "summary", FakeProvider()).status == "unchanged"

    source_text = source.path.read_text(encoding="utf-8")
    summary_text = summary.path.read_text(encoding="utf-8")
    source_metadata, _ = split_note(source_text)
    summary_metadata, _ = split_note(summary_text)
    assert "\nsummary:" not in source_text
    assert 'source: "file:' in summary_text
    assert 'author: "Example Channel"' in source_text
    assert "nouns: []" in summary_text
    assert (
        "- **pipeline**: 動画では、処理を複数の段階に分ける方法を指す。"
        in summary_text
    )
    assert source_metadata["description"] == ""
    assert summary_metadata["description"] == "論点から結論までを段階的に整理する。"
    assert source_metadata["cover"] == summary_metadata["cover"]
    assert summary_metadata["schemaVersion"] == "2.0"
    assert summary_metadata["promptId"] == DEFAULT_TEST_PROMPT_ID
    assert summary_metadata["promptVersion"] == "1.0"
    assert summary_metadata["cliptool"] == "Codex"
    assert summary_text.index("description:") < summary_text.index("cover:")
    assert summary_text.index("nouns:") < summary_text.index("url:")
    assert summary_text.index("url:") < summary_text.index("cliptool:")
    assert summary_text.index("cliptool:") < summary_text.index("source:")
    assert summary_text.index("source:") < summary_text.index("generator:")
    assert summary_text.index("generator:") < summary_text.index("promptId:")
    assert summary_text.index("promptId:") < summary_text.index("promptVersion:")
    assert summary_text.index("promptVersion:") < summary_text.index("reviewStatus:")
    assert summary_text.index("reviewStatus:") < summary_text.index("date:")
    assert summary_text.index("date:") < summary_text.index("updated:")
    assert summary_text.index("updated:") < summary_text.index("noteId:")


def test_compact_description_uses_a_sentence_boundary_or_ellipsis() -> None:
    sentence = "短い文です。" * 30
    compacted = compact_description(sentence, max_chars=40)
    assert compacted.endswith("。")
    assert len(compacted) <= 40

    compacted_without_boundary = compact_description("a" * 50, max_chars=20)
    assert compacted_without_boundary == "a" * 19 + "…"


def test_changed_caption_is_a_source_collision(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        raw_root,
    )
    build_source(manifest, tmp_path / "source")
    changed_payload = json.loads((FIXTURES / "captions.ja.json3").read_text(encoding="utf-8"))
    changed_payload["events"][0]["segs"][0]["utf8"] = "変更された論点です。"
    changed_captions = tmp_path / "captions.ja.json3"
    changed_captions.write_text(json.dumps(changed_payload, ensure_ascii=False), encoding="utf-8")
    changed_manifest = import_raw(
        FIXTURES / "metadata.info.json",
        changed_captions,
        raw_root,
        refresh=True,
    )
    with pytest.raises(FileExistsError, match="collision"):
        build_source(changed_manifest, tmp_path / "source")

    replaced = build_source(changed_manifest, tmp_path / "source", overwrite=True)
    assert replaced.status == "updated"
    assert "変更された論点です。" in replaced.path.read_text(encoding="utf-8")
    assert validate_source(replaced.path) == []


def test_transcript_validation_failure_does_not_persist_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source_root = tmp_path / "source"
    monkeypatch.setattr(pipeline, "validate_transcript", lambda *args, **kwargs: ["invalid"])

    with pytest.raises(ValueError, match="source validation failed"):
        build_source(manifest, source_root)

    assert not list(source_root.rglob("*.md"))


def test_reviewed_summary_remains_valid_and_idempotent(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    summary = build_summary(source.path, tmp_path / "summary", FakeProvider())
    generated_text = summary.path.read_text(encoding="utf-8")

    review_statuses = (
        "unreviewed",
        "pending",
        "reviewing",
        "accepted",
        "needs-revision",
        "rejected",
    )
    for review_status in review_statuses:
        reviewed_text = generated_text.replace(
            "reviewStatus: unreviewed",
            f"reviewStatus: {review_status}",
        )
        summary.path.write_text(reviewed_text, encoding="utf-8")
        assert validate_summary(summary.path, tmp_path / "source") == []

    accepted_text = generated_text.replace(
        "reviewStatus: unreviewed",
        "reviewStatus: accepted",
    )
    summary.path.write_text(accepted_text, encoding="utf-8")
    assert build_summary(source.path, tmp_path / "summary", FakeProvider()).status == "unchanged"

    invalid_text = generated_text.replace(
        "reviewStatus: unreviewed",
        "reviewStatus: unknown",
    )
    summary.path.write_text(invalid_text, encoding="utf-8")
    assert validate_summary(summary.path, tmp_path / "source") == [
        "reviewStatus must be one of: "
        "unreviewed, pending, reviewing, accepted, needs-revision, rejected"
    ]


def test_different_prompt_id_creates_a_separate_summary(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    first = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(prompt_id="11111111-0000-4000-8000-000000000011"),
    )
    second = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(prompt_id="22222222-0000-4000-8000-000000000012"),
    )

    assert first.path != second.path
    assert first.path.is_file()
    assert second.path.is_file()
    assert first.path.name.endswith("_11111111.md")
    assert second.path.name.endswith("_22222222.md")
    assert validate_summary(first.path, tmp_path / "source") == []
    assert validate_summary(second.path, tmp_path / "source") == []


def test_prompt_id_filename_prefix_extends_only_on_collision(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    first_id = "70a1a332-fa68-4a6d-9499-d703a17ced3e"
    second_id = "70a1a332-aa68-4a6d-9499-d703a17ced3e"

    first = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(prompt_id=first_id),
    )
    second = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(prompt_id=second_id),
    )

    assert first.path.name.endswith("_70a1a332.md")
    assert second.path.name.endswith("_70a1a332aa68.md")
    first_metadata, _ = split_note(first.path.read_text(encoding="utf-8"))
    second_metadata, _ = split_note(second.path.read_text(encoding="utf-8"))
    assert first_metadata["promptId"] == first_id
    assert second_metadata["promptId"] == second_id


def test_existing_summary_is_found_by_frontmatter_after_rename(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    generated = build_summary(source.path, tmp_path / "summary", FakeProvider())
    renamed_path = generated.path.with_name("manually-renamed-summary.md")
    generated.path.rename(renamed_path)

    existing = build_summary(source.path, tmp_path / "summary", FakeProvider())

    assert existing.status == "unchanged"
    assert existing.path == renamed_path
    assert validate_summary(renamed_path, tmp_path / "source") == []


def test_duplicate_summary_frontmatter_identity_is_rejected(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    generated = build_summary(source.path, tmp_path / "summary", FakeProvider())
    duplicate = generated.path.with_name("duplicate-summary.md")
    duplicate.write_text(generated.path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(
        FileExistsError,
        match="multiple summary notes share the same url and promptId",
    ):
        build_summary(source.path, tmp_path / "summary", FakeProvider())


def test_prompt_version_change_updates_same_summary_and_preserves_note_identity(
    tmp_path: Path,
) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    first = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(prompt_version="1.0"),
    )
    first_metadata, _ = split_note(first.path.read_text(encoding="utf-8"))

    updated = build_summary(
        source.path,
        tmp_path / "summary",
        FakeProvider(
            prompt_version="2.0",
            summary="更新したpromptで、論点と具体例を再構成する。",
        ),
    )
    updated_metadata, updated_body = split_note(updated.path.read_text(encoding="utf-8"))

    assert updated.status == "updated"
    assert updated.path == first.path
    assert updated.details["previous_prompt_version"] == "1.0"
    assert updated_metadata["promptVersion"] == "2.0"
    assert updated_metadata["noteId"] == first_metadata["noteId"]
    assert updated_metadata["date"] == first_metadata["date"]
    assert updated_metadata["updated"] >= first_metadata["updated"]
    assert updated_metadata["reviewStatus"] == "unreviewed"
    assert "更新したpromptで" in updated_body
    assert validate_summary(updated.path, tmp_path / "source") == []


def test_legacy_summary_schema_1_remains_valid(tmp_path: Path) -> None:
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        tmp_path / "raw",
    )
    source = build_source(manifest, tmp_path / "source")
    generated = build_summary(source.path, tmp_path / "summary", FakeProvider())
    generated_text = generated.path.read_text(encoding="utf-8")
    legacy_text = (
        generated_text.replace('schemaVersion: "2.0"', 'schemaVersion: "1.0"')
        .replace(f"promptId: {DEFAULT_TEST_PROMPT_ID}\n", "")
        .replace('promptVersion: "1.0"\n', "")
    )
    legacy_path = generated.path.parent / source.path.name
    legacy_path.write_text(legacy_text, encoding="utf-8")
    source_text = source.path.read_text(encoding="utf-8")
    source.path.write_text(
        update_source_description(
            source_text,
            "動画は論点、具体例、結論の順に説明する。",
            datetime.now().astimezone(),
        ),
        encoding="utf-8",
    )

    assert validate_summary(legacy_path, tmp_path / "source") == []
