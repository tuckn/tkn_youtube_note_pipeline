---
type: summary-template
id: 682b27ed-e542-4795-b295-107dbebe82f4
version: "1.2"
noteSchemaVersion: "5.0"
requiredHeadings:
  - "## 1. 要約"
  - "## 2. 結論"
  - "## 3. 要点"
  - "## 4. 構造（抽象から具体へ）"
  - "## 5. 専門用語"
summaryHeading: "## 1. 要約"
conclusionHeading: "## 2. 結論"
---

---
type: summary
schemaVersion: {{ template.note_schema_version | yaml_quote }}
title: {{ video.title | yaml_quote }}
description: {{ document.conclusion | compact_description | yaml_quote }}
cover: {{ cover }}
url: {{ video.canonical_url }}
cliptool: Codex
source: {{ source_uri | yaml_quote }}
generator: {{ generator | yaml_quote }}
promptId: {{ prompt.prompt_id }}
promptVersion: {{ prompt.version | yaml_quote }}
promptSha256: {{ prompt.sha256 | yaml_quote }}
outputSchemaId: {{ output_schema.resource_id }}
outputSchemaVersion: {{ output_schema.version | yaml_quote }}
outputSchemaSha256: {{ output_schema.sha256 | yaml_quote }}
templateId: {{ template.resource_id }}
templateVersion: {{ template.version | yaml_quote }}
templateSha256: {{ template.sha256 | yaml_quote }}
reviewStatus: unreviewed
date: {{ created }}
updated: {{ updated }}
noteId: {{ note_id }}
---

# {{ video.title }}

![]({{ video.canonical_url }})

## 1. 要約

{{ document.summary }}

## 2. 結論

{{ document.conclusion }}

## 3. 要点

{% for point in document.key_points %}
{% if point.timestamp_seconds is none %}
- {{ point.text }}
{% else %}
- [{{ point.timestamp_seconds | timestamp }}]({{ video.canonical_url }}&t={{ point.timestamp_seconds }}s) {{ point.text }}
{% endif %}
{% endfor %}

## 4. 構造（抽象から具体へ）

{% for section in document.structuring %}
### {{ section.heading }}

{% for item in section.details %}
- {{ item }}
{% endfor %}
{% for subsection in section.subsections %}
#### {{ subsection.heading }}

{% for item in subsection.details %}
- {{ item }}
{% endfor %}
{% endfor %}
{% endfor %}

## 5. 専門用語

{% for term in document.technical_terms %}
- {{ term }}
{% endfor %}
