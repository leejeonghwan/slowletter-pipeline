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

API_URL = "http://localhost:8000"

st.set_page_config(page_title="슬로우 컨텍스트", page_icon="📰", layout="wide")

# Sidebar 색상 등 간단한 스타일 오버라이드
st.markdown(
    """
    <style>
      section[data-testid="stSidebar"] {
        background-color: #fdad00;
      }
      /* 사이드바 내 텍스트 가독성 */
      section[data-testid="stSidebar"] * {
        color: #111111;
      }
      /* 일부 컴포넌트(버튼/라벨) 대비 보정 */
      section[data-testid="stSidebar"] button, 
      section[data-testid="stSidebar"] [role="button"] {
        color: #111111 !important;
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


# ===== 사이드바 =====
with st.sidebar:
    st.markdown("### 슬로우 컨텍스트")
    st.markdown("Slow Context: 슬로우레터 기반의 맥락 분석 서비스")

    api_ok = check_api()
    if api_ok:
        st.success("✅ API 서버 연결됨")
    else:
        st.error("❌ API 서버 연결 안됨")

    mode = st.radio("모드 선택", ["💬 채팅", "📊 타임라인", "📈 트렌드"], index=0)

    st.markdown("---")
    st.caption("데이터: 2023.04 ~ 2026.02")
    st.caption("약 17,988건 뉴스 코멘터리")


# ===== 채팅 모드 =====
if mode == "💬 채팅":
    st.title("슬로우 컨텍스트")
    st.markdown("Slow Context: 슬로우레터 기반의 맥락 분석 서비스")

    st.markdown("---")

    # 질문 입력
    default_q = st.session_state.pop("question_input", "")
    question = st.text_input("질문을 입력하세요:", value=default_q, key="q_input")

    if st.button("🔍 분석하기", type="primary", disabled=not api_ok) and question:
        with st.spinner("분석 중... (최대 1~2분 소요)"):
            result = query_agent(question)

        # 답변 표시
        st.markdown("---")
        st.markdown("### 📝 답변")
        st.markdown(result["answer"])

        # 사용된 도구
        if result.get("tool_calls"):
            st.markdown("---")
            tools_used = [tc["tool"] for tc in result["tool_calls"]]
            st.markdown(f"**사용된 도구:** {', '.join(tools_used)}")
            st.caption(f"추론 라운드: {result.get('rounds', 0)}")

    # 대화 이력
    if "history" not in st.session_state:
        st.session_state.history = []

    if question and st.session_state.get("last_q") != question:
        st.session_state.last_q = question


# ===== 타임라인 모드 =====
elif mode == "📊 타임라인":
    st.title("엔티티 타임라인")
    st.markdown("인물/조직/키워드의 시간순 보도 흐름")

    col1, col2 = st.columns([3, 1])
    with col1:
        entity_name = st.text_input("인물/조직/키워드", value="윤석열")
    with col2:
        granularity = st.selectbox("시간 단위", ["month", "week", "day"], index=0)

    if st.button("타임라인 조회", type="primary", disabled=not api_ok) and entity_name:
        with st.spinner("조회 중..."):
            timeline = get_timeline(entity_name, granularity)

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
elif mode == "📈 트렌드":
    st.title("트렌드 분석")
    st.markdown("키워드 빈도 변화 + 공출현 엔티티 + 대표 문서")

    col1, col2 = st.columns([3, 1])
    with col1:
        keyword = st.text_input("분석 키워드", value="탄핵")
    with col2:
        t_granularity = st.selectbox("시간 단위", ["month", "day"], index=0, key="tg")

    if st.button("트렌드 분석", type="primary", disabled=not api_ok) and keyword:
        with st.spinner("분석 중..."):
            trend = get_trend(keyword, t_granularity)

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
