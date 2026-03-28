"""
論文検索 & Slack通知スクリプト
- 平日: members.json からメンバーを日替わりで選択、キーワード検索
- 日曜: Altmetric スコアが高い注目論文を紹介
- Claude Haiku で最重要論文を1本選択・日本語要約
- Slack に投稿した論文だけ seen_papers.json に記録
"""

import os
import re
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# ── 設定 ────────────────────────────────────────────────
MAX_RESULTS        = 10
DAYS_BACK          = 365
DAYS_BACK_IMPACT   = 30     # 日曜モード: 過去1ヶ月
IMPACT_FETCH       = 20     # 日曜モード: Altmetricスコアを取得する候補数
SLACK_WEBHOOK      = os.environ["SLACK_WEBHOOK_URL"]
ANTHROPIC_KEY      = os.environ["ANTHROPIC_API_KEY"]
MEMBERS_FILE       = "docs/members.json"
SEEN_FILE          = "seen_papers.json"
MAX_SEEN           = 5000

TARGET_JOURNALS = [
    "Nature", "Science", "Cell",
    "Nature Neuroscience", "Nature Human Behaviour", "Nature Medicine", "Nature Communications", 
    "Neuron", "Current Biology", "eLife",
    "PNAS", "Journal of Neuroscience",
    "Cell Reports", "Science Advances",
    "Nature Methods", "Nature Aging", "Nature Biotechnology",
]
# ────────────────────────────────────────────────────────


def is_sunday():
    return datetime.utcnow().weekday() == 6


def load_members():
    with open(MEMBERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def select_member(members):
    day_index = (datetime.utcnow() - datetime(2025, 1, 1)).days
    member = members[day_index % len(members)]
    print(f"本日の担当: {member['name']} (キーワード: {', '.join(member['keywords'])})")
    return member


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
    """キーワード付きPubMed検索（平日モード）"""
    if not keywords:
        print("キーワードが設定されていません。スキップします。")
        return []
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    kw_query      = " AND ".join(f'"{kw}"' for kw in keywords)
    journal_query = " OR ".join(f'"{j}"[Journal]' for j in TARGET_JOURNALS)
    date_query    = f'"{since}"[Date - Publication] : "3000"[Date - Publication]'
    full_query    = f"({kw_query}) AND ({journal_query}) AND ({date_query})"

    search_params = urllib.parse.urlencode({
        "db": "pubmed", "term": full_query,
        "retmax": max_results, "retmode": "json", "sort": "pub+date",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        ids = json.loads(resp.read())["esearchresult"]["idlist"]

    print(f"PubMed: {len(ids)} 件ヒット")
    if not ids:
        return []
    return _fetch_pubmed_details(ids)


def fetch_pubmed_impact(days_back, max_results):
    """キーワードなし・ターゲットジャーナル新着（日曜モード）"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    journal_query = " OR ".join(f'"{j}"[Journal]' for j in TARGET_JOURNALS)
    date_query    = f'"{since}"[Date - Publication] : "3000"[Date - Publication]'
    full_query    = f"({journal_query}) AND ({date_query})"

    search_params = urllib.parse.urlencode({
        "db": "pubmed", "term": full_query,
        "retmax": max_results, "retmode": "json", "sort": "pub+date",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        ids = json.loads(resp.read())["esearchresult"]["idlist"]

    print(f"PubMed (インパクトモード): {len(ids)} 件ヒット")
    if not ids:
        return []
    return _fetch_pubmed_details(ids)


def _fetch_pubmed_details(ids):
    """PubMedのIDリストから論文詳細を取得する"""
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
            "pmid":     pmid,
            "title":    title_el.text    if title_el   is not None else "No title",
            "authors":  author_str,
            "journal":  journal_el.text  if journal_el is not None else "",
            "year":     (year_el.text or "")[:4] if year_el is not None else "",
            "abstract": abs_el.text      if abs_el     is not None else "",
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
                "pmid":     None,
                "title":    item.get("title", "No title"),
                "authors":  item.get("authors", ""),
                "journal":  "bioRxiv (preprint)",
                "year":     date[:4] if date else "",
                "abstract": item.get("abstract", ""),
                "url":      f"https://www.biorxiv.org/content/{doi}",
                "source":   "bioRxiv",
            })
    print(f"bioRxiv: {len(papers[:max_results])} 件ヒット")
    return papers[:max_results]


def get_altmetric_score(pmid):
    """Altmetric APIでスコアを取得する（失敗時は0）"""
    import time
    try:
        url = f"https://api.altmetric.com/v1/pmid/{pmid}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        score = data.get("score", 0)
        time.sleep(0.5)  # レートリミット対策
        return float(score)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            pass  # Altmetricに未登録（よくある）
        else:
            print(f"  Altmetric HTTPエラー {e.code} (pmid={pmid})")
        return 0.0
    except Exception as e:
        print(f"  Altmetric エラー: {e} (pmid={pmid})")
        return 0.0


def fetch_impact_papers(seen):
    """日曜モード: Altmetricスコアが高い論文を取得する"""
    candidates = fetch_pubmed_impact(DAYS_BACK_IMPACT, IMPACT_FETCH)
    new_papers  = [p for p in candidates if p["id"] not in seen]

    print(f"Altmetricスコアを取得中（{len(new_papers)} 件）...")
    for p in new_papers:
        if p["pmid"]:
            p["altmetric_score"] = get_altmetric_score(p["pmid"])
            print(f"  {p['altmetric_score']:.0f} — {p['title'][:50]}...")
        else:
            p["altmetric_score"] = 0.0

    new_papers.sort(key=lambda x: x["altmetric_score"], reverse=True)
    return new_papers


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
    lines = []
    for i, p in enumerate(papers):
        snippet = p["abstract"][:300].replace("\n", " ")
        lines.append(f"{i+1}. {p['title']} / {snippet}...")
    keyword_str = " / ".join(keywords)
    prompt = (
        f"以下の論文リストから、'{keyword_str}' の研究者にとって"
        "最も重要・新規性が高い論文を1本選んでください。"
        "番号だけを答えてください（例: 3）。\n\n"
        + "\n".join(lines)
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


def summarize_with_claude(title, abstract, context):
    if not abstract:
        return "（アブストラクトなし）"
    prompt = (
        f"以下の論文を、{context}向けに"
        "日本語で3文以内で要約してください。専門用語はそのまま使ってください。\n\n"
        f"タイトル: {title}\n\nアブストラクト: {abstract}"
    )
    try:
        return call_claude(prompt, max_tokens=300)
    except Exception as e:
        print(f"要約エラー: {e}")
        return "（要約失敗）"


def post_to_slack(header_text, sub_text, paper):
    author_line = f"\n_{paper['authors']}_" if paper.get("authors") else ""
    meta = []
    if paper.get("journal"):
        meta.append(paper["journal"])
    if paper.get("year"):
        meta.append(paper["year"])
    if paper.get("altmetric_score") and paper["altmetric_score"] > 0:
        meta.append(f"Altmetric {paper['altmetric_score']:.0f}")
    meta_line = f"\n`{'  |  '.join(meta)}`" if meta else f"\n`{paper['source']}`"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": sub_text}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": (
                f"*<{paper['url']}|{paper['title']}>*{author_line}"
                f"{meta_line}\n{paper.get('summary', '')}"
            )}},
        {"type": "divider"},
    ]

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()
    print("Slack に投稿しました")


def post_no_papers_to_slack(text):
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    seen  = load_seen()
    print(f"既出論文: {len(seen)} 件")

    # ── 日曜モード: Altmetric 注目論文 ──────────────────
    if True: #is_sunday():
        print("🌟 日曜インパクトモード")
        papers = fetch_impact_papers(seen)

        if not papers:
            post_no_papers_to_slack(f"📭 {today} 今週は注目論文なし（インパクトモード）")
            return

        # Altmetricスコア上位5件からClaudeが最終選択
        top5 = papers[:5]
        best = select_best_paper(top5, ["neuroscience", "life science"])
        best["summary"] = summarize_with_claude(
            best["title"], best["abstract"],
            "神経科学・生命科学の研究者"
        )

        score_str = f"Altmetric {best['altmetric_score']:.0f}" if best.get("altmetric_score") else ""
        post_to_slack(
            f"🌟 今週の注目論文 {today}",
            f"ターゲットジャーナルの中で今週最も注目された論文です。{score_str}",
            best,
        )

    # ── 平日モード: メンバーキーワード検索 ──────────────
    else:
        members  = load_members()
        member   = select_member(members)
        keywords = member["keywords"]

        print("論文を検索中...")
        candidates  = fetch_pubmed(keywords, DAYS_BACK, MAX_RESULTS)
        candidates += fetch_biorxiv(keywords, DAYS_BACK, MAX_RESULTS)

        new_papers = [p for p in candidates if p["id"] not in seen]
        print(f"新着: {len(new_papers)} 件（既出 {len(candidates) - len(new_papers)} 件をスキップ）")

        if not new_papers:
            print("本日は新着論文なし")
            keyword_str = ", ".join(keywords)
            post_no_papers_to_slack(
                f"📭 {today} 新着論文なし（担当: {f'<@{member["slack_id"]}>' if member.get('slack_id') else member['name']} / キーワード: {keyword_str}）"
            )
            return

        print(f"{len(new_papers)} 件から最重要論文を選択中...")
        best = select_best_paper(new_papers, keywords)

        print("要約中...")
        best["summary"] = summarize_with_claude(
            best["title"], best["abstract"],
            f"'{' / '.join(keywords)}' を研究するニューロサイエンス研究者"
        )

        post_to_slack(
            f"📄 論文アップデート {today}",
            f"For {member['name']} {f'<@{member["slack_id"]}>' if member.get('slack_id') else ''}　Keywords: {' / '.join(keywords)}",
            best,
        )

    seen.add(best["id"])
    save_seen(seen)
    print(f"seen_papers.json を更新しました（合計 {len(seen)} 件）")


if __name__ == "__main__":
    main()
