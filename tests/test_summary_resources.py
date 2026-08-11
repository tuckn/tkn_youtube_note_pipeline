import json
from pathlib import Path

import pytest

from youtube_note_pipeline.summary_resources import (
    _validate_strict_objects,
    load_summary_profile,
    validate_summary_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_packaged_default_summary_profile_is_versioned_and_bundled() -> None:
    profile = load_summary_profile()

    assert profile.name == "default-ja"
    assert profile.source.endswith("summary_profiles/default-ja")
    assert len(profile.sha256) == 64
    assert profile.prompt.source.endswith("summary_profiles/default-ja/prompt.md")
    assert profile.output_schema.resource_id == "8135b54f-cc2e-484d-8616-f07e1ee376da"
    assert profile.output_schema.version == "1.1"
    assert profile.output_schema.source.endswith("summary_profiles/default-ja/output.schema.json")
    assert set(profile.output_schema.schema["required"]) == set(
        profile.output_schema.schema["properties"]
    )
    assert profile.template.resource_id == "682b27ed-e542-4795-b295-107dbebe82f4"
    assert profile.template.version == "1.0"
    assert profile.template.note_schema_version == "5.0"
    assert profile.template.source.endswith("summary_profiles/default-ja/template.md")
    assert all(heading in profile.template.body for heading in profile.template.required_headings)


def test_english_profile_has_distinct_language_prompt_and_shared_contract() -> None:
    japanese = load_summary_profile("default-ja")
    english = load_summary_profile("default-en")

    assert english.name == "default-en"
    assert english.prompt.prompt_id != japanese.prompt.prompt_id
    assert "source-faithful English summary" in english.prompt.instructions
    assert "source-faithful Japanese summary" in japanese.prompt.instructions
    assert "two or three short English paragraphs" in english.prompt.instructions
    assert "two or three short Japanese paragraphs" in japanese.prompt.instructions
    assert "transferable claims" in english.prompt.instructions
    assert "transferable claims" in japanese.prompt.instructions
    assert english.output_schema.sha256 == japanese.output_schema.sha256
    assert english.template.sha256 == japanese.template.sha256
    assert english.sha256 != japanese.sha256


def test_provider_golden_document_matches_built_in_output_contracts() -> None:
    document = json.loads((FIXTURES / "summary_document.golden.json").read_text(encoding="utf-8"))

    for profile_name in ("default-ja", "default-en"):
        profile = load_summary_profile(profile_name)
        assert validate_summary_document(document, profile.output_schema) == document


def test_output_schema_rejects_implicit_objects_in_nested_compositions() -> None:
    with pytest.raises(ValueError, match=r"schema.anyOf\[0\] object must set type to object"):
        _validate_strict_objects(
            {"anyOf": [{"properties": {"value": {"type": "string"}}}]}
        )


def test_structuring_section_requires_details_or_subsections() -> None:
    document = json.loads((FIXTURES / "summary_document.golden.json").read_text(encoding="utf-8"))
    document["structuring"] = [{"heading": "空の節", "details": [], "subsections": []}]

    with pytest.raises(ValueError, match="must contain details or subsections"):
        validate_summary_document(document, load_summary_profile().output_schema)


@pytest.mark.parametrize("name", ["Default", "../default", "default/profile", ""])
def test_summary_profile_name_must_be_application_owned_slug(name: str) -> None:
    with pytest.raises(RuntimeError, match="invalid application-owned summary profile name"):
        load_summary_profile(name)
