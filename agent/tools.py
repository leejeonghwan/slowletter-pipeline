"""
에이전트 도구 정의
- Claude Tool Use 형식에 맞춘 도구 스키마
- 각 도구의 실행 로직
"""
from __future__ import annotations
import json
from typing import Optional


# ===== Tool Schemas (Claude Tool Use Format) =====

TOOL_DEFINITIONS = [
    {
        "name": "semantic_search",
        "description": (
            "슬로우레터 데이터베이스에서 의미 기반 검색을 수행합니다. "
            "하이브리드 검색(키워드+벡터)으로 관련 문서를 찾습니다. "
            "특정 사실, 사건, 의견을 찾을 때 사용하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리. 구체적이고 명확하게 작성하세요.",
                },
                "date_start": {
                    "type": "string",
                    "description": "검색 시작 날짜 (YYYY-MM-DD). 생략하면 전체 기간 검색.",
                },
                "date_end": {
                    "type": "string",
                    "description": "검색 종료 날짜 (YYYY-MM-DD). 생략하면 전체 기간 검색.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "반환할 결과 수 (기본값: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "entity_timeline",
        "description": (
            "특정 인물, 조직, 키워드의 시간순 보도 흐름을 추적합니다. "
            "'윤석열 관련 보도 흐름', '민주당 이슈 타임라인' 같은 질문에 사용하세요. "
            "기간별 보도 건수와 대표 제목을 반환합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "추적할 엔티티 이름 (인물, 조직, 키워드)",
                },
                "date_start": {
                    "type": "string",
                    "description": "시작 날짜 (YYYY-MM-DD)",
                },
                "date_end": {
                    "type": "string",
                    "description": "종료 날짜 (YYYY-MM-DD)",
                },
                "granularity": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "시간 단위 (day/week/month, 기본: month)",
                    "default": "month",
                },
            },
            "required": ["entity_name"],
        },
    },
    {
        "name": "trend_analysis",
        "description": (
            "특정 키워드나 주제의 트렌드를 분석합니다. "
            "기간별 빈도 변화, 공출현 엔티티, 대표 문서를 반환합니다. "
            "'탄핵 이슈 추이', '관세 관련 트렌드' 같은 질문에 사용하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "분석할 키워드나 주제",
                },
                "date_start": {
                    "type": "string",
                    "description": "분석 시작 날짜 (YYYY-MM-DD)",
                },
                "date_end": {
                    "type": "string",
                    "description": "분석 종료 날짜 (YYYY-MM-DD)",
                },
                "granularity": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "시간 단위 (기본: month)",
                    "default": "month",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "source_search",
        "description": (
            "특정 언론사의 보도를 검색합니다. "
            "'조선일보가 탄핵에 대해 뭐라고 했어?', '한겨레의 경제 기사' 같은 질문에 사용하세요. "
            "언론사별 논조 비교에 유용합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "media_name": {
                    "type": "string",
                    "description": "언론사 이름 (조선일보, 한겨레, 경향신문, 중앙일보, 한국일보, 동아일보 등)",
                },
                "topic": {
                    "type": "string",
                    "description": "검색할 주제나 키워드 (선택사항)",
                },
                "date_start": {
                    "type": "string",
                    "description": "검색 시작 날짜",
                },
                "date_end": {
                    "type": "string",
                    "description": "검색 종료 날짜",
                },
            },
            "required": ["media_name"],
        },
    },
]


class ToolExecutor:
    """도구 실행기: 에이전트의 도구 호출을 실제 검색으로 변환합니다."""

    def __init__(self, hybrid_search, entity_db):
        self.hybrid_search = hybrid_search
        self.entity_db = entity_db
        self._last_sources = []  # 최근 검색에서 찾은 소스 문서

    @property
    def last_sources(self) -> list:
        """최근 도구 실행에서 수집된 소스 문서 반환"""
        return self._last_sources

    def clear_sources(self):
        """소스 문서 초기화 (새 질문 시작 시 호출)"""
        self._last_sources = []

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """도구를 실행하고 결과를 문자열로 반환합니다."""
        try:
            if tool_name == "semantic_search":
                return self._semantic_search(tool_input)
            elif tool_name == "entity_timeline":
                return self._entity_timeline(tool_input)
            elif tool_name == "trend_analysis":
                return self._trend_analysis(tool_input)
            elif tool_name == "source_search":
                return self._source_search(tool_input)
            else:
                return f"알 수 없는 도구: {tool_name}"
        except Exception as e:
            return f"도구 실행 오류: {str(e)}"

    def _collect_source(self, doc: dict):
        """소스 문서를 중복 없이 수집 (id 또는 date+title 기준)"""
        doc_key = doc.get("id") or f"{doc.get('date', '')}_{doc.get('title', '')}"
        existing_keys = {
            s.get("id") or f"{s.get('date', '')}_{s.get('title', '')}"
            for s in self._last_sources
        }
        if doc_key not in existing_keys:
            self._last_sources.append(doc)

    def _semantic_search(self, params: dict) -> str:
        """시맨틱 검색 실행"""
        results = self.hybrid_search.search(
            query=params["query"],
            top_k=params.get("top_k", 10),
            date_start=params.get("date_start"),
            date_end=params.get("date_end"),
        )

        if not results:
            return "관련 문서를 찾지 못했습니다."

        output_parts = [f"검색 결과 ({len(results)}건):"]
        for i, r in enumerate(results, 1):
            # 소스 수집
            self._collect_source({
                "id": r.get("id", ""),
                "date": r.get("date", ""),
                "title": r.get("title", ""),
                "snippet": (r.get("content", "") or "")[:200],
                "persons": r.get("persons", ""),
                "organizations": r.get("organizations", ""),
                "score": r.get("score", 0),
            })

            output_parts.append(
                f"\n[{i}] ({r['date']}) {r['title']}\n"
                f"내용: {r['content']}\n"
                f"인물: {r.get('persons', '') or '없음'} | "
                f"조직: {r.get('organizations', '') or '없음'} | "
                f"키워드: {r.get('concepts', '') or '없음'}"
            )

        return "\n".join(output_parts)

    def _entity_timeline(self, params: dict) -> str:
        """엔티티 타임라인 실행"""
        timeline = self.entity_db.get_entity_timeline(
            entity_name=params["entity_name"],
            date_start=params.get("date_start"),
            date_end=params.get("date_end"),
            granularity=params.get("granularity", "month"),
        )

        if not timeline:
            return f"'{params['entity_name']}'에 대한 보도 이력을 찾지 못했습니다."

        output_parts = [f"'{params['entity_name']}' 타임라인 ({len(timeline)}개 기간):"]
        for entry in timeline:
            titles_str = " / ".join(entry["titles"][:3])
            bar = "█" * min(entry["doc_count"], 30)
            output_parts.append(
                f"\n{entry['period']}: {entry['doc_count']}건 {bar}\n"
                f"  주요 제목: {titles_str}"
            )

        return "\n".join(output_parts)

    def _trend_analysis(self, params: dict) -> str:
        """트렌드 분석 실행"""
        trend = self.entity_db.get_trend_data(
            keyword=params["keyword"],
            date_start=params.get("date_start"),
            date_end=params.get("date_end"),
            granularity=params.get("granularity", "month"),
        )

        output_parts = [
            f"'{trend['keyword']}' 트렌드 분석 (총 {trend['total_count']}건):",
            "\n[기간별 빈도]"
        ]

        for entry in trend["timeline"]:
            bar = "█" * min(entry["count"], 30)
            output_parts.append(f"  {entry['period']}: {entry['count']}건 {bar}")

        if trend["co_entities"]:
            output_parts.append("\n[공출현 엔티티 (관련 인물/조직/개념)]")
            for ent in trend["co_entities"][:10]:
                output_parts.append(f"  - {ent['name']} ({ent['type']}): {ent['count']}회")

        if trend["representative_docs"]:
            output_parts.append("\n[대표 문서]")
            for doc in trend["representative_docs"][:5]:
                output_parts.append(
                    f"  ({doc['date']}) {doc['title']}\n"
                    f"    {doc['snippet']}..."
                )

        return "\n".join(output_parts)

    def _source_search(self, params: dict) -> str:
        """언론사별 검색 실행"""
        results = self.entity_db.search_by_source(
            media_name=params["media_name"],
            topic=params.get("topic"),
            date_start=params.get("date_start"),
            date_end=params.get("date_end"),
        )

        if not results:
            return f"'{params['media_name']}' 관련 문서를 찾지 못했습니다."

        output_parts = [f"'{params['media_name']}' 관련 문서 ({len(results)}건):"]
        for i, r in enumerate(results, 1):
            self._collect_source({
                "id": r.get("id", ""),
                "date": r.get("date", ""),
                "title": r.get("title", ""),
                "snippet": (r.get("content", "") or "")[:200],
                "persons": r.get("persons", ""),
                "organizations": r.get("organizations", ""),
            })

            output_parts.append(
                f"\n[{i}] ({r['date']}) {r['title']}\n"
                f"내용: {r['content']}"
            )

        return "\n".join(output_parts)
