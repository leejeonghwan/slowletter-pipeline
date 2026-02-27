"""
SlowLetter RAG - Streamlit 웹 UI
채팅 + 타임라인 + 트렌드 시각화
(Streamlit 구버전 호환)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import streamlit as st
import requests
import sqlite3
from urllib.parse import quote

API_URL = "http://localhost:8000"
BASE_PUBLIC_URL = "https://slownews.net"

st.set_page_config(page_title="슬로우 컨텍스트", page_icon="📰", layout="wide")

# 스타일: index.html과 동일하게
st.markdown(
    """
    <style>
      /* === Layout alignment === */
      section.main .block-container {
        padding-top: 2.25rem;
      }
      section[data-testid="stSidebar"] > div {
        padding-top: 2.25rem;
      }

      /* === Main theme === */
      html, body, [data-testid="stAppViewContainer"] {
        background-color: #fafaf9;
      }
      [data-testid="stAppViewContainer"] * {
        color: #111111;
      }
      /* main 영역 링크 */
      [data-testid="stAppViewContainer"] a {
        color: #fdad00 !important;
        text-decoration: none !important;
      }

      /* 입력창 스타일: 흰색 배경, 검정 글씨 (index.html과 동일) */
      [data-testid="stTextInput"] input {
        background-color: #ffffff !important;
        color: #111111 !important;
        border: 1px solid rgba(0,0,0,0.18) !important;
        border-radius: 6px !important;
        padding: 0.6rem 0.85rem !important;
        font-size: 0.95rem !important;
      }
      [data-testid="stTextInput"] input::placeholder {
        color: rgba(0,0,0,0.55) !important;
      }
      [data-testid="stTextInput"] input:focus {
        border-color: #fdad00 !important;
        box-shadow: 0 0 0 2px rgba(253,173,0,0.1) !important;
      }
      
      [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: #111111 !important;
        border: 1px solid rgba(0,0,0,0.18) !important;
      }

      /* 버튼 */
      button[kind="primary"],
      div.stButton > button[kind="primary"] {
        background-color: #fdad00 !important;
        border: 1px solid #fdad00 !important;
        color: #111111 !important;
      }

      /* === Sidebar (index.html과 동일) === */
      section[data-testid="stSidebar"] {
        background-color: #1c1917 !important;
      }
      section[data-testid="stSidebar"] * {
        color: #e7e5e4 !important;
      }
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3 {
        color: #fdad00 !important;
        font-weight: 700 !important;
      }
      section[data-testid="stSidebar"] a {
        color: #e7e5e4 !important;
        text-decoration: none !important;
      }
      section[data-testid="stSidebar"] a:hover {
        background: #333 !important;
      }
      section[data-testid="stSidebar"] [data-testid="stAlert"] * {
        color: #111111 !important;
      }

      /* Title */
      h1 a, h1 a:visited {
        color: #111111 !important;
        text-decoration: none;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def check_api():
    try:
        r = requests.get(f"{API_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


from typing import Optional


def get_archive_count() -> Optional[int]:
    """로컬 SQLite 기준 문서 수를 반환합니다(가능하면 자동 표시)."""
    try:
        conn = sqlite3.connect("data/processed/entities.db")
        cur = conn.execute("SELECT COUNT(*) FROM documents")
        n = int(cur.fetchone()[0])
        conn.close()
        return n
    except Exception:
        return None


def get_date_range() -> Optional[str]:
    """로컬 SQLite 기준 날짜 범위를 반환합니다."""
    try:
        conn = sqlite3.connect("data/processed/entities.db")
        cur = conn.execute("SELECT MIN(date), MAX(date) FROM documents")
        min_date, max_date = cur.fetchone()
        conn.close()
        if min_date and max_date:
            return f"{min_date} ~ {max_date}"
        return None
    except Exception:
        return None


def ensure_period(text: str) -> str:
    """답변 끝에 마침표를 보정합니다."""
    if text is None:
        return "."
    t = text.strip()
    if not t:
        return "."
    if t.endswith((".", "!", "?", "…", "。", ":", ")", "\"", "%")):
        return t
    return t + "."


def fix_answer_lines(answer: str) -> str:
    """답변의 각 줄에 마침표 추가"""
    if not answer:
        return answer
    
    lines = answer.split("\n")
    fixed_lines = []
    
    for line in lines:
        # 빈 줄이나 제목(#), 구분선(---)은 그대로
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            fixed_lines.append(line)
            continue
        
        # 나머지 줄은 마침표 보정
        fixed_lines.append(ensure_period(line))
    
    return "\n".join(fixed_lines)


def query_agent(question):
    try:
        r = requests.post(f"{API_URL}/query", json={"question": question}, timeout=180)
        if r.status_code != 200:
            # FastAPI가 500일 때 text/plain으로 내려주는 경우가 있어 json 파싱을 피한다.
            return {
                "answer": f"오류: API {r.status_code} - {r.text.strip()[:800]}",
                "tool_calls": [],
                "rounds": 0,
            }
        try:
            return r.json()
        except Exception:
            return {
                "answer": f"오류: Invalid JSON response - {r.text.strip()[:800]}",
                "tool_calls": [],
                "rounds": 0,
            }
    except Exception as e:
        return {"answer": f"오류: {str(e)}", "tool_calls": [], "rounds": 0}


def get_doc(doc_id: str) -> dict:
    try:
        r = requests.get(f"{API_URL}/doc/{doc_id}", timeout=20)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def get_timeline(entity_name, granularity="month"):
    try:
        r = requests.post(f"{API_URL}/timeline", json={"entity_name": entity_name, "granularity": granularity}, timeout=30)
        return r.json().get("timeline", [])
    except Exception:
        return []


def get_trend(keyword, granularity="month"):
    try:
        r = requests.post(f"{API_URL}/trend", json={"keyword": keyword, "granularity": granularity}, timeout=30)
        return r.json()
    except Exception:
        return {}


def _evidence_score(r: dict) -> float:
    """검색 결과의 상대 점수를 계산한다.

    - 하이브리드 점수(hybrid_score)가 있으면 우선.
    - 없으면 BM25 점수(score)를 사용한다.
    """
    try:
        hs = float(r.get("hybrid_score") or 0.0)
    except Exception:
        hs = 0.0
    try:
        bs = float(r.get("score") or 0.0)
    except Exception:
        bs = 0.0
    return hs if hs > 0 else bs


def _select_evidence(refs: list[dict], max_items: int = 10) -> list[dict]:
    """최대 max_items에서, 관련도가 낮으면 자동으로 줄인다."""
    if not refs:
        return []

    refs = list(refs)[:max_items]

    scores = [_evidence_score(r) for r in refs]
    best = max(scores) if scores else 0.0
    if best <= 0:
        # 점수 체계가 없거나 전부 0이면 상위 3개까지만.
        return refs[: min(3, len(refs))]

    # 최고 점수 대비 비율로 컷.
    # 너무 빡세면 근거가 0이 되니 최소 1개 보장.
    cutoff_ratio = 0.4
    selected = [r for r in refs if _evidence_score(r) >= best * cutoff_ratio]
    if not selected:
        return refs[:1]
    return selected


def render_answer_and_evidence(question: str, api_ok: bool):
    if not api_ok:
        st.error("❌ API Server disconnected.")
        return

    with st.spinner("분석 중... (최대 1~2분 소요)"):
        result = query_agent(question)

    st.markdown("---")
    st.markdown("### 📝 답변:")
    st.markdown(fix_answer_lines(result.get("answer", "")))

    st.markdown("---")
    st.subheader("텍스트.")
    try:
        s = requests.post(
            f"{API_URL}/search",
            json={"query": question, "top_k": 30},
            timeout=30,
        )
        payload = s.json() if s.status_code == 200 else {"results": []}
        refs = payload.get("results", []) or []
    except Exception:
        refs = []

    refs = _select_evidence(refs, max_items=30)

    if not refs:
        st.caption("관련 문서를 찾지 못했다.")
    else:
        for i, r in enumerate(refs, 1):
            doc_id = r.get("doc_id", "")
            title = r.get("title", "")
            date = r.get("date", "")
            permalink = f"{BASE_PUBLIC_URL}/?doc={doc_id}" if doc_id else ""

            # 제목에 permalink 임베드, 새 탭에서 열기
            if permalink:
                st.markdown(f'{i}. ({date}) <a href="{permalink}" target="_blank">{ensure_period(title)}</a>', unsafe_allow_html=True)
            else:
                st.markdown(f"{i}. ({date}) {ensure_period(title)}")


from typing import List


def render_query_bar(
    text_key: str,
    select_key: Optional[str] = None,
    select_options: Optional[List[str]] = None,
    disabled: bool = False,
):
    """모든 화면에서 같은 위치/형태의 입력 바를 만든다."""

    with st.form(f"form_{text_key}", clear_on_submit=False):
        col1, col2 = st.columns([4, 1])
        with col1:
            text = st.text_input(
                "query",
                value=st.session_state.get(text_key, ""),
                key=text_key,
                label_visibility="collapsed",
                disabled=disabled,
            )
        sel = None
        if select_key and select_options:
            with col2:
                sel = st.selectbox(
                    "granularity",
                    select_options,
                    index=0,
                    key=select_key,
                    label_visibility="collapsed",
                    disabled=disabled,
                )
        else:
            with col2:
                st.markdown(" ")
        submitted = st.form_submit_button("분석하기.", type="primary", disabled=disabled)

    return text, sel, submitted


# ===== 사이드바 (index.html과 동일) =====
HOME_URL = f"{BASE_PUBLIC_URL}/"

with st.sidebar:
    st.markdown("## 슬로우 컨텍스트.")
    st.markdown('<div style="font-size:0.75rem;color:#a8a29e;margin-bottom:1.5rem;">Slow Context.</div>', unsafe_allow_html=True)

    # 아카이브 수
    st.markdown('<div style="font-size:0.7rem;color:#a8a29e;margin-bottom:0.2rem;text-transform:uppercase;letter-spacing:0.05em;">아카이브.</div>', unsafe_allow_html=True)
    n_archives = get_archive_count()
    if n_archives is not None:
        st.markdown(f'<div style="font-size:1.3rem;font-weight:700;color:#ffffff;margin-bottom:1rem;">{n_archives:,}<span style="font-size:0.75rem;font-weight:400;color:#a8a29e;"> 건.</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:1.3rem;font-weight:700;color:#ffffff;margin-bottom:1rem;">-<span style="font-size:0.75rem;font-weight:400;color:#a8a29e;"> 건.</span></div>', unsafe_allow_html=True)

    # 기간
    st.markdown('<div style="font-size:0.7rem;color:#a8a29e;margin-bottom:0.2rem;text-transform:uppercase;letter-spacing:0.05em;">기간.</div>', unsafe_allow_html=True)
    date_range = get_date_range()
    if date_range:
        st.markdown(f'<div style="font-size:0.75rem;color:#a8a29e;margin-bottom:1rem;">{date_range}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:0.75rem;color:#a8a29e;margin-bottom:1rem;">로딩 중...</div>', unsafe_allow_html=True)

    st.markdown("---")

    # 네비게이션
    st.markdown(f'<a href="/" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#e7e5e4;text-decoration:none;">Archives Search.</a>', unsafe_allow_html=True)
    st.markdown(f'<a href="/context/" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#1c1917;background:#fdad00;font-weight:600;text-decoration:none;">Context Analytics(AI).</a>', unsafe_allow_html=True)
    st.markdown(f'<a href="https://slownews.kr" target="_blank" rel="noopener" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#e7e5e4;text-decoration:none;">Slow News.</a>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div style="font-size:0.65rem;color:#57534e;">slownews.net</div>', unsafe_allow_html=True)

    # API 상태는 숨김 (필요시 로그로만 확인)
    api_ok = check_api()


# ===== 메인 (채팅 모드 전용) =====
st.markdown(f"# [SlowLetter Context Analytics(AI).]({HOME_URL})")
st.markdown("Slow Context: 슬로우레터 기반의 맥락 분석 서비스.")

# permalink 진입 시 단건 문서 뷰
try:
    qp = st.query_params  # streamlit 최신
except Exception:
    qp = st.experimental_get_query_params()  # 구버전 호환

doc_param = None
q_param = None
try:
    doc_param = qp.get("doc")
    q_param = qp.get("q")
    if isinstance(doc_param, list):
        doc_param = doc_param[0] if doc_param else None
    if isinstance(q_param, list):
        q_param = q_param[0] if q_param else None
except Exception:
    doc_param = None
    q_param = None

# 채팅에서도 입력 바를 최상단(부제 아래) 고정.
default_q = st.session_state.pop("question_input", "")
if q_param and not default_q:
    default_q = str(q_param)

# Streamlit은 입력 시마다 rerun하므로, 매번 값을 덮어쓰면 타이핑이 막힌다.
if "q_input" not in st.session_state:
    st.session_state["q_input"] = default_q

# 개별 기사 페이지에서는 검색바 숨김
if not doc_param:
    question, _, submitted = render_query_bar(text_key="q_input", disabled=not api_ok)
else:
    question = ""
    submitted = False

if doc_param:
    doc = get_doc(str(doc_param))
    if doc:
        st.markdown("---")
        st.header(f"{doc.get('title','')}")
        st.caption(f"{doc.get('date','')}")
        # 불릿 앞 줄바꿈 <br> 변환
        content = doc.get("content", "").replace("• ", "<br>• ")
        st.markdown(content, unsafe_allow_html=True)
    else:
        st.warning("문서를 찾지 못했다.")

st.markdown("---")

# q=로 들어온 경우, 1회 자동 실행.
# 문서(permalink) 뷰에서는 자동 실행하지 않는다.
auto_key = f"auto_ran::{question}"
should_auto_run = (
    bool(q_param)
    and bool(question)
    and (not doc_param)
    and (not st.session_state.get(auto_key))
)

if (submitted and question) or should_auto_run:
    st.session_state[auto_key] = True
    render_answer_and_evidence(question, api_ok)

# 대화 이력
if "history" not in st.session_state:
    st.session_state.history = []

if question and st.session_state.get("last_q") != question:
    st.session_state.last_q = question
