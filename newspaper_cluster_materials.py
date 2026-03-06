# -*- coding: utf-8 -*-
"""Cluster NAVER newspaper full (지면 전체) for 6 presses and extract materials.

Input:
- ~/Downloads/newspaper_full_press_view_YYYYMMDD.csv (requires content column)

Output:
- ~/Downloads/newspaper_clusters_materials_YYYYMMDD.md
- ~/Downloads/newspaper_clusters_links_YYYYMMDD.md

Design:
- Clustering by content similarity (TF-IDF on title+content snippet)
- For each cluster: list presses/titles; extract number sentences and direct quotes w/ speaker heuristic
- No bold (**)
"""

import argparse
import collections
import os
import re
import json
import sys
import subprocess
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import pandas as pd

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

# optional LLM (for '온도차/체크포인트' compaction)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


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


QUOTE_CHARS = ["“", "”", "‘", "’", '"']


def is_direct_quote_sentence(s: str) -> bool:
    ss = s or ""
    if not any(ch in ss for ch in QUOTE_CHARS):
        return False
    if re.search(r"/\s*\S+\s*기자", ss):
        return False
    if "게티이미지" in ss or "연합뉴스" in ss:
        return False
    return True


def label_number_sentence(s: str) -> str:
    """숫자 문장 라벨(Jeonghwan 기준).

    - '기간/시점' 라벨은 실무적으로 의미가 낮아 제외합니다(대부분 전날 기사).
    - 날짜/시각만 있는 문장은 아래 filter에서 걸러지는 것을 전제로 합니다.
    """
    ss = s
    if re.search(r"\d+(?:\.\d+)?\s*%", ss):
        return "비율/퍼센트"
    if re.search(r"\d[\d,]*\s*(?:원|달러|엔|유로|억원|조원|만\s*원|억\s*원|조\s*원)", ss):
        return "금액/규모"
    if re.search(r"\d+\s*(?:석|표|득표율)", ss):
        return "의석/표/득표"
    if re.search(r"\b(환율|원-달러|코스피|코스닥|지수|시가총액|금리)\b", ss):
        return "지표"
    if re.search(r"\d+\s*(?:명|건|개|회|배|곳|채|차례)", ss):
        return "수량/횟수"
    # 기간 단서는 보조 라벨로만(단독 라벨로는 쓰지 않음)
    if re.search(r"\d+\s*(?:년|개월|일|시간|분|초)", ss):
        return "기간(보조)"
    return "숫자 포함"

DATE_ONLY_RE = re.compile(r"^(?:\d{4}년\s*)?\d{1,2}월\s*\d{1,2}일|\d{4}-\d{2}-\d{2}")
MONEY_RE = re.compile(r"\d[\d,]*\s*(?:원|달러|엔|유로|억원|조원|만\s*원|억\s*원|조\s*원)")
PCT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")


def is_caption_like(sent: str) -> bool:
    s = (sent or "").strip()
    if not s:
        return False
    # 기자/사진 캡션성 문장 제거
    if re.search(r"/\s*\S+\s*기자", s):
        return True
    if re.search(r"\b(사진|포토|기자|게티이미지|연합뉴스|제공|뉴스1|뉴시스)\b", s) and len(s) < 120:
        return True
    # '.../뉴스1' 같은 전형적 캡션
    if re.search(r"/\s*(?:뉴스1|뉴시스|연합뉴스)$", s):
        return True
    # === 추가: 이메일 주소, 기사원문 링크 ===
    if "@" in s and len(s) < 80:  # 이메일 주소
        return True
    if "기사원문" in s:
        return True
    if re.search(r"^https?://", s):  # URL만 있는 문장
        return True
    return False


def is_low_value_number_sentence(sent: str) -> bool:
    """날짜/시각만 있는 숫자 문장 등, 의미가 낮은 것 제거."""
    s = sent or ""
    if DATE_ONLY_RE.search(s) and not (MONEY_RE.search(s) or PCT_RE.search(s)):
        # 날짜/시각 위주인데 금액/퍼센트/지표가 없으면 버림
        return True
    return False


def extract_number_facts(text: str, limit: int = 6) -> List[Tuple[str, str]]:
    out = []
    for sent in split_sentences(text):
        # 완전한 문장으로 확장
        sent = complete_sentence(sent, text)
        if not has_number(sent):
            continue
        if len(sent) < 14:
            continue
        # 완전한 문장인지 확인
        if not is_complete_sentence(sent):
            continue
        if is_caption_like(sent):
            continue
        if is_low_value_number_sentence(sent):
            continue
        out.append((label_number_sentence(sent), sent))

    seen = set()
    uniq = []
    for lab, sent in out:
        if sent in seen:
            continue
        seen.add(sent)
        uniq.append((lab, sent))
    return uniq[:limit]


def extract_speaker_from_quote_sentence(sentence: str) -> str:
    s = norm(sentence)
    if not s:
        return ""

    # 1) '이름(소속/직함) ... “' 형태
    m = re.search(r"([가-힣]{2,4})\s*\(([^\)]+)\)\s*(?:은|는|이|가)\s*[“\"]", s)
    if m:
        return norm(f"{m.group(1)}({m.group(2)})")

    # 2) '이름 + (소속) + (직함) + 은/는 ... “'
    m = re.search(
        r"([가-힣]{2,4})\s*(?:([가-힣]{2,10})\s*)?(의원|대표|원장|장관|차관|총리|비서실장|대변인|위원장|교수|연구원|변호사)\s*(?:은|는|이|가)\s*[“\"]",
        s,
    )
    if m:
        name = norm(m.group(1))
        org = norm(m.group(2) or "")
        role = norm(m.group(3) or "")
        if org and role:
            return norm(f"{name}({org} {role})")
        if role:
            return norm(f"{name}({role})")
        return name

    # 3) 마지막 토큰(예: '의원은')만 잡히는 경우 보정: 앞에 이름이 있으면 이름을 우선
    m = re.search(r"([가-힣]{2,4})\s+[^“\"]{0,18}\s*(?:의원|대표|원장|장관|차관|총리)\s*(?:은|는|이|가)\s*[“\"]", s)
    if m:
        return norm(m.group(1))

    # 4) '”라고 ... 이름은 말했다' 유형
    m = re.search(
        r"[”\"]\s*(?:라고|며|면서)\s*([가-힣]{2,4})(?:\(([^\)]+)\))?\s*(?:은|는|이|가)?\s*(?:말했|밝혔|전했|설명했|지적했|강조했|우려했|반박했)",
        s,
    )
    if m:
        name = norm(m.group(1))
        extra = norm(m.group(2) or "")
        return norm(f"{name}({extra})") if extra else name

    return ""


def is_cliche_quote(quote: str) -> bool:
    """상투적 표현이나 기사 가치가 낮은 인용문 감지."""
    q = norm(quote).lower()
    
    # 상투적 표현 패턴
    CLICHE_PATTERNS = [
        r"최선을\s*다하[겠다고|겠습니다]",
        r"유감(?:스럽|이)",
        r"노력하[겠다고|겠습니다]",
        r"면밀히?\s*검토",
        r"적극\s*(?:검토|추진|노력)",
        r"신중하?게?\s*(?:검토|판단|결정)",
        r"충분히?\s*(?:검토|논의)",
        r"깊이\s*(?:새기|반성)",
        r"송구(?:스럽|하)",
        r"(?:진심으로|깊이)\s*사과",
        r"안타까[운|웠]",
        r"(?:확인|검토)\s*중",
        r"(?:파악|점검)\s*중",
        r"조속히?\s*(?:해결|추진)",
        r"차질\s*없[이도록]",
        r"만전을\s*기하",
        r"중요하?게?\s*생각",
        r"(?:철저|엄정|엄중)하?게?\s*(?:대응|처리|조사)",
        r"법과\s*원칙",
        r"국민.*(?:마음|입장)",
    ]
    
    for pattern in CLICHE_PATTERNS:
        if re.search(pattern, q):
            return True
    
    # 너무 짧고 구체적 정보 없는 경우
    if len(q) < 15 and not any(ch.isdigit() for ch in q):
        return True
    
    # 감탄사만 있는 경우
    if re.match(r"^(?:아|어|오)\s*[!?]?\s*$", q):
        return True
    
    return False


def extract_direct_quotes(text: str, limit: int = 2) -> List[Tuple[str, str]]:
    out = []
    for sent in split_sentences(text):
        # 완전한 문장으로 확장
        sent = complete_sentence(sent, text)
        if not is_direct_quote_sentence(sent):
            continue
        if len(sent) > 360:
            continue
        # 완전한 문장인지 확인
        if not is_complete_sentence(sent):
            continue
        if is_caption_like(sent):
            continue
        
        # 인용구 추출 (따옴표 안 내용)
        quote_text = ""
        m = re.search(r'["""]([^"""]{4,300})["""]', sent)
        if m:
            quote_text = norm(m.group(1))
        
        # 상투적 표현 필터링
        if quote_text and is_cliche_quote(quote_text):
            continue
        
        sp = extract_speaker_from_quote_sentence(sent)
        out.append((sp, sent))
    seen = set()
    uniq = []
    for sp, sent in out:
        if sent in seen:
            continue
        seen.add(sent)
        uniq.append((sp, sent))
    return uniq[:limit]


def cluster_df(df: pd.DataFrame, distance_threshold: float, min_cluster_size: int):
    texts = []
    for _, r in df.iterrows():
        title = str(r.get("title", ""))
        content = str(r.get("content", ""))
        texts.append(f"{title}\n{content[:2000]}")

    vec = TfidfVectorizer(
        max_features=40000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.9,
        token_pattern=r"(?u)[\w\-]{2,}",
    )
    X = vec.fit_transform(texts)
    sim = cosine_similarity(X)
    dist = 1.0 - sim

    model = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="average",
        distance_threshold=distance_threshold,
    )
    raw = model.fit_predict(dist)

    cnt = collections.Counter(raw)
    labels = [(-1 if cnt[x] < min_cluster_size else int(x)) for x in raw]

    # remap cluster ids to dense 0..k-1 excluding -1
    uniq = sorted({x for x in labels if x != -1})
    remap = {old: new for new, old in enumerate(uniq)}
    labels = [(-1 if x == -1 else remap[x]) for x in labels]

    out = df.copy()
    out["cluster_id"] = labels
    return out


def llm_json(
    client: "OpenAI",
    model: str,
    payload: dict,
    max_tokens: int = 350,
    timeout_s: float = 40.0,
    retries: int = 2,
) -> dict:
    """Call OpenAI and return parsed JSON. Adds timeout/retry so --llm-context can't hang forever."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You output ONLY valid JSON. No markdown."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=timeout_s,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            last_err = e
            # small backoff
            time.sleep(1.5 * (attempt + 1))
            continue
    raise last_err


def make_cluster_context_llm(
    client: "OpenAI",
    model: str,
    headline: str,
    rep_articles: List[dict],
) -> dict:
    """Stage-2: Generate summary + quotes from representative full texts.

    rep_articles item:
      {press,title,content,url}

    Output keys:
      - summary: string (2-3 sentences)
      - quotes: list of {press, quote, speaker, url}
      - temp_diff: string
      - press_lines: {press: line}
      - checkpoint_q: string
      - context_keywords: [k1,k2,k3]
    """
    payload = {
        "task": "cluster_context_v3_with_quotes",
        "rules": [
            "한국어 존대말.",
            "굵은 표시(**) 금지.",
            "과장 금지. 입력 원문에 없는 사실을 만들지 말 것.",
            "summary는 이 클러스터의 핵심 내용을 2-3문장으로 요약.",
            "quotes는 '기사에 실을 가치가 있는' 직접 인용만 엄격히 선택:",
            "- ✅ 새로운 정보/수치/사실을 담은 발언",
            "- ✅ 정책/결정에 대한 핵심 진술 또는 구체적 계획",
            "- ✅ 논쟁적이거나 중요한 입장 표명",
            "- ✅ 이해관계자의 명확하고 구체적인 의견",
            "- ❌ 상투적 표현(예: '최선을 다하겠다', '유감스럽다', '노력하겠다', '면밀히 검토')",
            "- ❌ 배경 설명용 일반론이나 당연한 말",
            "- ❌ 부차적 세부사항이나 감성적 표현만 있는 발언",
            "- 인용구는 원문 그대로, 따옴표 안의 문장만.",
            "- 각 인용에 언론사(press), 인용구(quote), 발언자(speaker), url 포함.",
            "- 같은 내용이면 1개만, 서로 다른 코멘트가 있으면 각각 발췌.",
            "- 최소 0개(가치 있는 인용이 없으면 빈 배열), 최대 5개.",
            "온도차는 '프레임/책임소재/해법/강조점'의 차이만 1문장으로.",
            "press_lines는 언론사별로 '차이만' 드러나는 한 줄(요약 나열 금지). 차이가 없으면 생략해도 됨.",
            "press_lines의 한 줄은 반드시 완전한 문장으로 끝내세요(마침표/느낌표/물음표 필수).",
            "checkpoint_q는 독자가 궁금해할 질문 1개.",
            "context_keywords는 붙일 맥락 키워드 3개(짧게).",
        ],
        "input": {
            "cluster_label": headline,
            "rep_articles": rep_articles,
        },
        "output": {
            "summary": "...",
            "quotes": [
                {"press": "조선일보", "quote": "...", "speaker": "...", "url": "..."}
            ],
            "temp_diff": "...",
            "press_lines": {"조선일보": "..."},
            "checkpoint_q": "...",
            "context_keywords": ["...", "...", "..."]
        },
    }
    return llm_json(client, model, payload, max_tokens=1200)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--distance-threshold", type=float, default=0.78)
    ap.add_argument("--min-cluster-size", type=int, default=3)
    ap.add_argument("--top-clusters", type=int, default=15)
    ap.add_argument("--llm-context", action="store_true", help="온도차/체크포인트를 LLM으로 압축 생성")
    args = ap.parse_args()

    dl = os.path.expanduser("~/Downloads")
    in_path = os.path.join(dl, f"newspaper_full_press_view_{args.date}.csv")
    df = pd.read_csv(in_path)

    # optional LLM client
    client = None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if args.llm_context:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key and OpenAI is not None:
            client = OpenAI(api_key=api_key)
        else:
            print("[warn] --llm-context requested but OPENAI_API_KEY or openai package missing; skipping LLM context")
            client = None

    if "content" not in df.columns:
        raise RuntimeError("input csv must include content column")

    dfc = cluster_df(df, args.distance_threshold, args.min_cluster_size)

    # cluster stats
    stats = []
    for cid, g in dfc.groupby("cluster_id"):
        cid = int(cid)
        presses = ", ".join(sorted(set(g["press"].astype(str).tolist())))
        stats.append(((-1 if cid == -1 else len(g)), cid, presses, g))

    # sort: cluster size desc, put -1 last
    stats.sort(key=lambda t: (t[1] == -1, -t[0], t[1]))

    top = []
    misc = None
    for size, cid, presses, g in stats:
        if cid == -1:
            misc = (size, cid, presses, g)
            continue
        if len(top) < args.top_clusters:
            top.append((size, cid, presses, g))
    if misc:
        top.append(misc)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    mat_lines = []
    link_lines = []

    mat_lines.append("[지면 전체 클러스터 기초자료: 복붙용]")
    mat_lines.append("")
    mat_lines.append(f"기준일: {args.date}")
    mat_lines.append(f"생성 시각: {now}")
    mat_lines.append("원칙: 링크는 별도 파일에만 정리. 아래는 문장 재료(숫자/발언) 위주.")
    mat_lines.append("")

    # 상단 요약 레이어
    top_lines = []
    top_lines.append("[오늘의 핵심(편집용)]")
    top_lines.append("- 기준: 4개. 빠르게 핵심 파악용.")
    top_lines.append("")

    gems_lines = []
    gems_lines.append("[놓치기 쉬운 중요(구석의 중요)]")
    gems_lines.append("- 기준: 단독/소수(-1)에서 공적 가치/직접 인용/숫자 재료가 강한 것 최대 7개.")
    gems_lines.append("")

    # 목차(오늘의 이슈 목록): 15개
    toc_lines = []
    toc_items = []
    toc_lines.append("[오늘의 이슈 목록(목차)]")
    toc_lines.append("- 기준: 클러스터 단위로 15개. origin_url 우선.")
    toc_lines.append("")

    link_lines.append("[지면 전체 클러스터 링크 모음]")
    link_lines.append("")
    link_lines.append(f"기준일: {args.date}")
    link_lines.append(f"생성 시각: {now}")
    link_lines.append("")

    # 목차를 materials 상단에 삽입(상세 본문은 아래)
    # - kept_clusters는 본문 생성 루프에서 채워집니다.


    # simple filters
    DROP_TITLE_PATTERNS = [
        r"\[사진\]",
        r"\b포토\b",
        # === 추가: 부음/날씨/만평 등 ===
        r"\[부음\]",
        r"\[부고\]",
        r"별세",
        r"빈소",
        r"\[인사\]",
        r"인사이동",
        r"\[날씨\]",
        r"오늘의 날씨",
        r"내일 날씨",
        r"\[만평\]",
        r"\[크로스워드\]",
        r"\[퍼즐\]",
        r"\[지표로 보는\]",
        r"\[오늘의 운세\]",
    ]
    DROP_TOPIC_PATTERNS = [
        # sports/olympics
        r"\b올림픽\b",
        r"\b메달\b",
        r"\b경기\b",
        r"\b승리\b",
        r"\b골\b",
        r"\b선수\b",
        # 생활정보/미담 힌트(너무 공격적이면 나중에 조정)
        r"\b레시피\b",
        r"\b건강\b",
        r"\b운세\b",
    ]

    def drop_row(r) -> bool:
        title = norm(str(r.get("title", "")))
        if any(re.search(p, title) for p in DROP_TITLE_PATTERNS):
            return True
        if any(re.search(p, title) for p in DROP_TOPIC_PATTERNS):
            return True
        return False

    # 관찰(누적) 로그
    obs_log_path = os.path.join(os.path.dirname(__file__), "memory", "observation_log.md")
    os.makedirs(os.path.dirname(obs_log_path), exist_ok=True)

    OBS_TOPIC_RE = re.compile(r"(이란|항모|전쟁|관세|USTR|비관세|북한|무인기|중동|가자|러시아|우크라)")

    def choose_rep_links(rows_df: pd.DataFrame, max_n: int = 3) -> List[str]:
        out = []
        seen = set()
        for _, rr in rows_df.iterrows():
            naver_url = str(rr.get("url", "")).strip()
            origin_url = str(rr.get("origin_url", "")).strip()
            u = origin_url or naver_url
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= max_n:
                break
        return out

    def choose_rep_title(rows_df: pd.DataFrame) -> str:
        # 대표 제목 1개: 캡션/사진성 제외, 길이가 너무 짧지 않은 것 우선
        cands = []
        for _, rr in rows_df.iterrows():
            t = norm(str(rr.get("title", "")))
            if not t:
                continue
            if re.search(r"\b(사진|포토|만평|부고|인사)\b", t):
                continue
            cands.append(t)
        if not cands:
            return ""
        cands = sorted(cands, key=lambda x: (abs(len(x) - 38), len(x)))
        return cands[0]

    def select_rep_rows(rows_df: pd.DataFrame, min_n: int = 3, max_n: int = 5) -> pd.DataFrame:
        """Pick 3~5 representative rows prioritizing press diversity and rich content."""
        r = rows_df.copy()
        r["_len"] = r["content"].fillna("").astype(str).str.len()
        # prefer longer content
        r = r.sort_values(["_len"], ascending=False)

        picked = []
        used_press = set()
        # 1) pick one per press first
        for _, rr in r.iterrows():
            pr = str(rr.get("press", "")).strip()
            if pr in used_press:
                continue
            picked.append(rr)
            used_press.add(pr)
            if len(picked) >= max_n:
                break
        # ensure at least min_n
        if len(picked) < min_n:
            for _, rr in r.iterrows():
                if any(rr.get("url") == x.get("url") for x in picked):
                    continue
                picked.append(rr)
                if len(picked) >= min_n:
                    break
        return pd.DataFrame(picked)

    def extract_first_quoted_phrase(s: str) -> str:
        ss = s or ""
        m = re.search(r"[“\"]([^”\"]{4,160})[”\"]", ss)
        if m:
            return norm(m.group(1))
        return ""

    def looks_truncated(sent: str) -> bool:
        s = (sent or "").strip()
        if not s:
            return False
        # 문장부호 없이 '...했' 등으로 끝나면 잘린 경우가 많음
        if s[-1] in ".!?…’”\"”" or s.endswith("다"):
            return False
        return bool(re.search(r"(했|됐|있|없|된|할|중|및)$", s))

    def choose_point_text(angle_pool, fact_pool, quote_pool) -> str:
        # 1) 인용(직접 인용) 우선: 다만 상투적 표현/감탄사/캡션성은 제외
        BAD_QUOTE_PHRASE = re.compile(r"^(?:아빠|엄마)\s*(?:괜찮아|사랑해).*$")
        for sp, q, press, url in quote_pool:
            qn = norm(q)
            if not qn or is_caption_like(qn) or looks_truncated(qn):
                continue
            speaker = sp if sp else "(발언자 미상)"
            phrase = extract_first_quoted_phrase(qn)
            if phrase:
                # 상투적 표현 필터링
                if is_cliche_quote(phrase):
                    continue
                if BAD_QUOTE_PHRASE.match(phrase):
                    continue
                return f"{speaker}: \"{phrase}\""
            # if full quote is just a short shout, skip
            if len(qn) < 12 and BAD_QUOTE_PHRASE.match(qn):
                continue
            # 전체 인용문도 상투적 표현 체크
            if is_cliche_quote(qn):
                continue
            return f"{speaker}: \"{qn}\""

        # 2) 숫자/팩트 1개(라벨은 숨기고 문장 그대로, 기간보조/캡션/잘림 제외)
        for lab, sent, press, url in fact_pool:
            if lab == "기간(보조)" and not (
                MONEY_RE.search(sent)
                or PCT_RE.search(sent)
                or re.search(r"\b(환율|코스피|코스닥|지수|시가총액|금리)\b", sent)
            ):
                continue
            if is_caption_like(sent) or looks_truncated(sent):
                continue
            return sent

        # 3) 요약 1개
        for summ, press, url in angle_pool:
            if summ and not is_caption_like(summ):
                return summ
        return ""

    kept_clusters = []  # for TOC + obs selection

    for size, cid, presses, g in top:
        g2 = g.copy()
        # drop sports/photo/lifestyle at row-level
        g2 = g2[~g2.apply(drop_row, axis=1)]
        if len(g2) < max(2, args.min_cluster_size) and cid != -1:
            # cluster became too small after filtering
            continue

        # headline: do NOT rely on titles; use a neutral label built from frequent tokens in titles
        if cid == -1:
            headline = "기타(단독/소수 이슈 모음)"
        else:
            titles = " ".join([norm(str(x)) for x in g2["title"].tolist()])
            toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", titles) if len(t) >= 2]
            stop = {"기자", "신문", "오늘", "관련", "단독"}
            freq = collections.Counter([t for t in toks if t not in stop])
            key = ", ".join([w for w, _ in freq.most_common(6)])
            headline = key if key else f"클러스터 {cid}"

        presses2 = ", ".join(sorted(set(g2["press"].astype(str).tolist())))

        fact_pool = []
        quote_pool = []
        angle_pool = []
        phrase_pool = []

        for _, r in g2.iterrows():
            press = str(r.get("press", "")).strip()
            naver_url = str(r.get("url", "")).strip()
            origin_url = str(r.get("origin_url", "")).strip()
            url = origin_url or naver_url
            text = str(r.get("content", ""))
            summ = norm(str(r.get("summary_2sent", "")))

            for lab, sent in extract_number_facts(text, limit=4):
                fact_pool.append((lab, sent, press, url))
            for sp, q in extract_direct_quotes(text, limit=1):
                quote_pool.append((sp, q, press, url))

            if summ:
                angle_pool.append((summ, press, url))

            t = norm(str(r.get("title", "")))
            if "여자 아베" in t:
                phrase_pool.append(("여자 아베", press, url))

        rep_df = select_rep_rows(g2, min_n=3, max_n=5)
        rep_links = choose_rep_links(rep_df if len(rep_df) else g2, max_n=3)
        rep_title = choose_rep_title(rep_df if len(rep_df) else g2) or headline

        # stage-2 LLM context from representative full texts
        llm_ctx = {}
        best_quote_point = ""
        if client and len(rep_df):
            rep_articles = []
            for _, rr in rep_df.iterrows():
                pr = str(rr.get("press", "")).strip()
                title = norm(str(rr.get("title", "")))
                naver_url = str(rr.get("url", "")).strip()
                origin_url = str(rr.get("origin_url", "")).strip()
                u = origin_url or naver_url
                content = str(rr.get("content", ""))[:2500]
                rep_articles.append({"press": pr, "title": title, "content": content, "url": u})
            try:
                print(f"[llm] cluster {cid}: context...")
                llm_ctx = make_cluster_context_llm(client, model, headline, rep_articles)
            except Exception as e:
                print(f"[warn] cluster {cid}: llm-context failed: {e}")
                llm_ctx = {}

            # Extract quotes from LLM response
            quotes_llm = llm_ctx.get("quotes", [])
            if quotes_llm and isinstance(quotes_llm, list) and len(quotes_llm) > 0:
                first_q = quotes_llm[0]
                q = norm(str(first_q.get("quote", "")))
                sp = norm(str(first_q.get("speaker", "")))
                if q:
                    best_quote_point = f"\"{q}\"" + (f" / {sp}" if sp else "")

        point = best_quote_point or choose_point_text(angle_pool, fact_pool, quote_pool)

        kept_clusters.append(
            {
                "cid": cid,
                "headline": headline,
                "rep_title": rep_title,
                "size": len(g2),
                "presses": presses2,
                "rep_links": rep_links,
                "point": point,
                "g2": g2,
                "rep_df": rep_df,
                "fact_pool": fact_pool,
                "quote_pool": quote_pool,
                "angle_pool": angle_pool,
                "phrase_pool": phrase_pool,
                "llm_ctx": llm_ctx,
            }
        )

        # 본문 출력(클러스터 상세)
        mat_lines.append(f"### {rep_title}")
        mat_lines.append(f"- 언론: {presses2}")

        # LLM summary
        if llm_ctx.get("summary"):
            summ = norm(str(llm_ctx["summary"]))
            if summ:
                mat_lines.append(f"- [내용 요약]: {summ}")

        # LLM quotes
        quotes_llm = llm_ctx.get("quotes", [])
        if quotes_llm and isinstance(quotes_llm, list):
            mat_lines.append("- [중요 코멘트]:")
            for idx, q_item in enumerate(quotes_llm, 1):
                quote = norm(str(q_item.get("quote", "")))
                speaker = norm(str(q_item.get("speaker", "")))
                press = norm(str(q_item.get("press", "")))
                url = str(q_item.get("url", "")).strip()
                if not quote:
                    continue
                line = f"  {idx}. \"{quote}\""
                if speaker:
                    line += f" / {speaker}"
                if press:
                    line += f" ({press})"
                mat_lines.append(line)
                if url:
                    mat_lines.append(f"     → {url}")

        # 한줄 맥락/오늘의 포인트(나열 방지)
        if angle_pool:
            ctx = None
            for summ, pr, u in angle_pool:
                if summ and not is_caption_like(summ):
                    ctx = summ
                    break
            if ctx:
                mat_lines.append(f"- 한줄 맥락: {ctx}")
        if point:
            mat_lines.append(f"- 포인트: {point}")

        # dedupe facts
        seen = set()
        facts = []
        for lab, sent, press, url in fact_pool:
            if sent in seen:
                continue
            seen.add(sent)
            facts.append((lab, sent, press, url))
            if len(facts) >= 8:
                break
        def format_fact_line(sent: str, press: str) -> str:
            s = norm(sent)
            if not s:
                return f"  - ({press})"
            # If it contains a direct quote, prefer: "인용구" / 발언자
            if any(ch in s for ch in QUOTE_CHARS):
                sp = extract_speaker_from_quote_sentence(s)
                phrase = ""
                m = re.search(r"[“\"]([^”\"]{4,220})[”\"]", s)
                if m:
                    phrase = norm(m.group(1))
                if phrase and sp:
                    return f"  - \"{phrase}\" / {sp} ({press})"
                if phrase:
                    return f"  - \"{phrase}\" ({press})"
            return f"  - {s} ({press})"

        if facts:
            mat_lines.append("- 숫자/팩트(문장 그대로):")
            for lab, sent, press, url in facts:
                # drop meaningless '기간(보조)' unless it also contains money/%/indicator markers
                if lab == "기간(보조)" and not (MONEY_RE.search(sent) or PCT_RE.search(sent) or re.search(r"\b(환율|코스피|코스닥|지수|시가총액|금리)\b", sent)):
                    continue
                mat_lines.append(format_fact_line(sent, press))
                if url:
                    mat_lines.append(f"    {url}")

        # dedupe quotes
        seenq = set()
        quotes = []
        for sp, q, press, url in quote_pool:
            qn = norm(q)
            if not qn or qn in seenq:
                continue
            seenq.add(qn)
            quotes.append((sp, qn, press, url))
            if len(quotes) >= 4:
                break
        if quotes:
            mat_lines.append("- 발언/인용(직접 인용, 문장 그대로):")
            for sp, qn, press, url in quotes:
                speaker = sp if sp else "(발언자 미상)"
                mat_lines.append(f"  - {speaker}: \"{qn}\" ({press})")
                if url:
                    mat_lines.append(f"    {url}")

        # notable phrases
        if phrase_pool:
            mat_lines.append("- 표현(제목에서 포착):")
            # dedupe by (phrase, press)
            seen_ph = set()
            for ph, press, url in phrase_pool:
                key = (ph, press)
                if key in seen_ph:
                    continue
                seen_ph.add(key)
                mat_lines.append(f"  - {ph} ({press})")
                if url:
                    mat_lines.append(f"    {url}")
                if len(seen_ph) >= 6:
                    break

        # 온도차/체크포인트(가능하면 LLM으로 '차이만' 압축)
        # - angle_pool에서 언론사별 요약 1개씩만 뽑아서 사용
        press_sum = []
        usedp = set()
        for summ, press, url in angle_pool:
            if press in usedp:
                continue
            if not summ or is_caption_like(summ):
                continue
            usedp.add(press)
            press_sum.append((press, summ))

        # stage-2 context (preferred): use llm_ctx from representative full texts
        ctx = llm_ctx if isinstance(llm_ctx, dict) else {}
        temp_diff = norm(str(ctx.get("temp_diff", "")))
        press_lines = ctx.get("press_lines", {}) if isinstance(ctx.get("press_lines", {}), dict) else {}
        checkpoint_q = norm(str(ctx.get("checkpoint_q", "")))
        context_keywords = ctx.get("context_keywords", []) if isinstance(ctx.get("context_keywords", []), list) else []

        if temp_diff:
            mat_lines.append(f"- 온도차: {temp_diff}")
        if press_lines:
            mat_lines.append("- 신문별 한줄(차이만):")
            shown = 0
            for pr in sorted(press_lines.keys()):
                line = norm(str(press_lines.get(pr, "")))
                if not line:
                    continue
                mat_lines.append(f"  - {pr}: {line}")
                shown += 1
                if shown >= 4:
                    break
        if context_keywords:
            kws = ", ".join([norm(str(x)) for x in context_keywords if norm(str(x))][:3])
            if kws:
                mat_lines.append(f"- 붙일 맥락(키워드): {kws}")
        if checkpoint_q:
            mat_lines.append(f"- 체크포인트(질문): {checkpoint_q}")

        if not (temp_diff or press_lines or checkpoint_q or context_keywords):
            # fallback: keep concise per-press summaries
            if press_sum:
                mat_lines.append("- 신문별 한줄(원문 요약 기반):")
                for pr, summ in press_sum[:4]:
                    mat_lines.append(f"  - {pr}: {summ}")

        mat_lines.append("")

        # links
        link_lines.append(f"### {headline}")
        for _, r in g2.iterrows():
            press = str(r.get("press", "")).strip()
            title = norm(str(r.get("title", "")))
            naver_url = str(r.get("url", "")).strip()
            origin_url = str(r.get("origin_url", "")).strip()
            link_lines.append(f"- {press}: {title}")
            if origin_url:
                link_lines.append(f"  기사원문: {origin_url}")
            link_lines.append(f"  네이버: {naver_url}")
        link_lines.append("")

    # 목차(15개) 구성: kept_clusters 중 -1(기타) 제외, 앞에서부터 15개
    for it in kept_clusters:
        if it["cid"] == -1:
            continue
        toc_items.append(it)
        if len(toc_items) >= 15:
            break

    for idx, it in enumerate(toc_items, 1):
        title = it.get("rep_title") or it["headline"]
        presses2 = it["presses"]
        point2 = it.get("point", "")
        rep = it.get("rep_links", [])
        toc_lines.append(f"{idx}. {title} ({presses2})")
        if point2:
            toc_lines.append(f"   - 포인트: {point2}")
        for u in rep[:3]:
            toc_lines.append(f"   - {u}")
        toc_lines.append("")

    # 오늘의 핵심(편집용) 4개 선정(heuristic)
    def is_low_interest(title: str) -> bool:
        return bool(re.search(r"(피겨|쇼트|올림픽|야구|축구|농구|배구|연예|드라마|가수|배우|고양이|운세|부고|부음|만평|날씨|크로스워드)", title))

    def core_score(it: dict) -> int:
        t = (it.get("rep_title") or it.get("headline") or "")
        p = (it.get("point") or "")
        s = 0
        # 다언론/공적 키워드
        s += min(6, len([x for x in it.get("presses", "").split(",") if x.strip()]))
        for kw, w in [
            ("법원", 4), ("징역", 4), ("선고", 3), ("내란", 5), ("국회", 3), ("대법", 3), ("특검", 3),
            ("관세", 3), ("USTR", 3), ("부동산", 3), ("양도세", 3), ("해킹", 3), ("유출", 3),
            ("북한", 2), ("김여정", 2), ("무인기", 2),
        ]:
            if kw in t or kw in p:
                s += w
        if "\"" in p or "“" in p:
            s += 2
        if is_low_interest(t):
            s -= 6
        return s

    core_pool = [it for it in kept_clusters if it.get("cid") != -1]
    core_pool = sorted(core_pool, key=core_score, reverse=True)
    core_items = core_pool[:4]

    for idx, it in enumerate(core_items, 1):
        title = it.get("rep_title") or it["headline"]
        presses2 = it["presses"]
        point2 = it.get("point", "")
        rep = it.get("rep_links", [])
        top_lines.append(f"{idx}. {title} ({presses2})")
        if point2:
            top_lines.append(f"   - 결론: {point2}")
        # 논쟁축(온도차)이 있으면 1줄
        # (LLM 컨텍스트가 본문에 생성되므로 여기서는 대표 링크로만)
        for u in rep[:2]:
            top_lines.append(f"   - {u}")
        top_lines.append("")

    # materials 상단에 요약 레이어 + 목차 삽입
    insert_at = 6
    mat_lines[insert_at:insert_at] = top_lines + ["---", ""] + toc_lines + ["---", ""]

    # 관찰(누적): 오늘 관찰 후보를 observation_log.md에 누적 기록하고, 최근 기록을 materials에 붙임
    obs_candidates = []
    for it in kept_clusters:
        if it["cid"] == -1:
            continue
        if not OBS_TOPIC_RE.search(it["headline"]):
            continue
        obs_candidates.append(it)

    if obs_candidates:
        obs_candidates = obs_candidates[:5]
        with open(obs_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n## {args.date}\n")
            for it in obs_candidates:
                f.write(f"- {it['headline']}\n")
                if it.get("point"):
                    f.write(f"  포인트: {it['point']}\n")
                for u in (it.get("rep_links") or [])[:2]:
                    f.write(f"  {u}\n")
            f.write("\n")

    # 최근 관찰 로그(마지막 120줄 정도) 삽입
    if os.path.exists(obs_log_path):
        try:
            lines = open(obs_log_path, "r", encoding="utf-8").read().splitlines()
            tail = lines[-120:]
            if tail:
                mat_lines.append("---")
                mat_lines.append("")
                mat_lines.append("[관찰(누적)]")
                mat_lines.append("- 기준: 진행 중 이슈는 매일 누적. 큰 흐름이 잡힐 때만 본문 카드로 승격.")
                mat_lines.append("")
                mat_lines.extend(tail)
                mat_lines.append("")
        except Exception:
            pass

    # 소수지만 중요한 항목(클러스터 -1에서 골라 올리기)
    # - 지면 특성상 칼럼/기고/단독성 이슈가 여기로 몰리기 쉬움
    # - 숫자/직접 인용이 강한 항목을 우선
    misc_items = dfc[dfc["cluster_id"] == -1].copy()
    if len(misc_items):
        # 구석의 중요(편집용) 7개: misc에서 강한 재료만 뽑아 상단에 별도 제공
        misc_items_g = misc_items.copy()
        misc_items_g = misc_items_g[~misc_items_g.apply(drop_row, axis=1)]

        def gem_score(row) -> int:
            title = norm(str(row.get("title", "")))
            text = str(row.get("content", ""))
            if is_caption_like(title) or is_caption_like(text):
                pass
            if re.search(r"(부고|인사|만평|운세)", title):
                return -999
            nums = extract_number_facts(text, limit=6)
            qs = extract_direct_quotes(text, limit=4)
            s = 0
            s += min(4, len(nums))
            s += min(3, len(qs)) * 2
            if any(MONEY_RE.search(x) for _, x in nums):
                s += 2
            if any(PCT_RE.search(x) for _, x in nums):
                s += 1
            for kw, w in [("단독", 3), ("수사", 2), ("구속", 2), ("압수", 2), ("법원", 2), ("징역", 2), ("공소", 2), ("유출", 2), ("해킹", 2), ("특검", 2)]:
                if kw in title or kw in text:
                    s += w
            if is_low_interest(title):
                s -= 4
            return s

        misc_items_g["_gem"] = misc_items_g.apply(gem_score, axis=1)
        top_gems = misc_items_g.sort_values(["_gem"], ascending=False).head(7)

        if len(top_gems):
            for _, r in top_gems.iterrows():
                press = str(r.get("press", "")).strip()
                title = norm(str(r.get("title", "")))
                naver_url = str(r.get("url", "")).strip()
                origin_url = str(r.get("origin_url", "")).strip()
                url = origin_url or naver_url
                text = str(r.get("content", ""))

                gems_lines.append(f"- {press}: {title}")
                # 포인트 1줄: 인용구/발언자 우선, 없으면 숫자문장
                qs = extract_direct_quotes(text, limit=2)
                if qs:
                    sp, q = qs[0]
                    speaker = sp if sp else "(발언자 미상)"
                    m = re.search(r"[“\"]([^”\"]{4,220})[”\"]", q)
                    ph = norm(m.group(1)) if m else norm(q)
                    gems_lines.append(f"  포인트: \"{ph}\" / {speaker}")
                else:
                    nums = extract_number_facts(text, limit=2)
                    if nums:
                        gems_lines.append(f"  포인트: {nums[0][1]}")
                if url:
                    gems_lines.append(f"  {url}")
                gems_lines.append("")

            # 핵심 섹션 바로 아래에 삽입
            # (top_lines와 toc_lines는 이미 insert_at에 삽입되었으므로, 여기에 본문용으로 추가)
            mat_lines[insert_at + len(top_lines) + 2 : insert_at + len(top_lines) + 2] = gems_lines + ["---", ""]

        misc_items = misc_items[~misc_items.apply(drop_row, axis=1)]

        def item_score(row) -> int:
            text = str(row.get("content", ""))
            nums = extract_number_facts(text, limit=10)
            qs = extract_direct_quotes(text, limit=10)
            title = norm(str(row.get("title", "")))
            score = 0
            score += min(6, len(nums)) * 2
            score += min(4, len(qs)) * 3
            # 금액/퍼센트 포함 문장 보너스
            if any(MONEY_RE.search(s) for _, s in nums):
                score += 3
            if any(PCT_RE.search(s) for _, s in nums):
                score += 2
            # '여자 아베' 같은 강한 표현 보너스
            if "여자 아베" in title:
                score += 3
            return score

        misc_items["_score"] = misc_items.apply(item_score, axis=1)
        misc_items = misc_items.sort_values(["_score"], ascending=False)
        top_misc = misc_items.head(25)

        if len(top_misc):
            mat_lines.append("---")
            mat_lines.append("")
            mat_lines.append("[소수지만 중요한 항목]")
            mat_lines.append("- 기준: 지면 전체 중 '단독/소수'로 남았지만 숫자/직접 인용이 강한 항목")
            mat_lines.append("")

            link_lines.append("---")
            link_lines.append("")
            link_lines.append("[소수지만 중요한 항목 링크]")
            link_lines.append("")

            for _, r in top_misc.iterrows():
                press = str(r.get("press", "")).strip()
                title = norm(str(r.get("title", "")))
                naver_url = str(r.get("url", "")).strip()
                origin_url = str(r.get("origin_url", "")).strip()
                url = origin_url or naver_url
                text = str(r.get("content", ""))

                mat_lines.append(f"- {press}: {title}")
                if url:
                    mat_lines.append(f"  {url}")

                nums = extract_number_facts(text, limit=3)
                if nums:
                    mat_lines.append("  숫자/팩트:")
                    for lab, sent in nums[:3]:
                        if lab == "기간(보조)" and not (MONEY_RE.search(sent) or PCT_RE.search(sent) or re.search(r"\b(환율|코스피|코스닥|지수|시가총액|금리)\b", sent)):
                            continue
                        # keep quote phrases readable
                        s2 = norm(sent)
                        if any(ch in s2 for ch in QUOTE_CHARS):
                            sp2 = extract_speaker_from_quote_sentence(s2)
                            m2 = re.search(r"[“\"]([^”\"]{4,220})[”\"]", s2)
                            ph2 = norm(m2.group(1)) if m2 else ""
                            if ph2 and sp2:
                                mat_lines.append(f"  - \"{ph2}\" / {sp2}")
                            elif ph2:
                                mat_lines.append(f"  - \"{ph2}\"")
                            else:
                                mat_lines.append(f"  - {s2}")
                        else:
                            mat_lines.append(f"  - {s2}")

                qs = extract_direct_quotes(text, limit=1)
                if qs:
                    sp, q = qs[0]
                    speaker = sp if sp else "(발언자 미상)"
                    mat_lines.append(f"  인용: {speaker}: \"{norm(q)}\"")

                summ = norm(str(r.get("summary_2sent", "")))
                if summ:
                    mat_lines.append(f"  앵글: {summ}")

                mat_lines.append("")

                link_lines.append(f"- {press}: {title}")
                if origin_url:
                    link_lines.append(f"  기사원문: {origin_url}")
                link_lines.append(f"  네이버: {naver_url}")

            link_lines.append("")

        # 읽을만한 자잘한 것: C(자동) 운영
        # - 공적 가치(우선) + 재미(있으면) 가점을 주되, 시간 낭비 항목은 배제
        # - 기본은 misc(-1)에서만 뽑아 과잉 노이즈를 줄임
        def is_time_waste(title: str, text: str) -> bool:
            s = f"{title} {text}"
            # 광고/홍보/생활정보/연예/스포츠/운세 등
            waste = [
                r"\b운세\b",
                r"\b부고\b",
                r"\b인사\b",
                r"\b만평\b",
                r"\b포토\b",
                r"\b올림픽\b",
                r"\b메달\b",
                r"\b선수\b",
                r"\b경기\b",
                r"\b카지노\b",
                r"\b이벤트\b",
                r"\b경품\b",
                r"\b리조트\b",
                r"\b연예\b",
            ]
            return any(re.search(p, s) for p in waste)

        PUBLIC_KW = [
            # 권력/책임/제도
            "단독",
            "수사",
            "검찰",
            "경찰",
            "법원",
            "재판",
            "공소",
            "기각",
            "무죄",
            "구속",
            "압수수색",
            "특검",
            "감사",
            "징계",
            "청문",
            # 안전/권리/복지
            "학대",
            "피해",
            "장애",
            "환자",
            "의료",
            "요양",
            "돌봄",
            "산재",
            # 경제/소비자/데이터
            "유출",
            "해킹",
            "개인정보",
            "불공정",
            "담합",
            "탈세",
            "환불",
            "피해액",
            # 안보/통상
            "무인기",
            "침투",
            "관세",
            "USTR",
        ]

        FUN_KW = [
            "이런",
            "왜",
            "논란",
            "반전",
            "충격",
            "아이러니",
            "정작",
            "드러났다",
            "비꼬",
        ]

        def small_read_score(row) -> int:
            title = norm(str(row.get("title", "")))
            text = str(row.get("content", ""))
            if is_time_waste(title, text):
                return -999
            nums = extract_number_facts(text, limit=6)
            qs = extract_direct_quotes(text, limit=3)

            score = 0
            # 공적 가치 우선
            score += sum(2 for k in PUBLIC_KW if k in title) + sum(1 for k in PUBLIC_KW if k in text)
            # 재미(있으면)
            score += sum(1 for k in FUN_KW if k in title)
            # 숫자/인용 보조
            score += min(len(nums), 4)
            score += min(len(qs), 2)
            # 강한 숫자(돈/퍼센트) 보너스
            if any(MONEY_RE.search(s) for _, s in nums):
                score += 2
            if any(PCT_RE.search(s) for _, s in nums):
                score += 1
            return score

        misc_items2 = misc_items.copy()
        misc_items2["_read_score"] = misc_items2.apply(small_read_score, axis=1)
        misc_items2 = misc_items2[misc_items2["_read_score"] >= 6]
        # top_misc에 이미 포함된 건 제외
        if len(top_misc):
            used_urls = set((top_misc["origin_url"].fillna("") + "|" + top_misc["url"].fillna("")).tolist())
            misc_items2 = misc_items2[~((misc_items2["origin_url"].fillna("") + "|" + misc_items2["url"].fillna("")).isin(used_urls))]

        misc_items2 = misc_items2.sort_values(["_read_score"], ascending=False).head(10)

        if len(misc_items2):
            mat_lines.append("---")
            mat_lines.append("")
            mat_lines.append("[읽을만한 자잘한 것]")
            mat_lines.append("- 기준: 공적 가치 우선 + (있으면) 재미. 읽을 시간을 들일만한 항목만.")
            mat_lines.append("")

            link_lines.append("---")
            link_lines.append("")
            link_lines.append("[읽을만한 자잘한 것 링크]")
            link_lines.append("")

            for _, r in misc_items2.iterrows():
                press = str(r.get("press", "")).strip()
                title = norm(str(r.get("title", "")))
                naver_url = str(r.get("url", "")).strip()
                origin_url = str(r.get("origin_url", "")).strip()
                url = origin_url or naver_url
                text = str(r.get("content", ""))

                # 3줄 템플릿(복붙)
                mat_lines.append(f"- {press}: {title}")

                # 한 줄 근거: 숫자/인용 중 1개를 골라 '읽을 포인트'로
                point = ""
                nums = extract_number_facts(text, limit=3)
                qs = extract_direct_quotes(text, limit=2)
                if nums:
                    # avoid low-value '기간(보조)' and caption-like sentences for the point line
                    chosen = None
                    for lab, sent in nums:
                        if is_caption_like(sent):
                            continue
                        if lab == "기간(보조)" and not (
                            MONEY_RE.search(sent)
                            or PCT_RE.search(sent)
                            or re.search(r"\b(환율|코스피|코스닥|지수|시가총액|금리)\b", sent)
                        ):
                            continue
                        chosen = (lab, sent)
                        break
                    if not chosen:
                        chosen = nums[0]
                    lab, sent = chosen
                    point = f"  포인트: [{lab}] {sent}"
                elif qs:
                    sp, q = qs[0]
                    speaker = sp if sp else "(발언자 미상)"
                    point = f"  포인트: {speaker}: \"{norm(q)}\""
                else:
                    summ = norm(str(r.get("summary_2sent", "")))
                    if summ:
                        point = f"  포인트: {summ}"
                if point:
                    mat_lines.append(point)

                if url:
                    mat_lines.append(f"  {url}")
                mat_lines.append("")

                link_lines.append(f"- {press}: {title}")
                if origin_url:
                    link_lines.append(f"  기사원문: {origin_url}")
                link_lines.append(f"  네이버: {naver_url}")

            link_lines.append("")

    out_mat = os.path.join(dl, f"newspaper_clusters_materials_{args.date}.md")
    out_links = os.path.join(dl, f"newspaper_clusters_links_{args.date}.md")

    with open(out_mat, "w", encoding="utf-8") as f:
        f.write("\n".join(mat_lines).rstrip() + "\n")
    with open(out_links, "w", encoding="utf-8") as f:
        f.write("\n".join(link_lines).rstrip() + "\n")

    print("saved:", out_mat)
    print("saved:", out_links)

    # Auto-generate HTML version
    converter_script = os.path.join(os.path.dirname(__file__), "convert_materials_to_html.py")
    if os.path.exists(converter_script):
        try:
            subprocess.run([sys.executable, converter_script, args.date], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[warn] HTML conversion failed: {e}")
    else:
        print(f"[warn] HTML converter not found: {converter_script}")


if __name__ == "__main__":
    main()
