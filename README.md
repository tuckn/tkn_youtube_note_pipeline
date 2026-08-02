# tkn_youtube_note_pipeline

[日本語](README_ja.md)

`tkn_youtube_note_pipeline` is a CLI that summarizes YouTube videos in Japanese and saves the result as Markdown notes.

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

An editable installation is recommended for normal use. Replace `C:\path\to\tkn_youtube_note_pipeline` with the actual path to this repository.

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

The `-e` (`--editable`) option makes the installed `youtube-notes` command reference the source code in the repository directly. Source-code updates, such as those obtained with `git pull`, therefore take effect without reinstallation. The second command displays the active configuration and confirms that `youtube-notes` can be run after installation.

To switch to a non-editable installation that does not automatically reflect changes in the repository, run:

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --force
```

A non-editable installation uses the code as it existed at installation time and does not automatically track subsequent repository changes. After updating the repository, for example with `git pull`, run the same command again to make the updated code available to the installed `youtube-notes` command.

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
| `summary_root` | Japanese summary Markdown notes |
| `reports_root` | JSON run reports |

On Windows, if `codex` resolves to a different executable in an automated process than in an interactive PowerShell session, set `codex_executable` to the absolute path of the working `codex.exe` in a user-global or explicitly passed configuration file.

When `model` is set, that model is used for Codex execution. With `model: null`, Codex selects the model.

## Usage

### Summarize a video

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

This retrieves the captions and creates a source note containing the transcript and a Japanese summary note. One invocation accepts one video; playlist and channel URLs are not supported.

Use `--force` when you intentionally want to regenerate and replace the source and summary notes at the same output locations. `--overwrite` has the same meaning.

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

Because `--force` also replaces reviewed edits, use it only when regeneration is intended. Add `--refresh --force` to retrieve fresh metadata and captions as well.

### Other commands

| Command | Purpose |
| --- | --- |
| `youtube-notes acquire <video-url>` | Retrieve metadata and captions only |
| `youtube-notes import-raw --metadata <file> --captions <file>` | Import metadata and captions acquired elsewhere |
| `youtube-notes build-source <manifest>` | Create a transcript Markdown note from captured captions |
| `youtube-notes build-summary <source-note>` | Create a summary Markdown note from an existing source note |
| `youtube-notes validate <artifact>` | Validate a generated artifact |
| `youtube-notes config show` | Show effective settings and the summary profile |

Run `youtube-notes <command> --help` to see the options for a command.

### Progress logs

Progress is written to standard error and the final JSON result is written to standard output.

- Default: show normal progress
- `-q` / `--quiet`: suppress progress and show errors only
- `-v` / `--verbose`: include detailed diagnostics

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

Summary run reports record the prompt ID, document version, application envelope version, prompt source, and prompt SHA-256. Provider-only files use the platform temporary directory, and artifacts are staged next to their destinations for atomic replacement.

`ingest` and `build-summary` use generative AI. `acquire`, `import-raw`, `build-source`, `validate`, and `config show` are deterministic. Progress uses Python's standard `logging`; interactive output is colored by level and redirected or piped output remains uncolored.

### Application-owned summary profiles

The prompt, output schema, and Markdown template required for summary generation are bundled as one mutually dependent, developer-managed profile. Users cannot select or override the profile or any individual resource through the CLI or configuration. The application currently uses only `default`; a developer can add another summary pattern later as a sibling profile directory.

```text
src/youtube_note_pipeline/summary_profiles/
└── default/
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
