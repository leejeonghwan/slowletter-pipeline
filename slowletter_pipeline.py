#!/usr/bin/env python3
"""
slowletter_pipeline.py
======================
슬로우레터 크롤링 + 엔티티 추출 통합 파이프라인

사용법:
    python slowletter_pipeline.py                  # 증분 처리 (기본)
    python slowletter_pipeline.py --mode full      # 전체 재처리
    python slowletter_pipeline.py --mode rebuild   # 아카이브 초기화 후 전체 재수집

필요한 환경변수:
    SOLAR_API_KEY   - Upstage Solar Pro2 API 키

데이터 저장 위치:
    ./data/slowletter_data_archives.csv          - 크롤링 원본
    ./data/slowletter_entities.csv               - 엔티티 추출 결과
    ./data/logs/                                 - 실행 로그
"""

import os
import re
import json
import time
import csv
import math
import threading
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

import warnings
warnings.filterwarnings("ignore")


# ============================================================
# 설정
# ============================================================

# 경로 (환경변수로 변경 가능)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
ARCHIVE_CSV = os.path.join(DATA_DIR, "slowletter_data_archives.csv")
ENTITIES_CSV = os.path.join(DATA_DIR, "slowletter_entities.csv")
LOG_DIR = os.path.join(DATA_DIR, "logs")

# 크롤링 설정
WP_BASE_URL = "http://slownews.kr/wp-json/wp/v2/posts"
WP_CATEGORY_ID = 12637
WP_PER_PAGE = 100
WP_MAX_PAGES_FULL = 999
WP_MAX_PAGES_INCREMENTAL = 20
WP_SLEEP_SEC = 1.0

# 엔티티 추출 설정
SOLAR_BASE_URL = "https://api.upstage.ai/v1"
SOLAR_MODEL = "solar-pro2"
SOLAR_WORKERS = 2
SOLAR_QPS = 0.5
SOLAR_BATCH_SAVE = 500
SOLAR_TIMEOUT = 60
SOLAR_MAX_RETRIES = 10
SOLAR_BACKOFF = 5.0



# ============================================================
# 텔레그램 알림
# ============================================================
def send_telegram(message: str):
    """텔레그램으로 알림 전송."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


# ============================================================
# 로깅 설정
# ============================================================

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"run_{datetime.now():%Y%m%d_%H%M%S}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


# ============================================================
# STEP 1: 크롤링
# ============================================================

def extract_li_content(li_tag) -> str:
    """li 태그에서 텍스트와 a href만 추출.

    원본 HTML의 공백을 보존한다.
    <span>전기</span> 요금 → "전기 요금" (O)
    <span>전기</span> 요금 → "전기요금"  (X, 이전 버그)
    """
    parts = []
    for elem in li_tag.children:
        if isinstance(elem, NavigableString):
            # 원본 공백 보존: strip 대신 앞뒤 줄바꿈만 제거
            text = str(elem).replace("\n", " ").replace("\r", "")
            text = re.sub(r"  +", " ", text)  # 연속 공백 → 단일 공백
            if text.strip():
                parts.append(text)
        elif elem.name == "a" and elem.get("href"):
            parts.append(f'<a href="{elem.get("href")}">{elem.get_text(strip=True)}</a>')
        elif elem.name in ("strong", "b", "em", "i", "mark", "span"):
            inner_parts = []
            for inner in elem.children:
                if isinstance(inner, NavigableString):
                    t = str(inner).replace("\n", " ").replace("\r", "")
                    t = re.sub(r"  +", " ", t)
                    if t.strip():
                        inner_parts.append(t)
                elif inner.name == "a" and inner.get("href"):
                    inner_parts.append(
                        f'<a href="{inner.get("href")}">{inner.get_text(strip=True)}</a>'
                    )
                else:
                    t = inner.get_text(strip=True)
                    if t:
                        inner_parts.append(t)
            if inner_parts:
                parts.append("".join(inner_parts))
        else:
            t = elem.get_text(strip=True)
            if t:
                parts.append(t)
    result = "".join(parts)
    # 최종 정리: 연속 공백 제거, 앞뒤 정리
    result = re.sub(r"  +", " ", result).strip()
    return result


def load_archive(path: str) -> pd.DataFrame:
    """기존 아카이브 CSV 로드."""
    if not os.path.exists(path):
        return pd.DataFrame(
            columns=["uid", "post_id", "section_idx", "ID", "date", "title",
                      "h3_content", "api_id", "original_index"]
        )
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.drop(columns=["big_section"], errors="ignore", inplace=True)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    if "original_index" in df.columns:
        df["original_index"] = pd.to_numeric(df["original_index"], errors="coerce")
    return df


def migrate_legacy_archive(df: pd.DataFrame) -> pd.DataFrame:
    """구버전 아카이브(uid 없음)를 마이그레이션."""
    if df.empty:
        return df
    if "uid" in df.columns and df["uid"].notna().any():
        if "post_id" not in df.columns:
            df["post_id"] = df.get("api_id", pd.NA)
        if "section_idx" not in df.columns:
            df["section_idx"] = pd.NA
        return df

    if "api_id" not in df.columns:
        raise ValueError("legacy archive에 api_id가 없어 마이그레이션 불가")

    logging.getLogger(__name__).warning("legacy archive 감지 → uid 자동 생성")
    sort_cols = [c for c in ["date", "api_id", "original_index", "title"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(by=sort_cols).reset_index(drop=True)
    df["post_id"] = df["api_id"]
    df["section_idx"] = df.groupby("post_id").cumcount() + 1
    df["uid"] = df["post_id"].astype(str) + "_" + df["section_idx"].astype(int).astype(str).str.zfill(2)
    return df


def fetch_posts(category_id: int, since_date, mode: str, log) -> list:
    """WordPress REST API에서 포스트 수집."""
    posts = []
    page = 1
    max_pages = WP_MAX_PAGES_FULL if mode == "full" else WP_MAX_PAGES_INCREMENTAL

    after_param = None
    if mode == "incremental" and since_date is not None and pd.notna(since_date):
        after_param = (since_date - pd.Timedelta(days=2)).to_pydatetime().isoformat()
        log.info(f"증분 크롤링: {after_param} 이후 포스트 요청")

    while page <= max_pages:
        params = {
            "categories": category_id,
            "per_page": WP_PER_PAGE,
            "page": page,
            "orderby": "date",
            "order": "desc",
        }
        if after_param:
            params["after"] = after_param

        res = requests.get(WP_BASE_URL, params=params, timeout=30)
        data = res.json()

        if isinstance(data, dict):
            if data.get("code") == "rest_post_invalid_page_number":
                break
            raise RuntimeError(f"API 에러 (page={page}): {data}")
        if not data:
            break

        posts.extend(data)
        log.info(f"  page {page}: +{len(data)} posts (누적 {len(posts)})")
        page += 1
        time.sleep(WP_SLEEP_SEC)

    return posts


def parse_h3_sections(posts: list) -> pd.DataFrame:
    """포스트 HTML에서 h3 섹션을 파싱."""
    records = []
    for post in posts:
        post_id = post.get("id")
        date = post.get("date")
        html = (post.get("content") or {}).get("rendered", "") or ""
        soup = BeautifulSoup(html, "html.parser")

        section_idx = 0
        for h3 in soup.find_all("h3"):
            section_idx += 1
            h3_title = h3.get_text(" ", strip=True)
            content_parts = []
            sib = h3.find_next_sibling()
            while sib and getattr(sib, "name", None) not in ("h3", "h1", "div"):
                if getattr(sib, "name", None) in ("ul", "ol"):
                    for li in sib.find_all("li", recursive=False):
                        c = extract_li_content(li)
                        if c:
                            content_parts.append(f"<li>{c}</li>")
                sib = sib.find_next_sibling()

            records.append({
                "uid": f"{post_id}_{section_idx:02d}",
                "post_id": post_id,
                "section_idx": section_idx,
                "date": date,
                "title": h3_title,
                "h3_content": " ".join(content_parts),
                "api_id": post_id,
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    return df


def merge_archive(archive_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """아카이브와 새 데이터를 병합, uid 기준 중복 제거, ID 재부여."""
    if archive_df.empty:
        combined = new_df.copy()
    else:
        combined = pd.concat([archive_df, new_df], ignore_index=True)

    if combined.empty:
        return combined

    combined["date"] = pd.to_datetime(combined["date"], format="mixed", errors="coerce")
    combined["section_idx"] = pd.to_numeric(combined["section_idx"], errors="coerce")

    combined = combined.sort_values(by=["date", "uid"]).reset_index(drop=True)
    combined = combined.drop_duplicates(subset=["uid"], keep="last").reset_index(drop=True)

    combined = combined.sort_values(
        by=["date", "post_id", "section_idx"]
    ).reset_index(drop=True)
    combined["original_index"] = combined.index.astype(int)

    combined["date_str"] = combined["date"].dt.strftime("%Y_%m_%d")
    combined["date_rank"] = combined.groupby("date_str").cumcount() + 1
    combined["ID"] = combined["date_str"] + "_" + combined["date_rank"].astype(int).astype(str).str.zfill(2)
    combined.drop(columns=["date_str", "date_rank"], inplace=True)

    # 최신순 정렬
    combined = combined.sort_values(
        by=["date", "post_id", "section_idx"], ascending=[False, False, True]
    ).reset_index(drop=True)

    return combined


def step1_crawl(mode: str, log) -> pd.DataFrame:
    """Step 1: 크롤링 실행."""
    log.info("=" * 50)
    log.info("STEP 1: 크롤링 시작")
    log.info("=" * 50)

    os.makedirs(DATA_DIR, exist_ok=True)

    archive_df = load_archive(ARCHIVE_CSV)
    archive_df = migrate_legacy_archive(archive_df)
    log.info(f"기존 아카이브: {len(archive_df)}건")

    actual_mode = mode
    if mode == "auto":
        actual_mode = "incremental" if not archive_df.empty else "full"
    elif mode == "rebuild":
        log.info("rebuild 모드: 아카이브 초기화")
        archive_df = pd.DataFrame(columns=archive_df.columns)
        actual_mode = "full"

    latest_date = archive_df["date"].max() if not archive_df.empty else pd.NaT
    log.info(f"모드: {actual_mode} | 최신 날짜: {latest_date}")

    posts = fetch_posts(WP_CATEGORY_ID, latest_date, actual_mode, log)
    log.info(f"수집한 포스트: {len(posts)}개")

    h3_df = parse_h3_sections(posts)
    log.info(f"파싱한 h3 섹션: {len(h3_df)}건")

    archive_df = merge_archive(archive_df, h3_df)
    log.info(f"병합 후 아카이브: {len(archive_df)}건")

    archive_df.to_csv(ARCHIVE_CSV, index=False, encoding="utf-8-sig")
    log.info(f"저장 완료: {ARCHIVE_CSV}")

    return archive_df


# ============================================================
# STEP 2: 엔티티 추출
# ============================================================

def clean_html_for_api(text: str) -> str:
    """HTML 태그 제거, 공백 정규화."""
    if pd.isna(text) or text == "":
        return ""
    soup = BeautifulSoup(str(text), "html.parser")
    cleaned = soup.get_text().strip()
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_html_for_service(text: str) -> str:
    """HTML에서 텍스트 추출, 줄바꿈 보존."""
    if pd.isna(text) or text == "":
        return ""
    soup = BeautifulSoup(str(text), "html.parser")
    parts = []
    for elem in soup.contents:
        if isinstance(elem, NavigableString):
            parts.append(str(elem).strip())
        elif isinstance(elem, Tag):
            if elem.name == "br":
                parts.append("\n")
            elif elem.name in ("li", "p", "div"):
                parts.append(elem.get_text(strip=True))
                parts.append("\n")
            else:
                parts.append(elem.get_text(strip=True))
    cleaned = "".join(parts).strip()
    cleaned = re.sub(r"\n\s*\n", "\n", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class QPSLimiter:
    """초당 요청 수 제한."""
    def __init__(self, qps: float):
        self.min_interval = 1.0 / max(qps, 0.01)
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self):
        with self._lock:
            now = time.time()
            wait = self._last + self.min_interval - now
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self._last = now


class SolarEntityExtractor:
    """Upstage Solar Pro2 엔티티 추출기."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = f"{SOLAR_BASE_URL}/chat/completions"
        self.session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(total=0),
            pool_connections=SOLAR_WORKERS * 2,
            pool_maxsize=SOLAR_WORKERS * 2,
        )
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        self.qps = QPSLimiter(SOLAR_QPS)
        self.total_requests = 0
        self.total_tokens = 0
        self.errors = 0

    def test_connection(self, retries: int = 3, backoff: float = 5.0) -> bool:
        payload = {
            "model": SOLAR_MODEL,
            "messages": [{"role": "user", "content": "안녕"}],
            "max_tokens": 8,
        }
        for attempt in range(1, retries + 1):
            try:
                self.qps.acquire()
                r = self.session.post(self.endpoint, json=payload, timeout=10)
                if r.status_code == 200:
                    return True
                logging.warning(f"Solar API 연결 시도 {attempt}/{retries} 실패 (status={r.status_code})")
            except Exception as e:
                logging.warning(f"Solar API 연결 시도 {attempt}/{retries} 예외: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
        return False

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, List[str]]]:
        try:
            c = content.strip()
            if c.startswith("```json"):
                c = c[7:-3].strip()
            elif c.startswith("```"):
                c = c[3:-3].strip()
            data = json.loads(c)
            for k in ("persons", "organizations", "locations", "events", "concepts"):
                v = data.get(k, [])
                if not isinstance(v, list):
                    v = []
                data[k] = [str(x).strip() for x in v if isinstance(x, (str, int, float))][:10]
            return data
        except Exception:
            return None

    def extract(self, title: str, content: str) -> Dict[str, List[str]]:
        if len(content) > 1500:
            content = content[:1500] + "..."

        prompt = (
            "다음 한국어 뉴스에서 핵심 엔티티를 추출해주세요.\n\n"
            f"제목: {title}\n"
            f"내용: {content}\n\n"
            "다음 5개 카테고리별로 중요한 순서대로 최대 10개씩 추출하여 정확한 JSON 형식으로 응답하세요:\n\n"
            "1. persons: 인물명 (정치인, 기업인, 연예인, 일반인 등)\n"
            "2. organizations: 기관/조직명 (회사, 정부기관, 정당, 단체 등)\n"
            "3. locations: 지역명 (국가, 도시, 구체적 장소 등)\n"
            "4. events: 사건/사안명 (구체적 사건, 정책, 사고 등)\n"
            "5. concepts: 핵심 개념/키워드 (기술, 사회현상, 정책 등)\n\n"
            "응답 형식 (반드시 이 형식 준수):\n"
            '{"persons": ["이름1", "이름2"], "organizations": ["기관1"], '
            '"locations": ["지역1"], "events": ["사건1"], "concepts": ["개념1"]}\n\n'
            "주의: 유효한 JSON만 출력. 설명/주석 없이. 중복 제거. 빈 배열도 포함."
        )

        payload = {
            "model": SOLAR_MODEL,
            "messages": [
                {"role": "system", "content": "당신은 한국어 뉴스 분석 전문가입니다. 요청받은 JSON으로만 응답하세요."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 600,
        }

        empty = {"persons": [], "organizations": [], "locations": [], "events": [], "concepts": []}

        for attempt in range(1, SOLAR_MAX_RETRIES + 1):
            try:
                self.qps.acquire()
                r = self.session.post(self.endpoint, json=payload, timeout=SOLAR_TIMEOUT)
                self.total_requests += 1

                if r.status_code == 200:
                    js = r.json()
                    usage = js.get("usage") or {}
                    self.total_tokens += int(usage.get("total_tokens", 0))
                    parsed = self._parse_json(js["choices"][0]["message"]["content"])
                    if parsed:
                        return parsed
                    time.sleep(min(3.0, SOLAR_BACKOFF * attempt * 0.5))
                    continue

                if r.status_code in (429, 500, 502, 503, 504):
                    wait = SOLAR_BACKOFF * (2 ** (attempt - 1))
                    time.sleep(wait)
                    continue

                self.errors += 1
                break

            except requests.exceptions.Timeout:
                time.sleep(SOLAR_BACKOFF * (2 ** (attempt - 1)))
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
                time.sleep(SOLAR_BACKOFF * (2 ** (attempt - 1)))
            except Exception:
                self.errors += 1
                break

        return empty


def load_existing_entities(path: str) -> pd.DataFrame:
    """기존 엔티티 결과 CSV 로드."""
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def step2_entities(archive_df: pd.DataFrame, log, rebuild: bool = False) -> pd.DataFrame:
    """Step 2: 엔티티 추출. rebuild=True이면 기존 결과 무시하고 전체 재추출."""
    log.info("=" * 50)
    log.info("STEP 2: 엔티티 추출 시작")
    log.info("=" * 50)

    api_key = os.environ.get("SOLAR_API_KEY", "")
    if not api_key:
        log.error("SOLAR_API_KEY 환경변수가 설정되지 않았습니다.")
        log.error("  export SOLAR_API_KEY='your-key-here'")
        return pd.DataFrame()

    extractor = SolarEntityExtractor(api_key)
    if not extractor.test_connection():
        log.error("Solar API 연결 실패. API 키를 확인하세요.")
        return pd.DataFrame()
    log.info("Solar API 연결 성공")

    # 아카이브 데이터 전처리
    content_col = "h3_content" if "h3_content" in archive_df.columns else None
    if content_col is None:
        log.error("아카이브에 h3_content 컬럼이 없습니다.")
        return pd.DataFrame()

    archive_df["cleaned_content_for_api"] = archive_df[content_col].apply(clean_html_for_api)
    archive_df["cleaned_content_for_service"] = archive_df[content_col].apply(clean_html_for_service)

    # 기존 엔티티 결과 로드 → 증분 식별
    if rebuild:
        log.info("엔티티 전체 재추출 모드 (--rebuild-entity)")
        existing_df = pd.DataFrame()
        to_process = archive_df.copy()
    else:
        existing_df = load_existing_entities(ENTITIES_CSV)
    if not rebuild and existing_df.empty:
        to_process = archive_df.copy()
        log.info("기존 엔티티 결과 없음 → 전체 처리")
    elif not rebuild:
        existing_ids = set(existing_df["ID"].unique())
        archive_ids = set(archive_df["ID"].unique())
        new_ids = archive_ids - existing_ids
        if not new_ids:
            log.info("새로 처리할 데이터 없음")
            return existing_df
        to_process = archive_df[archive_df["ID"].isin(new_ids)].copy()
        log.info(f"기존: {len(existing_ids)}건 | 신규: {len(new_ids)}건")

    log.info(f"엔티티 추출 대상: {len(to_process)}건")

    # 병렬 추출
    results = []
    results_lock = threading.Lock()

    def _work(row: dict) -> dict:
        try:
            entities = extractor.extract(
                row.get("title", ""),
                row.get("cleaned_content_for_api", ""),
            )
            return {
                "ID": row.get("ID"),
                "date": row.get("date"),
                "title": row.get("title", ""),
                "cleaned_content_for_api": row.get("cleaned_content_for_api", ""),
                "cleaned_content_for_service": row.get("cleaned_content_for_service", ""),
                "original_index": row.get("original_index"),
                "solar_persons": "; ".join(entities.get("persons", [])),
                "solar_organizations": "; ".join(entities.get("organizations", [])),
                "solar_locations": "; ".join(entities.get("locations", [])),
                "solar_events": "; ".join(entities.get("events", [])),
                "solar_concepts": "; ".join(entities.get("concepts", [])),
                "total_entities": sum(len(v) for v in entities.values()),
                "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            extractor.errors += 1
            return {
                "ID": row.get("ID"),
                "date": row.get("date"),
                "title": row.get("title", ""),
                "cleaned_content_for_api": row.get("cleaned_content_for_api", ""),
                "cleaned_content_for_service": row.get("cleaned_content_for_service", ""),
                "original_index": row.get("original_index"),
                "solar_persons": "", "solar_organizations": "",
                "solar_locations": "", "solar_events": "", "solar_concepts": "",
                "total_entities": 0,
                "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e),
            }

    with ThreadPoolExecutor(max_workers=SOLAR_WORKERS) as ex:
        futures = [ex.submit(_work, row.to_dict()) for _, row in to_process.iterrows()]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="엔티티 추출"):
            results.append(fut.result())

    new_entities_df = pd.DataFrame(results)

    # 기존 결과와 병합
    if not existing_df.empty:
        # 컬럼 맞추기
        all_cols = list(set(existing_df.columns) | set(new_entities_df.columns))
        for col in all_cols:
            if col not in existing_df.columns:
                existing_df[col] = None
            if col not in new_entities_df.columns:
                new_entities_df[col] = None
        final_df = pd.concat([existing_df, new_entities_df], ignore_index=True)
    else:
        final_df = new_entities_df

    if not final_df.empty:
        final_df["date"] = pd.to_datetime(final_df["date"], errors="coerce")
        final_df = final_df[final_df["date"].notna()].copy()
        final_df = final_df.sort_values("original_index").reset_index(drop=True)

    # 저장
    final_df.to_csv(ENTITIES_CSV, index=False, encoding="utf-8", quoting=csv.QUOTE_NONNUMERIC)
    log.info(f"엔티티 결과 저장: {ENTITIES_CSV} ({len(final_df)}건)")

    log.info(f"API 요청: {extractor.total_requests} | 토큰: {extractor.total_tokens} | 오류: {extractor.errors}")

    return final_df


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="슬로우레터 크롤링 + 엔티티 추출 파이프라인")
    parser.add_argument(
        "--mode", choices=["auto", "incremental", "full", "rebuild"],
        default="auto",
        help="실행 모드 (기본: auto = 아카이브 있으면 증분, 없으면 전체)",
    )
    parser.add_argument(
        "--skip-crawl", action="store_true",
        help="크롤링 건너뛰기 (기존 아카이브로 엔티티만 추출)",
    )
    parser.add_argument(
        "--skip-entity", action="store_true",
        help="엔티티 추출 건너뛰기 (크롤링만 실행)",
    )
    parser.add_argument(
        "--rebuild-entity", action="store_true",
        help="엔티티 전체 재추출 (기존 결과 무시, --skip-crawl과 함께 사용 권장)",
    )
    args = parser.parse_args()

    log = setup_logging()
    start_time = time.time()

    log.info("🚀 슬로우레터 파이프라인 시작")
    log.info(f"   모드: {args.mode}")
    log.info(f"   데이터 경로: {DATA_DIR}")

    # Step 1: 크롤링
    if args.skip_crawl:
        log.info("크롤링 건너뛰기 (--skip-crawl)")
        archive_df = load_archive(ARCHIVE_CSV)
        archive_df = migrate_legacy_archive(archive_df)
    else:
        archive_df = step1_crawl(args.mode, log)

    if archive_df.empty:
        log.warning("아카이브가 비어 있습니다. 종료.")
        return

    # Step 2: 엔티티 추출
    if args.skip_entity:
        log.info("엔티티 추출 건너뛰기 (--skip-entity)")
    else:
        step2_entities(archive_df, log, rebuild=args.rebuild_entity)

    elapsed = int(time.time() - start_time)
    log.info(f"✅ 파이프라인 완료 (소요: {elapsed}초)")

    send_telegram(f"<b>슬로우레터 파이프라인 완료</b>\n아카이브: {len(archive_df)}건\n소요: {elapsed}초")


if __name__ == "__main__":
    main()
