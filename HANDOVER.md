# SlowNews 프로젝트 인수인계 메모

최종 업데이트: 2026-02-28

---

## 1. 프로젝트 개요

SlowNews(slownews.net)는 이정환 기자의 뉴스 큐레이션 레터 '슬로우레터' 데이터베이스(2023.04~현재, 약 18,000건)를 기반으로 한 뉴스 맥락 분석 서비스다.

- **메인 페이지** (slownews.net): 정적 HTML, nginx로 서빙
- **Context 페이지** (/context): Streamlit 기반 AI 분석 인터페이스 (Claude Sonnet 4.5 RAG)
- **타임라인/트렌드 페이지**: 엔티티별 보도 흐름 시각화

## 2. 인프라

### EC2 서버
- **IP**: 15.165.13.179
- **타입**: t3.large (2 vCPU, 8GB RAM)
- **SSH**: `ssh -i ~/slowletter-pipeline/slowkey.pem ubuntu@15.165.13.179`

### Systemd 서비스 (중요!)

| 서비스명 | 역할 | 상태 | 비고 |
|----------|------|------|------|
| `slownews-api` | FastAPI API 서버 (포트 8000) | ✅ 사용 중 | 재시작 대상 |
| `slownews-app` | Streamlit 프론트엔드 (포트 8510) | ✅ 사용 중 | 재시작 대상 |
| `slowletter-api` | 중복 API 서비스 | ❌ 비활성화 대상 | 잠금 충돌 원인 |
| `slowletter-ui` | 구 Streamlit 서비스 | 확인 필요 | |
| `nginx` | 리버스 프록시 | ✅ 사용 중 | |

⚠️ **주의**: `slowletter-api`와 `slownews-api`가 동일 Qdrant 폴더를 사용하므로 동시에 실행하면 잠금 충돌 발생. `slowletter-api`는 반드시 비활성화할 것.

```bash
sudo systemctl stop slowletter-api && sudo systemctl disable slowletter-api
```

### 배포 명령어

```bash
cd ~/slowletter-pipeline && git push origin main && \
ssh -i slowkey.pem ubuntu@15.165.13.179 \
  'cd ~/slowletter-pipeline && git pull origin main && \
   sudo systemctl restart slownews-api && \
   sudo systemctl restart slownews-app'
```

### 일일 업데이트
- crontab: `45 0 * * *` → `ec2_daily_update.sh` 실행

## 3. 기술 스택

### 검색 엔진
- **하이브리드 검색**: BM25 (키워드, 가중치 0.3) + 벡터 유사도 (시맨틱, 가중치 0.7)
- **점수 통합**: RRF (Reciprocal Rank Fusion), K=60
- **벡터 DB**: Qdrant (로컬 파일 모드, `/data/processed/qdrant`)
- **BM25 인덱스**: `/data/processed/bm25_index.pkl`
- **엔티티 DB**: SQLite, `/data/processed/entities.db`

### AI 에이전트
- **모델**: claude-sonnet-4-5-20250929 (temperature: 0.3, max_tokens: 4096)
- **Tool Use**: semantic_search, entity_timeline, trend_analysis, source_search
- **후처리**: `_reformat_answer()` — 1차 답변에 `###`/`•`가 없으면 2차 API 호출로 포맷 변환

### 프론트엔드
- **Streamlit**: `st.markdown()`으로 답변 렌더링
- **마크다운 처리**: `fix_answer_lines()` — 마침표 보정 + `~` → `\~` 이스케이프 (취소선 방지)

## 4. 주요 파일

| 파일 | 역할 |
|------|------|
| `agent/agent.py` | Claude RAG 에이전트 (SYSTEM_PROMPT, query, _reformat_answer) |
| `agent/tools.py` | Tool 정의 및 실행기 |
| `api/main.py` | FastAPI 엔드포인트 (/query, /search, /timeline, /trend) |
| `app.py` | Streamlit 프론트엔드 (context 페이지) |
| `search/hybrid_search.py` | 하이브리드 검색 엔진 (BM25 + 벡터 RRF) |
| `indexing/embedder.py` | 벡터 임베딩 + Qdrant VectorStore |
| `indexing/bm25_index.py` | BM25 인덱스 |
| `indexing/entity_db.py` | 엔티티 DB (인물/조직/키워드) |
| `entity_rules.json` | 엔티티 정규화 규칙 |
| `generate_web_csv.py` | 웹용 CSV 생성 (엔티티 규칙 적용) |
| `index.html` | 메인 페이지 (정적 HTML) |
| `ec2_daily_update.sh` | 일일 데이터 업데이트 스크립트 |

## 5. 에이전트 출력 포맷

### 목표: 악시오스/슬로우뉴스 스타일
```
도입 1~2문장 (소제목 없이)

### 키워드: 부연 설명
• 핵심 팩트 1
맥락 보충 서술 1~2문장.
• 핵심 팩트 2

### 왜 중요한가
• 전망 불렛
```

### 구현 방식 (시행착오 기록)
1. SYSTEM_PROMPT에 포맷 규칙 추가 → 모델이 무시
2. SYSTEM_PROMPT 맨 끝에 예시와 함께 배치 → 무시
3. 사용자 질문에 FORMAT_REMINDER 주입 → 무시
4. tool_results에 포맷 리마인더 삽입 → 무시
5. **`_reformat_answer()` 후처리** → ✅ 성공

핵심 교훈: claude-sonnet-4-5는 "~하지 마라" 규칙은 잘 따르지만, "이 형식으로 써라" 같은 긍정 포맷 지시는 복잡한 멀티턴 도구 사용 중에 잘 무시한다. 후처리(2차 API 호출)가 가장 확실한 해법이다.

### 인물 표기 규칙
- 첫 등장 시: 이름(최신 직책) — 예: 이재명(대통령)
- 이후: 이름만 — 예: 이재명

## 6. 관련 기사 (텍스트.) 섹션

- **검색**: `/search` 엔드포인트에 `top_k=50` 요청
- **필터링**: `_select_evidence(refs, max_items=50)` — 최고 점수 대비 35% 미만 컷오프
- **결과**: 관련도가 높으면 최대 50개, 낮으면 1~2개만 표시
- **점수 기준**: `hybrid_score` (RRF 통합 점수) 우선, 없으면 BM25 `score`

## 7. 엔티티 규칙 (entity_rules.json)

- 정규화: `"공정위"` → `"공정거래위원회"`, `"공정위(공정거래위원회)"` → `"공정거래위원회"`
- 제외 (빈 문자열): `"해마루 변호사"`, `"한국 증권사"`
- `generate_web_csv.py`에서 `nan` 값 필터 적용

## 8. 프론트엔드 주의사항

- **물결표(~)**: `fix_answer_lines()`에서 `~` → `\~` 이스케이프 (마크다운 취소선 방지)
- **OG 이미지**: `og-image.png?v=2` (캐시 버스팅)
- **마크다운 렌더링**: `###`으로 시작하는 줄은 마침표 보정에서 제외

## 9. 미완료/확인 필요 사항

- [ ] `slowletter-api` 서비스 비활성화 (위 명령어 실행)
- [ ] `slowletter-ui` 서비스 역할 확인 (slownews-app과 중복인지)
- [ ] /context/ OG nginx 설정: 봇 요청을 context-og.html로 라우팅 (소셜 공유용)
- [ ] `top_k=50` 변경사항 커밋 및 배포
- [ ] `~` 이스케이프 + 디버그 로그 변경사항 배포 확인
- [ ] 독립 Qdrant 서버 프로세스 (PID 248879, root) 용도 확인 — 필요 없으면 비활성화

## 10. Git 최근 커밋 히스토리

```
cfe8222 물결표 이스케이프 + 후처리 포맷 디버깅 로그 추가
954aa76 답변 후처리 포맷 변환 추가: _reformat_answer
190909b tool_results에 출력 형식 리마인더 삽입
e429ed8 사용자 질문에 출력 형식 리마인더 주입
8fd9011 에이전트 출력 형식 규칙 이동 + 인물 표기 규칙
fb5c3e9 에이전트 답변 구조 규칙 추가: Axios 스타일
782ce6e entity_rules 추가: 공정위→공정거래위원회, nan 필터
5cbd67d OG 이미지 캐시 버스팅: ?v=2
5ce56a1 og-image.png 교체
7f4eb19 에이전트 답변 구조 악시오스 스타일 소제목+불렛 추가
```
