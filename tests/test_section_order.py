import json
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from youtube_note_pipeline import cli
from youtube_note_pipeline.contracts import summary_contract
from youtube_note_pipeline.migration import patch_metadata
from youtube_note_pipeline.notes import split_note, summary_section
from youtube_note_pipeline.section_order import (
    UnsupportedLayout,
    apply_section_order,
    plan_section_order,
    reorder_sections,
)
from youtube_note_pipeline.sections import CONCLUSION_FIRST_HEADINGS, LEGACY_HEADINGS


def note(newline="\n", bom=False, final_newline=True, appendix=""):
    text = (
        '---\ntype: summary\nreviewStatus: accepted\ndate: "2026-01-01"\n'
        'updated: "2026-01-02"\nnoteId: keep-id\ncustom: [user-edit]\n---\n\n'
        "# My title\n\n![](https://www.youtube.com/watch?v=TESTVID0001)\n\n"
        "## 1. Summary\n\nOverview.\n\n"
        "## 2. Structuring (from abstract to concrete)\n\n"
        "### Claim\n\n#### Evidence\n\n- Keep this detail.\n\n"
        "```markdown\n## 5. Conclusion\nExample heading inside code.\n```\n\n"
        "## 3. Key points\n\n- [0:03](https://example.org?t=3) Exact link.\n\n"
        "## 4. Technical terms\n\n- **Term**: Definition.\n\n"
        "## 5. Conclusion\n\nTakeaway.\n\nQualification."
    )
    if final_newline:
        text += "\n"
    if appendix:
        text += "\n\n" + appendix
    return (b"\xef\xbb\xbf" if bom else b"") + text.replace("\n", newline).encode()


@pytest.mark.parametrize(
    "newline,bom,final_newline",
    [
        ("\n", False, True),
        ("\r\n", True, True),
        ("\r\n", False, False),
    ],
)
@pytest.mark.parametrize("appendix", ["", "## My notes\n\nUser text.\n"])
def test_reorder_preserves_metadata_content_code_links_and_appendix(
    newline, bom, final_newline, appendix
):
    original = note(newline, bom, final_newline, appendix)
    updated = reorder_sections(original)
    before_meta, before_body = split_note(original.decode("utf-8-sig"))
    after_meta, after_body = split_note(updated.decode("utf-8-sig"))
    assert before_meta == after_meta
    delimiter = (newline + "---" + newline).encode()
    assert original.split(delimiter)[0] == updated.split(delimiter)[0]
    for old_index, new_index in ((0, 0), (1, 3), (2, 2), (3, 4), (4, 1)):
        assert summary_section(before_body, LEGACY_HEADINGS[old_index]) == summary_section(
            after_body, CONCLUSION_FIRST_HEADINGS[new_index]
        )
    assert updated.startswith(b"\xef\xbb\xbf") == bom
    if newline == "\r\n":
        assert b"\n" not in updated.replace(b"\r\n", b"")
    if appendix:
        assert updated.endswith(appendix.replace("\n", newline).encode())
    else:
        assert updated.endswith(newline.encode()) == final_newline
    assert reorder_sections(updated) == updated


@pytest.mark.parametrize("change", ["missing", "duplicate", "interleaved", "empty"])
def test_ambiguous_or_incomplete_layout_does_not_get_rewritten(change):
    text = note().decode()
    if change == "missing":
        text = text.replace("## 4. Technical terms", "## Other section")
    elif change == "duplicate":
        text += "\n## 5. Conclusion\nDuplicate.\n"
    elif change == "interleaved":
        text = text.replace("## 3. Key points", "## User heading\nUser text\n\n## 3. Key points")
    else:
        text = text.replace("\n\nOverview.\n\n", "\n\n")
    with pytest.raises(UnsupportedLayout if change == "missing" else ValueError):
        reorder_sections(text.encode())


def test_plan_apply_backup_skip_and_idempotence(tmp_path):
    root = tmp_path / "summaries"
    root.mkdir()
    target = root / "note.md"
    original = note("\r\n", True)
    target.write_bytes(original)
    other = root / "old-format.md"
    other.write_text("---\ntype: summary\n---\n## Overview\nUser note.", encoding="utf-8")
    reports = tmp_path / "reports"
    plan = plan_section_order(root)
    assert plan["counts"] == {"planned": 1, "skipped": 1}
    assert target.read_bytes() == original
    assert not reports.exists()
    result = apply_section_order(plan, reports)
    assert result["updated"] == 1
    assert Path(result["files"][0]["backup"]).read_bytes() == original
    assert target.read_bytes() == reorder_sections(original)
    assert plan_section_order(root)["counts"] == {"unchanged": 1, "skipped": 1}
    assert apply_section_order(plan_section_order(root), reports)["updated"] == 0


@pytest.mark.parametrize("change", ["edited", "tampered", "added"])
def test_stale_plan_is_rejected_before_backups_or_writes(tmp_path, change):
    root = tmp_path / "notes"
    root.mkdir()
    path = root / "note.md"
    path.write_bytes(note())
    plan = plan_section_order(root)
    if change == "edited":
        path.write_bytes(note() + b"\nUser edit")
    elif change == "tampered":
        plan["items"][0]["after_sha256"] = "0" * 64
    else:
        (root / "second.md").write_bytes(note())
    before = path.read_bytes()
    with pytest.raises(ValueError, match="stale or modified"):
        apply_section_order(plan, tmp_path / "reports")
    assert path.read_bytes() == before
    assert not (tmp_path / "reports").exists()


def test_legacy_contract_allows_only_the_named_reorder_and_keeps_provenance_checks():
    metadata = {
        "schemaVersion": "5.0",
        "templateId": "682b27ed-e542-4795-b295-107dbebe82f4",
        "templateVersion": "1.0",
        "templateSha256": "b9e0d134f374fb0a68cf5fe04f2cbe6f1379dd4dfb18f9438ba41fb497d9f757",
        "outputSchemaId": "8135b54f-cc2e-484d-8616-f07e1ee376da",
        "outputSchemaVersion": "1.2",
        "outputSchemaSha256": "938a2f3c8cfd70a696337f68cc1be6fa970b7cf7ffa2d25fd260f67220c2f724",
    }
    before = note().decode()
    after = reorder_sections(note()).decode()
    assert summary_contract(metadata, before)[0] == list(LEGACY_HEADINGS)
    headings, _, conclusion, errors = summary_contract(metadata, after)
    assert headings == list(CONCLUSION_FIRST_HEADINGS)
    assert conclusion == "## 2. Conclusion"
    assert errors == []
    metadata["templateSha256"] = "0" * 64
    assert summary_contract(metadata, after)[3] == [
        "unknown or altered historical template resource"
    ]


def test_cli_dry_run_and_apply_never_call_ai(tmp_path, monkeypatch, capsys):
    root = tmp_path / "notes"
    root.mkdir()
    path = root / "note.md"
    path.write_bytes(note())
    reports = tmp_path / "reports"
    monkeypatch.setattr(
        cli,
        "_resolved",
        lambda args: Mock(config=Mock(summary_root=root, reports_root=reports), sources=[]),
    )
    monkeypatch.setattr(cli, "provider_for_config", Mock(side_effect=AssertionError("AI called")))
    assert cli.main(["reorder-notes", "--dry-run", "--quiet"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {"planned": 1}
    assert path.read_bytes() == note()
    assert not reports.exists()
    assert cli.main(["reorder-notes", "--quiet"]) == 0
    assert json.loads(capsys.readouterr().out)["updated"] == 1


def test_current_template_renders_conclusion_before_points_and_description_stops_at_boundary(
    tmp_path,
):
    from test_pipeline import FakeProvider

    from youtube_note_pipeline.pipeline import build_source, build_summary
    from youtube_note_pipeline.raw import import_raw
    from youtube_note_pipeline.validation import validate_summary

    fixtures = Path(__file__).parent / "fixtures"
    manifest = import_raw(
        fixtures / "metadata.info.json", fixtures / "captions.ja.json3", tmp_path / "raw"
    )
    source = build_source(manifest, tmp_path / "sources").path
    summary = build_summary(source, tmp_path / "summaries", FakeProvider()).path
    metadata, body = split_note(summary.read_text(encoding="utf-8"))
    assert re.findall(r"^## .+$", body, re.M) == list(CONCLUSION_FIRST_HEADINGS)
    assert validate_summary(summary) == []
    assert summary_section(body, "## 2. Conclusion") == metadata["description"]
    original = summary.read_bytes()
    summary.write_bytes(patch_metadata(original, {"description": "incorrect"}))
    assert "summary description must match the compacted Conclusion" in validate_summary(summary)
