"""Load and validate application-owned summary profile bundles."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError, meta
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from youtube_note_pipeline.prompting import SummaryPrompt, parse_summary_prompt

DEFAULT_SUMMARY_PROFILE = "default"
SUMMARY_PROFILES_ROOT = "summary_profiles"
PROMPT_FILENAME = "prompt.md"
OUTPUT_SCHEMA_FILENAME = "output.schema.json"
SUMMARY_TEMPLATE_FILENAME = "template.md"
_TEMPLATE_CONTEXT = {
    "cover",
    "created",
    "document",
    "generator",
    "note_id",
    "output_schema",
    "prompt",
    "source_uri",
    "template",
    "updated",
    "video",
}
_TEMPLATE_FILTERS = {
    "compact_description",
    "timestamp",
    "yaml_quote",
}


@dataclass(frozen=True)
class OutputSchemaResource:
    resource_id: str
    version: str
    schema: dict[str, Any]
    source: str
    sha256: str


@dataclass(frozen=True)
class SummaryTemplateResource:
    resource_id: str
    version: str
    note_schema_version: str
    required_headings: tuple[str, ...]
    summary_heading: str
    conclusion_heading: str
    body: str
    source: str
    sha256: str


@dataclass(frozen=True)
class SummaryProfile:
    name: str
    source: str
    sha256: str
    prompt: SummaryPrompt
    output_schema: OutputSchemaResource
    template: SummaryTemplateResource


def _profile_resource_path(profile_name: str, filename: str) -> str:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile_name) is None:
        raise RuntimeError(f"invalid application-owned summary profile name: {profile_name}")
    return f"{SUMMARY_PROFILES_ROOT}/{profile_name}/{filename}"


def _resource_bytes(path: str) -> tuple[bytes, str]:
    resource = files("youtube_note_pipeline").joinpath(path)
    try:
        payload = resource.read_bytes()
    except (OSError, FileNotFoundError) as exc:
        raise RuntimeError(f"summary resource is unavailable: {path}: {exc}") from exc
    return payload, f"package:youtube_note_pipeline/{path}"


def _canonical_uuid(value: object, field: str, source: str) -> str:
    try:
        normalized = str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID: {source}") from exc
    if str(value) != normalized:
        raise ValueError(f"{field} must use canonical lowercase UUID form: {source}")
    return normalized


def _version(value: object, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty quoted string: {source}")
    return value.strip()


def _validate_strict_objects(node: object, location: str = "schema") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            properties = node.get("properties")
            required = node.get("required")
            if not isinstance(properties, dict):
                raise ValueError(f"{location} object must define properties")
            if node.get("additionalProperties") is not False:
                raise ValueError(f"{location} object must set additionalProperties to false")
            if not isinstance(required, list) or set(required) != set(properties):
                raise ValueError(f"{location} object must require every property")
        for key, value in node.items():
            _validate_strict_objects(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _validate_strict_objects(value, f"{location}[{index}]")


def load_summary_prompt(
    profile_name: str = DEFAULT_SUMMARY_PROFILE,
) -> SummaryPrompt:
    path = _profile_resource_path(profile_name, PROMPT_FILENAME)
    payload, source = _resource_bytes(path)
    return parse_summary_prompt(payload, source)


def load_output_schema(
    profile_name: str = DEFAULT_SUMMARY_PROFILE,
) -> OutputSchemaResource:
    path = _profile_resource_path(profile_name, OUTPUT_SCHEMA_FILENAME)
    payload, source = _resource_bytes(path)
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid output schema resource {source}: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"type", "id", "version", "schema"}:
        raise ValueError(f"output schema resource has invalid top-level fields: {source}")
    if document.get("type") != "output-schema":
        raise ValueError(f"output schema resource type must be 'output-schema': {source}")
    resource_id = _canonical_uuid(document.get("id"), "output schema id", source)
    version = _version(document.get("version"), "output schema version", source)
    schema = document.get("schema")
    if not isinstance(schema, dict):
        raise ValueError(f"output schema must be an object: {source}")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"invalid JSON Schema {source}: {exc.message}") from exc
    _validate_strict_objects(schema)
    return OutputSchemaResource(
        resource_id=resource_id,
        version=version,
        schema=dict(schema),
        source=source,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _split_frontmatter(payload: bytes, source: str) -> tuple[dict[str, Any], str]:
    try:
        text = payload.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise ValueError(f"summary template must be UTF-8: {source}") from exc
    if not text.startswith("---\n"):
        raise ValueError(f"summary template must start with YAML frontmatter: {source}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"summary template frontmatter closing delimiter is missing: {source}")
    try:
        metadata = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid summary template frontmatter {source}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"summary template frontmatter must be a mapping: {source}")
    return dict(metadata), text[end + 5 :].strip()


def _template_environment(filters: Mapping[str, Callable[..., object]]) -> Environment:
    environment = Environment(
        autoescape=False,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    environment.filters.update(filters)
    return environment


def load_summary_template(
    profile_name: str = DEFAULT_SUMMARY_PROFILE,
) -> SummaryTemplateResource:
    path = _profile_resource_path(profile_name, SUMMARY_TEMPLATE_FILENAME)
    payload, source = _resource_bytes(path)
    metadata_document, body = _split_frontmatter(payload, source)
    if metadata_document.get("type") != "summary-template":
        raise ValueError(f"summary template type must be 'summary-template': {source}")
    resource_id = _canonical_uuid(metadata_document.get("id"), "summary template id", source)
    version = _version(metadata_document.get("version"), "summary template version", source)
    note_schema_version = _version(
        metadata_document.get("noteSchemaVersion"), "note schema version", source
    )
    headings = metadata_document.get("requiredHeadings")
    if not isinstance(headings, list) or not headings or not all(
        isinstance(item, str) and item.strip() for item in headings
    ):
        raise ValueError(f"requiredHeadings must be a non-empty string list: {source}")
    required_headings = tuple(item.strip() for item in headings)
    summary_heading = str(metadata_document.get("summaryHeading") or "").strip()
    conclusion_heading = str(metadata_document.get("conclusionHeading") or "").strip()
    if summary_heading not in required_headings or conclusion_heading not in required_headings:
        raise ValueError(f"summary and conclusion headings must be required headings: {source}")
    if not body:
        raise ValueError(f"summary template body must not be empty: {source}")
    for heading in required_headings:
        if heading not in body:
            raise ValueError(
                f"summary template body is missing required heading {heading!r}: {source}"
            )
    environment = _template_environment({name: lambda value: value for name in _TEMPLATE_FILTERS})
    try:
        parsed = environment.parse(body)
    except TemplateError as exc:
        raise ValueError(f"invalid summary template {source}: {exc}") from exc
    undeclared = meta.find_undeclared_variables(parsed) - _TEMPLATE_CONTEXT
    if undeclared:
        names = ", ".join(sorted(undeclared))
        raise ValueError(f"summary template uses unsupported context variables: {names}")
    return SummaryTemplateResource(
        resource_id=resource_id,
        version=version,
        note_schema_version=note_schema_version,
        required_headings=required_headings,
        summary_heading=summary_heading,
        conclusion_heading=conclusion_heading,
        body=body,
        source=source,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def load_summary_profile(
    profile_name: str = DEFAULT_SUMMARY_PROFILE,
) -> SummaryProfile:
    prompt = load_summary_prompt(profile_name)
    output_schema = load_output_schema(profile_name)
    template = load_summary_template(profile_name)
    source = f"package:youtube_note_pipeline/{SUMMARY_PROFILES_ROOT}/{profile_name}"
    identity = json.dumps(
        {
            "name": profile_name,
            "promptSha256": prompt.sha256,
            "outputSchemaSha256": output_schema.sha256,
            "templateSha256": template.sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SummaryProfile(
        name=profile_name,
        source=source,
        sha256=hashlib.sha256(identity).hexdigest(),
        prompt=prompt,
        output_schema=output_schema,
        template=template,
    )


def validate_summary_document(
    document: object,
    output_schema: OutputSchemaResource,
) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(output_schema.schema).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"structured summary does not match output schema: {details}")
    if not isinstance(document, dict):
        raise ValueError("structured summary must be an object")
    return dict(document)


def render_summary_template(
    template: SummaryTemplateResource,
    context: Mapping[str, object],
    filters: Mapping[str, Callable[..., object]],
) -> str:
    environment = _template_environment(filters)
    try:
        rendered = environment.from_string(template.body).render(**context)
    except TemplateError as exc:
        raise ValueError(f"cannot render summary template {template.source}: {exc}") from exc
    return re.sub(r"\n{3,}", "\n\n", rendered).rstrip() + "\n"
