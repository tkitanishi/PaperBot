"""
論文検索 & Slack通知スクリプト
- PubMed / bioRxiv から "spatial navigation" 論文を検索
- タイトル＋リンクを Slack に投稿
"""

import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
KEYWORDS      = ["spatial navigation"]   # 検索キーワード
MAX_RESULTS   = 2                        # 1ソースあたりの最大件数
DAYS_BACK     = 1                        # 何日前までの論文を対象にするか
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
# ────────────────────────────────────────────────────────


def fetch_pubmed(keywords, days_back, max_results):
    """PubMed から論文を取得する"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = " AND ".join(f'"{kw}"' for kw in keywords)
    query += f' AND ("{since}"[Date - Publication] : "3000"[Date - Publication])'

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
        title_el = article.find(".//ArticleTitle")
        pmid_el  = article.find(".//PMID")
        authors  = article.findall(".//Author")
        author_names = []
        for a in authors[:3]:
            last = a.find("LastName")
            if last is not None:
                author_names.append(last.text)
        author_str = ", ".join(author_names)
        if len(authors) > 3:
            author_str += " et al."

        title = title_el.text if title_el is not None else "No title"
        pmid  = pmid_el.text  if pmid_el  is not None else ""
        papers.append({
            "title":   title,
            "authors": author_str,
            "url":     f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":  "PubMed",
        })
    return papers


def fetch_biorxiv(keywords, days_back, max_results):
    """bioRxiv から論文を取得する"""
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
                "title":   item.get("title", "No title"),
                "authors": item.get("authors", ""),
                "url":     f"https://www.biorxiv.org/content/{doi}",
                "source":  "bioRxiv",
            })
    return papers[:max_results]


def post_to_slack(papers):
    """Slack に投稿する"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    keyword_str = " / ".join(KEYWORDS)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Papers {today}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"Keywords: *{keyword_str}*  |  {len(papers)} papers"},
        },
        {"type": "divider"},
    ]

    for i, p in enumerate(papers, 1):
        author_line = f"\n_{p['authors']}_" if p.get("authors") else ""
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{i}. <{p['url']}|{p['title']}>*{author_line}\n`{p['source']}`",
            },
        })

    blocks.append({"type": "divider"})

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()
    print(f"Posted {len(papers)} papers to Slack")


def main():
    print("Searching papers...")
    papers = []
    papers += fetch_pubmed(KEYWORDS, DAYS_BACK, MAX_RESULTS)
    papers += fetch_biorxiv(KEYWORDS, DAYS_BACK, MAX_RESULTS)

    if not papers:
        print("No new papers today")
        return

    print(f"Found {len(papers)} papers. Posting to Slack...")
    post_to_slack(papers)


if __name__ == "__main__":
    main()
