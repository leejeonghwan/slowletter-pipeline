# -*- coding: utf-8 -*-
"""Incremental NAVER opinion columns update.

- Scans latest NAVER opinion column pages (page 1..N) and finds new articles
  compared to an existing raw CSV (from naver_opinion_columns.py output).
- For new items: parse article + run the same LLM extraction logic via
  naver_opinion_columns.py helpers.
- Writes raw_new CSV + report_new MD to ~/Downloads.

Usage:
  python3 naver_opinion_columns_incremental.py \
    --prev-raw ~/Downloads/opinion_columns_raw_20260221_20260222.csv \
    --scan-pages 3 \
    --max-new 40

Env:
  OPENAI_API_KEY required.
  OPENAI_MODEL optional (default: gpt-4o-mini).
"""

import argparse
import csv
import os
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

# Reuse existing pipeline helpers
import naver_opinion_columns as base


def http_get(url: str) -> str:
    r = requests.get(url, headers=base.HEADERS, timeout=base.REQ_TIMEOUT)
    r.raise_for_status()
    return r.text


def extract_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if "n.news.naver.com" in href and "/article/" in href:
            links.append(href)
        elif href.startswith("/article/"):
            links.append("https://n.news.naver.com" + href)
    # dedupe
    return list(dict.fromkeys(links))


def load_prev_urls(path: str) -> set:
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return { (row.get("naver_link") or "").strip() for row in reader if (row.get("naver_link") or "").strip() }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-raw", required=True)
    ap.add_argument("--scan-pages", type=int, default=3)
    ap.add_argument("--max-new", type=int, default=30)
    ap.add_argument("--within-hours", type=float, default=0.0, help="Only include items within last N hours (0=off)")
    ap.add_argument("--sleep", type=float, default=0.35)
    args = ap.parse_args()

    prev_urls = load_prev_urls(os.path.expanduser(args.prev_raw))

    now = datetime.now(timezone(timedelta(hours=9)))
    cutoff = None
    if args.within_hours and args.within_hours > 0:
        cutoff = now - timedelta(hours=float(args.within_hours))

    # Scan latest pages
    cand_links: List[str] = []
    for page in range(1, args.scan_pages + 1):
        url = "https://news.naver.com/opinion/column"
        if page > 1:
            url += f"?page={page}"
        html = http_get(url)
        cand_links.extend(extract_links(html))
        time.sleep(args.sleep)

    cand_links = list(dict.fromkeys(cand_links))

    new_cols: List[base.Column] = []
    for link in cand_links:
        if link in prev_urls:
            continue
        col = base.parse_naver_article(link)
        if not col:
            continue
        if col.press not in base.TARGET_PRESSES:
            continue
        # time filter
        if cutoff and col.date:
            try:
                d = datetime.fromisoformat(col.date.replace(" ", "T"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone(timedelta(hours=9)))
            except Exception:
                d = None
            if d and d < cutoff:
                continue

        new_cols.append(col)
        if len(new_cols) >= args.max_new:
            break

    suffix = now.strftime("_%Y%m%d_%H%M")
    out_dir = os.path.expanduser("~/Downloads")
    os.makedirs(out_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, f"opinion_columns_raw_incremental{suffix}.csv")
    report_path = os.path.join(out_dir, f"opinion_columns_report_incremental{suffix}.md")

    # Save raw
    with open(raw_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","press","author","title","naver_link","content"])
        w.writeheader()
        for c in new_cols:
            w.writerow({
                "date": c.date,
                "press": c.press,
                "author": c.author,
                "title": c.title,
                "naver_link": c.naver_link,
                "content": c.content,
            })

    # Analyze
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 필요합니다.")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = base.OpenAI(api_key=api_key)

    lines: List[str] = []
    lines.append("# [오피니언 칼럼 추가분] 네이버 오피니언 칼럼 (증분).\n")
    lines.append(f"- 기준 파일: {os.path.basename(args.prev_raw)}")
    lines.append(f"- 스캔 페이지: 1~{args.scan_pages}")
    if cutoff:
        lines.append(f"- 시간 필터: 최근 {args.within_hours}시간 (cutoff {cutoff.isoformat()})")
    lines.append(f"- 추가 칼럼: {len(new_cols)}건\n")

    for i, col in enumerate(new_cols, 1):
        lines.append("---\n")
        lines.append(f"## {i}. ({col.press}) {col.title}")
        if col.author:
            lines.append(f"- 필자: {col.author}")
        if col.date:
            lines.append(f"- 발행: {col.date}")
        lines.append(f"- 링크: {col.naver_link}\n")

        try:
            brief = base.analyze_column_llm(client, model, col)
        except Exception as e:
            lines.append(f"오류: {e}\n")
            continue

        claim = (brief.get("claim") or "").strip()
        quotes = brief.get("quotes") or []
        numbers = brief.get("numbers") or []

        if claim:
            lines.append(f"핵심 주장: {claim}\n")

        if numbers:
            lines.append("숫자/맥락:")
            for n in numbers[:5]:
                what = (n.get("what") or "").strip()
                sent = (n.get("sentence") or "").strip()
                if what and sent:
                    lines.append(f"- {what}: {sent}")
                elif sent:
                    lines.append(f"- {sent}")
            lines.append("")

        if quotes:
            lines.append("인용:")
            for q in quotes[:3]:
                if isinstance(q, dict):
                    speaker = (q.get("speaker") or "").strip()
                    sentence = (q.get("sentence") or "").strip()
                else:
                    speaker = ""
                    sentence = str(q).strip()
                if not sentence:
                    continue
                if speaker:
                    lines.append(f"- \"{sentence}\" / {speaker}")
                else:
                    lines.append(f"- \"{sentence}\"")
            lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")

    print(f"Saved raw: {raw_path}")
    print(f"Saved report: {report_path}")


if __name__ == "__main__":
    main()
