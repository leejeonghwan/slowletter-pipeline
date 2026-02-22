"""SlowLetter RAG 시스템 설정"""
import os
from pathlib import Path

# .env 로드 (서버 프로세스 실행 환경에 키가 export되지 않아도 동작하도록)
try:
    from dotenv import load_dotenv  # type: ignore
    _BASE_DIR = Path(__file__).parent
    load_dotenv(_BASE_DIR / ".env")
except Exception:
    # dotenv 미설치/로딩 실패 시에도 기본 동작은 유지
    pass

# 경로 설정
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# 원본 데이터 파일
SOLAR_ENTITIES_CSV = RAW_DATA_DIR / "slowletter_solar_entities.csv"
ARCHIVES_CSV = RAW_DATA_DIR / "slowletter_data_archives.csv"

# 인덱스 파일
SQLITE_DB = PROCESSED_DIR / "entities.db"
BM25_INDEX = PROCESSED_DIR / "bm25_index.pkl"
VECTOR_INDEX_DIR = PROCESSED_DIR / "qdrant"

# API 키
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 임베딩 설정
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072
EMBEDDING_BATCH_SIZE = 100

# 검색 설정
HYBRID_SEARCH_TOP_K = 30       # 초기 검색 결과 수
RERANK_TOP_K = 10              # 리랭킹 후 최종 결과 수
BM25_WEIGHT = 0.3              # 하이브리드 검색에서 BM25 비중
VECTOR_WEIGHT = 0.7            # 하이브리드 검색에서 벡터 비중

# 에이전트 설정
AGENT_MODEL = "claude-sonnet-4-5-20250929"
AGENT_MAX_TOKENS = 4096
AGENT_TEMPERATURE = 0.3

# 서버 설정
API_HOST = "0.0.0.0"
API_PORT = 8000
