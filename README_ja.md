# tkn_youtube_note_pipeline

[English](README.md)

`tkn_youtube_note_pipeline`は、YouTube動画の内容を日本語または英語で要約し、Markdownノートとして保存するCLIです。既定では日本語で要約します。

通常は、動画URLを指定して次の1コマンドを実行します。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

## 必要なもの

- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)
- summary生成時に`PATH`から実行できる、認証済みの`codex`

Python版`yt-dlp`はdependencyとして自動的にインストールされるため、`yt-dlp` CLIを別途インストールする必要はありません。動画本体はdownloadしません。

## インストール

次のコマンドでインストールします。例示している`C:\path\to\tkn_youtube_note_pipeline`は、このリポジトリの実際のフォルダパスに置き換えてください。

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

2つ目のコマンドは、インストール後に現在の設定を表示し、`youtube-notes`を実行できることを確認します。この方式では、インストール時点のコードが使用され、その後のリポジトリの変更は自動的に反映されません。

`git pull`などでリポジトリを更新するたびに、更新後のコードと依存モジュールをインストール済みのコマンドへ反映するため、次のコマンドで再インストールしてください。

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline"
youtube-notes config show
```

開発時には、代わりにeditable installationを使用できます。

```console
uv tool install -e "C:\path\to\tkn_youtube_note_pipeline"
```

`-e`（`--editable`）を指定すると、インストールされたコマンドはリポジトリ内のソースコードを直接参照するため、ソースコードの変更は再インストールせずに反映されます。ただし、更新によって`pyproject.toml`の依存関係、package metadata、entry pointが変更された場合は、tool環境にも反映するため、同じeditable installationのコマンドを再実行してください。

通常の再インストールが失敗する、インストール済みコマンドが古い依存関係を使い続ける、またはtool環境やentry pointが壊れている場合は、`--force`を指定してtool環境を再作成してください。

```console
uv tool install "C:\path\to\tkn_youtube_note_pipeline" --force
youtube-notes config show
```

editable installationをeditableのまま修復する場合は、`--force`付きのインストールコマンドに`-e`も指定してください。

## 設定

user-global configを初期化し、有効な設定を確認します。

```console
youtube-notes config init
youtube-notes config show
```

`config init`はpackageに含まれるexampleを`~/.tkn/youtube_note_pipeline/config.yaml`へ作成し、statusとpathをJSONで表示します。同じ内容のファイルがすでにある場合は`unchanged`とし、編集済みの既存設定は上書きしません。repository-localなoverrideには`./.tkn/config.yaml`を使用し、任意の設定ファイルは`--config`で指定できます。

設定は次の順にmergeされ、後の値が前の値を上書きします。

1. built-in defaults
2. `~/.tkn/youtube_note_pipeline/config.yaml`
3. `./.tkn/config.yaml`
4. `--config`で指定したファイル
5. 個別のCLI option

初期化されるconfigの内容:

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

通常のrelativeな出力pathはcurrent working directoryを基準に解決します。privateなmachine pathやcredentialをpublic repositoryへcommitしないでください。

### 保存先

| 設定 | 保存する内容 |
| --- | --- |
| `raw_root` | 取得したmetadataと字幕 |
| `source_root` | 字幕全文を含むMarkdownノート |
| `summary_root` | 要約Markdownノート |
| `reports_root` | 実行結果のJSON report |

既定の`~/.tkn/youtube_note_pipeline/state/`は、`data/`に保存するraw captureやMarkdownノートとは分離して、pipelineの運用状態を置くためのdirectoryです。現行versionでは`reports/`だけを使用し、`ingest`、`acquire`、`import-raw`、`build-source`、`build-summary`の実行ごとに、status、error、各stageの出力pathとdetailsを含むJSON run reportを保存します。providerが失敗した場合は、完全なsubprocess診断を同じdirectoryの`*.provider.log`へ分離して保存します。

これらのreportは後続処理の入力には使用されません。削除すると過去の実行履歴と失敗時の詳細診断は失われますが、raw capture、sourceノート、summaryノートには影響せず、次にreportを出力するコマンドを実行したときに`reports/`が再作成されます。`reports_root`を変更した場合は、reportと診断logの保存先もそのdirectoryへ移ります。

Windowsで自動処理とinteractive PowerShellが異なる`codex`を解決する場合は、user-global configまたは`--config`で渡す設定の`codex_executable`に、動作する`codex.exe`のabsolute pathを指定してください。

`model`を指定すると、そのmodelをCodexの実行に使用します。`model: null`ではCodexが選択したmodelを使用します。

`summary_profile`は要約の出力言語を指定します。`default-ja`は日本語、`default-en`は英語です。通常はconfigで指定し、1回の実行だけ変更する場合は`--summary-profile default-en`を使用できます。

## 使い方

### 動画を要約する

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

字幕を取得し、字幕全文のMarkdownノートと、選択したprofileの言語による要約Markdownノートを作成します。1回の実行で指定できるのは1本の動画です。playlist URLとchannel URLには対応していません。

英語で要約する場合は、configの`summary_profile`を変更するか、次のように指定します。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --summary-profile default-en
```

同じ保存先のsourceノートとsummaryノートを意図的に再生成して置き換える場合は、`--force`を指定します。`--overwrite`も同じ意味です。

```console
youtube-notes ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

`--force`はreview済みの編集も置き換えるため、再生成してよい場合だけ使用してください。metadataと字幕も新しく取得する場合は`--refresh --force`を指定します。

### その他のコマンド

| コマンド | 用途 |
| --- | --- |
| `youtube-notes list` | 取得済み文字起こしと対応するsource・summaryノートをJSONで一覧表示 |
| `youtube-notes acquire <video-url>` | metadataと字幕だけを取得 |
| `youtube-notes import-raw --metadata <file> --captions <file>` | 別の方法で取得したmetadataと字幕を取り込み |
| `youtube-notes build-source <manifest>` | 取得済み字幕から字幕全文のMarkdownノートを作成 |
| `youtube-notes build-summary <source-note>` | 既存のsourceノートから要約Markdownノートを作成 |
| `youtube-notes validate <artifact>` | 生成物を検証 |
| `youtube-notes config show` | 有効な設定とsummary profileを表示 |

各コマンドのoptionは`youtube-notes <command> --help`で確認できます。

`youtube-notes list`は動画ごとに1件を、最新の取得日時から順に返します。各itemには、最新のmanifest・字幕path、成功した取得回数、同じcanonical video URLを持つすべてのsource・summaryノートが含まれます。まだ後続ノートを作成していない取得結果も、空のノート一覧として表示します。読み取れないmanifestやノートは、有効なitemを隠さずtop-levelの`warnings`配列で報告します。

### 進捗ログ

進捗はstandard errorへ、最終的なJSON resultはstandard outputへ出力します。
最終JSONは人が確認しやすい複数行のindent付き形式ですが、そのままJSON parserで
読み取れます。

- `[INFO]`: 処理の開始・進行中の状態を表示
- `[SUCCESS]`: 取得結果やsource・summaryノートが保存・検証済みになった時点で表示
- `[ERROR]`: 処理を完了できなかった場合に表示
- `-q` / `--quiet`: 進捗を省略し、errorだけを表示
- `-v` / `--verbose`: 詳細な診断情報も表示

providerの失敗はstandard errorへ短い要点だけを表示します。完全なprovider出力がある場合は
別の`*.provider.log`へ保存し、run reportの`diagnostic_log`から参照できるため、promptや
Transcript全文がterminalへ流れません。

## 開発

```console
uv sync --locked
uv run pytest
uv run mypy
uv build
```

通常のtestはsynthetic fixtureを使います。実際のYouTubeやCodexを使うsmoke testは
明示的な操作であり、CIでは実行しません。

### 内部の処理とartifact

`ingest`は次のstageを順に実行します。

```text
YouTube URL
  -> raw metadata・字幕・manifest
  -> Transcriptを含むsource Markdown
  -> structured outputを経由したsummary Markdown
```

各raw captureは`<raw-root>/<video-id>/<captured-at>/`に`metadata.info.json`、`captions.<language>.json3`、`manifest.json`として保存します。manifestはschema version、hash、caption track、tool version、canonical URL、成功・失敗を記録します。字幕取得に失敗した場合はsource・summaryノートを作りません。

sourceノートはFrontmatter `schemaVersion: "1.0"`を使用します。新しいsummaryノートは`type: summary`と`schemaVersion: "5.0"`を使用し、prompt・output schema・templateのID、version、SHA-256を記録します。既存summaryのschema 1.0、2.0、3.0、4.0も引き続き検証できます。`nouns`は生成時に登録せず、別のCLIによる付与を許可します。

summary生成stageのrun reportには、選択したprofile名とSHA-256、prompt ID、document version、application envelope version、prompt source、prompt SHA-256を記録します。providerが失敗した場合、reportの`error`は短い要点に限定し、完全なsubprocess診断は`diagnostic_log`が示す別ファイルへ保存します。provider用の一時ファイルにはplatformのtemp directoryを使用し、artifactは保存先の隣でstagingしてatomicに置き換えます。

生成AIを使うコマンドは`ingest`と`build-summary`です。`list`、`acquire`、`import-raw`、`build-source`、`validate`、`config show`はdeterministicな処理です。進捗ログはPython標準の`logging`を使用し、interactive terminalではlevelに応じて色を付け、redirectまたはpipe時は無色にします。

### Application-ownedな要約profile

要約生成に必要なprompt、output schema、Markdown templateは、相互に依存する1つのdeveloper-managed profileとしてまとめています。組み込みprofileはconfigまたはCLIから選択できますが、個別resourceや任意のcustom promptは指定できません。日本語用の`default-ja`と英語用の`default-en`を提供し、開発者が別の要約patternを追加する場合は同じ階層へprofile directoryを追加できます。

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

- `prompt.md`: 要約品質、source fidelity、各fieldへ含める内容
- `output.schema.json`: providerが返すstructured JSONのfield、型、階層
- `template.md`: 最終MarkdownのFrontmatter、見出し、順序、箇条書き、timestamp link

Pythonはprofileを一括で読み込み、profile名、各resourceのID・version・SHA-256、JSON Schema、template placeholderを検証し、3つのhashからprofile全体のSHA-256を計算します。安全な入力envelope、provider実行、provenance、atomic write、artifact検証はapplication-managedのままです。

要約profileのprovenanceは次のように管理します。

- 既存summaryはファイル名ではなくFrontmatterの`url`と`promptId`で検索し、完全UUID名や手動rename後のファイルも同じsummaryとして再利用して重複生成しない
- 組み込みpromptの同じ`id`で`version`が異なる場合、同じsummaryを自動再生成し、`noteId`と`date`を保持して`updated`を更新し、`reviewStatus: unreviewed`へ戻す
- 同じprompt `id`・`version`・SHA-256で、output schemaとtemplateのID・version・SHA-256も一致する場合はidempotentに`unchanged`
- promptの内容をversion変更なしで更新した場合、またはoutput schemaかtemplateのprovenanceが変わった場合は、既存のreview済み編集を自動置換せず、明示的な`--overwrite` / `--force`を要求

組み込み指示は、主張の帰属、根拠のない推測と外部知識の禁止、動画全体を抽象から具体へ論点別に再構成すること、主題に不要な広告とCTAの除外、structured summaryの各fieldに含める内容を明示しています。
