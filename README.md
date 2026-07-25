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
```

This sends the source transcript to the configured structured-output provider
(Codex in version 1), creates the source-faithful Japanese summary note, and
updates the source note description from `## 1. Summary`. It validates both
notes and does not add semantic classification or ontology links.

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
were actually loaded. It does not acquire or generate any content.

Version 1 accepts one video URL per invocation and rejects playlist and channel
URLs. By default, output is written below `./youtube-notes/`.

Only `ingest` and `build-summary` use generative AI. `ingest` uses it because
the command includes the summary stage. `acquire`, `import-raw`, `build-source`,
`validate`, and `config show` are deterministic operations.

## Progress logs

Commands show progress logs on standard error by default and keep the final JSON
result on standard output. This follows common CLI behavior: people can see
progress interactively, while scripts can still capture or pipe the JSON result.
The implementation uses Python's standard `logging` module and adds no logging
dependency.

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --quiet
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --verbose
```

- Default: show `[INFO]`, `[WARNING]`, and `[ERROR]` messages.
- `-q` / `--quiet`: suppress progress logs and show errors only.
- `-v` / `--verbose`: include `[DEBUG]` diagnostics.

## Configuration

Configuration is merged in this order:

1. built-in defaults;
2. `~/.tkn/youtube-note-pipeline/config.yaml`;
3. `./.tkn/config.yaml`;
4. a file passed with `--config`;
5. individual CLI options.

Example `./.tkn/config.yaml`:

```yaml
raw_root: ./data/raw
source_root: ./data/source
summary_root: ./data/summary
reports_root: ./data/reports
provider: codex
model: null
fallback_languages:
  - en
codex_executable: codex
```

Relative paths are resolved from the current working directory. Do not commit
private machine paths or credentials to a public repository.

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

Generated source and summary notes use Frontmatter `schemaVersion: "1.0"`.
Both notes store the same `cover`. The source description is derived from
`## 1. Summary`, while the summary description is derived from
`## 5. Conclusion`; long descriptions are compacted to a bounded single-line
value. A generated summary starts with `reviewStatus: unreviewed`. Subsequent
validation accepts the review workflow states `unreviewed`, `pending`,
`reviewing`, `accepted`, `needs-revision`, and `rejected`.

## Development

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

Normal tests use synthetic fixtures. Live YouTube and Codex smoke tests are
explicit operations and are not run in CI.
