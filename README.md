# tkn_youtube_note_pipeline

[日本語](README_ja.md)

`tkn_youtube_note_pipeline` is a CLI that summarizes YouTube videos in Japanese or English and saves the result as Markdown notes. Japanese is the default.

For normal use, pass a video URL to one command:

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- an authenticated `codex` on `PATH` for summary generation

The Python `yt-dlp` package is installed automatically as a dependency, so the separate `yt-dlp` command is not required. The CLI does not download the video itself.

## Install

Install the repository with the following command. Replace `C:\path\to\tkn_youtube_note_pipeline` with the actual path to this repository.

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install .
tkn-youtube-note --help
```

The last command confirms that `tkn-youtube-note` can be run after installation. This installation uses the code as it existed when the command was run and does not automatically track later repository changes.

Reinstall after every repository update, such as after `git pull`, to make the updated code and dependencies available to the installed command:

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install . --reinstall
tkn-youtube-note --help
```

Use `--force` only when uv must forcibly recreate the tool installation or replace an existing entry point, such as when an executable conflict or a damaged tool environment prevents the normal `--reinstall` command from succeeding. Use `--reinstall`, not `--force`, for ordinary repository updates:

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install . --force
tkn-youtube-note --help
```

### Editable installation for development

Use an editable installation during development when source-code changes must be reflected in the CLI immediately:

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install -e . --reinstall
```

The `-e` (`--editable`) option makes the installed command reference the repository source code directly, so source-code edits take effect without reinstallation. If an update changes dependencies in `pyproject.toml`, package metadata, or entry points, or if the repository folder is moved or renamed, run the same editable installation command again to update the tool environment and repository reference.

To repair an editable installation while preserving editable mode, use:

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install -e . --force
```

## Configuration

Initialize the user-global configuration and inspect the effective settings:

```console
tkn-youtube-note config init
tkn-youtube-note config show
```

`config init` creates the packaged example at `~/.tkn/youtube_note_pipeline/config.yaml` and prints its status and path as JSON. It returns `unchanged` when the same file already exists and refuses to overwrite an edited configuration. Use `./.tkn/config.yaml` for repository-local overrides, or pass any configuration file with `--config`.

Configuration is merged in this order, with later values overriding earlier ones:

1. built-in defaults;
2. `~/.tkn/youtube_note_pipeline/config.yaml`;
3. `./.tkn/config.yaml`;
4. a file passed with `--config`;
5. individual CLI options.

The initialized configuration contains:

```yaml
raw_root: ~/.tkn/youtube_note_pipeline/data/raw
source_root: ~/.tkn/youtube_note_pipeline/data/source
summary_root: ~/.tkn/youtube_note_pipeline/data/summary
reports_root: ~/.tkn/youtube_note_pipeline/state/reports
provider: codex
model: null
summary_profile: default-ja
fallback_languages: []
provider_timeout_seconds: 600
codex_executable: codex
```

Ordinary relative output paths are resolved from the current working directory. Do not commit private machine paths or credentials to a public repository.

### Output locations

| Setting | Stored content |
| --- | --- |
| `raw_root` | Retrieved raw metadata, caption data, and manifests |
| `source_root` | Human-readable transcript Markdown source notes |
| `summary_root` | Summary Markdown notes |
| `reports_root` | JSON run reports |

The default `~/.tkn/youtube_note_pipeline/state/` directory holds operational pipeline state separately from raw captures and Markdown notes under `data/`. Each normal `ingest`, `acquire`, `import-raw`, `build-source`, and `build-summary` run writes a JSON run report under `reports/` containing its status, error, and the output path and details for each stage. A provider failure stores the complete subprocess diagnostics separately as a `*.provider.log` file. Note migrations save their plans, exact backups, and results under `reports/migrations/`. Dry runs do not create reports or backups.

These reports are not inputs to later pipeline runs. Deleting them removes the execution history and detailed failure diagnostics but does not affect raw captures, source notes, or summary notes; `reports/` is created again the next time a command writes a report. Changing `reports_root` moves both reports and diagnostic logs to that directory.

On Windows, if `codex` resolves to a different executable in an automated process than in an interactive PowerShell session, set `codex_executable` to the absolute path of the working `codex.exe` in a user-global or explicitly passed configuration file.

When `model` is set, that model is used for Codex execution. With `model: null`, Codex selects the model.

`summary_profile` selects the summary language: `default-ja` for Japanese or `default-en` for English. Set it in configuration for normal use, or pass `--summary-profile default-en` to override it for one command.

## Usage

### Summarize a video

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

This retrieves raw caption data and video metadata, renders a human-readable transcript Markdown source note, and creates a summary Markdown note in the selected profile's language. One invocation accepts one video; playlist and channel URLs are not supported.

#### `ingest` workflow

`ingest` orchestrates the same internal processing exposed by the following standalone commands. It does not start these CLI commands as separate subprocesses.

| Stage | Equivalent standalone command | Input | Output | Generative AI |
| --- | --- | --- | --- | --- |
| 1. Acquire | `acquire <video-url>` | YouTube video URL | Immutable raw metadata, caption data (`captions.<language>.json3`), and `manifest.json` | No |
| 2. Build source | `build-source <manifest>` | A manifest referencing acquired raw caption data | A validated, human-readable transcript Markdown source note | No |
| 3. Build summary | `build-summary <source-note>` | The transcript Markdown source note | A summary Markdown note generated with the selected profile | Yes |

```text
YouTube URL
  -> acquire
  -> raw metadata + raw caption data + manifest
  -> build-source
  -> transcript Markdown source note
  -> build-summary
  -> summary Markdown note
```

If a stage fails, `ingest` stops and does not create artifacts from later stages. Its run report records the stages that completed before the failure. A normal rerun reuses the existing raw capture when the newly retrieved content is identical and keeps valid current notes unchanged. `--refresh` stores a new raw capture in stage 1 even when its content is identical, `--force` replaces source and summary notes in stages 2 and 3, and `--refresh --force` performs both operations.

To create an English summary, change `summary_profile` in configuration or run:

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID" --summary-profile default-en
```

Use `--force` when you intentionally want to regenerate and replace the source and summary notes for the same video. Existing source notes are identified by the YouTube video ID in Frontmatter `url`, so a manually renamed or moved note is updated at its current path. `--overwrite` has the same meaning.

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

Because `--force` also replaces reviewed edits, use it only when regeneration is intended. Use `--refresh --force` to store a new raw metadata and caption capture and regenerate both notes.

### Other commands

| Command | Purpose |
| --- | --- |
| `tkn-youtube-note list` | List successful raw caption captures and their source and summary notes as JSON |
| `tkn-youtube-note acquire <video-url>` | Retrieve raw video metadata and caption data without creating Markdown notes |
| `tkn-youtube-note import-raw --metadata <file> --captions <file>` | Import raw metadata and caption data acquired elsewhere |
| `tkn-youtube-note build-source <manifest>` | Validate acquired raw caption data and render a human-readable transcript Markdown source note |
| `tkn-youtube-note build-summary <source-note>` | Create a summary Markdown note from a transcript Markdown source note |
| `tkn-youtube-note validate <artifact>` | Validate a generated artifact |
| `tkn-youtube-note status <note>` | Report historical validity and currency against the selected profile separately |
| `tkn-youtube-note migrate-notes` | Repair source references and migrate inconsistent legacy schema declarations, with backups |
| `tkn-youtube-note config show` | Show effective settings and the summary profile |

Run `tkn-youtube-note <command> --help` to see the options for a command.

`tkn-youtube-note list` returns one item per video, ordered by the most recent successful capture. Each item includes the latest manifest and raw caption-data paths, the number of successful captures, and every source or summary note with the same canonical video URL. Captures that do not yet have derived notes are included with empty note lists. Unreadable manifests or notes are reported in the top-level `warnings` array without hiding valid items.

### Preview, validation, and maintenance

`ingest`, `acquire`, `import-raw`, `build-source`, `build-summary`, `config init`, and `migrate-notes` accept `--dry-run`. They validate local inputs and print a JSON plan without writing application files, invoking AI (including provider preflight), or acquiring remote data. Acquisition previews cannot know caption availability, exact capture timestamps, or the final notes; `ingest` explicitly marks downstream stages as deferred. Local build previews use the same overwrite/regeneration decisions as execution. A `require_force` plan returns exit code 1. Normal commands write by default.

```console
tkn-youtube-note build-source <manifest> --dry-run
tkn-youtube-note build-summary <source-note> --dry-run
tkn-youtube-note status <summary-note> --summary-profile default-ja
tkn-youtube-note migrate-notes --dry-run > migration-plan.json
tkn-youtube-note migrate-notes --apply-plan migration-plan.json
```

`--force` and `--overwrite` are equivalent on `ingest`, `build-source`, and `build-summary`. Forced regeneration replaces reviewed edits. `provider_timeout_seconds` defaults to 600 and must be positive and finite; `--provider-timeout-seconds` overrides it. Timeouts become concise failures with partial provider diagnostics retained in the normal error report. Both built-in defaults and the packaged config example use `fallback_languages: []`; opt in to English fallback with `[en]`.

Stage statuses are `created`, `updated`, `unchanged`, `failed`, or `planned`. Reused raw captures now report `unchanged`. Manifest and run-report outcomes retain their versioned `success` / `failure` vocabulary. A migration plan additionally labels unresolvable items `blocked` and unrelated notes `skipped`; these are planning decisions, not successful writes.

`validate` checks the note's declared historical contract. `status` also reports `currency.is_current` and differing provenance fields relative to `--summary-profile`; an old but valid note returns `valid: true` even when it is not current. Historical template/output-schema revisions are retained in `resources/summary_contracts.json`, independent of the current generation profile. Unknown or altered resources are reported as validation errors instead of guessed. The supported note versions are 1.0, 1.1, 2.0, 3.0, 4.0, and 5.0.

`migrate-notes` searches only the configured source and summary roots. It resolves a unique source by video URL, checks source note IDs (and any existing `sourceNoteId`) and file existence, repairs `source`, and records the confirmed `sourceNoteId`. It also migrates notes declaring 1.0/2.0 but already using `type: summary`: 1.0 → 1.1 (no invented prompt provenance or obsolete reverse source-description requirement), and 2.0 → 3.0. Original 1.0/2.0 contracts remain strict. Target-contract validation must pass before a schema migration is planned. Notes without a declared schema may receive reference repairs but are not assigned an invented schema.

Migration changes only the listed Frontmatter fields. Body bytes, user fields, review status, `noteId`, `date`, `updated`, BOM, and line endings are preserved. Configured logical root paths are kept in links; resolved physical paths are checked for containment. Before writing, the migration recomputes the plan and verifies source and summary hashes. Ambiguous or conflicting items remain blocked; safe planned items can be applied. Each changed file has an exact backup and a mapping in `result.json`. If a run stops partway, completed changes remain recorded and recoverable from those backups. Keep migration backups until the result is accepted. A fresh migration after successful repair returns `unchanged`.

### Progress logs

Progress is written to standard error and the final JSON result is written to standard output.
The final JSON is indented across multiple lines for readability and remains directly parseable.

- `[INFO]`: show work starting or in progress
- `[SUCCESS]`: show when a capture, source note, or summary note is saved and validated
- `[ERROR]`: show when work cannot be completed
- `-q` / `--quiet`: suppress progress and show errors only
- `-v` / `--verbose`: include detailed diagnostics

Provider failures are reduced to a concise error on standard error. The run report keeps that
concise message and points to a separate `*.provider.log` file when the complete provider output
is available, so prompts and transcripts do not flood the terminal.

## Development

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

Normal tests use synthetic fixtures. Live YouTube and Codex smoke tests are
explicit operations and are not run in CI.

### Internal processing and artifacts

The raw caption data and transcript Markdown source note preserve the same complete spoken text, but they are different artifacts: the raw JSON3 data retains acquisition events for machine processing, while the source note adds metadata and readable timestamped paragraphs for people and downstream summarization. `ingest` runs the three stages documented in the usage section in order:

```text
YouTube URL
  -> raw metadata, raw caption data, and manifest
  -> transcript Markdown source note
  -> summary Markdown note generated through structured output
```

Each raw capture is stored below `<raw-root>/<video-id>/<captured-at>/` as `metadata.info.json`, `captions.<language>.json3`, and `manifest.json`. The manifest records schema version, hashes, caption track, tool version, canonical URL, and success or failure. A failed caption acquisition does not produce source or summary notes.

Source notes use Frontmatter `schemaVersion: "1.0"`. Existing source notes are found recursively below `source_root` by the YouTube video ID derived from Frontmatter `url`, not by their filename or directory. Equivalent canonical watch and `youtu.be` URLs therefore share one identity. Regeneration with `--overwrite` / `--force` keeps the existing `noteId` and `date`, updates `updated`, and writes back to the discovered path. More than one source note for the same video is reported as an error instead of selecting one implicitly.

New summary notes use `type: summary` and `schemaVersion: "5.0"` and record the IDs, versions, and SHA-256 hashes of the prompt, output schema, and template. Existing summary schemas 1.0, 2.0, 3.0, and 4.0 remain valid. Generation omits `nouns`, while validation permits a separate CLI to add it later.

Summary run reports record the selected profile name and SHA-256, prompt ID, document version, application envelope version, prompt source, and prompt SHA-256. Failed provider runs store complete subprocess diagnostics in a separate file referenced by `diagnostic_log`; the report's `error` field remains concise. Provider-only temporary files use the platform temporary directory, and artifacts are staged next to their destinations for atomic replacement.

`ingest` and `build-summary` use generative AI. `list`, `acquire`, `import-raw`, `build-source`, `validate`, and `config show` are deterministic. Progress uses Python's standard `logging`; interactive output is colored by level and redirected or piped output remains uncolored.

### Application-owned summary profiles

The prompt, output schema, and Markdown template required for summary generation are bundled as one mutually dependent, developer-managed profile. A built-in profile can be selected through configuration or the CLI, but individual resources and arbitrary custom prompts cannot be supplied. The application includes `default-ja` for Japanese and `default-en` for English; developers can add another summary pattern as a sibling profile directory.

```text
src/youtube_note_pipeline/summary_profiles/
├── default-ja/
│   ├── prompt.md
│   ├── output.schema.json
│   └── template.md
└── default-en/
    ├── prompt.md
    ├── output.schema.json
    └── template.md
```

- `prompt.md`: summary quality, source fidelity, and field semantics
- `output.schema.json`: structured JSON fields, types, and hierarchy returned by the provider
- `template.md`: final Markdown Frontmatter, headings, ordering, lists, and timestamp links

Python loads the profile as a unit, validates the profile name, each resource's ID, version, and SHA-256, the JSON Schema, and template placeholders, and computes a profile-level SHA-256 from the three member hashes. The safe input envelope, provider execution, provenance, atomic writes, and artifact validation remain application-managed.

Summary-profile provenance is managed as follows:

- Existing summaries are found by matching Frontmatter `url` and `promptId`, not by filename. Existing complete-UUID names and manual renames therefore remain valid and are reused without creating a duplicate.
- A different `version` with the same built-in prompt `id` regenerates the existing summary automatically only when recorded output-schema and template resources are unchanged. The summary keeps its `noteId` and `date`, receives a new `updated`, and returns to `reviewStatus: unreviewed`.
- The same prompt ID, version, and SHA-256 returns `unchanged` when the output-schema and template IDs, versions, and SHA-256 hashes also match.
- If prompt content changes without a version change, or if output-schema or template provenance changes, existing reviewed edits are not replaced automatically; explicit `--overwrite` / `--force` is required.

Output schema 1.2 removes the unused AI-generated `document.description` field; Japanese prompt 2.3 and English prompt 1.3 request only fields used by the renderer. Markdown `description` continues to use compacted Conclusion, so the note schema remains 5.0 and the visible note layout is unchanged. Existing output-schema 1.1 notes remain historically valid. The combined prompt/schema update requires `--force` to regenerate them. When adding generation resources, append their immutable validation contracts to the registry instead of overwriting historical rules.

The built-in instructions require source attribution, prohibit unsupported inference and external knowledge, organize the whole video by topic from abstract to concrete, omit nonessential advertising and calls to action, and define the expected content of each structured summary field.
