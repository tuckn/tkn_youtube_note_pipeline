---
type: summary-template
id: 682b27ed-e542-4795-b295-107dbebe82f4
version: "1.0"
noteSchemaVersion: "5.0"
requiredHeadings:
  - "## 1. Summary"
  - "## 2. Structuring (from abstract to concrete)"
  - "## 3. Key points"
  - "## 4. Technical terms"
  - "## 5. Conclusion"
summaryHeading: "## 1. Summary"
conclusionHeading: "## 5. Conclusion"
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

## 1. Summary

{{ document.summary }}

## 2. Structuring (from abstract to concrete)

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
## 3. Key points

{% for point in document.key_points %}
{% if point.timestamp_seconds is none %}
- {{ point.text }}
{% else %}
- [{{ point.timestamp_seconds | timestamp }}]({{ video.canonical_url }}&t={{ point.timestamp_seconds }}s) {{ point.text }}
{% endif %}
{% endfor %}
## 4. Technical terms

{% for term in document.technical_terms %}
- {{ term }}
{% endfor %}
## 5. Conclusion

{{ document.conclusion }}
