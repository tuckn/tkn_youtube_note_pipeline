# Provider golden evaluation

Provider implementations must return JSON accepted by
`SummaryDocument.model_validate_json()`. The fixture in this directory is the
minimal provider-neutral contract used before adding a new implementation.

An Ollama provider is intentionally not included in version 1. A future
implementation should submit the same JSON Schema, validate the response with
the same Pydantic model, and pass the existing renderer and provenance tests
without provider-specific Markdown logic.

