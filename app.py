"""
SlowLetter RAG - Streamlit 웹 UI
채팅 + 타임라인 + 트렌드 시각화
쿠키 기반 간단 인증 · Finder와 동일 사이드바
"""
import os
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
ACCESS_PASSWORDS = ["preview", "justice"]

st.set_page_config(page_title="Slow Context.", page_icon="📰", layout="wide")

# ===== 전역 스타일: #fdad00 배경 + 블랙 사이드바 (Finder 동일) =====
st.markdown("""
<style>
/* Streamlit 기본 배경을 #fdad00로 */
.stApp, [data-testid="stAppViewContainer"], .main .block-container {
    background-color: #fdad00 !important;
}
header[data-testid="stHeader"] {
    background-color: #fdad00 !important;
}

/* 사이드바 — Finder 동일 블랙 */
[data-testid="stSidebar"] {
    background-color: #1c1917 !important;
    color: #e7e5e4 !important;
}
[data-testid="stSidebar"] * {
    color: #e7e5e4 !important;
}
[data-testid="stSidebar"] .stMarkdown h3 {
    color: #fdad00 !important;
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.15rem !important;
}
[data-testid="stSidebar"] .stMarkdown p {
    font-size: 0.85rem !important;
}
[data-testid="stSidebar"] hr {
    border-color: #333 !important;
}
[data-testid="stSidebar"] a {
    color: #e7e5e4 !important;
    text-decoration: none !important;
}
[data-testid="stSidebar"] a:hover {
    color: #fdad00 !important;
}
[data-testid="stSidebar"] .stRadio label {
    color: #e7e5e4 !important;
}
[data-testid="stSidebar"] .stButton button {
    background-color: #333 !important;
    color: #e7e5e4 !important;
    border: 1px solid #555 !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background-color: #fdad00 !important;
    color: #1c1917 !important;
}

/* 입력 필드 배경을 흰색으로 유지 */
.stTextInput input, .stSelectbox select {
    background-color: #ffffff !important;
    color: #1c1917 !important;
}

/* 카드/컨테이너 스타일 */
.login-card {
    max-width: 380px; margin: 80px auto; padding: 2.5rem;
    background: #ffffff; border-radius: 12px;
    box-shadow: 0 2px 16px rgba(0,0,0,0.1);
    text-align: center;
}
.login-card h2 { font-size: 1.3rem; font-weight: 700; color: #1c1917; margin-bottom: 0.25rem; }
.login-card .desc { font-size: 0.8rem; color: #57534e; margin-bottom: 2rem; }
.login-card .hint { font-size: 0.7rem; color: #57534e; margin-top: 1.5rem; }

/* metric 카드 */
[data-testid="stMetric"] {
    background: #ffffff; padding: 1rem; border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

/* expander */
.streamlit-expanderHeader {
    background: #ffffff !important; border-radius: 8px;
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
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid #f0f0f0;
}
.answer-card .answer-header .icon {
    font-size: 1.2rem;
}
.answer-card .answer-header .label {
    font-size: 0.85rem;
    font-weight: 600;
    color: #1c1917;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.answer-card .answer-body {
    font-size: 0.95rem;
    line-height: 1.75;
    color: #1c1917;
}
.answer-card .answer-body p {
    margin-bottom: 0.75rem;
}

/* 출처 카드 */
.source-card {
    background: #fafaf9;
    border: 1px solid #e7e5e4;
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.5rem;
    transition: box-shadow 0.15s;
}
.source-card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.source-card .source-date {
    font-size: 0.7rem;
    color: #a8a29e;
    margin-bottom: 0.15rem;
}
.source-card .source-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: #1c1917;
    margin-bottom: 0.35rem;
}
.source-card .source-snippet {
    font-size: 0.78rem;
    color: #57534e;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.source-card .source-tags {
    margin-top: 0.4rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}
.source-card .source-tags .tag {
    display: inline-block;
    padding: 0.1rem 0.4rem;
    border-radius: 10px;
    font-size: 0.65rem;
}
.source-card .source-tags .tag-person {
    background: #fecdd3;
    color: #9f1239;
}
.source-card .source-tags .tag-org {
    background: #bbf7d0;
    color: #166534;
}

/* 도구 사용 배지 */
.tool-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.25rem 0.65rem;
    border-radius: 16px;
    font-size: 0.72rem;
    font-weight: 500;
    background: #f5f5f4;
    color: #57534e;
    border: 1px solid #e7e5e4;
    margin-right: 0.35rem;
    margin-bottom: 0.35rem;
}
.tool-badge .tool-icon {
    font-size: 0.8rem;
}

/* 메타 정보 바 */
.meta-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding: 0.75rem 0;
    margin-top: 0.5rem;
    border-top: 1px solid #f0f0f0;
    font-size: 0.72rem;
    color: #a8a29e;
}

/* 섹션 헤더 */
.section-header {
    font-size: 0.8rem;
    font-weight: 600;
    color: #1c1917;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 1.5rem 0 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid #fdad00;
    display: inline-block;
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


# ===== 사이드바 (Finder와 동일 디자인) =====
def render_sidebar(authenticated=False):
    with st.sidebar:
        st.markdown("### 슬로우 컨텍스트.")
        st.markdown("Slow Context.")
        st.markdown("")

        st.markdown('<span style="font-size:0.7rem;color:#a8a29e;text-transform:uppercase;letter-spacing:0.05em;">아카이브.</span>', unsafe_allow_html=True)
        st.markdown('<span style="font-size:1.3rem;font-weight:700;color:#ffffff;">18,165<span style="font-size:0.75rem;font-weight:400;color:#a8a29e;"> 건.</span></span>', unsafe_allow_html=True)
        st.markdown("")

        st.markdown('<span style="font-size:0.7rem;color:#a8a29e;text-transform:uppercase;letter-spacing:0.05em;">기간.</span>', unsafe_allow_html=True)
        st.markdown('<span style="font-size:0.75rem;color:#a8a29e;">2023-04 ~ 2026-02</span>', unsafe_allow_html=True)

        st.markdown("---")

        st.markdown("[Archives Search.](/)")
        st.markdown("**Context Analytics(AI).**")
        st.markdown("[Slow News.](https://slownews.kr)")

        if authenticated:
            st.markdown("---")

            api_ok = check_api()
            if api_ok:
                st.markdown('<span style="font-size:0.75rem;color:#22c55e;">● API 연결됨</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span style="font-size:0.75rem;color:#ef4444;">● API 연결 안됨</span>', unsafe_allow_html=True)

            st.markdown("---")
            st.radio("모드 선택", ["채팅", "타임라인", "트렌드"], index=0, key="mode_select")

            st.markdown("---")
            if st.button("로그아웃", use_container_width=True):
                st.session_state["authenticated"] = False
                st.components.v1.html("""
                    <script>
                    document.cookie = "sl_auth=; path=/; max-age=0";
                    </script>
                """, height=0)
                st.rerun()

        st.markdown("---")
        st.markdown('<span style="font-size:0.65rem;color:#57534e;">slownews.net</span>', unsafe_allow_html=True)


# ===== 로그인 페이지 =====
def show_login():
    render_sidebar(authenticated=False)

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
if not is_authenticated():
    show_login()
    st.stop()


# ===== 메인 앱 (인증 통과 후) =====
render_sidebar(authenticated=True)
mode = st.session_state.get("mode_select", "채팅")


def query_agent(question):
    try:
        r = requests.post(f"{API_URL}/query", json={"question": question}, timeout=120)
        return r.json()
    except Exception as e:
        return {"answer": f"오류: {str(e)}", "tool_calls": [], "rounds": 0}


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


# ===== 헬퍼: 도구명 → 한국어 + 아이콘 =====
TOOL_DISPLAY = {
    "semantic_search": ("의미 검색", "🔍"),
    "entity_timeline": ("타임라인", "📊"),
    "trend_analysis": ("트렌드", "📈"),
    "source_search": ("언론사 검색", "📰"),
}


def render_answer_card(result: dict):
    """RAG 답변을 스타일링된 카드로 표시"""
    answer = result.get("answer", "")
    tool_calls = result.get("tool_calls", [])
    sources = result.get("sources", [])
    rounds = result.get("rounds", 0)

    # ---- 답변 카드 ----
    safe_answer = html_mod.escape(answer).replace("\n", "<br>")
    st.markdown(f"""
    <div class="answer-card">
        <div class="answer-header">
            <span class="icon">✦</span>
            <span class="label">AI 분석 결과</span>
        </div>
        <div class="answer-body">{safe_answer}</div>
        <div class="meta-bar">
            {''.join(
                f'<span class="tool-badge"><span class="tool-icon">{TOOL_DISPLAY.get(tc["tool"], ("도구","🔧"))[1]}</span>{TOOL_DISPLAY.get(tc["tool"], ("도구","🔧"))[0]}</span>'
                for tc in tool_calls
            )}
            <span>추론 {rounds}단계</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ---- 출처 문서 ----
    if sources:
        st.markdown(f'<div class="section-header">참조 문서 ({len(sources)}건)</div>', unsafe_allow_html=True)

        # 상위 5건만 기본 표시, 나머지는 expander
        display_sources = sources[:5]
        remaining_sources = sources[5:]

        for src in display_sources:
            _render_source_card(src)

        if remaining_sources:
            with st.expander(f"나머지 {len(remaining_sources)}건 더 보기"):
                for src in remaining_sources:
                    _render_source_card(src)


def _render_source_card(src: dict):
    """개별 출처 카드 렌더링"""
    date = html_mod.escape(str(src.get("date", "")))
    title = html_mod.escape(str(src.get("title", "")))
    snippet = html_mod.escape(str(src.get("snippet", "")))
    persons = str(src.get("persons", ""))
    orgs = str(src.get("organizations", ""))
    doc_id = html_mod.escape(str(src.get("id", "")))

    # 엔티티 태그 HTML
    tags_html = ""
    if persons:
        for p in persons.split(";"):
            p = p.strip()
            if p:
                tags_html += f'<span class="tag tag-person">{html_mod.escape(p)}</span>'
    if orgs:
        for o in orgs.split(";"):
            o = o.strip()
            if o:
                tags_html += f'<span class="tag tag-org">{html_mod.escape(o)}</span>'

    # permalink 링크 (doc_id가 있으면 Finder로 연결)
    title_html = title
    if doc_id:
        title_html = f'<a href="/?doc={doc_id}" target="_blank" style="color:#1c1917;text-decoration:none;">{title}</a>'

    st.markdown(f"""
    <div class="source-card">
        <div class="source-date">{date}</div>
        <div class="source-title">{title_html}</div>
        <div class="source-snippet">{snippet}</div>
        {f'<div class="source-tags">{tags_html}</div>' if tags_html else ''}
    </div>
    """, unsafe_allow_html=True)


# ===== 채팅 모드 =====
if mode == "채팅":
    st.title("SlowLetter 뉴스 분석")
    st.markdown("3년치 뉴스 코멘터리를 AI가 분석합니다")

    st.markdown("**예시 질문:**")
    cols = st.columns(3)
    examples = [
        "탄핵 이후 언론 논조 변화는?",
        "이재명 관련 최근 이슈는?",
        "AI 관련 보도 트렌드는?",
    ]
    for i, q in enumerate(examples):
        with cols[i]:
            if st.button(q, key=f"ex_{i}"):
                st.session_state["question_input"] = q

    st.markdown("---")

    default_q = st.session_state.pop("question_input", "")
    question = st.text_input("질문을 입력하세요:", value=default_q, key="q_input")

    api_ok = check_api()
    if st.button("분석하기", type="primary", disabled=not api_ok) and question:
        with st.spinner("분석 중... (최대 1~2분 소요)"):
            result = query_agent(question)

        render_answer_card(result)


# ===== 타임라인 모드 =====
elif mode == "타임라인":
    st.title("엔티티 타임라인")
    st.markdown("인물/조직/키워드의 시간순 보도 흐름")

    col1, col2 = st.columns([3, 1])
    with col1:
        entity_name = st.text_input("인물/조직/키워드", value="윤석열")
    with col2:
        granularity = st.selectbox("시간 단위", ["month", "week", "day"], index=0)

    api_ok = check_api()
    if st.button("타임라인 조회", type="primary", disabled=not api_ok) and entity_name:
        with st.spinner("조회 중..."):
            timeline = get_timeline(entity_name, granularity)

        if timeline:
            st.markdown(f"**'{entity_name}' 보도 타임라인** ({len(timeline)}개 기간)")
            try:
                import pandas as pd
                df = pd.DataFrame(timeline)
                df["period"] = df["period"].astype(str)
                st.bar_chart(df.set_index("period")["doc_count"])
            except ImportError:
                for entry in timeline:
                    bar = "█" * min(entry["doc_count"], 50)
                    st.text(f"{entry['period']}: {entry['doc_count']:3d}건 {bar}")

            with st.expander("상세 보기"):
                for entry in timeline:
                    titles = " / ".join(entry["titles"][:3])
                    st.markdown(f"**{entry['period']}** — {entry['doc_count']}건")
                    st.caption(titles)
        else:
            st.warning(f"'{entity_name}'에 대한 데이터가 없습니다.")


# ===== 트렌드 모드 =====
elif mode == "트렌드":
    st.title("트렌드 분석")
    st.markdown("키워드 빈도 변화 + 공출현 엔티티 + 대표 문서")

    col1, col2 = st.columns([3, 1])
    with col1:
        keyword = st.text_input("분석 키워드", value="탄핵")
    with col2:
        t_granularity = st.selectbox("시간 단위", ["month", "day"], index=0, key="tg")

    api_ok = check_api()
    if st.button("트렌드 분석", type="primary", disabled=not api_ok) and keyword:
        with st.spinner("분석 중..."):
            trend = get_trend(keyword, t_granularity)

        if trend and trend.get("timeline"):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("총 문서 수", f"{trend['total_count']}건")
            with col2:
                st.metric("분석 기간", f"{len(trend['timeline'])}개 구간")
            with col3:
                if trend.get("co_entities"):
                    st.metric("관련 엔티티", f"{len(trend['co_entities'])}개")

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

            if trend.get("representative_docs"):
                st.markdown("#### 대표 문서")
                for doc in trend["representative_docs"][:5]:
                    st.markdown(f"**({doc['date']}) {doc['title']}**")
                    st.caption(f"{doc['snippet']}...")
        else:
            st.warning(f"'{keyword}'에 대한 트렌드 데이터가 없습니다.")
