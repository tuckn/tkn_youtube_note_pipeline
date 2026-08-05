import json
from pathlib import Path
from types import SimpleNamespace

from youtube_note_pipeline.cli import main
from youtube_note_pipeline.config import PipelineConfig
from youtube_note_pipeline.inventory import build_inventory
from youtube_note_pipeline.notes import split_note
from youtube_note_pipeline.pipeline import build_source
from youtube_note_pipeline.raw import import_raw

FIXTURES = Path(__file__).parent / "fixtures"


def _create_inventory(tmp_path: Path) -> tuple[PipelineConfig, Path, Path]:
    config = PipelineConfig(
        raw_root=tmp_path / "raw",
        source_root=tmp_path / "source",
        summary_root=tmp_path / "summary",
        reports_root=tmp_path / "reports",
    )
    manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        config.raw_root,
    )
    source = build_source(manifest, config.source_root)
    source_metadata, _ = split_note(source.path.read_text(encoding="utf-8"))
    summary = config.summary_root / source.path.parent.name / "summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        "\n".join(
            [
                "---",
                "type: summary",
                'schemaVersion: "5.0"',
                f'title: "{source_metadata["title"]}"',
                f'url: {source_metadata["url"]}',
                "promptId: 00000000-0000-4000-8000-000000000010",
                'promptVersion: "1.0"',
                "reviewStatus: accepted",
                "updated: 2026-08-06T12:00:00+09:00",
                "noteId: 00000000-0000-4000-8000-000000000020",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config, manifest, summary


def test_inventory_lists_latest_capture_and_corresponding_notes(tmp_path: Path) -> None:
    config, first_manifest, summary = _create_inventory(tmp_path)
    latest_manifest = import_raw(
        FIXTURES / "metadata.info.json",
        FIXTURES / "captions.ja.json3",
        config.raw_root,
        refresh=True,
    )

    result = build_inventory(config.raw_root, config.source_root, config.summary_root)

    assert result["schema_version"] == "1.0"
    assert result["count"] == 1
    item = result["items"][0]
    assert item["video_id"] == "TESTVID0001"
    assert item["capture"]["capture_count"] == 2
    assert item["capture"]["manifest_path"] == str(latest_manifest)
    assert item["capture"]["manifest_path"] != str(first_manifest)
    assert item["capture"]["captions_available"] is True
    assert len(item["source_notes"]) == 1
    assert item["source_notes"][0]["schema_version"] == "1.0"
    assert item["summary_notes"] == [
        {
            "path": str(summary),
            "title": "Synthetic pipeline test video",
            "schema_version": "5.0",
            "note_id": "00000000-0000-4000-8000-000000000020",
            "updated": "2026-08-06T12:00:00+09:00",
            "prompt_id": "00000000-0000-4000-8000-000000000010",
            "prompt_version": "1.0",
            "review_status": "accepted",
        }
    ]
    assert result["warnings"] == []


def test_inventory_reports_unreadable_artifacts_without_hiding_valid_items(
    tmp_path: Path,
) -> None:
    config, _, _ = _create_inventory(tmp_path)
    broken_manifest = config.raw_root / "broken" / "capture" / "manifest.json"
    broken_manifest.parent.mkdir(parents=True)
    broken_manifest.write_text("not json", encoding="utf-8")
    broken_note = config.source_root / "broken.md"
    broken_note.write_text("not frontmatter", encoding="utf-8")

    result = build_inventory(config.raw_root, config.source_root, config.summary_root)

    assert result["count"] == 1
    assert {warning["path"] for warning in result["warnings"]} == {
        str(broken_manifest),
        str(broken_note),
    }


def test_list_command_prints_json_inventory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config, _, _ = _create_inventory(tmp_path)
    monkeypatch.setattr(
        "youtube_note_pipeline.cli._resolved",
        lambda args: SimpleNamespace(config=config, sources=[]),
    )

    assert main(["list", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["items"][0]["video_id"] == "TESTVID0001"
