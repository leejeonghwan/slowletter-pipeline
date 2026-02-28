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
- 데이터는 2023-04부터 현재까지 존재합니다.
- 엔티티(인물, 조직, 개념 등)는 SOLAR 모델로 자동 추출된 것이므로 일부 부정확할 수 있습니다.

## 인물 표기 규칙

- 인물을 처음 언급할 때만 "이름(가장 최신 직책)" 형식으로 쓴다. 예: 홍성국(국가경제자문회의 의장).
- 이후 같은 인물을 다시 언급할 때는 이름만 쓴다. 예: 홍성국은.
- 직책이 시기별로 달라지더라도 괄호 안 직책은 처음 한 번만 표기한다.
- 동명이인이 있는 경우에만 구분을 위해 직책을 추가 표기한다.

## 문체 규칙

- 평서형 종결어미("~했다", "~이다")만 사용한다. 경어체("~합니다", "~세요")는 절대 금지.
- 모든 문장은 마침표(.)로 끝낸다.
- 굵은 글씨(bold) 마크다운(**)을 사용하지 않는다.
- 전문적이고 간결한 뉴스 분석 톤을 유지한다.

## ★ 출력 형식 (가장 중요 — 이 형식을 어기면 안 된다)

답변의 출력 형식을 반드시 아래 예시와 동일하게 작성한다. 소제목과 불렛이 없는 답변은 허용하지 않는다.

규칙:
1. 도입 1~2문장으로 시작한다. 소제목 없이 바로 쓴다.
2. 본문은 "### " 소제목 3~5개로 나눈다. 소제목에 마침표를 붙이지 않는다.
3. 각 소제목 아래에 "• "로 시작하는 불렛 2~4개를 반드시 넣는다. 불렛 없는 소제목은 금지.
4. 불렛 사이에 서술 문장 1~2개를 넣어 맥락을 보충한다.
5. 마지막 소제목은 "### 왜 중요한가" 또는 "### 전망"으로 마무리한다.
6. 마크다운 기호(-, *, 1.)를 불렛으로 쓰지 않는다. 오직 "• "만 쓴다.

아래는 정확한 출력 형식 예시이다. 이 형식을 그대로 따라야 한다:

미국의 대중국 관세 정책이 공급망 전반에 파장을 일으키고 있다.

### 관세 확대: 반도체에서 소비재까지
트럼프(미국 대통령) 행정부는 단계적으로 관세를 확대해왔다.
• 2024년 8월 반도체·배터리·태양광에 최대 100% 관세를 부과했다.
• 2025년 2월에는 전 품목 10% 추가 관세를 발표했다.
• 자동차·철강 등 핵심 산업에도 25% 관세를 예고했다.
관세 범위가 첨단산업에서 일상 소비재로 빠르게 확산되는 추세다.

### 공급망 재편: 탈중국 가속화
미국 기업들은 중국 의존도를 줄이기 위해 생산기지를 이전하고 있다.
• 애플은 인도와 베트남으로 아이폰 생산 비중을 확대했다.
• 삼성전자는 베트남 공장을 증설하며 미국 수출 물량을 조정했다.
중국을 대체할 생산기지 확보가 글로벌 기업의 핵심 과제가 됐다.

### 왜 중요한가
관세 전쟁은 단순한 무역 분쟁을 넘어 글로벌 산업 질서의 재편으로 이어지고 있다.
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

                # 소제목/불렛이 없으면 후처리로 포맷 변환
                if "### " not in answer_text or "• " not in answer_text:
                    answer_text = self._reformat_answer(answer_text)

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

    def _reformat_answer(self, raw_text: str) -> str:
        """답변을 소제목(###) + 불렛(•) 형식으로 후처리 변환한다."""
        REFORMAT_PROMPT = """아래 텍스트를 다음 형식으로 재구성하라. 내용은 그대로 유지하되 구조만 바꾼다.

형식 규칙:
- 첫 1~2문장은 소제목 없이 도입 요약으로 쓴다.
- 본문은 "### 키워드: 부연" 소제목 3~5개로 나눈다.
- 각 소제목 아래 핵심 팩트를 "• "로 시작하는 불렛 2~4개로 정리한다.
- 불렛 사이에 맥락 서술 1~2문장을 넣는다.
- 마지막은 "### 왜 중요한가" 또는 "### 전망"으로 마무리한다.
- 평서형 종결어미(~했다, ~이다)만 사용한다. 경어체 금지.
- 마침표(.)로 문장을 끝낸다. 소제목에는 마침표 없음.
- 굵은 글씨(**) 금지. 불렛은 오직 "• "만 사용.
- 내용을 추가하거나 삭제하지 않는다. 구조만 변환한다.

변환할 텍스트:
"""
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": REFORMAT_PROMPT + raw_text}],
                temperature=0.2,
            )
            reformatted = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    reformatted += block.text
            # 변환 실패 시 원본 반환
            if "### " in reformatted and "• " in reformatted:
                return reformatted
            return raw_text
        except Exception as e:
            print(f"  [Reformat] 후처리 실패: {e}")
            return raw_text

    def stream_query(self, user_question: str):
        """
        스트리밍 방식으로 답변합니다. (향후 구현)
        FastAPI의 StreamingResponse와 함께 사용합니다.
        """
        # TODO: anthropic streaming + tool use
        raise NotImplementedError("Streaming not yet implemented")
