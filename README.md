# 📄 論文Bot : PubMed / bioRxiv → Claude API → Slack

毎朝、メンバーごとのキーワードで新着論文を自動検索し、Claude Haiku で最重要論文を1本選んで日本語要約し、Slack にメンションつきで投稿するBot。**日曜日は Semantic Scholar の引用数をもとにした注目論文モードに切り替わります。**

---

## 動作イメージ

**月〜土曜日：メンバーキーワードモード**

```
毎朝9時（日本時間）
    ↓ GitHub Actions が自動起動
今日の担当メンバーを日替わりで選択（日曜日を除いた周期）
    ↓
PubMed（ターゲットジャーナル限定）/ bioRxiv をキーワードで検索
    ↓
既出論文を除外 → 最大10件から Claude Haiku が最重要論文を1本選択
    ↓
日本語要約 → 担当メンバーへのメンションつきでSlackに投稿
    ↓
seen_papers.json を更新（投稿した論文のみ記録）
```

```
📄 論文アップデート
For 田中 @tanaka　Keywords: spatial navigation / place cell

Obstacle coding in scene-selective cortices
Smith, Jones, Brown et al.
Nature Neuroscience  |  2026
海馬傍回と海馬がナビゲーション中の障害物符号化に関与することを示した。...
```

**日曜日：注目論文モード**

```
毎朝9時（日本時間）
    ↓ GitHub Actions が自動起動
ターゲットジャーナルの過去1ヶ月の新着を20件取得
    ↓
各論文の Semantic Scholar 引用数を取得
    ↓
引用数上位5件から Claude Haiku が最終選択
    ↓
日本語要約 → 「今週の注目論文」としてSlackに投稿
```

```
🌟 今週の注目論文
引用 47 件

A new mechanism for hippocampal memory consolidation
Smith, Jones et al.
Nature  |  2026  |  引用 47 件  |  影響力 12 件
記憶固定化における海馬の新たなメカニズムを発見した。...
```

---

## ファイル構成

```
your-repo/
├── search_and_notify.py            # メインスクリプト
├── seen_papers.json                # 投稿済み論文ID（自動生成）
├── .github/
│   └── workflows/
│       └── daily_paper_search.yml  # GitHub Actions スケジューラー
└── docs/
    ├── index.html                  # キーワード設定ページ（GitHub Pages）
    └── members.json                # メンバーとキーワードの設定ファイル
```

---

## セットアップ手順

### Step 1｜Slack Incoming Webhook を作成する

1. https://api.slack.com/apps を開く
2. **「Create New App」→「From scratch」** を選択
3. App名（例: `論文Bot`）とワークスペースを入力 → **「Create App」**
4. 左メニュー **「Incoming Webhooks」** を開き、**「Activate Incoming Webhooks」** を ON
5. **「Add New Webhook to Workspace」** → 投稿先チャンネルを選択
6. 生成された Webhook URL をコピー

投稿先チャンネルを変更したい場合は、同画面で新しいWebhookを追加し、GitHub SecretのURLを差し替えます。

### Step 2｜Anthropic API キーを取得する

1. https://console.anthropic.com にアクセス
2. **「Plans & Billing」→「Buy credits」** で $5 以上購入
3. **「API Keys」→「Create Key」** でAPIキーを作成してコピー

費用の目安は約 $0.001/日（$5で約10年分）。

### Step 3｜GitHub リポジトリを作成する

1. GitHub で新しいリポジトリを作成（Public でも Private でも可）
2. 以下のファイルをアップロード：

```
search_and_notify.py
.github/workflows/daily_paper_search.yml
docs/index.html
docs/members.json
```

> **注意**: `.github/workflows/` フォルダはWeb画面で「Add file → Create new file」のファイル名欄に `.github/workflows/daily_paper_search.yml` と入力すると自動で作成されます。

### Step 4｜GitHub Secrets に登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録：

| Secret 名 | 値 |
|---|---|
| `SLACK_WEBHOOK_URL` | Step 1 でコピーした Webhook URL |
| `ANTHROPIC_API_KEY` | Step 2 でコピーした API キー |

### Step 5｜Actionsの書き込み権限を有効化する

リポジトリの **Settings → Actions → General → Workflow permissions**
→ **「Read and write permissions」** を選択 → Save

（`seen_papers.json` の自動コミットに必要）

### Step 6｜GitHub Pages を有効化する（任意）

メンバーがキーワードを自分で編集できるWebページを公開する場合：

1. リポジトリの **Settings → Pages**
2. Source: `Deploy from a branch`
3. Branch: `main`、フォルダ: `/docs` → **Save**
4. 数分後に `https://ユーザー名.github.io/リポジトリ名/` でアクセス可能

このページでキーワードを編集 → JSONをコピー → GitHubの `docs/members.json` に貼り付けてCommitするだけで設定を更新できます。

### Step 7｜動作確認

1. リポジトリの **Actions タブ** を開く
2. **「Daily Paper Search」** を選択
3. **「Run workflow」** で手動実行
4. Slack に投稿が届けば完了！

**日曜モードのテスト方法：** `search_and_notify.py` の `if is_sunday():` を一時的に `if True:` に書き換えてRun workflowすると動作確認できます。テスト後は必ず `is_sunday()` に戻してください。

---

## メンバー設定（docs/members.json）

各メンバーの名前・Slack ID・キーワードを設定します。

### 方法A：キーワード設定ページを使う（推奨）

GitHub Pages を有効化すると `https://ユーザー名.github.io/リポジトリ名/` にアクセスできます。

1. ページ上でメンバーの追加・削除、キーワードの編集ができる
2. 編集が終わったら **「コピー」** ボタンを押す
3. GitHubの `docs/members.json` を開いて全選択 → 貼り付け → **Commit changes**

JSONの書き方を知らなくてもGUIで操作できるのでメンバー全員が自分でキーワードを更新できます。

### 方法B：JSONを直接編集する

GitHubで `docs/members.json` を直接編集します：

```json
[
  {
    "name": "田中",
    "slack_id": "U01XXXXXXX",
    "keywords": ["spatial navigation", "place cell"]
  },
  {
    "name": "鈴木",
    "slack_id": "U02XXXXXXX",
    "keywords": ["working memory", "prefrontal cortex"]
  }
]
```

**Slack IDの調べ方：** Slackでプロフィールを開く → 「…」→「メンバーIDをコピー」

ローテーションは日曜日を除いた日数ベースで自動的に決まります（3人なら6日周期）。

---

## カスタマイズ

`search_and_notify.py` の設定欄を編集します：

```python
MAX_RESULTS       = 10    # キーワードモードの検索件数
DAYS_BACK         = 365   # キーワードモードの対象期間
DAYS_BACK_IMPACT  = 30    # 日曜モードの対象期間（過去1ヶ月）
IMPACT_FETCH      = 20    # 日曜モードで引用数を取得する候補数

TARGET_JOURNALS = [
    "Nature", "Science", "Cell",
    "Nature Neuroscience", "Nature Human Behaviour", "Nature Medicine", "Nature Communications",
    "Neuron", "Current Biology", "eLife",
    "PNAS", "Journal of Neuroscience",
    "Cell Reports", "Science Advances",
    "Nature Methods", "Nature Aging", "Nature Biotechnology",
]
```

投稿時間を変えたい場合は `daily_paper_search.yml` の cron 式を変更：

```yaml
- cron: "0 0 * * *"    # UTC 00:00 = JST 09:00（デフォルト）
- cron: "0 22 * * *"   # UTC 22:00 = JST 07:00（朝7時に変える場合）
```

日曜モードの曜日を変えたい場合は `is_sunday()` 関数を修正：

```python
def is_sunday():
    return datetime.utcnow().weekday() == 6  # 0=月, 1=火, ..., 6=日
```

---

## 費用の目安

| サービス | 費用 |
|---|---|
| GitHub Actions | 無料（月2,000分まで） |
| PubMed API | 無料 |
| bioRxiv API | 無料 |
| Semantic Scholar API | 無料 |
| Claude Haiku API | 約 $0.001 / 日（$5で約10年分） |

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Actionsタブにワークフローが出ない | YAMLのパスが違う | `.github/workflows/` に置く |
| `credit balance is too low` | APIクレジット不足 | console.anthropic.com で購入 |
| `本日は新着論文なし` | 該当論文がなかった | 正常動作。`DAYS_BACK` を増やすか `TARGET_JOURNALS` を広げる |
| bioRxiv タイムアウト | bioRxiv API が不安定 | 一時的なもの。PubMedの結果は投稿される |
| seen_papers.jsonのコミットが失敗 | 書き込み権限がない | Settings → Actions → General → Read and write permissions に変更 |
| 日曜モードで引用数が全部0 | Semantic Scholar に未登録 | 新しすぎる論文はデータがないことがある。引用数なしでClaudeが選択するので動作は継続 |
