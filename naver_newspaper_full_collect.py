# -*- coding: utf-8 -*-
"""Collect ALL NAVER newspaper (지면) articles for selected presses for a given date.

Jeonghwan request:
- For 6 presses (조선/중앙/동아/한겨레/경향/한국)
- Not only A1 but all newspaper (지면) articles on NAVER newspaper page
- Save to ~/Downloads, later used for copy/paste material extraction

Example:
  python3 naver_newspaper_full_collect.py --date 20260209 --max-links-per-press 140

Outputs (~/Downloads):
- newspaper_full_press_view_YYYYMMDD.csv

Notes:
- The NAVER newspaper page lists many article/newspaper links.
- We dedupe links and optionally cap per press for runtime.
"""

import argparse
import os
import re
import time
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}
REQ_TIMEOUT = 25
REQUEST_DELAY = 0.35

PRESS_LIST = [
    {"press": "조선일보", "code": "023"},
    {"press": "중앙일보", "code": "025"},
    {"press": "동아일보", "code": "020"},
    {"press": "한겨레", "code": "028"},
    {"press": "경향신문", "code": "032"},
    {"press": "한국일보", "code": "469"},
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def http_get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.text


def split_sentences(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    t = t.replace("\r", "\n")
    parts = re.split(r"(?:(?:[\.!\?])\s+|다\.\s+|\n+)", t)
    return [norm(x) for x in parts if norm(x)]


def extract_summary_2sent(text: str) -> str:
    sents = split_sentences(text)
    return " ".join(sents[:2]) if sents else ""


def get_newspaper_links(press: str, code: str, date: str) -> List[Tuple[str, str]]:
    """Return list of (title_on_page, url) from the newspaper page.

    NAVER occasionally serves slightly different href formats across presses/days.
    We therefore:
    - accept both absolute and relative hrefs
    - allow extra query params after date
    - retry a few times if we see 0 links (temporary anti-bot / incomplete HTML)
    """

    press_url = f"https://media.naver.com/press/{code}/newspaper?date={date}"

    rx = re.compile(
        r"^https?://n\.news\.naver\.com/(?:mnews/)?article/newspaper/"
        + re.escape(code)
        + r"/\d+\?date="
        + re.escape(date)
        + r"(?:&[^#]+)?(?:#.*)?$"
    )

    cand = []
    last_html = ""
    for _attempt in range(3):
        last_html = http_get(press_url)
        soup = BeautifulSoup(last_html, "html.parser")

        cand = []
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            # normalize relative article links if present
            if href.startswith(f"/article/newspaper/{code}/"):
                href = "https://n.news.naver.com" + href
            if rx.match(href):
                title = norm(a.get_text(" ", strip=True))
                cand.append((title, href))

        if cand:
            break
        time.sleep(0.6)

    # dedupe preserving order
    uniq = []
    seen = set()
    for t, h in cand:
        if h in seen:
            continue
        seen.add(h)
        uniq.append((t, h))

    return uniq


def clean_content(text: str) -> str:
    """Remove common caption/reporter noise from NAVER extracted text."""
    t = (text or "").strip()
    if not t:
        return ""
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    cleaned = []
    for ln in lines:
        # drop photo/caption lines
        if re.search(r"\b(사진|포토|제공|게티이미지|연합뉴스)\b", ln) and len(ln) < 80:
            continue
        # drop reporter credit line
        if re.search(r"/\s*\S+\s*기자", ln):
            continue
        # very short journalist-only line
        if ln.endswith("기자") and len(ln) <= 10:
            continue
        cleaned.append(ln)
    out = "\n".join(cleaned)
    out = re.sub(r"\n{2,}", "\n", out).strip()
    return out


def parse_naver_article(url: str) -> Tuple[str, str, str]:
    soup = BeautifulSoup(http_get(url), "html.parser")

    title = ""
    h2 = soup.select_one("h2#title_area") or soup.select_one("h2.media_end_head_headline")
    if h2:
        title = norm(h2.get_text(" ", strip=True))

    # original press url (기사원문)
    origin = ""
    origin_el = soup.select_one("a.media_end_head_origin_link")
    if origin_el and origin_el.get("href"):
        origin = origin_el.get("href", "").strip()

    body = soup.select_one("#dic_area") or soup.select_one("article#dic_area") or soup.select_one("article")
    content = ""
    if body:
        for tag in body.select("script, style"):
            tag.decompose()
        content = body.get_text("\n", strip=True)
        content = clean_content(content)

    return title, content, origin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--max-links-per-press", type=int, default=140)
    ap.add_argument("--sleep", type=float, default=REQUEST_DELAY)
    args = ap.parse_args()

    date = args.date.strip()

    rows = []
    total_links = 0
    for p in PRESS_LIST:
        press = p["press"]
        code = p["code"]
        links = get_newspaper_links(press, code, date)
        total_links += len(links)
        links = links[: args.max_links_per_press]
        print(f"{press}({code}): links={len(links)}")

        for i, (t_on_page, url) in enumerate(links, 1):
            try:
                title, content, origin_url = parse_naver_article(url)
            except Exception:
                title, content, origin_url = "", "", ""

            rows.append(
                {
                    "date": date,
                    "press": press,
                    "press_code": code,
                    "page": "(paper)",
                    "title": title or t_on_page,
                    "url": url,
                    "summary_2sent": extract_summary_2sent(content),
                    # 언론사 원문 링크(기사원문)
                    "origin_url": origin_url,
                    # 후처리(숫자/인용 추출)에서 재요청을 줄이기 위해 본문 일부를 함께 저장
                    "content": (content[:3500] if content else ""),
                }
            )

            if i % 25 == 0:
                print(f"  parsed {i}/{len(links)}")
            time.sleep(args.sleep)

        time.sleep(args.sleep)

    out_dir = os.path.expanduser("~/Downloads")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"newspaper_full_press_view_{date}.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print("saved:", out_path, "rows", len(rows), "raw_links", total_links)


if __name__ == "__main__":
    main()
