# tkn_youtube_note_pipeline

[日本語](README_ja.md)

`tkn_youtube_note_pipeline` is a CLI that summarizes YouTube videos in Japanese or English and saves the result as Markdown notes. Japanese is the default.

For normal use, pass a video URL to one command:

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- an authenticated `codex` on `PATH` for summary generation

The Python `yt-dlp` package is installed automatically as a dependency, so the separate `yt-dlp` command is not required. The CLI does not download the video itself.

## Install

Install the repository with the following command. Replace `C:\path\to\tkn_youtube_note_pipeline` with the actual path to this repository.

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

The second command displays the active configuration and confirms that `youtube-notes` can be run after installation. This installation uses the code as it existed when the command was run and does not automatically track later repository changes.

Reinstall after every repository update, such as after `git pull`, to make the updated code and dependencies available to the installed command:

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --reinstall
youtube-notes config show
```

Use `--force` only when uv must forcibly recreate the tool installation or replace an existing entry point, such as when an executable conflict or a damaged tool environment prevents the normal `--reinstall` command from succeeding. Use `--reinstall`, not `--force`, for ordinary repository updates:

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --force
youtube-notes config show
```

### Editable installation for development

Use an editable installation during development when source-code changes must be reflected in the CLI immediately:

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline" --reinstall
```

The `-e` (`--editable`) option makes the installed command reference the repository source code directly, so source-code edits take effect without reinstallation. If an update changes dependencies in `pyproject.toml`, package metadata, or entry points, or if the repository folder is moved or renamed, run the same editable installation command again to update the tool environment and repository reference.

To repair an editable installation while preserving editable mode, use:

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline" --force
```

## Configuration

Initialize the user-global configuration and inspect the effective settings:

```console
youtube-notes config init
youtube-notes config show
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
fallback_languages:
  - en
codex_executable: codex
```

Ordinary relative output paths are resolved from the current working directory. Do not commit private machine paths or credentials to a public repository.

### Output locations

| Setting | Stored content |
| --- | --- |
| `raw_root` | Retrieved metadata and captions |
| `source_root` | Markdown notes containing transcripts |
| `summary_root` | Summary Markdown notes |
| `reports_root` | JSON run reports |

The default `~/.tkn/youtube_note_pipeline/state/` directory holds operational pipeline state separately from raw captures and Markdown notes under `data/`. The current version uses only `reports/`. Each `ingest`, `acquire`, `import-raw`, `build-source`, and `build-summary` run writes a JSON run report containing its status, error, and the output path and details for each stage. A provider failure stores the complete subprocess diagnostics separately as a `*.provider.log` file in the same directory.

These reports are not inputs to later pipeline runs. Deleting them removes the execution history and detailed failure diagnostics but does not affect raw captures, source notes, or summary notes; `reports/` is created again the next time a command writes a report. Changing `reports_root` moves both reports and diagnostic logs to that directory.

On Windows, if `codex` resolves to a different executable in an automated process than in an interactive PowerShell session, set `codex_executable` to the absolute path of the working `codex.exe` in a user-global or explicitly passed configuration file.

When `model` is set, that model is used for Codex execution. With `model: null`, Codex selects the model.

`summary_profile` selects the summary language: `default-ja` for Japanese or `default-en` for English. Set it in configuration for normal use, or pass `--summary-profile default-en` to override it for one command.

## Usage

### Summarize a video

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

This retrieves the captions and creates a source note containing the transcript and a summary note in the selected profile's language. One invocation accepts one video; playlist and channel URLs are not supported.

To create an English summary, change `summary_profile` in configuration or run:

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --summary-profile default-en
```

Use `--force` when you intentionally want to regenerate and replace the source and summary notes at the same output locations. `--overwrite` has the same meaning.

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

Because `--force` also replaces reviewed edits, use it only when regeneration is intended. Add `--refresh --force` to retrieve fresh metadata and captions as well.

### Other commands

| Command | Purpose |
| --- | --- |
| `youtube-notes list` | List acquired transcripts and their source and summary notes as JSON |
| `youtube-notes acquire <video-url>` | Retrieve metadata and captions only |
| `youtube-notes import-raw --metadata <file> --captions <file>` | Import metadata and captions acquired elsewhere |
| `youtube-notes build-source <manifest>` | Create a transcript Markdown note from captured captions |
| `youtube-notes build-summary <source-note>` | Create a summary Markdown note from an existing source note |
| `youtube-notes validate <artifact>` | Validate a generated artifact |
| `youtube-notes config show` | Show effective settings and the summary profile |

Run `youtube-notes <command> --help` to see the options for a command.

`youtube-notes list` returns one item per video, ordered by the most recent successful capture. Each item includes the latest manifest and captions paths, the number of successful captures, and every source or summary note with the same canonical video URL. Captures that do not yet have derived notes are included with empty note lists. Unreadable manifests or notes are reported in the top-level `warnings` array without hiding valid items.

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

`ingest` runs these stages in order:

```text
YouTube URL
  -> raw metadata, captions, and manifest
  -> source Markdown containing the transcript
  -> summary Markdown generated through structured output
```

Each raw capture is stored below `<raw-root>/<video-id>/<captured-at>/` as `metadata.info.json`, `captions.<language>.json3`, and `manifest.json`. The manifest records schema version, hashes, caption track, tool version, canonical URL, and success or failure. A failed caption acquisition does not produce source or summary notes.

Source notes use Frontmatter `schemaVersion: "1.0"`. New summary notes use `type: summary` and `schemaVersion: "5.0"` and record the IDs, versions, and SHA-256 hashes of the prompt, output schema, and template. Existing summary schemas 1.0, 2.0, 3.0, and 4.0 remain valid. Generation omits `nouns`, while validation permits a separate CLI to add it later.

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
- A different `version` with the same built-in prompt `id` regenerates and updates the existing summary automatically. The summary keeps its `noteId` and `date`, receives a new `updated`, and returns to `reviewStatus: unreviewed`.
- The same prompt ID, version, and SHA-256 returns `unchanged` when the output-schema and template IDs, versions, and SHA-256 hashes also match.
- If prompt content changes without a version change, or if output-schema or template provenance changes, existing reviewed edits are not replaced automatically; explicit `--overwrite` / `--force` is required.

The built-in instructions require source attribution, prohibit unsupported inference and external knowledge, organize the whole video by topic from abstract to concrete, omit nonessential advertising and calls to action, and define the expected content of each structured summary field.
