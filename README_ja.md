# tkn_youtube_note_pipeline

[English](README.md)

`tkn_youtube_note_pipeline`は、1本のYouTube動画を次の再現可能な3層へ変換します。

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

通常は、次のコマンドでeditable installationを行います。例示している`C:\path\to\tkn_youtube_note_pipeline`は、このリポジトリの実際のフォルダパスに置き換えてください。リポジトリのパスを明示しているため、どのworking directoryからでも実行できます。

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

`-e`（`--editable`）を指定すると、インストールされた`youtube-notes`はリポジトリ内のソースコードを直接参照します。そのため、`git pull`などでソースコードを更新しても、再インストールせずに変更が反映されます。2つ目のコマンドは、インストール後に現在の設定を表示し、`youtube-notes`を実行できることを確認します。

リポジトリ内の変更を自動的に反映しないnon-editable installationへ切り替える場合は、次のコマンドを実行します。

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --force
```

non-editable installationでは、インストール時点のコードが使用され、その後のリポジトリの変更は自動的に反映されません。`git pull`などでリポジトリを更新した後、変更をインストール済みの`youtube-notes`へ反映するには、同じコマンドを再度実行してください。

## コマンド

1本の動画について全stageを実行します。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

metadataと字幕のraw capture、完全なTranscriptを持つsourceノート、structured
summaryノートを順に生成します。字幕取得に失敗した場合はderived noteを作らずに停止し、
成功・失敗のどちらでもJSON run reportを残します。

同じ保存先に内容の異なるsourceまたはsummaryノートがあり、意図的に両方を再生成して
上書きする場合は`--force`を指定します。`--overwrite`も同じ意味のaliasです。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

`--force`はsourceとsummaryの既存内容（review済みの編集を含む）を置き換えるため、
再生成してよいことを確認した場合だけ使用してください。raw captureも新しく取得する
場合は`--refresh --force`を併用します。

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
youtube-notes build-summary path/to/source-note.md --summary-prompt my-summary.md
```

sourceのTranscriptをconfigured structured-output provider（version 1ではCodex）へ渡し、
sourceに忠実な日本語summaryノートを作り、両方のノートを検証します。semantic
classificationやontology linkは追加しません。summary schema 2.0以降では、1つのsourceを
複数promptのsummaryが共有できるよう、特定summaryのdescriptionをsourceへ同期しません。

組み込みのsummary指示を編集用ファイルとして初期化します。

```console
youtube-notes prompt init
youtube-notes prompt init my-summary.md
```

`summary.md`または指定した`.md`ファイル名を
`~/.tkn/youtube_note_pipeline/prompts/`以下へ作成し、作成先をJSONで表示します。
`config.yaml`は変更せず、既存ファイルも上書きしません。各promptにはuniqueなUUIDと
初期version `"1.0"`を設定します。編集後はconfigに`summary_prompt: my-summary.md`を
設定するか、生成コマンドへ
`--summary-prompt my-summary.md`を渡します。

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
summary promptについては、有効なMarkdownを検証し、built-in/customのmode、ID、
document version、解決済みsource、SHA-256も表示します。contentの取得や生成は行いません。

version 1は1回の実行につき1本の動画URLだけを受け付け、playlist URLとchannel URLを
拒否します。永続データの既定の出力先は`~/.tkn/youtube_note_pipeline/`以下です。

生成AIを使うコマンドは`ingest`と`build-summary`だけです。`ingest`は内部にsummary
stageを含むため生成AIを使います。`acquire`、`import-raw`、`build-source`、
`validate`、`config show`はdeterministicな処理です。

## 進捗ログ

既定では、進捗ログをstandard errorへ、最終的なJSON resultをstandard outputへ
出力します。interactiveな実行では進捗が見え、scriptからはJSONだけをcapture・pipe
できる、一般的なCLIの挙動です。Python標準の`logging` moduleに`SUCCESS` levelを
追加しており、logging専用のdependencyは追加していません。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --quiet
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --verbose
```

- 既定: `[INFO]`、`[SUCCESS]`、`[WARNING]`、`[ERROR]`を表示
- `-q` / `--quiet`: 進捗を省略し、errorだけを表示
- `-v` / `--verbose`: `[DEBUG]`の診断情報も表示

interactive terminalでは`[SUCCESS]`を含む成功行を緑、`[ERROR]`と`[CRITICAL]`を
赤で表示します。これはPowerShell固有の機能ではなくANSI terminal colorを使います。
redirectまたはpipeされたログは自動的に無色になり、`NO_COLOR` environment variable
でも色を無効化できます。

## 設定

設定は次の順にmergeされ、後の値が前の値を上書きします。

1. built-in defaults
2. `~/.tkn/youtube_note_pipeline/config.yaml`
3. `./.tkn/config.yaml`
4. `--config`で指定したファイル
5. 個別のCLI option

user-global configを作成するには、commit済みのexampleをコピーしてから、使用環境に
合わせて変更してください。

```console
New-Item -ItemType Directory -Force "$HOME\.tkn\youtube_note_pipeline"
Copy-Item ".tkn\config.example.yaml" "$HOME\.tkn\youtube_note_pipeline\config.yaml"
```

repository-localなoverrideとして使う場合は、代わりに`./.tkn/config.yaml`へコピーします。

exampleの内容:

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

通常のrelativeな出力pathはcurrent working directoryを基準に解決します。
`summary_prompt`には次の専用規則を適用します。

- `null`はpackageに含まれる組み込み指示を使用
- `my-summary.md`のようなファイル名だけの値は
  `~/.tkn/youtube_note_pipeline/prompts/`以下として解決
- その他の場所はabsolute pathで指定し、`~`によるhome展開も許可
- `prompts/my-summary.md`のような階層を含むrelative pathは拒否

custom promptは、空でないUTF-8の`.md`ファイルで、次のFrontmatterが必要です。

```yaml
---
type: prompt
id: 00000000-0000-4000-8000-000000000001
version: "1.0"
---
```

`id`はUUIDとし、1つのpromptの生存期間中は変更しません。指示を更新するときは、quoted
stringの`version`を更新します。手作業でも作成できますが、unique IDを確実に発行する
`youtube-notes prompt init`を推奨します。missingまたは不正な場合、組み込みpromptへ
黙ってfallbackせず、summary生成を停止します。
`--summary-prompt`にも同じ解決規則を適用し、通常のCLI優先順位で最優先になります。
privateなmachine pathやcredentialをpublic repositoryへcommitしないでください。

custom Markdownが置き換えるのは、人が編集できるsummary指示だけです。title、URL、
Transcript、Transcriptを信頼できない入力dataとして扱うguardrail、structured JSONの
出力契約はpipelineが必ず追加します。

prompt identityはsummary identityを次のように決定します。

- 異なるprompt `id`は、同じsourceから別summaryを作成。ファイル名には通常、
  `_70a1a332.md`のようにUUIDの先頭8桁を使用し、完全UUIDはFrontmatterで保持。
  先頭8桁が衝突した場合だけ、必要な長さまでprefixを延長
- 既存summaryはファイル名ではなくFrontmatterの`url`と`promptId`で検索。完全UUID名や
  手動rename後のファイルも同じsummaryとして再利用し、重複生成しない
- 同じ`id`で`version`が異なる場合、同じsummaryを自動再生成し、`noteId`と`date`を保持、
  `updated`を更新して`reviewStatus: unreviewed`へ戻す
- 同じ`id`と`version`はidempotentに`unchanged`
- versionを変えずに再生成する場合だけ、明示的な`--overwrite` / `--force`を使用

組み込み指示は、主張の帰属、根拠のない推測と外部知識の禁止、動画全体を抽象から具体へ
論点別に再構成すること、主題に不要な広告とCTAの除外、structured summaryの各fieldに
含める内容を明示しています。

### ユーザーディレクトリの構成

user-levelの既定レイアウトは次のとおりです。

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

このレイアウトは、
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
によるconfig、永続data、永続state、破棄可能なcache、runtime fileの分離を尊重しながら、
user home以下の固定されたcross-platformな場所を使用します。

設定ファイルが1つだけの現状では`config/config.yaml`としても有用な区別が増えないため、
`config.yaml`はapplication directoryの直下に置きます。raw capture、sourceノート、
summaryノートは永続的なuser data、ユーザーが編集するprompt Markdownは`prompts/`に
置くconfig資産、run reportは永続的なapplication stateです。破棄可能なcache dataは
`~/.cache/youtube_note_pipeline/`以下へ保存します。

summary生成stageのrun reportには、prompt ID、document version、application envelope
version、prompt source、prompt SHA-256を記録します。

providerだけが使用する一時ファイルには、Pythonがplatformごとに解決するtemp
directory（Windowsでは`%TMP%`、Linuxでは標準temp directory）を使います。
atomic writeのstaging fileは、置換を同一filesystem内に保ってatomicにできるよう
保存先の隣に作成し、同じoperation内で削除または正式ファイルへ置き換えます。

旧`~/.tkn/youtube-note-pipeline/`directoryは検索しません。以前のversionから更新する
場合は、`config.yaml`をunderscore表記の新directoryへ移動し、既存reportを
`state/reports/`以下へ移動してください。

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

生成するsourceノートはFrontmatter `schemaVersion: "1.0"`を維持します。新しいsummaryは
`type: summary`と`schemaVersion: "4.0"`を使用し、`promptId`と`promptVersion`を含みます。
`nouns`は登録せず、別のCLIによる付与に委ねます。既存summaryのschema 1.0、2.0、3.0も
引き続き検証できます。両方のノートに同じ`cover`を保存し、現行summaryはタイトル直下にも
動画を埋め込みます。現行summaryのdescriptionは`## 5. Conclusion`から作成し、長い場合は
一定長の1行へ区切ります。
共有sourceのdescriptionは変更しません。生成時のsummaryは`reviewStatus: unreviewed`で
始まります。その後の検証ではreview workflowの状態として`unreviewed`、`pending`、
`reviewing`、`accepted`、`needs-revision`、`rejected`を受け付けます。

## 開発

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

通常のtestはsynthetic fixtureを使います。実際のYouTubeやCodexを使うsmoke testは
明示的な操作であり、CIでは実行しません。
