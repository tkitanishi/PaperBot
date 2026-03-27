# 📄 論文Bot — PubMed / bioRxiv → Slack

毎朝、`spatial navigation` に関する新着論文を自動検索し、Claude で日本語要約して Slack に投稿します。

---

## ファイル構成

```
your-repo/
├── search_and_notify.py            # メインスクリプト
└── .github/
    └── workflows/
        └── daily_paper_search.yml  # GitHub Actions スケジューラー
```

---

## セットアップ手順

### Step 1｜Slack Incoming Webhook を作成する

1. https://api.slack.com/apps を開く
2. **「Create New App」** → **「From scratch」** を選択
3. App Name（例: `論文Bot`）と投稿先ワークスペースを入力 → **「Create App」**
4. 左メニュー **「Incoming Webhooks」** を開く
5. **「Activate Incoming Webhooks」** を ON にする
6. 下部の **「Add New Webhook to Workspace」** をクリック
7. 投稿先チャンネルを選択 → **「許可する」**
8. 生成された **Webhook URL** をコピーしておく
   ```
   https://hooks.slack.com/services/XXXXX/YYYYY/ZZZZZ
   ```

---

### Step 2｜GitHub リポジトリを作る

1. GitHub で新しいリポジトリを作成（Private でOK）
2. 上記の2ファイルをそのままアップロード（またはclone→push）

---

### Step 3｜GitHub Secrets に API キーを登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録：

| Secret 名 | 値 |
|---|---|
| `SLACK_WEBHOOK_URL` | Step 1 でコピーした Webhook URL |
| `ANTHROPIC_API_KEY` | Anthropic の API キー（https://console.anthropic.com） |

---

### Step 4｜動作確認

1. GitHub リポジトリの **Actions タブ** を開く
2. **「Daily Paper Search」** ワークフローを選択
3. **「Run workflow」** ボタンで手動実行
4. Slack に投稿が届けば完了！

---

## カスタマイズ

`search_and_notify.py` の設定欄を変更するだけです：

```python
KEYWORDS     = ["spatial navigation", "hippocampus"]  # キーワード追加
MAX_RESULTS  = 5    # 1ソースあたりの最大件数
DAYS_BACK    = 1    # 何日前までの論文を対象にするか
```

投稿時間を変えたい場合は `daily_paper_search.yml` の cron 式を変更：

```yaml
- cron: "0 0 * * *"   # UTC 00:00 = JST 09:00
- cron: "0 22 * * *"  # UTC 22:00 = JST 07:00（朝7時に変える場合）
```

---

## 費用の目安

| サービス | 費用 |
|---|---|
| GitHub Actions | 無料（月2,000分まで） |
| PubMed API | 無料 |
| bioRxiv API | 無料 |
| Claude API（Sonnet） | 約 $0.003〜0.01 / 日 |
