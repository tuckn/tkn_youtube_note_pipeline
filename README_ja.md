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

通常は、次のコマンドでeditable installationを行います。例示している`C:\path\to\tkn_youtube_note_pipeline`は、このリポジトリの実際のフォルダパスに置き換えてください。

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
| `youtube-notes acquire <video-url>` | metadataと字幕だけを取得 |
| `youtube-notes import-raw --metadata <file> --captions <file>` | 別の方法で取得したmetadataと字幕を取り込み |
| `youtube-notes build-source <manifest>` | 取得済み字幕から字幕全文のMarkdownノートを作成 |
| `youtube-notes build-summary <source-note>` | 既存のsourceノートから要約Markdownノートを作成 |
| `youtube-notes validate <artifact>` | 生成物を検証 |
| `youtube-notes config show` | 有効な設定とsummary profileを表示 |

各コマンドのoptionは`youtube-notes <command> --help`で確認できます。

### 進捗ログ

進捗はstandard errorへ、最終的なJSON resultはstandard outputへ出力します。

- 既定: 通常の進捗を表示
- `-q` / `--quiet`: 進捗を省略し、errorだけを表示
- `-v` / `--verbose`: 詳細な診断情報も表示

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

summary生成stageのrun reportには、選択したprofile名とSHA-256、prompt ID、document version、application envelope version、prompt source、prompt SHA-256を記録します。provider用の一時ファイルにはplatformのtemp directoryを使用し、artifactは保存先の隣でstagingしてatomicに置き換えます。

生成AIを使うコマンドは`ingest`と`build-summary`です。`acquire`、`import-raw`、`build-source`、`validate`、`config show`はdeterministicな処理です。進捗ログはPython標準の`logging`を使用し、interactive terminalではlevelに応じて色を付け、redirectまたはpipe時は無色にします。

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
