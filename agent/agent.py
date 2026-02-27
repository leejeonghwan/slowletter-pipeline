"""
Claude 기반 Agentic RAG 에이전트
- Claude Tool Use로 다중 도구 활용
- 질문 유형에 따른 자동 도구 선택
- 멀티턴 추론 (필요시 추가 검색)
"""
from __future__ import annotations
import json
from typing import Optional

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    raise

from agent.tools import TOOL_DEFINITIONS, ToolExecutor


SYSTEM_PROMPT = """당신은 한국 뉴스 분석 전문가입니다. '슬로우레터(SlowLetter)' 데이터베이스를 활용하여 사용자의 질문에 답변합니다.

슬로우레터는 이정환 기자가 매일 발행하는 뉴스 큐레이션 레터로, 2023년 4월부터 현재까지 약 17,000건의 뉴스 코멘터리가 축적되어 있습니다. 한국 정치, 사회, 경제, 미디어 이슈를 다룹니다.

## 사용 가능한 도구

1. **semantic_search**: 의미 기반 문서 검색. 특정 사실, 사건, 의견을 찾을 때 사용.
2. **entity_timeline**: 인물/조직/키워드의 시간순 보도 흐름 추적.
3. **trend_analysis**: 키워드 트렌드 분석 (빈도 변화 + 공출현 엔티티 + 대표 문서).
4. **source_search**: 특정 언론사 보도 검색.

## 답변 원칙

1. **도구 선택**: 질문을 분석하여 가장 적절한 도구를 선택하세요.
   - 팩트/의견 검색 → semantic_search
   - 시간순 흐름 → entity_timeline
   - 트렌드/추이 → trend_analysis
   - 언론사별 비교 → source_search
   - 복합 질문 → 여러 도구 순차 사용

2. **날짜 추론**: 시간 범위가 명시되지 않으면 맥락에서 추론하세요.
   - "최근" → 최근 3개월
   - "작년" → 2025년
   - "탄핵 이후" → 2024-12-14 이후

3. **출처 표기**: 답변에는 반드시 출처(날짜, 제목)를 포함하세요.

4. **분석적 답변**: 단순 나열이 아닌, 맥락과 흐름을 해석한 분석적 답변을 제공하세요.

5. **한국어**: 모든 답변은 한국어로 작성하세요.

6. **보충 검색**: 첫 검색 결과가 불충분하면 쿼리를 수정하여 추가 검색하세요.

## 주의사항

- 슬로우레터는 뉴스 코멘터리이므로, 원문 자체가 기자의 해석이 포함된 텍스트입니다.
- 데이터는 2023-04부터 2026-01까지 존재합니다.
- 엔티티(인물, 조직, 개념 등)는 SOLAR 모델로 자동 추출된 것이므로 일부 부정확할 수 있습니다.
"""


class SlowLetterAgent:
    """슬로우레터 RAG 에이전트"""

    def __init__(
        self,
        anthropic_api_key: str,
        tool_executor: ToolExecutor,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 4096,
        max_tool_rounds: int = 5,
    ):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.tool_executor = tool_executor
        self.model = model
        self.max_tokens = max_tokens
        self.max_tool_rounds = max_tool_rounds

    def query(self, user_question: str, conversation_history: list = None) -> dict:
        """
        사용자 질문에 답변합니다.

        Returns:
            {
                "answer": str,          # 최종 답변
                "tool_calls": list,     # 사용된 도구 목록
                "sources": list,        # 참조된 문서
            }
        """
        messages = conversation_history or []
        messages.append({"role": "user", "content": user_question})

        tool_calls_log = []
        round_count = 0
        self.tool_executor.clear_sources()  # 소스 초기화

        while round_count < self.max_tool_rounds:
            round_count += 1

            # Claude API 호출
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
                temperature=0.3,
            )

            # 응답 처리
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # stop_reason 확인
            if response.stop_reason == "end_turn":
                # 최종 답변 추출
                answer_text = ""
                for block in assistant_content:
                    if hasattr(block, "text"):
                        answer_text += block.text

                return {
                    "answer": answer_text,
                    "tool_calls": tool_calls_log,
                    "rounds": round_count,
                    "sources": self.tool_executor.last_sources,
                }

            elif response.stop_reason == "tool_use":
                # 도구 호출 처리
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_id = block.id

                        print(f"  [Tool] {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:100]}...)")

                        # 도구 실행
                        result = self.tool_executor.execute(tool_name, tool_input)

                        tool_calls_log.append({
                            "tool": tool_name,
                            "input": tool_input,
                            "result_length": len(result),
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})

            else:
                # 예상치 못한 종료
                return {
                    "answer": "응답 생성 중 오류가 발생했습니다.",
                    "tool_calls": tool_calls_log,
                    "rounds": round_count,
                    "sources": self.tool_executor.last_sources,
                }

        return {
            "answer": "최대 도구 호출 횟수를 초과했습니다.",
            "tool_calls": tool_calls_log,
            "rounds": round_count,
            "sources": self.tool_executor.last_sources,
        }

    def stream_query(self, user_question: str):
        """
        스트리밍 방식으로 답변합니다. (향후 구현)
        FastAPI의 StreamingResponse와 함께 사용합니다.
        """
        # TODO: anthropic streaming + tool use
        raise NotImplementedError("Streaming not yet implemented")
