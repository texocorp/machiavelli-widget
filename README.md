# Machiavelli Geopolitics Bot

マキャベリの著作(『君主論』『リウィウス論』『戦争の技法』『フィレンツェ史』— いずれも
パブリックドメイン)から箴言を引用し、地政学的に重要なニュースを冷徹な現実主義の視座で
分析・つぶやくボット。

## 設計思想

- **リベラルな規範の不採用**: 国際法の理想主義や主権平等の建前を出発点にしない。
  代わりに「誰が誰に対して実効的な軍事的優位・依存関係を持つか」という力の実相を
  分析の基準に置く(`geopolitical_scorer.py` のキーワード重み付け、
  `machiavelli_engine.py` の SYSTEM_PROMPT を参照)。
- **日本の対米関係**: 太平洋戦争敗戦以来の指揮権・基地提供・核の傘における対米依存という
  実効支配の実情を、法的建前(独立主権国家)より重視して語る設定にしてある
  (`machiavelli_engine.py` の `THEME_ANALYSIS_TEMPLATES` / SYSTEM_PROMPT 内の指示)。
  これは歴史的事実に基づく現実主義的な分析レンズであり、特定の政策への賛否を
  主張するものではない。なお、分析文はニュースごとに具体的な内容と結びつけて
  生成され、同一の定型文が繰り返し付与されることはない。
- **箴言の出典**: 全てパブリックドメインの原典からの引用(`data/quotes.json`)。
  伊語原文と日本語意訳を併記。

## ファイル構成

```
machiavelli_bot/
├── config.yaml            # 情報源・スコアリング重み・投稿モードの設定
├── data/quotes.json        # マキャベリ箴言データベース(テーマ別)
├── geopolitical_scorer.py  # ニュースの地政学的重要度スコアリング & テーマ分類
├── news_fetcher.py         # RSSからニュース取得(要ネット接続)
├── machiavelli_engine.py   # つぶやき文生成(template / LLMの2モード)
├── generate_feed.py        # ★サイト埋め込み用: docs/feed.json を更新するスクリプト
├── docs/                   # ★GitHub Pagesで公開するディレクトリ
│   ├── feed.json            # 生成済みつぶやきの配信用JSON(サンプル同梱)
│   ├── widget.js             # 埋め込みウィジェット本体
│   ├── widget.css            # ウィジェットのスタイル
│   └── index.html            # 単体プレビュー用ページ
├── .github/workflows/tweet.yml  # ★GitHub Actionsによる定期実行(頻度=cron)
├── bot.py                  # X(Twitter)へ直接投稿する場合の本体(任意)
├── demo.py                 # ネット接続不要のデモ(サンプル実データで動作確認済み)
└── requirements.txt
```

## 🌐 使い方(推奨): ウェブサイトへの埋め込み

X(Twitter)へは投稿せず、**あなたのウェブサイト内につぶやきを表示する**ための仕組みです。
裏側で GitHub Actions(無料)が定期的にニュースを分析して `docs/feed.json` を更新し、
表側で軽量な JavaScript ウィジェットがそれを読み込んで表示します。サーバー費用は一切かかりません。

### 全体像

```
[GitHub Actions が定期実行]
   news_fetcher.py → geopolitical_scorer.py → machiavelli_engine.py
        ↓
   docs/feed.json を更新して自動コミット
        ↓
[GitHub Pages が feed.json を公開]
        ↓
[WordPressページに貼った widget.js が feed.json を取得して表示]
```

### 手順1: GitHubにリポジトリを作る

1. https://github.com でアカウントを作成(無料)
2. 右上の「+」→「New repository」。名前は何でも良い(例: `machiavelli-widget`)。Public を選択
3. 解凍済みの `machiavelli_bot` フォルダの中身一式を、そのリポジトリにアップロード
   (GitHubの「Add file」→「Upload files」からドラッグ&ドロップで可能。
   `.github` フォルダも忘れずに含めてください)
4. 「Commit changes」

### 手順2: GitHub Pages を有効化する

1. リポジトリの「Settings」タブ →左メニュー「Pages」
2. 「Source」を `Deploy from a branch` にし、Branch を `main` / フォルダを `/docs` に設定して Save
3. 数分待つと、ページ上部に公開URLが表示される
   (例: `https://あなたのユーザー名.github.io/machiavelli-widget/`)
   **このURLを控えてください。**手順4で使います。

### 手順3(任意・推奨): より自然な文章にするAPIキーを設定

1. リポジトリの「Settings」→「Secrets and variables」→「Actions」
2. 「New repository secret」
   - Name: `ANTHROPIC_API_KEY`
   - Secret: あなたのAnthropic APIキー
3. 設定しない場合は定型合成モードで動作します(それでも問題なく機能します)

### 手順4: 初回実行を試す

1. リポジトリの「Actions」タブを開く
2. 「Update Machiavelli Feed」ワークフローを選択 →「Run workflow」で手動実行
3. 数十秒〜数分後、`docs/feed.json` が更新されコミットされていれば成功
4. 手順2で控えたURLに `/feed.json` を付けてブラウザでアクセスし、
   内容が表示されるか確認(例: `https://あなたのユーザー名.github.io/machiavelli-widget/feed.json`)

### 手順5: WordPressの About Us ページに埋め込む

1. WordPress管理画面 →「固定ページ」→ 該当ページ(About Us)を編集
2. ブロックエディタで「+」→「カスタムHTML」ブロックを追加
3. 以下をそのまま貼り付ける(あなたのリポジトリ `texocorp/machiavelli-widget` のURLで確定済みです)

```html
<div style="position:relative; max-width:640px; margin:0 auto;">
  <img src="https://commons.wikimedia.org/wiki/Special:FilePath/Portrait_of_Niccol%C3%B2_Machiavelli_by_Santi_di_Tito.jpg"
       alt=""
       style="position:absolute; top:0; left:50%; transform:translateX(-50%);
              width:60%; max-width:380px; opacity:0.10; filter:grayscale(100%);
              pointer-events:none; z-index:0; user-select:none;">
  <div id="machiavelli-tweets" style="position:relative; z-index:1;"></div>
</div>
<link rel="stylesheet" href="https://texocorp.github.io/machiavelli-widget/widget.css">
<script
  src="https://texocorp.github.io/machiavelli-widget/widget.js"
  data-feed="https://texocorp.github.io/machiavelli-widget/feed.json"
  data-target="machiavelli-tweets"
  data-count="5"
  data-refresh="600000">
</script>
```

4. 「更新」または「公開」を押す
5. ページを表示し、サンプルのつぶやき2件(`docs/feed.json` に同梱)と、上部にうっすらとマキャベリの肖像画が表示されれば成功です

#### 肖像画(透かし)について

以前はCSSファイル側で自動的に背景表示させる方式でしたが、WordPressのテーマ側の
スタイルと干渉して表示されない事例があったため、**上記のように `<img>` タグを
直接HTMLに書き込む方式に変更しました。** この方式であれば、表示の有無や位置を
このHTML自体を見て直接確認・調整できます。

- 画像は、サンティ・ディ・ティート筆《ニッコロ・マキャヴェッリの肖像》
  (16世紀後半、フィレンツェ ヴェッキオ宮殿蔵、パブリックドメイン、
  出典: [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Portrait_of_Niccol%C3%B2_Machiavelli_by_Santi_di_Tito.jpg))
- **濃さを変えたい場合**: `style="..."` の中の `opacity:0.10;` の数値を変更(大きいほど濃く表示される。0〜1の範囲)
- **大きさ・位置を変えたい場合**: 同じく `width:60%;` や `top:0;` の数値を調整
- **表示されない場合の確認方法**: 上記コードのうち `<img ...>` の行だけを
  別の空のカスタムHTMLブロックに単体で貼り付けてみてください。それでも
  画像が表示されない場合は、WordPressのセキュリティプラグイン等が
  外部画像の読み込みをブロックしている可能性があります

⚠️ 重要: `<img>` タグは、必ず `<div id="machiavelli-tweets">` の**外側(兄弟要素)**に
置いてください。内側に置くと、つぶやきウィジェットが更新されるたびに
画像ごと消えてしまいます(上記のコードは既にこの点を考慮した配置になっています)。

### つぶやきの頻度を調整する

**新しい分析が生成される頻度**は `.github/workflows/tweet.yml` の `cron` で決まります
(GitHub Actionsの都合上、UTC基準で指定します。日本時間 = UTC + 9時間)。

```yaml
schedule:
  - cron: "0 */3 * * *"   # 3時間おき(既定)
```

よく使う例:

| 頻度 | cron |
|---|---|
| 1時間おき | `"0 * * * *"` |
| 3時間おき(既定) | `"0 */3 * * *"` |
| 6時間おき | `"0 */6 * * *"` |
| 1日1回(日本時間 朝9時) | `"0 0 * * *"` |

変更後、リポジトリにコミットするだけで反映されます(再デプロイ不要)。

**表示側の自動更新間隔**は埋め込みコードの `data-refresh`(ミリ秒)で調整します。
既定は `600000`(10分)。ページを開いている間、この間隔で `feed.json` を再取得して表示を更新します。

**1度に表示する件数**は `data-count` で調整します(既定5件)。

### 見た目のカスタマイズ

`docs/widget.css` を編集すれば、テクスオ様のサイトの雰囲気(文藝酒場風の落ち着いた配色)に
さらに合わせて調整できます。クラス名は全て `mcv-` で始まる名前空間にしてあるため、
WordPressテーマの既存スタイルと衝突しません。

背景のマキャベリの肖像画(透かし)は、`docs/widget.css` ではなく
**WordPress側に貼る埋め込みコードの `<img>` タグ**で直接指定する方式にしてあります。
詳細と調整方法は「手順5: WordPressの About Us ページに埋め込む」内の
「肖像画(透かし)について」を参照してください。

### つぶやきの文章を無料のローカルLLMで推敲する(Ollama)

外部の有料APIを使わず、GitHub Actionsの実行環境内だけで完結する
無料・独立のローカルLLM([Ollama](https://ollama.com))で、定型合成モードの
下書きを自然な文章に推敲する機能を組み込んであります。

`.github/workflows/tweet.yml` には既にOllamaのセットアップ手順
(インストール→起動→軽量モデル `qwen2.5:1.5b` の取得)が含まれており、
**追加設定なしでそのまま動作**します。生成の優先順位は:

```
1. Ollama(無料・ローカル、既定で最優先)
   ↓ 失敗時
2. Anthropic API(ANTHROPIC_API_KEY設定時のみ)
   ↓ 失敗時
3. 定型合成モード(必ず成功する最終フォールバック)
```

**使用モデルを変更したい場合**は、`.github/workflows/tweet.yml` 内の
`ollama pull qwen2.5:1.5b` と `OLLAMA_MODEL: "qwen2.5:1.5b"` の2箇所を、
Ollamaが対応する他の軽量モデル名(例: `gemma2:2b`, `llama3.2:1b` など)に
書き換えてください。モデルが大きいほど文章は洗練されますが、
GitHub Actions上でのダウンロード・生成時間は長くなります。

**ローカルPC上でOllamaを使う場合**(`bot.py` を手元で実行する場合など)は、
[Ollama公式サイト](https://ollama.com)からインストールし、
`ollama serve` を起動した状態で `ollama pull qwen2.5:1.5b` を実行しておけば、
同様に自動でOllama推敲モードが使われます。

---

## 任意: X(旧Twitter)へ実際に投稿する場合

上記のサイト埋め込み方式とは別に、`bot.py` を使えば実際にXへ投稿することもできます。

### 1. まずデモで動作確認(ネット接続不要)

```bash
python demo.py
```

台湾情勢・日中緊張・米中覇権競争に関する実際のニュース(2026年7月時点)を
サンプルとして、選別ロジックと文体を確認できます。

### 2. 本番運用: RSSから自動取得して1回だけ試す

```bash
python bot.py --once
```

`config.yaml` の `mode.dry_run: true` の間は実際には投稿されず、
`logs/tweets.jsonl` に生成結果が記録されるだけです。まずはここで
文体・選別精度を確認することを強く推奨します。

### 3. つぶやきの頻度を調整する

`config.yaml` の `schedule` セクションを編集するだけです。

```yaml
schedule:
  posting_interval_minutes: 180   # 数値を下げるほど頻繁に(最小30推奨)
  posts_per_day_cap: 6            # 1日の上限
  quiet_hours:
    start: "01:00"
    end: "06:00"
```

### 4. 常駐実行(自動でループ)

```bash
python bot.py
```

`posting_interval_minutes` ごとにニュースを取得し、重複していない
最重要ニュース1件を選んでつぶやきを生成します。サーバーや
`cron` / `systemd timer` / GitHub Actions のスケジュール実行に載せる形が
実運用向きです。

### 5. 実際にXへ投稿する

1. X Developer Portal でAPIキーを取得(Free/Basicプランでも投稿は可能)
2. 環境変数を設定:
   ```bash
   export TWITTER_API_KEY=...
   export TWITTER_API_SECRET=...
   export TWITTER_ACCESS_TOKEN=...
   export TWITTER_ACCESS_SECRET=...
   ```
3. `config.yaml` の `mode.dry_run` を `false` に変更

### 6. より自然な生成文にする(任意)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

を設定すると、`bot.py` は自動的に Claude API 経由で個別具体的な分析文を
生成するモードに切り替わります(未設定の場合は定型合成モードにフォールバック)。
使用モデルは環境変数 `ANTHROPIC_MODEL` で指定可能です
(現行モデル名は https://docs.claude.com を参照してください)。

## 注意点

- RSSフィードのURLは例として一般的な国際ニュース源(Reuters, AP, NHK, 防衛省, 外務省)を
  設定していますが、実際に稼働させる際は各フィードの現在のURLと利用規約を
  ご自身で確認してください(配信元によりRSS仕様は変更されることがあります)。
- X(Twitter)のAPI利用規約・自動投稿ポリシーを遵守してください。
- 生成される分析はマキャベリという歴史的思想家の枠組みを模したフィクション的
  ペルソナによるものであり、実在の国・人物への断定的な事実主張ではなく、
  古典的現実主義の視座からの解釈的コメンタリーです。
