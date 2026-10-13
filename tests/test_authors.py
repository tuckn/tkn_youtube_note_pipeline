import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_maintenance import setup_notes as setup_notes

from youtube_note_pipeline import cli
from youtube_note_pipeline.migration import apply_migration, patch_metadata, plan_migration
from youtube_note_pipeline.models import VideoSource
from youtube_note_pipeline.notes import render_summary, split_note
from youtube_note_pipeline.summary_resources import load_summary_profile
from youtube_note_pipeline.validation import validate_summary


def without_author(path):
    payload = path.read_bytes()
    payload = re.sub(rb"(?m)^author:[^\r\n]*\r?\n", b"", payload)
    path.write_bytes(payload)
    return payload


@pytest.mark.parametrize("profile_name", ["default-ja", "default-en"])
@pytest.mark.parametrize("author", ['Channel: "日本"', ["[[Channel]]", "Second"], None])
def test_summary_renders_source_author_without_model_inference(tmp_path, profile_name, author):
    document = json.loads(
        (Path(__file__).parent / "fixtures/summary_document.golden.json").read_text("utf-8")
    )
    video = VideoSource(
        video_id="TESTVID0001",
        canonical_url="https://www.youtube.com/watch?v=TESTVID0001",
        title="Test",
        author=author,
        published="2026-01-01",
    )
    text = render_summary(
        video,
        tmp_path / "source.md",
        document,
        datetime.now(UTC),
        "Test",
        load_summary_profile(profile_name),
    )
    metadata, _ = split_note(text)
    assert metadata["author"] == author
    assert text.index("url:") < text.index("author:") < text.index("cliptool:")


@pytest.mark.parametrize("legacy", [False, True])
def test_backfill_preserves_reviewed_note_bytes_and_is_idempotent(setup_notes, legacy):
    config, _, source, summary, _ = setup_notes
    original = without_author(summary)
    original = patch_metadata(original, {"reviewStatus": "accepted"})
    if legacy:
        original = original.replace(b'schemaVersion: "5.0"\n', b"")
    original = b"\xef\xbb\xbf" + original.replace(b"\n", b"\r\n")
    summary.write_bytes(original)
    sources_before = source.read_bytes()
    before_tree = {p: p.read_bytes() for p in config.source_root.parent.rglob("*") if p.is_file()}
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    assert plan["counts"] == {"planned": 1}
    assert plan["items"][0]["changes"] == {"author": "Example Channel"}
    assert before_tree == {
        p: p.read_bytes() for p in config.source_root.parent.rglob("*") if p.is_file()
    }
    backups = config.reports_root.parent / "backups"
    result = apply_migration(plan, config.reports_root, backup_root=backups)
    assert result["updated"] == 1
    backup = Path(result["files"][0]["backup"])
    assert backup.is_relative_to(backups)
    assert backup.read_bytes() == original
    after = summary.read_bytes()
    assert after.replace(b'author: "Example Channel"\r\n', b"") == original
    assert source.read_bytes() == sources_before
    assert plan_migration(config.source_root, config.summary_root, authors_only=True)["counts"] == {
        "unchanged": 1
    }


@pytest.mark.parametrize("author", [None, "", [], ["[[Channel]]", "Second"]])
def test_empty_summary_author_can_be_filled_without_changing_lists(setup_notes, author):
    config, _, source, summary, _ = setup_notes
    source_author = ["[[Channel]]", "Second"]
    source.write_bytes(patch_metadata(source.read_bytes(), {"author": source_author}))
    summary.write_bytes(patch_metadata(summary.read_bytes(), {"author": author}))
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    result = apply_migration(plan, config.reports_root)
    assert result["updated"] == (0 if author == source_author else 1)
    assert split_note(summary.read_text("utf-8"))[0]["author"] == source_author
    assert validate_summary(summary, config.source_root) == []


@pytest.mark.parametrize("fault", ["conflict", "missing", "invalid", "duplicate", "identity"])
def test_backfill_refuses_ambiguous_or_conflicting_author(setup_notes, fault):
    config, _, source, summary, _ = setup_notes
    without_author(summary)
    if fault == "conflict":
        summary.write_bytes(patch_metadata(summary.read_bytes(), {"author": "User edit"}))
    elif fault in ("missing", "invalid"):
        value = None if fault == "missing" else {"not": "an author"}
        source.write_bytes(patch_metadata(source.read_bytes(), {"author": value}))
    elif fault == "duplicate":
        source.with_name("duplicate.md").write_bytes(source.read_bytes())
    else:
        summary.write_bytes(
            patch_metadata(
                summary.read_bytes(),
                {
                    "sourceNoteId": "00000000-0000-4000-8000-000000000001",
                },
            )
        )
    before = summary.read_bytes()
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    assert plan["counts"] == {"blocked": 1}
    assert apply_migration(plan, config.reports_root)["updated"] == 0
    assert before == summary.read_bytes()
    assert not config.reports_root.exists()


@pytest.mark.parametrize("fault", ["source", "summary", "tamper"])
def test_author_plan_refuses_changes_after_preview(setup_notes, fault):
    config, _, source, summary, _ = setup_notes
    without_author(summary)
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    if fault == "tamper":
        plan["items"][0]["changes"]["author"] = "Tampered"
    else:
        path = source if fault == "source" else summary
        path.write_bytes(path.read_bytes() + b"\nUser edit\n")
    before = summary.read_bytes()
    with pytest.raises(ValueError, match="stale or modified"):
        apply_migration(plan, config.reports_root)
    assert summary.read_bytes() == before
    assert not config.reports_root.exists()


def test_author_backfill_does_not_repair_other_metadata(setup_notes):
    config, _, source, summary, _ = setup_notes
    original = without_author(summary)
    original = patch_metadata(original, {"schemaVersion": "1.0"})
    summary.write_bytes(original)
    source.rename(source.with_name("moved.md"))
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    assert plan["items"][0]["changes"] == {"author": "Example Channel"}
    apply_migration(plan, config.reports_root)
    assert summary.read_bytes().replace(b'author: "Example Channel"\n', b"") == original


def test_cli_applies_author_plan_and_rejects_wrong_scope(setup_notes, monkeypatch, capsys):
    config, _, _, summary, _ = setup_notes
    without_author(summary)
    monkeypatch.setattr(cli, "_resolved", lambda args: Mock(config=config, sources=[]))
    assert cli.main(["migrate-notes", "--authors-only", "--dry-run", "--quiet"]) == 0
    plan_file = config.summary_root.parent / "plan.json"
    plan_file.write_text(capsys.readouterr().out, encoding="utf-8")
    assert cli.main(["migrate-notes", "--apply-plan", str(plan_file), "--quiet"]) == 1
    capsys.readouterr()
    assert "author" not in split_note(summary.read_text("utf-8"))[0]
    backup_root = config.summary_root.parent / "originals"
    assert (
        cli.main(
            [
                "migrate-notes",
                "--authors-only",
                "--apply-plan",
                str(plan_file),
                "--backup-root",
                str(backup_root),
                "--quiet",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["updated"] == 1
    assert Path(result["files"][0]["backup"]).is_relative_to(backup_root)


def test_optional_author_remains_compatible_with_historical_notes(setup_notes):
    config, _, _, summary, provider = setup_notes
    without_author(summary)
    summary.write_bytes(
        patch_metadata(
            summary.read_bytes(),
            {
                "templateVersion": "1.3",
                "templateSha256": (
                    "812dcfb2bf18fc043353a101bdfb2de39d344b37ff4230c10b09c31dc5a2cafa"
                ),
            },
        )
    )
    assert validate_summary(summary, config.source_root) == []
    plan = plan_migration(config.source_root, config.summary_root, authors_only=True)
    apply_migration(plan, config.reports_root)
    assert validate_summary(summary, config.source_root) == []
    metadata, _ = split_note(summary.read_text("utf-8"))
    assert metadata["templateVersion"] == "1.3"
    assert metadata["templateSha256"] != provider.profile.template.sha256
    summary.write_bytes(patch_metadata(summary.read_bytes(), {"author": 123}))
    assert "author must be a string, a list of strings, or null" in validate_summary(summary)
