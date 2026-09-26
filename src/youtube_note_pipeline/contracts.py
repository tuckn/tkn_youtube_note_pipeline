"""Frozen note contracts; historical validity does not depend on installed profiles.

Registry records are append-only. LF and CRLF hashes describe the same released
resource on different checkouts. Unknown resource revisions are never inferred.
Schema 1.1 is the explicit migration of 1.0 to type summary without inventing
missing prompt provenance or requiring obsolete reverse source descriptions.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from youtube_note_pipeline.sections import LEGACY_HEADINGS, historical_layout
from youtube_note_pipeline.summary_resources import SummaryProfile

NOTE_VERSIONS = ("1.0", "1.1", "2.0", "3.0", "4.0", "5.0")


def summary_contract(
    metadata: dict[str, Any], body: str | None = None,
) -> tuple[list[str], str, str, list[str]]:
    """Resolve recorded template and output schema to maintained validation rules."""
    if str(metadata.get("schemaVersion")) != "5.0":
        headings = historical_layout(list(LEGACY_HEADINGS), body)
        conclusion = next(heading for heading in headings if heading.endswith(". Conclusion"))
        return headings, headings[0], conclusion, []
    registry = json.loads(
        files("youtube_note_pipeline")
        .joinpath("resources/summary_contracts.json")
        .read_text(encoding="utf-8")
    )
    errors = []
    template = None
    for section, prefix in (("templates", "template"), ("output_schemas", "outputSchema")):
        matches = [
            entry
            for entry in registry[section]
            if entry["id"] == metadata.get(prefix + "Id")
            and entry["version"] == metadata.get(prefix + "Version")
            and metadata.get(prefix + "Sha256") in entry["hashes"]
        ]
        if not matches:
            errors.append(f"unknown or altered historical {prefix} resource")
        elif section == "templates":
            template = matches[0]
            if template["schema_version"] != str(metadata.get("schemaVersion")):
                errors.append("template contract does not match schemaVersion")
    if template is None:
        return list(LEGACY_HEADINGS), LEGACY_HEADINGS[0], LEGACY_HEADINGS[-1], errors
    headings = historical_layout(template["headings"], body)
    conclusion = next(heading for heading in headings if heading.endswith(". Conclusion"))
    return headings, template["summary_heading"], conclusion, errors


def summary_currency(metadata: dict[str, Any], profile: SummaryProfile) -> dict[str, Any]:
    """Currency is relative to the selected profile, independent of note validity."""
    expected = {
        "schemaVersion": profile.template.note_schema_version,
        "promptId": profile.prompt.prompt_id,
        "promptVersion": profile.prompt.version,
        "promptSha256": profile.prompt.sha256,
        "outputSchemaId": profile.output_schema.resource_id,
        "outputSchemaVersion": profile.output_schema.version,
        "outputSchemaSha256": profile.output_schema.sha256,
        "templateId": profile.template.resource_id,
        "templateVersion": profile.template.version,
        "templateSha256": profile.template.sha256,
    }
    differences = [key for key, value in expected.items() if str(metadata.get(key)) != value]
    return {"is_current": not differences, "profile": profile.name, "differences": differences}
