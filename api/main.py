"""
FastAPI 서버
- /query: 에이전트 기반 질의응답
- /search: 직접 검색
- /timeline: 엔티티 타임라인
- /trend: 트렌드 분석
"""
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

# 프로젝트 루트를 path에 추가 (절대경로)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import *
from indexing.entity_db import EntityDB
from indexing.bm25_index import KiwiBM25
from indexing.embedder import SlowLetterEmbedder, VectorStore
from search.hybrid_search import HybridSearchEngine
from agent.tools import ToolExecutor
from agent.agent import SlowLetterAgent


# ===== Global State =====
agent: Optional[SlowLetterAgent] = None
entity_db: Optional[EntityDB] = None
hybrid_search: Optional[HybridSearchEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 리소스 관리"""
    global agent, entity_db, hybrid_search

    print("Loading indexes...")

    # 1. Entity DB
    entity_db = EntityDB(str(SQLITE_DB))
    print(f"  EntityDB loaded: {SQLITE_DB}")

    # 2. BM25
    bm25 = KiwiBM25()
    bm25.load(str(BM25_INDEX))
    print(f"  BM25 loaded: {BM25_INDEX}")

    # 3. Vector Store / Embedder
    vector_store = VectorStore(str(VECTOR_INDEX_DIR))
    print(f"  VectorStore loaded: {VECTOR_INDEX_DIR}")

    embedder = None
    try:
        embedder = SlowLetterEmbedder(OPENAI_API_KEY)
    except Exception as e:
        # OPENAI_API_KEY 미설정/placeholder/오류인 경우에도 서버는 뜨게 하고
        # BM25-only 검색으로 폴백한다.
        print(f"  Embedder disabled: {e}")

    # 4. Hybrid Search
    hybrid_search = HybridSearchEngine(bm25, vector_store, embedder)

    # 5. Agent
    tool_executor = ToolExecutor(hybrid_search, entity_db)
    agent = SlowLetterAgent(
        anthropic_api_key=ANTHROPIC_API_KEY,
        tool_executor=tool_executor,
        model=AGENT_MODEL,
        max_tokens=AGENT_MAX_TOKENS,
    )

    print("All indexes loaded. Server ready.")
    yield

    # Cleanup
    entity_db.close()
    print("Server shutdown.")


app = FastAPI(
    title="SlowLetter RAG API",
    description="슬로우레터 뉴스 분석 서비스 - Agentic RAG",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Request/Response Models =====

class QueryRequest(BaseModel):
    question: str = Field(..., description="질문", examples=["탄핵 이후 언론 논조가 어떻게 변했나요?"])
    conversation_history: Optional[list] = Field(None, description="이전 대화 이력")


class QueryResponse(BaseModel):
    answer: str
    tool_calls: list
    rounds: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    date_start: Optional[str] = None
    date_end: Optional[str] = None


class TimelineRequest(BaseModel):
    entity_name: str
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    granularity: str = "month"


class TrendRequest(BaseModel):
    keyword: str
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    granularity: str = "month"


# ===== Endpoints =====

@app.get("/")
def root():
    return {"service": "SlowLetter RAG", "version": "2.0", "status": "running"}


@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    """에이전트 기반 질의응답

    Anthropic 크레딧/네트워크/인증 문제 등으로 에이전트 호출이 실패하더라도
    500으로 터지지 않게, 로컬 검색(BM25/벡터) 기반 요약으로 폴백합니다.
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = agent.query(req.question, req.conversation_history)
        return QueryResponse(**result)
    except Exception as e:
        # Agent 실패 시: 검색 컨텍스트 기반으로 최소한의 답변 제공
        fallback_answer = None
        try:
            if hybrid_search is not None:
                # search_with_context는 내부적으로 하이브리드 검색을 호출
                ctx = hybrid_search.search_with_context(req.question, top_k=8)
                fallback_answer = (
                    "(에이전트 호출이 실패하여, 검색 결과 기반으로만 답변합니다.)\n\n"
                    + ctx
                )
        except Exception:
            fallback_answer = None

        msg = str(e)
        if fallback_answer is None:
            fallback_answer = (
                "(에이전트 호출이 실패했습니다.)\n"
                f"오류: {msg}"
            )

        return QueryResponse(answer=fallback_answer, tool_calls=[], rounds=0)


@app.post("/search")
def search_endpoint(req: SearchRequest):
    """직접 하이브리드 검색"""
    if not hybrid_search:
        raise HTTPException(status_code=503, detail="Search engine not initialized")

    results = hybrid_search.search(
        query=req.query,
        top_k=req.top_k,
        date_start=req.date_start,
        date_end=req.date_end,
    )
    return {"results": results, "count": len(results)}


@app.post("/timeline")
def timeline_endpoint(req: TimelineRequest):
    """엔티티 타임라인"""
    if not entity_db:
        raise HTTPException(status_code=503, detail="Entity DB not initialized")

    timeline = entity_db.get_entity_timeline(
        entity_name=req.entity_name,
        date_start=req.date_start,
        date_end=req.date_end,
        granularity=req.granularity,
    )
    return {"entity": req.entity_name, "timeline": timeline}


@app.post("/trend")
def trend_endpoint(req: TrendRequest):
    """트렌드 분석"""
    if not entity_db:
        raise HTTPException(status_code=503, detail="Entity DB not initialized")

    trend = entity_db.get_trend_data(
        keyword=req.keyword,
        date_start=req.date_start,
        date_end=req.date_end,
        granularity=req.granularity,
    )
    return trend


@app.get("/health")
def health():
    return {
        "status": "ok",
        "agent": agent is not None,
        "entity_db": entity_db is not None,
        "hybrid_search": hybrid_search is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
