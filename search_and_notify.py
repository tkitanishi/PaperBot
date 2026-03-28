"""
論文検索 & Slack通知スクリプト
- PubMed / bioRxiv から10本検索
- Claude Haiku で最重要論文を1本選択
- 選んだ論文を日本語要約して Slack に投稿
"""

import os
import re
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
KEYWORDS       = ["spatial navigation"]
MAX_RESULTS    = 10
DAYS_BACK      = 1
SLACK_WEBHOOK  = os.environ["SLACK_WEBHOOK_URL"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SEEN_FILE      = "seen_papers.json"
MAX_SEEN       = 2000
# ────────────────────────────────────────────────────────


def load_seen():
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_seen(seen):
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
        title_el   = article.find(".//ArticleTitle")
        pmid_el    = article.find(".//PMID")
        abs_el     = article.find(".//AbstractText")
        journal_el = article.find(".//Journal/Title")
        year_el    = article.find(".//PubDate/Year")
        if year_el is None:
            year_el = article.find(".//PubDate/MedlineDate")
        authors = article.findall(".//Author")
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
            "title":    title_el.text  if title_el   is not None else "No title",
            "authors":  author_str,
            "journal":  journal_el.text if journal_el is not None else "",
            "year":     (year_el.text[:4] if year_el is not None else ""),
            "abstract": abs_el.text    if abs_el     is not None else "",
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
            doi  = item.get("doi", "")
            date = item.get("date", "")
            papers.append({
                "id":       f"biorxiv_{doi}",
                "title":    item.get("title", "No title"),
                "authors":  item.get("authors", ""),
                "journal":  "bioRxiv (preprint)",
                "year":     date[:4] if date else "",
                "abstract": item.get("abstract", ""),
                "url":      f"https://www.biorxiv.org/content/{doi}",
                "source":   "bioRxiv",
            })
    return papers[:max_results]


def call_claude(prompt, max_tokens=50):
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
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


def select_best_paper(papers, keywords):
    """最も重要な論文を1本選ぶ"""
    lines = []
    for i, p in enumerate(papers):
        snippet = p["abstract"][:300].replace("\n", " ")
        lines.append(f"{i+1}. {p['title']} / {snippet}...")
    paper_list = "\n".join(lines)
    keyword_str = " / ".join(keywords)

    prompt = (
        f"以下の論文リストから、'{keyword_str}' の研究者にとって"
        "最も重要・新規性が高い論文を1本選んでください。"
        "番号だけを答えてください（例: 3）。\n\n"
        + paper_list
    )

    try:
        answer = call_claude(prompt, max_tokens=10)
        m = re.search(r"\d+", answer)
        idx = int(m.group()) - 1 if m else 0
        idx = max(0, min(idx, len(papers) - 1))
        print(f"選ばれた論文: {idx+1}番 「{papers[idx]['title'][:60]}」")
        return papers[idx]
    except Exception as e:
        print(f"選択エラー: {e} → 1番を使用")
        return papers[0]


def summarize_with_claude(title, abstract):
    """日本語要約"""
    if not abstract:
        return "（アブストラクトなし）"
    prompt = (
        "以下の論文を、空間ナビゲーション・認知地図の研究者向けに"
        "日本語で3文以内で要約してください。専門用語はそのまま使ってください。\n\n"
        f"タイトル: {title}\n\nアブストラクト: {abstract}"
    )
    try:
        return call_claude(prompt, max_tokens=300)
    except Exception as e:
        print(f"要約エラー: {e}")
        return "（要約失敗）"


def post_to_slack(papers):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    keyword_str = " / ".join(KEYWORDS)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📄 論文アップデート {today}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"キーワード: *{keyword_str}*"}},
        {"type": "divider"},
    ]

    for i, p in enumerate(papers, 1):
        author_line = f"\n_{p['authors']}_" if p.get("authors") else ""
        meta = []
        if p.get("journal"):
            meta.append(p["journal"])
        if p.get("year"):
            meta.append(p["year"])
        meta_line = f"\n`{'  |  '.join(meta)}`" if meta else f"\n`{p['source']}`"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. <{p['url']}|{p['title']}>*{author_line}"
                    f"{meta_line}\n{p.get('summary', '')}"
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
    print(f"Slack に投稿しました")


def main():
    seen = load_seen()
    print(f"既出論文: {len(seen)} 件")

    print("論文を検索中...")
    candidates = fetch_pubmed(KEYWORDS, DAYS_BACK, MAX_RESULTS)
    candidates += fetch_biorxiv(KEYWORDS, DAYS_BACK, MAX_RESULTS)

    new_papers = [p for p in candidates if p["id"] not in seen]
    print(f"新着: {len(new_papers)} 件（既出 {len(candidates) - len(new_papers)} 件をスキップ）")

    if not new_papers:
        print("本日は新着論文なし")
        return

    print(f"{len(new_papers)} 件から最重要論文を選択中...")
    best = select_best_paper(new_papers, KEYWORDS)

    print("要約中...")
    best["summary"] = summarize_with_claude(best["title"], best["abstract"])

    post_to_slack([best])

    # 選ばれなかった論文も含めて全て既出として記録
    seen.update(p["id"] for p in new_papers)
    save_seen(seen)
    print(f"seen_papers.json を更新しました（合計 {len(seen)} 件）")


if __name__ == "__main__":
    main()
