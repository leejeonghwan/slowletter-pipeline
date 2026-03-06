# -*- coding: utf-8 -*-
"""[오피니언 분석] 네이버 오피니언(칼럼) 수집 → 핵심 주장/직접 인용 발췌

요청 사항
- 대상: 네이버 오피니언 칼럼 https://news.naver.com/opinion/column
- 언론사: 조선/중앙/동아/한겨레/경향/한국 (6개)
- 클러스터링 없음
- 결과: 핵심 주장(1~2문장) + '문장 직접 인용' 1~3개 + 중요한 숫자(있으면)
- 굵은 표시(**) 사용하지 않음
- 산출물은 ~/Downloads 에 저장 (그리고 OpenClaw에서 텔레그램 첨부 가능)

실행 예
  python3 naver_opinion_columns.py --max-pages 5 --max-articles 60

환경변수
- OPENAI_API_KEY (필수)
- OPENAI_MODEL (옵션, 기본 gpt-4o-mini)
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}
REQ_TIMEOUT = 20
REQUEST_DELAY = 0.5

TARGET_PRESSES = {
    "조선일보",
    "중앙일보",
    "동아일보",
    "한겨레",
    "경향신문",
    "한국일보",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def http_get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.text


def extract_article_links_from_column_page(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")

    # 다양한 링크 형태를 포괄적으로 수집
    links = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if "n.news.naver.com" in href and "/article/" in href:
            links.append(href)
        elif href.startswith("/article/"):
            links.append("https://n.news.naver.com" + href)

    # 중복 제거(순서 유지)
    return list(dict.fromkeys(links))


@dataclass
class Column:
    date: str
    press: str
    title: str
    author: str
    naver_link: str
    content: str


def parse_naver_article(naver_url: str) -> Optional[Column]:
    try:
        html = http_get(naver_url)
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")

    press_el = soup.select_one("a.media_end_head_top_logo img[alt]") or soup.select_one("img.media_end_head_top_logo_img[alt]")
    press = press_el.get("alt", "").strip() if press_el else ""

    title_el = soup.select_one("h2#title_area") or soup.select_one(".media_end_head_title")
    title = norm(title_el.get_text(" ", strip=True)) if title_el else ""

    date_text = ""
    date_el = soup.select_one(".media_end_head_info_datestamp_time")
    if date_el and date_el.has_attr("data-date-time"):
        date_text = date_el["data-date-time"].strip()

    # 필자
    author = ""
    author_el = soup.select_one(".media_end_head_journalist_name")
    if author_el:
        author = norm(author_el.get_text(" ", strip=True))

    body = soup.select_one("article#dic_area") or soup.select_one("#dic_area") or soup.select_one("#newsct_article")
    content = ""
    if body:
        for tag in body.select("script, style"):
            tag.decompose()
        content = body.get_text("\n", strip=True)
        content = re.sub(r"\n{2,}", "\n", content).strip()

    if not title or not content or not press:
        return None

    return Column(
        date=date_text,
        press=press,
        title=title,
        author=author,
        naver_link=naver_url,
        content=content,
    )


def llm_json(client: OpenAI, model: str, payload: dict, max_tokens: int = 900) -> dict:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You output ONLY valid JSON. No markdown."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


QUOTE_CHARS = ["“", "”", "‘", "’", '"']


def split_sentences(text: str) -> List[str]:
    """
    한국어 문장 분리. 종결어미를 소비하지 않는 방식.
    """
    t = (text or "").strip()
    if not t:
        return []
    t = t.replace("\r", " ")
    # 방법: 종결 부호 뒤에서 끊되, 종결 부호를 앞 문장에 남긴다
    # 1) .!? + 닫는 따옴표 + 공백 (우선)
    # 2) .!? + 공백 (따옴표 없는 경우)
    # 3) 줄바꿈
    pattern = r'(?<=[.!?]["\'"」』])\s+|(?<=[.!?])\s+|(?<=\n)\s*'
    parts = re.split(pattern, t)
    return [norm(x) for x in parts if norm(x)]


def has_number(s: str) -> bool:
    return bool(re.search(r"\d", s or ""))


KOREAN_ENDINGS = re.compile(r'(다|요|죠|음|임|됨|함|것|수|듯)[.!?""」』]?\s*$')

def is_complete_sentence(s: str) -> bool:
    """종결어미로 끝나는 완전한 문장인지 확인"""
    s = s.strip()
    if len(s) < 10:
        return False
    if re.search(r'[.!?""」』]\s*$', s):
        return True
    if KOREAN_ENDINGS.search(s):
        return True
    return False


def complete_sentence(s: str, full_text: str) -> str:
    """
    잘린 문장을 원문에서 찾아 종결어미까지 확장한다.
    찾을 수 없으면 원본 그대로 반환.
    """
    s = s.strip()
    if is_complete_sentence(s):
        return s
    idx = full_text.find(s)
    if idx == -1:
        return s
    after = full_text[idx + len(s):]
    match = re.search(r'^(.{0,20}?(?:다|요|죠|음|임|됨|함)[.!?""」』]?)', after)
    if match:
        return s + match.group(1)
    return s


def is_direct_quote_sentence(s: str) -> bool:
    ss = s or ""
    if not any(ch in ss for ch in QUOTE_CHARS):
        return False
    if re.search(r"/\s*\S+\s*기자", ss):
        return False
    if "게티이미지" in ss or "연합뉴스" in ss:
        return False
    return True


def extract_number_sentences(text: str, limit: int = 12) -> List[str]:
    out = []
    for s in split_sentences(text):
        # 완전한 문장으로 확장
        s = complete_sentence(s, text)
        if not has_number(s):
            continue
        if len(s) < 14:
            continue
        # 완전한 문장인지 확인
        if not is_complete_sentence(s):
            continue
        if re.search(r"\b(사진|기자|게티이미지|연합뉴스)\b", s) and len(s) < 80:
            continue
        out.append(s)
    return list(dict.fromkeys(out))[:limit]


def extract_direct_quote_sentences(text: str, limit: int = 10) -> List[str]:
    out = []
    for s in split_sentences(text):
        # 완전한 문장으로 확장
        s = complete_sentence(s, text)
        # 완전한 문장인지 확인
        if not is_complete_sentence(s):
            continue
        if is_direct_quote_sentence(s) and len(s) <= 360:
            out.append(s)
    return list(dict.fromkeys(out))[:limit]


def analyze_column_llm(client: OpenAI, model: str, col: Column) -> dict:
    number_candidates = extract_number_sentences(col.content)
    quote_candidates = extract_direct_quote_sentences(col.content)

    payload = {
        "task": "opinion_column_brief_v4",
        "rules": [
            "굵은 표시(**)를 쓰지 마세요.",
            "summary: 이 칼럼에서만 알 수 있는 새로운 사실이나 핵심 주장을 1-2문장으로 요약하세요. '~에 대해 논한다', '~이 필요하다', '~이 중요하다'식의 일반론은 금지입니다. 구체적인 사실/주장/수치가 드러나야 합니다.",
            "summary 좋은 예: '주한 미군 사령관이 한밤에 국방부를 비판하는 성명을 냈는데, \"전투 대비 태세에 사과하지 않는다\"는 대목에서 한미 갈등의 수위가 읽힌다.'",
            "summary 나쁜 예: '한미 동맹의 복잡성을 드러내며, 실용적 접근이 필요하다는 점을 강조한다.'",
            "core_claim은 필자의 핵심 주장을 1~2문장으로.",
            "quotes는 candidates.direct_quotes에서만 고르세요(문장 그대로). 최소 3개, 최대 7개.",
            "quotes는 반드시 완전한 문장이어야 합니다. 중간에 끊긴 문장은 제외하세요.",
            "quotes는 필자의 주장을 뒷받침하는 중요한 문장/인용을 우선하세요.",
            "numbers는 candidates.number_sentences에서만 고르세요(문장 그대로).",
            "numbers의 what은 10자 이내의 짧은 라벨. 원문 문장의 단어를 반복하지 마세요.",
            "numbers의 what 좋은 예: '기대 출산율 증가폭' / 나쁜 예: '부부가 모두 주 1일 이상 재택근무를 하는 경우 여성 1인당 기대 출산율'",
            "뻔한 문장(원론/상투)은 피하고, 상황을 정확히 규정하는 문장을 우선.",
        ],
        "input": {
            "press": col.press,
            "title": col.title,
            "author": col.author,
            "date": col.date,
            "url": col.naver_link,
        },
        "candidates": {
            "number_sentences": number_candidates,
            "direct_quotes": quote_candidates,
        },
        "output": {
            "summary": "3줄 요약",
            "core_claim": "...",
            "quotes": ["...", "...", "..."],
            "numbers": [
                {"what": "...", "sentence": "..."}
            ]
        }
    }

    return llm_json(client, model, payload, max_tokens=1100)


def write_csv(path: str, rows: List[dict], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def parse_naver_datetime_kst(s: str) -> Optional[dt.datetime]:
    """Parse NAVER data-date-time string to timezone-aware KST datetime."""
    ss = (s or "").strip()
    if not ss:
        return None
    try:
        # NAVER commonly uses 'YYYY-MM-DD HH:MM:SS'
        d = dt.datetime.fromisoformat(ss.replace(" ", "T"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))
    return d.astimezone(dt.timezone(dt.timedelta(hours=9)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYYMMDD (예: 20260208). 비우면 최신")
    ap.add_argument("--start-date", default="", help="YYYYMMDD (예: 20260214). end-date와 함께 쓰면 날짜 범위 수집")
    ap.add_argument("--end-date", default="", help="YYYYMMDD (예: 20260218). start-date와 함께 쓰면 날짜 범위 수집")
    ap.add_argument("--within-hours", type=float, default=0.0, help="최근 N시간 이내 발행분만 (0이면 필터 없음)")
    ap.add_argument("--max-pages", type=int, default=5)
    ap.add_argument("--max-articles", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=REQUEST_DELAY)
    args = ap.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 필요합니다.")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    out_dir = os.path.expanduser("~/Downloads")
    os.makedirs(out_dir, exist_ok=True)

    # output suffix
    if args.start_date.strip() and args.end_date.strip():
        suffix = f"_{args.start_date.strip()}_{args.end_date.strip()}"
    else:
        suffix = f"_{args.date.strip()}" if args.date.strip() else ""

    raw_path = os.path.join(out_dir, f"opinion_columns_raw{suffix}.csv")
    report_path = os.path.join(out_dir, f"opinion_columns_report{suffix}.md")

    print("=" * 80)
    print("[오피니언 분석] 네이버 칼럼 수집 시작")
    print("=" * 80)

    def iter_dates(start_yyyymmdd: str, end_yyyymmdd: str) -> List[str]:
        try:
            s = dt.datetime.strptime(start_yyyymmdd, "%Y%m%d").date()
            e = dt.datetime.strptime(end_yyyymmdd, "%Y%m%d").date()
        except Exception:
            return []
        if e < s:
            s, e = e, s
        out = []
        cur = s
        while cur <= e:
            out.append(cur.strftime("%Y%m%d"))
            cur += dt.timedelta(days=1)
        return out

    # 1) 링크 수집 (단일 날짜 또는 날짜 범위)
    links: List[str] = []
    date_list: List[str] = []
    if args.start_date.strip() and args.end_date.strip():
        date_list = iter_dates(args.start_date.strip(), args.end_date.strip())
        print(f"- 날짜 범위 수집: {date_list[0]} ~ {date_list[-1]} ({len(date_list)}일)")
    elif args.date.strip():
        date_list = [args.date.strip()]
    else:
        date_list = [""]  # latest

    for dd in date_list:
        for page in range(1, args.max_pages + 1):
            base = "https://news.naver.com/opinion/column"
            params = []
            if dd:
                params.append(f"date={dd}")
            if page > 1:
                params.append(f"page={page}")
            url = base + ("?" + "&".join(params) if params else "")
            html = http_get(url)
            page_links = extract_article_links_from_column_page(html)
            if not page_links:
                break
            before = len(links)
            links.extend(page_links)
            links = list(dict.fromkeys(links))
            added = len(links) - before
            tag = dd if dd else "latest"
            print(f"- {tag} page {page}: +{added} (total {len(links)})")
            time.sleep(args.sleep)
            if len(links) >= args.max_articles:
                break
        if len(links) >= args.max_articles:
            break

    links = links[: args.max_articles]
    print(f"\n🔗 링크 수집: {len(links)}개")

    # 2) 기사 파싱 + 언론사 필터 (+ 최근 N시간 필터)
    cols: List[Column] = []
    kst = dt.timezone(dt.timedelta(hours=9))
    now_kst = dt.datetime.now(tz=kst)
    cutoff = None
    if args.within_hours and args.within_hours > 0:
        cutoff = now_kst - dt.timedelta(hours=float(args.within_hours))
        print(f"- 최근 {args.within_hours:g}시간 이내만 수집 (cutoff: {cutoff.strftime('%Y-%m-%d %H:%M:%S %z')})")

    # if date range requested, also filter parsed article datetime into [start,end]
    range_start = None
    range_end = None
    if args.start_date.strip() and args.end_date.strip():
        try:
            ds = dt.datetime.strptime(args.start_date.strip(), "%Y%m%d").date()
            de = dt.datetime.strptime(args.end_date.strip(), "%Y%m%d").date()
            if de < ds:
                ds, de = de, ds
            range_start = dt.datetime.combine(ds, dt.time.min, tzinfo=kst)
            range_end = dt.datetime.combine(de, dt.time.max, tzinfo=kst)
            print(f"- 날짜 필터: {range_start.strftime('%Y-%m-%d')} ~ {range_end.strftime('%Y-%m-%d')}")
        except Exception:
            range_start = range_end = None

    for i, link in enumerate(links, 1):
        col = parse_naver_article(link)
        if col and col.press in TARGET_PRESSES:
            d = parse_naver_datetime_kst(col.date)
            if cutoff:
                if not d or d < cutoff:
                    pass
                else:
                    cols.append(col)
            elif range_start and range_end:
                if not d or d < range_start or d > range_end:
                    pass
                else:
                    cols.append(col)
            else:
                cols.append(col)
        if i % 10 == 0 or i == len(links):
            print(f"📖 파싱 {i}/{len(links)} (대상 {len(cols)})")
        time.sleep(args.sleep)

    if not cols:
        raise RuntimeError("대상 6개 신문 칼럼을 찾지 못했습니다(시간 필터 포함).")

    # raw 저장
    raw_rows = [c.__dict__ for c in cols]
    write_csv(raw_path, raw_rows, ["date", "press", "author", "title", "naver_link", "content"])
    print(f"\n💾 저장: {raw_path} ({len(cols)}건)")

    # 3) LLM 분석
    print("\n" + "=" * 80)
    print("🤖 핵심 주장/인용 발췌")
    print("=" * 80)

    analyses = []
    for idx, c in enumerate(cols, 1):
        a = analyze_column_llm(client, model, c)
        summary = norm(a.get("summary", ""))  # ← P0-3: summary 추출
        core = norm(a.get("core_claim", ""))
        quotes = a.get("quotes", [])
        numbers = a.get("numbers", [])

        if not isinstance(quotes, list):
            quotes = []
        if not isinstance(numbers, list):
            numbers = []

        # quotes는 원문 포함 여부를 간단히 검증(없으면 제외)
        verified_quotes = []
        for q in quotes[:6]:
            q = norm(str(q))
            if q and q in c.content:
                verified_quotes.append(q)

        # numbers는 {what, sentence} 구조 + sentence 검증
        verified_numbers = []
        for it in numbers[:8]:
            if not isinstance(it, dict):
                continue
            what = norm(str(it.get("what", "")))
            sent = norm(str(it.get("sentence", "")))
            if not sent:
                continue
            if sent not in re.sub(r"\s+", " ", c.content):
                # allow simple whitespace normalization match
                cn = re.sub(r"\s+", " ", c.content)
                sn = re.sub(r"\s+", " ", sent)
                if sn not in cn:
                    continue
                sent = sn
            if not what:
                # if model omitted, fallback to the sentence itself (still usable)
                what = sent
            verified_numbers.append({"what": what, "sentence": sent})

        analyses.append({
            "press": c.press,
            "title": c.title,
            "author": c.author,
            "date": c.date,
            "url": c.naver_link,
            "summary": summary,  # ← P0-3: summary 추가
            "core_claim": core,
            "quotes": verified_quotes[:3],
            "numbers": verified_numbers[:6],
        })

        if idx % 10 == 0 or idx == len(cols):
            print(f"- 분석 {idx}/{len(cols)}")
        time.sleep(0.4)

    # 4) 리포트 MD
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append("[오피니언 분석]")
    lines.append("")
    lines.append(f"생성 시각: {now}")
    lines.append(f"대상 언론사: {', '.join(sorted(TARGET_PRESSES))}")
    if args.within_hours and args.within_hours > 0:
        lines.append(f"최근 {args.within_hours:g}시간 이내 발행만")
    lines.append(f"수집 건수: {len(analyses)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for a in analyses:
        lines.append(f"- {a['press']} | {a['title']}")
        if a.get("author"):
            lines.append(f"  {a['author']}")
        if a.get("summary"):
            lines.append(f"  {a['summary']}")
        if a.get("core_claim"):
            lines.append(f"  {a['core_claim']}")
        if a.get("numbers"):
            for it in a["numbers"][:6]:
                if isinstance(it, dict):
                    what = it.get("what", "")
                    sent = it.get("sentence", "")
                    if what and sent:
                        lines.append(f"  - {what}: {sent}")
                    elif sent:
                        lines.append(f"  - {sent}")
                else:
                    lines.append(f"  - {it}")
        if a.get("quotes"):
            for q in a["quotes"][:7]:
                lines.append(f"  - \"{q}\"")
        lines.append(f"  {a['url']}")
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")

    print(f"💾 저장: {report_path}")
    
    # HTML 변환
    try:
        from convert_opinion_columns_to_html import convert_opinion_columns_to_html
        html_path = convert_opinion_columns_to_html(report_path)
        print(f"💾 HTML 저장: {html_path}")
    except Exception as e:
        print(f"⚠️  HTML 변환 실패: {e}")
    
    print("완료되었습니다.")


if __name__ == "__main__":
    main()
