# youtube-note-pipeline

[English](README.md)

`youtube-note-pipeline`は、1本のYouTube動画を次の再現可能な3層へ変換します。

1. 不変なraw metadata、字幕、capture manifest
2. provenanceと完全なTranscriptを持つsource Markdownノート
3. structured-output providerで生成する、sourceに忠実なsummary Markdownノート

semantic classificationとontology promotionは、このpipelineの責務外です。

## 必要なもの

- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)
- summary生成時に`PATH`から実行できる`codex`

Python版`yt-dlp`はproject dependencyとして自動的にインストールされ、
embedded `YoutubeDL` API経由で呼び出されます。別途`yt-dlp` CLIをインストールしたり、
`PATH`を通したりする必要はありません。

このpipelineは動画binaryをdownloadせず、Codexのcredentialやauthenticationを
インストール・設定しません。

## インストール

```console
uv tool install -e .
youtube-notes config show
```

non-editable installationへ切り替える場合:

```console
uv tool install . --force
```

## コマンド

1本の動画について全stageを実行します。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

metadataと字幕のraw capture、完全なTranscriptを持つsourceノート、structured
summaryノートを順に生成します。字幕取得に失敗した場合はderived noteを作らずに停止し、
成功・失敗のどちらでもJSON run reportを残します。

raw inputだけを取得します。

```console
youtube-notes acquire "https://www.youtube.com/watch?v=VIDEO_ID"
```

動画をdownloadせず、metadataと優先順位に従って選択した完全なJSON3字幕を保存し、
manifestを作成します。source・summaryノートは作りません。同じ内容の成功済みcaptureは
再利用し、`--refresh`指定時だけ新しいcaptureを作ります。

pipeline外で取得したraw inputを取り込みます。

```console
youtube-notes import-raw --metadata metadata.info.json --captions captions.ja.json3
```

指定したmetadataとJSON3字幕を検証し、不変なraw captureとmanifestとして保存します。
外部fallbackで字幕を取得した場合に使います。derived noteは作りません。

成功したraw manifestからsourceノートを作ります。

```console
youtube-notes build-source path/to/manifest.json
```

provenanceと完全な時刻付きTranscriptを持つMarkdown sourceノートを作り、
保存したJSON3字幕との全文一致を検証します。

有効なsourceノートからsummaryノートを作ります。

```console
youtube-notes build-summary path/to/source-note.md
```

sourceのTranscriptをconfigured structured-output provider（version 1ではCodex）へ渡し、
sourceに忠実な日本語summaryノートを作ります。同時にsourceノートのdescriptionを
`## 1. Summary`から更新し、両方のノートを検証します。semantic classificationや
ontology linkは追加しません。

pipeline artifactを1件検証します。

```console
youtube-notes validate path/to/artifact
```

raw manifest、sourceノート、summaryノートのどれかを自動判定し、artifact kind、
validity、errorをJSONで表示します。検証失敗時はnon-zeroで終了します。

有効な設定を表示します。

```console
youtube-notes config show
```

merge後の非secret設定と、実際に読み込まれた設定sourceを表示します。
contentの取得や生成は行いません。

version 1は1回の実行につき1本の動画URLだけを受け付け、playlist URLとchannel URLを
拒否します。既定の出力先は`./youtube-notes/`以下です。

生成AIを使うコマンドは`ingest`と`build-summary`だけです。`ingest`は内部にsummary
stageを含むため生成AIを使います。`acquire`、`import-raw`、`build-source`、
`validate`、`config show`はdeterministicな処理です。

## 進捗ログ

既定では、進捗ログをstandard errorへ、最終的なJSON resultをstandard outputへ
出力します。interactiveな実行では進捗が見え、scriptからはJSONだけをcapture・pipe
できる、一般的なCLIの挙動です。Python標準の`logging` moduleを使っているため、
logging専用のdependencyは追加していません。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --quiet
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --verbose
```

- 既定: `[INFO]`、`[WARNING]`、`[ERROR]`を表示
- `-q` / `--quiet`: 進捗を省略し、errorだけを表示
- `-v` / `--verbose`: `[DEBUG]`の診断情報も表示

## 設定

設定は次の順にmergeされ、後の値が前の値を上書きします。

1. built-in defaults
2. `~/.tkn/youtube-note-pipeline/config.yaml`
3. `./.tkn/config.yaml`
4. `--config`で指定したファイル
5. 個別のCLI option

`./.tkn/config.yaml`の例:

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

relative pathはcurrent working directoryを基準に解決します。privateなmachine pathや
credentialをpublic repositoryへcommitしないでください。

Windowsで自動処理とinteractive PowerShellが異なる`codex`を解決する場合は、
user-global configまたは`--config`で渡す設定の`codex_executable`に、動作する
`codex.exe`のabsolute pathを指定してください。

`model`を指定した場合、pipelineはその値を`codex exec --model`へ渡し、
`generator: "Codex (<model>)"`としてそのまま記録します。`model: null`の場合は、
Codexの実行ログが報告するeffective modelをbest-effortで検出します。Codexがモデル名を
報告しなかった場合だけ`generator: "Codex"`へfallbackします。モデル選択と表記を
安定・再現可能にしたい場合は、`model`を明示してください。

## Raw capture契約

各captureは次の場所へ保存されます。

```text
<raw-root>/<video-id>/<captured-at>/
  metadata.info.json
  captions.<language>.json3
  manifest.json
```

manifestはschema version、hash、選択したcaption track、tool version、canonical URL、
成功・失敗を記録します。字幕取得に失敗した場合、source・summaryノートは作りません。

生成するsource・summaryノートはFrontmatter `schemaVersion: "1.0"`を使用します。
両方のノートに同じ`cover`を保存します。sourceのdescriptionは`## 1. Summary`、
summaryのdescriptionは`## 5. Conclusion`から作成し、長い場合は一定長の1行へ
区切ります。生成時のsummaryは`reviewStatus: unreviewed`で始まります。その後の
検証ではreview workflowの状態として`unreviewed`、`pending`、`reviewing`、
`accepted`、`needs-revision`、`rejected`を受け付けます。

## 開発

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

通常のtestはsynthetic fixtureを使います。実際のYouTubeやCodexを使うsmoke testは
明示的な操作であり、CIでは実行しません。
