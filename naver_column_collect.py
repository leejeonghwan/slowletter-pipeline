#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect NAVER column articles for selected presses.

Collects columns from press main pages (not newspaper pages).
Columns are published independently of newspaper date.

Example:
  python3 naver_column_collect.py

Outputs (~/Downloads):
- newspaper_full_press_view_column_YYYYMMDD_HHMM.csv
"""

import argparse
import os
import re
import time
from datetime import datetime
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


def get_column_links(press: str, code: str) -> List[Tuple[str, str, str]]:
    """Return list of (title, url, time_text) from the press main page.
    
    Columns are shown in the "칼럼" section.
    """
    press_url = f"https://media.naver.com/press/{code}"
    
    html = http_get(press_url)
    soup = BeautifulSoup(html, "html.parser")
    
    # Find column section
    column_section = soup.find("h4", class_="press_title_h", string=re.compile("칼럼"))
    if not column_section:
        return []
    
    # Find column list
    column_list = column_section.find_next("ul", class_="press_todaycolumn_ct")
    if not column_list:
        return []
    
    items = []
    for li in column_list.find_all("li", class_="press_todaycolumn_item"):
        a = li.find("a", class_="press_todaycolumn_headline")
        if not a or not a.get("href"):
            continue
        
        href = a.get("href", "").strip()
        title = norm(a.get_text())
        
        # Get time info
        time_div = li.find("div", class_="press_todaycolumn_time")
        time_text = norm(time_div.get_text()) if time_div else ""
        
        # Validate URL pattern: /article/{code}/{id}
        if f"/article/{code}/" in href:
            items.append((title, href, time_text))
    
    return items


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
    ap.add_argument("--sleep", type=float, default=REQUEST_DELAY)
    ap.add_argument("--max-per-press", type=int, default=20, help="Max columns per press")
    args = ap.parse_args()
    
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M")
    date_str = now.strftime("%Y%m%d")
    
    rows = []
    total_links = 0
    
    for p in PRESS_LIST:
        press = p["press"]
        code = p["code"]
        
        try:
            links = get_column_links(press, code)
        except Exception as e:
            print(f"{press}({code}): ERROR - {e}")
            continue
        
        total_links += len(links)
        links = links[:args.max_per_press]
        print(f"{press}({code}): columns={len(links)}")
        
        for i, (t_on_page, url, time_text) in enumerate(links, 1):
            try:
                title, content, origin_url = parse_naver_article(url)
            except Exception:
                title, content, origin_url = "", "", ""
            
            rows.append({
                "date": date_str,
                "press": press,
                "press_code": code,
                "page": "column",  # ← 칼럼 태그
                "title": title or t_on_page,
                "url": url,
                "summary_2sent": extract_summary_2sent(content),
                "origin_url": origin_url,
                "content": (content[:3500] if content else ""),
                "time_text": time_text,  # 추가 정보
            })
            
            if i % 10 == 0:
                print(f"  parsed {i}/{len(links)}")
            time.sleep(args.sleep)
        
        time.sleep(args.sleep)
    
    out_dir = os.path.expanduser("~/Downloads")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"newspaper_full_press_view_column_{timestamp}.csv")
    
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"saved: {out_path} rows={len(rows)} raw_links={total_links}")


if __name__ == "__main__":
    main()
