import pytest

from youtube_note_pipeline.summary_resources import load_summary_profile


def test_packaged_default_summary_profile_is_versioned_and_bundled() -> None:
    profile = load_summary_profile()

    assert profile.name == "default"
    assert profile.source.endswith("summary_profiles/default")
    assert len(profile.sha256) == 64
    assert profile.prompt.source.endswith("summary_profiles/default/prompt.md")
    assert profile.output_schema.resource_id == "8135b54f-cc2e-484d-8616-f07e1ee376da"
    assert profile.output_schema.version == "1.0"
    assert profile.output_schema.source.endswith(
        "summary_profiles/default/output.schema.json"
    )
    assert set(profile.output_schema.schema["required"]) == set(
        profile.output_schema.schema["properties"]
    )
    assert profile.template.resource_id == "682b27ed-e542-4795-b295-107dbebe82f4"
    assert profile.template.version == "1.0"
    assert profile.template.note_schema_version == "5.0"
    assert profile.template.source.endswith("summary_profiles/default/template.md")
    assert all(
        heading in profile.template.body
        for heading in profile.template.required_headings
    )


@pytest.mark.parametrize("name", ["Default", "../default", "default/profile", ""])
def test_summary_profile_name_must_be_application_owned_slug(name: str) -> None:
    with pytest.raises(RuntimeError, match="invalid application-owned summary profile name"):
        load_summary_profile(name)
