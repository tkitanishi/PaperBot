# 📄 論文Bot — PubMed / bioRxiv → Slack

毎朝、指定キーワードに関する新着論文を自動検索し、Claude Haiku で日本語要約して Slack に投稿するBot。

---

## 完成イメージ

```
毎朝9時（日本時間）
    ↓ GitHub Actions が自動起動
PubMed / bioRxiv を検索
    ↓
Claude Haiku で日本語要約
    ↓
Slack に投稿
```

Slackにはこのような形式で届きます：

```
📄 論文アップデート 2026-03-28
キーワード: spatial navigation | 5件

1. Obstacle coding in scene-selective cortices
   Smith, Jones, Brown et al.
   PubMed
   海馬傍回と海馬がナビゲーション中の障害物符号化に関与することを示した。
   fMRI実験により、障害物の位置と形状が...

---
```

---

## ファイル構成

```
your-repo/
├── search_and_notify.py            # メインスクリプト
├── README.md                       # このファイル
└── .github/
    └── workflows/
        └── daily_paper_search.yml  # GitHub Actions スケジューラー
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
   ```
   https://hooks.slack.com/services/XXXXX/YYYYY/ZZZZZ
   ```

### Step 2｜Anthropic API キーを取得する

1. https://console.anthropic.com にアクセス
2. **「Plans & Billing」→「Buy credits」** で $5 以上購入
3. **「API Keys」→「Create Key」** でAPIキーを作成してコピー

### Step 3｜GitHub リポジトリを作成する

1. GitHub で新しいリポジトリを作成（Private でOK）
2. 以下の3ファイルをアップロード：
   - `search_and_notify.py`
   - `.github/workflows/daily_paper_search.yml`
   - `README.md`

> **注意**: `.github/workflows/` フォルダはGitHubのWeb画面で  
> 「Add file → Create new file」でファイル名に `.github/workflows/daily_paper_search.yml` と  
> 入力すると自動で作成されます。

### Step 4｜GitHub Secrets に登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録：

| Secret 名 | 値 |
|---|---|
| `SLACK_WEBHOOK_URL` | Step 1 でコピーした Webhook URL |
| `ANTHROPIC_API_KEY` | Step 2 でコピーした API キー |

### Step 5｜動作確認

1. リポジトリの **Actions タブ** を開く
2. **「Daily Paper Search」** を選択
3. **「Run workflow」** で手動実行
4. Slack に投稿が届けば完了！

---

## カスタマイズ

`search_and_notify.py` の設定欄を編集するだけです：

```python
# ── 設定 ──────────────────────────────────────
KEYWORDS      = ["spatial navigation"]   # ← キーワードを追加・変更
MAX_RESULTS   = 5                        # ← 1ソースあたりの最大件数
DAYS_BACK     = 1                        # ← 何日前までの論文を対象にするか
```

### キーワードを増やす例

```python
KEYWORDS = ["spatial navigation", "hippocampus", "place cell", "cognitive map"]
```

### 投稿時間を変える

`daily_paper_search.yml` の `cron` 式を変更します（UTC基準）：

```yaml
- cron: "0 0 * * *"    # UTC 00:00 = JST 09:00（デフォルト）
- cron: "0 22 * * *"   # UTC 22:00 = JST 07:00（朝7時に変える場合）
- cron: "0 1 * * 1"    # 毎週月曜 JST 10:00（週1回にする場合）
```

---

## 費用の目安

| サービス | 費用 |
|---|---|
| GitHub Actions | 無料（月2,000分まで） |
| PubMed API | 無料 |
| bioRxiv API | 無料 |
| Claude Haiku API | 約 $0.001 / 日（$5で約10年分） |

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Actions タブにワークフローが出ない | YAMLのパスが違う | `.github/workflows/` に置く |
| `credit balance is too low` | APIクレジット不足 | console.anthropic.com で購入 |
| `本日は新着論文なし` | 該当論文がなかった | 正常動作。キーワードを見直す |
| bioRxiv タイムアウト | bioRxiv API が不安定 | 一時的なもの。翌日は復旧することが多い |
