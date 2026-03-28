"""
論文検索 & Slack通知スクリプト
- PubMed / bioRxiv から論文を検索
- 既出論文をスキップ（seen_papers.json で管理）
- Claude Haiku で日本語要約
- Slack に投稿
"""

import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
KEYWORDS       = ["spatial navigation"]
MAX_RESULTS    = 1
DAYS_BACK      = 1
SLACK_WEBHOOK  = os.environ["SLACK_WEBHOOK_URL"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SEEN_FILE      = "seen_papers.json"   # 既出論文IDを保存するファイル
MAX_SEEN       = 2000                 # 保存する最大件数（古いものは自動削除）
# ────────────────────────────────────────────────────────


def load_seen():
    """既出論文IDのセットを読み込む"""
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_seen(seen: set):
    """既出論文IDを保存する（古いものは削除）"""
    seen_list = list(seen)
    if len(seen_list) > MAX_SEEN:
        seen_list = seen_list[-MAX_SEEN:]
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_list, f)


def fetch_pubmed(keywords, days_back, max_results):
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = " AND ".join(f'"{kw}"' for kw in keywords)
    query += f' AND ("{since}"[Date - Publication] : "3000"[Date - Publication])'

    search_params = urllib.parse.urlencode({
        "db": "pubmed", "term": query,
        "retmax": max_results, "retmode": "json", "sort": "pub+date",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        ids = json.loads(resp.read())["esearchresult"]["idlist"]

    if not ids:
        return []

    fetch_params = urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        root = ET.fromstring(resp.read())

    papers = []
    for article in root.findall(".//PubmedArticle"):
        title_el = article.find(".//ArticleTitle")
        pmid_el  = article.find(".//PMID")
        abs_el   = article.find(".//AbstractText")
        authors  = article.findall(".//Author")
        author_names = []
        for a in authors[:3]:
            last = a.find("LastName")
            if last is not None:
                author_names.append(last.text)
        author_str = ", ".join(author_names)
        if len(authors) > 3:
            author_str += " et al."

        pmid = pmid_el.text if pmid_el is not None else ""
        papers.append({
            "id":       f"pubmed_{pmid}",
            "title":    title_el.text if title_el is not None else "No title",
            "authors":  author_str,
            "abstract": abs_el.text   if abs_el   is not None else "",
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":   "PubMed",
        })
    return papers


def fetch_biorxiv(keywords, days_back, max_results):
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://api.biorxiv.org/details/biorxiv/{since}/{today}/0/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"bioRxiv API エラー: {e}")
        return []

    papers = []
    for item in data.get("collection", []):
        text = (item.get("title", "") + " " + item.get("abstract", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            doi = item.get("doi", "")
            papers.append({
                "id":       f"biorxiv_{doi}",
                "title":    item.get("title", "No title"),
                "authors":  item.get("authors", ""),
                "abstract": item.get("abstract", ""),
                "url":      f"https://www.biorxiv.org/content/{doi}",
                "source":   "bioRxiv",
            })
    return papers[:max_results]


def summarize_with_claude(title, abstract):
    if not abstract:
        return "（アブストラクトなし）"

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{
            "role": "user",
            "content": (
                "以下の論文を、空間ナビゲーション・認知地図の研究者向けに"
                "日本語で3文以内で要約してください。専門用語はそのまま使ってください。\n\n"
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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        print(f"Claude API エラー {e.code}: {e.read().decode()}")
        return "（要約失敗）"
    except Exception as e:
        print(f"Claude API エラー: {e}")
        return "（要約失敗）"


def post_to_slack(papers):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    keyword_str = " / ".join(KEYWORDS)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📄 論文アップデート {today}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"キーワード: *{keyword_str}*  |  {len(papers)} 件"}},
        {"type": "divider"},
    ]

    for i, p in enumerate(papers, 1):
        author_line = f"\n_{p['authors']}_" if p.get("authors") else ""
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. <{p['url']}|{p['title']}>*{author_line}\n"
                    f"`{p['source']}`\n{p.get('summary', '')}"
                ),
            },
        })
        blocks.append({"type": "divider"})

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()
    print(f"Slack に {len(papers)} 件投稿しました")


def main():
    seen = load_seen()
    print(f"既出論文: {len(seen)} 件")

    print("論文を検索中...")
    candidates = fetch_pubmed(KEYWORDS, DAYS_BACK, MAX_RESULTS)
    candidates += fetch_biorxiv(KEYWORDS, DAYS_BACK, MAX_RESULTS)

    # 既出をフィルタ
    new_papers = [p for p in candidates if p["id"] not in seen]
    print(f"新着: {len(new_papers)} 件（既出 {len(candidates) - len(new_papers)} 件をスキップ）")

    if not new_papers:
        print("本日は新着論文なし")
        return

    print("要約中...")
    for p in new_papers:
        p["summary"] = summarize_with_claude(p["title"], p["abstract"])
        print(f"  完了: {p['title'][:60]}...")

    post_to_slack(new_papers)

    # 投稿済みIDを保存
    seen.update(p["id"] for p in new_papers)
    save_seen(seen)
    print(f"seen_papers.json を更新しました（合計 {len(seen)} 件）")


if __name__ == "__main__":
    main()
