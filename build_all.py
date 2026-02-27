"""
전체 인덱스 빌드 스크립트
사용법: python build_all.py <solar_csv_path> [openai_api_key]

1. SQLite 엔티티 DB 구축
2. BM25 인덱스 구축
3. (OpenAI 키 제공시) 벡터 인덱스 구축
"""
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트 (절대경로로 확정)
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # 작업 디렉토리도 프로젝트 루트로 고정

from config import PROCESSED_DIR, SQLITE_DB, BM25_INDEX, VECTOR_INDEX_DIR, QDRANT_URL


def main():
    if len(sys.argv) < 2:
        print("사용법: python build_all.py <solar_entities_csv_path> [openai_api_key]")
        print("예시:   python build_all.py data/raw/slowletter_solar_entities.csv sk-...")
        sys.exit(1)

    csv_path = sys.argv[1]
    openai_key = sys.argv[2] if len(sys.argv) > 2 else os.getenv("OPENAI_API_KEY", "")

    # 디렉토리 생성
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # ===== Step 1: SQLite Entity DB =====
    print("\n" + "=" * 60)
    print("Step 1: SQLite Entity DB 구축")
    print("=" * 60)
    start = time.time()

    from indexing.entity_db import create_db
    create_db(csv_path, str(SQLITE_DB))

    print(f"완료: {time.time() - start:.1f}초")

    # ===== Step 2: BM25 Index =====
    print("\n" + "=" * 60)
    print("Step 2: BM25 인덱스 구축")
    print("=" * 60)
    start = time.time()

    from indexing.bm25_index import build_bm25_index
    build_bm25_index(csv_path, str(BM25_INDEX))

    print(f"완료: {time.time() - start:.1f}초")

    # ===== Step 3: Vector Index =====
    if openai_key:
        print("\n" + "=" * 60)
        print("Step 3: 벡터 인덱스 구축 (OpenAI Embedding)")
        print("=" * 60)
        start = time.time()

        from indexing.embedder import build_index
        # 기본은 증분 임베딩. 전체 재빌드가 필요하면 FULL_REBUILD_VECTOR=1로 실행.
        recreate = os.getenv("FULL_REBUILD_VECTOR", "0") == "1"
        build_index(csv_path, QDRANT_URL, openai_key, incremental=True, recreate=recreate)

        print(f"완료: {time.time() - start:.1f}초")
    else:
        print("\n[Skip] 벡터 인덱스: OpenAI API 키가 없어서 건너뜁니다.")
        print("  벡터 인덱스 구축: python indexing/embedder.py <csv> <output_dir> <api_key>")

    # ===== 완료 =====
    print("\n" + "=" * 60)
    print("빌드 완료!")
    print("=" * 60)
    print(f"  SQLite DB: {SQLITE_DB}")
    print(f"  BM25 Index: {BM25_INDEX}")
    if openai_key:
        print(f"  Vector Index: {VECTOR_INDEX_DIR}")

    print(f"\n서버 실행: python api/main.py")
    print(f"  OPENAI_API_KEY=... ANTHROPIC_API_KEY=... python api/main.py")


if __name__ == "__main__":
    main()
