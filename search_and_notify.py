"""
論文検索 & Slack通知スクリプト
- PubMed / bioRxiv から "spatial navigation" 論文を検索
- Claude API で要約
- Slack に投稿
"""

import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
KEYWORDS       = ["spatial navigation"]          # 検索キーワード
MAX_RESULTS    = 5                               # 1回あたりの最大件数
DAYS_BACK      = 1                               # 何日前までの論文を対象にするか
SLACK_WEBHOOK  = os.environ["SLACK_WEBHOOK_URL"] # GitHub Secrets から取得
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"] # GitHub Secrets から取得
# ────────────────────────────────────────────────────────


def fetch_pubmed(keywords: list[str], days_back: int, max_results: int) -> list[dict]:
    """PubMed から論文を取得する"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = " AND ".join(f'"{kw}"' for kw in keywords)
    query += f' AND ("{since}"[Date - Publication] : "3000"[Date - Publication])'

    # Step 1: IDリストを取得
    search_params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "pub+date",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        ids = json.loads(resp.read())["esearchresult"]["idlist"]

    if not ids:
        return []

    # Step 2: 詳細を取得
    fetch_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        root = ET.fromstring(resp.read())

    papers = []
    for article in root.findall(".//PubmedArticle"):
        title_el  = article.find(".//ArticleTitle")
        abs_el    = article.find(".//AbstractText")
        pmid_el   = article.find(".//PMID")
        title  = title_el.text  if title_el  is not None else "No title"
        abstract = abs_el.text  if abs_el    is not None else ""
        pmid   = pmid_el.text   if pmid_el   is not None else ""
        papers.append({
            "title":    title,
            "abstract": abstract,
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":   "PubMed",
        })
    return papers


def fetch_biorxiv(keywords: list[str], days_back: int, max_results: int) -> list[dict]:
    """bioRxiv から論文を取得する"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # 正しいAPI形式: /details/biorxiv/YYYY-MM-DD/YYYY-MM-DD/cursor/json
    url = f"https://api.biorxiv.org/details/biorxiv/{since}/{today}/0/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ bioRxiv API エラー: {e}")
        return []

    papers = []
    for item in data.get("collection", []):
        text = (item.get("title", "") + " " + item.get("abstract", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            doi = item.get("doi", "")
            papers.append({
                "title":    item.get("title", "No title"),
                "abstract": item.get("abstract", ""),
                "url":      f"https://www.biorxiv.org/content/{doi}",
                "source":   "bioRxiv",
            })
    return papers[:max_results]


def summarize_with_claude(title: str, abstract: str) -> str:
    """Claude API でアブストラクトを日本語要約する"""
    if not abstract:
        return "（アブストラクトなし）"

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 300,
        "messages": [{
            "role": "user",
            "content": (
                "以下の論文のアブストラクトを、認知地図・空間ナビゲーション研究者向けに"
                "日本語で3〜5文で要約してください。専門用語はそのまま使って構いません。\n\n"
                f"タイトル: {title}\n\nアブストラクト: {abstract}"
            ),
        }],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"].strip()


def post_to_slack(papers: list[dict]) -> None:
    """Slack に投稿する"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    keyword_str = " / ".join(KEYWORDS)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📄 論文アップデート {today}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"キーワード: *{keyword_str}*  |  {len(papers)} 件"},
        },
        {"type": "divider"},
    ]

    for i, p in enumerate(papers, 1):
        blocks += [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}. <{p['url']}|{p['title']}>*\n_{p['source']}_",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": p["summary"]},
            },
            {"type": "divider"},
        ]

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()
    print(f"✅ Slack に {len(papers)} 件投稿しました")


def main():
    print("🔍 論文を検索中...")
    papers = []
    papers += fetch_pubmed(KEYWORDS, DAYS_BACK, MAX_RESULTS)
    papers += fetch_biorxiv(KEYWORDS, DAYS_BACK, MAX_RESULTS)

    if not papers:
        print("📭 本日は新着論文なし")
        # 新着なし通知を送る場合は以下をコメントアウト解除
        # post_to_slack_empty()
        return

    print(f"✨ {len(papers)} 件見つかりました。要約中...")
    for p in papers:
        p["summary"] = summarize_with_claude(p["title"], p["abstract"])
        print(f"  - {p['title'][:60]}...")

    post_to_slack(papers)


if __name__ == "__main__":
    main()
