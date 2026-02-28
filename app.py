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

# Sidebar 색상 등 간단한 스타일 오버라이드
st.markdown(
    """
    <style>
      /* === Layout alignment (sidebar vs main top) === */
      section.main .block-container {
        padding-top: 2.25rem;
      }
      section[data-testid="stSidebar"] > div {
        padding-top: 2.25rem;
      }

      /* === Main theme === */
      html, body, [data-testid="stAppViewContainer"] {
        background-color: #000000;
      }
      [data-testid="stAppViewContainer"] * {
        color: #ffffff;
      }
      /* main 영역 링크는 슬로우 컬러 */
      [data-testid="stAppViewContainer"] a {
        color: #fdad00 !important;
        text-decoration: none !important;
      }

      /* 입력창 스타일 (검정 배경에서 가독성) */
      [data-testid="stTextInput"] input {
        background-color: #111111 !important;
        color: #ffffff !important;
        border: 1px solid #333333 !important;
      }
      [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background-color: #111111 !important;
        color: #ffffff !important;
        border: 1px solid #333333 !important;
      }

      /* 분석하기 버튼 색 */
      button[kind="primary"],
      div.stButton > button[kind="primary"] {
        background-color: #fdad00 !important;
        border: 1px solid #fdad00 !important;
        color: #111111 !important;
      }

      /* === Sidebar theme (SlowNews company color) === */
      section[data-testid="stSidebar"] {
        background-color: #fdad00;
      }
      /* 사이드바 내 텍스트 가독성 */
      section[data-testid="stSidebar"] * {
        color: #111111;
      }
      /* 사이드바 링크도 검정으로(가독성/통일) */
      section[data-testid="stSidebar"] a {
        color: #111111 !important;
      }
      /* Streamlit status box(성공/에러) 글자 대비 */
      section[data-testid="stSidebar"] [data-testid="stAlert"] * {
        color: #111111 !important;
      }

      /* === Title style === */
      h1 a, h1 a:visited {
        color: #fdad00 !important;
        text-decoration: none;
      }
      h1 a:hover {
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
    cutoff_ratio = 0.35
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
    st.markdown("### 📝 분석 결과:")
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
            title = ensure_period(r.get("title", ""))
            date = r.get("date", "")
            link = f"{BASE_PUBLIC_URL}/?doc={doc_id}" if doc_id else ""

            if link:
                st.markdown(f"{i}. ({date}) [{title}]({link})")
            else:
                st.markdown(f"{i}. ({date}) {title}")


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


# ===== 사이드바 =====
HOME_URL = f"{BASE_PUBLIC_URL}/"

with st.sidebar:
    st.markdown(
        '<a href="https://slownews.kr" target="_blank"><img src="https://img.stibee.com/d846e0cc-c5fc-4bb4-b18f-e064a51c1cd2.png" style="width:100%;"></a>',
        unsafe_allow_html=True,
    )

    n_archives = get_archive_count()
    if n_archives is not None:
        st.markdown(f"<div style='font-size:1.3rem;font-weight:700;margin:0.5rem 0 1rem 0.4rem;'>{n_archives:,}<span style='font-size:0.75rem;font-weight:400;color:#666;'> 건.</span></div>", unsafe_allow_html=True)

    api_ok = check_api()
    if api_ok:
        st.success("✅ API 연결됨.")
    else:
        st.error("❌ API 연결 안 됨.")

    mode = st.radio("Mode", ["맥락 분석.", "타임라인.", "트렌드."], index=0, label_visibility="collapsed")

    st.markdown("---")
    st.info("[🔍 슬로우레터 빠른 검색.](/)")
    st.info("[📝 컨텍스트 분석(후원회원 전용).](/context/)")


# ===== 채팅 모드 =====
if mode == "맥락 분석.":
    st.markdown(f"# [슬로우 컨텍스트.]({HOME_URL})")
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
    question, _, submitted = render_query_bar(text_key="q_input", disabled=not api_ok)

    if doc_param:
        doc = get_doc(str(doc_param))
        if doc:
            st.markdown("---")
            st.header(f"{doc.get('title','')}")
            st.caption(f"{doc.get('date','')} | {doc.get('doc_id','')}")
            with st.expander("원문.", expanded=True):
                st.markdown(doc.get("content", ""))
            if st.button("목록으로."):
                try:
                    if q_param:
                        st.query_params.clear()
                        st.query_params["q"] = q_param
                    else:
                        st.query_params.clear()
                except Exception:
                    if q_param:
                        st.experimental_set_query_params(q=q_param)
                    else:
                        st.experimental_set_query_params()
                st.rerun()
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


# ===== 타임라인 모드 =====
elif mode == "타임라인.":
    st.markdown(f"# [슬로우 컨텍스트.]({HOME_URL})")
    st.markdown("Slow Context: 이슈의 타임라인.")

    entity_name, granularity, submitted = render_query_bar(
        text_key="timeline_entity",
        select_key="timeline_gran",
        select_options=["month", "week", "day"],
        disabled=not api_ok,
    )

    if submitted and entity_name:
        with st.spinner("조회 중..."):
            timeline = get_timeline(entity_name, granularity or "month")

        if timeline:
            st.markdown(f"**'{entity_name}' 보도 타임라인** ({len(timeline)}개 기간)")

            # 차트
            try:
                import pandas as pd
                df = pd.DataFrame(timeline)
                df["period"] = df["period"].astype(str)
                st.bar_chart(df.set_index("period")["doc_count"])
            except ImportError:
                for entry in timeline:
                    bar = "█" * min(entry["doc_count"], 50)
                    st.text(f"{entry['period']}: {entry['doc_count']:3d}건 {bar}")

            # 상세
            with st.expander("상세 보기"):
                for entry in timeline:
                    titles = " / ".join(entry["titles"][:3])
                    st.markdown(f"**{entry['period']}** — {entry['doc_count']}건")
                    st.caption(titles)
        else:
            st.warning(f"'{entity_name}'에 대한 데이터가 없습니다.")


# ===== 트렌드 모드 =====
elif mode == "트렌드.":
    st.markdown(f"# [슬로우 컨텍스트.]({HOME_URL})")
    st.markdown("Slow Context: 이슈의 구조와 맥락 읽기.")

    keyword, t_granularity, submitted = render_query_bar(
        text_key="trend_keyword",
        select_key="trend_gran",
        select_options=["month", "day"],
        disabled=not api_ok,
    )

    if submitted and keyword:
        with st.spinner("분석 중..."):
            trend = get_trend(keyword, t_granularity or "month")

        if trend and trend.get("timeline"):
            # 요약
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("총 문서 수", f"{trend['total_count']}건")
            with col2:
                st.metric("분석 기간", f"{len(trend['timeline'])}개 구간")
            with col3:
                if trend.get("co_entities"):
                    st.metric("관련 엔티티", f"{len(trend['co_entities'])}개")

            # 빈도 차트
            st.markdown("#### 기간별 빈도")
            try:
                import pandas as pd
                df = pd.DataFrame(trend["timeline"])
                df["period"] = df["period"].astype(str)
                st.bar_chart(df.set_index("period")["count"])
            except ImportError:
                for entry in trend["timeline"]:
                    bar = "█" * min(entry["count"], 50)
                    st.text(f"{entry['period']}: {entry['count']:3d}건 {bar}")

            # 공출현 엔티티
            if trend.get("co_entities"):
                st.markdown("#### 함께 언급된 엔티티")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**인물**")
                    for ent in trend["co_entities"]:
                        if ent["type"] == "person":
                            st.markdown(f"- {ent['name']} ({ent['count']}회)")
                with col2:
                    st.markdown("**조직**")
                    for ent in trend["co_entities"]:
                        if ent["type"] == "organization":
                            st.markdown(f"- {ent['name']} ({ent['count']}회)")

            # 대표 문서
            if trend.get("representative_docs"):
                st.markdown("#### 대표 문서")
                for doc in trend["representative_docs"][:5]:
                    st.markdown(f"**({doc['date']}) {doc['title']}**")
                    st.caption(f"{doc['snippet']}...")
        else:
            st.warning(f"'{keyword}'에 대한 트렌드 데이터가 없습니다.")
