import streamlit as st
import requests
from datetime import datetime
import os
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# 페이지 설정
st.set_page_config(
    page_title="Slow Context",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 패스워드 체크
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if st.session_state.authenticated:
        return True
    
    PASSWORD_PUBLIC = os.getenv("PASSWORD_PUBLIC", "preview")
    PASSWORD_PREMIUM = os.getenv("PASSWORD_PREMIUM", "justice")
    EXPIRY_PUBLIC = os.getenv("EXPIRY_PUBLIC", "2026-03-03")
    EXPIRY_PREMIUM = os.getenv("EXPIRY_PREMIUM", "2026-03-31")
    
    st.markdown('<div class="result-box">', unsafe_allow_html=True)
    password = st.text_input("패스워드", type="password", key="password_input", label_visibility="collapsed", placeholder="패스워드를 입력하세요")
    
    if st.button("로그인"):
        today = datetime.now().strftime("%Y-%m-%d")
        
        if password == PASSWORD_PUBLIC and today <= EXPIRY_PUBLIC:
            st.session_state.authenticated = True
            st.session_state.access_level = "public"
            st.rerun()
        elif password == PASSWORD_PREMIUM and today <= EXPIRY_PREMIUM:
            st.session_state.authenticated = True
            st.session_state.access_level = "premium"
            st.rerun()
        else:
            st.error("잘못된 패스워드이거나 만료되었습니다")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    return False

# 사이드바 (index.html과 동일)
def render_sidebar():
    with st.sidebar:
        # 로고
        logo_path = "/var/www/slownews/static/logo.jpg"
        if os.path.exists(logo_path):
            st.image(logo_path, width=180)
        else:
            st.markdown("### SlowNews")
        
        # 통계
        st.markdown("""
        <div style="margin-top: 1.5rem;">
            <div style="font-size: 0.7rem; color: #a8a29e; margin-bottom: 0.2rem; text-transform: uppercase; letter-spacing: 0.05em;">아카이브.</div>
            <div style="font-size: 1.3rem; font-weight: 700; color: #ffffff; margin-bottom: 1rem;">
                18,165<span style="font-size: 0.75rem; font-weight: 400; color: #a8a29e;"> 건.</span>
            </div>
            
            <div style="font-size: 0.7rem; color: #a8a29e; margin-bottom: 0.2rem; text-transform: uppercase; letter-spacing: 0.05em;">기간.</div>
            <div style="font-size: 0.75rem; color: #a8a29e; margin-bottom: 1rem;">2023-04-24 ~ 2026-02-27</div>
        </div>
        
        <hr style="border: none; border-top: 1px solid #333; margin: 1rem 0;">
        
        <a href="/" style="display: block; padding: 0.6rem 0.8rem; margin-bottom: 0.4rem; border-radius: 6px; 
           font-size: 0.85rem; color: #e7e5e4; text-decoration: none; background: transparent;">
            Archives Search.
        </a>
        <a href="/context/" style="display: block; padding: 0.6rem 0.8rem; margin-bottom: 0.4rem; border-radius: 6px; 
           font-size: 0.85rem; color: #1c1917; text-decoration: none; background: #fdad00; font-weight: 600;">
            Context Analytics(AI).
        </a>
        <a href="https://slownews.kr" target="_blank" style="display: block; padding: 0.6rem 0.8rem; margin-bottom: 0.4rem; 
           border-radius: 6px; font-size: 0.85rem; color: #e7e5e4; text-decoration: none; background: transparent;">
            Slow News.
        </a>
        
        <div style="margin-top: auto; font-size: 0.65rem; color: #57534e;">
            <hr style="border: none; border-top: 1px solid #333; margin: 1rem 0;">
            slownews.net
        </div>
        """, unsafe_allow_html=True)

# CSS (index.html과 동일)
st.markdown("""
<style>
    /* 전역 스타일 */
    .stApp {
        background-color: #fdad00;
    }
    
    /* 사이드바 스타일 */
    [data-testid="stSidebar"] {
        background-color: #1c1917;
    }
    
    [data-testid="stSidebar"] * {
        color: #e7e5e4;
    }
    
    /* 메인 영역 */
    .main .block-container {
        max-width: 800px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* 검색 입력창 (흰색 배경, 검정 텍스트) */
    .stTextInput > div > div > input {
        background-color: white;
        color: #111111;
        border: 1px solid rgba(0,0,0,0.18);
        border-radius: 6px;
        padding: 0.6rem 0.85rem;
        font-size: 0.95rem;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #fdad00;
        box-shadow: 0 0 0 2px rgba(253,173,0,0.1);
    }
    
    /* 검색 결과 박스 (흰색 배경) */
    .result-box {
        background: white;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        color: #111111;
    }
    
    .result-title {
        font-size: 1.4rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
        color: #111111;
    }
    
    .result-date {
        font-size: 0.75rem;
        color: #666;
        margin-bottom: 0.5rem;
    }
    
    .result-content {
        font-size: 0.9rem;
        color: #444;
        line-height: 1.8;
        margin-bottom: 0.75rem;
    }
    
    .result-content a {
        color: #0369a1;
        text-decoration: none;
    }
    
    .result-content a:hover {
        text-decoration: underline;
    }
    
    /* 답변 박스 */
    .answer-box {
        background: white;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        color: #111111;
        font-size: 1rem;
        line-height: 1.9;
    }
    
    /* Streamlit 기본 요소 숨기기 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 메인 로직
render_sidebar()

if not check_password():
    st.stop()

# 검색창
st.markdown('<div class="result-box">', unsafe_allow_html=True)
query = st.text_input("", placeholder="검색어를 입력하세요...", label_visibility="collapsed")
st.markdown('</div>', unsafe_allow_html=True)

# 검색 실행
if query:
    with st.spinner("검색 중..."):
        try:
            API_URL = os.getenv("API_URL", "http://localhost:8000")
            response = requests.post(
                f"{API_URL}/query",
                json={"question": query},
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # 답변 표시
                if result.get("answer"):
                    st.markdown(f'<div class="answer-box">{result["answer"]}</div>', unsafe_allow_html=True)
                
                # 관련 기사 표시
                texts = result.get("texts", [])
                if texts:
                    for text in texts[:10]:  # 상위 10개만
                        st.markdown(f"""
                        <div class="result-box">
                            <div class="result-date">{text.get('date', '')}</div>
                            <div class="result-title">{text.get('title', '')}</div>
                            <div class="result-content">{text.get('content', '')[:300]}...</div>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.error(f"API 오류: {response.status_code}")
        
        except Exception as e:
            st.error(f"검색 중 오류: {str(e)}")
