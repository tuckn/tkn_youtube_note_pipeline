import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_pipeline import FakeProvider

from youtube_note_pipeline import cli, pipeline
from youtube_note_pipeline.config import PipelineConfig
from youtube_note_pipeline.contracts import summary_currency
from youtube_note_pipeline.migration import apply_migration, patch_metadata, plan_migration
from youtube_note_pipeline.naming import path_to_file_uri
from youtube_note_pipeline.notes import split_note
from youtube_note_pipeline.raw import import_raw
from youtube_note_pipeline.summary_resources import load_summary_profile, validate_summary_document
from youtube_note_pipeline.validation import validate_summary

FIXTURES = Path(__file__).parent / "fixtures"
HISTORICAL_SCHEMA_HASH = "9672084b4bb213baa0e840573f105ac8870c1e6ed65f305dbd8df1d09fa325cd"


@pytest.fixture
def setup_notes(tmp_path):
    config = PipelineConfig(
        **{f"{k}_root": tmp_path / k for k in ("raw", "source", "summary", "reports")}
    )
    manifest = import_raw(
        FIXTURES / "metadata.info.json", FIXTURES / "captions.ja.json3", config.raw_root
    )
    source = pipeline.build_source(manifest, config.source_root).path
    provider = FakeProvider()
    summary = pipeline.build_summary(source, config.summary_root, provider).path
    return config, manifest, source, summary, provider


@pytest.mark.parametrize("version,target_version", [("1.0", "1.1"), ("2.0", "3.0")])
def test_migration_repairs_renamed_source_and_preserves_reviewed_bytes(
    setup_notes,
    version,
    target_version,
):
    config, _, source, summary, _ = setup_notes
    payload = summary.read_bytes()
    text = payload.decode("utf-8")
    removed = ("promptSha256:", "outputSchema", "template")
    if version == "1.0":
        removed += ("promptId:", "promptVersion:")
    text = "\n".join(line for line in text.splitlines() if not line.startswith(removed)) + "\n"
    text = text.replace('schemaVersion: "5.0"', f'schemaVersion: "{version}"')
    text = text.replace("reviewStatus: unreviewed", "reviewStatus: accepted")
    text = text.replace("date:", "tags: [user-edit]\ndate:", 1)
    # Preserve Windows line endings and user prose exactly.
    summary.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    original = summary.read_bytes()
    original_metadata, original_body = split_note(original.decode("utf-8"))
    moved = source.with_name("manually-renamed-source.md")
    source.rename(moved)
    before_tree = {p: p.read_bytes() for p in config.source_root.parent.rglob("*") if p.is_file()}
    plan = plan_migration(config.source_root, config.summary_root)
    assert plan["counts"] == {"planned": 1}
    assert plan["items"][0]["changes"]["schemaVersion"] == target_version
    assert before_tree == {
        p: p.read_bytes() for p in config.source_root.parent.rglob("*") if p.is_file()
    }
    result = apply_migration(plan, config.reports_root)
    assert result["updated"] == 1
    assert Path(result["files"][0]["backup"]).read_bytes() == original
    metadata, body = split_note(summary.read_text(encoding="utf-8"))
    assert body == original_body
    for key in ("noteId", "date", "updated", "reviewStatus", "tags", "description"):
        assert metadata[key] == original_metadata[key]
    assert metadata["source"] == path_to_file_uri(moved)
    assert metadata["sourceNoteId"] == split_note(moved.read_text(encoding="utf-8"))[0]["noteId"]
    assert b"\n" not in summary.read_bytes().replace(b"\r\n", b"")
    assert validate_summary(summary, config.source_root) == []
    assert plan_migration(config.source_root, config.summary_root)["counts"] == {"unchanged": 1}


@pytest.mark.parametrize(
    "change", ["summary", "source", "duplicate", "invalid_duplicate", "tamper"]
)
def test_migration_refuses_stale_or_modified_plan_before_writes(setup_notes, change):
    config, _, source, summary, _ = setup_notes
    summary.write_bytes(
        patch_metadata(
            summary.read_bytes(),
            {
                "source": path_to_file_uri(source.with_name("missing.md")),
            },
        )
    )
    plan = plan_migration(config.source_root, config.summary_root)
    if change in ("source", "summary"):
        path = source if change == "source" else summary
        path.write_bytes(path.read_bytes() + b"\nUser change\n")
    elif change in ("duplicate", "invalid_duplicate"):
        duplicate = source.read_bytes()
        if change == "invalid_duplicate":
            duplicate = patch_metadata(duplicate, {"noteId": "invalid"})
        source.with_name("duplicate.md").write_bytes(duplicate)
    else:
        plan["items"][0]["changes"]["source"] = "file:///wrong.md"
    before = summary.read_bytes()
    with pytest.raises(ValueError, match="stale or modified"):
        apply_migration(plan, config.reports_root)
    assert summary.read_bytes() == before
    assert not config.reports_root.exists()


def test_migration_rejects_identity_conflict(setup_notes):
    config, _, source, summary, _ = setup_notes
    summary.write_bytes(
        patch_metadata(
            summary.read_bytes(),
            {
                "source": path_to_file_uri(source.with_name("missing.md")),
                "sourceNoteId": "00000000-0000-4000-8000-000000000001",
            },
        )
    )
    plan = plan_migration(config.source_root, config.summary_root)
    assert plan["counts"] == {"blocked": 1}
    assert "conflicts" in plan["items"][0]["reason"]
    assert apply_migration(plan, config.reports_root)["updated"] == 0


@pytest.mark.parametrize("mutation", ["version", "items", "duplicate"])
def test_migration_rejects_malformed_plan(setup_notes, mutation):
    config, *_ = setup_notes
    plan = plan_migration(config.source_root, config.summary_root)
    if mutation == "version":
        plan["schema_version"] = "999"
    elif mutation == "items":
        plan["items"] = [None]
    else:
        plan["items"] *= 2
    with pytest.raises(ValueError, match="plan"):
        apply_migration(plan, config.reports_root)
    assert not config.reports_root.exists()


def test_historical_validity_is_independent_of_current_profile(setup_notes, monkeypatch):
    config, _, _, summary, provider = setup_notes
    historical = patch_metadata(
        summary.read_bytes(),
        {
            "outputSchemaVersion": "1.1",
            "outputSchemaSha256": HISTORICAL_SCHEMA_HASH,
        },
    )
    summary.write_bytes(historical)
    monkeypatch.setattr(
        "youtube_note_pipeline.summary_resources.load_summary_profile",
        lambda *a: (_ for _ in ()).throw(RuntimeError("profile removed")),
    )
    assert validate_summary(summary, config.source_root) == []
    metadata, _ = split_note(summary.read_text(encoding="utf-8"))
    assert summary_currency(metadata, provider.profile)["is_current"] is False
    summary.write_bytes(patch_metadata(historical, {"templateSha256": "0" * 64}))
    assert any("historical template" in error for error in validate_summary(summary))


def test_output_contract_change_requires_force_even_with_new_prompt(setup_notes):
    config, _, source, summary, provider = setup_notes
    summary.write_bytes(
        patch_metadata(
            summary.read_bytes(),
            {
                "outputSchemaVersion": "1.1",
                "promptVersion": "older",
                "outputSchemaSha256": HISTORICAL_SCHEMA_HASH,
                "reviewStatus": "accepted",
            },
        )
    )
    original = summary.read_bytes()
    provider.generate = Mock(side_effect=AssertionError("AI must not run"))
    preview = pipeline.build_summary(source, config.summary_root, provider, dry_run=True)
    assert preview.details["action"] == "require_force"
    with pytest.raises(FileExistsError, match="use --force"):
        pipeline.build_summary(source, config.summary_root, provider)
    assert original == summary.read_bytes()
    provider.generate.assert_not_called()


def test_all_mutation_previews_are_read_only(setup_notes, tmp_path, monkeypatch, capsys):
    config, manifest, source, summary, _ = setup_notes
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: config_path)
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("external process")))
    monkeypatch.setattr(pipeline, "acquire", Mock(side_effect=AssertionError("network")))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    commands = [
        ["ingest", "https://youtu.be/TESTVID0001", "--force"],
        ["acquire", "https://youtu.be/TESTVID0001"],
        [
            "import-raw",
            "--metadata",
            str(FIXTURES / "metadata.info.json"),
            "--captions",
            str(FIXTURES / "captions.ja.json3"),
        ],
        ["build-source", str(manifest), "--force"],
        ["build-summary", str(source), "--force"],
        ["migrate-notes"],
    ]
    for command in commands:
        assert cli.main([*command, "--config", str(config_path), "--dry-run", "--quiet"]) == 0
        json.loads(capsys.readouterr().out)
        assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert not config.reports_root.exists()
    target = tmp_path / "new-user" / "config.yaml"
    monkeypatch.setattr("youtube_note_pipeline.config.global_config_path", lambda: target)
    assert cli.main(["config", "init", "--dry-run", "--quiet"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert not target.parent.exists()


def test_import_stage_reports_unchanged_when_capture_reused(setup_notes):
    config, _, _, _, _ = setup_notes
    result = pipeline.run_import(
        FIXTURES / "metadata.info.json", FIXTURES / "captions.ja.json3", config
    )
    assert result.status == "unchanged"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_provider_timeout_rejects_invalid_values(setup_notes, timeout):
    config, *_ = setup_notes
    config.generation.selected.overrides["timeout_seconds"] = timeout
    with pytest.raises(RuntimeError, match="invalid_config"):
        pipeline.provider_for_config(config).plan()


def test_removed_description_is_rejected_by_both_output_contracts():
    document = json.loads((FIXTURES / "summary_document.golden.json").read_text(encoding="utf-8"))
    for name in ("default-ja", "default-en"):
        profile = load_summary_profile(name)
        assert "`description`:" not in profile.prompt.instructions
        assert "description" not in profile.output_schema.schema["properties"]
        with pytest.raises(ValueError, match="Additional properties"):
            validate_summary_document(document | {"description": "unused"}, profile.output_schema)


def test_status_reports_validity_and_currency_separately(setup_notes, monkeypatch, capsys):
    config, _, _, summary, provider = setup_notes
    monkeypatch.setattr(cli, "_resolved", lambda args: Mock(config=config, sources=[]))
    monkeypatch.setattr(
        cli,
        "load_summary_profile",
        lambda *args: replace(
            provider.profile,
            prompt=replace(provider.profile.prompt, version="future"),
        ),
    )
    assert cli.main(["status", str(summary), "--quiet"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is True
    assert result["currency"]["is_current"] is False
    assert result["currency"]["differences"] == ["promptVersion"]
