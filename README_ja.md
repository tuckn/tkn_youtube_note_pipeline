# tkn_youtube_note_pipeline

[English](README.md)

`tkn_youtube_note_pipeline`は、YouTube動画の内容を日本語または英語で要約し、Markdownノートとして保存するCLIです。既定では日本語で要約します。

通常は、動画URLを指定して次の1コマンドを実行します。

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

## 必要なもの

- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)
- summary生成時に`PATH`から実行できる、認証済みの`codex`

Python版`yt-dlp`はdependencyとして自動的にインストールされるため、`yt-dlp` CLIを別途インストールする必要はありません。動画本体はdownloadしません。

## インストール

次のコマンドでインストールします。例示している`C:\path\to\tkn_youtube_note_pipeline`は、このリポジトリの実際のフォルダパスに置き換えてください。

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install .
tkn-youtube-note --help
```

最後のコマンドは、インストール後に`tkn-youtube-note`を実行できることを確認します。この方式では、インストール時点のコードが使用され、その後のリポジトリの変更は自動的に反映されません。

`git pull`などでリポジトリを更新するたびに、更新後のコードと依存モジュールをインストール済みのコマンドへ反映するため、次のコマンドで再インストールしてください。

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install . --reinstall
tkn-youtube-note --help
```

`--force`は、実行ファイルの競合やtool環境の破損によって通常の`--reinstall`が成功せず、uvにtool installationの強制作成や既存entry pointの置き換えをさせる必要がある場合に限って使用します。通常のリポジトリ更新には、`--force`ではなく`--reinstall`を使用してください。

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install . --force
tkn-youtube-note --help
```

### 開発用のeditable installation

開発時にソースコードの変更をすぐCLIへ反映したい場合は、editable installationを使用します。

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install -e . --reinstall
```

`-e`（`--editable`）を指定すると、インストールされたコマンドはリポジトリ内のソースコードを直接参照するため、ソースコードの変更は再インストールせずに反映されます。ただし、更新によって`pyproject.toml`の依存関係、package metadata、entry pointが変更された場合や、リポジトリのフォルダを移動または名前変更した場合は、tool環境とリポジトリへの参照を更新するため、同じeditable installationのコマンドを再実行してください。

editable installationをeditableのまま修復する場合は、次のコマンドを使用します。

```console
cd "C:\path\to\tkn_youtube_note_pipeline"
uv tool install -e . --force
```

## 設定

user-global configを初期化し、有効な設定を確認します。

```console
tkn-youtube-note config init
tkn-youtube-note config show
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
fallback_languages: []
provider_timeout_seconds: 600
codex_executable: codex
```

通常のrelativeな出力pathはcurrent working directoryを基準に解決します。privateなmachine pathやcredentialをpublic repositoryへcommitしないでください。

### 保存先

| 設定 | 保存する内容 |
| --- | --- |
| `raw_root` | 取得したraw metadata、字幕データ、manifest |
| `source_root` | 人が読みやすい文字起こしMarkdown sourceノート |
| `summary_root` | 要約Markdownノート |
| `reports_root` | 実行結果のJSON report |

既定の`~/.tkn/youtube_note_pipeline/state/`は、`data/`に保存するraw captureやMarkdownノートとは分離して、pipelineの運用状態を置くためのdirectoryです。通常の`ingest`、`acquire`、`import-raw`、`build-source`、`build-summary`の実行ごとに、status、error、各stageの出力pathとdetailsを含むJSON run reportを`reports/`に保存します。providerが失敗した場合は、完全なsubprocess診断を`*.provider.log`へ分離して保存します。ノート移行の計画・原本backup・結果は`reports/migrations/`へ保存します。dry-runではreportもbackupも作りません。

これらのreportは後続処理の入力には使用されません。削除すると過去の実行履歴と失敗時の詳細診断は失われますが、raw capture、sourceノート、summaryノートには影響せず、次にreportを出力するコマンドを実行したときに`reports/`が再作成されます。`reports_root`を変更した場合は、reportと診断logの保存先もそのdirectoryへ移ります。

Windowsで自動処理とinteractive PowerShellが異なる`codex`を解決する場合は、user-global configまたは`--config`で渡す設定の`codex_executable`に、動作する`codex.exe`のabsolute pathを指定してください。

`model`を指定すると、そのmodelをCodexの実行に使用します。`model: null`ではCodexが選択したmodelを使用します。

`summary_profile`は要約の出力言語を指定します。`default-ja`は日本語、`default-en`は英語です。通常はconfigで指定し、1回の実行だけ変更する場合は`--summary-profile default-en`を使用できます。

## 使い方

### 動画を要約する

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID"
```

raw字幕データと動画metadataを取得し、人が読みやすい文字起こしMarkdown sourceノートへ整形してから、選択したprofileの言語によるsummary Markdownノートを作成します。1回の実行で指定できるのは1本の動画です。playlist URLとchannel URLには対応していません。

#### `ingest`の処理フロー

`ingest`は、次の単独コマンドが提供するものと同じ内部処理を順番にorchestrateします。これらのCLIコマンドを別processとして起動するわけではありません。

| Stage | 対応する単独コマンド | 入力 | 出力 | 生成AI |
| --- | --- | --- | --- | --- |
| 1. 取得 | `acquire <video-url>` | YouTube動画URL | immutableなraw metadata、字幕データ（`captions.<language>.json3`）、`manifest.json` | 不使用 |
| 2. Source構築 | `build-source <manifest>` | 取得済みraw字幕データを参照するmanifest | 検証済みで人が読みやすい文字起こしMarkdown sourceノート | 不使用 |
| 3. Summary構築 | `build-summary <source-note>` | 文字起こしMarkdown sourceノート | 選択したprofileで生成したsummary Markdownノート | 使用 |

```text
YouTube URL
  -> acquire
  -> raw metadata + raw字幕データ + manifest
  -> build-source
  -> 文字起こしMarkdown sourceノート
  -> build-summary
  -> summary Markdownノート
```

途中のstageが失敗した場合、`ingest`はそこで停止し、後続stageのartifactを作成しません。run reportには失敗前に完了したstageを記録します。通常の再実行では、新たに取得した内容が同一なら既存のraw captureを再利用し、検証済みで最新のノートは変更しません。`--refresh`は内容が同一でもstage 1で新しいraw captureを保存し、`--force`はstage 2・3のsource・summaryノートを置き換え、`--refresh --force`は両方を実行します。

英語で要約する場合は、configの`summary_profile`を変更するか、次のように指定します。

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID" --summary-profile default-en
```

同じ動画のsourceノートとsummaryノートを意図的に再生成して置き換える場合は、`--force`を指定します。既存sourceノートはFrontmatter `url`内のYouTube video IDで識別するため、手動でrename・移動したノートも現在のpathで更新します。`--overwrite`も同じ意味です。

```console
tkn-youtube-note ingest "https://www.youtube.com/watch?v=VIDEO_ID" --force
```

`--force`はreview済みの編集も置き換えるため、再生成してよい場合だけ使用してください。raw metadata・字幕データを新しいcaptureとして保存し、両方のノートも再生成する場合は`--refresh --force`を指定します。

### その他のコマンド

| コマンド | 用途 |
| --- | --- |
| `tkn-youtube-note list` | 取得に成功したraw字幕データと対応するsource・summaryノートをJSONで一覧表示 |
| `tkn-youtube-note acquire <video-url>` | Markdownノートを作らず、動画のraw metadataと字幕データを取得 |
| `tkn-youtube-note import-raw --metadata <file> --captions <file>` | 別の方法で取得したraw metadataと字幕データを取り込み |
| `tkn-youtube-note build-source <manifest>` | 取得済みraw字幕データを検証し、人が読みやすい文字起こしMarkdown sourceノートへ整形 |
| `tkn-youtube-note build-summary <source-note>` | 文字起こしMarkdown sourceノートからsummary Markdownノートを作成 |
| `tkn-youtube-note validate <artifact>` | 生成物を検証 |
| `tkn-youtube-note status <note>` | 過去の契約に対する妥当性と、選択profileに対する現行性を別々に表示 |
| `tkn-youtube-note migrate-notes` | backup付きでsource参照と不整合な旧schema宣言を修復 |
| `tkn-youtube-note config show` | 有効な設定とsummary profileを表示 |

各コマンドのoptionは`tkn-youtube-note <command> --help`で確認できます。

`tkn-youtube-note list`は動画ごとに1件を、最新の取得日時から順に返します。各itemには、最新のmanifest・raw字幕データのpath、成功した取得回数、同じcanonical video URLを持つすべてのsource・summaryノートが含まれます。まだ後続ノートを作成していない取得結果も、空のノート一覧として表示します。読み取れないmanifestやノートは、有効なitemを隠さずtop-levelの`warnings`配列で報告します。

### 事前確認・検証・移行

`ingest`、`acquire`、`import-raw`、`build-source`、`build-summary`、`config init`、`migrate-notes`は`--dry-run`に対応します。ローカル入力を検証してJSONの計画を表示し、applicationのファイル書き込み、AI実行（providerの事前実行確認を含む）、remoteデータの取得は行いません。取得前には字幕の有無・正確なcapture日時・最終ノートを確定できないため、`ingest`は後続stageを`deferred`と明示します。ローカルのbuildでは実行時と同じ上書き・再生成判定を使います。`require_force`の計画は終了コード1を返します。通常のコマンドは既定で書き込みます。

```console
tkn-youtube-note build-source <manifest> --dry-run
tkn-youtube-note build-summary <source-note> --dry-run
tkn-youtube-note status <summary-note> --summary-profile default-ja
tkn-youtube-note migrate-notes --dry-run > migration-plan.json
tkn-youtube-note migrate-notes --apply-plan migration-plan.json
```

`ingest`、`build-source`、`build-summary`では`--force`と`--overwrite`を同義で使用できます。強制再生成はreview済みの編集も置き換えます。`provider_timeout_seconds`は既定600秒で、正の有限値を指定し、`--provider-timeout-seconds`で上書きできます。timeoutは短い失敗メッセージとなり、途中までのprovider診断を通常のerror reportへ保存します。組み込み既定値と設定例はどちらも`fallback_languages: []`です。英語字幕へのfallbackを使う場合は`[en]`を指定します。

stageのstatusは`created`、`updated`、`unchanged`、`failed`、`planned`です。raw captureを再利用した場合も`unchanged`を返します。manifestとrun reportの結果は、既存の版に従い`success` / `failure`を維持します。移行計画では追加で、解決できない項目を`blocked`、対象外を`skipped`と表示します。これらは書き込み成功を表すstatusではありません。

`validate`はノートが宣言した過去の契約で検証します。`status`はさらに、`--summary-profile`に対する`currency.is_current`とprovenanceの差分fieldを表示します。古くても契約上正しいノートは、最新版でなくても`valid: true`です。過去のtemplate・output schemaの検証ルールは`resources/summary_contracts.json`へ保持し、現在の生成profileから独立させます。未知の版や改変されたresourceは推測で通さず検証errorにします。対応するノートの版は1.0、1.1、2.0、3.0、4.0、5.0です。

`migrate-notes`は設定されたsource・summaryのrootだけを検索します。動画URLから一意なsourceを特定し、sourceのnote ID・既存の`sourceNoteId`・ファイルの実在を確認して`source`を修復し、確認済みの`sourceNoteId`を記録します。また、1.0/2.0を宣言しながら既に`type: summary`となっているノートは、1.0 → 1.1（prompt情報を補作せず、旧来のsource側description更新を要求しない形式）、2.0 → 3.0へ移行します。元の1.0/2.0の検証契約は維持します。移行後の契約を事前に検証できた場合だけ計画へ載せます。schema宣言のないノートは参照だけ修復でき、推測したschemaは付けません。

移行で変更するのは計画に記載されたFrontmatter fieldだけです。本文のbyte列、ユーザーfield、review状態、`noteId`、`date`、`updated`、BOM、改行コードを保持します。リンクには設定された論理rootのpathを使用し、物理pathの解決後にroot内であることも確認します。書き込み前に計画を再計算し、sourceとsummaryのhashを照合します。候補が曖昧・矛盾する項目はblockedのままにし、安全なplanned項目を適用できます。変更した各ファイルの原本backupと対応表を`result.json`に残します。途中停止した場合も完了分を記録し、backupから復元できます。結果を受け入れるまでは移行backupを保持してください。修復後に新しく移行を実行すると`unchanged`になります。

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

raw字幕データと文字起こしMarkdown sourceノートは同じ発話全文を保持しますが、異なるartifactです。raw JSON3データは機械処理用の取得eventを保持し、sourceノートは人による閲覧と後続の要約処理に適したmetadata・timestamp付き段落を加えます。`ingest`は使い方の節で説明した3つのstageを順番に実行します。

```text
YouTube URL
  -> raw metadata・raw字幕データ・manifest
  -> 文字起こしMarkdown sourceノート
  -> structured outputを経由したsummary Markdownノート
```

各raw captureは`<raw-root>/<video-id>/<captured-at>/`に`metadata.info.json`、`captions.<language>.json3`、`manifest.json`として保存します。manifestはschema version、hash、caption track、tool version、canonical URL、成功・失敗を記録します。字幕取得に失敗した場合はsource・summaryノートを作りません。

sourceノートはFrontmatter `schemaVersion: "1.0"`を使用します。既存sourceノートはファイル名やdirectoryではなく、`source_root`配下を再帰的に検索し、Frontmatter `url`から得たYouTube video IDで識別します。そのためcanonical watch URLと同じvideo IDの`youtu.be` URLは同一identityです。`--overwrite` / `--force`による再生成では、既存の`noteId`と`date`を保持し、`updated`を更新して、発見した現在のpathへ書き戻します。同じ動画のsourceノートが複数ある場合は、暗黙に1件を選ばずerrorにします。

新しいsummaryノートは`type: summary`と`schemaVersion: "5.0"`を使用し、prompt・output schema・templateのID、version、SHA-256を記録します。既存summaryのschema 1.0、2.0、3.0、4.0も引き続き検証できます。`nouns`は生成時に登録せず、別のCLIによる付与を許可します。

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
- 組み込みpromptの同じ`id`で`version`が異なる場合、記録済みのoutput schemaとtemplateのresourceが変わっていなければ同じsummaryを自動再生成し、`noteId`と`date`を保持して`updated`を更新し、`reviewStatus: unreviewed`へ戻す
- 同じprompt `id`・`version`・SHA-256で、output schemaとtemplateのID・version・SHA-256も一致する場合はidempotentに`unchanged`
- promptの内容をversion変更なしで更新した場合、またはoutput schemaかtemplateのprovenanceが変わった場合は、既存のreview済み編集を自動置換せず、明示的な`--overwrite` / `--force`を要求

output schema 1.2では、使っていなかったAI出力の`document.description`を削除しました。日本語prompt 2.3・英語prompt 1.3は描画で使うfieldだけを要求します。Markdownの`description`は引き続きConclusionを短縮して使用するため、ノートのschemaは5.0のままで、表示形式も変わりません。既存のoutput schema 1.1のノートも過去の契約で検証できます。今回のprompt・schema同時更新で再生成する場合は`--force`が必要です。生成resourceを追加するときは、過去の検証ルールを上書きせず、不変の契約をregistryへ追記してください。

組み込み指示は、主張の帰属、根拠のない推測と外部知識の禁止、動画全体を抽象から具体へ論点別に再構成すること、主題に不要な広告とCTAの除外、structured summaryの各fieldに含める内容を明示しています。
