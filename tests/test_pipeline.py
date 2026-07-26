import json
from pathlib import Path

import pytest

from youtube_note_pipeline import pipeline
from youtube_note_pipeline.models import (
    KeyPoint,
    SummaryDocument,
    SummarySection,
)
from youtube_note_pipeline.notes import compact_description, split_note
from youtube_note_pipeline.pipeline import build_source, build_summary
from youtube_note_pipeline.providers.base import ProviderResult
from youtube_note_pipeline.raw import import_raw
from youtube_note_pipeline.validation import validate_source, validate_summary

FIXTURES = Path(__file__).parent / "fixtures"


class FakeProvider:
    def generate(self, request):
        assert "最初の論点" in request.transcript
        return ProviderResult(
            document=SummaryDocument(
                description="動画の論点を短く説明する。",
                summary="動画は論点、具体例、結論の順に説明する。",
                structuring=[
                    SummarySection(
                        heading="中心となる考え",
                        details=["最初に論点を提示する。", "次に具体例で説明する。"],
                    )
                ],
                key_points=[KeyPoint(text="最初の論点", timestamp_seconds=0)],
                technical_terms=["pipeline: 段階的なデータ処理"],
                conclusion="論点から結論までを段階的に整理する。",
            ),
            provider="fake",
            model="fixture",
            generator="Fake (fixture)",
            provider_version="test",
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
    assert source_metadata["description"] == "動画は論点、具体例、結論の順に説明する。"
    assert summary_metadata["description"] == "論点から結論までを段階的に整理する。"
    assert source_metadata["cover"] == summary_metadata["cover"]
    assert summary_metadata["schemaVersion"] == "1.0"
    assert summary_metadata["cliptool"] == "Codex"
    assert summary_text.index("description:") < summary_text.index("cover:")
    assert summary_text.index("nouns:") < summary_text.index("url:")
    assert summary_text.index("url:") < summary_text.index("cliptool:")
    assert summary_text.index("cliptool:") < summary_text.index("source:")
    assert summary_text.index("source:") < summary_text.index("generator:")
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
