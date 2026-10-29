# CLI output contract

This contract applies to every `tkn-youtube-note` command. Help and version retain
their normal informational output. It changes console presentation only; Python
return values, generated notes, RAW manifests, saved reports and network protocols
keep their existing contracts.

## Format and streams

Default stdout is a copyable list with one `key=value` per line. Nested keys use
`.` and array elements use `[0]`, `[1]`, etc. Empty collections are `[]` and `{}`;
booleans are `true`/`false`; unset values are `null`. Strings have no JSON quotes.
Windows backslashes remain single and paths are never shortened. Control characters,
including newlines, tabs and ANSI escape characters, are escaped on one line.

`--json` selects one UTF-8 JSON object on stdout. Normal operation, dry-run,
validation, configuration operations, errors and interruption use the same format
selection. Progress, warnings and diagnostics belong to stderr. No log headers or
color codes are injected into JSON. Secrets are not public result fields.

`--json`, `--full-output`, `--quiet` and `--verbose` can occur before or after the
command, including between `config` and `list`/`init`. Nested argument parsing
preserves selections. `--quiet` and `--verbose` are mutually exclusive and affect
only stderr logs. Pipes, redirects and TTY detection do not change result format.
After the `--` positional separator, option-like strings are positional values.

## Result keys

Command-specific fields use the types described below. Automation should tolerate
additional fields and counts whose value is zero being absent. Units depend on the command, as described below; stage counts are not video
counts. Human and JSON formats expose the same selected detail level.

| Command | Result fields | CLI summary and target fields |
| --- | --- | --- |
| `ingest` | `status`, `path`, `report` | `stages[]` (`path`, `status`, `details`); `counts` by stage status |
| `acquire`, `import-raw`, `build-source`, `build-summary` | `status`, `path`, `report` | one stage in `stages[]`; `counts` by stage status; failed acquisition reason in `stages[].details.error` |
| processing `--dry-run` | `dry_run`, `status`, `path`, `details` | one planned stage in `counts`, or `counts.require_force=1` for a protected collision |
| `list` | `schema_version`, `count`, `items[]`, `warnings[]` | `counts.videos`, `counts.warnings`; all videos are listed |
| `validate`, `status` | `kind`, `valid`, `errors[]`; `currency` for summary status | input `path`, `counts.checked`, `counts.invalid`; error strings remain in `errors[]` |
| `config list` | `sources[]`, `values`, `generationResolved`, `winning_sources`, `source_schema_versions[]`, `effective_schema_version` | `status=success`, `counts.sources` (includes built-in defaults) |
| `config init` | `status`, `path` | `counts` by init status (`created`, `unchanged`, `planned`) |
| `migrate-notes --dry-run` | plan roots, schema, scope, `counts`, `items[]`, `warnings[]` | `status`, `counts.total`, `counts.warnings`; optional `omitted_items` and `details_hint` |
| `migrate-notes` | apply result (`status`, `updated`, `counts`, optional `files`, `backup_root`, `report_root`) | `attention[]` retains blocked paths/reasons; `warnings[]` retains planning warnings |

Every result includes `status` (string), `outcome` (string), and `counts` (mapping
of string keys to integer counts). Existing `status` values such as `created`,
`updated`, `unchanged` and `planned` retain their meanings. `outcome` is `success`,
`failed`, or `partial_failure`; a failed command with completed/planned/unchanged
items is `partial_failure`. A blocked dry-run has not performed those planned
changes. Warning-only inventories still exit zero, preserving their existing
success criteria; inspect `warnings` and `counts.warnings`.

Unexpected failures return `status=failed`, `error_type`, `error`, and `targets`
(named input/configuration/output-root paths). OS errors also include `path` and
`path2` when provided by the OS. Reasons and paths are separate, so callers do not
need to parse error text. Configuration errors include available source paths and
omit Pydantic input values from public diagnostics. Malformed YAML diagnostics
show the line and column without echoing source text. Argument errors return
`error_type=argument_error`. Interruption returns `status=interrupted`,
`error=interrupted`, available `targets` and `counts.interrupted=1`.
The original provider diagnostic body stays in the existing diagnostic file;
CLI results expose the report path. Existing ingest failure reports expose
completed `stages` and counts when their report can be read.

Result writing is best effort when stdout itself fails (for example a closed pipe)
or the process is forcibly terminated. Completed writes are not rolled back by
interruption. No result-only option enables/disables acquisition, AI, report
creation, or other application side effects.

## Detail level and migration plans

Only `migrate-notes --dry-run` condenses `unchanged` and `skipped` items by default.
Their counts remain visible; `omitted_items` and `details_hint` describe omitted
rows and how to retrieve them. Blocked and planned items, warnings, and applied
files stay visible. `--full-output` restores all rows in text and JSON alike.
Other commands already return all relevant details and accept this option without
changing their content.

For a plan that will be saved and reapplied, request complete JSON explicitly:

```shell
tkn-youtube-note migrate-notes --dry-run --json --full-output
```

Save stdout as UTF-8 in `.local/data/<datetime_work-id>/migration-plan.json`, inspect
it, then use `--apply-plan` with that file. Add `--authors-only` to both commands
for author migration. CLI summary fields are additive; the migration API and
persisted plan/report formats have not changed.

## Exit codes

| Exit | Meaning |
| --- | --- |
| 0 | existing command-specific success criteria satisfied |
| 1 | processing/configuration/validation failure, protected dry-run collision, or migration with blocked items |
| 2 | invalid or missing command arguments |
| 130 | keyboard interruption |

## Machine-readable examples

Use `--json` to read command results as JSON. This option controls stdout formatting;
it does not select artifact types or save files. Help and version keep their normal
informational output.

```shell
tkn-youtube-note --json list
tkn-youtube-note config --json list
tkn-youtube-note validate "<note-path>" --json
```
