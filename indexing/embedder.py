"""
임베딩 생성 및 벡터 인덱스 구축
- OpenAI text-embedding-3-large (3072차원)
- Qdrant 로컬 모드 (파일 기반, 서버 불필요)
"""
from __future__ import annotations
import csv
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from openai import OpenAI
except ImportError:
    print("pip install openai")
    raise

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct,
        Filter, FieldCondition, Range, MatchValue,
        PayloadSchemaType,
    )
except ImportError:
    print("pip install qdrant-client")
    raise


class SlowLetterEmbedder:
    """SlowLetter 문서 임베딩 생성기"""

    def __init__(
        self,
        openai_api_key: str,
        model: str = "text-embedding-3-large",
        dim: int = 3072,
    ):
        # OPENAI_API_KEY가 비어있거나 placeholder(한글 등)인 경우, 클라이언트가
        # Authorization 헤더 구성 과정에서 UnicodeEncodeError를 낼 수 있다.
        if not openai_api_key or not str(openai_api_key).strip():
            raise ValueError("OPENAI_API_KEY is missing")
        try:
            str(openai_api_key).encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("OPENAI_API_KEY must be ASCII (looks like a placeholder)")

        self.client = OpenAI(api_key=openai_api_key)
        self.model = model
        self.dim = dim

    def embed_texts(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """텍스트 리스트를 임베딩으로 변환합니다."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # 빈 텍스트 처리
            batch = [t if t.strip() else "빈 문서" for t in batch]

            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dim,
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)

            if i + batch_size < len(texts):
                print(f"  Embedded {i + batch_size}/{len(texts)}...")
                time.sleep(0.5)  # Rate limit 대응

        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        """단일 쿼리를 임베딩으로 변환합니다."""
        response = self.client.embeddings.create(
            model=self.model,
            input=[query],
            dimensions=self.dim,
        )
        return response.data[0].embedding


class VectorStore:
    """Qdrant 기반 벡터 저장소"""

    COLLECTION_NAME = "slowletter"

    def __init__(self, path: str):
        """로컬 파일 기반 Qdrant 클라이언트를 초기화합니다."""
        self.client = QdrantClient(path=path)

    def collection_exists(self) -> bool:
        collections = [c.name for c in self.client.get_collections().collections]
        return self.COLLECTION_NAME in collections

    def create_collection(self, dim: int = 3072, recreate: bool = False):
        """컬렉션을 생성합니다.

        recreate=True면 기존 컬렉션을 삭제 후 재생성합니다.
        """
        collections = [c.name for c in self.client.get_collections().collections]
        if self.COLLECTION_NAME in collections and recreate:
            self.client.delete_collection(self.COLLECTION_NAME)

        if self.COLLECTION_NAME in collections and not recreate:
            return

        self.client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=VectorParams(
                size=dim,
                distance=Distance.COSINE,
            ),
        )

        # 페이로드 인덱스 생성 (메타데이터 필터링용)
        for field in ["date", "persons", "organizations", "concepts"]:
            self.client.create_payload_index(
                collection_name=self.COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def upsert_documents(
        self,
        doc_ids: list[str],
        embeddings: list[list[float]],
        payloads: list[dict],
        batch_size: int = 100,
    ):
        """문서를 벡터 저장소에 삽입합니다.

        Point id는 doc_id(문서 고유키)를 그대로 사용합니다.
        """
        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_payloads = payloads[i:i + batch_size]

            points = [
                PointStruct(
                    id=did,
                    vector=emb,
                    payload={**payload, "doc_id": did},
                )
                for (did, emb, payload) in zip(batch_ids, batch_embeddings, batch_payloads)
            ]
            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=points,
            )

        print(f"Upserted {len(doc_ids)} documents to vector store")

    def get_existing_hashes(self, limit: int = 2000) -> dict:
        """현재 컬렉션에 들어있는 문서들의 content_hash를 가져옵니다."""
        existing: dict[str, str] = {}
        if not self.collection_exists():
            return existing

        next_offset = None
        while True:
            points, next_offset = self.client.scroll(
                collection_name=self.COLLECTION_NAME,
                limit=limit,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                pid = str(p.id)
                payload = p.payload or {}
                h = str(payload.get("content_hash", ""))
                if pid:
                    existing[pid] = h
            if next_offset is None:
                break
        return existing

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        entity_filter: Optional[str] = None,
    ) -> list[dict]:
        """벡터 유사도 검색을 수행합니다."""
        must_conditions = []

        if date_start or date_end:
            # 날짜 범위 필터 - Qdrant에서는 문자열 비교로 처리
            # 실제 배포시 datetime 인덱스 사용 권장
            pass

        if entity_filter:
            # 엔티티 필터 (persons, organizations, concepts 중 하나에 포함)
            must_conditions.append(
                FieldCondition(
                    key="all_entities",
                    match=MatchValue(value=entity_filter),
                )
            )

        search_filter = Filter(must=must_conditions) if must_conditions else None

        results = self.client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True,
        )

        return [
            {
                "doc_id": hit.payload.get("doc_id", ""),
                "score": hit.score,
                "date": hit.payload.get("date", ""),
                "title": hit.payload.get("title", ""),
                "content": hit.payload.get("content", ""),
                "persons": hit.payload.get("persons", ""),
                "organizations": hit.payload.get("organizations", ""),
                "concepts": hit.payload.get("concepts", ""),
            }
            for hit in results
        ]


def _hash_text(t: str) -> str:
    import hashlib

    return hashlib.sha1((t or "").encode("utf-8", errors="ignore")).hexdigest()


def build_index(
    csv_path: str,
    vector_dir: str,
    openai_api_key: str,
    incremental: bool = True,
    recreate: bool = False,
):
    """CSV에서 벡터 인덱스를 구축합니다.

    - incremental=True: 기존 Qdrant 컬렉션이 있으면 doc_id/content_hash 기준으로 증분 임베딩
    - recreate=True: 벡터 컬렉션을 삭제 후 전체 재생성

    기본은 증분(incremental)이며, 일주일에 한 번 등 필요할 때 recreate를 사용합니다.
    """
    print("=== Vector Index Build ===")

    # 0) store 준비
    store = VectorStore(vector_dir)
    store.create_collection(dim=3072, recreate=recreate)

    existing_hashes = {}
    if incremental and not recreate:
        print("Loading existing vector index (hashes)...")
        existing_hashes = store.get_existing_hashes()
        print(f"Existing points: {len(existing_hashes)}")

    # 1. CSV 로드
    print("Loading CSV...")
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"Loaded {len(rows)} documents")

    # 2. 임베딩 텍스트 준비 (제목 + 콘텐츠 + 주요 엔티티)
    texts: list[str] = []
    doc_ids: list[str] = []
    payloads: list[dict] = []

    skipped = 0
    for row in rows:
        doc_id = (row.get("ID", "") or "").strip()
        title = (row.get("title", "") or "").strip()
        content = (row.get("cleaned_content_for_api", "") or "").strip()
        if not doc_id or not content:
            continue

        persons = (row.get("solar_persons", "") or "").strip()
        orgs = (row.get("solar_organizations", "") or "").strip()
        concepts = (row.get("solar_concepts", "") or "").strip()

        embed_text = f"{title}\n{content}"
        if persons:
            embed_text += f"\n인물: {persons}"
        if concepts:
            embed_text += f"\n키워드: {concepts}"

        h = _hash_text(embed_text)
        if incremental and not recreate:
            old = existing_hashes.get(doc_id)
            if old and old == h:
                skipped += 1
                continue

        texts.append(embed_text)
        doc_ids.append(doc_id)
        payloads.append({
            "date": (row.get("date", "") or "")[:10],
            "title": title,
            "content": content,
            "persons": persons,
            "organizations": orgs,
            "concepts": concepts,
            "events": row.get("solar_events", ""),
            "locations": row.get("solar_locations", ""),
            "content_hash": h,
            "all_entities": "; ".join(filter(None, [persons, orgs, concepts])),
        })

    # 3. 임베딩 생성
    print(f"Embedding targets: {len(texts)} (skipped unchanged: {skipped})")
    if not texts:
        print("No changes. Vector index is up to date.")
        print("=== Build Complete ===")
        return

    embedder = SlowLetterEmbedder(openai_api_key)
    embeddings = embedder.embed_texts(texts)
    print(f"Generated {len(embeddings)} embeddings")

    # 4. 벡터 저장소에 삽입
    print("Upserting to vector store...")
    store.upsert_documents(doc_ids, embeddings, payloads)

    print("=== Build Complete ===")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python embedder.py <csv_path> <vector_dir> <openai_api_key>")
        sys.exit(1)
    build_index(sys.argv[1], sys.argv[2], sys.argv[3])
