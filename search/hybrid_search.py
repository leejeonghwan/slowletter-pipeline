"""
하이브리드 검색 엔진
- BM25 (키워드) + 벡터 (시맨틱) 검색 결합
- RRF (Reciprocal Rank Fusion) 기반 점수 통합
- 메타데이터 필터링 (날짜, 엔티티)
"""
from __future__ import annotations
from typing import Optional


class HybridSearchEngine:
    """BM25 + 벡터 하이브리드 검색"""

    def __init__(self, bm25_index, vector_store, embedder):
        self.bm25 = bm25_index
        self.vector_store = vector_store
        self.embedder = embedder

    def search(
        self,
        query: str,
        top_k: int = 10,
        initial_k: int = 30,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        entity_filter: Optional[str] = None,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> list[dict]:
        """
        하이브리드 검색을 수행합니다.

        RRF (Reciprocal Rank Fusion) 방식으로 두 검색 결과를 통합합니다.
        RRF_score = sum(1 / (k + rank_i)) for each ranking system
        """
        RRF_K = 60  # RRF 상수

        # 1. BM25 검색
        bm25_results = self.bm25.search(
            query, top_k=initial_k,
            date_start=date_start, date_end=date_end
        )

        # 2. 벡터 검색 (OPENAI_API_KEY 미설정/오류 시 BM25-only로 폴백)
        vector_results = []
        if self.embedder is not None and self.vector_store is not None:
            try:
                query_embedding = self.embedder.embed_query(query)
                vector_results = self.vector_store.search(
                    query_vector=query_embedding,
                    top_k=initial_k,
                    date_start=date_start,
                    date_end=date_end,
                    entity_filter=entity_filter,
                )
            except Exception as e:
                # 벡터 검색 실패 시에도 BM25 결과는 반환한다.
                # (예: OPENAI_API_KEY placeholder/미설정, 네트워크 오류 등)
                vector_results = []

        # 3. RRF 점수 계산
        rrf_scores = {}
        doc_data = {}

        # BM25 결과에 RRF 점수 부여
        for rank, result in enumerate(bm25_results):
            doc_id = result["doc_id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + bm25_weight / (RRF_K + rank + 1)
            doc_data[doc_id] = result

        # 벡터 결과에 RRF 점수 부여
        for rank, result in enumerate(vector_results):
            doc_id = result["doc_id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + vector_weight / (RRF_K + rank + 1)
            if doc_id not in doc_data:
                doc_data[doc_id] = result

        # 4. 날짜 필터 적용 (벡터 검색에서 필터링이 안 된 경우)
        if date_start or date_end:
            filtered_ids = set()
            for doc_id, data in doc_data.items():
                doc_date = data.get("date", "")
                if date_start and doc_date < date_start:
                    filtered_ids.add(doc_id)
                if date_end and doc_date > date_end:
                    filtered_ids.add(doc_id)
            for doc_id in filtered_ids:
                rrf_scores.pop(doc_id, None)

        # 5. 정렬 및 상위 K개 반환
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_id, score in ranked:
            data = doc_data[doc_id]
            data["hybrid_score"] = score
            results.append(data)

        return results

    def search_with_context(
        self,
        query: str,
        top_k: int = 10,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> str:
        """검색 결과를 LLM 컨텍스트용 텍스트로 반환합니다."""
        results = self.search(
            query, top_k=top_k,
            date_start=date_start, date_end=date_end
        )

        if not results:
            return "관련 문서를 찾지 못했습니다."

        context_parts = []
        for i, r in enumerate(results, 1):
            context_parts.append(
                f"[{i}] ({r['date']}) {r['title']}\n"
                f"내용: {r['content']}\n"
                f"인물: {r.get('persons', '')}\n"
                f"조직: {r.get('organizations', '')}\n"
                f"키워드: {r.get('concepts', '')}"
            )

        return "\n\n---\n\n".join(context_parts)
