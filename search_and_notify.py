"""
論文検索 & Slack通知スクリプト
- PubMed / bioRxiv から論文を検索
- Hugging Face API（無料）で日本語要約
- Slack に投稿
"""

import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
KEYWORDS      = ["spatial navigation"]
MAX_RESULTS   = 5
DAYS_BACK     = 1
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
HF_KEY        = os.environ["HF_API_KEY"]
HF_MODEL      = "mistralai/Mistral-7B-Instruct-v0.2"
# ────────────────────────────────────────────────────────


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

        papers.append({
            "title":    title_el.text if title_el is not None else "No title",
            "authors":  author_str,
            "abstract": abs_el.text   if abs_el   is not None else "",
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid_el.text if pmid_el is not None else ''}/",
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
                "title":    item.get("title", "No title"),
                "authors":  item.get("authors", ""),
                "abstract": item.get("abstract", ""),
                "url":      f"https://www.biorxiv.org/content/{doi}",
                "source":   "bioRxiv",
            })
    return papers[:max_results]


def summarize_with_hf(title, abstract):
    if not abstract:
        return "（アブストラクトなし）"

    prompt = (
        f"<s>[INST] Summarize the following paper in Japanese in 3 sentences for a spatial navigation researcher. "
        f"Keep technical terms as-is.\n\nTitle: {title}\n\nAbstract: {abstract} [/INST]"
    )

    payload = json.dumps({
        "inputs": prompt,
        "parameters": {"max_new_tokens": 300, "return_full_text": False},
    }).encode()

    url = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {HF_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        if isinstance(result, list):
            return result[0].get("generated_text", "（要約失敗）").strip()
        return str(result)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HF API エラー {e.code}: {body}")
        return "（要約失敗）"
    except Exception as e:
        print(f"HF API エラー: {type(e).__name__}: {e}")
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
    print("論文を検索中...")
    papers = fetch_pubmed(KEYWORDS, DAYS_BACK, MAX_RESULTS)
    papers += fetch_biorxiv(KEYWORDS, DAYS_BACK, MAX_RESULTS)

    if not papers:
        print("本日は新着論文なし")
        return

    print(f"{len(papers)} 件見つかりました。要約中...")
    for p in papers:
        p["summary"] = summarize_with_hf(p["title"], p["abstract"])
        print(f"  完了: {p['title'][:60]}...")

    post_to_slack(papers)


if __name__ == "__main__":
    main()
