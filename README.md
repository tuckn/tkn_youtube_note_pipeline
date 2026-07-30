# tkn_youtube_note_pipeline

[日本語](README_ja.md)

`tkn_youtube_note_pipeline` turns one YouTube video into three reproducible data
layers:

1. immutable raw metadata, captions, and a capture manifest;
2. a source Markdown note containing provenance and the complete transcript;
3. a source-faithful summary Markdown note generated through a structured-output
   provider.

Semantic classification and ontology promotion are intentionally outside this
pipeline.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- `codex` on `PATH` for summary generation

The Python `yt-dlp` package is installed as a project dependency and is called
through its embedded `YoutubeDL` API. The separate `yt-dlp` command does not
need to be installed or added to `PATH`.

The pipeline does not download video binaries and does not install or configure
Codex credentials.

## Install

For an editable installation, which reflects source-code changes without
reinstallation:

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

Replace the example path with the path to this repository on your computer.
Because the repository path is specified explicitly, the command can be run
from any working directory.

For a non-editable installation:

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --force
```

The non-editable installation does not track subsequent changes to the
repository. After updating the repository, for example with `git pull`, run the
same command again to install the updated version.

## Commands

Run every stage for one video:

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

This acquires immutable metadata and captions, builds the complete-transcript
source note, then generates the structured summary note. It stops before
creating derived notes when caption acquisition fails, and writes a JSON run
report whether the run succeeds or fails.

If different source or summary content already exists at the target paths and
you intentionally want to regenerate and replace both notes, use `--force`.
`--overwrite` is an alias with the same behavior.

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

Because `--force` replaces existing source and summary content, including
reviewed edits, use it only after confirming that regeneration is intended. Add
`--refresh` when you also want to create a fresh raw capture.

Capture only the raw inputs:

```console
youtube-notes acquire "https://www.youtube.com/watch?v=VIDEO_ID"
```

This fetches metadata and the preferred complete JSON3 caption track without
downloading the video. It writes the raw files and manifest but does not build a
source or summary note. An identical successful capture is reused unless
`--refresh` is passed.

Import raw inputs acquired outside this pipeline:

```console
youtube-notes import-raw --metadata metadata.info.json --captions captions.ja.json3
```

This validates the supplied metadata and JSON3 captions and stores them as an
immutable raw capture with a manifest. Use it when captions were acquired by an
external fallback. It does not build derived notes.

Build a source note from a successful raw manifest:

```console
youtube-notes build-source path/to/manifest.json
```

This creates the provenance-bearing Markdown source note with the complete
timestamped transcript and verifies it against the captured JSON3 captions.

Build a summary note from a valid source note:

```console
youtube-notes build-summary path/to/source-note.md
youtube-notes build-summary path/to/source-note.md --summary-prompt my-summary.md
```

This sends the source transcript to the configured structured-output provider
(Codex in version 1) and creates a source-faithful Japanese summary note. It
validates both notes and does not add semantic classification or ontology links.
Summary schema 2.0 does not copy one summary's description back to the shared
source note, because one source can now have summaries made with multiple
prompts.

Initialize an editable copy of the built-in summary instructions:

```console
youtube-notes prompt init
youtube-notes prompt init my-summary.md
```

This creates `summary.md`, or the supplied `.md` filename, below
`~/.tkn/youtube_note_pipeline/prompts/`. It prints the created path as JSON and
does not modify `config.yaml`. It refuses to overwrite an existing file and
gives every new prompt a unique UUID with initial version `"1.0"`. After editing
the file, set `summary_prompt: my-summary.md` in a configuration file or pass
`--summary-prompt my-summary.md` to a generating command.

Validate one pipeline artifact:

```console
youtube-notes validate path/to/artifact
```

This detects whether the path is a raw manifest, source note, or summary note,
then prints JSON containing the artifact kind, validity, and any errors. The
command exits with a non-zero status when validation fails.

Show the effective configuration:

```console
youtube-notes config show
```

This prints the merged non-secret settings and the configuration sources that
were actually loaded. For the summary prompt, it also validates the effective
Markdown and reports its built-in/custom mode, ID, document version, resolved
source, and SHA-256. It does not acquire or generate any content.

Version 1 accepts one video URL per invocation and rejects playlist and channel
URLs. By default, durable output is written below
`~/.tkn/youtube_note_pipeline/`.

Only `ingest` and `build-summary` use generative AI. `ingest` uses it because
the command includes the summary stage. `acquire`, `import-raw`, `build-source`,
`validate`, and `config show` are deterministic operations.

## Progress logs

Commands show progress logs on standard error by default and keep the final JSON
result on standard output. This follows common CLI behavior: people can see
progress interactively, while scripts can still capture or pipe the JSON result.
The implementation adds a `SUCCESS` level to Python's standard `logging` module
and adds no logging dependency.

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --quiet
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --verbose
```

- Default: show `[INFO]`, `[SUCCESS]`, `[WARNING]`, and `[ERROR]` messages.
- `-q` / `--quiet`: suppress progress logs and show errors only.
- `-v` / `--verbose`: include `[DEBUG]` diagnostics.

In an interactive terminal, successful outcome lines including `[SUCCESS]` are
green, while `[ERROR]` and `[CRITICAL]` lines are red. This uses ANSI terminal
colors and is not specific to PowerShell. Redirected or piped logs stay
uncolored automatically, and the `NO_COLOR` environment variable also disables
color.

## Configuration

Configuration is merged in this order:

1. built-in defaults;
2. `~/.tkn/youtube_note_pipeline/config.yaml`;
3. `./.tkn/config.yaml`;
4. a file passed with `--config`;
5. individual CLI options.

To create the user-global configuration, copy the committed example and then
customize it for your environment:

```console
New-Item -ItemType Directory -Force "$HOME\.tkn\youtube_note_pipeline"
Copy-Item ".tkn\config.example.yaml" "$HOME\.tkn\youtube_note_pipeline\config.yaml"
```

For a repository-local override, copy the example to `./.tkn/config.yaml`
instead.

The example contains:

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
summary_prompt: null
```

Ordinary relative output paths are resolved from the current working directory.
`summary_prompt` has stricter rules:

- `null` uses the packaged built-in instructions.
- A filename such as `my-summary.md` resolves below
  `~/.tkn/youtube_note_pipeline/prompts/`.
- A prompt elsewhere must use an absolute path; `~` home expansion is accepted.
- Nested relative values such as `prompts/my-summary.md` are rejected.

The file must be a non-empty UTF-8 `.md` file with this required Frontmatter:

```yaml
---
type: prompt
id: 00000000-0000-4000-8000-000000000001
version: "1.0"
---
```

`id` must be a UUID and remains stable for the lifetime of one prompt. Increment
the quoted `version` when changing that prompt's instructions. Although a
correctly formed file can be created manually, `youtube-notes prompt init` is
recommended because it generates a unique ID. A missing or invalid custom
prompt stops summary generation instead of silently using the built-in prompt.
The same resolution applies to `--summary-prompt`, which has the highest normal
CLI precedence. Do not commit private machine paths or credentials to a public
repository.

Custom Markdown replaces only the human-editable summary instructions. The
pipeline always appends the title, URL, transcript, transcript-as-untrusted-data
guardrail, and structured JSON output contract.

Prompt identity controls summary identity:

- A different prompt `id` creates a separate summary file for the same source.
  Its filename normally uses the first eight UUID hexadecimal characters, for
  example `_70a1a332.md`; the complete UUID remains authoritative in
  Frontmatter. If two IDs share that prefix, the filename prefix is extended
  only as far as needed.
- Existing summaries are found by matching Frontmatter `url` and `promptId`,
  not by filename. Existing complete-UUID names and manual renames therefore
  remain valid and are reused without creating a duplicate.
- A different `version` with the same `id` regenerates and updates that prompt's
  existing summary automatically. The summary keeps its `noteId` and `date`,
  receives a new `updated`, and returns to `reviewStatus: unreviewed`.
- The same `id` and `version` remains idempotent and returns `unchanged`.
- `--overwrite` / `--force` remains the explicit way to regenerate without a
  prompt version change.

The built-in instructions require source attribution, prohibit unsupported
inference and external knowledge, organize the whole video by topic from
abstract to concrete, omit nonessential advertising and calls to action, and
define the expected content of each structured summary field.

### User directory layout

The default user-level layout is:

```text
~/.tkn/youtube_note_pipeline/
  config.yaml
  prompts/
    summary.md
  data/
    raw/
    source/
    summary/
  state/
    reports/

~/.cache/youtube_note_pipeline/
  yt-dlp/
```

This layout follows the
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)'s
separation of configuration, durable data, persistent state, disposable cache,
and runtime files while retaining fixed, cross-platform locations below the
user's home directory.

`config.yaml` is kept directly under the application directory because a
separate `config/config.yaml` hierarchy would add no useful distinction while
there is only one configuration file. Raw captures, source notes, and summaries
are durable user data. User-edited prompt Markdown is a configuration asset kept
in `prompts/`. Run reports are persistent application state. Disposable cache
data is stored below `~/.cache/youtube_note_pipeline/`.

Each generated summary stage records prompt ID, document version, application
envelope version, source, and SHA-256 in its run report.

Provider-only temporary files use Python's platform temporary directory
resolution (`%TMP%` on Windows and the standard temporary directory on
Linux). Atomic-write staging files are created next to their destination and
removed or promoted within the same operation so that replacement stays on one
filesystem and can remain atomic.

The former `~/.tkn/youtube-note-pipeline/` directory is not searched. When
upgrading from an earlier version, move `config.yaml` to the new underscored
directory and move existing reports below `state/reports/`.

On Windows, if `codex` resolves to a different executable in an automated
process than it does in an interactive PowerShell session, set
`codex_executable` to the absolute path of the working `codex.exe` in a
user-global or explicitly passed configuration file.

When `model` is set, the pipeline passes it to `codex exec --model` and records
the exact value as `generator: "Codex (<model>)"`. When `model` is `null`, the
pipeline best-effort detects the effective model reported by the Codex execution
log. If Codex does not report it, the fallback remains `generator: "Codex"`.
Set `model` explicitly when a stable, reproducible model selection and label are
required.

## Raw capture contract

Each capture is stored at:

```text
<raw-root>/<video-id>/<captured-at>/
  metadata.info.json
  captions.<language>.json3
  manifest.json
```

The manifest records schema version, hashes, selected caption track, tool
version, canonical URL, and success or failure. A failed caption acquisition
does not produce a source or summary note.

Generated source notes remain on Frontmatter `schemaVersion: "1.0"`. New summary
notes use `type: summary` and `schemaVersion: "3.0"`, include `promptId` and
`promptVersion`, and omit `nouns` so a separate CLI can assign that metadata.
Legacy summary schemas 1.0 and 2.0 remain valid for existing notes. Both notes
store the same `cover`. A current summary description is derived from
`## 5. Conclusion`; long descriptions are compacted to a bounded single-line
value. Its shared source description is not modified. A generated summary
starts with `reviewStatus: unreviewed`. Subsequent validation accepts the review
workflow states `unreviewed`, `pending`, `reviewing`, `accepted`,
`needs-revision`, and `rejected`.

## Development

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

Normal tests use synthetic fixtures. Live YouTube and Codex smoke tests are
explicit operations and are not run in CI.
