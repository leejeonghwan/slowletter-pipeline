"""
SlowLetter RAG - Streamlit 웹 UI
채팅 + 타임라인 + 트렌드 시각화
쿠키 기반 간단 인증 · Finder와 동일 고정 사이드바
"""
import os
import re
import sys
import hashlib
import html as html_mod
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import streamlit as st
import requests

API_URL = "http://localhost:8000"

# ===== 인증 설정 =====
# REQUIRE_LOGIN = True 로 바꾸면 비밀번호 로그인이 활성화됩니다.
REQUIRE_LOGIN = False
ACCESS_PASSWORDS = ["preview", "justice"]

st.set_page_config(page_title="Slow Context.", page_icon="📰", layout="wide",
                   initial_sidebar_state="collapsed")

# ===== 전역 스타일 =====
st.markdown("""
<style>
/* Streamlit 기본 배경 */
.stApp, [data-testid="stAppViewContainer"], .main .block-container {
    background-color: #fdad00 !important;
}
header[data-testid="stHeader"] {
    background-color: #fdad00 !important;
}

/* Streamlit 기본 사이드바 숨기기 */
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
button[kind="headerNoPadding"] { display: none !important; }

/* 고정 사이드바 (index.html과 동일) */
.fixed-sidebar {
    position: fixed; top: 0; left: 0;
    width: 240px; height: 100vh;
    background: #1c1917; color: #e7e5e4;
    padding: 1.5rem 1.2rem;
    display: flex; flex-direction: column;
    z-index: 999;
    overflow-y: auto;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.fixed-sidebar h2 { font-size: 1.1rem; font-weight: 700; color: #fdad00; margin: 0 0 0.25rem 0; }
.fixed-sidebar .sub { font-size: 0.75rem; color: #a8a29e; margin-bottom: 1.5rem; }
.fixed-sidebar .divider { border: none; border-top: 1px solid #333; margin: 1rem 0; }
.fixed-sidebar .stat-label { font-size: 0.7rem; color: #a8a29e; margin-bottom: 0.2rem; text-transform: uppercase; letter-spacing: 0.05em; }
.fixed-sidebar .stat-value { font-size: 1.3rem; font-weight: 700; color: #ffffff; margin-bottom: 1rem; }
.fixed-sidebar .stat-value .unit { font-size: 0.75rem; font-weight: 400; color: #a8a29e; }
.fixed-sidebar .date-range { font-size: 0.75rem; color: #a8a29e; margin-bottom: 1rem; }
.fixed-sidebar .nav-link {
    display: block; padding: 0.6rem 0.8rem; margin-bottom: 0.4rem;
    border-radius: 6px; font-size: 0.85rem; color: #e7e5e4;
    text-decoration: none; transition: background 0.15s;
}
.fixed-sidebar .nav-link:hover { background: #333; }
.fixed-sidebar .nav-link.active { background: #fdad00; color: #1c1917; font-weight: 600; }
.fixed-sidebar .sidebar-footer { margin-top: auto; font-size: 0.65rem; color: #57534e; }

/* 메인 콘텐츠를 사이드바 너비만큼 밀기 */
.main .block-container {
    margin-left: 240px !important;
    max-width: calc(100% - 240px) !important;
    padding: 2rem 2rem !important;
}

/* 입력 필드 — index.html .search-box 동일 */
.stTextInput input, .stSelectbox select {
    background-color: #ffffff !important;
    color: #1c1917 !important;
    border: 1px solid rgba(0,0,0,0.18) !important;
    border-radius: 6px !important;
    padding: 0.6rem 0.85rem !important;
    font-size: 0.95rem !important;
}
.stTextInput input:focus {
    border-color: #0369a1 !important;
    box-shadow: 0 0 0 2px #e0f2fe !important;
}

/* 분석 시작 버튼 — index.html sortSelect 자리 */
.stFormSubmitButton button {
    background-color: #1c1917 !important;
    color: #fdad00 !important;
    border: 1px solid rgba(0,0,0,0.18) !important;
    border-radius: 6px !important;
    padding: 0.6rem 1rem !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    white-space: nowrap !important;
}
.stFormSubmitButton button:hover {
    background-color: #fdad00 !important;
    color: #1c1917 !important;
}

/* 예시 질문 버튼 */
.stButton button {
    background-color: transparent !important;
    color: #57534e !important;
    border: 1px solid rgba(0,0,0,0.12) !important;
    border-radius: 6px !important;
    font-size: 0.8rem !important;
    padding: 0.4rem 0.8rem !important;
}
.stButton button:hover {
    background-color: #ffffff !important;
    color: #1c1917 !important;
}

/* form 하단 여백 줄이기 */
[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
}

/* ===== RAG 답변 카드 스타일 ===== */
.answer-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 2rem;
    margin: 1.5rem 0;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    border-left: 4px solid #fdad00;
}
.answer-card .answer-header {
    display: flex; align-items: center; gap: 0.5rem;
    margin-bottom: 1rem; padding-bottom: 0.75rem;
    border-bottom: 1px solid #f0f0f0;
}
.answer-card .answer-header .icon { font-size: 1.2rem; }
.answer-card .answer-header .label {
    font-size: 0.85rem; font-weight: 600; color: #1c1917;
    text-transform: uppercase; letter-spacing: 0.03em;
}
.answer-card .answer-body {
    font-size: 0.95rem; line-height: 1.75; color: #1c1917;
}
.answer-card .answer-body p { margin-bottom: 0.75rem; }

/* 인용 기사 목록 */
.ref-list {
    margin-top: 1.5rem; padding-top: 1rem;
    border-top: 1px solid #f0f0f0;
}
.ref-list .ref-title {
    font-size: 0.78rem; font-weight: 600; color: #a8a29e;
    text-transform: uppercase; letter-spacing: 0.04em;
    margin-bottom: 0.5rem;
}
.ref-list .ref-item {
    font-size: 0.82rem; color: #57534e; line-height: 1.6;
    padding: 0.15rem 0;
}
.ref-list .ref-item a {
    color: #1c1917; text-decoration: none;
}
.ref-list .ref-item a:hover {
    color: #0369a1; text-decoration: underline;
}
.ref-list .ref-item .ref-date {
    color: #a8a29e; font-size: 0.75rem; margin-right: 0.4rem;
}

/* 도구 사용 배지 */
.tool-badge {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.25rem 0.65rem; border-radius: 16px;
    font-size: 0.72rem; font-weight: 500;
    background: #f5f5f4; color: #57534e;
    border: 1px solid #e7e5e4;
    margin-right: 0.35rem; margin-bottom: 0.35rem;
}
.tool-badge .tool-icon { font-size: 0.8rem; }

/* 메타 정보 바 */
.meta-bar {
    display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem;
    padding: 0.75rem 0; margin-top: 0.5rem;
    border-top: 1px solid #f0f0f0;
    font-size: 0.72rem; color: #a8a29e;
}

/* Streamlit 기본 요소 숨기기 */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* 모바일 */
@media (max-width: 768px) {
    .fixed-sidebar { display: none; }
    .main .block-container {
        margin-left: 0 !important;
        max-width: 100% !important;
        padding: 1rem !important;
    }
}
</style>
""", unsafe_allow_html=True)


def make_token(password: str) -> str:
    secret = os.getenv("COOKIE_SECRET", "sl-secret-key-change-me")
    return hashlib.sha256(f"{password}:{secret}".encode()).hexdigest()[:32]


def inject_cookie_js(token: str, days: int):
    max_age = days * 86400
    st.components.v1.html(f"""
        <script>
        document.cookie = "sl_auth={token}; path=/; max-age={max_age}; SameSite=Lax";
        </script>
    """, height=0)


def get_cookie_via_header():
    try:
        headers = st.context.headers
        cookies = headers.get("Cookie", "")
        for part in cookies.split(";"):
            part = part.strip()
            if part.startswith("sl_auth="):
                return part.split("=", 1)[1]
    except Exception:
        pass
    return None


def is_authenticated() -> bool:
    if st.session_state.get("authenticated"):
        return True
    cookie_token = get_cookie_via_header()
    if cookie_token:
        for pw in ACCESS_PASSWORDS:
            if cookie_token == make_token(pw):
                st.session_state["authenticated"] = True
                return True
    return False


def check_api():
    try:
        r = requests.get(f"{API_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ===== 고정 사이드바 (index.html과 동일 HTML) =====
def render_sidebar():
    st.markdown("""
    <div class="fixed-sidebar">
        <img src="https://img.stibee.com/d846e0cc-c5fc-4bb4-b18f-e064a51c1cd2.png" alt="슬로우 컨텍스트" style="width:100%;margin-bottom:1.2rem;">


        <div class="stat-label">아카이브.</div>
        <div class="stat-value">18,165<span class="unit"> 건.</span></div>

        <div class="stat-label">기간.</div>
        <div class="date-range">2023-04 ~ 2026-02</div>

        <hr class="divider">

        <a href="/" class="nav-link">Archives Search.</a>
        <a href="/context/" class="nav-link active">Context Analytics(AI).</a>
        <a href="https://slownews.kr" class="nav-link" target="_blank" rel="noopener">Slow News.</a>

        <div class="sidebar-footer">
            <hr class="divider">
            slownews.net
        </div>
    </div>
    """, unsafe_allow_html=True)


# ===== 로그인 페이지 =====
def show_login():
    render_sidebar()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("")
        st.markdown("")
        st.markdown("### Context Analytics.")
        st.markdown("유료 구독자 전용 서비스입니다.")
        st.markdown("")

        password = st.text_input("접속 암호", type="password", key="login_pw", label_visibility="collapsed", placeholder="접속 암호")

        if st.button("입장", type="primary", use_container_width=True):
            if password in ACCESS_PASSWORDS:
                st.session_state["authenticated"] = True
                token = make_token(password)
                days = 3 if password == "preview" else 33
                inject_cookie_js(token, days)
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("암호가 올바르지 않습니다.")

        st.caption("암호를 모르시면 슬로우레터 구독 페이지를 확인해 주세요.")


# ===== 인증 확인 =====
if REQUIRE_LOGIN and not is_authenticated():
    show_login()
    st.stop()


# ===== 메인 앱 (인증 통과 후) =====
render_sidebar()


def query_agent(question):
    try:
        r = requests.post(f"{API_URL}/query", json={"question": question}, timeout=120)
        return r.json()
    except Exception as e:
        return {"answer": f"오류: {str(e)}", "tool_calls": [], "rounds": 0}



# ===== 헬퍼: 도구명 → 한국어 + 아이콘 =====
TOOL_DISPLAY = {
    "semantic_search": ("의미 검색", "🔍"),
    "entity_timeline": ("타임라인", "📊"),
    "trend_analysis": ("트렌드", "📈"),
    "source_search": ("언론사 검색", "📰"),
}


def postprocess_answer(text: str) -> str:
    """답변 후처리: ** 제거, 마침표 종결 보장"""
    # 마크다운 bold(**text**) 제거
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    # 마크다운 italic(*text*) 제거
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # 글머리 기호(- , * ) 줄을 일반 문장으로
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    # 번호 목록(1. 2. ) 제거
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # 각 문단의 마지막이 마침표가 아니면 추가
    lines = text.split("\n")
    processed = []
    for line in lines:
        stripped = line.rstrip()
        if stripped and not stripped.endswith(('.', '?', '!', '。')):
            stripped += '.'
        processed.append(stripped)
    return "\n".join(processed)


def render_answer_card(result: dict):
    """RAG 답변을 스타일링된 카드로 표시"""
    answer = result.get("answer", "")
    tool_calls = result.get("tool_calls", [])
    sources = result.get("sources", [])
    rounds = result.get("rounds", 0)

    # 답변 후처리
    answer = postprocess_answer(answer)

    # ---- 답변 카드 ----
    safe_answer = html_mod.escape(answer).replace("\n", "<br>")

    # ---- 인용 기사 목록 HTML ----
    ref_html = ""
    if sources:
        ref_items = ""
        for src in sources:
            date = html_mod.escape(str(src.get("date", "")))
            title = html_mod.escape(str(src.get("title", "")))
            doc_id = html_mod.escape(str(src.get("id", "")))
            if doc_id:
                ref_items += f'<div class="ref-item"><span class="ref-date">{date}</span><a href="/?doc={doc_id}" target="_blank">{title}</a></div>'
            else:
                ref_items += f'<div class="ref-item"><span class="ref-date">{date}</span>{title}</div>'
        ref_html = f"""
        <div class="ref-list">
            <div class="ref-title">참조 기사</div>
            {ref_items}
        </div>"""

    st.markdown(f"""
    <div class="answer-card">
        <div class="answer-header">
            <span class="icon">✦</span>
            <span class="label">AI 분석 결과</span>
        </div>
        <div class="answer-body">{safe_answer}</div>
        {ref_html}
        <div class="meta-bar">
            {''.join(
                f'<span class="tool-badge"><span class="tool-icon">{TOOL_DISPLAY.get(tc["tool"], ("도구","🔧"))[1]}</span>{TOOL_DISPLAY.get(tc["tool"], ("도구","🔧"))[0]}</span>'
                for tc in tool_calls
            )}
            <span>추론 {rounds}단계</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ===== 헤더 (index.html과 동일 구조) =====
st.markdown("""
<div style="background:#fdad00;border-bottom:1px solid rgba(0,0,0,0.08);padding:1.5rem 0;">
    <div style="max-width:720px;margin:0 auto;padding:0 2rem;">
        <h1 style="font-size:1.8rem;font-weight:800;margin:0;color:#1c1917;">Slow Context.</h1>
    </div>
</div>
""", unsafe_allow_html=True)

# ===== 검색 컨트롤 (index.html controls와 동일 디자인) =====
# st.form을 사용하면 엔터키로도 제출 가능
with st.form("search_form", clear_on_submit=False):
    col_input, col_btn = st.columns([6, 1])
    with col_input:
        default_q = st.session_state.get("question_input", "")
        if default_q:
            del st.session_state["question_input"]
        question = st.text_input(
            "질문",
            value=default_q,
            key="q_input",
            label_visibility="collapsed",
            placeholder="질문을 입력하세요",
        )
    with col_btn:
        submitted = st.form_submit_button("분석 시작.")

if submitted and question:
    api_ok = check_api()
    if not api_ok:
        st.error("API 서버에 연결할 수 없습니다.")
    else:
        with st.spinner("분석 중... (최대 1~2분 소요)"):
            result = query_agent(question)
        render_answer_card(result)

# 예시 질문 버튼
cols = st.columns(3)
examples = [
    "탄핵 이후 언론 논조 변화는?",
    "이재명 관련 최근 이슈는?",
    "AI 관련 보도 트렌드는?",
]
for i, q in enumerate(examples):
    with cols[i]:
        if st.button(q, key=f"ex_{i}", use_container_width=True):
            st.session_state["question_input"] = q
            st.rerun()
