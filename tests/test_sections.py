import re
from pathlib import Path

from youtube_note_pipeline.contracts import summary_contract
from youtube_note_pipeline.migration import patch_metadata
from youtube_note_pipeline.notes import split_note, summary_section
from youtube_note_pipeline.sections import CONCLUSION_FIRST_HEADINGS, LEGACY_HEADINGS


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
    before = "\n\n".join(heading + "\n\nContent." for heading in LEGACY_HEADINGS)
    after = "\n\n".join(heading + "\n\nContent." for heading in CONCLUSION_FIRST_HEADINGS)
    assert summary_contract(metadata, before)[0] == list(LEGACY_HEADINGS)
    headings, _, conclusion, errors = summary_contract(metadata, after)
    assert headings == list(CONCLUSION_FIRST_HEADINGS)
    assert conclusion == "## 2. Conclusion"
    assert errors == []
    metadata["templateSha256"] = "0" * 64
    assert summary_contract(metadata, after)[3] == [
        "unknown or altered historical template resource"
    ]


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


def test_section_extraction_ignores_fenced_headings_and_stops_before_appendix():
    body = (
        "## 2. Conclusion\n\nTakeaway.\n\n"
        "```markdown\n## 3. Key points\nExample, not a section.\n```\n\n"
        "## 3. Key points\n\n- Point.\n\n## User notes\n\nKeep separate.\n"
    )
    assert summary_section(body, "## 2. Conclusion") == (
        "Takeaway.\n\n```markdown\n## 3. Key points\nExample, not a section.\n```"
    )
    assert summary_section(body, "## 3. Key points") == "- Point."
