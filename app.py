"""
SlowLetter RAG - Streamlit 웹 UI
Streamlit 기본 사이드바 + index.html 동일 디자인
"""
import os, re, sys, hashlib, html as html_mod, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import streamlit as st
import requests

API_URL = "http://localhost:8000"

# ===== 인증 설정 =====
REQUIRE_LOGIN = False
ACCESS_PASSWORDS = ["preview", "justice"]

st.set_page_config(
    page_title="Slow Context.",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ───────────────────────────────────────────────
# CSS (index.html과 동일 디자인)
# ───────────────────────────────────────────────
st.markdown("""<style>
.stApp { background-color: #fdad00; }

/* 사이드바 — index.html .sidebar 동일 */
[data-testid="stSidebar"] { background-color: #1c1917; }
[data-testid="stSidebar"] * { color: #e7e5e4; }

/* 메인 콘텐츠 — index.html .content 동일 폭 */
.main .block-container {
    max-width: 760px;
    padding-top: 2rem;
    padding-bottom: 2rem;
}

/* 검색 입력창 */
.stTextInput > div > div > input {
    background-color: white; color: #1c1917;
    border: 1px solid rgba(0,0,0,0.18); border-radius: 6px;
    padding: 0.6rem 0.85rem; font-size: 0.95rem;
}
.stTextInput > div > div > input:focus {
    border-color: #0369a1; box-shadow: 0 0 0 2px #e0f2fe;
}

/* 분석 시작 버튼 */
.stFormSubmitButton button {
    background-color: #1c1917 !important; color: #fdad00 !important;
    border: 1px solid rgba(0,0,0,0.18) !important; border-radius: 6px !important;
    padding: 0.6rem 1rem !important; font-size: 0.85rem !important;
    font-weight: 600 !important; white-space: nowrap !important;
}
.stFormSubmitButton button:hover {
    background-color: #fdad00 !important; color: #1c1917 !important;
}

/* 예시 질문 버튼 */
.stButton button {
    background-color: transparent !important; color: #57534e !important;
    border: 1px solid rgba(0,0,0,0.12) !important; border-radius: 6px !important;
    font-size: 0.8rem !important; padding: 0.4rem 0.8rem !important;
}
.stButton button:hover { background-color: #fff !important; color: #1c1917 !important; }

/* form 테두리 제거 */
[data-testid="stForm"] { border: none !important; padding: 0 !important; }

/* Streamlit 기본 요소 숨기기 */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>""", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# 사이드바 (Streamlit 기본 st.sidebar 사용 — 어제 정상 작동한 방식)
# ───────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.image(
            "https://img.stibee.com/d846e0cc-c5fc-4bb4-b18f-e064a51c1cd2.png",
            use_container_width=True,
        )
        st.markdown("""
        <div style="margin-top:1rem;">
            <div style="font-size:0.7rem;color:#a8a29e;margin-bottom:0.2rem;text-transform:uppercase;letter-spacing:0.05em;">아카이브.</div>
            <div style="font-size:1.3rem;font-weight:700;color:#ffffff;margin-bottom:1rem;">
                18,165<span style="font-size:0.75rem;font-weight:400;color:#a8a29e;"> 건.</span>
            </div>
            <div style="font-size:0.7rem;color:#a8a29e;margin-bottom:0.2rem;text-transform:uppercase;letter-spacing:0.05em;">기간.</div>
            <div style="font-size:0.75rem;color:#a8a29e;margin-bottom:1rem;">2023-04 ~ 2026-02</div>
        </div>
        <hr style="border:none;border-top:1px solid #333;margin:1rem 0;">
        <a href="/" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#e7e5e4;text-decoration:none;">
            Archives Search.
        </a>
        <a href="/context/" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#1c1917;text-decoration:none;background:#fdad00;font-weight:600;">
            Context Analytics(AI).
        </a>
        <a href="https://slownews.kr" target="_blank" rel="noopener" style="display:block;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border-radius:6px;font-size:0.85rem;color:#e7e5e4;text-decoration:none;">
            Slow News.
        </a>
        <div style="margin-top:auto;font-size:0.65rem;color:#57534e;">
            <hr style="border:none;border-top:1px solid #333;margin:1rem 0;">
            slownews.net
        </div>
        """, unsafe_allow_html=True)


# ───────────────────────────────────────────────
# 인증 헬퍼
# ───────────────────────────────────────────────
def make_token(pw):
    secret = os.getenv("COOKIE_SECRET", "sl-secret-key-change-me")
    return hashlib.sha256(f"{pw}:{secret}".encode()).hexdigest()[:32]

def inject_cookie_js(token, days):
    import streamlit.components.v1 as comp
    comp.html(f'<script>document.cookie="sl_auth={token};path=/;max-age={days*86400};SameSite=Lax";</script>', height=0)

def get_cookie_via_header():
    try:
        cookies = st.context.headers.get("Cookie", "")
        for part in cookies.split(";"):
            part = part.strip()
            if part.startswith("sl_auth="):
                return part.split("=", 1)[1]
    except Exception:
        pass
    return None

def is_authenticated():
    if st.session_state.get("authenticated"):
        return True
    token = get_cookie_via_header()
    if token:
        for pw in ACCESS_PASSWORDS:
            if token == make_token(pw):
                st.session_state["authenticated"] = True
                return True
    return False

def show_login():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(""); st.markdown("")
        st.markdown("### Context Analytics.")
        st.markdown("유료 구독자 전용 서비스입니다."); st.markdown("")
        password = st.text_input("접속 암호", type="password", key="login_pw",
                                 label_visibility="collapsed", placeholder="접속 암호")
        if st.button("입장", type="primary", use_container_width=True):
            if password in ACCESS_PASSWORDS:
                st.session_state["authenticated"] = True
                inject_cookie_js(make_token(password), 3 if password == "preview" else 33)
                time.sleep(0.5); st.rerun()
            else:
                st.error("암호가 올바르지 않습니다.")
        st.caption("암호를 모르시면 슬로우레터 구독 페이지를 확인해 주세요.")


# ───────────────────────────────────────────────
# 메인 실행
# ───────────────────────────────────────────────
render_sidebar()

if REQUIRE_LOGIN and not is_authenticated():
    show_login(); st.stop()


# ===== API 헬퍼 =====
def check_api():
    try:
        return requests.get(f"{API_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False

def query_agent(question):
    try:
        r = requests.post(f"{API_URL}/query", json={"question": question}, timeout=120)
        return r.json()
    except Exception as e:
        return {"answer": f"오류: {str(e)}", "tool_calls": [], "rounds": 0, "sources": []}


# ===== 답변 후처리 =====
TOOL_DISPLAY = {
    "semantic_search": ("의미 검색", "🔍"),
    "entity_timeline": ("타임라인", "📊"),
    "trend_analysis": ("트렌드", "📈"),
    "source_search": ("언론사 검색", "📰"),
}

def postprocess_answer(text):
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    lines = []
    for line in text.split("\n"):
        s = line.rstrip()
        if s and not s.endswith(('.', '?', '!', '。')):
            s += '.'
        lines.append(s)
    return "\n".join(lines)


def render_answer_card(result):
    answer = postprocess_answer(result.get("answer", ""))
    tool_calls = result.get("tool_calls", [])
    sources = result.get("sources", [])
    rounds = result.get("rounds", 0)

    safe = html_mod.escape(answer).replace("\n", "<br>")

    # 인용 기사
    ref_html = ""
    if sources:
        items = []
        for src in sources:
            d = html_mod.escape(str(src.get("date", "")))
            t = html_mod.escape(str(src.get("title", "")))
            doc_id = html_mod.escape(str(src.get("id", "")))
            link = f'<a href="/?doc={doc_id}" target="_blank" style="color:#1c1917;text-decoration:none">{t}</a>' if doc_id else t
            items.append(f'<div style="font-size:0.82rem;color:#57534e;line-height:1.6;padding:0.15rem 0"><span style="color:#a8a29e;font-size:0.75rem;margin-right:0.4rem">{d}</span>{link}</div>')
        ref_html = (
            '<div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #f0f0f0">'
            '<div style="font-size:0.78rem;font-weight:600;color:#a8a29e;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:0.5rem">관련 기사</div>'
            + "".join(items) + '</div>'
        )

    # 도구 배지
    badges = ""
    for tc in tool_calls:
        info = TOOL_DISPLAY.get(tc.get("tool", ""), ("도구", "🔧"))
        badges += (
            f'<span style="display:inline-flex;align-items:center;gap:0.3rem;'
            f'padding:0.25rem 0.65rem;border-radius:16px;font-size:0.72rem;'
            f'font-weight:500;background:#f5f5f4;color:#57534e;border:1px solid #e7e5e4;'
            f'margin-right:0.35rem;margin-bottom:0.35rem">'
            f'<span style="font-size:0.8rem">{info[1]}</span>{info[0]}</span>'
        )

    st.markdown(
        f'<div style="background:#fff;border-radius:12px;padding:2rem;margin:1.5rem 0;'
        f'box-shadow:0 2px 12px rgba(0,0,0,0.08);border-left:4px solid #fdad00">'
        f'<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;'
        f'padding-bottom:0.75rem;border-bottom:1px solid #f0f0f0">'
        f'<span style="font-size:1.2rem">✦</span>'
        f'<span style="font-size:0.85rem;font-weight:600;color:#1c1917;'
        f'text-transform:uppercase;letter-spacing:0.03em">AI 분석 결과</span></div>'
        f'<div style="font-size:0.95rem;line-height:1.75;color:#1c1917">{safe}</div>'
        f'{ref_html}'
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:0.5rem;'
        f'padding:0.75rem 0;margin-top:0.5rem;border-top:1px solid #f0f0f0;'
        f'font-size:0.72rem;color:#a8a29e">{badges}<span>추론 {rounds}단계</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ───────────────────────────────────────────────
# 헤더 + 검색 폼
# ───────────────────────────────────────────────
st.markdown("# Slow Context.")

with st.form("search_form", clear_on_submit=False):
    col_input, col_btn = st.columns([6, 1])
    with col_input:
        default_q = st.session_state.pop("question_input", "")
        question = st.text_input(
            "질문", value=default_q, key="q_input",
            label_visibility="collapsed", placeholder="질문을 입력하세요",
        )
    with col_btn:
        submitted = st.form_submit_button("분석 시작.")

if submitted and question:
    if not check_api():
        st.error("API 서버에 연결할 수 없습니다.")
    else:
        with st.spinner("분석 중... (최대 1~2분 소요)"):
            result = query_agent(question)
        st.session_state["last_result"] = result
        render_answer_card(result)
elif "last_result" in st.session_state:
    render_answer_card(st.session_state["last_result"])

# 예시 질문
cols = st.columns(3)
examples = ["탄핵 이후 언론 논조 변화는?", "이재명 관련 최근 이슈는?", "AI 관련 보도 트렌드는?"]
for i, q in enumerate(examples):
    with cols[i]:
        if st.button(q, key=f"ex_{i}", use_container_width=True):
            st.session_state["question_input"] = q
            st.rerun()
